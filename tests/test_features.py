"""Version 1.6 features: settings, ASS, burned video, editor tools, theme."""

from __future__ import annotations

import os
import sys
import tempfile
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.config import (  # noqa: E402
    BUILTIN_PROFILES,
    AppConfig,
    AssStyle,
    load_settings,
    save_settings,
    settings_path,
)
from farsisub.models import Cue, Project, Word  # noqa: E402
from farsisub.render.writers import ass_color, frame_scale, to_ass, write_subtitle  # noqa: E402


class _TempData:
    """Run a block against a fresh, private data folder."""

    def __enter__(self):
        self.previous = os.environ.get("FARSISUB_DATA")
        self.folder = tempfile.mkdtemp(prefix="farsisub-feature-")
        os.environ["FARSISUB_DATA"] = self.folder
        return Path(self.folder)

    def __exit__(self, *_exc):
        if self.previous is None:
            os.environ.pop("FARSISUB_DATA", None)
        else:
            os.environ["FARSISUB_DATA"] = self.previous


def _qt():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


# ------------------------------------------------------------------ settings


def test_settings_survive_a_restart():
    with _TempData():
        config = AppConfig()
        config.profile = replace(BUILTIN_PROFILES["word"])
        config.output_format = "ass"
        config.theme = "light"
        config.text.persian_digits = False
        config.ass_style.size = 80
        save_settings(config)
        again = load_settings()
        assert again.profile.name == "word"
        assert again.output_format == "ass"
        assert again.theme == "light"
        assert again.text.persian_digits is False
        assert again.ass_style.size == 80
        assert again.suffix == ".ass"


def test_a_broken_settings_file_falls_back_to_defaults():
    with _TempData():
        settings_path().write_text("{not json", encoding="utf-8")
        assert load_settings().profile.name == "smart"


def test_wrong_values_cost_only_their_own_field():
    config = AppConfig.from_dict(
        {
            "profile": {"name": "no-such-style"},
            "text": {"bom": "yes", "persian_digits": False},
            "ass_style": {"size": "huge", "outline": 2},
            "low_confidence": "high",
            "theme": 7,
            "output_format": "docx",
            "custom_profile": {"mode": "bogus", "max_lines": 99, "label": "من"},
        }
    )
    assert config.profile.name == "smart"
    assert config.text.bom is True and config.text.persian_digits is False
    assert config.ass_style.size == 64 and config.ass_style.outline == 2.0
    assert config.low_confidence == 0.6
    assert config.theme == "dark" and config.output_format == "srt"
    assert config.custom_profile.mode == "smart"
    assert config.custom_profile.max_lines == 3  # clamped
    assert config.custom_profile.label == "من"


def test_a_saved_custom_style_is_selected_again():
    with _TempData():
        config = AppConfig()
        config.custom_profile = replace(
            BUILTIN_PROFILES["reels"], name="custom", label="سبک من", max_chars_per_line=30
        )
        config.profile = replace(config.custom_profile)
        save_settings(config)
        again = load_settings()
        assert again.profile.name == "custom"
        assert again.profile.max_chars_per_line == 30


# ----------------------------------------------------------------------- ASS


def test_ass_colours_and_scaling():
    assert ass_color("#FFD400") == "&H0000D4FF"
    assert ass_color("not a colour") == "&H00FFFFFF"
    assert frame_scale(1920, 1080) == 1.0
    # A vertical reel scales by its short side, not its height.
    assert frame_scale(1080, 1920) == 1.0
    assert frame_scale(1280, 720) == 720 / 1080


def test_ass_file_has_styles_events_and_safe_text():
    cues = [
        Cue(index=1, start=1.0, end=2.5, lines=["سلام {\\b1}", "خط دوم"]),
        Cue(index=2, start=2.5, end=3.0, lines=["کلیدی"], keyword=True),
    ]
    body = to_ass(cues, AssStyle(), (1080, 1920))
    assert "PlayResX: 1080" in body and "PlayResY: 1920" in body
    assert "Style: Default,Vazirmatn,64," in body
    assert "Style: Keyword," in body
    assert "Dialogue: 0,0:00:01.00,0:00:02.50,Default,,0,0,0,," in body
    assert "\\N" in body  # line break
    assert "{\\b1}" not in body  # typed braces are never override codes
    assert ",Keyword,,0,0,0,,کلیدی" in body


