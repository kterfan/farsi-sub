"""Combine the word streams of two models.

Neither model alone was right on the test clip: large-v3 looped a phrase twice,
while the Persian fine-tune dropped a whole sentence. Their mistakes did not
overlap, which is exactly the case where merging helps.

The rule is deliberately conservative: one model stays in charge of the whole
transcript, and the other is only consulted for stretches the first left empty.
Interleaving both word by word would produce sentences neither model said.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..models import Word

# A hole shorter than this is just the pause between two words.
MIN_HOLE = 0.8
# Ignore anything the filler model is unsure about.
MIN_FILL_PROBABILITY = 0.5


@dataclass
class MergeReport:
    holes: int = 0
    filled: int = 0
    words_added: int = 0
    seconds_recovered: float = 0.0


def find_holes(words: list[Word], duration: float, min_hole: float = MIN_HOLE) -> list[tuple[float, float]]:
    """Stretches of the timeline with no words in them."""
    holes: list[tuple[float, float]] = []
    cursor = 0.0
    for word in words:
        if word.start - cursor >= min_hole:
            holes.append((cursor, word.start))
        cursor = max(cursor, word.end)
    if duration - cursor >= min_hole:
        holes.append((cursor, duration))
    return holes


def words_inside(words: list[Word], start: float, end: float) -> list[Word]:
    return [w for w in words if w.start >= start - 0.05 and w.end <= end + 0.05]


def merge_streams(
    primary: list[Word],
    secondary: list[Word],
    *,
    duration: float | None = None,
    min_hole: float = MIN_HOLE,
) -> tuple[list[Word], MergeReport]:
    """Fill the primary stream's holes with words from the secondary one."""
    report = MergeReport()
    if not secondary:
        return primary, report
    if not primary:
        return secondary, report

    span = duration or max(primary[-1].end, secondary[-1].end)
    holes = find_holes(primary, span, min_hole)
    report.holes = len(holes)

    additions: list[Word] = []
    for start, end in holes:
        candidates = [
            w
            for w in words_inside(secondary, start, end)
            if w.probability >= MIN_FILL_PROBABILITY
        ]
        if not candidates:
            continue
        # Only bother if the other model really has something to say here.
        spoken = candidates[-1].end - candidates[0].start
        if spoken < min_hole * 0.5:
            continue
        additions.extend(candidates)
        report.filled += 1
        report.words_added += len(candidates)
        report.seconds_recovered += spoken

    if not additions:
        return primary, report

    merged = sorted(primary + additions, key=lambda w: (w.start, w.end))
    return merged, report


# --- repetition arbitration -------------------------------------------------
#
# Whisper sometimes emits the same phrase two or three times, seconds apart,
# when only one was spoken. Timing alone cannot tell that from a speaker
# repeating themselves for emphasis -- but a second model can: if it heard the
# phrase once where the first heard it three times, the extra copies are the
# first model's invention.

ARBITRATION_PHRASE = 4  # shortest phrase worth cross-checking
ARBITRATION_WINDOW = 25.0  # seconds; copies further apart are treated separately


def _phrase_key(words: list[Word], start: int, length: int) -> tuple[str, ...]:
    return tuple(w.text.strip("،؛:.!؟…") for w in words[start : start + length])


def _occurrences(words: list[Word], key: tuple[str, ...]) -> list[int]:
    length = len(key)
    return [
        i
        for i in range(len(words) - length + 1)
        if _phrase_key(words, i, length) == key
    ]


def arbitrate_repeats(
    primary: list[Word],
    secondary: list[Word],
    *,
    phrase_length: int = ARBITRATION_PHRASE,
    window: float = ARBITRATION_WINDOW,
) -> tuple[list[Word], int]:
    """Drop copies of a phrase the second model did not hear that many times."""
    if not secondary or len(primary) < phrase_length * 2:
        return primary, 0

    drop: set[int] = set()
    seen: set[tuple[str, ...]] = set()

    for i in range(len(primary) - phrase_length + 1):
        key = _phrase_key(primary, i, phrase_length)
        if key in seen or any(index in drop for index in range(i, i + phrase_length)):
            continue
        seen.add(key)

        hits = _occurrences(primary, key)
        if len(hits) < 2:
            continue
        # Only consider copies that sit close together in time.
        cluster = [h for h in hits if primary[h].start - primary[hits[0]].start <= window]
        if len(cluster) < 2:
            continue

        start_time = primary[cluster[0]].start - 3.0
        end_time = primary[cluster[-1]].end + 3.0
        heard = [
            h
            for h in _occurrences(secondary, key)
            if start_time <= secondary[h].start <= end_time
        ]
        allowed = max(1, len(heard))
        for extra in cluster[allowed:]:
            drop.update(range(extra, extra + phrase_length))

    if not drop:
        return primary, 0
    return [w for i, w in enumerate(primary) if i not in drop], len(drop)
