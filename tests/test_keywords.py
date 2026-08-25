"""The keyword detector must never put a preposition alone on screen."""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.config import KeywordRules  # noqa: E402
from farsisub.models import Word  # noqa: E402
from farsisub.render.keywords import mark_keywords, score_words  # noqa: E402

RULES = KeywordRules()


def timeline(spec: list[tuple[str, float, float]]) -> list[Word]:
    return [Word(text=t, start=s, end=e, probability=0.9) for t, s, e in spec]


def test_stretched_word_after_a_pause_scores_highest():
    words = timeline(
        [
            ("این", 0.00, 0.25),
            ("محصول", 0.30, 0.62),
            ("کاملا", 0.66, 0.98),
            # stretched and preceded by a clear pause
            ("رایگان", 1.60, 2.60),
            ("است", 2.65, 2.90),
        ]
    )
    scores = score_words(words)
    assert scores.index(max(scores)) == 3


def test_function_words_are_never_keywords():
    words = timeline(
        [
            ("را", 0.0, 1.2),  # absurdly stretched on purpose
            ("محصول", 1.3, 1.6),
            ("که", 1.7, 2.9),
            ("خریدیم", 3.0, 3.3),
        ]
    )
    mark_keywords(words, RULES)
    assert words[0].keyword is False
    assert words[2].keyword is False


def test_short_words_are_skipped():
    words = timeline([("با", 0.0, 1.0), ("کیفیت", 1.1, 1.4)])
    mark_keywords(words, RULES)
    assert words[0].keyword is False


def test_glossary_always_wins():
    words = timeline([("سلام", 0.0, 0.3), ("ارفان", 0.35, 0.5)])
    mark_keywords(words, RULES, glossary={"ارفان"})
    assert words[1].keyword is True


def test_manual_decision_is_not_overwritten():
    words = timeline([("یک", 0.0, 0.2), ("کلمه", 0.3, 1.4), ("دیگر", 1.5, 1.7)])
    words[1].keyword = False
    words[1].edited = True
    mark_keywords(words, RULES)
    assert words[1].keyword is False


def test_sensitivity_changes_how_many_words_qualify():
    words = timeline(
        [
            ("امروز", 0.0, 0.35),
            ("درباره", 0.4, 0.75),
            ("موضوع", 0.8, 1.5),
            ("بسیار", 1.9, 2.6),
            ("مهم", 2.7, 3.4),
        ]
    )
    strict = [Word(**w.__dict__) for w in words]
    loose = [Word(**w.__dict__) for w in words]
    mark_keywords(strict, KeywordRules(sensitivity=0.0))
    mark_keywords(loose, KeywordRules(sensitivity=1.0))
    assert sum(bool(w.keyword) for w in loose) >= sum(bool(w.keyword) for w in strict)


def test_disabled_detector_marks_nothing():
    words = timeline([("محصول", 0.0, 1.5), ("جدید", 1.6, 1.9)])
    mark_keywords(words, KeywordRules(enabled=False))
    assert not any(w.keyword for w in words)


def test_energy_is_used_when_audio_is_available():
    words = timeline([("یک", 0.0, 0.3), ("دو", 0.4, 0.7), ("سه", 0.8, 1.1)])
    quiet = score_words(words, energies=[0.1, 0.1, 0.9])
    assert quiet.index(max(quiet)) == 2
