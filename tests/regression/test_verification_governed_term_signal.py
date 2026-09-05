"""TC-APT-069: the governed term must be stripped in the WRITE-TIME check too.

The term now has to be listed in FOUR places that must agree:

  1. config/site_profiles/blog.aspose.org.yaml  preserve_patterns  (masking)
  2. src/translation_engine/engine.py           _FRONTMATTER_TECHNICAL_SIGNAL_RE
  3. config/terminology.yaml                    (terminology validator)
  4. src/verification/checks/language_check.py  TECHNICAL_SIGNAL_RE   <- this one

Missing the fourth made seoTitle the dominant failure on words-document-net: 6 of
r4's 7 failures were verification:language_detection on that field. The signal
was "for - Document Object Model &" (22 alphabetic characters, so the check ran
and misdetected) instead of "for &" (3 characters, correctly skipped by the
TC-APT-052 floor).

TC-APT-052's 6-char floor was already implemented here and working. The floor was
never the problem -- the token inventory it measures was.

These tests pin both directions: the governed term stops counting as language
evidence, and fields with real prose are still judged.
"""

import pytest

from src.verification.checks.language_check import LanguageDetectionCheck

TERM = "Document Object Model"
SEO_TITLE = "Aspose.Words FOSS for .NET — Document Object Model & DocumentBuilder"
TITLE = "Inside the Aspose.Words FOSS for .NET Document Object Model"


@pytest.fixture(scope="module")
def check():
    return LanguageDetectionCheck()


def _alpha(check, text):
    return sum(1 for character in check._language_signal_text(text) if character.isalpha())


def test_the_governed_term_is_not_language_evidence(check):
    assert TERM not in check._language_signal_text(SEO_TITLE)


def test_the_dominant_failing_field_is_now_skipped(check):
    """seoTitle: 22 alphabetic characters before, 3 after -- below the floor."""
    assert _alpha(check, SEO_TITLE) < 6


@pytest.mark.parametrize(
    "text",
    [
        TITLE,
        "There are no usage restrictions and no runtime fees",
        "Aspose.Words provides a document object model",
    ],
)
def test_fields_with_real_prose_are_still_judged(check, text):
    """The property that must not regress -- including the lowercase carve-out.

    Only the capitalized term of art is governed; the lowercase generic phrase
    is ordinary prose and must keep counting as language evidence.
    """
    assert _alpha(check, text) >= 6


def test_the_tc_apt_052_floor_is_untouched(check):
    """The floor was already correct; only the inventory it measures changed."""
    from pathlib import Path

    source = Path("src/verification/checks/language_check.py").read_text(encoding="utf-8")

    assert "< 6" in source


def test_this_inventory_agrees_with_the_engine_side_one(check):
    """The two regexes are near-copies and drifting apart is the actual bug.

    If someone governs a term in one and not the other, the write-time check and
    the frontmatter gate disagree about what counts as prose -- which is exactly
    what happened here.
    """
    from src.translation_engine.engine import _frontmatter_language_signal_text

    engine_side = _frontmatter_language_signal_text(SEO_TITLE)
    verification_side = check._language_signal_text(SEO_TITLE)

    assert (TERM in engine_side) == (TERM in verification_side)