def test_ass_written_through_the_normal_writer():
    with tempfile.TemporaryDirectory() as folder:
        out = write_subtitle(
            [Cue(index=1, start=0.0, end=1.0, lines=["سلام"])], Path(folder) / "a.ass"
        )
        assert out.read_text(encoding="utf-8-sig").startswith("[Script Info]")


def test_word_style_marks_keyword_cues_for_colour():
    from farsisub.render.segment import build_cues

    words = [Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate("این خیلی مهمه".split())]
    words[2].keyword = True
    cues = build_cues(words, BUILTIN_PROFILES["word"], AppConfig().text)
    assert [c.keyword for c in cues] == [False, False, True]


# -------------------------------------------------------------- burned video


def _sample_video(path: Path, seconds: float = 2.0, size=(640, 360), audio: bool = True) -> Path:
    import math

    import av
    import numpy as np

    with av.open(str(path), "w") as out:
        try:
            video = out.add_stream("libx264", rate=25)
        except Exception:  # an FFmpeg build without x264
            video = out.add_stream("mpeg4", rate=25)
        video.width, video.height, video.pix_fmt = size[0], size[1], "yuv420p"
        sound = out.add_stream("aac", rate=44100, layout="stereo") if audio else None
        for i in range(int(seconds * 25)):
            frame = av.VideoFrame.from_ndarray(np.full((size[1], size[0], 3), 90, np.uint8), format="rgb24")
            frame.pts = i
            for packet in video.encode(frame):
                out.mux(packet)
        if sound is not None:
            t = 0
            for _ in range(int(seconds * 44100 / 1024)):
                wave = np.sin(2 * math.pi * 440 * (np.arange(1024) + t) / 44100).astype(np.float32)
                block = av.AudioFrame.from_ndarray(np.stack([wave, wave]), format="fltp", layout="stereo")
                block.sample_rate, block.pts = 44100, t
                t += 1024
                for packet in sound.encode(block):
                    out.mux(packet)
            for packet in sound.encode(None):
                out.mux(packet)
        for packet in video.encode(None):
            out.mux(packet)
    return path


def test_burning_draws_the_text_into_the_frames_and_keeps_the_sound():
    import av
    import numpy as np

    from farsisub.render.burn import burn

    with tempfile.TemporaryDirectory() as folder:
        source = _sample_video(Path(folder) / "in.mp4")
        cues = [Cue(index=1, start=0.0, end=1.0, lines=["سلام دنیا"])]
        progress: list[int] = []
        out = burn(source, cues, AssStyle(), Path(folder) / "out.mp4", on_progress=progress.append)
        with av.open(str(out)) as result:
            kinds = sorted(s.type for s in result.streams)
            frames = [f.to_ndarray(format="rgb24") for f in result.decode(video=0)]
        assert kinds == ["audio", "video"]
        assert len(frames) == 50
        changed = lambda f: int((np.abs(f.astype(int) - 90) > 40).sum())  # noqa: E731
        assert changed(frames[10]) > 500, "no text in the first second"
        assert changed(frames[40]) < 50, "text stayed after its cue ended"
        assert progress[-1] == 100
        assert not list(Path(folder).glob("*.part*"))


def test_a_cancelled_burn_leaves_no_half_file():
    from farsisub.pipeline import Cancelled
    from farsisub.render.burn import burn

    with tempfile.TemporaryDirectory() as folder:
        source = _sample_video(Path(folder) / "in.mp4", audio=False)
        calls = []

        def checkpoint():
            calls.append(1)
            if len(calls) > 5:
                raise Cancelled

        try:
            burn(source, [], AssStyle(), Path(folder) / "out.mp4", checkpoint=checkpoint)
        except Cancelled:
            pass
        else:
            raise AssertionError("the cancel did not stop the burn")
        assert sorted(p.name for p in Path(folder).iterdir()) == ["in.mp4"]


