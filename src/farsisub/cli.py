"""Headless entry point: batch runs, testing, and re-rendering saved projects.

    python -m farsisub.cli video.mp4 --profile smart
    python -m farsisub.cli video.fsub --profile reels --render-only
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from . import __version__
from .config import BUILTIN_PROFILES, AppConfig
from .logging_setup import setup as setup_logging
from .engine import locate
from .models import Project
from .pipeline import PipelineError, process, render


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="farsisub",
        description="ساخت زیرنویس فارسی از روی ویدیو، کاملاً محلی",
    )
    parser.add_argument("input", nargs="?", help="مسیر ویدیو یا فایل پروژه .fsub")
    parser.add_argument(
        "--profile", choices=sorted(BUILTIN_PROFILES), default="smart", help="سبک زیرنویس"
    )
    parser.add_argument("--model", default="large-v3", help="نام مدل")
    parser.add_argument("--language", default="fa", help="زبان صدا (پیش‌فرض فارسی)")
    parser.add_argument("--output-dir", help="پوشه خروجی (پیش‌فرض: کنار ویدیو)")
    parser.add_argument("--format", default="srt", choices=["srt", "vtt", "txt"])
    parser.add_argument("--latin-digits", action="store_true", help="ارقام لاتین به‌جای فارسی")
    parser.add_argument("--keep-period", action="store_true", help="نقطه انتهای جمله حفظ شود")
    parser.add_argument("--no-bom", action="store_true", help="بدون BOM در فایل خروجی")
    parser.add_argument("--prompt", default="", help="واژگان دلخواه برای تزریق به مدل")
    parser.add_argument("--render-only", action="store_true", help="فقط رندر دوباره از .fsub")
    parser.add_argument("--list-models", action="store_true", help="مدل‌های نصب‌شده")
    parser.add_argument(
        "--fix",
        action="append",
        metavar="شنیده=درست",
        help="افزودن اصلاح به دیکشنری، مثال: --fix بوهران=بحران",
    )
    parser.add_argument("--list-fixes", action="store_true", help="نمایش دیکشنری اصلاحات")
    parser.add_argument("--quiet", action="store_true")
    parser.add_argument("--version", action="version", version=f"FarsiSub {__version__}")
    return parser


def config_from_args(args: argparse.Namespace) -> AppConfig:
    config = AppConfig()
    config.profile = BUILTIN_PROFILES[args.profile]
    config.model_name = args.model
    config.language = args.language
    config.output_dir = args.output_dir
    config.text.persian_digits = not args.latin_digits
    config.text.strip_final_period = not args.keep_period
    config.text.bom = not args.no_bom
    return config


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    setup_logging()

    if args.fix:
        from .text.corrections import add_correction

        for pair in args.fix:
            heard, _, correct = pair.partition("=")
            if not correct:
                print(f"قالب درست: --fix شنیده=درست (دریافت شد: {pair})", file=sys.stderr)
                return 2
            path = add_correction(heard, correct)
        print(f"ذخیره شد در {path}")
        return 0

    if args.list_fixes:
        from .text.corrections import build_table

        for heard, correct in sorted(build_table().items()):
            print(f"{heard} -> {correct}")
        return 0

    if args.list_models:
        installed = locate.installed_models()
        print("\n".join(installed) if installed else "هیچ مدلی نصب نشده است")
        return 0

    if not args.input:
        build_parser().print_help()
        return 2

    config = config_from_args(args)
    source = Path(args.input)
    suffix = f".{args.format}"

    def progress(pct: int) -> None:
        if not args.quiet:
            print(f"\r{pct:3d}%", end="", file=sys.stderr, flush=True)

    try:
        if args.render_only or source.suffix.lower() == ".fsub":
            try:
                project = Project.load(source)
            except (OSError, ValueError, KeyError) as error:
                raise PipelineError(f"فایل پروژه خوانده نشد: {source} ({error})") from error
            if project.lines and not args.quiet:
                print(
                    "این پروژه در ویرایشگر شکل داده شده؛ همان خط‌ها نوشته می‌شود "
                    "و سبک فقط شکست سطر را تعیین می‌کند.",
                    file=sys.stderr,
                )
            written = render(project, config, suffix=suffix)
        else:
            _, written = process(
                source,
                config,
                prompt=args.prompt,
                suffix=suffix,
                on_progress=None if args.quiet else progress,
            )
    except PipelineError as error:
        print(f"\nخطا: {error}", file=sys.stderr)
        return 1
    except OSError as error:  # an output folder that cannot be written, say
        print(f"\nخطا: {error}", file=sys.stderr)
        return 1

    if not args.quiet:
        print()
    print(written)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
