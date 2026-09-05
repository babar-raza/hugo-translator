"""TC-APT-079: the two signal inventories are derived, not hand-copied.

Governing ONE term took four commits across three iterations, because the same
fact had to be written into four independently-edited places and every miss
produced a distinct live failure -- the last of them made ``seoTitle`` the single
most frequent failure on words-document-net.

When this was written the drift was already large: config/terminology.yaml held
15 multi-word governed terms and the two signal regexes contained exactly ONE of
them, so ``API Reference``, ``REST API``, ``QR Code``, ``Data Matrix`` and the
barcode symbology names were all still being counted as prose evidence when
deciding what language a short field was written in. That reaches whole
subdomains, not just one page.

test_every_governed_term_is_stripped_by_both_signal_paths is the drift guard: it
fails the moment the two inventories disagree about any governed term.
"""

from pathlib import Path

import pytest

from src.translation_engine.engine import _frontmatter_language_signal_text
from src.translation_engine.governed_terms import (
    governed_multiword_terms,
    governed_signal_alternation,
)
from src.verification.checks.language_check import LanguageDetectionCheck


@pytest.fixture(scope="module")
def verification_signal():
    return LanguageDetectionCheck()._language_signal_text


def test_terms_come_from_the_terminology_config():
    terms = governed_multiword_terms()

    assert "Document Object Model" in terms
    assert len(terms) > 1, "only the hand-copied fallback term was found"


def test_terms_are_longest_first():
    """`API Reference Guide` must claim its span before `API Reference` can.

    Same ordering rule the site profiles' preserve_patterns already follow.
    """
    terms = governed_multiword_terms()

    assert list(terms) == sorted(terms, key=lambda term: (-len(term), term))


def test_only_multi_word_terms_are_governed_here():
    """Single tokens are excluded on purpose.

    The signal regexes already cover that shape generically, and stripping every
    single-token entry would remove ordinary words like "Java" or "Office" from
    prose that is genuinely using them as prose.
    """
    assert all(" " in term for term in governed_multiword_terms())


@pytest.mark.parametrize("term", governed_multiword_terms())
def test_every_governed_term_is_stripped_by_both_signal_paths(term, verification_signal):
    """The drift guard. This is the test that would have caught the original bug."""
    text = f"Introducing the {term} for developers"

    assert term not in _frontmatter_language_signal_text(text), "engine-side signal kept it"
    assert term not in verification_signal(text), "verification-side signal kept it"


def test_the_two_signal_paths_agree_on_every_governed_term(verification_signal):
    """Stronger than 'both strip it': they must produce the same verdict."""
    for term in governed_multiword_terms():
        text = f"The {term} reference"
        engine_alpha = sum(c.isalpha() for c in _frontmatter_language_signal_text(text))
        verify_alpha = sum(c.isalpha() for c in verification_signal(text))

        assert (engine_alpha >= 6) == (verify_alpha >= 6), f"paths disagree on {term!r}"


def test_ordinary_prose_is_untouched(verification_signal):
    """Neutrality: the point is to remove terminology, not to shrink prose."""
    prose = "There are no usage restrictions and no runtime fees for developers"

    assert sum(c.isalpha() for c in _frontmatter_language_signal_text(prose)) >= 6
    assert sum(c.isalpha() for c in verification_signal(prose)) >= 6


def test_the_alternation_never_produces_an_empty_branch():
    """An empty alternative would match at every position and strip everything."""
    alternation = governed_signal_alternation()

    assert not alternation.startswith("|")
    assert "||" not in alternation
    assert alternation.endswith("|")


def test_the_config_and_the_profile_agree_on_the_governed_term():
    """Inventories 1 and 3 are not merged, so assert they agree instead.

    Masking and validation are different jobs and a term can legitimately be
    validated without being masked -- but a term governed in one and unknown to
    the other is the drift that caused this whole sequence.
    """
    from src.utils.config_loader import ConfigService

    patterns = ConfigService(Path("config")).get_site_profile("blog.aspose.org").body.preserve_patterns

    assert any("Document Object Model" in pattern for pattern in patterns)
    assert "Document Object Model" in governed_multiword_terms()
