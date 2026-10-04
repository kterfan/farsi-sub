"""The interface's icons, drawn in code.

Like the logo, they are painted rather than shipped as files: nothing to add
to the installer, they stay sharp at any scaling, and they take whatever
colour the theme gives them. Each one is a few strokes on a 24-unit grid with
round caps -- the same visual language as the common open icon sets.
"""

from __future__ import annotations

import math
from typing import Callable

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, QPixmap

GRID = 24.0
STROKE = 2.0

# A painter receives a path to stroke and one to fill, both in grid units.
Drawer = Callable[[QPainterPath, QPainterPath], None]


def _poly(path: QPainterPath, *points: tuple[float, float], close: bool = False) -> None:
    path.moveTo(*points[0])
    for point in points[1:]:
        path.lineTo(*point)
    if close:
        path.closeSubpath()


def _arc(path: QPainterPath, cx: float, cy: float, r: float, start: float, sweep: float,
         move: bool = True) -> None:
    """An arc in degrees, Qt's way: 0 at three o'clock, positive anticlockwise."""
    rect = QRectF(cx - r, cy - r, 2 * r, 2 * r)
    if move:
        path.arcMoveTo(rect, start)
    path.arcTo(rect, start, sweep)


def _dot(path: QPainterPath, x: float, y: float, r: float = 1.25) -> None:
    path.addEllipse(QPointF(x, y), r, r)


# ------------------------------------------------------------------- shapes


def _play(s, f):
    f.moveTo(8, 5.2)
    f.lineTo(19, 12)
    f.lineTo(8, 18.8)
    f.closeSubpath()
    s.addPath(f)


def _pause(s, f):
    f.addRoundedRect(QRectF(6.5, 5, 3.6, 14), 1.2, 1.2)
    f.addRoundedRect(QRectF(13.9, 5, 3.6, 14), 1.2, 1.2)


def _stop(s, f):
    s.addRoundedRect(QRectF(6, 6, 12, 12), 2.5, 2.5)


def _undo(s, f):
    _poly(s, (9, 4), (4, 9), (9, 14))
    s.moveTo(4, 9)
    s.lineTo(14.5, 9)
    _arc(s, 14.5, 14, 5, 90, -180, move=False)
    s.lineTo(11, 19)


def _redo(s, f):
    _poly(s, (15, 4), (20, 9), (15, 14))
    s.moveTo(20, 9)
    s.lineTo(9.5, 9)
    _arc(s, 9.5, 14, 5, 90, 180, move=False)
    s.lineTo(13, 19)


def _scissors(s, f):
    s.addEllipse(QPointF(6, 6), 3, 3)
    s.addEllipse(QPointF(6, 18), 3, 3)
    _poly(s, (20, 4), (8.1, 15.9))
    _poly(s, (14.5, 14.5), (20, 20))
    _poly(s, (8.1, 8.1), (12, 12))


def _merge(s, f):
    s.moveTo(6, 3.5)
    s.lineTo(6, 7)
    s.cubicTo(6, 11, 12, 11, 12, 14.5)
    s.moveTo(18, 3.5)
    s.lineTo(18, 7)
    s.cubicTo(18, 11, 12, 11, 12, 14.5)
    s.lineTo(12, 20.5)
    _poly(s, (8.5, 17), (12, 20.5), (15.5, 17))


def _trash(s, f):
    _poly(s, (3.5, 6.5), (20.5, 6.5))
    s.moveTo(9, 6.5)
    s.lineTo(9, 4.5)
    s.quadTo(9, 3.5, 10, 3.5)
    s.lineTo(14, 3.5)
    s.quadTo(15, 3.5, 15, 4.5)
    s.lineTo(15, 6.5)
    s.moveTo(5.5, 6.5)
    s.lineTo(6.5, 18.5)
    s.quadTo(6.7, 20.5, 8.7, 20.5)
    s.lineTo(15.3, 20.5)
    s.quadTo(17.3, 20.5, 17.5, 18.5)
    s.lineTo(18.5, 6.5)
    _poly(s, (10, 10.5), (10, 16.5))
    _poly(s, (14, 10.5), (14, 16.5))


def _word_up(s, f):
    _poly(s, (5, 3.5), (19, 3.5))
    _poly(s, (12, 20.5), (12, 8))
    _poly(s, (7, 13), (12, 8), (17, 13))


def _word_down(s, f):
    _poly(s, (5, 20.5), (19, 20.5))
    _poly(s, (12, 3.5), (12, 16))
    _poly(s, (7, 11), (12, 16), (17, 11))


def _space(s, f):
    s.moveTo(3.5, 10)
    s.lineTo(3.5, 14)
    s.quadTo(3.5, 16, 5.5, 16)
    s.lineTo(18.5, 16)
    s.quadTo(20.5, 16, 20.5, 14)
    s.lineTo(20.5, 10)
    _poly(s, (12, 8), (12, 12.5))


