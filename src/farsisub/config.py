"""Style profiles and Persian typing rules.

Every number here is a default, not a law: the settings panel writes the same
fields back as JSON so a user can build their own profile.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Literal

SegmentMode = Literal["sentence", "smart", "reels"]


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
}

DEFAULT_PROFILE = "smart"


@dataclass
class AppConfig:
    profile: StyleProfile = field(default_factory=lambda: BUILTIN_PROFILES[DEFAULT_PROFILE])
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
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "AppConfig":
        cfg = cls()
        if "profile" in d:
            cfg.profile = StyleProfile.from_dict(d["profile"])
        if "text" in d:
            cfg.text = TextRules.from_dict(d["text"])
        if "keywords" in d:
            known = {f for f in KeywordRules.__dataclass_fields__}
            cfg.keywords = KeywordRules(**{k: v for k, v in d["keywords"].items() if k in known})
        cfg.model_name = d.get("model_name", cfg.model_name)
        cfg.language = d.get("language", cfg.language)
        cfg.prompt = d.get("prompt", cfg.prompt)
        cfg.merge_model = d.get("merge_model", cfg.merge_model)
        cfg.output_dir = d.get("output_dir")
        cfg.low_confidence = float(d.get("low_confidence", cfg.low_confidence))
        cfg.very_low_confidence = float(d.get("very_low_confidence", cfg.very_low_confidence))
        return cfg

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=2), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "AppConfig":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
