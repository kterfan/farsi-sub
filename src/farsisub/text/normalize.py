"""Persian text hygiene for subtitle cues.

Raw Whisper output for Persian carries Arabic letter variants, missing ZWNJ,
mixed digit systems and stray spacing. This module fixes all of that.

hazm is used when it is installed (its Normalizer handles ZWNJ placement far
better than regex), but every rule has a pure-Python fallback so the core
pipeline keeps working without it.
"""

from __future__ import annotations

import re
from functools import lru_cache

from ..config import TextRules

ZWNJ = "\u200c"

# Arabic letters that must become their Persian counterparts.
_ARABIC_TO_PERSIAN = str.maketrans(
    {
        "\u064a": "\u06cc",  # ARABIC YEH -> FARSI YEH
        "\u0649": "\u06cc",  # ALEF MAKSURA -> FARSI YEH
        "\u0643": "\u06a9",  # ARABIC KAF -> KEHEH
        "\u06c0": "\u0647",  # HEH WITH YEH ABOVE -> HEH
        "\u0629": "\u0647",  # TEH MARBUTA -> HEH
    }
)

PERSIAN_DIGITS = "\u06f0\u06f1\u06f2\u06f3\u06f4\u06f5\u06f6\u06f7\u06f8\u06f9"
ARABIC_DIGITS = "\u0660\u0661\u0662\u0663\u0664\u0665\u0666\u0667\u0668\u0669"
LATIN_DIGITS = "0123456789"

_TO_PERSIAN_DIGITS = str.maketrans(LATIN_DIGITS + ARABIC_DIGITS, PERSIAN_DIGITS * 2)
_TO_LATIN_DIGITS = str.maketrans(PERSIAN_DIGITS + ARABIC_DIGITS, LATIN_DIGITS * 2)

# Latin punctuation typed (or transcribed) inside Persian text.
_LATIN_PUNCT = str.maketrans({",": "،", ";": "؛", "?": "؟"})

# Tanvin (U+064B) is deliberately excluded: "\u0644\u0632\u0648\u0645\u0627\u064b" and "\u0648\u0627\u0642\u0639\u0627\u064b" are spelled
# with it in ordinary Persian, unlike the decorative harakat.
_DIACRITICS = re.compile("[\u064c-\u0652\u0653-\u0655\u0670]")
_KASHIDA = re.compile("\u0640+")
_REPEATED = re.compile(r"(.)\1{2,}")

# Space before punctuation is always wrong; space after is always required.
_SPACE_BEFORE_PUNCT = re.compile(r"\s+([،؛؟!\.:])")
_MISSING_SPACE_AFTER_PUNCT = re.compile(r"([،؛؟!:])(?=[^\s\d])")
_MULTI_SPACE = re.compile(r"[ \t]{2,}")

# ZWNJ rules (fallback path only).
_MI_PREFIX = re.compile(r"(?<![\w\u200c])(ن?می)\s+(?=[\u0600-\u06ff])")
_SUFFIXES = re.compile(r"(?<=[\u0600-\u06ff])\s+(ها|های|هایی|هایم|هایت|هایش|تر|تری|ترین)(?![\u0600-\u06ff])")

# Spoken fillers that add nothing to a subtitle line.
_FILLERS = re.compile(
    r"(?<![\u0600-\u06ff])(اِ+|اِم+|ام+م|خب|خُب|یعنی که|چیزه|آآ+|اِه+)(?![\u0600-\u06ff])"
)

_TRAILING_PERIOD = re.compile(r"\s*[\.。]+\s*$")

# Whisper often glues a suffix straight onto a word ending in "ه":
# "خونهدار", "وابستهترین", "خانهها". hazm cannot split these because there is
# no space to work with, so the join is repaired by shape.
_GLUED_SUFFIX = re.compile(r"(?<=[؀-ۿ]ه)(ترین|تر|دار|ها|های|هایی)(?![؀-ۿ])")

# Real words that merely look glued and must be left alone.
_GLUE_EXCEPTIONS = {"بهتر", "بهترین", "مهتر", "کهتر", "بهدار"}


