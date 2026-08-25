"""Fetch and manage the ASR models.

Written against the standard library on purpose: this code has to run on the
very first launch, before anything else is guaranteed to be installed.

Every download resumes from where it stopped. A 3 GB file over a shaky
connection is the normal case here, not the exception.
"""

from __future__ import annotations

import shutil
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from . import locate

HF_BASE = "https://huggingface.co/ggerganov/whisper.cpp/resolve/main"
HF_VAD_BASE = "https://huggingface.co/ggml-org/whisper-vad/resolve/main"
# Used when huggingface.co itself is unreachable.
MIRRORS = ["https://hf-mirror.com/ggerganov/whisper.cpp/resolve/main"]

VAD_FILE = "ggml-silero-v5.1.2.bin"
VAD_SIZE = 885_098


@dataclass
class ModelInfo:
    """One downloadable model, listed strongest first."""

    name: str
    filename: str
    size: int  # exact byte count, used to verify a finished download
    label: str
    quality: str
    speed: str
    note: str = ""

    @property
    def urls(self) -> list[str]:
        return [f"{HF_BASE}/{self.filename}"] + [f"{m}/{self.filename}" for m in MIRRORS]

    @property
    def size_gb(self) -> float:
        return self.size / 1_000_000_000


CATALOG: list[ModelInfo] = [
    ModelInfo(
        name="large-v3",
        filename="ggml-large-v3.bin",
        size=3_095_033_483,
        label="لارج v3 کامل",
        quality="حداکثر",
        speed="کند",
        note="سقف کیفیت؛ حدود ۳ تا ۴ گیگ VRAM",
    ),
    ModelInfo(
        name="large-v3-q5_0",
        filename="ggml-large-v3-q5_0.bin",
        size=1_081_140_203,
        label="لارج v3 فشرده",
        quality="۱ تا ۲٪ خطای بیشتر",
        speed="متوسط",
        note="تعادل حجم و کیفیت",
    ),
    ModelInfo(
        name="large-v3-turbo",
        filename="ggml-large-v3-turbo.bin",
        size=1_624_555_275,
        label="توربو کامل",
        quality="زیر لارج",
        speed="خیلی سریع",
    ),
    ModelInfo(
        name="large-v3-turbo-q8_0",
        filename="ggml-large-v3-turbo-q8_0.bin",
        size=874_188_075,
        label="توربو q8",
        quality="زیر توربو کامل",
        speed="خیلی سریع",
    ),
    ModelInfo(
        name="large-v3-turbo-q5_0",
        filename="ggml-large-v3-turbo-q5_0.bin",
        size=574_041_195,
        label="توربو q5",
        quality="افت محسوس",
        speed="خیلی سریع",
        note="برای سیستم ضعیف",
    ),
]

CATALOG_BY_NAME = {m.name: m for m in CATALOG}


class DownloadError(RuntimeError):
    pass


@dataclass
class Progress:
    downloaded: int = 0
    total: int = 0
    resumed: int = 0
    urls_tried: list[str] = field(default_factory=list)

    @property
    def percent(self) -> float:
        return 100.0 * self.downloaded / self.total if self.total else 0.0


def free_space(path: Path) -> int:
    return shutil.disk_usage(path).free


def _open(url: str, offset: int):
    request = urllib.request.Request(url, headers={"User-Agent": "FarsiSub"})
    if offset:
        request.add_header("Range", f"bytes={offset}-")
    return urllib.request.urlopen(request, timeout=60)


def download(
    urls: list[str],
    target: Path,
    expected_size: int = 0,
    *,
    on_progress: Callable[[Progress], None] | None = None,
    chunk: int = 1 << 20,
) -> Path:
    """Download to `target`, resuming a partial `.part` file when present."""
    target.parent.mkdir(parents=True, exist_ok=True)
    if target.exists() and (not expected_size or target.stat().st_size == expected_size):
        return target

    partial = target.with_suffix(target.suffix + ".part")
    if expected_size:
        needed = expected_size - (partial.stat().st_size if partial.exists() else 0)
        if free_space(target.parent) < needed + (100 << 20):
            raise DownloadError(
                f"فضای دیسک کافی نیست: حدود {needed / 1e9:.1f} گیگابایت لازم است"
            )

    progress = Progress(total=expected_size)
    last_error: Exception | None = None

    for url in urls:
        offset = partial.stat().st_size if partial.exists() else 0
        progress.urls_tried.append(url)
        try:
            with _open(url, offset) as response:
                # A server that ignores Range restarts the file from zero.
                if offset and response.status != 206:
                    offset = 0
                    partial.unlink(missing_ok=True)
                if not expected_size:
                    length = response.headers.get("Content-Length")
                    if length:
                        progress.total = int(length) + offset
                progress.resumed = offset
                progress.downloaded = offset

                mode = "ab" if offset else "wb"
                with open(partial, mode) as handle:
                    while True:
                        block = response.read(chunk)
                        if not block:
                            break
                        handle.write(block)
                        progress.downloaded += len(block)
                        if on_progress:
                            on_progress(progress)

            if expected_size and partial.stat().st_size != expected_size:
                raise DownloadError(
                    f"حجم فایل دانلودشده نادرست است: {partial.stat().st_size} به‌جای {expected_size}"
                )
            partial.replace(target)
            return target
        except (urllib.error.URLError, TimeoutError, OSError, DownloadError) as error:
            last_error = error
            continue

    raise DownloadError(f"دانلود ناموفق بود: {last_error}")


def download_model(
    name: str, *, on_progress: Callable[[Progress], None] | None = None
) -> Path:
    info = CATALOG_BY_NAME.get(name)
    if info is None:
        raise DownloadError(f"مدل ناشناخته: {name}")
    return download(
        info.urls, locate.models_dir() / info.filename, info.size, on_progress=on_progress
    )


def download_vad(*, on_progress: Callable[[Progress], None] | None = None) -> Path:
    target = locate.bin_dir() / VAD_FILE
    return download(
        [f"{HF_VAD_BASE}/{VAD_FILE}"], target, VAD_SIZE, on_progress=on_progress
    )


def import_model_file(source: str | Path) -> Path:
    """Install a model the user copied over by hand (flash drive, no internet)."""
    src = Path(source)
    if not src.exists():
        raise DownloadError(f"فایل پیدا نشد: {src}")
    match = next((m for m in CATALOG if m.filename == src.name), None)
    if match and src.stat().st_size != match.size:
        raise DownloadError("حجم فایل با مدل رسمی نمی‌خواند؛ احتمالاً ناقص است")
    target = locate.models_dir() / src.name
    shutil.copy2(src, target)
    return target


def delete_model(name: str) -> bool:
    path = locate.model_path(name)
    if path is None:
        return False
    path.unlink()
    return True


def status() -> list[tuple[ModelInfo, bool]]:
    installed = set(locate.installed_models())
    return [(info, info.name in installed) for info in CATALOG]
