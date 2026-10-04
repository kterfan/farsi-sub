"""Segmentation rules are where subtle bugs hide, so they get the most tests."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.config import BUILTIN_PROFILES, TextRules  # noqa: E402
from farsisub.models import Word  # noqa: E402
from farsisub.render.segment import build_cues, wrap_lines  # noqa: E402

RULES = TextRules()
SMART = BUILTIN_PROFILES["smart"]
REELS = BUILTIN_PROFILES["reels"]


def make_words(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e, probability=0.9) for t, s, e in spec]


def speech(text: str, *, start: float = 0.0, wps: float = 2.5) -> list[Word]:
    """Lay a sentence out on a timeline at a plausible speaking rate."""
    words: list[Word] = []
    step = 1.0 / wps
    t = start
    for token in text.split():
        words.append(Word(text=token, start=t, end=t + step * 0.9, probability=0.9))
        t += step
    return words


def test_cue_never_exceeds_line_and_duration_limits():
    words = speech("سلام به همه شما که این ویدیو را تماشا می کنید و همراه ما هستید امروز")
    cues = build_cues(words, SMART, RULES)
    assert cues
    for cue in cues:
        assert len(cue.lines) <= SMART.max_lines
        for line in cue.lines:
            assert len(line) <= SMART.max_chars_per_line
        assert cue.duration <= SMART.max_duration + 1e-6


def test_reading_speed_stays_under_limit():
    words = speech("این یک جمله نسبتا سریع است که تند گفته می شود ولی خواندنی می ماند", wps=4.0)
    cues = build_cues(words, SMART, RULES)
    for cue in cues:
        assert cue.cps <= SMART.max_cps * 1.35


def test_impossibly_fast_speech_does_not_shatter_into_one_word_cues():
    # No segmentation can meet the CPS limit when speech is this fast; the
    # right answer is fewer, fuller cues plus an orange CPS flag in the editor,
    # not a stroboscope of single words.
    words = speech("این یک جمله بسیار سریع است که خیلی تند گفته می شود", wps=9.0)
    cues = build_cues(words, SMART, RULES)
    assert cues
    assert max(len(cue.text.split()) for cue in cues) >= 3


def test_cues_do_not_overlap_and_keep_a_gap():
    words = speech("جمله اول تمام شد. جمله دوم شروع شد. جمله سوم هم آمد.")
    cues = build_cues(words, SMART, RULES)
    for a, b in zip(cues, cues[1:]):
        assert a.end <= b.start + 1e-9


def test_sentence_boundary_starts_a_new_cue():
    words = speech("سلام دوستان. خوش آمدید.")
    cues = build_cues(words, SMART, RULES)
    assert len(cues) >= 2


def test_final_period_removed_but_question_mark_kept():
    words = speech("حال شما چطور است؟ من خوبم.")
    cues = build_cues(words, SMART, RULES)
    joined = " ".join(c.text for c in cues)
    assert "؟" in joined
    assert not any(c.text.endswith(".") for c in cues)


def test_persian_digits_by_default_and_latin_when_switched():
    words = make_words([("سال", 0.0, 0.5), ("2026", 0.6, 1.2)])
    persian = build_cues(words, SMART, RULES)[0].text
    assert "۲۰۲۶" in persian

    latin_rules = TextRules(persian_digits=False)
    latin = build_cues(words, SMART, latin_rules)[0].text
    assert "2026" in latin


def test_reels_profile_is_tighter_than_smart():
    words = speech("امروز درباره یک موضوع بسیار مهم و کاربردی صحبت می کنیم")
    reels = build_cues(words, REELS, RULES)
    for cue in reels:
        for line in cue.lines:
            assert len(line) <= REELS.max_chars_per_line
        assert cue.duration <= REELS.max_duration + 1e-6
    assert len(reels) >= len(build_cues(words, SMART, RULES))


def test_keyword_gets_its_own_cue_in_reels():
    words = speech("امروز درباره این محصول جدید و کاربردی حرف می زنیم")
    words[3].keyword = True  # محصول
    cues = build_cues(words, REELS, RULES)
    assert any(cue.text.strip().strip("…") == "محصول" for cue in cues)


def test_solo_keyword_is_skipped_when_it_would_strand_a_fragment():
    # Splitting here would leave "این" alone for a third of a second.
    words = speech("این محصول جدید ما است")
    words[1].keyword = True
    cues = build_cues(words, REELS, RULES)
    assert not any(cue.text.strip() == "محصول" for cue in cues)


def test_wrap_lines_balances_two_lines():
    profile = BUILTIN_PROFILES["smart"]
    text = "یک دو سه چهار پنج شش هفت هشت نه ده یازده دوازده سیزده چهارده"
    lines = wrap_lines(text, profile)
    assert len(lines) <= profile.max_lines
    if len(lines) == 2:
        assert abs(len(lines[0]) - len(lines[1])) <= 20


def test_empty_input_yields_no_cues():
    assert build_cues([], SMART, RULES) == []


def test_no_lone_word_flashes_on_screen():
    words = speech("امروز درباره یک موضوع بسیار مهم صحبت می کنیم")
    words[6].keyword = True
    cues = build_cues(words, REELS, RULES)
    for cue in cues:
        plain = cue.text.strip().strip("…")
        if len(plain.split()) == 1 and plain != "صحبت":
            assert cue.duration >= REELS.min_duration * 0.5, plain


def test_keyword_stays_inline_when_there_is_no_time_to_read_it():
    # Fast speech: giving this keyword its own cue would flash it for 0.3s.
    words = speech("این محصول جدید ما است", wps=3.3)
    words[1].keyword = True
    cues = build_cues(words, REELS, RULES)
    for cue in cues:
        if cue.text.strip().strip("…") == "محصول":
            assert cue.duration >= 0.45


def test_persian_suffix_never_splits_from_its_stem():
    # Seen in a real clip: "وابسته" ended one cue and "ترین" opened the next.
    words = speech("زن همه فن حریف خونه وابسته ترین آدم هر خونه است")
    for profile in (SMART, REELS):
        cues = build_cues(words, profile, RULES)
        for cue in cues:
            first = cue.text.split()[0].strip("…")
            assert first not in {"ترین", "تر", "ها", "های"}, cue.text


def test_cue_never_opens_with_a_clitic():
    # Real clip: "این‌که همه چی" / "رو بلد باشی" — the object marker was left
    # stranded at the head of the next cue.
    words = speech("این که همه چی رو بلد باشی یعنی اختیار زندگی دست خودته")
    for profile in (SMART, REELS):
        for cue in build_cues(words, profile, RULES):
            first = cue.text.split()[0]
            assert first not in {"رو", "را", "که", "و", "به", "از", "با"}, cue.text


def test_line_break_does_not_split_a_compound_verb():
    # Was: "بوهران رو جمع / کنی،" — "جمع کنی" is one verb.
    from farsisub.render.segment import wrap_lines

    text = "تو ممکنه خرید کنی، بحران رو جمع کنی، حساب کتاب بلد باشی"
    lines = wrap_lines(text, SMART)
    assert len(lines) <= 2
    for line in lines[1:]:
        assert line.split()[0] not in {"کنی،", "کنی", "باشی", "کن"}


def test_line_break_does_not_leave_a_dangling_preposition():
    from farsisub.render.segment import wrap_lines

    text = "و این قسمتشه که معمولا به زن خونه‌دار برمیخوره و آزارش میده"
    lines = wrap_lines(text, SMART)
    for line in lines[:-1]:
        assert line.split()[-1] not in {"به", "با", "از", "در", "برای"}


WORD = BUILTIN_PROFILES["word"]


def _spaced(text: str, step: float = 0.5) -> list[Word]:
    return [Word(text=t, start=i * step, end=i * step + step * 0.8) for i, t in enumerate(text.split())]


def test_word_style_gives_each_word_its_own_cue():
    cues = build_cues(_spaced("امروز درباره بحران حرف زدیم"), WORD, RULES)
    assert [c.text for c in cues] == ["امروز", "درباره", "بحران", "حرف", "زدیم"]
    for first, second in zip(cues, cues[1:]):
        assert first.end <= second.start + 1e-9


def test_word_style_keeps_leaning_words_with_their_host():
    cues = build_cues(_spaced("کتاب ها رو باید جمع کنی"), WORD, RULES)
    texts = [c.text for c in cues]
    assert not any(t.split()[0] in {"ها", "رو", "کنی"} for t in texts), texts
    assert "جمع کنی" in texts


def test_word_style_glues_a_word_too_fast_to_read():
    words = _spaced("یک دو سه")
    words[1] = Word(text="دو", start=0.5, end=0.6)
    words[2] = Word(text="سه", start=0.6, end=1.0)
    cues = build_cues(words, WORD, RULES)
    assert all(c.duration >= 0.25 for c in cues)
    assert " ".join(c.text for c in cues).split() == ["یک", "دو", "سه"]


def test_word_style_does_not_glue_across_a_sentence_end():
    words = _spaced("تموم شد. رو")
    cues = build_cues(words, WORD, RULES)
    assert cues[-1].text == "رو"
