"""The editor's extra tools: waveform, find and replace, burning a video.

Kept apart from editor.py, which is long enough already. The pure functions at
the top carry the logic and are tested without a window.
"""

from __future__ import annotations

import logging
import re
import tempfile
from pathlib import Path
from typing import Callable

from PySide6.QtCore import QObject, QPointF, QRectF, Qt, Signal
from PySide6.QtGui import QColor, QPainter, QPen
from PySide6.QtWidgets import (
    QCheckBox,
    QDialog,
    QFormLayout,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QPushButton,
    QVBoxLayout,
    QWidget,
)

from . import theme

log = logging.getLogger(__name__)

# The shortest a line may become by dragging one of its edges.
MIN_LINE = 0.1
# How far the waveform reaches on each side of the current line.
WAVE_SPAN = 6.0


# ----------------------------------------------------------------- pure logic


def move_edge(cues, row: int, which: str, seconds: float) -> float:
    """Move the start or the end of one line; return where it landed.

    The line's time comes from its words, so the edge moves the first word's
    start or the last word's end. It stops at the neighbouring line, never
    leaves a line shorter than MIN_LINE, and never moves a start past the end
    of the word it belongs to.
    """
    cue = cues[row]
    if not cue.words:
        return seconds
    if which == "start":
        floor = cues[row - 1].end if row > 0 and cues[row - 1].words else 0.0
        ceiling = min(cue.end - MIN_LINE, cue.words[0].end - 0.02)
        value = max(floor, min(seconds, ceiling))
        cue.words[0].start = value
        return value
    floor = max(cue.start + MIN_LINE, cue.words[-1].start + 0.02)
    ceiling = cues[row + 1].start if row + 1 < len(cues) and cues[row + 1].words else float("inf")
    value = min(ceiling, max(seconds, floor))
    cue.words[-1].end = value
    return value


def replace_in_text(text: str, find: str, replacement: str, whole_word: bool) -> tuple[str, int]:
    """Replace in one line; (new text, how many replaced)."""
    if not find:
        return text, 0
    if whole_word:
        pattern = rf"(?<![\w‌]){re.escape(find)}(?![\w‌])"
    else:
        pattern = re.escape(find)
    return re.subn(pattern, lambda _m: replacement, text)


def replace_in_cues(cues, find: str, replacement: str, whole_word: bool = True) -> int:
    """Replace across every line; how many replacements were made."""
    total = 0
    for cue in cues:
        fixed, count = replace_in_text(cue.text, find, replacement, whole_word)
        if count:
            cue.text = fixed
            cue.edited = True
            total += count
    return total


# ------------------------------------------------------------------ waveform


class _Stop(BaseException):
    """The editor closed while the waveform was still being read."""


class EnvelopeWorker(QObject):
    """Decodes the audio once, off the GUI thread, for the waveform."""

    ready = Signal(object)  # numpy array of 10 ms loudness bins
    failed = Signal(str)

    def __init__(self, media: Path) -> None:
        super().__init__()
        self.media = media
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _checkpoint(self) -> None:
        if self._cancelled:
            raise _Stop

    def run(self) -> None:
        from ..engine import audio

        try:
            with tempfile.TemporaryDirectory(prefix="farsisub-wave-") as folder:
                wav = audio.extract_wav(
                    self.media, Path(folder) / "audio.wav", checkpoint=self._checkpoint
                )
                envelope = audio.energy_envelope(wav, checkpoint=self._checkpoint)
        except _Stop:
            self.failed.emit("لغو شد")
            return
        except Exception as error:  # noqa: BLE001 - the waveform is a convenience
            log.warning("موج صدا ساخته نشد: %s", error)
            self.failed.emit(str(error))
            return
        self.ready.emit(envelope)


