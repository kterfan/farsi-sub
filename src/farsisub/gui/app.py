"""GUI entry point: python -m farsisub.gui"""

from __future__ import annotations

import sys

from PySide6.QtCore import Qt
from PySide6.QtGui import QFont
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication

from ..config import load_settings
from ..logging_setup import setup as setup_logging
from . import theme
from .first_run import FirstRunDialog
from .main_window import MainWindow


def build_app(argv: list[str] | None = None) -> tuple[QApplication, MainWindow]:
    # pythonw.exe has no console: without a log file a crash leaves no trace.
    setup_logging()
    app = QApplication.instance() or QApplication(argv or sys.argv)
    app.setApplicationName("FarsiSub")
    app.setLayoutDirection(Qt.RightToLeft)

    theme.load_fonts()
    app.setFont(QFont(theme.FONT_FAMILY, theme.FONT_BODY))
    config = load_settings()
    theme.apply(app, config.theme)

    window = MainWindow(config)
    return app, window


def ensure_model(window: MainWindow) -> None:
    """A fresh install has no model; ask for one before the main window."""
    from ..engine import locate

    if locate.installed_models():
        return
    dialog = FirstRunDialog(window)
    dialog.exec()
    window._refresh_model_state()


SOCKET_NAME = "farsisub-single-instance"


def _already_running() -> bool:
    """True when another copy is up; it is raised instead of a second window.

    Every shortcut press used to open a fresh window, so an old one -- started
    before a model was installed -- could still be on screen showing a stale
    model list.
    """
    probe = QLocalSocket()
    probe.connectToServer(SOCKET_NAME)
    if not probe.waitForConnected(300):
        return False

    probe.write(b"raise")
    probe.flush()
    probe.waitForBytesWritten(300)

    # A crashed instance can leave its pipe behind on Windows: connecting then
    # succeeds and this copy would exit silently, so the app "does not open".
    # Only a live instance answers, so an unanswered probe means carry on.
    alive = probe.waitForReadyRead(600) and bool(probe.readAll())
    probe.disconnectFromServer()
    return alive


def _listen(window) -> QLocalServer:
    """Accept the wake-up from later launches."""
    QLocalServer.removeServer(SOCKET_NAME)
    server = QLocalServer(window)

    def wake() -> None:
        connection = server.nextPendingConnection()
        if connection is not None:
            # The reply is what proves this instance is alive, not merely a
            # pipe left behind by a crash.
            connection.write(b"ok")
            connection.flush()
            connection.waitForBytesWritten(300)
            connection.disconnectFromServer()
        window.showNormal()
        window.raise_()
        window.activateWindow()
        window.refresh_models()

    server.newConnection.connect(wake)
    server.listen(SOCKET_NAME)
    return server


def main() -> int:
    app, window = build_app()
    if _already_running():
        return 0  # the running copy was raised instead
    window._single_instance_server = _listen(window)
    window.show()
    ensure_model(window)
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
