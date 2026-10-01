"""Drive whisper-cli.exe and turn its JSON into a WordStream.

Everything heavy happens in the whisper.cpp binary; this module only builds the
command line, follows progress, and converts tokens into words.

Two details from the whisper.cpp source that quietly break things if missed:

  * token `t0`, `t1` and `t_dtw` are in CENTISECONDS (hundredths of a second).
    The `offsets` block in the JSON is already multiplied by 10, so it is in
    milliseconds. Mixing the two shifts every subtitle by a factor of ten.
  * `-ml` / `-sow` must stay off. They are whisper.cpp's own segmentation and
    would fight with ours.
"""

from __future__ import annotations

import json
import os
import re
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterable

from ..models import Word

# The app is built without a console, and a console program started from it
# gets a black window of its own unless told not to.
_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0) if os.name == "nt" else 0

# Every whisper-cli this process has started and not yet reaped, so a cancel
# or a closing window can stop them from the GUI thread.
_running: set[subprocess.Popen] = set()
_running_lock = threading.Lock()


def stop_running() -> None:
    """Kill every whisper-cli started by this process. Safe from any thread.

    The reader loop in `run` then sees the end of the output at once, instead
    of waiting for a progress line that may be half a minute away.
    """
    with _running_lock:
        processes = list(_running)
    for process in processes:
        try:
            process.kill()
        except OSError:
            pass  # already gone

# Tokens that carry control information rather than speech.
# [_BEG_], [_EOT_], [_TT_350] ... the digits in [_TT_n] matter: a letters-only
# pattern silently glues timestamp tokens onto the previous word.
_SPECIAL_TOKEN = re.compile(r"^\s*(\[_[A-Za-z0-9_]+\]|<\|[^|]*\|>)\s*$")
_PROGRESS = re.compile(r"progress\s*=\s*(\d+)\s*%")

# Alignment-head presets accepted by `-dtw`, keyed by model family.
DTW_PRESETS = {
    "large-v3": "large.v3",
    "large-v3-q5_0": "large.v3",
    "large-v3-turbo": "large.v3.turbo",
    "large-v3-turbo-q8_0": "large.v3.turbo",
    "large-v3-turbo-q5_0": "large.v3.turbo",
}


def dtw_preset_for(model_name: str) -> str:
    """Alignment heads for a model we may not have in the table.

    A locally converted fine-tune keeps the architecture of whatever it was
    trained from, so the name is enough to choose.
    """
    if model_name in DTW_PRESETS:
        return DTW_PRESETS[model_name]
    return "large.v3.turbo" if "turbo" in model_name.lower() else "large.v3"


@dataclass
class WhisperOptions:
    binary: Path
    model: Path
    vad_model: Path | None = None
    language: str = "fa"
    beam_size: int = 5
    best_of: int = 5
    threads: int | None = None
    prompt: str = ""
    use_gpu: bool = True
    offset_ms: int | None = None
    duration_ms: int | None = None
    dtw_preset: str | None = None


def build_command(opts: WhisperOptions, audio: Path, out_prefix: Path) -> list[str]:
    cmd: list[str] = [
        str(opts.binary),
        "-m",
        str(opts.model),
        "-f",
        str(audio),
        "-l",
        opts.language,
        "-bs",
        str(opts.beam_size),
        "-bo",
        str(opts.best_of),
        "-ojf",  # full JSON: per-token probability and DTW timestamp
        "-of",
        str(out_prefix),
        "-pp",  # progress lines for the UI
    ]
    if opts.dtw_preset:
        # Flash attention silently switches DTW off inside whisper.cpp, and
        # DTW is what gives us word-accurate starts. Precision wins here.
        cmd += ["-dtw", opts.dtw_preset, "-nfa"]
    if opts.vad_model:
        cmd += ["--vad", "-vm", str(opts.vad_model)]
    if opts.threads:
        cmd += ["-t", str(opts.threads)]
    if opts.prompt:
        cmd += ["--prompt", opts.prompt]
    if not opts.use_gpu:
        cmd.append("-ng")
    if opts.offset_ms:
        cmd += ["-ot", str(opts.offset_ms)]
    if opts.duration_ms:
        cmd += ["-d", str(opts.duration_ms)]
    return cmd


def _token_time_ms(token: dict) -> tuple[float | None, float | None]:
    """Return (start, end) in milliseconds for one token.

    DTW gives a single aligned instant per token, so it can only supply the
    start; the end comes from the coarse offsets, and gets tightened against
    the next word later in `_close_gaps`.
    """
    t_dtw = token.get("t_dtw", -1)
    offsets = token.get("offsets") or {}
    start = offsets.get("from")
    end = offsets.get("to")
    end_ms = None if end is None else float(end)
    if isinstance(t_dtw, (int, float)) and t_dtw >= 0:
        return float(t_dtw) * 10.0, end_ms  # centiseconds -> milliseconds
    return (None if start is None else float(start), end_ms)


# Shortest sensible word duration; also the fallback when timings collapse.
MIN_WORD_S = 0.08


def _close_gaps(words: list[Word]) -> list[Word]:
    """Make word spans monotonic and non-overlapping.

    DTW starts are precise, but the ends inherited from segment offsets can
    overlap the next word or collapse to zero. A word never outlives the start
    of the next one.
    """
    for i, word in enumerate(words):
        limit = words[i + 1].start if i + 1 < len(words) else None
        end = word.end
        if limit is not None:
            end = min(end, limit)
        if end <= word.start:
            end = word.start + MIN_WORD_S if limit is None else min(limit, word.start + MIN_WORD_S)
        word.end = max(end, word.start + 0.01)
    return words


