"""Run the same clip through several models and put the results side by side.

    python tools/compare_models.py video.mp4 large-v3 persian-v3

Prints per-model stats and the first cues of each, so a claim like "the Persian
fine-tune is better" can be checked instead of assumed.
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from farsisub.config import BUILTIN_PROFILES, AppConfig  # noqa: E402
from farsisub.engine import locate  # noqa: E402
from farsisub.pipeline import PipelineError, transcribe  # noqa: E402
from farsisub.render.segment import build_cues  # noqa: E402
from farsisub.render.writers import write_subtitle  # noqa: E402


def stats(words) -> dict[str, float]:
    if not words:
        return {"words": 0, "mean_p": 0.0, "low": 0, "low_pct": 0.0}
    low = [w for w in words if w.probability < 0.6]
    return {
        "words": len(words),
        "mean_p": sum(w.probability for w in words) / len(words),
        "low": len(low),
        "low_pct": 100.0 * len(low) / len(words),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="مقایسه چند مدل روی یک ویدیو")
    parser.add_argument("video")
    parser.add_argument("models", nargs="+")
    parser.add_argument("--profile", default="smart", choices=sorted(BUILTIN_PROFILES))
    parser.add_argument("--cues", type=int, default=8, help="چند cue اول نمایش داده شود")
    parser.add_argument("--out-dir", default="demo")
    args = parser.parse_args()

    video = Path(args.video)
    results: dict[str, tuple[dict, list]] = {}

    for name in args.models:
        if locate.model_path(name) is None:
            print(f"مدل «{name}» نصب نیست — رد شد", file=sys.stderr)
            continue

        config = AppConfig()
        config.model_name = name
        config.profile = BUILTIN_PROFILES[args.profile]

        print(f"\n=== {name} ===", flush=True)
        started = time.time()
        try:
            project = transcribe(video, config)
        except PipelineError as error:
            print(f"  خطا: {error}", file=sys.stderr)
            continue
        elapsed = time.time() - started

        cues = build_cues(project.words, config.profile, config.text)
        out = Path(args.out_dir) / f"{video.stem}__{name}.srt"
        write_subtitle(cues, out, bom=config.text.bom)

        numbers = stats(project.words)
        numbers["seconds"] = elapsed
        numbers["cues"] = len(cues)
        results[name] = (numbers, cues)

        print(
            f"  {numbers['words']} کلمه | میانگین اطمینان {numbers['mean_p']:.3f} | "
            f"مشکوک {numbers['low']} ({numbers['low_pct']:.1f}%) | "
            f"{len(cues)} cue | {elapsed:.1f} ثانیه"
        )
        print(f"  خروجی: {out}")

    if len(results) < 2:
        return 0

    print("\n" + "=" * 70)
    print("مقایسه cue به cue")
    print("=" * 70)
    names = list(results)
    for index in range(args.cues):
        print(f"\n[{index + 1}]")
        for name in names:
            cues = results[name][1]
            text = cues[index].text.replace("\n", " ⏎ ") if index < len(cues) else "—"
            print(f"  {name:>14}: {text}")

    print("\n" + "=" * 70)
    header = f"{'مدل':>14} {'کلمه':>7} {'اطمینان':>9} {'مشکوک':>8} {'cue':>6} {'ثانیه':>8}"
    print(header)
    for name, (numbers, _) in results.items():
        print(
            f"{name:>14} {numbers['words']:>7} {numbers['mean_p']:>9.3f} "
            f"{numbers['low_pct']:>7.1f}% {numbers['cues']:>6} {numbers['seconds']:>8.1f}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
