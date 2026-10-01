"""Minimal runner so the test suite works before pytest is installed.

`pytest tests/` gives the same results once the venv exists; this file just
removes the dependency for early development.
"""

from __future__ import annotations

import importlib.util
import os
import sys
import tempfile
import traceback
from pathlib import Path

HERE = Path(__file__).resolve().parent

# The suite must never write into the real data folder: the editor tests save
# projects and the window layout, and from a source checkout that folder is
# the one the app itself uses.
os.environ.setdefault("FARSISUB_DATA", tempfile.mkdtemp(prefix="farsisub-tests-"))


def load(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


def main() -> int:
    passed = failed = 0
    for path in sorted(HERE.glob("test_*.py")):
        try:
            module = load(path)
        except Exception:
            # One file that cannot even be imported (PySide6 missing, say)
            # used to end the whole run without a summary.
            failed += 1
            print(f"FAIL {path.name} (import)")
            traceback.print_exc()
            continue
        for name in sorted(dir(module)):
            if not name.startswith("test_"):
                continue
            func = getattr(module, name)
            if not callable(func):
                continue
            try:
                func()
            except Exception:
                failed += 1
                print(f"FAIL {path.name}::{name}")
                traceback.print_exc()
            else:
                passed += 1
                print(f"ok   {path.name}::{name}")
    print(f"\n{passed} passed, {failed} failed")
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
