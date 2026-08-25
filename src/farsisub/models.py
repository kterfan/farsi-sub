"""Core data structures shared by the whole pipeline.

The central idea of FarsiSub: transcribe once into a WordStream, then render
that stream into any subtitle style. Everything downstream (styles, Persian
text rules, manual edits) operates on these structures, never on raw ASR output.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCHEMA_VERSION = 1


@dataclass
class Word:
    """A single word with its timing and how sure the model was about it."""

    text: str
    start: float  # seconds
    end: float  # seconds
    probability: float = 1.0
    # None = decided automatically by the keyword engine,
    # True/False = the user overrode that decision by hand.
    keyword: bool | None = None
    edited: bool = False
    # Loudness of this word, kept so the keyword sensitivity slider can be
    # re-applied later without decoding the audio again.
    energy: float = 0.0

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    def to_dict(self) -> dict[str, Any]:
        return {
            "text": self.text,
            "start": round(self.start, 3),
            "end": round(self.end, 3),
            "p": round(self.probability, 4),
            "keyword": self.keyword,
            "edited": self.edited,
            "energy": round(self.energy, 5),
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Word":
        return cls(
            text=d["text"],
            start=float(d["start"]),
            end=float(d["end"]),
            probability=float(d.get("p", 1.0)),
            keyword=d.get("keyword"),
            edited=bool(d.get("edited", False)),
            energy=float(d.get("energy", 0.0)),
        )


@dataclass
class Cue:
    """One subtitle block: what shows on screen between start and end."""

    index: int
    start: float
    end: float
    lines: list[str] = field(default_factory=list)
    # Indices into the source WordStream, so the editor can walk back from a
    # cue to the words (and their confidences) that produced it.
    word_range: tuple[int, int] | None = None

    @property
    def text(self) -> str:
        return "\n".join(self.lines)

    @property
    def duration(self) -> float:
        return max(0.0, self.end - self.start)

    @property
    def char_count(self) -> int:
        return sum(len(line) for line in self.lines)

    @property
    def cps(self) -> float:
        """Characters per second: the reading-speed check."""
        if self.duration <= 0:
            return float("inf")
        return self.char_count / self.duration


@dataclass
class Project:
    """Everything needed to re-render subtitles without touching the video again."""

    video_path: str
    words: list[Word] = field(default_factory=list)
    model_name: str = ""
    profile_name: str = "smart"
    language: str = "fa"
    duration: float = 0.0
    schema: int = SCHEMA_VERSION

    def to_dict(self) -> dict[str, Any]:
        return {
            "schema": self.schema,
            "video_path": self.video_path,
            "model_name": self.model_name,
            "profile_name": self.profile_name,
            "language": self.language,
            "duration": round(self.duration, 3),
            "words": [w.to_dict() for w in self.words],
        }

    @classmethod
    def from_dict(cls, d: dict[str, Any]) -> "Project":
        return cls(
            video_path=d["video_path"],
            words=[Word.from_dict(w) for w in d.get("words", [])],
            model_name=d.get("model_name", ""),
            profile_name=d.get("profile_name", "smart"),
            language=d.get("language", "fa"),
            duration=float(d.get("duration", 0.0)),
            schema=int(d.get("schema", SCHEMA_VERSION)),
        )

    def save(self, path: str | Path) -> None:
        Path(path).write_text(
            json.dumps(self.to_dict(), ensure_ascii=False, indent=1), encoding="utf-8"
        )

    @classmethod
    def load(cls, path: str | Path) -> "Project":
        return cls.from_dict(json.loads(Path(path).read_text(encoding="utf-8")))
