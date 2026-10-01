"""Writing files so that a crash mid-write cannot leave half of one behind.

A plain `write_text` truncates the file first and fills it after: a power cut
or a killed process in between leaves an empty or broken file, and for the
glossary or a project that means the user's work is gone. Writing a sibling
file and swapping it in keeps either the old version or the new one, never a
mix.
"""

from __future__ import annotations

import os
import tempfile
from pathlib import Path


def atomic_write_text(path: str | Path, text: str, *, encoding: str = "utf-8") -> Path:
    target = Path(path)
    target.parent.mkdir(parents=True, exist_ok=True)
    handle, temporary = tempfile.mkstemp(
        prefix=f".{target.name}.", suffix=".tmp", dir=target.parent
    )
    try:
        with os.fdopen(handle, "w", encoding=encoding) as stream:
            stream.write(text)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, target)
    except BaseException:
        Path(temporary).unlink(missing_ok=True)
        raise
    return target
