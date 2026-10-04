"""Fix the spellings Whisper reliably gets wrong in Persian.

Two layers:

  * a built-in list of forms that are simply not Persian words, so replacing
    them cannot change meaning ("بوهران" -> "بحران", "تعیید" -> "تأیید");
  * the user's own glossary, which always wins, and which also feeds the model
    as a prompt so the next run hears the word correctly in the first place.

Anything ambiguous stays out. A correction table that guesses is worse than no
correction table.
"""

from __future__ import annotations

import difflib
import json
import logging
import re
import time
from pathlib import Path
from typing import Any

from ..engine import locate
from ..fileio import atomic_write_text

log = logging.getLogger(__name__)

# Forms Whisper produces that are not words in Persian. Safe to replace.
BUILTIN_CORRECTIONS: dict[str, str] = {
    "بوهران": "بحران",
    "بوحران": "بحران",
    "تعیید": "تأیید",
    "تایید": "تأیید",
    "لزومن": "لزوماً",
    "خوندار": "خونه‌دار",
    "وجدا": "وجدان",
    "مسئولیت‌پزیری": "مسئولیت‌پذیری",
    "مسئولیت پزیری": "مسئولیت‌پذیری",
    # Tanvin dropped by the model: these are adverbs, always written with -اً.
    "صرفا": "صرفاً",
    "معمولا": "معمولاً",
    "واقعا": "واقعاً",
    "حتما": "حتماً",
    "اصلا": "اصلاً",
    "مثلا": "مثلاً",
    "تقریبا": "تقریباً",
    "دقیقا": "دقیقاً",
    "قطعا": "قطعاً",
    "کاملا": "کاملاً",
    "نسبتا": "نسبتاً",
    "عمدتا": "عمدتاً",
    "شخصا": "شخصاً",
    "قبلا": "قبلاً",
    "بعدا": "بعداً",
    "فعلا": "فعلاً",
    "لطفا": "لطفاً",
    "دائما": "دائماً",
    "ضمنا": "ضمناً",
    "اتفاقا": "اتفاقاً",
}

GLOSSARY_FILE = "glossary.json"
_TRAILING = "،؛:.!؟…"


def glossary_path() -> Path:
    return locate.data_dir() / GLOSSARY_FILE


def _set_aside(path: Path, reason: Exception) -> None:
    """Move a broken glossary out of the way instead of writing over it.

    Treating it as empty and saving the next correction on top used to wipe
    every correction the user had ever taught. Kept beside the original, the
    file can still be repaired by hand.
    """
    backup = path.with_name(f"{path.stem}.broken-{time.strftime('%Y%m%d-%H%M%S')}{path.suffix}")
    try:
        path.replace(backup)
        log.warning("دیکشنری خراب بود (%s)؛ نسخه‌اش نگه داشته شد: %s", reason, backup)
    except OSError as error:
        log.warning("دیکشنری خراب است (%s) و کنار گذاشتنش ممکن نشد: %s", reason, error)


def _read_glossary_file(*, strict: bool = False) -> dict[str, Any]:
    """The raw glossary JSON, or {} when there is none.

    `strict` is for callers about to write: a file that exists but cannot be
    read right now (locked by another program) must stop the write rather
    than be replaced with a shorter version.
    """
    path = glossary_path()
    try:
        raw = path.read_text(encoding="utf-8")
    except FileNotFoundError:
        return {}
    except OSError:
        if strict:
            raise
        log.warning("دیکشنری خوانده نشد: %s", path, exc_info=True)
        return {}
    try:
        data = json.loads(raw)
        if not isinstance(data, dict):
            raise ValueError("glossary is not a JSON object")
    except ValueError as error:  # JSONDecodeError is a ValueError
        _set_aside(path, error)
        return {}
    return data


def _corrections_of(data: dict[str, Any]) -> dict[str, str]:
    corrections = data.get("corrections")
    if not isinstance(corrections, dict):
        return {}
    return {str(k): str(v) for k, v in corrections.items()}


