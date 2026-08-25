"""Where a Persian sentence may be cut, and how much it hurts.

Greedy filling produced cuts like:

    تو ممکنه خرید کنی، بوهران رو جمع
    کنی، حساب کتاب بلد باشی،

"جمع کنی" is one verb; splitting it reads as two broken words. Same for a
line that ends on a preposition ("معمولا به") or a cue that opens on "رو".

So every gap between two words gets a cost, and both the cue splitter and the
line wrapper cut at the cheapest gap available instead of the nearest one.
"""

from __future__ import annotations

from ..models import Word

# --- word classes ----------------------------------------------------------

TERMINAL_PUNCT = "؟?!.…"
CLAUSE_PUNCT = "،؛:"

# Light verbs: the second half of "جمع کردن", "گوش دادن", "بلد بودن" and the
# hundreds of Persian compound verbs built the same way. Splitting before one
# of these tears a single verb in half.
LIGHT_VERBS = {
    "کن", "کنم", "کنی", "کنه", "کند", "کنیم", "کنید", "کنند", "کرد", "کردم",
    "کردی", "کردیم", "کردید", "کردند", "کرده", "میکنم", "میکنی", "میکنه",
    "میکند", "میکنیم", "میکنید", "میکنند",
    "شو", "شم", "شی", "شه", "شد", "شدم", "شدی", "شدیم", "شدید", "شدند", "شده",
    "باش", "باشم", "باشی", "باشه", "باشد", "باشیم", "باشید", "باشند",
    "بود", "بودم", "بودی", "بودیم", "بودید", "بودند", "هست", "هستم", "هستی",
    "بده", "بدم", "بدی", "بدیم", "بدید", "بدن", "داد", "دادم", "دادی", "داده",
    "بزن", "بزنم", "بزنی", "زد", "زده", "بخور", "خورد", "خورده",
    "بگیر", "بگیرم", "بگیری", "گرفت", "گرفته", "میگیرم", "میگیری", "میگیره",
    "بیار", "بیارم", "بیاری", "آورد", "آورده", "میشه", "میشم", "میشی",
    "داره", "دارم", "داری", "داریم", "دارید", "دارند", "داشت", "داشته",
}

# Prepositions and the ezafe-carrying words that must not end a line.
PREPOSITIONS = {
    "به", "با", "از", "در", "بر", "برای", "روی", "زیر", "بالای", "کنار",
    "بدون", "درباره", "توسط", "مثل", "مانند", "طبق", "پس از", "قبل از", "تا",
}

# Enclitics: they attach to the word before them and can never open a cue.
HARD_ENCLITICS = {"رو", "را", "هم", "و", "یا", "ی"}

# Prepositions opening a cue is merely awkward, not wrong, so it costs rather
# than forbids. Clause starters are the opposite: a cue that begins with "ولی"
# or "یعنی" reads better than one that ends with it.

SUFFIX_WORDS = {
    "تر", "تری", "ترین", "ها", "های", "هایی", "هایم", "هایت", "هایش",
    "هایمان", "هایتان", "هایشان", "ام", "ات", "اش", "مان", "تان", "شان",
}

# Words that make a good opening for the next cue: a new clause starts here.
CLAUSE_STARTERS = {"ولی", "اما", "چون", "اگر", "پس", "که", "تا", "یعنی", "نه", "بلکه"}

# --- costs -----------------------------------------------------------------

COST_SENTENCE_END = 0.0
COST_CLAUSE_END = 1.0
COST_BEFORE_CLAUSE_STARTER = 2.0
COST_PLAIN = 5.0
COST_BEFORE_PREPOSITION = 8.0
COST_AFTER_PREPOSITION = 40.0
COST_BEFORE_LIGHT_VERB = 60.0
COST_BEFORE_CLITIC = 80.0
COST_BEFORE_SUFFIX = 200.0  # never: it splits one word into two


def bare(text: str) -> str:
    return text.strip("،؛:.!؟…‌ ")


def ends_sentence(text: str) -> bool:
    return bool(text) and text.rstrip()[-1:] in TERMINAL_PUNCT


def ends_clause(text: str) -> bool:
    return bool(text) and text.rstrip()[-1:] in CLAUSE_PUNCT


def is_suffix(text: str) -> bool:
    return bare(text) in SUFFIX_WORDS


def is_clitic(text: str) -> bool:
    """True only for words that must never start a cue or a line."""
    return bare(text) in HARD_ENCLITICS


def is_light_verb(text: str) -> bool:
    return bare(text) in LIGHT_VERBS


def is_preposition(text: str) -> bool:
    return bare(text) in PREPOSITIONS


def break_cost(before: str, after: str) -> float:
    """Cost of cutting between two neighbouring words.

    Lower is better. The hard blocks (suffix, clitic, light verb) are ranked
    far above the soft preferences so they always win.
    """
    if is_suffix(after):
        return COST_BEFORE_SUFFIX
    if is_clitic(after):
        return COST_BEFORE_CLITIC
    if is_light_verb(after):
        return COST_BEFORE_LIGHT_VERB
    if is_preposition(before) and not ends_clause(before):
        return COST_AFTER_PREPOSITION

    # A clause boundary is the best cut there is, in either direction.
    if bare(after) in CLAUSE_STARTERS:
        return COST_BEFORE_CLAUSE_STARTER
    if ends_sentence(before):
        return COST_SENTENCE_END
    if ends_clause(before):
        return COST_CLAUSE_END
    if is_preposition(after):
        return COST_BEFORE_PREPOSITION
    return COST_PLAIN


def word_break_cost(words: list[Word], index: int) -> float:
    """Cost of cutting so that `index` starts the next cue or line."""
    if index <= 0 or index >= len(words):
        return COST_SENTENCE_END
    return break_cost(words[index - 1].text, words[index].text)


def token_break_cost(tokens: list[str], index: int) -> float:
    if index <= 0 or index >= len(tokens):
        return COST_SENTENCE_END
    return break_cost(tokens[index - 1], tokens[index])
