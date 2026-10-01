"""Write cues out as subtitle files.

Timecodes always use Latin digits: that is what the SRT/VTT formats specify,
regardless of the digit style chosen for the subtitle text itself.
"""

from __future__ import annotations

from pathlib import Path

from ..models import Cue

BOM = "\ufeff"


def format_timestamp(seconds: float, *, sep: str = ",") -> str:
    total_ms = max(0, int(round(seconds * 1000)))
    hours, rem = divmod(total_ms, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d}{sep}{ms:03d}"


def to_srt(cues: list[Cue]) -> str:
    blocks: list[str] = []
    for n, cue in enumerate(cues, start=1):
        blocks.append(
            f"{n}\n"
            f"{format_timestamp(cue.start)} --> {format_timestamp(cue.end)}\n"
            f"{cue.text}\n"
        )
    return "\n".join(blocks)


def to_vtt(cues: list[Cue]) -> str:
    blocks = ["WEBVTT\n"]
    for cue in cues:
        blocks.append(
            f"{format_timestamp(cue.start, sep='.')} --> "
            f"{format_timestamp(cue.end, sep='.')}\n"
            f"{cue.text}\n"
        )
    return "\n".join(blocks)


def to_txt(cues: list[Cue]) -> str:
    return "\n".join(cue.text.replace("\n", " ") for cue in cues) + "\n"


def write_subtitle(cues: list[Cue], path: str | Path, *, bom: bool = True) -> Path:
    """Write .srt, .vtt or .txt based on the path suffix."""
    out = Path(path)
    suffix = out.suffix.lower()
    if suffix == ".vtt":
        body = to_vtt(cues)
    elif suffix == ".txt":
        body = to_txt(cues)
    else:
        body = to_srt(cues)

    # Old Windows players read UTF-8 Persian as mojibake without a BOM.
    prefix = BOM if (bom and suffix != ".vtt") else ""
    out.write_text(prefix + body, encoding="utf-8", newline="\r\n")
    return out
