"""Persian text rules, subtitle writers, and whisper.cpp JSON parsing."""

from __future__ import annotations

import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.config import TextRules  # noqa: E402
from farsisub.engine.whispercpp import (  # noqa: E402
    WhisperOptions,
    build_command,
    parse_progress,
    words_from_json,
)
from farsisub.models import Cue  # noqa: E402
from farsisub.render.writers import format_timestamp, to_srt, write_subtitle  # noqa: E402
from farsisub.text.normalize import (  # noqa: E402
    apply_punctuation_rules,
    normalize_text,
    to_persian_digits,
)

RULES = TextRules()


def test_arabic_letters_become_persian():
    out = normalize_text("كتاب هاي من", RULES)
    assert "ك" not in out
    assert "ي" not in out
    assert "ک" in out and "ی" in out


def test_diacritics_and_kashida_removed():
    out = normalize_text("سَلامـــ عَلیکُم", RULES)
    assert "ـ" not in out
    assert all(ch not in out for ch in "َُِ")


def test_digits_follow_the_switch():
    assert to_persian_digits("2026") == "۲۰۲۶"
    assert normalize_text("سال 1404", RULES) == "سال ۱۴۰۴"
    assert normalize_text("سال ۱۴۰۴", TextRules(persian_digits=False)) == "سال 1404"


def test_space_before_punctuation_is_removed():
    assert normalize_text("سلام ، خوبی ؟", RULES) == "سلام، خوبی؟"


def test_final_period_dropped_but_question_survives():
    assert apply_punctuation_rules("این یک جمله است.", RULES) == "این یک جمله است"
    assert apply_punctuation_rules("خوبی؟", RULES) == "خوبی؟"


def test_punctuation_switches_can_strip_marks():
    rules = TextRules(keep_exclamation_mark=False, keep_question_mark=False, keep_comma=False)
    assert apply_punctuation_rules("سلام، چطوری؟ عالی!", rules) == "سلام چطوری عالی"


def test_ellipsis_is_off_by_default():
    # On a real 79-second clip every single cue ended in "…", which reads as
    # noise rather than as "the sentence continues".
    assert not apply_punctuation_rules("و بعد از آن", RULES, continues=True).endswith("…")


def test_ellipsis_marks_continuation_when_switched_on():
    rules = TextRules(ellipsis_on_continuation=True)
    assert apply_punctuation_rules("و بعد از آن", rules, continues=True).endswith("…")


def test_timestamp_format_matches_srt_spec():
    assert format_timestamp(0) == "00:00:00,000"
    assert format_timestamp(3661.5) == "01:01:01,500"


def test_srt_structure_and_bom():
    cues = [Cue(index=1, start=0.0, end=1.5, lines=["سلام دنیا"])]
    body = to_srt(cues)
    assert body.startswith("1\n00:00:00,000 --> 00:00:01,500\n")
    with tempfile.TemporaryDirectory() as tmp:
        path = write_subtitle(cues, Path(tmp) / "out.srt", bom=True)
        raw = path.read_bytes()
        assert raw.startswith(b"\xef\xbb\xbf")  # UTF-8 BOM for old players
        assert b"\r\n" in raw


def test_token_timestamps_are_centiseconds_not_milliseconds():
    # t_dtw = 250 centiseconds = 2.5 seconds. Reading it as milliseconds would
    # place the word at 0.25s and shift the whole file by a factor of ten.
    data = {
        "transcription": [
            {
                "offsets": {"from": 0, "to": 4000},
                "tokens": [
                    {"text": " سلام", "p": 0.9, "t_dtw": 250, "offsets": {"from": 0, "to": 3000}},
                ],
            }
        ]
    }
    words = words_from_json(data)
    assert len(words) == 1
    assert abs(words[0].start - 2.5) < 1e-6


def test_subword_tokens_merge_into_one_word_with_min_confidence():
    data = {
        "transcription": [
            {
                "offsets": {"from": 0, "to": 2000},
                "tokens": [
                    {"text": " کتاب", "p": 0.95, "t_dtw": 0, "offsets": {"from": 0, "to": 1000}},
                    {"text": "خانه", "p": 0.42, "t_dtw": 50, "offsets": {"from": 500, "to": 1500}},
                    {"text": "[_TT_10]", "p": 0.99, "t_dtw": -1, "offsets": {}},
                ],
            }
        ]
    }
    words = words_from_json(data)
    assert [w.text for w in words] == ["کتابخانه"]
    assert abs(words[0].probability - 0.42) < 1e-9  # weakest token wins


