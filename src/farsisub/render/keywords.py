"""Decide which words the speaker emphasised.

Prosody research says an emphasised word shows up three ways: it is stretched,
it is louder, and a pause tends to sit next to it. All three are computable
from data we already have, so the detector costs nothing extra.

A grammar filter sits on top: no matter how loud it was, "را" or "که" must
never end up alone on screen.
"""

from __future__ import annotations

import math
import re
from dataclasses import dataclass
from functools import lru_cache
from typing import Sequence

from ..config import KeywordRules
from ..models import Word

# Persian function words. Used when the hazm POS model is unavailable, which is
# the normal case on a first run.
FUNCTION_WORDS = {
    "و", "یا", "که", "را", "از", "به", "در", "با", "بر", "تا", "بی", "برای", "روی",
    "این", "آن", "همان", "چه", "هر", "هیچ", "خیلی", "هم", "نیز", "اما", "ولی", "اگر",
    "چون", "پس", "یعنی", "مثل", "مانند", "طبق", "بدون", "درباره", "توسط", "هنگام",
    "است", "هست", "بود", "شد", "شده", "باشد", "کرد", "کند", "می", "نمی", "خواهد",
    "من", "تو", "او", "ما", "شما", "آنها", "خود", "ایشان", "آنان",
    "یک", "دو", "سه", "دیگر", "بعد", "قبل", "الان", "حالا",
}

_PUNCT = re.compile(r"[^\w‌]+", re.UNICODE)
_NUMBER = re.compile(r"^[\d۰-۹٠-٩]+$")

# Fractions of the final score. Energy drops out when no audio is available and
# the remaining two are renormalised.
WEIGHT_DURATION = 0.45
WEIGHT_PAUSE = 0.30
WEIGHT_ENERGY = 0.25


def bare(text: str) -> str:
    return _PUNCT.sub("", text)


@lru_cache(maxsize=1)
def _pos_tagger():
    """hazm POS tagger, or None when its model file is not installed."""
    try:
        from hazm import POSTagger  # type: ignore

        from ..engine import locate

        model = locate.bin_dir() / "pos_tagger.model"
        if not model.exists():
            return None
        return POSTagger(model=str(model))
    except Exception:
        return None


def _is_function_word(text: str, tag: str | None) -> bool:
    if tag is not None:
        # hazm tags: ADP preposition, PRON pronoun, CCONJ/SCONJ conjunction,
        # AUX auxiliary verb, DET determiner.
        return tag.split(",")[0] in {"ADP", "PRON", "CCONJ", "SCONJ", "AUX", "DET", "PUNCT"}
    return text in FUNCTION_WORDS


def _zscores(values: Sequence[float]) -> list[float]:
    if not values:
        return []
    mean = sum(values) / len(values)
    variance = sum((v - mean) ** 2 for v in values) / len(values)
    sigma = math.sqrt(variance)
    if sigma < 1e-6:
        return [0.0] * len(values)
    return [(v - mean) / sigma for v in values]


@dataclass
class Features:
    stretch: float  # seconds per character
    pause: float  # longest neighbouring silence
    energy: float  # RMS of the word span, 0 when unknown


def extract_features(words: list[Word], energies: Sequence[float] | None = None) -> list[Features]:
    features: list[Features] = []
    for i, word in enumerate(words):
        chars = max(1, len(bare(word.text)))
        before = word.start - words[i - 1].end if i > 0 else 0.0
        after = words[i + 1].start - word.end if i + 1 < len(words) else 0.0
        features.append(
            Features(
                stretch=word.duration / chars,
                pause=max(0.0, before, after),
                energy=float(energies[i]) if energies is not None and i < len(energies) else 0.0,
            )
        )
    return features


def score_words(words: list[Word], energies: Sequence[float] | None = None) -> list[float]:
    """Combined emphasis score per word, in z-score units."""
    if not words:
        return []
    features = extract_features(words, energies)
    stretch_z = _zscores([f.stretch for f in features])
    pause_z = _zscores([f.pause for f in features])

    has_energy = energies is not None and len(energies) >= len(words)
    energy_z = _zscores([f.energy for f in features]) if has_energy else [0.0] * len(words)

    if has_energy:
        w_dur, w_pause, w_energy = WEIGHT_DURATION, WEIGHT_PAUSE, WEIGHT_ENERGY
    else:
        total = WEIGHT_DURATION + WEIGHT_PAUSE
        w_dur, w_pause, w_energy = WEIGHT_DURATION / total, WEIGHT_PAUSE / total, 0.0

    return [
        w_dur * stretch_z[i] + w_pause * pause_z[i] + w_energy * energy_z[i]
        for i in range(len(words))
    ]


def mark_keywords(
    words: list[Word],
    rules: KeywordRules,
    *,
    glossary: set[str] | None = None,
    energies: Sequence[float] | None = None,
) -> list[float]:
    """Set `word.keyword` in place and return the scores behind each decision.

    A manual choice by the user (keyword already True or False) is never
    overwritten: the editor always wins over the detector.
    """
    glossary = {bare(g) for g in (glossary or set())}
    scores = score_words(words, energies)
    tagger = _pos_tagger() if rules.use_pos_filter else None
    tags: list[str | None] = [None] * len(words)

    if tagger is not None:
        try:
            tokens = [bare(w.text) or w.text for w in words]
            tags = [tag for _, tag in tagger.tag(tokens)]
        except Exception:
            tags = [None] * len(words)

    # Which words are even allowed to be keywords.
    eligible: list[int] = []
    for i, word in enumerate(words):
        plain = bare(word.text)
        if word.keyword is not None and word.edited:
            continue  # the user decided this one; the detector stays out
        if plain in glossary:
            continue  # handled below, unconditionally
        ok = len(plain) >= rules.min_word_chars and not _is_function_word(plain, tags[i])
        if _NUMBER.match(plain):
            ok = True  # numbers carry the message in short-form video
        if ok:
            eligible.append(i)

    # Keep the top slice by score. A fixed z-score cut-off looked principled but
    # picked 2 words out of 176 on a real clip; a share adapts to the speaker.
    keep: set[int] = set()
    if rules.enabled and eligible:
        ranked = sorted(eligible, key=lambda i: scores[i], reverse=True)
        count = max(1, round(len(words) * rules.keep_fraction))
        keep = set(ranked[:count])

    for i, word in enumerate(words):
        plain = bare(word.text)
        if word.keyword is not None and word.edited:
            continue
        if plain in glossary:
            word.keyword = True
            continue
        word.keyword = i in keep

    return scores