@lru_cache(maxsize=1)
def _hazm_normalizer():
    """Return a hazm Normalizer, or None when hazm is not installed."""
    try:
        from hazm import Normalizer  # type: ignore
    except Exception:
        return None
    try:
        return Normalizer(
            correct_spacing=True,
            # hazm strips tanvin along with the harakat, turning "لزوماً" into
            # "لزوما". Diacritics are handled by _DIACRITICS instead, which
            # keeps the tanvin.
            remove_diacritics=False,
            remove_specials_chars=True,
            decrease_repeated_chars=True,
            persian_style=True,
            persian_numbers=False,  # digits are handled here, driven by TextRules
            unicodes_replacement=True,
        )
    except TypeError:
        # Older/newer hazm releases moved these keyword names around.
        return Normalizer()


def to_persian_digits(text: str) -> str:
    return text.translate(_TO_PERSIAN_DIGITS)


def to_latin_digits(text: str) -> str:
    return text.translate(_TO_LATIN_DIGITS)


def repair_glued_suffix(word: str) -> str:
    """Put the ZWNJ back into "خونهدار" -> "خونه‌دار"."""
    core = word.rstrip("،؛:.!؟…")
    if len(core) < 5 or core in _GLUE_EXCEPTIONS:
        return word
    fixed = _GLUED_SUFFIX.sub(ZWNJ + chr(92) + "1", core, count=1)
    return fixed + word[len(core) :] if fixed != core else word


def normalize_word(text: str, rules: TextRules) -> str:
    """Character-level cleanup applied to a single word, before segmentation."""
    out = text.strip()
    if rules.arabic_to_persian:
        out = out.translate(_ARABIC_TO_PERSIAN)
    if rules.remove_diacritics:
        out = _DIACRITICS.sub("", out)
    if rules.remove_kashida:
        out = _KASHIDA.sub("", out)
    out = _REPEATED.sub(r"\1", out)
    if rules.zwnj:
        out = repair_glued_suffix(out)
    return out


def normalize_text(text: str, rules: TextRules, *, use_hazm: bool = True) -> str:
    """Full cleanup for an assembled line of subtitle text."""
    out = text

    if rules.arabic_to_persian:
        out = out.translate(_ARABIC_TO_PERSIAN).translate(_LATIN_PUNCT)
    if rules.remove_diacritics:
        out = _DIACRITICS.sub("", out)
    if rules.remove_kashida:
        out = _KASHIDA.sub("", out)
    if rules.remove_fillers:
        out = _FILLERS.sub(" ", out)

    normalizer = _hazm_normalizer() if (use_hazm and rules.zwnj) else None
    if normalizer is not None:
        try:
            out = normalizer.normalize(out)
        except Exception:
            normalizer = None
    if normalizer is None and rules.zwnj:
        out = _MI_PREFIX.sub(r"\1" + ZWNJ, out)
        out = _SUFFIXES.sub(ZWNJ + r"\1", out)

    out = _SPACE_BEFORE_PUNCT.sub(r"\1", out)
    out = _MISSING_SPACE_AFTER_PUNCT.sub(r"\1 ", out)
    out = _MULTI_SPACE.sub(" ", out).strip()

    out = to_persian_digits(out) if rules.persian_digits else to_latin_digits(out)
    return out


def apply_punctuation_rules(text: str, rules: TextRules, *, continues: bool = False) -> str:
    """Apply the user's punctuation switches to a finished cue.

    `continues` means the sentence runs on into the next cue, which is what the
    trailing ellipsis is for.
    """
    out = text
    if not rules.keep_comma:
        # Latin comma included: it survives when this runs on raw model text.
        for mark in ("،", "؛", ",", ";"):
            out = out.replace(mark, " ")
    if not rules.keep_question_mark:
        out = out.replace("؟", " ").replace("?", " ")
    if not rules.keep_exclamation_mark:
        out = out.replace("!", " ")

    out = _MULTI_SPACE.sub(" ", out).strip()

    if rules.strip_final_period:
        out = _TRAILING_PERIOD.sub("", out)

    if continues and rules.ellipsis_on_continuation and out and out[-1] not in "…؟!":
        out = out.rstrip("،؛: ") + "…"

    return out.strip()
