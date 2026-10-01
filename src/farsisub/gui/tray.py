"""The icon beside the clock: progress while working, a notice when done.

A long file runs for minutes; the window is usually behind something else by
then. The icon shows a ring that fills as the file goes, its tooltip names
the file and the percentage, and Windows pops a notice when it is finished.
"""

from __future__ import annotations

from PySide6.QtCore import QObject
from PySide6.QtWidgets import QMenu, QSystemTrayIcon

from .. import brand
from ..text.normalize import to_persian_digits


class Tray(QObject):
    # Redrawing the icon is cheap, but not every percent needs a new one.
    STEP = 2

    def __init__(self, window) -> None:
        super().__init__(window)
        self.window = window
        self.available = QSystemTrayIcon.isSystemTrayAvailable()
        self.tooltip = brand.APP_NAME
        self.last_message: tuple[str, str] | None = None
        self.progress: int | None = None
        self.icon = QSystemTrayIcon(brand.app_icon(), self)
        self.icon.setToolTip(self.tooltip)
        self.icon.activated.connect(self._activated)
        self.icon.messageClicked.connect(self.window.bring_to_front)

        menu = QMenu()
        menu.addAction("نمایش FarsiSub", self.window.bring_to_front)
        self.cancel_action = menu.addAction("لغو پردازش", self.window.cancel)
        self.cancel_action.setEnabled(False)
        menu.addAction("باز کردن پوشه خروجی", self.window.open_output_folder)
        menu.addSeparator()
        menu.addAction("درباره", self.window.open_about)
        menu.addAction("خروج", self.window.close)
        self.menu = menu
        self.icon.setContextMenu(menu)
        if self.available:
            self.icon.show()

    # ------------------------------------------------------------- state

    def _set_tooltip(self, text: str) -> None:
        self.tooltip = text
        self.icon.setToolTip(text)

    def _notify(self, title: str, text: str, icon=QSystemTrayIcon.Information) -> None:
        self.last_message = (title, text)
        if self.available and QSystemTrayIcon.supportsMessages():
            self.icon.showMessage(title, text, icon, 6000)

    def working(self, name: str, percent: int) -> None:
        self.cancel_action.setEnabled(True)
        stepped = percent - percent % self.STEP
        if stepped != self.progress:
            self.progress = stepped
            self.icon.setIcon(brand.app_icon(progress=stepped / 100))
        self._set_tooltip(f"{brand.APP_NAME} — {to_persian_digits(str(percent))}٪ · {name}")

    def idle(self) -> None:
        self.progress = None
        self.cancel_action.setEnabled(False)
        self.icon.setIcon(brand.app_icon())
        self._set_tooltip(brand.APP_NAME)

    def finished(self, name: str, output: str) -> None:
        self.idle()
        self._notify("زیرنویس آماده شد", f"{name}\n{output}")

    def failed(self, name: str, message: str) -> None:
        self.idle()
        self._notify("پردازش انجام نشد", f"{name}\n{message}", QSystemTrayIcon.Warning)

    def cancelled(self, name: str) -> None:
        self.idle()
        self._notify("لغو شد", name)

    def queue_done(self, count: int) -> None:
        self.idle()
        self._notify("صف تمام شد", f"{to_persian_digits(str(count))} فایل پردازش شد")

    def _activated(self, reason) -> None:
        if reason in (QSystemTrayIcon.Trigger, QSystemTrayIcon.DoubleClick):
            self.window.bring_to_front()

    def hide(self) -> None:
        self.icon.hide()
