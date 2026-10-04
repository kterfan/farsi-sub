"""1.8: rows that wrap instead of hiding buttons, and the new controls."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))


def _qt():
    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    app.setLayoutDirection(Qt.RightToLeft)
    return app


def _settle(ms: int = 50) -> None:
    from PySide6.QtCore import QEventLoop, QTimer

    loop = QEventLoop()
    QTimer.singleShot(ms, loop.quit)
    loop.exec()


def _row(width: int, priorities=(1, 1, 2, 2, 3, 3)):
    from PySide6.QtWidgets import QVBoxLayout, QWidget

    from farsisub.gui.widgets import ActionButton, ResponsiveRow

    _qt()
    window = QWidget()
    column = QVBoxLayout(window)
    row = ResponsiveRow()
    buttons = []
    for index, priority in enumerate(priorities):
        button = ActionButton(f"دکمه شماره {index}", "split", priority=priority)
        row.add(button)
        buttons.append(button)
    column.addWidget(row)
    column.addStretch(1)
    window.resize(width, 400)
    window.show()
    _settle()
    return window, row, buttons


def _inside(widget, window) -> bool:
    from PySide6.QtCore import QRect

    top_left = widget.mapTo(window, widget.rect().topLeft())
    return window.rect().contains(QRect(top_left, widget.size()))


def test_a_wide_row_keeps_every_label():
    window, row, buttons = _row(2400)
    assert not any(b.compact for b in buttons)
    window.close()


def test_labels_go_least_important_first():
    window, row, buttons = _row(2400)
    # Just too narrow for every label: only the lowest priority gives way.
    width = row.width_at(1) + 20
    window.resize(width + 24, 400)
    _settle()
    assert [b.compact for b in buttons] == [True, True, False, False, False, False]
    window.close()


def test_a_narrow_row_wraps_and_hides_nothing():
    window, row, buttons = _row(160)
    assert all(b.compact for b in buttons)
    for button in buttons:
        assert button.isVisible()
        assert _inside(button, window)
    # Wrapping costs height, never a button.
    assert row.heightForWidth(140) > row.heightForWidth(2000)
    window.close()


def test_a_compact_button_still_says_what_it_does():
    from farsisub.gui.widgets import ActionButton

    _qt()
    button = ActionButton("تقسیم", "split")
    button.setToolTip("این خط را دو تکه کن")
    button.set_compact(True)
    assert "تقسیم" in button.toolTip()
    assert button.sizeHint().width() == button.sizeHint().height()
    button.set_compact(False)
    assert button.toolTip() == "این خط را دو تکه کن"
    assert button.sizeHint().width() > button.sizeHint().height()


def test_the_switch_is_still_a_checkbox():
    from farsisub.gui.widgets import ToggleSwitch

    _qt()
    seen = []
    switch = ToggleSwitch("ارقام فارسی")
    switch.toggled.connect(seen.append)
    switch.setChecked(True)
    switch.click()
    assert seen == [True, False]
    assert not switch.isChecked()


def test_every_icon_draws():
    from farsisub.gui import icons

    _qt()
    for name in icons.SHAPES:
        image = icons.pixmap(name, "#000000", 24, 1.0).toImage()
        painted = sum(
            1 for x in range(24) for y in range(24) if image.pixelColor(x, y).alpha() > 0
        )
        assert painted > 10, name


def test_every_editor_command_is_on_screen_in_a_small_window():
    """The complaint that started it: a small editor lost its buttons."""
    from farsisub.config import AppConfig
    from farsisub.gui.editor import EditorDialog
    from farsisub.models import Project, Word

    _qt()
    words = [Word(text=t, start=i * 0.5, end=i * 0.5 + 0.4) for i, t in enumerate("یک دو سه چهار".split())]
    dialog = EditorDialog(Project(video_path="x.mp4", words=words), AppConfig())
    dialog.resize(560, 520)
    dialog.show()
    _settle(100)
    for button in (
        dialog.undo_button,
        dialog.redo_button,
        dialog.split_button,
        dialog.merge_button,
        dialog.delete_button,
        dialog.word_up_button,
        dialog.word_down_button,
        dialog.zwnj_button,
        dialog.glossary_button,
        dialog.find_button,
        dialog.burn_button,
        dialog.export_button,
        dialog.style_box,
    ):
        assert button.isVisible(), button.objectName() or type(button).__name__
        assert _inside(button, dialog), getattr(button, "text", lambda: "")()
    dialog.close()
