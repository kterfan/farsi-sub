"""Background transcription for the GUI.

Qt widgets may only be touched from the GUI thread, so the worker talks back
through signals and never renders anything itself.

Thread lifetime is the delicate part: dropping the last Python reference to a
QThread that is still running crashes the process outright. Nothing here is
released until the thread reports `finished`.
"""

from __future__ import annotations

import logging
from pathlib import Path

from PySide6.QtCore import QObject, QThread, Signal

from ..config import AppConfig
from ..engine import whispercpp
from ..pipeline import Cancelled, PipelineError, process

log = logging.getLogger(__name__)

__all__ = ["Cancelled", "Job", "TranscribeWorker"]


class TranscribeWorker(QObject):
    """Runs one file. The queue lives in the window, not here."""

    progress = Signal(int)  # 0..100
    log_line = Signal(str)
    finished = Signal(object, object)  # Project, output Path
    failed = Signal(str)
    # A cancel is not a failure: the window stops the queue on this one
    # instead of showing an error or moving on to the next file. Not called
    # `cancelled`: that name is the property below.
    stopped = Signal()

    def __init__(
        self,
        video: Path,
        config: AppConfig,
        *,
        prompt: str = "",
        glossary: set[str] | None = None,
        suffix: str = ".srt",
    ) -> None:
        super().__init__()
        self.video = video
        self.config = config
        self.prompt = prompt
        self.glossary = glossary
        self.suffix = suffix
        self._cancelled = False

    def cancel(self) -> None:
        """Called from the GUI thread. Stops the engine now, not at its next line.

        The flag comes first: the killed process ends like a failed one, and
        the flag is what tells the pipeline it was a cancel rather than a
        reason to retry on the CPU.
        """
        self._cancelled = True
        whispercpp.stop_running()

    @property
    def cancelled(self) -> bool:
        return self._cancelled

    def run(self) -> None:
        log.info("شروع پردازش: %s", self.video)
        try:
            project, output = process(
                self.video,
                self.config,
                prompt=self.prompt,
                glossary=self.glossary,
                suffix=self.suffix,
                on_progress=self._on_progress,
                on_log=self._on_log,
                checkpoint=self._checkpoint,
            )
        except Cancelled:
            log.info("لغو شد: %s", self.video)
            self.stopped.emit()
        except PipelineError as error:
            log.warning("پردازش ناموفق: %s", error)
            self.failed.emit(str(error))
        except Exception as error:  # noqa: BLE001 - surfaced to the user as text
            log.exception("خطای غیرمنتظره در پردازش %s", self.video)
            self.failed.emit(f"خطای غیرمنتظره: {error}")
        else:
            log.info("انجام شد: %s -> %s (%d کلمه)", self.video, output, len(project.words))
            self.finished.emit(project, output)

    def _checkpoint(self) -> None:
        if self._cancelled:
            raise Cancelled

    def _on_progress(self, percent: int) -> None:
        self._checkpoint()
        self.progress.emit(percent)

    def _on_log(self, message: str) -> None:
        log.debug("whisper: %s", message)
        self.log_line.emit(message)


class Job:
    """Keeps a worker and its thread alive together, and cleans up once."""

    def __init__(self, worker: TranscribeWorker) -> None:
        self.worker = worker
        self.thread = QThread()
        worker.moveToThread(self.thread)
        self.thread.started.connect(worker.run)
        worker.finished.connect(self.thread.quit)
        worker.failed.connect(self.thread.quit)
        worker.stopped.connect(self.thread.quit)

    def start(self) -> None:
        self.thread.start()

    def stop(self, timeout_ms: int = 30_000) -> bool:
        """Ask the worker to stop and wait for the thread to actually end.

        True once the thread is gone. The engine is killed by `cancel`, so
        the wait is normally a fraction of a second; the timeout only covers
        a stage that has no checkpoint, such as decoding the audio.
        """
        self.worker.cancel()
        self.thread.quit()
        if not self.thread.wait(timeout_ms):
            log.error("رشته پردازش در زمان تعیین‌شده تمام نشد")
            return False
        return True
