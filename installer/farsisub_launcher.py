"""Entry point for the frozen build.

PyInstaller needs a plain script to start from; everything real lives in the
package.
"""

from __future__ import annotations

import multiprocessing
import sys

from farsisub.gui.app import main

if __name__ == "__main__":
    # Without this a frozen Windows build re-runs the whole app in any child
    # process it spawns.
    multiprocessing.freeze_support()
    sys.exit(main())