def test_command_line_has_the_flags_that_matter():
    opts = WhisperOptions(
        binary=Path("whisper-cli.exe"),
        model=Path("ggml-large-v3.bin"),
        vad_model=Path("ggml-silero-v5.1.2.bin"),
        dtw_preset="large.v3",
    )
    cmd = build_command(opts, Path("clip.mp4"), Path("out"))
    assert "-ojf" in cmd  # full JSON with per-token p and t_dtw
    assert "-dtw" in cmd and "large.v3" in cmd
    assert "--vad" in cmd
    # our own segmentation must not fight whisper.cpp's
    assert "-ml" not in cmd and "-sow" not in cmd
    assert "-ng" not in cmd  # GPU first, CPU only as a fallback


def test_cpu_fallback_flag_is_added_when_gpu_disabled():
    opts = WhisperOptions(binary=Path("w.exe"), model=Path("m.bin"), use_gpu=False)
    assert "-ng" in build_command(opts, Path("a.wav"), Path("out"))


def test_progress_lines_are_parsed():
    assert parse_progress("whisper_print_progress_callback: progress =  40%") == 40
    assert parse_progress("whisper_init_state: loading model") is None


def test_latin_punctuation_becomes_persian():
    assert normalize_text("سلام , خوبی ?", RULES) == "سلام، خوبی؟"


def test_dtw_forces_flash_attention_off():
    # whisper.cpp silently disables DTW when flash attention is on, so the two
    # flags must always travel together. Measured, not assumed.
    opts = WhisperOptions(binary=Path("w.exe"), model=Path("m.bin"), dtw_preset="large.v3")
    cmd = build_command(opts, Path("a.wav"), Path("out"))
    assert "-nfa" in cmd


def test_word_spans_are_monotonic_and_never_overlap():
    # DTW gives one instant per token; ends inherited from segment offsets can
    # overlap the next word or collapse to zero.
    data = {
        "transcription": [
            {
                "offsets": {"from": 0, "to": 3000},
                "tokens": [
                    {"text": " یک", "p": 0.9, "t_dtw": 20, "offsets": {"from": 0, "to": 2000}},
                    {"text": " دو", "p": 0.9, "t_dtw": 40, "offsets": {"from": 0, "to": 2500}},
                    {"text": " سه", "p": 0.9, "t_dtw": 60, "offsets": {"from": 0, "to": 0}},
                ],
            }
        ]
    }
    words = words_from_json(data)
    assert [round(w.start, 2) for w in words] == [0.2, 0.4, 0.6]
    for a, b in zip(words, words[1:]):
        assert a.end <= b.start + 1e-9
        assert a.end > a.start
    assert words[-1].end > words[-1].start


def test_project_file_does_not_land_next_to_the_video():
    # A .fsub beside the video gets opened in a subtitle editor by mistake and
    # shows up as 180 one-word cues with zero duration.
    from farsisub.engine import locate

    target = locate.project_path(r"C:\videos\001Roya.mp4")
    assert target.suffix == ".fsub"
    assert target.parent == locate.projects_dir()
    assert "001Roya" in target.name
    # same name, different folder -> different project file
    other = locate.project_path(r"D:\archive\001Roya.mp4")
    assert other.name != target.name


def test_confident_words_survive_the_silence_filter():
    # Measured on a real clip: DTW placed "گوش" (p=0.95) inside a four second
    # silence, and the first version of the filter deleted it.
    from farsisub.engine.audio import drop_silent_words
    from farsisub.models import Word

    words = [
        Word(text="مسئولیت", start=1.0, end=1.5, probability=0.94),
        Word(text="گوش", start=4.0, end=4.7, probability=0.95),  # in a gap
        Word(text="بلبلبل", start=5.0, end=5.4, probability=0.11),  # hallucinated
        Word(text="نظریه", start=8.0, end=8.4, probability=0.99),
    ]
    kept = drop_silent_words(words, [0.20, 0.0000, 0.0000, 0.18])
    assert [w.text for w in kept] == ["مسئولیت", "گوش", "نظریه"]


def test_builtin_corrections_fix_known_whisper_slips():
    from farsisub.text.corrections import BUILTIN_CORRECTIONS, correct_text

    table = dict(BUILTIN_CORRECTIONS)
    out = correct_text("تو ممکنه بوهران رو جمع کنی، منتظر تعیید بقیه باشی", table)
    assert "بحران" in out and "تأیید" in out
    assert "بوهران" not in out