def words_from_json(data: dict, *, offset_ms: float = 0.0) -> list[Word]:
    """Aggregate whisper.cpp tokens into words with a confidence each."""
    words: list[Word] = []
    pending_text = ""
    pending_start: float | None = None
    pending_end: float | None = None
    pending_p: list[float] = []

    def flush() -> None:
        nonlocal pending_text, pending_start, pending_end, pending_p
        text = _whole_text(pending_text).strip()
        if text and pending_start is not None and pending_end is not None:
            words.append(
                Word(
                    text=text,
                    start=(pending_start + offset_ms) / 1000.0,
                    end=(max(pending_end, pending_start) + offset_ms) / 1000.0,
                    # One shaky token makes the whole word shaky.
                    probability=min(pending_p) if pending_p else 1.0,
                )
            )
        pending_text = ""
        pending_start = None
        pending_end = None
        pending_p = []

    for segment in data.get("transcription", []):
        seg_offsets = segment.get("offsets") or {}
        seg_start = float(seg_offsets.get("from", 0.0))
        seg_end = float(seg_offsets.get("to", seg_start))
        for token in segment.get("tokens", []):
            raw = token.get("text", "")
            if not raw or _SPECIAL_TOKEN.match(raw):
                continue
            start_ms, end_ms = _token_time_ms(token)
            if start_ms is None:
                start_ms = pending_end if pending_end is not None else seg_start
            if end_ms is None:
                end_ms = seg_end

            starts_word = raw.startswith(" ") or not pending_text
            if starts_word:
                flush()
                pending_start = start_ms
            pending_text += raw
            pending_end = end_ms
            p = token.get("p")
            if isinstance(p, (int, float)):
                pending_p.append(float(p))
        flush()

    flush()
    return _close_gaps(words)


def _whole_text(text: str) -> str:
    """Rejoin bytes that whisper.cpp split between tokens.

    Tokens are byte pieces: a two-byte Persian letter can end one token and
    finish in the next, and the JSON file then holds half a character.
    Read with surrogateescape those halves survive as placeholders; once the
    tokens of a word are joined they form the letter again. Anything still
    broken becomes U+FFFD instead of failing the whole file.
    """
    return text.encode("utf-8", "surrogateescape").decode("utf-8", "replace")


def load_words(json_path: str | Path, *, offset_ms: float = 0.0) -> list[Word]:
    # Not read_text(encoding="utf-8"): one letter split across two tokens made
    # the strict decode fail and lost a whole transcription.
    raw = Path(json_path).read_bytes().decode("utf-8", "surrogateescape")
    return words_from_json(json.loads(raw), offset_ms=offset_ms)


def parse_progress(line: str) -> int | None:
    match = _PROGRESS.search(line)
    return int(match.group(1)) if match else None


class WhisperError(RuntimeError):
    pass


def run(
    opts: WhisperOptions,
    audio: Path,
    out_prefix: Path,
    *,
    on_progress: Callable[[int], None] | None = None,
    on_log: Callable[[str], None] | None = None,
    checkpoint: Callable[[], None] | None = None,
) -> list[Word]:
    """Run whisper.cpp once and return the WordStream.

    Falls back to CPU (`-ng`) when the GPU path fails, which is what happens on
    an old driver or when the model does not fit in VRAM.

    `checkpoint` is called for every line of output and once the process has
    ended; raising from it stops the run. Whatever ends the run -- a cancel, an
    exception in a callback -- the process is killed rather than left
    decoding on the GPU with nobody reading its output.
    """
    attempts: Iterable[bool] = (True, False) if opts.use_gpu else (False,)
    last_error = ""

    for use_gpu in attempts:
        attempt = WhisperOptions(**{**opts.__dict__, "use_gpu": use_gpu})
        cmd = build_command(attempt, audio, out_prefix)
        process = subprocess.Popen(
            cmd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            encoding="utf-8",
            errors="replace",
            bufsize=1,
            creationflags=_NO_WINDOW,
        )
        with _running_lock:
            _running.add(process)
        tail: list[str] = []
        try:
            assert process.stdout is not None
            for line in process.stdout:
                if checkpoint:
                    checkpoint()
                line = line.rstrip()
                tail.append(line)
                del tail[:-40]
                if on_log:
                    on_log(line)
                if on_progress:
                    pct = parse_progress(line)
                    if pct is not None:
                        on_progress(pct)
            code = process.wait()
        finally:
            with _running_lock:
                _running.discard(process)
            if process.poll() is None:
                process.kill()
            process.wait()
            if process.stdout is not None:
                process.stdout.close()
        # A killed process ends like a failed one; without this a cancel would
        # be retried on the CPU.
        if checkpoint:
            checkpoint()
        if code == 0:
            json_path = out_prefix.with_suffix(out_prefix.suffix + ".json")
            if not json_path.exists():
                json_path = Path(f"{out_prefix}.json")
            # `-ot` already reports times on the original timeline, so no
            # offset is added here. Doing so shifted a range re-run twice.
            return load_words(json_path)
        last_error = "\n".join(tail)

    raise WhisperError(last_error or "whisper-cli failed")
