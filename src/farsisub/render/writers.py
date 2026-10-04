"""Write cues out as subtitle files.

Timecodes always use Latin digits: that is what the SRT/VTT formats specify,
regardless of the digit style chosen for the subtitle text itself.
"""

from __future__ import annotations

from pathlib import Path
from typing import TYPE_CHECKING

from ..models import Cue

if TYPE_CHECKING:
    from ..config import AssStyle

# A frame size nobody has to know about: the ASS "canvas" when the video's own
# size is unknown.
DEFAULT_FRAME = (1920, 1080)

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


def ass_color(color: str, fallback: str = "#FFFFFF") -> str:
    """'#RRGGBB' -> ASS '&H00BBGGRR'. A bad value falls back instead of failing."""
    value = color.strip().lstrip("#") if isinstance(color, str) else ""
    if len(value) != 6 or any(c not in "0123456789abcdefABCDEF" for c in value):
        value = fallback.lstrip("#")
    rr, gg, bb = value[0:2], value[2:4], value[4:6]
    return f"&H00{bb}{gg}{rr}".upper()


def frame_scale(width: int, height: int) -> float:
    """Style sizes are given for a 1080-pixel frame; scale by the short side.

    Scaling by the height alone made text on a vertical 1080x1920 reel 1.8
    times larger than on a landscape video, and a 28-letter line ran off the
    sides of the picture.
    """
    short = min(width, height) if width > 0 and height > 0 else 1080
    return short / 1080


def _ass_time(seconds: float) -> str:
    total_cs = max(0, int(round(seconds * 100)))
    hours, rem = divmod(total_cs, 360_000)
    minutes, rem = divmod(rem, 6_000)
    secs, cs = divmod(rem, 100)
    return f"{hours}:{minutes:02d}:{secs:02d}.{cs:02d}"


def _ass_text(text: str) -> str:
    """Text that ASS will show as typed, never read as override codes."""
    out = text.replace("\\", "\\\u2060").replace("{", "\uff5b").replace("}", "\uff5d")
    return out.replace("\n", "\\N")


def to_ass(cues: list[Cue], style: "AssStyle", frame: tuple[int, int] = DEFAULT_FRAME) -> str:
    """A styled subtitle file: font, outline, colours, position, keyword colour."""
    width, height = frame if frame[0] > 0 and frame[1] > 0 else DEFAULT_FRAME
    scale = frame_scale(width, height)
    size = max(8, round(style.size * scale))
    outline = round(max(0.0, style.outline) * scale, 2)
    margin = max(0, round(style.margin_bottom * scale))
    side = round(width * 0.05)
    bold = -1 if style.bold else 0
    font = (style.font or "Vazirmatn").replace(",", " ")
    back = "&H64000000"

    def style_line(name: str, colour: str) -> str:
        return (
            f"Style: {name},{font},{size},{colour},&H000000FF,{ass_color(style.outline_color, '#000000')},"
            f"{back},{bold},0,0,0,100,100,0,0,1,{outline},0,2,{side},{side},{margin},1"
        )

    lines = [
        "[Script Info]",
        "; Made by FarsiSub",
        "ScriptType: v4.00+",
        f"PlayResX: {width}",
        f"PlayResY: {height}",
        "WrapStyle: 2",
        "ScaledBorderAndShadow: yes",
        "",
        "[V4+ Styles]",
        "Format: Name, Fontname, Fontsize, PrimaryColour, SecondaryColour, OutlineColour, "
        "BackColour, Bold, Italic, Underline, StrikeOut, ScaleX, ScaleY, Spacing, Angle, "
        "BorderStyle, Outline, Shadow, Alignment, MarginL, MarginR, MarginV, Encoding",
        style_line("Default", ass_color(style.color)),
        style_line("Keyword", ass_color(style.keyword_color, "#FFD400")),
        "",
        "[Events]",
        "Format: Layer, Start, End, Style, Name, MarginL, MarginR, MarginV, Effect, Text",
    ]
    for cue in cues:
        name = "Keyword" if cue.keyword else "Default"
        lines.append(
            f"Dialogue: 0,{_ass_time(cue.start)},{_ass_time(cue.end)},{name},,0,0,0,,"
            f"{_ass_text(cue.text)}"
        )
    return "\n".join(lines) + "\n"


def write_subtitle(
    cues: list[Cue],
    path: str | Path,
    *,
    bom: bool = True,
    style: "AssStyle | None" = None,
    frame: tuple[int, int] = DEFAULT_FRAME,
) -> Path:
    """Write .srt, .vtt, .ass or .txt based on the path suffix."""
    out = Path(path)
    suffix = out.suffix.lower()
    if suffix == ".vtt":
        body = to_vtt(cues)
    elif suffix == ".ass":
        from ..config import AssStyle

        body = to_ass(cues, style or AssStyle(), frame)
    elif suffix == ".txt":
        body = to_txt(cues)
    else:
        body = to_srt(cues)

    # Old Windows players read UTF-8 Persian as mojibake without a BOM.
    prefix = BOM if (bom and suffix != ".vtt") else ""
    out.write_text(prefix + body, encoding="utf-8", newline="\r\n")
    return out
