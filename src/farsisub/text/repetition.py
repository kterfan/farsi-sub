"""Remove the phrases Whisper repeats when it loops.

Measured on a real clip, large-v3 produced:

    نه صرفاً کارای بیشتری انجام بدی صرفاً کارای بیشتری انجام بدی

The second copy is not in the audio. Whisper's decoder gets stuck and emits the
same phrase again, usually with squeezed or overlapping timings.

Only immediate repeats are removed, and only when the timing says the words
cannot both have been spoken -- a speaker really can say "نه نه" twice.
"""

from __future__ import annotations

from ..models import Word

MIN_PHRASE = 2  # shortest repeated phrase worth removing
MAX_PHRASE = 12  # longest to look for
# A genuine repeat leaves a pause. A looped one starts almost immediately or
# overlaps what came before.
MAX_GAP_FOR_LOOP = 0.35


def _texts(words: list[Word], start: int, length: int) -> list[str]:
    return [w.text.strip("،؛:.!؟…") for w in words[start : start + length]]


# A four-word phrase repeated verbatim, back to back, is a decoder loop
# whatever the timings say. People do not do that.
LONG_PHRASE = 4
MAX_GAP_FOR_LONG_LOOP = 1.5


def _is_loop(words: list[Word], first: int, second: int, length: int) -> bool:
    """Same words twice in a row, with no room to have said them twice."""
    if _texts(words, first, length) != _texts(words, second, length):
        return False
    gap = words[second].start - words[second - 1].end
    if length >= LONG_PHRASE:
        return gap <= MAX_GAP_FOR_LONG_LOOP
    if gap > MAX_GAP_FOR_LOOP:
        return False
    # The repeat is usually faster than the original: a real second delivery
    # takes about as long.
    original = words[first + length - 1].end - words[first].start
    repeat = words[second + length - 1].end - words[second].start
    return repeat <= original * 1.35


def drop_repetitions(words: list[Word]) -> tuple[list[Word], int]:
    """Return the cleaned stream and how many words were dropped."""
    if len(words) < MIN_PHRASE * 2:
        return words, 0

    keep = [True] * len(words)
    i = 0
    removed = 0
    while i < len(words):
        if not keep[i]:
            i += 1
            continue
        # Longest repeat first: "a b c a b c" should lose three words, not one.
        for length in range(min(MAX_PHRASE, (len(words) - i) // 2), MIN_PHRASE - 1, -1):
            second = i + length
            if second + length > len(words):
                continue
            if _is_loop(words, i, second, length):
                for j in range(second, second + length):
                    keep[j] = False
                removed += length
                i = second + length - 1
                break
        i += 1

    return [w for w, ok in zip(words, keep) if ok], removed
