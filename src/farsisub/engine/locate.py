"""Find the whisper.cpp binary, the VAD model, and the downloaded ASR models.

Layout used at runtime:

    <install dir>/bin/whisper-cli.exe          shipped in the installer
    <install dir>/bin/ggml-silero-v5.1.2.bin   shipped (885 KB, no reason to download)
    <install dir>/data/models/*.bin            downloaded on first run (see data_dir)

During development everything can be overridden with environment variables so
the same code runs from a source checkout.
"""

from __future__ import annotations

import os
import sys
from functools import lru_cache
from pathlib import Path

APP_NAME = "FarsiSub"

MODEL_FILES = {
    "large-v3": "ggml-large-v3.bin",
    "large-v3-q5_0": "ggml-large-v3-q5_0.bin",
    "large-v3-turbo": "ggml-large-v3-turbo.bin",
    "large-v3-turbo-q8_0": "ggml-large-v3-turbo-q8_0.bin",
    "large-v3-turbo-q5_0": "ggml-large-v3-turbo-q5_0.bin",
}


def install_dir() -> Path:
    """Where the application lives; also where its data folder goes."""
    if getattr(sys, "frozen", False):
        return Path(sys.executable).parent
    return Path(__file__).resolve().parents[3]


def resource_dir() -> Path:
    """Where files bundled with the app live.

    A frozen build unpacks its data into `_internal`, next to the executable
    but not beside it, so binaries and fonts have to be looked up there while
    user data stays in the visible folder.
    """
    bundled = getattr(sys, "_MEIPASS", None)
    return Path(bundled) if bundled else install_dir()


def bin_dir() -> Path:
    return Path(os.environ.get("FARSISUB_BIN", resource_dir() / "bin"))


def data_dir() -> Path:
    """Where models, logs, projects and the glossary live.

    Next to the application by default, on purpose. %LOCALAPPDATA% looks like
    the obvious home, but it is redirected for sandboxed processes: a model
    downloaded by one process landed in a container private folder and was
    invisible to the app the user actually launched. A path beside the program
    means every process sees the same files.

    Falls back to %LOCALAPPDATA% when the program folder is read only, which is
    what a Program Files install will be.
    """
    override = os.environ.get("FARSISUB_DATA")
    if override:
        return Path(override)
    return _default_data_dir()


@lru_cache(maxsize=1)
def _default_data_dir() -> Path:
    """Decided once per process.

    This is asked for on every button refresh and every time the window is
    activated; probing the disk each time wrote and deleted a file again and
    again. The probe name is per process: two copies starting together (the
    app and a CLI run) once tripped over one shared probe file on Windows,
    and the loser quietly fell back to the other folder.
    """
    local = install_dir() / "data"
    try:
        local.mkdir(parents=True, exist_ok=True)
        probe = local / f".writable-{os.getpid()}"
        probe.write_text("", encoding="utf-8")
        probe.unlink()
        return local
    except OSError:
        base = os.environ.get("LOCALAPPDATA") or str(Path.home() / ".local" / "share")
        return Path(base) / APP_NAME


def projects_dir() -> Path:
    """Where .fsub project files live.

    Deliberately NOT next to the video: a JSON sitting beside the subtitle
    looks like a broken subtitle, and subtitle editors will happily open it as
    one word per line.
    """
    path = data_dir() / "projects"
    path.mkdir(parents=True, exist_ok=True)
    return path


def project_path(video: str | Path) -> Path:
    """Stable name per video, including a hash so two files called
    `001.mp4` in different folders do not overwrite each other."""
    import hashlib

    video = Path(video)
    digest = hashlib.sha1(str(video.resolve()).encode("utf-8")).hexdigest()[:8]
    return projects_dir() / f"{video.stem}-{digest}.fsub"


MODEL_DIRS_FILE = "model_dirs.txt"


def models_dir() -> Path:
    """Where downloads land."""
    path = data_dir() / "models"
    path.mkdir(parents=True, exist_ok=True)
    return path


def extra_model_dirs() -> list[Path]:
    """Folders to look in besides the download folder.

    Model files are gigabytes each; an installed copy should be able to use a
    set that is already on the disk instead of fetching it again. One path per
    line in data/model_dirs.txt.
    """
    listing = data_dir() / MODEL_DIRS_FILE
    if not listing.exists():
        return []
    dirs = []
    for line in listing.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if line and not line.startswith("#"):
            path = Path(line)
            if path.is_dir():
                dirs.append(path)
    return dirs


def add_model_dir(folder: str | Path) -> Path:
    """Register another folder of models."""
    listing = data_dir() / MODEL_DIRS_FILE
    folder = str(Path(folder).resolve())
    existing = []
    if listing.exists():
        existing = [l.strip() for l in listing.read_text(encoding="utf-8").splitlines()]
    if folder not in existing:
        existing.append(folder)
    listing.write_text(chr(10).join(filter(None, existing)) + chr(10), encoding="utf-8")
    return listing


def model_search_dirs() -> list[Path]:
    return [models_dir(), *extra_model_dirs()]


def whisper_binary() -> Path | None:
    name = "whisper-cli.exe" if os.name == "nt" else "whisper-cli"
    candidate = bin_dir() / name
    return candidate if candidate.exists() else None


def vad_model() -> Path | None:
    candidate = bin_dir() / "ggml-silero-v5.1.2.bin"
    return candidate if candidate.exists() else None


def model_path(model_name: str) -> Path | None:
    """Official name, custom name, or a bare filename -- all resolve here."""
    for folder in model_search_dirs():
        for filename in (
            MODEL_FILES.get(model_name),
            f"ggml-{model_name}.bin",
            model_name,
        ):
            if not filename:
                continue
            candidate = folder / filename
            if candidate.exists():
                return candidate
    return None


def custom_models() -> list[str]:
    """Models converted locally, e.g. a Persian fine-tune."""
    known = set(MODEL_FILES.values())
    names: list[str] = []
    for folder in model_search_dirs():
        for path in sorted(folder.glob("ggml-*.bin")):
            name = path.stem.removeprefix("ggml-")
            if path.name not in known and name not in names:
                names.append(name)
    return names


def installed_models() -> list[str]:
    present: set[str] = set()
    for folder in model_search_dirs():
        present |= {p.name for p in folder.glob("*.bin")}
    official = [name for name, filename in MODEL_FILES.items() if filename in present]
    return official + custom_models()
