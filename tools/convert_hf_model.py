"""Turn a Hugging Face Whisper fine-tune into a ggml model whisper.cpp can run.

    .venv-convert/Scripts/python tools/convert_hf_model.py \
        --repo AmirMohseni/whisper-large-v3-persian-bf16 --name persian-v3

Needs torch + transformers, which is why it lives in its own virtualenv: the
app itself never imports them.

The converter from whisper.cpp also wants `mel_filters.npz` out of the openai
whisper repo, so that single file is fetched too (about 4 MB) rather than
cloning the whole repository.
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
WORK = ROOT / "build" / "convert"

CONVERTER_URL = (
    "https://raw.githubusercontent.com/ggml-org/whisper.cpp/master/models/convert-h5-to-ggml.py"
)
MEL_URL = "https://raw.githubusercontent.com/openai/whisper/main/whisper/assets/mel_filters.npz"


def fetch(url: str, target: Path) -> Path:
    if target.exists() and target.stat().st_size > 0:
        return target
    target.parent.mkdir(parents=True, exist_ok=True)
    request = urllib.request.Request(url, headers={"User-Agent": "FarsiSub"})
    with urllib.request.urlopen(request, timeout=120) as response, open(target, "wb") as handle:
        shutil.copyfileobj(response, handle)
    print(f"  دریافت شد: {target.name} ({target.stat().st_size / 1e6:.1f} MB)")
    return target


def patch_converter(script: Path) -> None:
    """Teach the upstream converter about bfloat16 weights.

    numpy has no bfloat16, so `tensor.numpy()` raises
    "Got unsupported ScalarType BFloat16" on any bf16 checkpoint -- which is
    what most recent fine-tunes are published as. Casting to float32 first
    costs nothing: the ggml writer converts to f16 straight after.
    """
    text = script.read_text(encoding="utf-8")
    if ".squeeze().float().numpy()" in text:
        return
    patched = text.replace(".squeeze().numpy()", ".squeeze().float().numpy()")
    if patched != text:
        script.write_text(patched, encoding="utf-8")
        print("  مبدل برای وزن‌های bfloat16 وصله شد")


def download_model(repo: str) -> Path:
    from huggingface_hub import snapshot_download

    print(f"دانلود مدل {repo} ...")
    path = snapshot_download(
        repo_id=repo,
        allow_patterns=[
            "*.json",
            "*.safetensors",
            "*.txt",
            "*.model",
        ],
        local_dir=str(WORK / "hf" / repo.replace("/", "_")),
    )
    return Path(path)


def main() -> int:
    parser = argparse.ArgumentParser(description="تبدیل مدل HuggingFace به ggml")
    parser.add_argument("--repo", required=True, help="مثال: AmirMohseni/whisper-large-v3-persian-bf16")
    parser.add_argument("--name", required=True, help="نام کوتاه مدل در برنامه")
    args = parser.parse_args()

    WORK.mkdir(parents=True, exist_ok=True)
    model_dir = download_model(args.repo)

    # The converter reads exactly one file out of the whisper repo layout.
    fake_repo = WORK / "whisper-repo"
    fetch(MEL_URL, fake_repo / "whisper" / "assets" / "mel_filters.npz")
    converter = fetch(CONVERTER_URL, WORK / "convert-h5-to-ggml.py")
    patch_converter(converter)

    out_dir = WORK / "out" / args.name
    out_dir.mkdir(parents=True, exist_ok=True)

    print("تبدیل به ggml ...")
    result = subprocess.run(
        [sys.executable, str(converter), str(model_dir), str(fake_repo), str(out_dir)],
        check=False,
    )
    if result.returncode != 0:
        print("تبدیل ناموفق بود", file=sys.stderr)
        return result.returncode

    produced = out_dir / "ggml-model.bin"
    if not produced.exists():
        print("فایل خروجی ساخته نشد", file=sys.stderr)
        return 1

    # Install it where the app looks for models. This used to be a hard-coded
    # %LOCALAPPDATA%\FarsiSub\models, which the app stopped reading when its
    # data moved beside the program: the converted model never showed up.
    sys.path.insert(0, str(ROOT / "src"))
    from farsisub.engine import locate

    target = locate.models_dir() / f"ggml-{args.name}.bin"
    shutil.move(str(produced), target)
    print(f"\nآماده است: {target}  ({target.stat().st_size / 1e9:.2f} GB)")
    print(f"در برنامه با نام «{args.name}» انتخاب می‌شود.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
