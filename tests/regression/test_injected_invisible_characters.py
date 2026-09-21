"""TC-APT-073: the producer must not introduce invisible punctuation of its own.

Measured on words-document-net's seven accepted cells: U+2011 NON-BREAKING
HYPHEN appears in 7 of 7 locales -- 147 occurrences (nl 67, he 37, fr 22, hi 11,
el 7, ar 2, fa 1) -- with ZERO in the English source, and U+00AD SOFT HYPHEN
appears word-interior in fr. Both render like ordinary punctuation, which is why
human reviewers caught them in only two of the seven locales while they break
copy, search and diffing everywhere.

By RB-005's recurrence test -- the same defect at the same structural position
across multiple locales is not variance -- this is a producer bug.

The normalization is deliberately conditional on the source, so this is a
fidelity rule ("do not introduce what the source lacks") rather than a
character ban. The tests below pin both halves: what gets removed, and what must
survive.
"""

import pytest

from src.translation_engine.segment_translator import normalize_injected_invisibles

NBH = "‑"  # NON-BREAKING HYPHEN
SHY = "­"  # SOFT HYPHEN
ZWSP = "​"
RLM = "‏"
NBSP = " "


def test_the_non_breaking_hyphen_becomes_a_real_hyphen():
    """The 147-occurrence defect: it must render AND copy as a hyphen."""
    assert normalize_injected_invisibles("node-tree", f"node{NBH}tree") == "node-tree"


def test_the_soft_hyphen_is_removed_not_replaced():
    """fr line 443: invisible, word-interior. Replacing it would split the word."""
    assert normalize_injected_invisibles("dependent", f"depen{SHY}dent") == "dependent"


def test_a_character_the_source_itself_uses_is_left_alone():
    """The rule is 'do not introduce', not 'never allow'."""
    text = f"node{NBH}tree"

    assert normalize_injected_invisibles(f"node{NBH}tree", text) == text


def test_rtl_marks_are_never_touched():
    """ar/fa/he can need these for correct bidi rendering; stripping them damages output."""
    text = f"a{RLM}b"

    assert normalize_injected_invisibles("ab", text) == text


def test_non_breaking_space_is_not_touched():
    """fr typography uses NBSP legitimately before ':' and '!'; out of scope here."""
    text = f"mot{NBSP}: suite"

    assert normalize_injected_invisibles("word: next", text) == text


def test_every_occurrence_is_normalized_not_just_the_first():
    """nl carried 67 in one file."""
    translated = NBH.join(["a"] * 68)

    assert NBH not in normalize_injected_invisibles("plain", translated)
    assert normalize_injected_invisibles("plain", translated).count("-") == 67


@pytest.mark.parametrize("empty", ["", None])
def test_empty_translation_is_returned_unchanged(empty):
    assert normalize_injected_invisibles("source", empty) == empty


def test_missing_source_still_normalizes():
    """A segment with no recorded source must not silently skip the fix."""
    assert normalize_injected_invisibles("", f"node{NBH}tree") == "node-tree"
    assert normalize_injected_invisibles(None, f"node{NBH}tree") == "node-tree"


def test_ordinary_text_is_returned_byte_identical():
    """Neutrality: the normalizer must be a no-op on clean output."""
    for text in ("Une phrase ordinaire.", "نص عادي", "सामान्य पाठ", "a-b-c", "x"):
        assert normalize_injected_invisibles("source text", text) == text


def test_it_runs_before_placeholder_restore_so_protected_spans_are_masked():
    """Placement property, asserted on the source rather than assumed.

    _restore_placeholders normalizes its input and only then restores, so code
    spans, links and shortcodes are still placeholders when normalization runs
    and can never be rewritten by it.
    """
    from pathlib import Path

    source = Path("src/translation_engine/segment_translator.py").read_text(encoding="utf-8")
    body = source.split("def _restore_placeholders(")[1]
    normalize_at = body.index("normalize_injected_invisibles")
    restore_at = body.index("placeholder_manager.restore")

    assert normalize_at < restore_at
