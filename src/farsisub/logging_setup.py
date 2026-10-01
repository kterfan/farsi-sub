"""Write everything to a log file.

The GUI runs under pythonw.exe, which has no console: without this, a crash
leaves nothing behind but a closed window. Uncaught exceptions, Qt warnings
and worker output all end up in one file the user can send over.
"""

from __future__ import annotations

import faulthandler
import logging
import logging.handlers
import sys
import traceback
from pathlib import Path

from . import __version__
from .engine import locate

LOG_NAME = "farsisub.log"
_configured = False


def log_dir() -> Path:
    path = locate.data_dir() / "logs"
    path.mkdir(parents=True, exist_ok=True)
    return path


def log_path() -> Path:
    return log_dir() / LOG_NAME


def setup(level: int = logging.INFO) -> Path:
    """Configure file + stderr logging once, and catch anything uncaught."""
    global _configured
    target = log_path()
    if _configured:
        return target

    handler = logging.handlers.RotatingFileHandler(
        target, maxBytes=2_000_000, backupCount=3, encoding="utf-8"
    )
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)-7s %(name)s: %(message)s")
    )

    root = logging.getLogger()
    root.setLevel(level)
    root.addHandler(handler)
    if sys.stderr is not None:
        stream = logging.StreamHandler(sys.stderr)
        stream.setFormatter(logging.Formatter("%(levelname)-7s %(message)s"))
        root.addHandler(stream)

    def hook(exc_type, exc, tb) -> None:
        if issubclass(exc_type, KeyboardInterrupt):
            sys.__excepthook__(exc_type, exc, tb)
            return
        root.critical("خطای گرفته‌نشده:\n%s", "".join(traceback.format_exception(exc_type, exc, tb)))

    sys.excepthook = hook

    # A Qt or CUDA level crash kills the process without raising in Python.
    # faulthandler writes the native stack into the same log instead of
    # leaving nothing behind but a closed window.
    try:
        crash_file = open(log_dir() / "crash.log", "a", encoding="utf-8", buffering=1)
        faulthandler.enable(file=crash_file, all_threads=True)
    except Exception:
        pass

    try:  # Qt warnings are often the only clue for a native crash
        from PySide6.QtCore import QtMsgType, qInstallMessageHandler

        levels = {
            QtMsgType.QtDebugMsg: logging.DEBUG,
            QtMsgType.QtInfoMsg: logging.INFO,
            QtMsgType.QtWarningMsg: logging.WARNING,
            QtMsgType.QtCriticalMsg: logging.ERROR,
            QtMsgType.QtFatalMsg: logging.CRITICAL,
        }

        def qt_handler(mode, context, message) -> None:
            logging.getLogger("qt").log(levels.get(mode, logging.INFO), message)

        qInstallMessageHandler(qt_handler)
    except Exception:  # pragma: no cover - Qt not installed in some contexts
        pass

    _configured = True
    root.info("--- FarsiSub %s شروع شد | python %s ---", __version__, sys.version.split()[0])
    # Where the app is looking, so a "no models" report can be diagnosed from
    # the log instead of guessed at.
    try:
        root.info("پوشه اجرا : %s", locate.install_dir())
        root.info("پوشه موتور: %s (whisper-cli: %s)", locate.bin_dir(), locate.whisper_binary())
        root.info("پوشه داده : %s", locate.data_dir())
        root.info("مدل‌ها    : %s", locate.installed_models() or "هیچ")
    except Exception as error:  # never let logging break startup
        root.warning("گزارش مسیرها ناموفق: %s", error)
    return target
