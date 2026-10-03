"""Write the text of a GitHub Release: how to install, then what changed.

    python tools/release_notes.py v1.8.0 > release-notes.md

The workflow used to publish the whole changelog as the release body, which
put every old version's notes under the newest download. This keeps the page
to what a person arriving there needs.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REPO = "https://github.com/kterfan/farsi-sub"

PERSIAN_DIGITS = str.maketrans("0123456789", "۰۱۲۳۴۵۶۷۸۹")


def section(markdown: str, heading: str) -> str:
    """The body under `## heading`, up to the next `## ` heading; "" if absent."""
    match = re.search(
        rf"^## {re.escape(heading)}\s*$(.*?)(?=^## |\Z)", markdown, re.MULTILINE | re.DOTALL
    )
    return match.group(1).strip() if match else ""


def render(version: str, persian_log: str, english_log: str) -> str:
    version = version.lstrip("v")
    persian = section(persian_log, version.translate(PERSIAN_DIGITS))
    english = section(english_log, version)
    installer = f"FarsiSub-{version}-Setup.exe"

    parts = [
        f"## Download\n\n"
        f"Get **`{installer}`** from the *Assets* list below and run it. "
        f"Windows 10/11 64-bit, no administrator rights needed. "
        f"On first launch it offers to download a speech model; after that everything is offline.\n\n"
        f"Windows may show a *SmartScreen* warning because the installer is not code-signed yet: "
        f"click **More info → Run anyway**. "
        f"Installing over an older version keeps your models, settings and dictionary.\n\n"
        f"**دانلود:** فایل **`{installer}`** را از فهرست *Assets* پایین همین صفحه بگیر و اجرا کن. "
        f"ویندوز ۱۰ یا ۱۱ (۶۴ بیتی)، بدون نیاز به دسترسی ادمین. "
        f"در اولین اجرا برنامه پیشنهاد می‌دهد یک مدل دانلود کنی؛ بعد از آن همه‌چیز آفلاین است. "
        f"اگر ویندوز هشدار *SmartScreen* داد (نصاب هنوز امضای دیجیتال ندارد) روی "
        f"**More info ← Run anyway** بزن. نصب روی نسخهٔ قبلی، مدل‌ها و تنظیمات و دیکشنری‌ات را نگه می‌دارد.\n\n"
        f"Documentation · راهنما: [English]({REPO}/blob/v{version}/README.md) · "
        f"[فارسی]({REPO}/blob/v{version}/README.fa.md)"
    ]
    if english:
        parts.append(f"## What's new\n\n{english}")
    if persian:
        parts.append(f"## تغییرات این نسخه\n\n{persian}")
    return "\n\n".join(parts) + "\n"


def main(argv: list[str]) -> int:
    if len(argv) != 2:
        print("usage: release_notes.py v1.8.0", file=sys.stderr)
        return 2
    persian = (ROOT / "CHANGELOG.md").read_text(encoding="utf-8")
    english_path = ROOT / "CHANGELOG.en.md"
    english = english_path.read_text(encoding="utf-8") if english_path.exists() else ""
    sys.stdout.reconfigure(encoding="utf-8")
    sys.stdout.write(render(argv[1], persian, english))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
