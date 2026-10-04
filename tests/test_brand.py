"""1.7: the mark, the About window, the icon by the clock, the credit."""

from __future__ import annotations

import os
import struct
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

ROOT = Path(__file__).resolve().parents[1]


def _qt():
    from PySide6.QtWidgets import QApplication

    return QApplication.instance() or QApplication([])


def test_the_mark_draws_at_every_icon_size():
    from farsisub import brand

    _qt()
    for size in (16, 32, 256):
        image = brand.logo_image(size)
        assert image.width() == size
        # The corner is transparent and the middle is painted.
        assert image.pixelColor(0, 0).alpha() == 0
        assert image.pixelColor(size // 2, size // 4).alpha() == 255


def test_the_progress_ring_grows_with_progress():
    from farsisub import brand

    _qt()

    def ring_pixels(progress):
        image = brand.logo_image(64, progress)
        ring = brand.RING.lower()
        return sum(
            1
            for x in range(64)
            for y in range(64)
            if image.pixelColor(x, y).name() == ring
        )

    assert ring_pixels(0.0) < ring_pixels(0.3) < ring_pixels(0.9)


def test_the_committed_icon_holds_every_size():
    data = (ROOT / "assets" / "brand" / "farsisub.ico").read_bytes()
    reserved, kind, count = struct.unpack("<HHH", data[:6])
    assert (reserved, kind) == (0, 1) and count >= 6
    sizes = {data[6 + 16 * i] or 256 for i in range(count)}
    assert {16, 32, 48, 256} <= sizes
    for name in ("wizard.bmp", "wizard-2x.bmp", "wizard-small.bmp", "logo.png"):
        assert (ROOT / "assets" / "brand" / name).stat().st_size > 1000


def test_the_about_window_names_the_author_and_links_the_project():
    from farsisub import brand
    from farsisub.gui.about_dialog import AboutDialog, version_report

    _qt()
    dialog = AboutDialog()
    text = dialog.author.text()
    assert brand.AUTHOR_FA in text and brand.AUTHOR_EN in text
    assert brand.REPO_URL in dialog.link.text()
    assert dialog.link.openExternalLinks()
    report = version_report()
    assert brand.VERSION in report and brand.REPO_URL in report


def test_the_main_window_carries_the_credit():
    from farsisub import brand
    from farsisub.gui.main_window import MainWindow

    _qt()
    previous = os.environ.get("FARSISUB_DATA")
    os.environ["FARSISUB_DATA"] = tempfile.mkdtemp()
    try:
        window = MainWindow()
        credit = window.credit_label.text()
        assert brand.AUTHOR_FA in credit and brand.AUTHOR_EN in credit
        assert brand.REPO_URL in credit
    finally:
        if previous is None:
            os.environ.pop("FARSISUB_DATA", None)
        else:
            os.environ["FARSISUB_DATA"] = previous


def test_the_tray_follows_a_file_from_start_to_finish():
    from farsisub.gui.main_window import STATUS_RUNNING, MainWindow
    from farsisub.gui.tray import Tray

    _qt()
    previous = os.environ.get("FARSISUB_DATA")
    os.environ["FARSISUB_DATA"] = tempfile.mkdtemp()
    try:
        window = MainWindow()
        window.tray = Tray(window)
        window.add_files([Path("clip.mp4")])
        window.running_path = Path("clip.mp4")
        window._set_status(Path("clip.mp4"), STATUS_RUNNING)
        window._on_progress(42)
        assert "۴۲٪" in window.tray.tooltip and "clip.mp4" in window.tray.tooltip
        assert window.tray.cancel_action.isEnabled()
        assert window.table.cellWidget(0, 1).value() == 42  # the row's own bar
        window._on_finished(None, "clip.srt")
        assert window.tray.last_message[0] == "زیرنویس آماده شد"
        assert window.tray.tooltip == "FarsiSub"
        assert window.table.cellWidget(0, 1) is None
        window.tray.hide()
    finally:
        if previous is None:
            os.environ.pop("FARSISUB_DATA", None)
        else:
            os.environ["FARSISUB_DATA"] = previous


def test_time_left_reads_past_an_hour():
    from farsisub.gui.main_window import format_duration

    assert format_duration(307) == "۰۵:۰۷"
    # QTime's mm:ss wrapped here and showed "05:07".
    assert format_duration(3907) == "۱:۰۵:۰۷"
    assert format_duration(-5) == "۰۰:۰۰"


def test_the_installer_is_persian_and_credits_the_author():
    script = (ROOT / "installer" / "farsisub.iss").read_bytes()
    assert script.startswith(b"\xef\xbb\xbf"), "Inno reads Persian right only with a BOM"
    text = script.decode("utf-8-sig")
    assert 'MessagesFile: "Farsi.isl"' in text
    assert "Erfan Esmailzadeh" in text and "عرفان اسمعیل‌زاده" in text
    assert "github.com/kterfan/farsi-sub" in text
    from farsisub import __version__

    assert f'#define AppVersion "{__version__}"' in text
    translation = (ROOT / "installer" / "Farsi.isl").read_text(encoding="utf-8-sig")
    assert "RightToLeft=yes" in translation