def _keywords_of(data: dict[str, Any]) -> set[str]:
    keywords = data.get("keywords")
    if not isinstance(keywords, list):
        return set()
    return {str(w) for w in keywords}


def load_glossary() -> dict[str, str]:
    """User corrections: {heard -> correct}."""
    return _corrections_of(_read_glossary_file())


def load_keywords() -> set[str]:
    """Terms the user marked as keywords for the reels profile."""
    return _keywords_of(_read_glossary_file())


def save_glossary(corrections: dict[str, str], keywords: set[str] | None = None) -> Path:
    payload = {"corrections": corrections, "keywords": sorted(keywords or set())}
    return atomic_write_text(
        glossary_path(), json.dumps(payload, ensure_ascii=False, indent=2)
    )


def add_correction(heard: str, correct: str) -> Path:
    data = _read_glossary_file(strict=True)
    corrections = _corrections_of(data)
    corrections[heard.strip()] = correct.strip()
    return save_glossary(corrections, _keywords_of(data))


def build_table(use_builtin: bool = True) -> dict[str, str]:
    table = dict(BUILTIN_CORRECTIONS) if use_builtin else {}
    table.update(load_glossary())  # the user always wins
    return table


def correct_word(text: str, table: dict[str, str]) -> str:
    """Replace a single word, keeping whatever punctuation trails it."""
    if not text:
        return text
    core = text.rstrip(_TRAILING)
    tail = text[len(core) :]
    replacement = table.get(core)
    return f"{replacement}{tail}" if replacement else text


def correct_text(text: str, table: dict[str, str]) -> str:
    """Apply the table to a whole line.

    Multi word entries ("خونه دار" -> "خونه‌دار") are replaced first, since a
    word by word pass would never see them.
    """
    if not table:
        return text
    out = text
    for heard, correct in table.items():
        if " " in heard and heard in out:
            # Whole words only: a bare substring replace turned "کتابخونه
            # داره" into "کتابخونه‌داره" through the entry "خونه دار".
            pattern = rf"(?<![\w‌]){re.escape(heard)}(?![\w‌])"
            out = re.sub(pattern, lambda _m, fix=correct: fix, out)
    return re.sub(r"\S+", lambda m: correct_word(m.group(0), table), out)


def prompt_terms(limit: int = 40) -> str:
    """Correct spellings to prime the model with, so it hears them right."""
    terms = list(load_glossary().values()) + sorted(load_keywords())
    unique: list[str] = []
    for term in terms:
        if term not in unique:
            unique.append(term)
    return "، ".join(unique[:limit])


def diff_pairs(heard: list[str], corrected: list[str]) -> list[tuple[str, str]]:
    """What the user actually changed, as (heard -> correct) pairs.

    Aligns the two versions instead of demanding the same word count, so
    "خونه دار" -> "خونه‌دار" (two words becoming one) is learnable too.
    """
    pairs: list[tuple[str, str]] = []
    matcher = difflib.SequenceMatcher(None, heard, corrected)
    for tag, i1, i2, j1, j2 in matcher.get_opcodes():
        if tag != "replace":
            continue
        left, right = heard[i1:i2], corrected[j1:j2]
        if len(left) == len(right):
            pairs.extend(
                (a.strip(_TRAILING), b.strip(_TRAILING))
                for a, b in zip(left, right)
                if a.strip(_TRAILING) != b.strip(_TRAILING)
            )
        elif len(right) == 1 and len(left) > 1:
            # several words merged into one: "خونه دار" -> "خونه‌دار"
            pairs.append((" ".join(w.strip(_TRAILING) for w in left), right[0].strip(_TRAILING)))
        elif len(left) == 1 and len(right) > 1:
            # one word split into several: "خودتعینگری" -> "خودتعیین گری"
            pairs.append((left[0].strip(_TRAILING), " ".join(w.strip(_TRAILING) for w in right)))
    # Single letters and empty strings teach nothing useful.
    return [(a, b) for a, b in pairs if len(a) > 1 and b]