class WaveformStrip(QWidget):
    """The sound around the current line, with the lines drawn over it.

    Drag the edge of the highlighted line to move it; click anywhere else to
    send the video there.
    """

    edge_moved = Signal(str, float)  # "start" / "end", seconds
    seek = Signal(float)

    GRAB = 6  # pixels either side of an edge that still count as "on" it

    def __init__(self, parent: QWidget | None = None) -> None:
        super().__init__(parent)
        self.setMinimumHeight(70)
        self.setMaximumHeight(90)
        self.setMouseTracking(True)
        self.setLayoutDirection(Qt.LeftToRight)  # time runs left to right
        self.envelope = None
        self.peak = 1.0
        self.spans: list[tuple[float, float]] = []
        self.current = -1
        self.playhead = -1.0
        self.window = (0.0, WAVE_SPAN * 2)
        self.dragging: str | None = None
        self.drag_at = 0.0
        self.message = "در حال خواندن صدا…"

    # data
    def set_envelope(self, envelope) -> None:
        import numpy as np

        self.envelope = envelope
        self.peak = float(np.percentile(envelope, 99)) if len(envelope) else 1.0
        self.peak = self.peak or 1.0
        self.update()

    def set_failed(self, message: str) -> None:
        self.message = "موج صدا در دسترس نیست"
        self.setToolTip(message)
        self.update()

    def set_lines(self, spans: list[tuple[float, float]], current: int) -> None:
        self.spans = spans
        self.current = current
        if 0 <= current < len(spans):
            start, end = spans[current]
            middle = (start + end) / 2
            half = max(WAVE_SPAN, (end - start) / 2 + 1.0)
            self.window = (max(0.0, middle - half), middle + half)
        self.update()

    def set_playhead(self, seconds: float) -> None:
        self.playhead = seconds
        self.update()

    # geometry
    def x_of(self, seconds: float) -> float:
        start, end = self.window
        return (seconds - start) / max(end - start, 1e-6) * self.width()

    def seconds_at(self, x: float) -> float:
        start, end = self.window
        return start + x / max(self.width(), 1) * (end - start)

    def _edge_near(self, x: float) -> str | None:
        if not (0 <= self.current < len(self.spans)):
            return None
        start, end = self.spans[self.current]
        if abs(x - self.x_of(start)) <= self.GRAB:
            return "start"
        if abs(x - self.x_of(end)) <= self.GRAB:
            return "end"
        return None

    # painting
    def paintEvent(self, event) -> None:  # noqa: N802 - Qt naming
        palette = theme.LIGHT
        painter = QPainter(self)
        painter.setRenderHint(QPainter.Antialiasing)
        painter.fillRect(self.rect(), QColor(palette.surface_alt))
        height = self.height()

        for index, (start, end) in enumerate(self.spans):
            if end < self.window[0] or start > self.window[1]:
                continue
            left, right = self.x_of(start), self.x_of(end)
            colour = QColor(palette.accent if index == self.current else palette.border_strong)
            colour.setAlpha(70 if index == self.current else 45)
            painter.fillRect(QRectF(left, 0, max(1.0, right - left), height), colour)

        if self.envelope is None or not len(self.envelope):
            painter.setPen(QColor(palette.text_muted))
            painter.drawText(self.rect(), Qt.AlignCenter, self.message)
        else:
            painter.setPen(QPen(QColor(palette.text_muted), 1))
            bins = len(self.envelope)
            middle = height / 2
            for x in range(self.width()):
                first = int(self.seconds_at(x) * 100)
                last = max(first + 1, int(self.seconds_at(x + 1) * 100))
                if first >= bins or last <= 0:
                    continue
                value = float(self.envelope[max(0, first) : min(bins, last)].max())
                half = min(1.0, value / self.peak) * (height / 2 - 4)
                painter.drawLine(QPointF(x, middle - half), QPointF(x, middle + half))

        if 0 <= self.current < len(self.spans):
            pen = QPen(QColor(palette.accent), 3)
            painter.setPen(pen)
            for edge in self.spans[self.current]:
                x = self.x_of(edge)
                painter.drawLine(QPointF(x, 0), QPointF(x, height))
        if self.window[0] <= self.playhead <= self.window[1]:
            painter.setPen(QPen(QColor(palette.danger), 2))
            x = self.x_of(self.playhead)
            painter.drawLine(QPointF(x, 0), QPointF(x, height))
        painter.end()

    # mouse
    def mousePressEvent(self, event) -> None:  # noqa: N802 - Qt naming
        x = event.position().x()
        self.dragging = self._edge_near(x)
        if self.dragging is None:
            self.seek.emit(self.seconds_at(x))

    def mouseMoveEvent(self, event) -> None:  # noqa: N802 - Qt naming
        x = event.position().x()
        if self.dragging is not None and 0 <= self.current < len(self.spans):
            start, end = self.spans[self.current]
            self.drag_at = self.seconds_at(x)
            self.spans[self.current] = (self.drag_at, end) if self.dragging == "start" else (start, self.drag_at)
            self.update()
            return
        self.setCursor(Qt.SizeHorCursor if self._edge_near(x) else Qt.PointingHandCursor)

    def mouseReleaseEvent(self, event) -> None:  # noqa: N802 - Qt naming
        if self.dragging is not None:
            which, self.dragging = self.dragging, None
            self.edge_moved.emit(which, self.seconds_at(event.position().x()))


