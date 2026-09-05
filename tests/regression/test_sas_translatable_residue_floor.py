"""TC-SAS-01 residue floor: judge only units that had something to translate.

TC-SAS-01 counts a unit as "unchanged" when the model returns it byte-identical, and
under zero-defect the tolerance is 0%. That is only evidence of a failure if the unit
held translatable content in the first place.

Measured on words-document-net: the cs cell was rejected with
"same-as-source ratio 1.9% exceeds tolerance 0.0% (1/54 units unchanged);
unit_fingerprints=link_text:24a774f596eca994" -- that fingerprint is
sha256('Aspose.Words for .NET')[:16]. After protection the model receives
"{PH} for .NET", so the whole translatable residue is the preposition "for". A model
that leaves three characters alone made a 54-unit cell fail. The ar cell of the same
page did localise it, so this is variance on three characters, not a quality signal.

The floor is deliberately conservative. The test that matters most here is
test_genuinely_untranslated_prose_is_still_counted: the gate must keep catching real
misses, because relaxing it would be relaxing a quality control rather than fixing a
false positive.
"""

from pathlib import Path

import pytest

from src.translation_engine.segment_translator import _has_translatable_residue
from src.utils.config_loader import ConfigService

BLOG_PATTERNS = ConfigService(Path("config")).get_site_profile("blog.aspose.org").body.preserve_patterns


@pytest.mark.parametrize(
    "text",
    [
        "Aspose.Words for .NET",            # the exact culprit, by fingerprint
        "Aspose.Words FOSS",                 # brand compound only
        "Aspose.Cells for Go",               # same shape, other product
        "API HTTP JSON",                     # bare acronyms
    ],
)
def test_units_with_no_real_word_are_not_judgeable(text):
    assert not _has_translatable_residue(text, BLOG_PATTERNS), text


@pytest.mark.parametrize(
    "text",
    [
        "The source code is available at",
        "There are no usage restrictions, no runtime fees",
        "Aspose.Words provides a document object model",
        "Read cells back from a worksheet",
    ],
)
def test_genuinely_untranslated_prose_is_still_counted(text):
    """The property that must never regress: real misses still fail the gate."""
    assert _has_translatable_residue(text, BLOG_PATTERNS), text


def test_the_floor_does_not_depend_on_raw_length():
    """Why the existing same_as_source_min_length floor did not catch this.

    'Aspose.Words for .NET' is 21 characters, comfortably past the default floor of
    10, so it was counted despite offering nothing to translate.
    """
    culprit = "Aspose.Words for .NET"

    assert len(culprit) > 10
    assert not _has_translatable_residue(culprit, BLOG_PATTERNS)


def test_an_all_caps_token_is_not_mistaken_for_a_word():
    assert not _has_translatable_residue("Aspose.Words DOCX PDF RTF", BLOG_PATTERNS)


def test_a_lowercase_word_of_the_floor_length_is_judgeable():
    assert _has_translatable_residue("Aspose.Words core", BLOG_PATTERNS)


def test_without_preserve_patterns_a_brand_phrase_reads_as_translatable():
    """The floor is relative to what was actually masked, not a hardcoded brand list."""
    assert _has_translatable_residue("Aspose.Words for .NET", [])


def test_min_word_len_is_a_parameter_not_a_magic_number():
    assert _has_translatable_residue("Aspose.Words for .NET", BLOG_PATTERNS, min_word_len=3)
    assert not _has_translatable_residue("Aspose.Words for .NET", BLOG_PATTERNS, min_word_len=4)


def test_a_broken_pattern_does_not_break_the_check():
    """A malformed profile pattern must not take the gate down with it."""
    assert _has_translatable_residue("The source code is available", ["([unclosed"])
