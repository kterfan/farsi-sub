"""Style profiles and Persian typing rules.

Every number here is a default, not a law: the settings panel writes the same
fields back as JSON so a user can build their own profile.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field, replace
from pathlib import Path
from typing import Any, Literal

SegmentMode = Literal["sentence", "smart", "reels", "word"]


@dataclass
class StyleProfile:
    """How the WordStream gets cut into cues."""

    name: str
    label: str  # shown in the UI, Persian
    mode: SegmentMode = "smart"
    max_lines: int = 2
    max_chars_per_line: int = 42
    min_duration: float = 1.0
    max_duration: float = 6.0
    max_cps: float = 20.0
    min_gap: float = 0.08
    # reels mode only
    phrase_min_words: int = 3
    phrase_max_words: int = 5
    keyword_solo: bool = False

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "StyleProfile":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class TextRules:
    """Persian writing conventions applied to cue text before it is written out."""

    strip_final_period: bool = True  # subtitles do not end sentences with a dot
    keep_question_mark: bool = True
    keep_exclamation_mark: bool = True
    keep_comma: bool = False  # the user wants clean lines, no ، and no ,
    persian_digits: bool = True  # False -> Latin digits
    zwnj: bool = True  # mi-/nemi- prefixes, -ha/-tar suffixes
    arabic_to_persian: bool = True  # always on in practice
    remove_diacritics: bool = True
    remove_kashida: bool = True
    remove_fillers: bool = False
    # Replace spellings Whisper reliably gets wrong ("بوهران" -> "بحران").
    auto_corrections: bool = True
    ellipsis_on_continuation: bool = False
    bom: bool = True  # UTF-8 BOM: old Windows players need it

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "TextRules":
        known = {f for f in cls.__dataclass_fields__}
        return cls(**{k: v for k, v in d.items() if k in known})


@dataclass
class KeywordRules:
    """Thresholds for the emphasis detector used by the reels profile."""

    enabled: bool = True
    sensitivity: float = 0.5  # 0..1, maps to the z-score threshold
    min_word_chars: int = 3
    use_pos_filter: bool = True

    @property
    def keep_fraction(self) -> float:
        """Share of eligible words that become keywords.

        An absolute z-score threshold sounded principled and behaved badly: on
        a real 176-word clip it picked 2 words. A percentile adapts to how
        emphatic the speaker actually is.
        """
        sensitivity = max(0.0, min(1.0, self.sensitivity))
        return 0.02 + 0.10 * sensitivity


BUILTIN_PROFILES: dict[str, StyleProfile] = {
    "sentence": StyleProfile(
        name="sentence",
        label="جمله‌ای",
        mode="sentence",
        max_chars_per_line=42,
        max_duration=7.0,
        max_cps=22.0,
    ),
    "smart": StyleProfile(
        name="smart",
        label="هوشمند",
        mode="smart",
        max_chars_per_line=42,
        min_duration=1.0,
        max_duration=6.0,
        max_cps=20.0,
    ),
    "reels": StyleProfile(
        name="reels",
        label="ریلز فارسی",
        mode="reels",
        # One line, always. A wrapped two-line block on a vertical video reads
        # like a paragraph and defeats the point of the profile.
        max_lines=1,
        max_chars_per_line=28,
        min_duration=0.7,
        max_duration=3.0,
        max_cps=20.0,
        phrase_min_words=3,
        phrase_max_words=5,
        keyword_solo=True,
    ),
    "word": StyleProfile(
        name="word",
        label="کلمه به کلمه",
        mode="word",
        # One word at a time, in step with the voice. Words follow each other
        # without a gap: a gap between every word reads as flicker.
        max_lines=1,
        max_chars_per_line=28,
        min_duration=0.3,
        max_duration=2.0,
        max_cps=40.0,
        min_gap=0.0,
    ),
}

DEFAULT_PROFILE = "smart"


CUSTOM_PROFILE = "custom"
MODES = ("sentence", "smart", "reels", "word")
OUTPUT_FORMATS = ("srt", "vtt", "ass", "txt")
THEMES = ("dark", "light")


def _coerce(cls, d: Any, base: Any = None):
    """Build a dataclass from JSON, keeping defaults for anything unusable.

    Settings are read on every start; a value of the wrong type (a hand edit,
    a field from another version) must cost that one field, never the start.
    """
    out = base if base is not None else cls()
    if not isinstance(d, dict):
        return out
    values = {}
    for name in cls.__dataclass_fields__:
        if name not in d:
            continue
        default = getattr(out, name)
        value = d[name]
        try:
            if isinstance(default, bool):
                if not isinstance(value, bool):
                    continue
            elif isinstance(default, int):
                value = int(value)
            elif isinstance(default, float):
                value = float(value)
            elif isinstance(default, str):
                if not isinstance(value, str):
                    continue
        except (TypeError, ValueError):
            continue
        values[name] = value
    return replace(out, **values)


@dataclass
class AssStyle:
    """How subtitles look once they are drawn: ASS export and burned-in video.

    Sizes are in pixels of a 1080-pixel-tall frame and scale with the video.
    """

    font: str = "Vazirmatn"
    size: int = 64
    color: str = "#FFFFFF"
    keyword_color: str = "#FFD400"
    outline: float = 3.0
    outline_color: str = "#000000"
    margin_bottom: int = 90
    bold: bool = True


DEFAULT_PROFILE = "smart"


@dataclass
class AppConfig:
    # A copy: handing out the shared built-in meant any change to one config's
    # profile silently changed the built-in for everyone.
    profile: StyleProfile = field(default_factory=lambda: replace(BUILTIN_PROFILES[DEFAULT_PROFILE]))
    text: TextRules = field(default_factory=TextRules)
    keywords: KeywordRules = field(default_factory=KeywordRules)
    model_name: str = "large-v3"
    language: str = "fa"
    # Second model consulted only for stretches the first left empty. Costs a
    # second pass, so it is opt-in.
    merge_model: str | None = None
    # Whisper treats this as text it just heard, which biases decoding toward
    # properly punctuated, correctly spaced Persian.
    prompt: str = "این یک گفت‌وگوی فارسی است. جمله‌ها با نقطه‌گذاری درست و نیم‌فاصله نوشته می‌شوند."
    output_dir: str | None = None  # None -> next to the video file
    low_confidence: float = 0.6
    very_low_confidence: float = 0.4
    output_format: str = "srt"
    theme: str = "dark"
    ass_style: AssStyle = field(default_factory=AssStyle)
    # The user's own style from the settings panel, offered next to the
    # built-in ones.
    custom_profile: StyleProfile | None = None

    @property
    def suffix(self) -> str:
        return "." + (self.output_format if self.output_format in OUTPUT_FORMATS else "srt")

    def to_dict(self) -> dict[str, Any]:
        return {
            "profile": self.profile.to_dict(),
            "text": self.text.to_dict(),
            "keywords": asdict(self.keywords),
            "model_name": self.model_name,
            "language": self.language,
            "merge_model": self.merge_model,
            "prompt": self.prompt,
            "output_dir": self.output_dir,
            "low_confidence": self.low_confidence,
            "very_low_confidence": self.very_low_confidence,
            "output_format": self.output_format,
            "theme": self.theme,
            "ass_style": asdict(self.ass_style),
            "custom_profile": self.custom_profile.to_dict() if self.custom_profile else None,
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        cfg = cls()
        if not isinstance(d, dict):
            return cfg
        custom = d.get("custom_profile")
        if isinstance(custom, dict):
            cfg.custom_profile = _profile_from(custom, CUSTOM_PROFILE)
        saved = d.get("profile")
        if isinstance(saved, dict):
            name = saved.get("name")
            if name in BUILTIN_PROFILES:
                # The built-in itself, so an improved default reaches users
                # who merely picked it.
                cfg.profile = replace(BUILTIN_PROFILES[name])
            elif name == CUSTOM_PROFILE and cfg.custom_profile is not None:
                cfg.profile = replace(cfg.custom_profile)
        cfg.text = _coerce(TextRules, d.get("text"))
        cfg.keywords = _coerce(KeywordRules, d.get("keywords"))
        cfg.ass_style = _coerce(AssStyle, d.get("ass_style"))
        for name in ("model_name", "language", "prompt"):
            if isinstance(d.get(name), str) and d[name]:
                setattr(cfg, name, d[name])
        merge = d.get("merge_model")
        cfg.merge_model = merge if isinstance(merge, str) and merge else None
        output_dir = d.get("output_dir")
        cfg.output_dir = output_dir if isinstance(output_dir, str) and output_dir else None
        for name in ("low_confidence", "very_low_confidence"):
            try:
                setattr(cfg, name, min(1.0, max(0.0, float(d.get(name, getattr(cfg, name))))))
            except (TypeError, ValueError):
                pass
        if d.get("output_format") in OUTPUT_FORMATS:
            cfg.output_format = d["output_format"]
        if d.get("theme") in THEMES:
            cfg.theme = d["theme"]
        return cfg

    def save(self, path: str | Path) -> None:
        from .fileio import atomic_write_text

        atomic_write_text(path, json.dumps(self.to_dict(), ensure_ascii=False, indent=2))

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))


def _profile_from(d: dict[str, Any], name: str) -> StyleProfile:
    """A user profile from JSON, every number kept inside a sane range."""
    start = replace(BUILTIN_PROFILES[DEFAULT_PROFILE], name=name, label="سبک من")
    profile = _coerce(StyleProfile, d, base=start)
    profile.name = name
    if profile.mode not in MODES:
        profile.mode = DEFAULT_PROFILE
    profile.label = profile.label or "سبک من"
    profile.max_lines = min(3, max(1, profile.max_lines))
    profile.max_chars_per_line = min(80, max(10, profile.max_chars_per_line))
    profile.min_duration = min(5.0, max(0.1, profile.min_duration))
    profile.max_duration = min(15.0, max(profile.min_duration, profile.max_duration))
    profile.max_cps = min(60.0, max(5.0, profile.max_cps))
    profile.min_gap = min(1.0, max(0.0, profile.min_gap))
    return profile


SETTINGS_FILE = "settings.json"


def settings_path() -> Path:
    from .engine import locate

    return locate.data_dir() / SETTINGS_FILE


def load_settings() -> AppConfig:
    """The user's last settings, or the defaults. Never raises."""
    import logging

    try:
        return AppConfig.load(settings_path())
    except FileNotFoundError:
        return AppConfig()
    except Exception:  # noqa: BLE001 - a bad settings file must not stop the app
        logging.getLogger(__name__).warning("تنظیمات خوانده نشد؛ پیش‌فرض‌ها", exc_info=True)
        return AppConfig()


def save_settings(config: AppConfig) -> None:
    import logging

    try:
        config.save(settings_path())
    except OSError:
        logging.getLogger(__name__).warning("تنظیمات ذخیره نشد", exc_info=True)
