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


def _phrase_index(words: list[Word], length: int) -> dict[tuple[str, ...], list[int]]:
    """Every phrase of `length` words -> where it starts, in one pass.

    Searching the whole stream again for each phrase made arbitration
    quadratic: 7 s for 4000 words, well over a minute for a 90 minute video.
    """
    texts = [w.text.strip("،؛:.!؟…") for w in words]
    index: dict[tuple[str, ...], list[int]] = {}
    for i in range(len(texts) - length + 1):
        index.setdefault(tuple(texts[i : i + length]), []).append(i)
    return index


def _clusters(words: list[Word], hits: list[int], window: float) -> list[list[int]]:
    """Group the copies of one phrase that sit close together in time."""
    groups: list[list[int]] = []
    for hit in hits:
        if groups and words[hit].start - words[groups[-1][0]].start <= window:
            groups[-1].append(hit)
        else:
            groups.append([hit])
    return groups


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

    primary_index = _phrase_index(primary, phrase_length)
    secondary_index = _phrase_index(secondary, phrase_length)
    drop: set[int] = set()

    # Keys come out in the order they first appear, so phrases are judged in
    # reading order, as before.
    for key, hits in primary_index.items():
        if len(hits) < 2:
            continue
        # Nothing left to judge once every copy is already gone. Copies that
        # were dropped stay in `hits` otherwise, so the words they leave
        # behind are taken along with them.
        if all(any(i in drop for i in range(h, h + phrase_length)) for h in hits):
            continue

        # Every cluster counts, not only the first: a loop twenty minutes in
        # is as invented as one in the opening seconds.
        for cluster in _clusters(primary, hits, window):
            if len(cluster) < 2:
                continue
            start_time = primary[cluster[0]].start - 3.0
            end_time = primary[cluster[-1]].end + 3.0
            heard = [
                h
                for h in secondary_index.get(key, [])
                if start_time <= secondary[h].start <= end_time
            ]
            allowed = max(1, len(heard))
            for extra in cluster[allowed:]:
                drop.update(range(extra, extra + phrase_length))

    if not drop:
        return primary, 0
    return [w for i, w in enumerate(primary) if i not in drop], len(drop)