def test_rotation_follows_the_display_matrix():
    import numpy as np

    from farsisub.render.burn import rotate

    landscape = np.zeros((2, 4, 3), np.uint8)
    assert rotate(landscape, 0).shape == (2, 4, 3)
    assert rotate(landscape, -90).shape == (4, 2, 3)  # a portrait phone video
    assert rotate(landscape, 180).shape == (2, 4, 3)


# -------------------------------------------------------------- editor tools


def _cues(spec):
    from farsisub.gui.editor import EditableCue

    return [
        EditableCue(words=[Word(text=t, start=s, end=e) for t, s, e in words], text=" ".join(w[0] for w in words))
        for words in spec
    ]


def test_dragging_an_edge_stops_at_the_neighbours():
    from farsisub.gui.editor_tools import MIN_LINE, move_edge

    cues = _cues([[("یک", 0.0, 1.0)], [("دو", 2.0, 2.5), ("سه", 2.6, 3.0)], [("چهار", 4.0, 5.0)]])
    assert move_edge(cues, 1, "start", 0.2) == 1.0  # stops at the line before
    assert move_edge(cues, 1, "end", 9.0) == 4.0  # stops at the line after
    assert move_edge(cues, 1, "end", 0.0) >= cues[1].start + MIN_LINE
    assert move_edge(cues, 1, "start", 2.9) <= cues[1].words[0].end


def test_find_and_replace_respects_whole_words():
    from farsisub.gui.editor_tools import replace_in_cues, replace_in_text

    assert replace_in_text("کتابخونه خونه", "خونه", "خانه", True) == ("کتابخونه خانه", 1)
    assert replace_in_text("کتابخونه خونه", "خونه", "خانه", False) == ("کتابخانه خانه", 2)
    cues = _cues([[("بوهران", 0, 1)], [("یک", 1, 2)], [("بوهران", 2, 3)]])
    assert replace_in_cues(cues, "بوهران", "بحران") == 2
    assert cues[0].text == "بحران" and cues[0].edited


def _editor(text: str = "یک دو سه چهار پنج شش", video: str = "x.mp4", profile: str = "smart"):
    from farsisub.gui.editor import EditorDialog

    _qt()
    stream = [Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4, probability=0.9) for i, t in enumerate(text.split())]
    config = AppConfig()
    config.profile = replace(BUILTIN_PROFILES[profile])
    return EditorDialog(Project(video_path=video, words=stream), config)


def test_an_edge_move_is_undone_with_its_time():
    dialog = _editor()
    dialog.table.setCurrentCell(0, 4)
    dialog.split_selected()
    dialog.table.setCurrentCell(0, 4)
    before = dialog.cues[0].end
    dialog._edge_moved("end", before - 0.2)
    assert abs(dialog.cues[0].end - (before - 0.2)) < 1e-9
    dialog.undo()
    assert dialog.cues[0].end == before
    dialog.redo()
    assert abs(dialog.cues[0].end - (before - 0.2)) < 1e-9


def test_switching_style_in_the_editor_rebuilds_the_lines():
    dialog = _editor("یک دو سه چهار پنج شش", profile="smart")
    assert len(dialog.cues) == 1
    dialog.style_box.setCurrentIndex(dialog.style_box.findData("word"))
    assert len(dialog.cues) == 6
    assert dialog.config.profile.name == "word"
    assert dialog.shaped is False


def test_a_keyword_chosen_by_hand_is_kept_in_the_project():
    from farsisub.engine import locate

    with _TempData():
        dialog = _editor("این خیلی مهمه", video="clip.mp4", profile="reels")
        word = dialog.cues[0].words[2]
        dialog.set_keyword(word, True)
        assert "مهمه" in dialog.keyword_texts(dialog.cues[0])
        dialog.close()
        saved = Project.load(locate.project_path("clip.mp4"))
        assert saved.words[2].keyword is True and saved.words[2].edited is True
        assert saved.lines == []  # the style still decides the lines


def test_replace_everywhere_can_teach_the_glossary():
    from farsisub.text.corrections import load_glossary

    with _TempData():
        dialog = _editor("بوهران یک بوهران دو")
        assert dialog.replace_everywhere("بوهران", "بحران", True, True) == 2
        assert load_glossary() == {"بوهران": "بحران"}
        dialog.undo()
        assert "بوهران" in dialog.cues[0].text
        assert dialog.replace_everywhere("نیست", "هست", True, False) == 0


