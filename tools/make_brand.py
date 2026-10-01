"""Render every brand image from farsisub.brand into assets/brand/.

    python tools/make_brand.py

The outputs are committed: building the installer should not depend on a
font or a renderer being present. Run this again only when the mark changes.

    farsisub.ico          exe, window, taskbar, installer (16..256 px)
    logo.png              512 px, for the README and the About window
    wizard.bmp/-2x.bmp    the tall image on the installer's first and last page
    wizard-small.bmp/-2x  the small image at the top of the other pages
"""

from __future__ import annotations

import struct
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from farsisub import brand  # noqa: E402

OUT = ROOT / "assets" / "brand"
ICO_SIZES = (16, 20, 24, 32, 40, 48, 64, 128, 256)


def _png_bytes(image) -> bytes:
    from PySide6.QtCore import QBuffer, QByteArray, QIODevice

    data = QByteArray()
    buffer = QBuffer(data)
    buffer.open(QIODevice.WriteOnly)
    image.save(buffer, "PNG")
    return bytes(data)


def write_ico(path: Path, sizes=ICO_SIZES) -> Path:
    """A multi-size .ico with PNG-compressed entries (Windows Vista and later)."""
    images = [(size, _png_bytes(brand.logo_image(size))) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(images))
    offset = 6 + 16 * len(images)
    directory = b""
    payload = b""
    for size, png in images:
        side = 0 if size >= 256 else size  # 0 means 256 in the ICO format
        directory += struct.pack("<BBBBHHII", side, side, 0, 0, 1, 32, len(png), offset)
        payload += png
        offset += len(png)
    path.write_bytes(header + directory + payload)
    return path


def _font(pixels: int, bold: bool = False):
    from PySide6.QtGui import QFont

    font = QFont()
    font.setFamilies(["Vazirmatn", "Segoe UI"])
    font.setPixelSize(pixels)
    font.setBold(bold)
    return font


def wizard_image(width: int, height: int):
    """The tall panel: the mark, the name, and who made it."""
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QColor, QImage, QLinearGradient, QPainter

    scale = width / 164
    image = QImage(width, height, QImage.Format_RGB32)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    gradient = QLinearGradient(0, 0, 0, height)
    gradient.setColorAt(0.0, QColor("#141B2D"))
    gradient.setColorAt(1.0, QColor("#0B0E13"))
    painter.fillRect(image.rect(), gradient)

    # A faint glow behind the mark.
    glow = QColor(brand.GRADIENT_BOTTOM)
    glow.setAlpha(40)
    painter.setPen(Qt.NoPen)
    painter.setBrush(glow)
    logo = int(width * 0.46)
    top = height * 0.18
    centre_y = top + logo / 2
    halo = width * 0.66
    painter.drawEllipse(QRectF((width - halo) / 2, centre_y - halo / 2, halo, halo))

    painter.translate((width - logo) / 2, top)
    brand.paint_logo(painter, logo)
    painter.resetTransform()

    painter.setPen(QColor("#E7ECF3"))
    painter.setFont(_font(int(20 * scale), bold=True))
    painter.drawText(QRectF(0, height * 0.47, width, 30 * scale), Qt.AlignHCenter, brand.APP_NAME)
    painter.setPen(QColor("#93A0B4"))
    painter.setFont(_font(int(13 * scale)))
    painter.drawText(QRectF(0, height * 0.56, width, 22 * scale), Qt.AlignHCenter, brand.APP_NAME_FA)

    painter.setPen(QColor("#93A0B4"))
    painter.setFont(_font(int(10 * scale)))
    painter.drawText(QRectF(0, height * 0.82, width, 18 * scale), Qt.AlignHCenter, brand.AUTHOR_FA)
    painter.drawText(QRectF(0, height * 0.87, width, 18 * scale), Qt.AlignHCenter, brand.AUTHOR_EN)
    painter.end()
    return image


def small_image(side: int):
    from PySide6.QtGui import QColor, QImage, QPainter

    image = QImage(side, side, QImage.Format_RGB32)
    image.fill(QColor("#FFFFFF"))
    painter = QPainter(image)
    inner = int(side * 0.86)
    offset = (side - inner) / 2
    painter.translate(offset, offset)
    brand.paint_logo(painter, inner)
    painter.end()
    return image


def main() -> int:
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    QApplication.instance() or QApplication([])
    for font in sorted((ROOT / "assets" / "fonts").glob("Vazirmatn*.ttf")):
        QFontDatabase.addApplicationFont(str(font))
    OUT.mkdir(parents=True, exist_ok=True)

    write_ico(OUT / "farsisub.ico")
    brand.logo_image(512).save(str(OUT / "logo.png"))
    wizard_image(164, 314).save(str(OUT / "wizard.bmp"))
    wizard_image(328, 628).save(str(OUT / "wizard-2x.bmp"))
    small_image(55).save(str(OUT / "wizard-small.bmp"))
    small_image(110).save(str(OUT / "wizard-small-2x.bmp"))
    for path in sorted(OUT.iterdir()):
        print(f"{path.name:22} {path.stat().st_size:>8} bytes")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