def _book(s, f):
    s.moveTo(5, 19)
    s.lineTo(5, 5)
    s.quadTo(5, 3, 7, 3)
    s.lineTo(19, 3)
    s.lineTo(19, 17)
    s.lineTo(7, 17)
    s.quadTo(5, 17, 5, 19)
    s.quadTo(5, 21, 7, 21)
    s.lineTo(19, 21)
    _poly(s, (9, 7.5), (15, 7.5))
    _poly(s, (9, 11), (13, 11))


def _search(s, f):
    s.addEllipse(QPointF(10.5, 10.5), 6.5, 6.5)
    _poly(s, (15.5, 15.5), (20.5, 20.5))


def _film(s, f):
    s.addRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
    _poly(s, (7.5, 4), (7.5, 20))
    _poly(s, (16.5, 4), (16.5, 20))
    _poly(s, (3, 12), (21, 12))
    _poly(s, (3, 8), (7.5, 8))
    _poly(s, (3, 16), (7.5, 16))
    _poly(s, (16.5, 8), (21, 8))
    _poly(s, (16.5, 16), (21, 16))


def _save(s, f):
    _poly(s, (12, 3.5), (12, 14.5))
    _poly(s, (7, 9.5), (12, 14.5), (17, 9.5))
    s.moveTo(4, 15.5)
    s.lineTo(4, 18.5)
    s.quadTo(4, 20.5, 6, 20.5)
    s.lineTo(18, 20.5)
    s.quadTo(20, 20.5, 20, 18.5)
    s.lineTo(20, 15.5)


def _columns(s, f):
    s.addRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
    _poly(s, (12, 4), (12, 20))


def _rows(s, f):
    s.addRoundedRect(QRectF(3, 4, 18, 16), 2.5, 2.5)
    _poly(s, (3, 11), (21, 11))


def _alert(s, f):
    s.moveTo(10.3, 4.6)
    s.quadTo(12, 1.8, 13.7, 4.6)
    s.lineTo(21, 17.4)
    s.quadTo(22.5, 20, 19.5, 20)
    s.lineTo(4.5, 20)
    s.quadTo(1.5, 20, 3, 17.4)
    s.closeSubpath()
    _poly(s, (12, 9), (12, 13))
    _dot(f, 12, 16.4)


def _check(s, f):
    _poly(s, (5, 12.5), (10, 17.5), (19.5, 7))


def _sun(s, f):
    s.addEllipse(QPointF(12, 12), 4, 4)
    for step in range(8):
        angle = math.radians(step * 45)
        inner, outer = 7, 9.5
        _poly(
            s,
            (12 + inner * math.cos(angle), 12 + inner * math.sin(angle)),
            (12 + outer * math.cos(angle), 12 + outer * math.sin(angle)),
        )


def _moon(s, f):
    s.moveTo(20, 14.5)
    s.cubicTo(18.6, 18.4, 14.4, 21, 10, 20.4)
    s.cubicTo(5.4, 19.7, 2.9, 15.4, 3.6, 11)
    s.cubicTo(4.2, 7.4, 6.9, 4.6, 10.4, 3.8)
    s.cubicTo(8.3, 7.7, 9.2, 12.6, 12.6, 15.3)
    s.cubicTo(14.8, 17, 17.7, 16, 20, 14.5)
    s.closeSubpath()


def _sliders(s, f):
    _poly(s, (4, 7), (13, 7))
    _poly(s, (19, 7), (20, 7))
    s.addEllipse(QPointF(16, 7), 2.6, 2.6)
    _poly(s, (4, 17), (5, 17))
    _poly(s, (11, 17), (20, 17))
    s.addEllipse(QPointF(8, 17), 2.6, 2.6)


def _info(s, f):
    s.addEllipse(QPointF(12, 12), 9, 9)
    _poly(s, (12, 11), (12, 16.5))
    _dot(f, 12, 7.8)


def _pencil(s, f):
    s.moveTo(15.5, 4.5)
    s.lineTo(19.5, 8.5)
    s.lineTo(8.5, 19.5)
    s.lineTo(4, 20)
    s.lineTo(4.5, 15.5)
    s.closeSubpath()
    _poly(s, (13, 7), (17, 11))


def _folder(s, f):
    s.moveTo(3, 7)
    s.quadTo(3, 5, 5, 5)
    s.lineTo(9.2, 5)
    s.lineTo(11.2, 7)
    s.lineTo(19, 7)
    s.quadTo(21, 7, 21, 9)
    s.lineTo(21, 17)
    s.quadTo(21, 19, 19, 19)
    s.lineTo(5, 19)
    s.quadTo(3, 19, 3, 17)
    s.closeSubpath()


