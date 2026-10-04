"""Editing must never corrupt the timeline.

Cue times are derived from the words inside the cue, so splitting and merging
recompute them instead of shifting anything.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.gui.editor import EditableCue, cue_index_at, timecode  # noqa: E402
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


def _two_cues() -> tuple[list[EditableCue], list[float]]:
    first = EditableCue(words=words([("یک", 1.0, 2.0)]), text="یک")
    second = EditableCue(words=words([("دو", 5.0, 6.0)]), text="دو")
    cues = [first, second]
    return cues, [c.start for c in cues]


def test_overlay_shows_the_cue_the_playhead_is_inside():
    cues, starts = _two_cues()
    assert cue_index_at(cues, starts, 1.5) == 0
    assert cue_index_at(cues, starts, 5.5) == 1


def test_overlay_is_empty_in_the_silence_between_two_cues():
    # A gap must clear the burned-in line instead of leaving the last one up.
    cues, starts = _two_cues()
    assert cue_index_at(cues, starts, 3.0) == -1
    assert cue_index_at(cues, starts, 0.5) == -1
    assert cue_index_at(cues, starts, 99.0) == -1


def test_a_snapshot_keeps_the_old_text_while_sharing_the_words():
    dialog = _dialog("یعنی لزومان اختیار زندگی")
    dialog._snapshot()
    dialog.cues[0].text = "یعنی لزوماً اختیار زندگی"
    kept = dialog.history[-1][0]
    assert kept.text != dialog.cues[0].text
    assert (kept.start, kept.end) == (dialog.cues[0].start, dialog.cues[0].end)


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


def _eight_words():
    """One line of eight evenly spaced words, ready to be cut up."""
    from farsisub.config import AppConfig
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    stream = [
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4, probability=0.9)
        for i, t in enumerate("یک دو سه چهار پنج شش هفت هشت".split())
    ]
    return EditorDialog(Project(video_path="x.mp4", words=stream), AppConfig())


def test_moving_words_by_hand_carries_their_timing():
    # Deleting words off the end of one line and typing them at the start of
    # the next used to leave the timing behind: the line kept its old end and
    # the words were read out of time.
    dialog = _eight_words()
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    first, second = dialog.cues[0], dialog.cues[1]
    moving = first.text.split()[-2:]

    dialog.table.item(0, 4).setText(" ".join(first.text.split()[:-2]))
    dialog.table.item(1, 4).setText(" ".join(moving) + " " + second.text)

    first, second = dialog.cues[0], dialog.cues[1]
    assert [w.text for w in first.words] == ["یک", "دو"]
    assert first.end == 0.9  # the end came back with the words
    assert second.start == 1.0  # and the next line now starts where they do
    assert second.text.split()[:2] == moving


def test_correcting_a_word_moves_no_timing():
    dialog = _eight_words()
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    before = (dialog.cues[0].start, dialog.cues[0].end)
    dialog.table.item(0, 4).setText("یک دو سه چهارم")
    assert (dialog.cues[0].start, dialog.cues[0].end) == before


def test_split_lands_where_the_caret_is():
    dialog = _eight_words()
    dialog.table.setCurrentCell(0, 4)
    dialog.table.editItem(dialog.table.item(0, 4))
    dialog.active_editor.setCursorPosition(len("یک دو سه چهار پنج"))
    dialog.split_selected()
    assert dialog.cues[0].text == "یک دو سه چهار پنج"
    assert dialog.cues[0].end == 2.4
    assert dialog.cues[1].start == 2.5


def test_edits_survive_closing_the_editor(tmp_path=None):
    """Closing without exporting must not throw the work away."""
    import tempfile

    from farsisub.config import AppConfig
    from farsisub.engine import locate
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    folder = Path(tempfile.mkdtemp())
    video = folder / "clip.mp4"
    stream = [
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4, probability=0.9)
        for i, t in enumerate("یک دو سه چهار پنج شش هفت هشت".split())
    ]
    dialog = EditorDialog(Project(video_path=str(video), words=stream), AppConfig())
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    dialog.table.item(0, 4).setText("متن دست‌ساز")
    shaped = [(c.text, c.start, c.end) for c in dialog.cues]
    dialog.close()

    saved = Project.load(locate.project_path(video))
    assert saved.lines, "the editor wrote nothing back to the project"
    reopened = EditorDialog(saved, AppConfig())
    assert [(c.text, c.start, c.end) for c in reopened.cues] == shaped
    reopened.close()


def test_an_untouched_project_still_builds_lines_from_the_style():
    # Only a subtitle someone has shaped keeps its own lines; a fresh one is
    # still free to follow whatever style is selected.
    from farsisub.models import Project

    project = Project(video_path="x.mp4", words=words([("یک", 0.0, 0.4)]))
    assert project.lines == []
    assert "lines" in project.to_dict()


def test_deleting_every_line_does_not_leave_old_ones_in_the_file():
    """An emptied subtitle must not come back from the saved project."""
    import tempfile

    from farsisub.config import AppConfig
    from farsisub.engine import locate
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    video = str(Path(tempfile.mkdtemp()) / "clip.mp4")
    stream = [
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4, probability=0.9)
        for i, t in enumerate("یک دو سه چهار".split())
    ]
    dialog = EditorDialog(Project(video_path=video, words=stream), AppConfig())
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    dialog.close()
    assert len(Project.load(locate.project_path(video)).lines) == 2

    dialog = EditorDialog(Project.load(locate.project_path(video)), AppConfig())
    for _ in range(len(dialog.cues)):
        dialog.table.setCurrentCell(0, 4)
        dialog.delete_selected()
    dialog.close()
    assert Project.load(locate.project_path(video)).lines == []


def _isolated_data():
    """Point the app's data folder at a fresh temp dir; returns a restore function."""
    import os
    import tempfile

    previous = os.environ.get("FARSISUB_DATA")
    os.environ["FARSISUB_DATA"] = tempfile.mkdtemp()

    def restore() -> None:
        if previous is None:
            os.environ.pop("FARSISUB_DATA", None)
        else:
            os.environ["FARSISUB_DATA"] = previous

    return restore


