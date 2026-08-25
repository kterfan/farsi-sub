"""Video in, subtitle file out.

    transcribe()  video -> Project (the WordStream, saved once)
    render()      Project -> subtitle file (repeatable, instant, free)

The split is the whole point: changing a style, a digit setting or a line
length re-runs render() only, never the model.
"""

from __future__ import annotations

import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from .config import AppConfig
from .engine import audio as audio_module
from .engine import locate
from .engine.whispercpp import WhisperOptions, dtw_preset_for, run
from .models import Project, Word
from .render.keywords import mark_keywords
from .render.merge import arbitrate_repeats, merge_streams
from .render.segment import build_cues
from .render.writers import write_subtitle
from .text import corrections as corrections_module
from .text.repetition import drop_repetitions
from .text.normalize import normalize_word


class PipelineError(RuntimeError):
    pass


@dataclass
class Tools:
    binary: Path
    model: Path
    model_name: str
    vad_model: Path | None


def resolve_tools(model_name: str) -> Tools:
    binary = locate.whisper_binary()
    if binary is None:
        raise PipelineError(
            "whisper-cli پیدا نشد. مسیر مورد انتظار: " + str(locate.bin_dir())
        )
    model = locate.model_path(model_name)
    if model is None:
        available = locate.installed_models()
        hint = "، ".join(available) if available else "هیچ مدلی"
        raise PipelineError(
            f"مدل «{model_name}» دانلود نشده است. مدل‌های موجود: {hint}"
        )
    return Tools(binary=binary, model=model, model_name=model_name, vad_model=locate.vad_model())


