"""Stopping a run has to stop the engine, not just the progress bar.

whisper-cli is replaced by a small Python process that prints lines and keeps
a heartbeat file growing, so the tests can see whether it is really gone.
"""

from __future__ import annotations

import sys
import tempfile
import threading
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub import pipeline  # noqa: E402
from farsisub.config import AppConfig  # noqa: E402
from farsisub.engine import whispercpp  # noqa: E402
from farsisub.engine.whispercpp import WhisperOptions  # noqa: E402
from farsisub.models import EditedLine, Project, Word  # noqa: E402

# Prints a line, then beats (appending to a file) without printing anything
# else, the way whisper-cli goes quiet while it decodes a long window.
FAKE_ENGINE = r"""
import sys, time
beat = sys.argv[1]
print("progress = 1%", flush=True)
for _ in range(600):
    with open(beat, "a") as f:
        f.write(".")
    if "--chatty" in sys.argv:
        print("whisper_full: decoding", flush=True)
    time.sleep(0.05)
"""


def _fake_engine(beat: Path, *extra: str):
    def build(opts, audio, out_prefix):
        return [sys.executable, "-u", "-c", FAKE_ENGINE, str(beat), *extra]

    return build


def _options() -> WhisperOptions:
    return WhisperOptions(binary=Path("whisper-cli"), model=Path("model.bin"))


def _still_beating(beat: Path) -> bool:
    before = beat.stat().st_size if beat.exists() else 0
    time.sleep(0.4)
    after = beat.stat().st_size if beat.exists() else 0
    return after > before


def _with_fake(beat: Path, *extra: str):
    original = whispercpp.build_command
    whispercpp.build_command = _fake_engine(beat, *extra)
    return original


def test_raising_from_a_callback_kills_the_engine():
    with tempfile.TemporaryDirectory() as folder:
        beat = Path(folder) / "beat"
        original = _with_fake(beat, "--chatty")
        try:
            seen = []

            def checkpoint() -> None:
                seen.append(1)
                if len(seen) > 3:
                    raise pipeline.Cancelled

            try:
                whispercpp.run(_options(), Path("a.wav"), Path(folder) / "out", checkpoint=checkpoint)
            except pipeline.Cancelled:
                pass
            else:
                raise AssertionError("the cancel did not stop the run")
            assert not _still_beating(beat), "whisper-cli kept running after the cancel"
        finally:
            whispercpp.build_command = original


def test_stop_running_ends_a_silent_engine_at_once():
    # The engine prints nothing for half a minute; waiting for its next line
    # is what made closing the window hang and then crash.
    with tempfile.TemporaryDirectory() as folder:
        beat = Path(folder) / "beat"
        original = _with_fake(beat)
        cancelled = threading.Event()

        def checkpoint() -> None:
            if cancelled.is_set():
                raise pipeline.Cancelled

        def press_cancel() -> None:
            time.sleep(0.5)
            cancelled.set()
            whispercpp.stop_running()

        try:
            threading.Thread(target=press_cancel, daemon=True).start()
            started = time.monotonic()
            try:
                whispercpp.run(_options(), Path("a.wav"), Path(folder) / "out", checkpoint=checkpoint)
            except pipeline.Cancelled:
                pass
            else:
                raise AssertionError("a killed run must end as a cancel, not be retried on the CPU")
            assert time.monotonic() - started < 5.0
            assert not _still_beating(beat)
        finally:
            whispercpp.build_command = original


def test_a_cancel_is_not_mistaken_for_a_failed_second_model():
    # The second pass catches every Exception so a crash there cannot lose the
    # first pass. A cancel caught there was logged and the run went on.
    config = AppConfig()
    config.merge_model = "other"
    original_run, original_path = pipeline.run, pipeline.locate.model_path

    def cancelled_run(*_args, **_kwargs):
        raise pipeline.Cancelled

    pipeline.run = cancelled_run
    pipeline.locate.model_path = lambda name: Path("ggml-other.bin")
    try:
        words = [Word(text="سلام", start=0.0, end=0.5)]
        try:
            pipeline._fill_with_second_model(
                words, config, _options(), Path("a.wav"), Path(".")
            )
        except pipeline.Cancelled:
            pass
        else:
            raise AssertionError("the second model swallowed the cancel")
    finally:
        pipeline.run, pipeline.locate.model_path = original_run, original_path


def test_the_transcript_is_saved_even_if_the_subtitle_cannot_be_written():
    import os

    project = Project(video_path="clip.mp4", words=[Word(text="سلام", start=0.0, end=0.5)])
    original_transcribe, original_render = pipeline.transcribe, pipeline.render

    def failing_render(*_args, **_kwargs):
        raise PermissionError("the subtitle is open in a player")

    with tempfile.TemporaryDirectory() as home:
        previous = os.environ.get("FARSISUB_DATA")
        os.environ["FARSISUB_DATA"] = home
        pipeline.transcribe = lambda *a, **k: project
        pipeline.render = failing_render
        try:
            try:
                pipeline.process("clip.mp4", AppConfig())
            except PermissionError:
                pass
            assert pipeline.locate.project_path("clip.mp4").exists()
        finally:
            pipeline.transcribe, pipeline.render = original_transcribe, original_render
            if previous is None:
                os.environ.pop("FARSISUB_DATA", None)
            else:
                os.environ["FARSISUB_DATA"] = previous


def test_rendering_a_project_keeps_the_lines_shaped_by_hand():
    words = [
        Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4)
        for i, t in enumerate("یک دو سه چهار".split())
    ]
    project = Project(
        video_path="clip.mp4",
        words=words,
        lines=[
            EditedLine(words=[0, 1], text="متن دست‌ساز", edited=True),
            EditedLine(words=[2, 3], text="سه چهار"),
        ],
    )
    with tempfile.TemporaryDirectory() as folder:
        config = AppConfig()
        config.output_dir = folder
        written = pipeline.render(project, config).read_text(encoding="utf-8-sig")
    assert "متن دست‌ساز" in written
    assert "یک دو" not in written