def test_correction_keeps_trailing_punctuation():
    from farsisub.text.corrections import correct_text

    assert correct_text("بوهران،", {"بوهران": "بحران"}) == "بحران،"
    assert correct_text("معمولا.", {"معمولا": "معمولاً"}) == "معمولاً."


def test_correction_leaves_unknown_words_alone():
    from farsisub.text.corrections import correct_text

    text = "این جمله دست نخورده می‌ماند"
    assert correct_text(text, {"بوهران": "بحران"}) == text


def test_tanvin_survives_normalisation():
    # "لزوماً" spelled without its tanvin is a different, wrong word.
    assert normalize_text("لزوماً", RULES) == "لزوماً"
    assert normalize_text("واقعاً خوب بود", RULES) == "واقعاً خوب بود"
    # decorative harakat still go
    assert normalize_text("سَلامُ", RULES) == "سلام"


def test_commas_are_removed_by_default():
    assert "،" not in apply_punctuation_rules("سلام، خوبی؟", TextRules())
    assert "," not in apply_punctuation_rules("سلام, خوبی؟", TextRules())
    # and the sentence marks still survive
    assert apply_punctuation_rules("سلام، خوبی؟", TextRules()).endswith("؟")


def test_glued_suffixes_get_their_zwnj_back():
    from farsisub.text.normalize import normalize_word

    rules = TextRules()
    assert normalize_word("خونهدار", rules) == "خونه‌دار"
    assert normalize_word("وابستهترین", rules) == "وابسته‌ترین"
    assert normalize_word("خانهها،", rules) == "خانه‌ها،"
    # words that only look glued stay untouched
    assert normalize_word("بهتر", rules) == "بهتر"
    assert normalize_word("بهترین", rules) == "بهترین"


def test_learning_a_correction_from_an_edit():
    from farsisub.text.corrections import diff_pairs

    heard = "تو ممکنه بوهران رو جمع کنی".split()
    fixed = "تو ممکنه بحران رو جمع کنی".split()
    assert diff_pairs(heard, fixed) == [("بوهران", "بحران")]


def test_learning_a_merge_of_two_words():
    from farsisub.text.corrections import diff_pairs

    assert diff_pairs("زن خونه دار".split(), "زن خونه‌دار".split()) == [
        ("خونه دار", "خونه‌دار")
    ]


def test_no_change_teaches_nothing():
    from farsisub.text.corrections import diff_pairs

    assert diff_pairs("همین متن".split(), "همین متن".split()) == []


def test_learning_a_split_of_one_word_into_two():
    from farsisub.text.corrections import diff_pairs

    assert diff_pairs("نظریه خودتعینگری میگه".split(), "نظریه خودتعیین‌گری میگه".split()) == [
        ("خودتعینگری", "خودتعیین‌گری")
    ]
    assert diff_pairs("نظریه خودتعینگری میگه".split(), "نظریه خود تعیین‌گری میگه".split()) == [
        ("خودتعینگری", "خود تعیین‌گری")
    ]


def test_multi_word_corrections_are_applied_to_a_line():
    from farsisub.text.corrections import correct_text

    table = {"خونه دار": "خونه‌دار", "بوهران": "بحران"}
    assert correct_text("زن خونه دار با بوهران", table) == "زن خونه‌دار با بحران"


def test_models_are_found_in_extra_folders(tmp_path=None):
    # An installed copy should reuse a model set already on the disk instead of
    # downloading gigabytes again.
    import os
    import tempfile

    from farsisub.engine import locate

    with tempfile.TemporaryDirectory() as home, tempfile.TemporaryDirectory() as shared:
        previous = os.environ.get("FARSISUB_DATA")
        os.environ["FARSISUB_DATA"] = home
        try:
            (Path(shared) / "ggml-large-v3.bin").write_bytes(b"x")
            (Path(shared) / "ggml-my-tune.bin").write_bytes(b"x")
            assert locate.installed_models() == []

            locate.add_model_dir(shared)
            found = locate.installed_models()
            assert "large-v3" in found
            assert "my-tune" in found
            assert locate.model_path("my-tune") == Path(shared) / "ggml-my-tune.bin"
        finally:
            if previous is None:
                os.environ.pop("FARSISUB_DATA", None)
            else:
                os.environ["FARSISUB_DATA"] = previous
