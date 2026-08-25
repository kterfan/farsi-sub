"""Editing must never corrupt the timeline.

Cue times are derived from the words inside the cue, so splitting and merging
recompute them instead of shifting anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.gui.editor import EditableCue, timecode  # noqa: E402
from farsisub.models import Word  # noqa: E402


def words(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e, probability=0.9) for t, s, e in spec]


def test_cue_times_come_from_its_words():
    cue = EditableCue(words=words([("یک", 1.0, 1.4), ("دو", 1.5, 2.2)]), text="یک دو")
    assert cue.start == 1.0
    assert cue.end == 2.2
    assert abs(cue.duration - 1.2) < 1e-9


def test_splitting_keeps_each_half_on_its_own_words():
    original = words([("یک", 0.0, 0.5), ("دو", 0.6, 1.0), ("سه", 2.0, 2.4), ("چهار", 2.5, 3.0)])
    first = EditableCue(words=original[:2])
    second = EditableCue(words=original[2:])
    assert first.end == 1.0 and second.start == 2.0
    # no overlap, and nothing invented between them
    assert first.end < second.start


def test_merging_restores_the_original_span():
    original = words([("یک", 0.0, 0.5), ("دو", 0.6, 1.0), ("سه", 2.0, 2.4)])
    whole = EditableCue(words=original)
    halves = [EditableCue(words=original[:1]), EditableCue(words=original[1:])]
    merged = EditableCue(words=halves[0].words + halves[1].words)
    assert (merged.start, merged.end) == (whole.start, whole.end)


def test_editing_text_leaves_timing_untouched():
    cue = EditableCue(words=words([("بوهران", 3.0, 3.6)]), text="بوهران")
    before = (cue.start, cue.end)
    cue.text = "بحران"
    cue.edited = True
    assert (cue.start, cue.end) == before


def test_confidence_of_a_cue_is_its_weakest_word():
    cue = EditableCue(
        words=[
            Word(text="خوب", start=0.0, end=0.3, probability=0.99),
            Word(text="مشکوک", start=0.3, end=0.7, probability=0.31),
        ]
    )
    assert abs(cue.worst_probability - 0.31) < 1e-9


def test_timecode_is_readable():
    assert timecode(0) == "00:00.00"
    assert timecode(75.25) == "01:15.25"


def _dialog(sentence: str):
    """A dialog over one line, without touching the real glossary."""
    from PySide6.QtWidgets import QApplication

    from farsisub.config import AppConfig
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project

    QApplication.instance() or QApplication([])
    stream = [
        Word(text=t, start=i * 0.45, end=i * 0.45 + 0.35, probability=0.9)
        for i, t in enumerate(sentence.split())
    ]
    return EditorDialog(Project(video_path="x.mp4", words=stream), AppConfig())


def test_marked_word_is_paired_with_the_word_it_replaced():
    dialog = _dialog("یعنی لزومان اختیار زندگی")
    dialog.cues[0].text = "یعنی لزوماً اختیار زندگی"
    dialog.remember_marked("لزوماً", 0)
    heard = " ".join(w.text for w in dialog.cues[0].words).split()
    assert dialog._pair_for_marked(heard, dialog.cues[0].text.split()) == (
        "لزومان",
        "لزوماً",
    )


def test_marking_an_untouched_word_teaches_nothing():
    dialog = _dialog("یعنی لزومان اختیار زندگی")
    dialog.cues[0].text = "یعنی لزوماً اختیار زندگی"
    dialog.remember_marked("زندگی", 0)
    heard = " ".join(w.text for w in dialog.cues[0].words).split()
    assert dialog._pair_for_marked(heard, dialog.cues[0].text.split()) is None


def test_marking_ignores_punctuation_around_the_word():
    dialog = _dialog("خب لزومان باید")
    dialog.cues[0].text = "خب لزوماً، باید"
    dialog.remember_marked("لزوماً،", 0)
    assert dialog.marked_text == "لزوماً"


def test_edit_is_compared_against_what_was_shown_not_raw_model_output():
    # The normaliser removes commas and adds ZWNJ before the line is displayed.
    # Diffing against the raw words would report those as user edits and hide
    # the real one -- which is why a correction silently failed to save.
    dialog = _dialog("تو، ممکنه لزومان اختیار داری")
    cue = dialog.cues[0]
    assert "،" not in cue.original  # the comma is gone from the shown text
    assert cue.original == cue.text

    cue.text = cue.text.replace("لزومان", "لزوماً")
    dialog.remember_marked("لزوماً", 0)
    assert dialog._pair_for_marked(cue.original.split(), cue.text.split()) == (
        "لزومان",
        "لزوماً",
    )


def test_split_and_merge_keep_a_baseline_for_learning():
    dialog = _dialog("یکی دوتا سه‌تا چهارتا پنجم ششم هفتم هشتم")
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    for cue in dialog.cues:
        assert cue.original == cue.text
