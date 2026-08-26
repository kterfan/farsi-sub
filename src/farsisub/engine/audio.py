"""Audio inspection: does this file even have sound, how loud is each word.

Uses PyAV, which ships FFmpeg inside its wheel -- no ffmpeg.exe to install and
nothing extra to put in the installer.

The loudness envelope is stored in fixed 10 ms bins rather than raw samples:
90 minutes of audio becomes ~540k floats instead of ~86 million, which is the
difference between a responsive waveform and a frozen window.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from ..models import Word

BIN_MS = 10
SAMPLE_RATE = 16_000


class AudioError(RuntimeError):
    pass


@dataclass
class MediaInfo:
    has_audio: bool
    duration: float
    audio_codec: str = ""
    video_codec: str = ""


def probe(path: str | Path) -> MediaInfo:
    """Check a file before spending twenty minutes transcribing nothing."""
    try:
        import av
    except ImportError as error:  # pragma: no cover - depends on install state
        raise AudioError("کتابخانه PyAV نصب نیست") from error

    try:
        with av.open(str(path)) as container:
            audio = next((s for s in container.streams if s.type == "audio"), None)
            video = next((s for s in container.streams if s.type == "video"), None)
            duration = float(container.duration / 1_000_000) if container.duration else 0.0
            return MediaInfo(
                has_audio=audio is not None,
                duration=duration,
                audio_codec=audio.codec_context.name if audio else "",
                video_codec=video.codec_context.name if video else "",
            )
    except Exception as error:
        raise AudioError(f"فایل قابل خواندن نیست: {error}") from error


def extract_wav(source: str | Path, target: str | Path, sample_rate: int = SAMPLE_RATE) -> Path:
    """Pull a 16 kHz mono WAV out of any container.

    whisper-cli reads flac/mp3/ogg/wav only -- hand it an mp4 or mkv and it
    simply refuses. PyAV does the demux and resample, so no ffmpeg.exe needed.
    """
    import av

    src = Path(source)
    dst = Path(target)
    dst.parent.mkdir(parents=True, exist_ok=True)

    with av.open(str(src)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise AudioError(f"این فایل ترک صوتی ندارد: {src.name}")
        stream.thread_type = "AUTO"

        with av.open(str(dst), mode="w", format="wav") as out:
            out_stream = out.add_stream("pcm_s16le", rate=sample_rate, layout="mono")
            resampler = av.audio.resampler.AudioResampler(
                format="s16", layout="mono", rate=sample_rate
            )
            for frame in container.decode(stream):
                for resampled in resampler.resample(frame):
                    resampled.pts = None
                    for packet in out_stream.encode(resampled):
                        out.mux(packet)
            for packet in out_stream.encode(None):
                out.mux(packet)

    return dst


def energy_envelope(path: str | Path, bin_ms: int = BIN_MS):
    """RMS loudness per time bin, as a numpy array."""
    import av
    import numpy as np

    samples_per_bin = max(1, SAMPLE_RATE * bin_ms // 1000)
    bins: list[float] = []
    carry = np.zeros(0, dtype=np.float32)

    with av.open(str(path)) as container:
        stream = next((s for s in container.streams if s.type == "audio"), None)
        if stream is None:
            raise AudioError("این فایل ترک صوتی ندارد")
        stream.thread_type = "AUTO"
        resampler = av.audio.resampler.AudioResampler(
            format="flt", layout="mono", rate=SAMPLE_RATE
        )
        for frame in container.decode(stream):
            for resampled in resampler.resample(frame):
                chunk = resampled.to_ndarray().reshape(-1).astype(np.float32)
                carry = np.concatenate((carry, chunk)) if carry.size else chunk
                usable = (carry.size // samples_per_bin) * samples_per_bin
                if usable:
                    block = carry[:usable].reshape(-1, samples_per_bin)
                    bins.extend(np.sqrt((block**2).mean(axis=1)).tolist())
                    carry = carry[usable:]

    if carry.size:
        bins.append(float(np.sqrt((carry**2).mean())))
    return np.asarray(bins, dtype=np.float32)


def word_energies(
    words: Sequence[Word], envelope, bin_ms: int = BIN_MS
) -> list[float]:
    """Average loudness over each word's time span."""
    import numpy as np

    values: list[float] = []
    total = len(envelope)
    for word in words:
        start = min(total - 1, max(0, int(word.start * 1000 / bin_ms)))
        end = min(total, max(start + 1, int(word.end * 1000 / bin_ms)))
        span = envelope[start:end]
        values.append(float(np.mean(span)) if span.size else 0.0)
    return values


