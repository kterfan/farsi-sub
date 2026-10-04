"""The queue: what runs next after a file finishes, fails or is cancelled."""

from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _window():
    from PySide6.QtWidgets import QApplication

    from farsisub.gui import main_window

    QApplication.instance() or QApplication([])
    os.environ.setdefault("FARSISUB_DATA", tempfile.mkdtemp())
    window = main_window.MainWindow()
    started: list[Path] = []
    window._run = started.append  # record instead of transcribing
    window.add_files([Path("a.mp4"), Path("b.mp4")])
    return window, started, main_window


def test_a_cancelled_file_is_not_started_again():
    window, started, mw = _window()
    window._set_status(Path("a.mp4"), mw.STATUS_CANCELLED)
    window.stop_requested = True  # what pressing cancel sets
    window._continue_queue()
    assert started == []
    assert window.stop_requested is False


def test_a_failed_file_is_not_retried_by_itself():
    # A file that always fails used to run again and again, an error each time.
    window, started, mw = _window()
    window._set_status(Path("a.mp4"), mw.STATUS_FAILED)
    window._continue_queue()
    assert started == [Path("b.mp4")]


def test_the_start_button_does_retry_failed_and_cancelled_files():
    window, started, mw = _window()
    window._set_status(Path("a.mp4"), mw.STATUS_CANCELLED)
    window._set_status(Path("b.mp4"), mw.STATUS_DONE)
    window.start_queue()
    assert started == [Path("a.mp4")]


def _wait_until(condition, seconds: float = 10.0) -> bool:
    import time

    from PySide6.QtWidgets import QApplication

    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        QApplication.processEvents()
        if condition():
            return True
        time.sleep(0.01)
    return False


def test_cancel_through_a_real_job_stops_the_whole_queue():
    # The whole path: worker thread, signals, the window's slots. Only the
    # transcription itself is replaced by a loop that waits to be cancelled.
    import time

    from PySide6.QtWidgets import QApplication

    from farsisub.gui import main_window, worker

    QApplication.instance() or QApplication([])
    os.environ.setdefault("FARSISUB_DATA", tempfile.mkdtemp())

    def endless(*_args, checkpoint=None, **_kwargs):
        while True:
            checkpoint()
            time.sleep(0.01)

    original = worker.process
    worker.process = endless
    try:
        window = main_window.MainWindow()
        window.add_files([Path("a.mp4"), Path("b.mp4")])
        window.start_queue()
        assert window.job is not None
        window.cancel()
        assert _wait_until(lambda: window.job is None), "the job never finished"
        _wait_until(lambda: False, 0.2)  # let any queued follow-up run
        assert window.job is None, "the queue moved on after a cancel"
        assert window.table.item(0, 1).text() == main_window.STATUS_CANCELLED
        assert window.table.item(1, 1).text() == main_window.STATUS_QUEUED
    finally:
        worker.process = original
