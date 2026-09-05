"""TC-APT-090: the frontmatter guard must stop naming languages on short residues.

Background, measured rather than assumed:

* Detection accuracy on the stripped signal residue is 66.2% at 6 alphabetic
  characters, 88.2% at 20, 91.2% at 25-30, 98.5% at 40 (19 shipped locales, 68
  samples per length). Confidence does not fall when the answer is wrong:
  87-91% of wrong answers exceed the 0.80 threshold, median confidence when
  wrong 1.000. So no confidence cut helps and length is the only lever.
* Below the floor the residue is page scaffolding, not prose. On
  introducing-cells-foss-rust the ENGLISH SOURCE seoTitle strips to
  "for - Open-Source Excel Crate for" and reads en 0.70 / ro 0.30, which is why
  cs, id, it, hi and ru were every one of them rejected on that page as
  Romanian while genuine Romanian passed. The verdict tracked the page.

These tests call the REAL method, not a mirror of it. The pre-existing module
tests/unit/translation_engine/test_frontmatter_language_token_dominated_fields.py
reimplements the verdict in a local helper with its own hard-coded floor; such a
stand-in keeps passing when the real code changes, which is exactly how an
earlier inert fix in this project went unnoticed. `_check_frontmatter_language`
touches no instance state, so a bare instance is a faithful harness.
"""

import langdetect
import pytest

from src.translation_engine.engine import (
    FRONTMATTER_UNTRANSLATED_SIMILARITY,
    MIN_FRONTMATTER_SIGNAL_ALPHA,
    TranslationEngine,
    _frontmatter_language_signal_text,
)

# The real seoTitle of introducing-cells-foss-rust, the page whose five
# unrelated locales were all rejected as Romanian.
SOURCE_SEO = "Aspose.Cells FOSS for Rust — Open-Source Excel Crate for Rust"
# Real shipped, reviewed renderings that the guard rejected or nearly rejected.
CZECH_SEO = "Aspose.Cells FOSS pro Rust — Open-Source knihovna pro Excel"
GERMAN_SEO = "Aspose.Cells FOSS für Rust — Open-Source-Excel-Crate für Rust"


@pytest.fixture(autouse=True)
def _deterministic_langdetect():
    langdetect.DetectorFactory.seed = 0


@pytest.fixture()
def engine():
    """A real TranslationEngine without __init__.

    The method under test reads no instance state, so this exercises the real
    code path rather than a reimplementation of it.
    """
    return TranslationEngine.__new__(TranslationEngine)


def _frontmatter(**fields):
    body = "\n".join(f'{k}: "{v}"' for k, v in fields.items())
    return f"---\n{body}\n---\n\nbody text\n"


def _issues(engine, target_lang, translated_fields, source_fields=None):
    return engine._check_frontmatter_language(
        _frontmatter(**translated_fields),
        target_lang,
        source_content=_frontmatter(**source_fields) if source_fields else "",
    )


def test_an_untranslated_field_is_rejected_by_identity_not_by_language():
    """The guard's real job, kept without consulting a language model."""
    engine = TranslationEngine.__new__(TranslationEngine)
    issues = _issues(engine, "cs", {"seoTitle": SOURCE_SEO}, {"seoTitle": SOURCE_SEO})

    assert issues, "an unchanged field must still be rejected"
    assert any(
        issue.details.get("reason") == "untranslated_frontmatter_field" for issue in issues
    ), "it must be rejected for being unchanged, not for its detected language"


def test_a_translated_short_field_is_accepted_however_langdetect_reads_it(engine):
    """The false-positive class: cs was rejected as 'sl' and 'ro' on real pages."""
    assert not _issues(engine, "cs", {"seoTitle": CZECH_SEO}, {"seoTitle": SOURCE_SEO})


def test_the_german_rendering_that_a_similarity_threshold_would_have_rejected(engine):
    """Regression on my own near-miss.

    A first draft used a 0.90 similarity threshold, justified by a corpus-wide
    figure. On this page the shipped, reviewed German cell scores 0.939 and
    would have been rejected. Exact identity is the only threshold whose premise
    is literally true.
    """
    assert not _issues(engine, "de", {"seoTitle": GERMAN_SEO}, {"seoTitle": SOURCE_SEO})


def test_no_source_content_means_no_verdict_rather_than_a_guessed_one(engine):
    """Without the source there is nothing to compare, so the guard must abstain."""
    assert not _issues(engine, "cs", {"seoTitle": SOURCE_SEO})


def test_the_short_residue_path_never_consults_langdetect(engine):
    """Pins WHY the fix works, so a revert cannot look harmless.

    langdetect confidently misreads this residue; the guard must not care.
    """
    residue = _frontmatter_language_signal_text(CZECH_SEO)
    assert sum(c.isalpha() for c in residue) < MIN_FRONTMATTER_SIGNAL_ALPHA

    detected = langdetect.detect_langs(residue)[0]
    if detected.lang != "cs":
        assert detected.prob > 0.80, "the misread is confident, which is the whole problem"
    assert not _issues(engine, "cs", {"seoTitle": CZECH_SEO}, {"seoTitle": SOURCE_SEO})


def test_a_long_wrong_language_field_is_still_rejected(engine):
    """Draft 2 of this fix would have destroyed this control; draft 4 keeps it.

    Above the floor the residue carries real information, so the language check
    still runs and a field written in the wrong language is still a defect.
    """
    french = (
        "Bibliothèque open source et gratuite pour les développeurs qui "
        "manipulent des feuilles de calcul au quotidien"
    )
    residue = _frontmatter_language_signal_text(french)
    assert sum(c.isalpha() for c in residue) >= MIN_FRONTMATTER_SIGNAL_ALPHA

    assert _issues(engine, "de", {"seoTitle": french}, {"seoTitle": SOURCE_SEO})


def test_the_constants_are_module_level_so_tests_cannot_hard_code_them():
    """The mirror-drift guard.

    The older module reimplements the verdict with a hard-coded floor. Exporting
    the real constants is what lets a test import them instead of copying a
    number that silently goes stale.
    """
    assert MIN_FRONTMATTER_SIGNAL_ALPHA == 40
    assert FRONTMATTER_UNTRANSLATED_SIMILARITY == 1.0
