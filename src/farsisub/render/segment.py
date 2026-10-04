"""Turn a WordStream into subtitle cues.

Two stages, deliberately separate:

    group_words()  -> decides WHERE to cut, using timing and reading-speed rules
    render_cues()  -> turns each group into final text and wraps it into lines

Keeping them apart means the Persian text rules never influence where a cut
lands, and a cut is never re-decided because a dot got removed.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Sequence

from ..config import StyleProfile, TextRules
from ..models import Cue, Project, Word
from ..text.normalize import apply_punctuation_rules, normalize_text
from .breaks import ends_clause, ends_sentence as _ends_sentence
from .breaks import (
    COST_PLAIN,
    is_clitic,
    is_light_verb,
    is_suffix,
    token_break_cost,
    word_break_cost,
)


def _bad_cue_start(text: str) -> bool:
    """A cue may not open on a word that leans on the one before it."""
    return is_suffix(text) or is_clitic(text)


@dataclass
class WordGroup:
    start: int  # inclusive index into the word list
    end: int  # exclusive
    continues: bool = False  # sentence runs on into the next group
    solo_keyword: bool = False


def _text_len(words: list[Word], start: int, end: int) -> int:
    """Characters a group would occupy, counting the joining spaces."""
    if end <= start:
        return 0
    return sum(len(w.text) for w in words[start:end]) + (end - start - 1)


def _split_sentences(words: list[Word]) -> list[tuple[int, int]]:
    spans: list[tuple[int, int]] = []
    begin = 0
    for i, w in enumerate(words):
        if _ends_sentence(w.text):
            spans.append((begin, i + 1))
            begin = i + 1
    if begin < len(words):
        spans.append((begin, len(words)))
    return spans


def _split_clauses(words: list[Word], start: int, end: int) -> list[tuple[int, int]]:
    """Cut a sentence at its clause marks.

    A clause is the natural unit of a subtitle: "اینکه همه چی رو بلد باشی،"
    reads as one thought, while any cut inside it leaves a stub on screen.
    """
    spans: list[tuple[int, int]] = []
    begin = start
    for i in range(start, end):
        if ends_clause(words[i].text) and i + 1 < end:
            spans.append((begin, i + 1))
            begin = i + 1
    if begin < end:
        spans.append((begin, end))
    return spans


def _fits(words: list[Word], start: int, end: int, profile: StyleProfile) -> bool:
    """Does this candidate group satisfy every readability rule?"""
    if end <= start:
        return False
    capacity = profile.max_lines * profile.max_chars_per_line
    chars = _text_len(words, start, end)
    if chars > capacity:
        return False
    duration = words[end - 1].end - words[start].start
    if duration > profile.max_duration:
        return False
    # Reading speed is measured against how long the cue will actually be on
    # screen, which is never shorter than min_duration. Ignoring that would
    # shatter fast speech into one-word cues -- and a one-word cue is not more
    # readable, just more annoying.
    display = max(duration, profile.min_duration)
    if chars / display > profile.max_cps and (end - start) > 1:
        return False
    return True


def _best_break(words: list[Word], start: int, limit: int) -> int:
    """Pick the cheapest place to cut inside the window.

    Cutting one word early at a clause boundary beats cutting at the last
    possible word in the middle of a verb phrase, so a small distance penalty
    keeps cues full without overriding grammar.
    """
    half = start + max(1, (limit - start) // 2)
    best_index = limit
    best_cost = word_break_cost(words, limit)
    for i in range(limit - 1, half - 1, -1):
        cost = word_break_cost(words, i) + (limit - i) * 0.4
        if cost < best_cost:
            best_cost, best_index = cost, i
    return best_index


def _adjust_break(
    words: list[Word], start: int, cut: int, end: int, profile: StyleProfile
) -> int:
    """Move a cut so the next cue does not open on a clitic or suffix.

    Backwards first, but never far enough to leave a stub behind; if that fails,
    forwards, as long as the group still fits.
    """
    if cut >= end or not _bad_cue_start(words[cut].text):
        return cut

    back = cut
    while back > start + 1 and _bad_cue_start(words[back].text):
        back -= 1
    if back > start + 1:
        span = words[back - 1].end - words[start].start
        if span >= profile.min_duration:
            return back

    forward = cut
    while forward < end and _bad_cue_start(words[forward].text):
        if not _room_for(words, start, forward + 1, profile):
            break
        forward += 1
    if forward < end and not _bad_cue_start(words[forward].text):
        return forward

    return cut


def _chunk_span(words: list[Word], start: int, end: int, profile: StyleProfile) -> list[WordGroup]:
    """Cut one sentence span into groups that each satisfy the rules."""
    groups: list[WordGroup] = []
    i = start
    while i < end:
        j = i + 1
        # Grow greedily while the rules still hold.
        while j < end and _fits(words, i, j + 1, profile):
            j += 1
        if profile.mode == "reels" and j - i > profile.phrase_max_words:
            j = i + profile.phrase_max_words
        if j < end:
            j = _best_break(words, i, j)
        j = _adjust_break(words, i, j, end, profile)
        groups.append(WordGroup(start=i, end=j))
        i = j

    for g in groups:
        g.continues = not _ends_sentence(words[g.end - 1].text)
    return groups


def _merge_clauses(
    words: list[Word], groups: list[WordGroup], profile: StyleProfile
) -> list[WordGroup]:
    """Join neighbouring clauses when they still fit comfortably.

    Clause-sized cues alone leave the smart profile choppy: "تو ممکنه خرید
    کنی،" and "بحران رو جمع کنی،" belong on one screen. Reels wants them
    apart, so it opts out.
    """
    if profile.mode == "reels":
        return groups

    merged: list[WordGroup] = []
    for g in groups:
        if (
            merged
            and not g.solo_keyword
            and not merged[-1].solo_keyword
            # Do not let one cue carry the end of a sentence and the start of
            # the next: that reads as two thoughts glued together.
            and not _ends_sentence(words[merged[-1].end - 1].text)
            and _fits(words, merged[-1].start, g.end, profile)
        ):
            merged[-1].end = g.end
            merged[-1].continues = g.continues
            continue
        merged.append(g)
    return merged


def _merge_short(
    words: list[Word], groups: list[WordGroup], profile: StyleProfile
) -> list[WordGroup]:
    """Fold a cue that is too brief to read into the next one."""
    merged: list[WordGroup] = []
    for g in groups:
        if (
            merged
            and not g.solo_keyword
            and not merged[-1].solo_keyword
            # A finished sentence keeps its own cue however short it is.
            and not _ends_sentence(words[merged[-1].end - 1].text)
            and (words[g.end - 1].end - words[g.start].start) < profile.min_duration
            and _room_for(words, merged[-1].start, g.end, profile)
        ):
            merged[-1].end = g.end
            merged[-1].continues = g.continues
            continue
        merged.append(g)
    return merged


def _room_for(words: list[Word], start: int, end: int, profile: StyleProfile) -> bool:
    """Relaxed check used when rescuing an orphan: size and duration only.

    Reading speed is dropped here on purpose. A merged cue that reads slightly
    fast still beats a cue holding one word for a third of a second.
    """
    capacity = profile.max_lines * profile.max_chars_per_line
    if _text_len(words, start, end) > capacity:
        return False
    return (words[end - 1].end - words[start].start) <= profile.max_duration


def _is_orphan(words: list[Word], g: WordGroup, profile: StyleProfile) -> bool:
    if g.solo_keyword:
        return False  # a keyword is meant to stand alone
    if g.end - g.start > 1:
        return False
    span = words[g.end - 1].end - words[g.start].start
    return span < profile.min_duration


def _merge_orphans(
    words: list[Word], groups: list[WordGroup], profile: StyleProfile
) -> list[WordGroup]:
    """A lone word flashing on screen looks broken; glue it to a neighbour.

    Backwards first (it keeps reading order intact); forwards when the previous
    cue is a solo keyword that must not be touched.
    """
    merged: list[WordGroup] = []
    pending: WordGroup | None = None

    for g in groups:
        if pending is not None:
            if not g.solo_keyword and _room_for(words, pending.start, g.end, profile):
                g.start = pending.start
            else:
                merged.append(pending)
            pending = None

        if not _is_orphan(words, g, profile) or not merged:
            merged.append(g)
            continue

        prev = merged[-1]
        if not prev.solo_keyword and _room_for(words, prev.start, g.end, profile):
            prev.end = g.end
            prev.continues = g.continues
        else:
            pending = g  # try to attach it to the next group instead

    if pending is not None:
        merged.append(pending)
    return merged


def _apply_keyword_solos(
    words: list[Word], groups: list[WordGroup], profile: StyleProfile
) -> list[WordGroup]:
    """Reels profile: a keyword gets the screen to itself."""
    if not profile.keyword_solo:
        return groups
    # Below this the word is a flash rather than a word, even with the hold
    # applied later in _timings, so it stays inline instead.
    readable_floor = 0.25

    # A fragment left beside a solo keyword still has to be readable, so the
    # split only happens when both sides survive it. One solo per group keeps
    # the rhythm from turning into a stroboscope.
    min_fragment = profile.min_duration * 0.6

    def fragment_ok(start: int, end: int) -> bool:
        if end <= start:
            return True
        return (words[end - 1].end - words[start].start) >= min_fragment

    out: list[WordGroup] = []
    for g in groups:
        cursor = g.start
        used_solo = False
        for i in range(g.start, g.end):
            if not words[i].keyword or used_solo:
                continue
            if not fragment_ok(cursor, i) or not fragment_ok(i + 1, g.end):
                continue
            screen_time = (
                words[i + 1].start if i + 1 < len(words) else words[i].end
            ) - words[i].start
            if screen_time < readable_floor:
                continue
            if i + 1 < len(words) and is_suffix(words[i + 1].text):
                continue
            if is_suffix(words[i].text):
                continue
            if i > cursor:
                out.append(WordGroup(cursor, i, continues=True))
            out.append(WordGroup(i, i + 1, continues=i + 1 < g.end, solo_keyword=True))
            cursor = i + 1
            used_solo = True
        if cursor < g.end:
            out.append(WordGroup(cursor, g.end, continues=g.continues))
        elif out:
            out[-1].continues = g.continues
    return out


# Word mode: a word shown for less than this is a flicker, not a word.
WORD_MIN_SCREEN = 0.25
WORD_MAX_GROUP = 3


def _word_groups(words: list[Word], profile: StyleProfile) -> list[WordGroup]:
    """One word per cue, in step with the voice.

    A few words cannot stand alone and ride with the one before them: a
    detached suffix ("ها", "تر"), an enclitic ("رو", "و"), the light verb of a
    compound ("صحبت کنم"). So does a word spoken too fast to be read on its
    own. A group never grows past three words or one line.
    """
    groups: list[WordGroup] = []
    for i, word in enumerate(words):
        screen = (words[i + 1].start if i + 1 < len(words) else word.end) - word.start
        leans = is_suffix(word.text) or is_clitic(word.text) or is_light_verb(word.text)
        if groups and not _ends_sentence(words[i - 1].text):
            last = groups[-1]
            previous_screen = word.start - words[last.start].start
            too_fast = screen < WORD_MIN_SCREEN or previous_screen < WORD_MIN_SCREEN
            fits = _text_len(words, last.start, i + 1) <= profile.max_chars_per_line
            # A leaning word always rides along (alone it would read as a
            # broken line); a merely fast one only while the group is small.
            if fits and (leans or (too_fast and last.end - last.start < WORD_MAX_GROUP)):
                last.end = i + 1
                continue
        groups.append(WordGroup(start=i, end=i + 1))
    for g in groups:
        g.continues = not _ends_sentence(words[g.end - 1].text)
    return groups


def group_words(words: list[Word], profile: StyleProfile) -> list[WordGroup]:
    if not words:
        return []
    if profile.mode == "word":
        return _word_groups(words, profile)
    groups: list[WordGroup] = []
    for start, end in _split_sentences(words):
        for clause_start, clause_end in _split_clauses(words, start, end):
            if _fits(words, clause_start, clause_end, profile):
                groups.append(WordGroup(clause_start, clause_end))
            else:
                groups.extend(_chunk_span(words, clause_start, clause_end, profile))
    groups = _merge_clauses(words, groups, profile)
    groups = _apply_keyword_solos(words, groups, profile)
    groups = _merge_orphans(words, groups, profile)
    groups = _merge_short(words, groups, profile)
    return groups


def wrap_lines(text: str, profile: StyleProfile) -> list[str]:
    """Split a cue into lines at the most natural place, not the last possible one.

    Greedy filling produced "بوهران رو جمع / کنی،" -- a verb torn in half. The
    line break is chosen by the same cost table the cue splitter uses, with a
    mild preference for balanced halves.
    """
    tokens = text.split()
    if not tokens:
        return []
    if len(text) <= profile.max_chars_per_line:
        return [text]

    if profile.max_lines >= 2:
        best_index = None
        best_cost = float("inf")
        for i in range(1, len(tokens)):
            first = " ".join(tokens[:i])
            second = " ".join(tokens[i:])
            if len(first) > profile.max_chars_per_line:
                break
            if len(second) > profile.max_chars_per_line:
                continue  # the tail is still too long; keep moving right
            imbalance = abs(len(first) - len(second)) / profile.max_chars_per_line
            cost = token_break_cost(tokens, i) + imbalance * COST_PLAIN * 2
            if min(len(first), len(second)) < 8:
                cost += COST_PLAIN * 3  # a stub line looks like a bug
            if cost < best_cost:
                best_cost, best_index = cost, i
        if best_index is not None:
            return [" ".join(tokens[:best_index]), " ".join(tokens[best_index:])]

    # Nothing fits in max_lines; fall back to filling greedily.
    lines: list[str] = []
    current: list[str] = []
    for token in tokens:
        candidate = " ".join(current + [token])
        if current and len(candidate) > profile.max_chars_per_line:
            lines.append(" ".join(current))
            current = [token]
        else:
            current.append(token)
    if current:
        lines.append(" ".join(current))
    if len(lines) > profile.max_lines:
        head = lines[: profile.max_lines - 1]
        head.append(" ".join(lines[profile.max_lines - 1 :]))
        lines = head
    return lines


# A solo keyword may stay on screen after its audio ends, pushing the next cue
# slightly late. Up to a third of a second of caption lag is imperceptible, and
# it is the difference between a readable word and a flash.
KEYWORD_HOLD = 0.35


def timings_for_spans(
    spans: Sequence[tuple[float, float, bool]], profile: StyleProfile
) -> list[tuple[float, float]]:
    """On-screen times for cues, from (first word start, last word end, solo keyword).

    Shared by the style renderer and by lines shaped in the editor, so both
    get the same minimum duration, gap and keyword hold.
    """
    times: list[tuple[float, float]] = []
    earliest_start = 0.0

    for index, (first, last, solo_keyword) in enumerate(spans):
        start = max(first, earliest_start)
        end = max(last, start + 0.2)
        if end - start < profile.min_duration:
            end = start + profile.min_duration

        if index + 1 < len(spans):
            natural_next = spans[index + 1][0]
            hold = KEYWORD_HOLD if solo_keyword else 0.0
            end = min(end, max(start + 0.2, natural_next + hold - profile.min_gap))

        times.append((start, end))
        earliest_start = end + profile.min_gap

    return times


def _timings(
    words: list[Word], groups: list[WordGroup], profile: StyleProfile
) -> list[tuple[float, float]]:
    return timings_for_spans(
        [(words[g.start].start, words[g.end - 1].end, g.solo_keyword) for g in groups],
        profile,
    )


def _all_keywords(words: list[Word], g: WordGroup, profile: StyleProfile) -> bool:
    """Word mode: a cue whose only real word is a keyword gets the keyword colour."""
    if profile.mode != "word":
        return False
    host = [w for w in words[g.start : g.end] if not (is_suffix(w.text) or is_clitic(w.text))]
    return bool(host) and all(w.keyword for w in host)


def render_cues(
    words: list[Word],
    groups: list[WordGroup],
    profile: StyleProfile,
    rules: TextRules,
) -> list[Cue]:
    cues: list[Cue] = []
    times = _timings(words, groups, profile)
    for (start, end), g in zip(times, groups):
        raw = " ".join(w.text for w in words[g.start : g.end])
        text = normalize_text(raw, rules)
        text = apply_punctuation_rules(text, rules, continues=g.continues)
        if not text:
            continue
        cues.append(
            Cue(
                index=len(cues) + 1,
                start=start,
                end=end,
                lines=wrap_lines(text, profile),
                word_range=(g.start, g.end),
                keyword=g.solo_keyword or _all_keywords(words, g, profile),
            )
        )
    return cues


def build_cues(words: list[Word], profile: StyleProfile, rules: TextRules) -> list[Cue]:
    """One call from WordStream to finished cues."""
    return render_cues(words, group_words(words, profile), profile, rules)


def cues_from_lines(
    lines: Sequence[tuple[Sequence[Word], str]], profile: StyleProfile
) -> list[Cue]:
    """Cues for lines shaped by hand: the text as typed, the timing from the words.

    The text is left exactly as the user wrote it -- no normalising, no
    punctuation rules -- but it is wrapped, and timed by the same rules as a
    rendered style, so a hand-edited subtitle does not flash one-word lines
    for a fifth of a second.
    """
    kept = [(list(words), text.strip()) for words, text in lines if words and text.strip()]
    spans = [
        (
            words[0].start,
            words[-1].end,
            profile.keyword_solo and len(words) == 1 and bool(words[0].keyword),
        )
        for words, _ in kept
    ]
    # The colour follows the keyword in reels and word mode; the hold after
    # it (the third span field) only in reels, or every word after a keyword
    # would start a third of a second late.
    coloured = [
        (profile.keyword_solo or profile.mode == "word")
        and len(words) == 1
        and bool(words[0].keyword)
        for words, _ in kept
    ]
    return [
        Cue(index=index, start=start, end=end, lines=wrap_lines(text, profile), keyword=colour)
        for index, ((_, text), (start, end), colour) in enumerate(
            zip(kept, timings_for_spans(spans, profile), coloured), start=1
        )
    ]


def project_cues(project: Project, profile: StyleProfile, rules: TextRules) -> list[Cue]:
    """The cues a project stands for: its edited lines if it has any, else the style."""
    if not project.lines:
        return build_cues(project.words, profile, rules)
    stream = project.words
    lines = [
        ([stream[i] for i in line.words if 0 <= i < len(stream)], line.text)
        for line in project.lines
    ]
    return cues_from_lines(lines, profile)
