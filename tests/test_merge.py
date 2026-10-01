"""Repetition removal and two-model merging.

Both behaviours come from one measured clip: large-v3 said
"صرفاً کارای بیشتری انجام بدی" twice in a row, and the Persian fine-tune
dropped a sentence the first model had.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.models import Word  # noqa: E402
from farsisub.render.merge import arbitrate_repeats, find_holes, merge_streams  # noqa: E402
from farsisub.text.repetition import drop_repetitions  # noqa: E402


def stream(spec: list[tuple[str, float, float]], probability: float = 0.9) -> list[Word]:
    return [Word(text=t, start=s, end=e, probability=probability) for t, s, e in spec]


def phrase(words: list[str], start: float, step: float = 0.3, p: float = 0.9) -> list[Word]:
    out = []
    t = start
    for w in words:
        out.append(Word(text=w, start=t, end=t + step * 0.8, probability=p))
        t += step
    return out


# --------------------------------------------------------------- repetitions


def test_looped_phrase_is_removed():
    words = phrase(["صرفاً", "کارای", "بیشتری", "انجام", "بدی"], 0.0)
    words += phrase(["صرفاً", "کارای", "بیشتری", "انجام", "بدی"], 1.5)
    cleaned, removed = drop_repetitions(words)
    assert removed == 5
    assert [w.text for w in cleaned] == ["صرفاً", "کارای", "بیشتری", "انجام", "بدی"]


def test_a_phrase_looped_three_times_keeps_one_copy():
    # Only the second copy used to go; the third was compared with the
    # removed one and survived, so the subtitle still said it twice.
    one = ["صرفاً", "کارای", "بیشتری", "انجام"]
    words = phrase(one, 0.0) + phrase(one, 1.2) + phrase(one, 2.4)
    cleaned, removed = drop_repetitions(words)
    assert removed == 8
    assert [w.text for w in cleaned] == one


def test_a_real_pause_between_repeats_is_kept():
    # Someone genuinely saying the same thing twice leaves a gap.
    words = phrase(["نه", "لزوماً"], 0.0)
    words += phrase(["نه", "لزوماً"], 5.0)
    cleaned, removed = drop_repetitions(words)
    assert removed == 0
    assert len(cleaned) == 4


def test_single_repeated_word_is_left_alone():
    words = phrase(["نه", "نه", "اصلاً"], 0.0)
    cleaned, removed = drop_repetitions(words)
    assert removed == 0
    assert len(cleaned) == 3


def test_empty_and_tiny_streams_survive():
    assert drop_repetitions([]) == ([], 0)
    single = phrase(["سلام"], 0.0)
    assert drop_repetitions(single)[1] == 0


# --------------------------------------------------------------------- merge


def test_holes_are_found_where_nothing_was_transcribed():
    words = stream([("یک", 0.0, 0.5), ("دو", 4.0, 4.5)])
    holes = find_holes(words, duration=6.0)
    assert holes[0][0] < 1.0 and holes[0][1] > 3.0  # the gap in the middle
    assert any(start >= 4.4 for start, _ in holes)  # and the tail


def test_second_model_fills_a_hole_the_first_left():
    primary = stream([("جمله", 0.0, 0.5), ("اول", 0.5, 1.0), ("پایان", 6.0, 6.5)])
    secondary = stream(
        [("میتونی", 2.0, 2.6), ("بدون", 2.6, 3.1), ("عذاب", 3.1, 3.8), ("وجدان", 3.8, 4.4)]
    )
    merged, report = merge_streams(primary, secondary, duration=7.0)
    texts = [w.text for w in merged]
    assert "عذاب" in texts and "وجدان" in texts
    assert report.words_added == 4
    # the original words keep their order and timing
    assert texts[:2] == ["جمله", "اول"]
    assert merged == sorted(merged, key=lambda w: w.start)


def test_merge_does_not_touch_places_the_first_model_covered():
    primary = phrase(["یک", "دو", "سه", "چهار"], 0.0)
    secondary = phrase(["پنج", "شش", "هفت", "هشت"], 0.0)
    merged, report = merge_streams(primary, secondary, duration=2.0)
    assert [w.text for w in merged] == ["یک", "دو", "سه", "چهار"]
    assert report.words_added == 0


def test_low_confidence_filler_is_ignored():
    primary = stream([("شروع", 0.0, 0.5), ("پایان", 6.0, 6.5)])
    secondary = stream([("همهمه", 2.0, 3.5)], probability=0.2)
    merged, report = merge_streams(primary, secondary, duration=7.0)
    assert report.words_added == 0
    assert len(merged) == 2


def test_merge_survives_an_empty_second_model():
    primary = stream([("تنها", 0.0, 0.5)])
    merged, report = merge_streams(primary, [], duration=1.0)
    assert merged == primary
    assert report.words_added == 0


def test_long_phrase_repeat_is_a_loop_even_with_a_pause():
    # Measured: large-v3 repeated a five word phrase with a gap wide enough to
    # fool the strict rule, and the merge then spliced the copy back in.
    words = phrase(["نه", "اینکه", "صرفاً", "کارای", "بیشتری"], 0.0)
    words += phrase(["نه", "اینکه", "صرفاً", "کارای", "بیشتری"], 2.5)
    cleaned, removed = drop_repetitions(words)
    assert removed == 5
    assert [w.text for w in cleaned] == ["نه", "اینکه", "صرفاً", "کارای", "بیشتری"]


def test_second_model_settles_how_many_times_a_phrase_was_said():
    said_once = phrase(["نه", "اینکه", "صرفاً", "کارای", "بیشتری"], 0.0)
    primary = list(said_once)
    primary += phrase(["نه", "اینکه", "صرفاً", "کارای", "بیشتری"], 6.0)
    primary += phrase(["نه", "اینکه", "صرفاً", "کارای", "بیشتری"], 12.0)
    secondary = phrase(["نه", "اینکه", "صرفاً", "کارای", "بیشتری"], 0.0)

    cleaned, dropped = arbitrate_repeats(primary, secondary)
    # Exactly one clean copy survives; the arbitration also takes the orphan
    # tail words the dropped copies leave behind.
    assert dropped == len(primary) - len(said_once)
    assert [w.text for w in cleaned] == [w.text for w in said_once]


def test_arbitration_keeps_repeats_both_models_agree_on():
    words = phrase(["این", "خیلی", "مهمه", "واقعاً"], 0.0)
    words += phrase(["این", "خیلی", "مهمه", "واقعاً"], 8.0)
    cleaned, dropped = arbitrate_repeats(list(words), list(words))
    assert dropped == 0
    assert len(cleaned) == len(words)


def test_arbitration_judges_a_loop_late_in_the_file_too():
    # The phrase is said once early on; much later the first model loops it.
    # Only the first cluster of each phrase used to be looked at.
    line = ["این", "خیلی", "مهمه", "واقعاً"]
    primary = phrase(line, 0.0) + phrase(line, 300.0) + phrase(line, 306.0)
    secondary = phrase(line, 0.0) + phrase(line, 300.0)
    cleaned, dropped = arbitrate_repeats(primary, secondary)
    assert dropped == 4
    assert [w.start for w in cleaned][:1] == [0.0]
    assert len(cleaned) == 8


def test_arbitration_is_fast_on_a_long_video():
    import random
    import time

    random.seed(7)
    vocab = [f"w{i}" for i in range(800)]

    def long_stream(n: int) -> list[Word]:
        return [
            Word(text=random.choice(vocab), start=i * 0.35, end=i * 0.35 + 0.3, probability=0.9)
            for i in range(n)
        ]

    started = time.perf_counter()
    arbitrate_repeats(long_stream(15_000), long_stream(15_000))
    # About ninety minutes of speech. The old search took well over a minute.
    assert time.perf_counter() - started < 3.0
