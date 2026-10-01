"""Burn the subtitle into the picture: a video that needs no subtitle file.

Short-form platforms show no subtitle track, so the text has to be part of
the frames. FFmpeg's own subtitle filter needs libass, which the PyAV wheel
does not carry; Qt draws the text instead, and Qt shapes Persian (joined
letters, right to left) correctly.

Frames are decoded, the line on screen at that moment is blended in, and the
result is encoded again as H.264 with the audio re-encoded to AAC, in an MP4
that every platform accepts.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Sequence

from ..config import AssStyle
from ..models import Cue
from .writers import frame_scale


class BurnError(RuntimeError):
    pass


def burned_path(subtitle_target: Path) -> Path:
    """Where the burned video goes: beside the subtitle, never over the source."""
    return subtitle_target.with_name(subtitle_target.stem + ".subtitled.mp4")


def _ensure_qt() -> None:
    """Text drawing needs a Qt GUI application; the CLI and tests have none."""
    from PySide6.QtGui import QFontDatabase
    from PySide6.QtWidgets import QApplication

    # A full QApplication, not just the GUI one text needs: a bare
    # QGuiApplication would make every window opened later in this process
    # abort.
    if QApplication.instance() is None:
        QApplication([])
    from ..engine.locate import resource_dir

    for path in sorted((resource_dir() / "assets" / "fonts").glob("Vazirmatn*.ttf")):
        QFontDatabase.addApplicationFont(str(path))


def _color(value: str, fallback: str):
    from PySide6.QtGui import QColor

    colour = QColor(value)
    return colour if colour.isValid() else QColor(fallback)


@dataclass
class Overlay:
    """One cue drawn once: premultiplied-free RGBA pixels and where they go."""

    top: int
    left: int
    rgb: object  # numpy (h, w, 3) float32
    alpha: object  # numpy (h, w, 1) float32, 0..1


def render_overlay(cue: Cue, style: AssStyle, width: int, height: int) -> Overlay | None:
    """Draw one cue the way the ASS export describes it."""
    import numpy as np
    from PySide6.QtCore import QRectF, Qt
    from PySide6.QtGui import QFont, QImage, QPainter, QTextOption

    text = cue.text.strip()
    if not text:
        return None
    scale = frame_scale(width, height)
    size = max(8, round(style.size * scale))
    outline = max(0.0, style.outline) * scale
    margin = round(style.margin_bottom * scale)
    side = round(width * 0.05)

    font = QFont()
    font.setFamilies([style.font or "Vazirmatn", "Vazirmatn", "Segoe UI"])
    font.setPixelSize(size)
    font.setBold(style.bold)

    lines = max(1, len(cue.lines) or text.count("\n") + 1)
    pad = math.ceil(outline) + 2
    band_height = int(lines * size * 1.55) + 2 * pad
    band_width = max(16, width - 2 * side)
    top = max(0, height - margin - band_height)

    image = QImage(band_width, band_height, QImage.Format_ARGB32)
    image.fill(0)
    painter = QPainter(image)
    painter.setRenderHint(QPainter.Antialiasing)
    painter.setRenderHint(QPainter.TextAntialiasing)
    painter.setFont(font)
    option = QTextOption(Qt.AlignHCenter | Qt.AlignBottom)
    option.setTextDirection(Qt.RightToLeft)
    option.setWrapMode(QTextOption.WordWrap)
    box = QRectF(pad, pad, band_width - 2 * pad, band_height - 2 * pad)

    # Qt has no stroked text that keeps Persian shaping, so the outline is the
    # same text drawn around a small circle underneath.
    if outline > 0:
        painter.setPen(_color(style.outline_color, "#000000"))
        steps = max(8, int(outline * 6))
        for i in range(steps):
            angle = 2 * math.pi * i / steps
            painter.drawText(
                box.translated(outline * math.cos(angle), outline * math.sin(angle)), text, option
            )
    painter.setPen(_color(style.keyword_color if cue.keyword else style.color, "#FFFFFF"))
    painter.drawText(box, text, option)
    painter.end()

    pixels = image.constBits()
    array = np.frombuffer(pixels, dtype=np.uint8, count=band_height * image.bytesPerLine())
    array = array.reshape(band_height, image.bytesPerLine() // 4, 4)[:, :band_width]
    # ARGB32 is B, G, R, A in memory on little-endian machines.
    rgb = array[:, :, [2, 1, 0]].astype(np.float32)
    alpha = array[:, :, 3:4].astype(np.float32) / 255.0
    used = np.nonzero(alpha[:, :, 0].max(axis=1) > 0)[0]
    if used.size == 0:
        return None
    first, last = int(used[0]), int(used[-1]) + 1
    return Overlay(top=top + first, left=side, rgb=rgb[first:last], alpha=alpha[first:last])


def blend(frame, overlay: Overlay):
    """Alpha-blend the overlay into an (h, w, 3) uint8 frame, in place."""
    import numpy as np

    h, w = overlay.alpha.shape[:2]
    top, left = overlay.top, overlay.left
    bottom, right = min(frame.shape[0], top + h), min(frame.shape[1], left + w)
    if bottom <= top or right <= left:
        return frame
    region = frame[top:bottom, left:right].astype(np.float32)
    alpha = overlay.alpha[: bottom - top, : right - left]
    rgb = overlay.rgb[: bottom - top, : right - left]
    frame[top:bottom, left:right] = (rgb * alpha + region * (1.0 - alpha)).astype(np.uint8)
    return frame


def rotate(array, degrees: float):
    """Apply a display rotation (counterclockwise degrees) to an (h, w, c) array.

    Phone videos store "portrait" as a flag next to landscape pixels. Ignoring
    it burned the text sideways onto a sideways picture.
    """
    import numpy as np

    turns = round((degrees or 0) / 90) % 4
    return np.ascontiguousarray(np.rot90(array, k=turns)) if turns else array


def _frame_shape(source: Path) -> tuple[int, int]:
    """(width, height) of the picture as shown, rotation applied, sides even.

    Read from the first frame before anything is written: an MP4 cannot take
    a new stream once packets are in it, and audio often comes first.
    """
    import av

    with av.open(str(source)) as probe:
        stream = probe.streams.video[0]
        for frame in probe.decode(stream):
            turns = round((getattr(frame, "rotation", 0) or 0) / 90) % 4
            width, height = frame.width, frame.height
            if turns % 2:
                width, height = height, width
            return width & ~1, height & ~1
    raise BurnError("هیچ فریمی در این ویدیو خوانده نشد")


def _cue_at(cues: Sequence[Cue], starts: list[float], seconds: float) -> int:
    from bisect import bisect_right

    index = bisect_right(starts, seconds) - 1
    if 0 <= index < len(cues) and seconds < cues[index].end:
        return index
    return -1


def burn(
    video: str | Path,
    cues: Sequence[Cue],
    style: AssStyle,
    target: str | Path,
    *,
    on_progress: Callable[[int], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> Path:
    """Write `target` (an .mp4): the video with the cues drawn into every frame."""
    import av
    import numpy as np

    _ensure_qt()
    source = Path(video)
    final = Path(target)
    final.parent.mkdir(parents=True, exist_ok=True)
    partial = final.with_name(final.stem + ".part" + final.suffix)
    ordered = sorted(cues, key=lambda c: c.start)
    starts = [c.start for c in ordered]
    # Only the line on screen is kept drawn: frames come in time order, and a
    # cache of every line held gigabytes on a long word-by-word video.
    shown_index = -1
    shown: Overlay | None = None

    try:
        with av.open(str(source)) as src:
            if not src.streams.video:
                raise BurnError("این فایل تصویر ندارد؛ زیرنویس فقط روی ویدیو سوزانده می‌شود")
            width, height = _frame_shape(source)
            vin = src.streams.video[0]
            ain = src.streams.audio[0] if src.streams.audio else None
            vin.thread_type = "AUTO"
            duration = float(src.duration / 1_000_000) if src.duration else 0.0

            with av.open(str(partial), mode="w", format="mp4") as dst:
                rate = vin.average_rate or vin.guessed_rate or 30
                try:
                    vout = dst.add_stream("libx264", rate=rate)
                    vout.options = {"crf": "18", "preset": "medium"}
                except Exception:  # noqa: BLE001 - an FFmpeg build without x264
                    vout = dst.add_stream("mpeg4", rate=rate)
                    vout.codec_context.bit_rate = 8_000_000
                vout.width, vout.height = width, height
                vout.pix_fmt = "yuv420p"
                aout = None
                resampler = None
                if ain is not None:
                    aout = dst.add_stream("aac", rate=ain.codec_context.sample_rate or 48000)
                    aout.codec_context.bit_rate = 192_000
                    layout = ain.codec_context.layout.name if ain.codec_context.layout else "stereo"
                    resampler = av.audio.resampler.AudioResampler(
                        format="fltp", layout=layout, rate=aout.codec_context.sample_rate
                    )
                last_percent = -1

                streams = [s for s in (vin, ain) if s is not None]
                for packet in src.demux(*streams):
                    if checkpoint:
                        checkpoint()
                    for frame in packet.decode():
                        if packet.stream is ain:
                            for resampled in resampler.resample(frame):
                                resampled.pts = None
                                for out_packet in aout.encode(resampled):
                                    dst.mux(out_packet)
                            continue

                        pixels = rotate(frame.to_ndarray(format="rgb24"), getattr(frame, "rotation", 0))
                        # H.264 in 4:2:0 needs even sides; every frame the size
                        # of the first.
                        pixels = pixels[:height, :width]
                        if pixels.shape[0] != height or pixels.shape[1] != width:
                            continue  # a mid-stream resolution change: skip, never crash
                        seconds = float(frame.time) if frame.time is not None else 0.0
                        index = _cue_at(ordered, starts, seconds)
                        if index >= 0:
                            if index != shown_index:
                                shown_index = index
                                shown = render_overlay(ordered[index], style, width, height)
                            if shown is not None:
                                pixels = blend(np.array(pixels, copy=True), shown)
                        out = av.VideoFrame.from_ndarray(pixels, format="rgb24")
                        out.pts = frame.pts
                        out.time_base = frame.time_base
                        for out_packet in vout.encode(out):
                            dst.mux(out_packet)
                        if on_progress and duration > 0:
                            percent = min(99, int(100 * seconds / duration))
                            if percent != last_percent:
                                last_percent = percent
                                on_progress(percent)

                if resampler is not None:
                    for resampled in resampler.resample(None):
                        resampled.pts = None
                        for out_packet in aout.encode(resampled):
                            dst.mux(out_packet)
                    for out_packet in aout.encode(None):
                        dst.mux(out_packet)
                for out_packet in vout.encode(None):
                    dst.mux(out_packet)
        partial.replace(final)
    except BaseException:
        partial.unlink(missing_ok=True)
        raise
    if on_progress:
        on_progress(100)
    return final