def _refresh(s, f):
    _arc(s, 12, 12, 8, 40, 300)
    _poly(s, (19.6, 3.6), (18.4, 7), (15, 6.2))


def _close(s, f):
    _poly(s, (6.5, 6.5), (17.5, 17.5))
    _poly(s, (17.5, 6.5), (6.5, 17.5))


def _plus(s, f):
    _poly(s, (12, 5), (12, 19))
    _poly(s, (5, 12), (19, 12))


def _clear(s, f):
    _poly(s, (4, 6), (15, 6))
    _poly(s, (4, 12), (12, 12))
    _poly(s, (4, 18), (10, 18))
    _poly(s, (15, 13.5), (20, 18.5))
    _poly(s, (20, 13.5), (15, 18.5))


def _chevron_down(s, f):
    _poly(s, (6, 9), (12, 15), (18, 9))


SHAPES: dict[str, Drawer] = {
    "chevron-down": _chevron_down,
    "play": _play,
    "pause": _pause,
    "stop": _stop,
    "undo": _undo,
    "redo": _redo,
    "split": _scissors,
    "merge": _merge,
    "trash": _trash,
    "word-up": _word_up,
    "word-down": _word_down,
    "space": _space,
    "book": _book,
    "search": _search,
    "film": _film,
    "save": _save,
    "columns": _columns,
    "rows": _rows,
    "alert": _alert,
    "check": _check,
    "sun": _sun,
    "moon": _moon,
    "sliders": _sliders,
    "info": _info,
    "pencil": _pencil,
    "folder": _folder,
    "refresh": _refresh,
    "close": _close,
    "plus": _plus,
    "clear": _clear,
}


def paint(painter: QPainter, name: str, rect: QRectF, color: QColor | str) -> None:
    """Draw one icon into `rect`, in `color`."""
    draw = SHAPES[name]
    stroke, fill = QPainterPath(), QPainterPath()
    draw(stroke, fill)
    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    painter.translate(rect.topLeft())
    painter.scale(rect.width() / GRID, rect.height() / GRID)
    colour = QColor(color)
    pen = QPen(colour, STROKE)
    pen.setCapStyle(Qt.RoundCap)
    pen.setJoinStyle(Qt.RoundJoin)
    painter.setPen(pen)
    painter.setBrush(Qt.NoBrush)
    painter.drawPath(stroke)
    if not fill.isEmpty():
        painter.setPen(Qt.NoPen)
        painter.setBrush(colour)
        painter.drawPath(fill)
    painter.restore()


def pixmap(name: str, color: QColor | str, size: int = 18, ratio: float = 2.0) -> QPixmap:
    """A transparent pixmap of the icon, drawn at `ratio` for sharp scaling."""
    image = QPixmap(int(size * ratio), int(size * ratio))
    image.fill(Qt.transparent)
    painter = QPainter(image)
    paint(painter, name, QRectF(0, 0, size * ratio, size * ratio), color)
    painter.end()
    image.setDevicePixelRatio(ratio)
    return image


def make(name: str, color: QColor | str, disabled: QColor | str | None = None,
         size: int = 18) -> QIcon:
    """An icon with its own greyed-out look for a disabled button.

    Qt's automatic disabled state only lightens the pixmap, which on the dark
    theme turned the icon brighter than the label next to it.
    """
    from PySide6.QtGui import QGuiApplication

    ratio = max(2.0, QGuiApplication.instance().devicePixelRatio()) if QGuiApplication.instance() else 2.0
    icon = QIcon()
    icon.addPixmap(pixmap(name, color, size, ratio), QIcon.Normal)
    icon.addPixmap(pixmap(name, color, size, ratio), QIcon.Active)
    if disabled is not None:
        icon.addPixmap(pixmap(name, disabled, size, ratio), QIcon.Disabled)
    return icon


def file(name: str, color: str, size: int = 16) -> str:
    """The icon as a PNG on disk, for the few places only a style sheet
    reaches -- the arrow of every combo box in every dialog, say.

    Drawn on a QImage, which needs no running application; returns "" if it
    cannot be written, and the sheet then simply shows no arrow.
    """
    import tempfile
    from pathlib import Path

    from PySide6.QtGui import QImage

    folder = Path(tempfile.gettempdir()) / "farsisub-icons"
    target = folder / f"{name}-{color.lstrip('#')}-{size}.png"
    if target.exists():
        return target.as_posix()
    try:
        folder.mkdir(parents=True, exist_ok=True)
        ratio = 2
        image = QImage(size * ratio, size * ratio, QImage.Format_ARGB32_Premultiplied)
        image.fill(Qt.transparent)
        painter = QPainter(image)
        paint(painter, name, QRectF(0, 0, size * ratio, size * ratio), color)
        painter.end()
        if not image.save(str(target)):
            return ""
    except Exception:  # noqa: BLE001 - an arrow is not worth failing a window over
        return ""
    return target.as_posix()
