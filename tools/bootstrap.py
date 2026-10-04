"""Fetch everything the app needs to actually run: engine binary, VAD, model.

    python tools/bootstrap.py --model large-v3

Downloads resume, so a dropped connection costs nothing but a rerun. The same
downloader backs the first-run wizard in the GUI.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
import zipfile
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from farsisub.engine import locate, modelstore  # noqa: E402

RELEASES_API = "https://api.github.com/repos/ggml-org/whisper.cpp/releases/latest"
RELEASE_DOWNLOAD = "https://github.com/ggml-org/whisper.cpp/releases/download/{version}/{name}"

# The engine the app is built and measured against. "Latest" is not safe:
# v1.9.4 shipped without the Windows CUDA archive, and flags such as -dtw and
# -nfa behave differently between versions (see HANDOFF.md).
DEFAULT_ENGINE_VERSION = "v1.8.2"

# Preference order for the Windows build. Vulkan has no official binary yet, so
# CUDA covers NVIDIA and the plain CPU build covers everything else.
ASSET_PREFERENCE = {
    "cuda": ["whisper-cublas-12.4.0-bin-x64.zip", "whisper-cublas-11.8.0-bin-x64.zip"],
    "cpu": ["whisper-blas-bin-x64.zip", "whisper-bin-x64.zip"],
}


def human(size: float) -> str:
    return f"{size / 1e9:.2f} GB" if size >= 1e9 else f"{size / 1e6:.0f} MB"


class Reporter:
    """One rewritable progress line per file."""

    def __init__(self, label: str) -> None:
        self.label = label
        self.started = time.time()
        self.last = 0.0

    def __call__(self, progress: modelstore.Progress) -> None:
        now = time.time()
        if now - self.last < 0.5 and progress.downloaded < progress.total:
            return
        self.last = now
        elapsed = max(0.001, now - self.started)
        speed = (progress.downloaded - progress.resumed) / elapsed
        remaining = (progress.total - progress.downloaded) / speed if speed > 0 else 0
        print(
            f"\r{self.label}: {progress.percent:5.1f}%  "
            f"{human(progress.downloaded)}/{human(progress.total)}  "
            f"{speed / 1e6:5.1f} MB/s  باقی‌مانده {remaining / 60:4.1f} دقیقه",
            end="",
            flush=True,
        )

    def done(self) -> None:
        print()


def release_assets() -> dict[str, dict]:
    request = urllib.request.Request(RELEASES_API, headers={"User-Agent": "FarsiSub"})
    with urllib.request.urlopen(request, timeout=30) as response:
        data = json.load(response)
    return {asset["name"]: asset for asset in data.get("assets", [])}


def fetch_engine(flavour: str, version: str | None = DEFAULT_ENGINE_VERSION) -> Path:
    """Download and unpack whisper.cpp into bin/.

    With a version the archive is fetched straight from that release, no API
    call; `None` asks the API for the latest release instead.
    """
    bin_dir = locate.bin_dir()
    bin_dir.mkdir(parents=True, exist_ok=True)
    reporter = Reporter(f"موتور ({flavour} {version or 'latest'})")
    archive: Path | None = None
    if version:
        for name in ASSET_PREFERENCE[flavour]:
            try:
                archive = modelstore.download(
                    [RELEASE_DOWNLOAD.format(version=version, name=name)],
                    bin_dir / name,
                    on_progress=reporter,
                )
                break
            except modelstore.DownloadError as error:
                print(f"\n{name}: {error}")
    else:
        assets = release_assets()
        chosen = next((assets[n] for n in ASSET_PREFERENCE[flavour] if n in assets), None)
        if chosen is not None:
            archive = modelstore.download(
                [chosen["browser_download_url"]],
                bin_dir / chosen["name"],
                chosen["size"],
                on_progress=reporter,
            )
    if archive is None:
        raise SystemExit(f"هیچ فایل مناسبی برای {flavour} در انتشار {version or 'latest'} پیدا نشد")
    reporter.done()

    with zipfile.ZipFile(archive) as zf:
        for member in zf.namelist():
            name = Path(member).name
            if not name or member.endswith("/"):
                continue
            # The archives nest everything under Release/; flatten into bin/.
            with zf.open(member) as src, open(bin_dir / name, "wb") as dst:
                dst.write(src.read())
    archive.unlink()
    return bin_dir


def main() -> int:
    parser = argparse.ArgumentParser(description="آماده‌سازی موتور و مدل")
    parser.add_argument("--model", default="large-v3", choices=sorted(modelstore.CATALOG_BY_NAME))
    parser.add_argument("--flavour", default="cuda", choices=sorted(ASSET_PREFERENCE))
    parser.add_argument("--skip-engine", action="store_true")
    parser.add_argument("--skip-model", action="store_true")
    parser.add_argument(
        "--version",
        default=DEFAULT_ENGINE_VERSION,
        help="نسخه whisper.cpp، مثل v1.8.2؛ latest برای آخرین انتشار",
    )
    args = parser.parse_args()

    if not args.skip_engine:
        fetch_engine(args.flavour, None if args.version == "latest" else args.version)
        reporter = Reporter("مدل VAD")
        modelstore.download_vad(on_progress=reporter)
        reporter.done()

    if not args.skip_model:
        info = modelstore.CATALOG_BY_NAME[args.model]
        reporter = Reporter(f"مدل {info.name}")
        modelstore.download_model(args.model, on_progress=reporter)
        reporter.done()

    print("\nآماده است:")
    print(f"  باینری : {locate.whisper_binary()}")
    print(f"  VAD    : {locate.vad_model()}")
    print(f"  مدل‌ها  : {', '.join(locate.installed_models()) or 'هیچ'}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
