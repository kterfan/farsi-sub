"""Who made FarsiSub and what it looks like: one source for every surface.

The window, the taskbar, the icon by the clock, the installer and the exe all
draw the same mark from here, so they can never drift apart.
"""

from __future__ import annotations

from . import __version__

APP_NAME = "FarsiSub"
APP_NAME_FA = "فارسی‌ساب"
TAGLINE_FA = "زیرنویس فارسی، کاملاً روی همین کامپیوتر"
AUTHOR_FA = "عرفان اسمعیل‌زاده"
AUTHOR_EN = "Erfan Esmailzadeh"
REPO_URL = "https://github.com/kterfan/farsi-sub"
REPO_LABEL = "github.com/kterfan/farsi-sub"
VERSION = __version__

# The mark's gradient: the accent blue of the interface into a violet.
GRADIENT_TOP = "#4C8DFF"
GRADIENT_BOTTOM = "#8B5CF6"
RING = "#2DD4A7"


def paint_logo(painter, size: float, progress: float | None = None) -> None:
    """Draw the mark into a `size` x `size` square at the painter's origin.

    A rounded tile with two subtitle lines. With `progress` (0..1) the tile
    shrinks a little and a ring around it fills clockwise: that is the icon
    beside the clock while a file is being transcribed.
    """
    from PySide6.QtCore import QPointF, QRectF, Qt
    from PySide6.QtGui import QColor, QLinearGradient, QPainter, QPainterPath, QPen

    painter.save()
    painter.setRenderHint(QPainter.Antialiasing)
    inset = 0.0
    if progress is not None:
        ring = max(1.5, size * 0.09)
        inset = ring * 1.6
        bounds = QRectF(ring / 2, ring / 2, size - ring, size - ring)
        track = QColor(GRADIENT_TOP)
        track.setAlpha(60)
        painter.setPen(QPen(track, ring))
        painter.drawEllipse(bounds)
        pen = QPen(QColor(RING), ring)
        pen.setCapStyle(Qt.RoundCap)
        painter.setPen(pen)
        span = int(-360 * 16 * max(0.0, min(1.0, progress)))
        painter.drawArc(bounds, 90 * 16, span)

    tile = QRectF(inset, inset, size - 2 * inset, size - 2 * inset)
    radius = tile.width() * 0.24
    gradient = QLinearGradient(tile.topLeft(), tile.bottomRight())
    gradient.setColorAt(0.0, QColor(GRADIENT_TOP))
    gradient.setColorAt(1.0, QColor(GRADIENT_BOTTOM))
    path = QPainterPath()
    path.addRoundedRect(tile, radius, radius)
    painter.setPen(Qt.NoPen)
    painter.fillPath(path, gradient)

    # A soft highlight on the top half gives the tile some depth.
    shine = QLinearGradient(tile.topLeft(), QPointF(tile.left(), tile.center().y()))
    shine.setColorAt(0.0, QColor(255, 255, 255, 46))
    shine.setColorAt(1.0, QColor(255, 255, 255, 0))
    painter.fillPath(path, shine)

    # Two subtitle lines, right-aligned like Persian text: the longer one on
    # top, the shorter underneath.
    unit = tile.width() / 10
    bar = unit * 1.05
    painter.setBrush(QColor("#FFFFFF"))
    painter.drawRoundedRect(
        QRectF(tile.left() + unit * 2.0, tile.top() + unit * 5.2, unit * 6.0, bar), bar / 2, bar / 2
    )
    soft = QColor("#FFFFFF")
    soft.setAlpha(205)
    painter.setBrush(soft)
    painter.drawRoundedRect(
        QRectF(tile.left() + unit * 4.0, tile.top() + unit * 7.0, unit * 4.0, bar), bar / 2, bar / 2
    )
    painter.restore()


def logo_image(size: int, progress: float | None = None):
    """The mark as a transparent QImage."""
    from PySide6.QtGui import QImage, QPainter

    image = QImage(size, size, QImage.Format_ARGB32_Premultiplied)
    image.fill(0)
    painter = QPainter(image)
    paint_logo(painter, size, progress)
    painter.end()
    return image


def app_icon(progress: float | None = None):
    """A QIcon with every size Windows asks for."""
    from PySide6.QtGui import QIcon, QPixmap

    icon = QIcon()
    for size in (16, 20, 24, 32, 40, 48, 64, 128, 256):
        icon.addPixmap(QPixmap.fromImage(logo_image(size, progress)))
    return icon