def test_editor_export_uses_the_chosen_format():
    with tempfile.TemporaryDirectory() as folder:
        dialog = _editor(video=str(Path(folder) / "clip.mp4"))
        dialog.config.output_format = "ass"
        dialog.config.output_dir = folder
        from PySide6.QtWidgets import QMessageBox

        original = QMessageBox.information
        QMessageBox.information = staticmethod(lambda *a, **k: None)
        try:
            with _TempData():
                dialog.export()
        finally:
            QMessageBox.information = original
        written = Path(folder) / "clip.ass"
        assert written.exists()
        assert "[V4+ Styles]" in written.read_text(encoding="utf-8-sig")


# ------------------------------------------------------------ main window


def test_main_window_remembers_style_format_and_theme():
    from farsisub.gui.main_window import MainWindow

    with _TempData():
        _qt()
        window = MainWindow(load_settings())
        window.profile_box.setCurrentIndex(window.profile_box.findData("word"))
        window.format_box.setCurrentIndex(window.format_box.findData("vtt"))
        window.toggle_theme()
        again = load_settings()
        assert again.profile.name == "word"
        assert again.output_format == "vtt"
        assert again.theme == "light"
        window.toggle_theme()
        assert load_settings().theme == "dark"


def test_settings_dialog_builds_a_custom_style():
    from farsisub.gui.settings_dialog import SettingsDialog

    _qt()
    config = AppConfig()
    dialog = SettingsDialog(config)
    dialog.mode_box.setCurrentIndex(dialog.mode_box.findData("word"))
    dialog.chars_spin.setValue(24)
    dialog.min_spin.setValue(2.0)
    dialog.max_spin.setValue(1.0)  # below the minimum: lifted to it
    dialog.sensitivity.setValue(80)
    dialog.size_spin.setValue(90)
    dialog.apply_to(config)
    assert config.profile.name == "custom" and config.profile.mode == "word"
    assert config.profile.max_chars_per_line == 24
    assert config.profile.max_duration >= config.profile.min_duration
    assert config.keywords.sensitivity == 0.8
    assert config.ass_style.size == 90


def test_a_search_that_finds_nothing_leaves_the_lines_to_the_style():
    dialog = _editor("یک دو سه")
    assert dialog.replace_everywhere("نیست", "هست", True, False) == 0
    assert dialog.shaped is False and dialog.history == []


def test_saving_the_active_custom_style_applies_it_now():
    from farsisub.gui.settings_dialog import SettingsDialog

    _qt()
    config = AppConfig()
    config.custom_profile = replace(BUILTIN_PROFILES["smart"], name="custom", label="من")
    config.profile = replace(config.custom_profile)
    dialog = SettingsDialog(config)
    dialog.use_custom_box.setChecked(False)
    dialog.chars_spin.setValue(33)
    dialog.apply_to(config)
    assert config.profile.max_chars_per_line == 33


def test_cancelling_a_burn_from_the_progress_window_stops_it():
    import time

    from PySide6.QtWidgets import QApplication, QMessageBox

    from farsisub.gui.editor import EditorDialog

    _qt()
    with tempfile.TemporaryDirectory() as folder, _TempData():
        video = _sample_video(Path(folder) / "clip.mp4", seconds=8.0)
        stream = [Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate("یک دو سه چهار".split())]
        config = AppConfig()
        config.output_dir = folder
        dialog = EditorDialog(Project(video_path=str(video), words=stream), config)
        shown = []
        original = QMessageBox.information
        QMessageBox.information = staticmethod(lambda *a, **k: shown.append(a))
        try:
            dialog.burn_video()
            dialog._burn_progress.canceled.emit()  # what the Cancel button sends
            deadline = time.monotonic() + 30
            while dialog.burn_thread is not None and time.monotonic() < deadline:
                QApplication.processEvents()
                time.sleep(0.01)
        finally:
            QMessageBox.information = original
        assert dialog.burn_thread is None, "the burn never ended"
        assert not shown, "a cancelled burn reported a finished video"
        assert not list(Path(folder).glob("*.subtitled*"))
        dialog.close()