def test_just_opening_the_editor_does_not_freeze_the_style():
    # Closing an untouched editor used to save its auto-built lines, and from
    # then on switching to another style changed nothing in the editor.
    from farsisub.config import AppConfig
    from farsisub.engine import locate
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    restore = _isolated_data()
    try:
        video = "clip.mp4"
        stream = [
            Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4, probability=0.9)
            for i, t in enumerate("یک دو سه چهار".split())
        ]
        project = Project(video_path=video, words=stream)
        EditorDialog(project, AppConfig()).close()
        assert project.lines == []
        assert not locate.project_path(video).exists()
    finally:
        restore()


def test_splitting_keeps_the_writing_rules_of_the_shown_line():
    # Without a caret the halves were rebuilt from the raw model words: Latin
    # digits and the dropped comma came back.
    dialog = _dialog("سال 1404، خیلی سخت گذشت برای همه ما")
    shown = dialog.cues[0].text
    assert "۱۴۰۴" in shown and "،" not in shown
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    joined = " ".join(cue.text for cue in dialog.cues)
    assert joined == shown


def test_moving_a_word_keeps_corrections_on_both_lines():
    dialog = _eight_words()
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    dialog.cues[0].text = dialog.cues[0].text.replace("یک", "یکم")
    dialog.cues[1].text = dialog.cues[1].text.replace("هشت", "هشتم")
    dialog.table.setCurrentCell(0, 4)
    dialog.move_word_down()
    assert dialog.cues[0].text.split()[0] == "یکم"
    assert dialog.cues[1].text.split()[-1] == "هشتم"
    assert dialog.cues[1].text.split()[0] == "چهار"
    assert [w.text for w in dialog.cues[1].words][0] == "چهار"


def test_an_exported_one_word_line_stays_on_screen_long_enough():
    # Export wrote the raw word times: a lone "آره" flashed for 0.2 s even
    # with three seconds of silence after it.
    from farsisub.config import AppConfig
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    stream = [
        Word(text="آره", start=0.0, end=0.2, probability=0.9),
        Word(text="بعدش", start=3.0, end=3.4, probability=0.9),
        Word(text="رفتیم", start=3.5, end=3.9, probability=0.9),
        Word(text="خونه", start=4.0, end=4.4, probability=0.9),
    ]
    dialog = EditorDialog(Project(video_path="x.mp4", words=stream), AppConfig())
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    dialog.table.setCurrentCell(0, 4)
    while len(dialog.cues[0].words) > 1:
        dialog.move_word_down()
    assert [w.text for w in dialog.cues[0].words] == ["آره"]
    first = dialog.to_cues()[0]
    assert first.end - first.start >= dialog.config.profile.min_duration - 1e-9