def drop_silent_words(
    words: list[Word], energies: Sequence[float], *, max_probability: float = 0.6
) -> list[Word]:
    """Remove words the model invented over silence.

    whisper.cpp's own VAD would do this, but enabling it collapses the
    timeline: with `--vad` the words after a three second pause came back
    ~3.5 s early. So silence is handled here, where the timestamps stay honest.

    Two guards, both learned the hard way:
      * only near-total silence counts as silence -- quiet speech survives;
      * a word the model was confident about is kept even if it lands in a
        silent gap, because DTW sometimes parks a real word a few seconds off.
        A real clip lost the word "گوش" (p=0.95) to the first version of this.
    """
    import numpy as np

    if not words or len(energies) < len(words):
        return words

    values = np.asarray(energies, dtype=np.float32)
    loud = float(np.percentile(values, 90)) if values.size else 0.0
    if loud <= 0:
        return words
    floor = loud * 0.03

    return [
        word
        for word, energy in zip(words, values)
        if energy > floor or word.probability >= max_probability
    ]


def speech_regions(
    envelope, bin_ms: int = BIN_MS, *, min_length: float = 0.4
) -> list[tuple[float, float]]:
    """Stretches where someone is audibly talking.

    Used to check the finished transcript against the audio: anything the
    model left silent here is a hole worth a second look.
    """
    import numpy as np

    if len(envelope) == 0:
        return []
    loud = float(np.percentile(envelope, 90))
    if loud <= 0:
        return []
    speaking = envelope > loud * 0.08

    regions: list[tuple[float, float]] = []
    start: int | None = None
    for index, on in enumerate(speaking):
        if on and start is None:
            start = index
        elif not on and start is not None:
            if (index - start) * bin_ms / 1000 >= min_length:
                regions.append((start * bin_ms / 1000, index * bin_ms / 1000))
            start = None
    if start is not None:
        regions.append((start * bin_ms / 1000, len(speaking) * bin_ms / 1000))
    return regions


def uncovered_speech(
    words: Sequence[Word],
    envelope,
    *,
    bin_ms: int = BIN_MS,
    min_gap: float = 1.2,
    covered_fraction: float = 0.3,
) -> list[tuple[float, float]]:
    """Speech regions the transcript barely touches."""
    spans = [(w.start, w.end) for w in words]

    def covered(start: float, end: float) -> float:
        return sum(min(end, e) - max(start, s) for s, e in spans if e > start and s < end)

    holes = []
    for start, end in speech_regions(envelope, bin_ms):
        length = end - start
        if length >= min_gap and covered(start, end) < length * covered_fraction:
            holes.append((start, end))
    return holes


def waveform_points(envelope, width: int = 1200) -> list[float]:
    """Downsample the envelope to one value per pixel for the editor."""
    import numpy as np

    if len(envelope) == 0:
        return []
    if len(envelope) <= width:
        peak = float(np.max(envelope)) or 1.0
        return (envelope / peak).tolist()

    step = len(envelope) / width
    points = [
        float(np.max(envelope[int(i * step) : max(int((i + 1) * step), int(i * step) + 1)]))
        for i in range(width)
    ]
    peak = max(points) or 1.0
    return [p / peak for p in points]
