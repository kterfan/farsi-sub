"""Quality guards for the subtitle itself, not just the code paths.

Everything else in this suite checks that functions behave. Nothing checked
whether the subtitle got better or worse, so three times in a row a change was
called an improvement and the user was the one who had to notice it was not.

These run against a saved WordStream from a real clip, so they cost no model
time and still catch a rendering change that ruins the output.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from farsisub.config import BUILTIN_PROFILES, AppConfig  # noqa: E402
from farsisub.models import Project  # noqa: E402
from farsisub.render.segment import build_cues  # noqa: E402

REFERENCE = Path(__file__).parent / "reference" / "sample.fsub"


def reference_project() -> Project | None:
    return Project.load(REFERENCE) if REFERENCE.exists() else None


def cues_for(profile_name: str):
    project = reference_project()
    if project is None:
        return None
    config = AppConfig()
    config.profile = BUILTIN_PROFILES[profile_name]
    return build_cues(project.words, config.profile, config.text)


def test_reference_clip_is_present():
    # Without it every other check here silently passes and guards nothing.
    assert REFERENCE.exists(), "tests/reference/sample.fsub is missing"


def test_every_word_reaches_the_subtitle():
    project = reference_project()
    cues = cues_for("smart")
    if project is None or cues is None:
        return
    spoken = sum(len(w.text) for w in project.words)
    written = sum(len(cue.text.replace("\n", "")) for cue in cues)
    # Normalisation trims a little; losing a tenth of the text means a bug.
    assert written >= spoken * 0.9, f"{written} chars written for {spoken} spoken"


def test_subtitle_covers_the_speech_timeline():
    project = reference_project()
    cues = cues_for("smart")
    if project is None or cues is None:
        return
    talking = project.words[-1].end - project.words[0].start
    shown = sum(cue.duration for cue in cues)
    assert shown >= talking * 0.6, f"only {shown:.1f}s shown of {talking:.1f}s spoken"


def test_no_cue_is_unreadably_fast_or_flashed():
    for name in ("sentence", "smart", "reels"):
        cues = cues_for(name)
        if cues is None:
            return
        profile = BUILTIN_PROFILES[name]
        for cue in cues:
            assert cue.duration <= profile.max_duration + 0.01, f"{name}: {cue.text}"
            assert cue.duration >= 0.25, f"{name}: flashed cue {cue.text}"
            for line in cue.lines:
                assert len(line) <= profile.max_chars_per_line, f"{name}: {line}"
            assert len(cue.lines) <= profile.max_lines


def test_cues_never_overlap():
    for name in ("sentence", "smart", "reels"):
        cues = cues_for(name)
        if cues is None:
            return
        for first, second in zip(cues, cues[1:]):
            assert first.end <= second.start + 1e-6, f"{name}: {first.text}"


def test_no_line_starts_with_a_stranded_word():
    stranded = {"رو", "را", "و", "هم", "تر", "ترین", "ها", "های"}
    for name in ("smart", "reels"):
        cues = cues_for(name)
        if cues is None:
            return
        for cue in cues:
            for line in cue.lines:
                first = line.split()[0].strip("،؛:.!؟…")
                assert first not in stranded, f"{name}: {line}"


def test_persian_text_conventions_hold():
    cues = cues_for("smart")
    if cues is None:
        return
    joined = " ".join(cue.text for cue in cues)
    assert "ي" not in joined and "ك" not in joined  # Arabic letter variants
    assert "  " not in joined  # doubled spaces
    for cue in cues:
        assert not cue.text.rstrip().endswith(".")  # subtitles drop the full stop
        assert not cue.text.startswith(" ")


def test_switching_profile_keeps_the_same_words():
    smart = cues_for("smart")
    reels = cues_for("reels")
    if smart is None or reels is None:
        return

    def words(cues):
        return " ".join(c.text.replace("\n", " ") for c in cues).split()

    # Reels cuts differently, but must not invent or drop content.
    assert abs(len(words(smart)) - len(words(reels))) <= 2
