"""The release page: install steps plus only the current version's notes."""

from __future__ import annotations

import importlib.util
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))


def _tool():
    spec = importlib.util.spec_from_file_location("release_notes", ROOT / "tools" / "release_notes.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


PERSIAN = "# تغییرات\n\n## ۱.۸.۰\n\n- تازه\n\n## ۱.۷.۰\n\n- قدیمی\n"
ENGLISH = "# Changelog\n\n## 1.8.0\n\n- new\n\n## 1.7.0\n\n- old\n"


def test_only_the_current_versions_notes_are_used():
    text = _tool().render("v1.8.0", PERSIAN, ENGLISH)
    assert "- تازه" in text and "- new" in text
    assert "قدیمی" not in text and "- old" not in text


def test_the_page_names_the_installer_file_in_both_languages():
    text = _tool().render("1.8.0", PERSIAN, ENGLISH)
    assert text.count("FarsiSub-1.8.0-Setup.exe") == 2
    assert "SmartScreen" in text
    assert "blob/v1.8.0/README.fa.md" in text and "blob/v1.8.0/README.md" in text


def test_a_version_without_notes_still_gets_the_install_steps():
    text = _tool().render("v9.9.9", PERSIAN, ENGLISH)
    assert "FarsiSub-9.9.9-Setup.exe" in text
    assert "What's new" not in text and "تغییرات این نسخه" not in text


def test_the_real_changelogs_have_the_current_version():
    from farsisub import __version__

    tool = _tool()
    persian = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    english = (ROOT / "CHANGELOG.en.md").read_text(encoding="utf-8")
    assert tool.section(persian, __version__.translate(tool.PERSIAN_DIGITS))
    assert tool.section(english, __version__)
