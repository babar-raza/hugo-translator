"""TC-APT-040 second manifestation: token-dominated frontmatter fields (2026-09-05).

The first fix skipped the check when fewer than 6 alphabetic characters of prose
survived stripping governed technical tokens. That reasoning -- "the unstripped
field is dominated by the very tokens just removed, so re-detecting it is a
structurally guaranteed false positive" -- does not stop applying when the field
is long. It was left applying only to the short branch, and the long branch kept
re-detecting the FULL field.

Found live: on cells/go/introducing-cells-foss-go, target `de` exhausted all five
attempts on `seoTitle`. German compounds keep the English technical tokens
("Open-Source-Go-Excel-Bibliothek"), so the prose attests German weakly while the
full field reads English at 0.999996 -- the exact confidence the failure record
logged (data/summaries/fp-recurrence-classes-survive-fixes-20260905.json).

These tests pin the fixed behaviour at the detection boundary: a correct
translation of a token-dominated field is accepted, and the two defects the guard
exists for -- an untranslated field and a wrong-language field -- are still caught.
"""

import langdetect
import pytest

from src.translation_engine.engine import _frontmatter_language_signal_text

CONFIDENCE_THRESHOLD = 0.80

# The exact source field whose German cell exhausted its retries.
SOURCE_SEO_TITLE = "Aspose.Cells FOSS for Go — Open-Source Go Excel Library"
CORRECT_DE = "Aspose.Cells FOSS für Go — Open-Source-Go-Excel-Bibliothek"
CORRECT_DE_ALT = "Aspose.Cells FOSS für Go — Quelloffene Go-Excel-Bibliothek"
WRONG_LANGUAGE_FOR_DE = "Bibliothèque Excel Go open source et gratuite pour les développeurs"


@pytest.fixture(autouse=True)
def _deterministic_langdetect():
    langdetect.DetectorFactory.seed = 0


def _rejects(text: str, target_lang: str) -> bool:
    """Mirror engine.py's frontmatter verdict for a single field."""
    signal_text = _frontmatter_language_signal_text(text)
    if sum(character.isalpha() for character in signal_text) < 6:
        return False
    detected = langdetect.detect_langs(signal_text)
    if not detected:
        return False
    top = detected[0]
    if top.lang == target_lang:
        return False
    return top.prob > CONFIDENCE_THRESHOLD


def test_correct_translation_of_a_token_dominated_field_is_accepted():
    """The real failing case: a correct German seoTitle must not be rejected."""
    assert not _rejects(CORRECT_DE, "de")


def test_alternative_correct_translation_is_also_accepted():
    assert not _rejects(CORRECT_DE_ALT, "de")


def test_untranslated_field_is_still_rejected():
    """The guard's actual job: an English field under a German target is a defect."""
    assert _rejects(SOURCE_SEO_TITLE, "de")


def test_wrong_target_language_is_still_rejected():
    assert _rejects(WRONG_LANGUAGE_FOR_DE, "de")


def test_that_same_text_is_accepted_for_its_own_language():
    assert not _rejects(WRONG_LANGUAGE_FOR_DE, "fr")


def test_the_full_field_is_what_used_to_misfire():
    """Pins WHY the fix was needed, so a revert cannot look harmless.

    Detecting the unstripped field calls a correct German rendering English with
    near-certainty; detecting the prose does not.
    """
    full_field = langdetect.detect_langs(CORRECT_DE)[0]
    assert full_field.lang == "en"
    assert full_field.prob > 0.99, "the old fallback saw near-certain English here"

    prose = langdetect.detect_langs(_frontmatter_language_signal_text(CORRECT_DE))[0]
    assert not (prose.lang == "en" and prose.prob > CONFIDENCE_THRESHOLD)


def test_engine_fallback_detects_on_signal_text_not_the_raw_field():
    """Source-level guard: the fallback must not go back to `v_stripped`."""
    from pathlib import Path

    source = Path("src/translation_engine/engine.py").read_text(encoding="utf-8")

    assert "detected_langs = _ld.detect_langs(signal_text)" in source
    assert "detected_langs = _ld.detect_langs(v_stripped)" not in source