def _fill_with_second_model(
    words: list[Word],
    config: AppConfig,
    options: WhisperOptions,
    wav: Path,
    tmp: Path,
    *,
    on_log=None,
    on_progress=None,
) -> list[Word]:
    """Run the merge model and splice it into the holes of the first pass."""
    model = locate.model_path(config.merge_model or "")
    if model is None:
        if on_log:
            on_log(f"مدل ترکیبی «{config.merge_model}» نصب نیست — رد شد")
        return words

    second = WhisperOptions(
        **{
            **options.__dict__,
            "model": model,
            "dtw_preset": dtw_preset_for(config.merge_model or ""),
        }
    )
    try:
        other = run(
            second,
            wav,
            tmp / "second",
            on_log=on_log,
            # Second half of the bar: without this the UI sits at 100% for a
            # minute and looks frozen.
            on_progress=(lambda pct: on_progress(50 + pct // 2)) if on_progress else None,
        )
    except Exception as error:  # a failed second opinion must not lose the first
        if on_log:
            on_log(f"مدل دوم اجرا نشد: {error}")
        return words

    other, _ = drop_repetitions(other)

    # The second model also acts as a witness: a phrase it heard once but the
    # first heard three times was invented by the first.
    words, arbitrated = arbitrate_repeats(words, other)
    if arbitrated and on_log:
        on_log(f"{arbitrated} کلمه تکراری با داوری مدل دوم حذف شد")

    merged, report = merge_streams(words, other)
    # Splicing can put a phrase next to its own copy from the other model.
    merged, spliced_repeats = drop_repetitions(merged)
    if spliced_repeats and on_log:
        on_log(f"{spliced_repeats} کلمه تکراری بعد از ترکیب حذف شد")
    if on_log:
        on_log(
            f"ترکیب: {report.holes} حفره، {report.filled} پر شد، "
            f"{report.words_added} کلمه ({report.seconds_recovered:.1f} ثانیه) اضافه شد"
        )
    return merged


def _build_prompt(base: str) -> str:
    """Append the user's own vocabulary so the model expects those words."""
    terms = corrections_module.prompt_terms()
    return f"{base} {terms}".strip() if terms else base


def transcribe(
    video: str | Path,
    config: AppConfig,
    *,
    prompt: str = "",
    glossary: set[str] | None = None,
    offset_ms: int | None = None,
    duration_ms: int | None = None,
    on_progress: Callable[[int], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> Project:
    video_path = Path(video)
    if not video_path.exists():
        raise PipelineError(f"فایل پیدا نشد: {video_path}")

    # Fail in a second, not twenty minutes in.
    try:
        info = audio_module.probe(video_path)
        if not info.has_audio:
            raise PipelineError(f"این فایل ترک صوتی ندارد: {video_path.name}")
    except audio_module.AudioError as error:
        if on_log:
            on_log(f"بررسی صدا انجام نشد: {error}")

    tools = resolve_tools(config.model_name)
    options = WhisperOptions(
        binary=tools.binary,
        model=tools.model,
        # whisper.cpp's VAD is deliberately NOT used: with --vad the words
        # after a pause come back on a compressed timeline (measured: 3.5 s
        # early after a 3 s silence). Silence is filtered from the energy
        # envelope instead, further down, where timestamps stay correct.
        vad_model=None,
        language=config.language,
        prompt=_build_prompt(prompt or config.prompt),
        offset_ms=offset_ms,
        duration_ms=duration_ms,
        dtw_preset=dtw_preset_for(config.model_name),
    )

    with tempfile.TemporaryDirectory(prefix="farsisub-") as tmp:
        # whisper-cli reads flac/mp3/ogg/wav only, never a video container.
        wav = audio_module.extract_wav(video_path, Path(tmp) / "audio.wav")
        out_prefix = Path(tmp) / video_path.stem
        two_passes = bool(config.merge_model and config.merge_model != config.model_name)
        first_progress = on_progress
        if two_passes and on_progress:
            first_progress = lambda pct: on_progress(pct // 2)  # noqa: E731

        words = run(
            options,
            wav,
            out_prefix,
            on_progress=first_progress,
            on_log=on_log,
        )

        # Whisper loops phrases when its decoder gets stuck; the repeat is not
        # in the audio and must go before anything else looks at the stream.
        words, repeated = drop_repetitions(words)
        if repeated and on_log:
            on_log(f"{repeated} کلمه تکراری حذف شد")

        # A second model, used only where the first one stayed silent.
        if config.merge_model and config.merge_model != config.model_name:
            if on_progress:
                on_progress(50)
            words = _fill_with_second_model(
                words,
                config,
                options,
                wav,
                Path(tmp),
                on_log=on_log,
                on_progress=on_progress,
            )

        try:
            envelope = audio_module.energy_envelope(wav)
        except Exception as error:  # audio is a bonus signal, never a blocker
            envelope = None
            if on_log:
                on_log(f"تحلیل بلندی صدا انجام نشد: {error}")

    table = corrections_module.build_table(config.text.auto_corrections)
    cleaned: list[Word] = []
    for word in words:
        word.text = corrections_module.correct_word(
            normalize_word(word.text, config.text), table
        )
        if word.text:
            cleaned.append(word)

    # Loudness and keyword flags are computed once, here, so that switching
    # profiles or moving the sensitivity slider later stays instant.
    energies = None
    if envelope is not None:
        energies = audio_module.word_energies(cleaned, envelope)
        for word, energy in zip(cleaned, energies):
            word.energy = energy
        before = len(cleaned)
        cleaned = audio_module.drop_silent_words(cleaned, energies)
        if len(cleaned) != before:
            if on_log:
                on_log(f"{before - len(cleaned)} کلمه روی سکوت حذف شد")
            energies = [w.energy for w in cleaned]

    mark_keywords(
        cleaned,
        config.keywords,
        glossary=(glossary or set()) | corrections_module.load_keywords(),
        energies=energies,
    )

    return Project(
        video_path=str(video_path),
        words=cleaned,
        model_name=config.model_name,
        profile_name=config.profile.name,
        duration=cleaned[-1].end if cleaned else 0.0,
    )


def output_path(video: Path, config: AppConfig, suffix: str = ".srt") -> Path:
    folder = Path(config.output_dir) if config.output_dir else video.parent
    folder.mkdir(parents=True, exist_ok=True)
    return folder / (video.stem + suffix)


def render(project: Project, config: AppConfig, *, suffix: str = ".srt") -> Path:
    """Re-render subtitles from an existing WordStream. No model involved."""
    cues = build_cues(project.words, config.profile, config.text)
    target = output_path(Path(project.video_path), config, suffix)
    return write_subtitle(cues, target, bom=config.text.bom)


def process(
    video: str | Path,
    config: AppConfig,
    *,
    prompt: str = "",
    glossary: set[str] | None = None,
    save_project: bool = True,
    suffix: str = ".srt",
    on_progress: Callable[[int], None] | None = None,
    on_log: Callable[[str], None] | None = None,
) -> tuple[Project, Path]:
    project = transcribe(
        video,
        config,
        prompt=prompt,
        glossary=glossary,
        on_progress=on_progress,
        on_log=on_log,
    )
    subtitle = render(project, config, suffix=suffix)
    if save_project:
        project.save(locate.project_path(project.video_path))
    return project, subtitle
