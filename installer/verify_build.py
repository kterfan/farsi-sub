"""Check a built or installed copy before it goes anywhere.

    python installer/verify_build.py dist/FarsiSub

Every item listed here has actually been missing from a build: hazm's word
lists were dropped by an over broad exclude rule in the installer script,
and the app only failed later, on its first Persian sentence.
"""

from __future__ import annotations

import sys
from pathlib import Path

REQUIRED = [
    "FarsiSub.exe",
    "_internal/bin/whisper-cli.exe",
    "_internal/bin/ggml-silero-v5.1.2.bin",
    "_internal/hazm/data/words.dat",
    "_internal/hazm/data/verbs.dat",
    "_internal/assets/fonts/Vazirmatn-Regular.ttf",
    "_internal/base_library.zip",
    # Playback inside the editor: without these the video panel stays black.
    "_internal/PySide6/plugins/multimedia/ffmpegmediaplugin.dll",
    "_internal/PySide6/QtMultimedia.pyd",
    "_internal/PySide6/QtMultimediaWidgets.pyd",
]


def main() -> int:
    root = Path(sys.argv[1] if len(sys.argv) > 1 else "dist/FarsiSub")
    print("بررسی " + str(root))

    missing = []
    for name in REQUIRED:
        present = (root / name).exists()
        print(("  هست   " if present else "  نیست  ") + name)
        if not present:
            missing.append(name)

    if missing:
        print("")
        print(str(len(missing)) + " فایل جا افتاده — این بسته قابل استفاده نیست")
        return 1

    print("")
    print("همه اجزای لازم موجودند")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