# ------------------------------------------------------------ find / replace


class FindReplaceDialog(QDialog):
    """Ctrl+H: one wrong word, fixed on every line at once."""

    def __init__(self, on_replace: Callable[[str, str, bool, bool], int], parent=None) -> None:
        super().__init__(parent)
        self.on_replace = on_replace
        self.setWindowTitle("جستجو و جایگزینی")
        self.setLayoutDirection(Qt.RightToLeft)
        layout = QVBoxLayout(self)
        form = QFormLayout()
        self.find_edit = QLineEdit()
        self.replace_edit = QLineEdit()
        form.addRow("پیدا کن", self.find_edit)
        form.addRow("جایگزین کن با", self.replace_edit)
        layout.addLayout(form)
        self.whole_box = QCheckBox("فقط کلمه کامل")
        self.whole_box.setChecked(True)
        self.glossary_box = QCheckBox("به دیکشنری هم اضافه شود (برای ویدیوهای بعدی)")
        layout.addWidget(self.whole_box)
        layout.addWidget(self.glossary_box)
        self.result = QLabel("")
        self.result.setObjectName("Muted")
        layout.addWidget(self.result)
        buttons = QHBoxLayout()
        replace_all = QPushButton("جایگزین همه")
        replace_all.setObjectName("Primary")
        replace_all.clicked.connect(self._replace)
        close = QPushButton("بستن")
        close.clicked.connect(self.accept)
        buttons.addStretch(1)
        buttons.addWidget(close)
        buttons.addWidget(replace_all)
        layout.addLayout(buttons)

    def _replace(self) -> None:
        find = self.find_edit.text().strip()
        if not find:
            self.result.setText("اول بنویس دنبال چه بگردم")
            return
        count = self.on_replace(
            find, self.replace_edit.text().strip(), self.whole_box.isChecked(), self.glossary_box.isChecked()
        )
        self.result.setText(f"{count} مورد جایگزین شد" if count else "پیدا نشد")


# ------------------------------------------------------------------ burning


class BurnWorker(QObject):
    """Draws the subtitle into the video on its own thread."""

    progress = Signal(int)
    finished = Signal(str)
    failed = Signal(str)
    stopped = Signal()

    def __init__(self, video: Path, cues, style, target: Path) -> None:
        super().__init__()
        self.video, self.cues, self.style, self.target = video, cues, style, target
        self._cancelled = False

    def cancel(self) -> None:
        self._cancelled = True

    def _checkpoint(self) -> None:
        if self._cancelled:
            from ..pipeline import Cancelled

            raise Cancelled

    def run(self) -> None:
        from ..pipeline import Cancelled
        from ..render.burn import burn

        try:
            out = burn(
                self.video,
                self.cues,
                self.style,
                self.target,
                on_progress=self.progress.emit,
                checkpoint=self._checkpoint,
            )
        except Cancelled:
            self.stopped.emit()
        except Exception as error:  # noqa: BLE001 - shown to the user
            log.exception("ساخت ویدیو با زیرنویس شکست خورد")
            self.failed.emit(str(error))
        else:
            self.finished.emit(str(out))
