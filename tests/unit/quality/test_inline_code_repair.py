"""HT-INLINE-CODE-001 TC-ICR-001: regression suite for the shared
inline-code-span detector/repairer.

Every fixture here encodes a specific, previously-observed failure mode
from the three prior, independent (and differently buggy)
reimplementations of this check -- see inline_code_repair.py's module
docstring for the full rationale.
"""
from __future__ import annotations

from src.translation_engine.quality.inline_code_repair import (
    find_inline_code_mismatches,
    has_translated_inline_code,
    restore_inline_code_spans,
)


class TestBelowThreshold:
    def test_fewer_than_three_en_spans_never_fires(self) -> None:
        en = "Call `Save` then `Close`."
        tr = "Appelez `Enregistrer` puis `Fermer`."
        assert find_inline_code_mismatches(en, tr) == []
        assert restore_inline_code_spans(en, tr) is None
        assert has_translated_inline_code(en, tr) is False


class TestBasicCorruption:
    def test_single_corrupted_span_detected_and_fixed(self) -> None:
        en = "The `AssetInfo` class has `GetName` and `SetName` methods."
        tr = "La classe `AssetInfo` a des méthodes `RécupérerNom` et `SetName`."
        mismatches = find_inline_code_mismatches(en, tr)
        assert mismatches is not None
        assert len(mismatches) == 1
        assert mismatches[0].en_span == "GetName"
        assert mismatches[0].tr_span == "RécupérerNom"

        fixed = restore_inline_code_spans(en, tr)
        assert fixed == "La classe `AssetInfo` a des méthodes `GetName` et `SetName`."

    def test_multiple_corrupted_spans_all_fixed_not_just_first(self) -> None:
        en = "Use `equals`, `close`, and `create` in that order."
        tr = "Utilisez `identité`, `fermé`, et `create` dans cet ordre."
        mismatches = find_inline_code_mismatches(en, tr)
        assert mismatches is not None
        assert len(mismatches) == 2
        assert {m.en_span for m in mismatches} == {"equals", "close"}

        fixed = restore_inline_code_spans(en, tr)
        assert fixed == "Utilisez `equals`, `close`, et `create` dans cet ordre."

    def test_real_world_fmatrix4_example(self) -> None:
        # Reconstructed from reference.aspose.org/fr/3d/java/FMatrix4.md's
        # real audit hit: `equals` -> `identité`.
        en = "| `equals` | `hashCode` | `toString` | Standard Java members. |"
        tr = "| `identité` | `hashCode` | `toString` | Membres Java standards. |"
        fixed = restore_inline_code_spans(en, tr)
        assert fixed == "| `equals` | `hashCode` | `toString` | Membres Java standards. |"


class TestSpanCountMismatchIsUnsafeToGuess:
    def test_dropped_span_returns_none_not_a_guess(self) -> None:
        en = "Use `create`, `close`, and `equals` here."
        # TR dropped one span entirely (2 spans instead of 3) -- positional
        # pairing from here on would be a guess, not a fact.
        tr = "Utilisez . Tous les membres publics sont `fermer` et `equals` ici."
        assert find_inline_code_mismatches(en, tr) is None
        assert restore_inline_code_spans(en, tr) is None
        assert has_translated_inline_code(en, tr) is False

    def test_extra_span_returns_none_not_a_guess(self) -> None:
        en = "Use `create`, `close`, and `equals` here."
        tr = "Utilisez `create`, `fermer`, `equals`, et `extra` ici."
        assert find_inline_code_mismatches(en, tr) is None
        assert restore_inline_code_spans(en, tr) is None


class TestFencedCodeBlockExclusion:
    def test_fence_backticks_do_not_corrupt_span_pairing(self) -> None:
        en = (
            "The `AssetInfo` class has `GetName` and `SetName` methods.\n\n"
            "```java\n"
            "AssetInfo info = new AssetInfo();\n"
            "```\n"
        )
        tr = (
            "La classe `AssetInfo` a des méthodes `GetName` et `SetName`.\n\n"
            "```java\n"
            "AssetInfo info = new AssetInfo();\n"
            "```\n"
        )
        # All 3 real inline spans are clean; the fence's own backticks must
        # not be mispaired as a 4th/5th inline span.
        assert find_inline_code_mismatches(en, tr) == []
        assert restore_inline_code_spans(en, tr) is None

    def test_corruption_still_detected_alongside_a_fence(self) -> None:
        en = (
            "The `AssetInfo` class has `GetName` and `SetName` methods.\n\n"
            "```java\n"
            "AssetInfo info = new AssetInfo();\n"
            "```\n"
        )
        tr = (
            "La classe `AssetInfo` a des méthodes `RécupérerNom` et `SetName`.\n\n"
            "```java\n"
            "AssetInfo info = new AssetInfo();\n"
            "```\n"
        )
        mismatches = find_inline_code_mismatches(en, tr)
        assert mismatches is not None
        assert len(mismatches) == 1
        assert mismatches[0].en_span == "GetName"
        fixed = restore_inline_code_spans(en, tr)
        assert "`GetName`" in fixed
        assert "```java\nAssetInfo info = new AssetInfo();\n```" in fixed


class TestStrayBacktickBeforeTableRow:
    """Reproduces the documented m2m100 artifact (write_gate.py's own
    comment: 'm2m100 inserts a stray ` before table rows'). Without the
    [^`\\n] newline exclusion, a naive regex lets this stray backtick pair
    with an unrelated backtick later in the document, swallowing everything
    in between -- confirmed as the actual cause of ~59%% of the original
    21,904-hit audit count when read directly against the raw JSONL."""

    def test_stray_leading_table_backtick_does_not_swallow_next_paragraph(
        self,
    ) -> None:
        en = (
            "The `AssetInfo` class has `GetName` and `SetName` methods.\n\n"
            "| Col |\n| --- |\n| data |\n"
        )
        tr = (
            "La classe `AssetInfo` a des méthodes `GetName` et `SetName`.\n\n"
            "` | Данные |\n| --- |\n| données |\n"
        )
        # The stray backtick is unpaired within its own line (newline
        # excluded from the span pattern) -- it must not merge with any
        # other backtick and must not corrupt the count of real spans.
        assert find_inline_code_mismatches(en, tr) == []
        assert restore_inline_code_spans(en, tr) is None


class TestNonBackticksNeverConsidered:
    def test_bare_hyphenated_technical_code_outside_backticks_ignored(
        self,
    ) -> None:
        # UPC-E / PDF/A style codes are real content this corpus protects
        # elsewhere (config/site_profiles preserve_patterns), but they are
        # NOT this detector's concern unless they appear inside backticks --
        # confirms no false positive from bare technical-looking text.
        en = "The `AssetInfo` class supports UPC-E and `GetName`/`SetName`."
        tr = "La classe `AssetInfo` prend en charge UPC-E et `GetName`/`SetName`."
        assert find_inline_code_mismatches(en, tr) == []


class TestNonAsciiEnglishSpanNeverFlagged:
    def test_en_span_already_non_ascii_is_skipped(self) -> None:
        # If EN itself wasn't ASCII (rare, e.g. a pre-existing non-ASCII
        # identifier), the "translated instead of preserved" signature
        # doesn't apply -- must never fire regardless of what TR contains.
        en = "Use `café_id`, `GetName`, and `SetName` here."
        tr = "Utilisez `identifiant_café`, `GetName`, et `SetName` ici."
        mismatches = find_inline_code_mismatches(en, tr)
        assert mismatches == []


class TestRestoreInvariant:
    def test_restore_returns_none_when_nothing_to_fix(self) -> None:
        en = "Use `create`, `close`, and `equals` here."
        tr = "Utilisez `create`, `close`, et `equals` ici."
        assert restore_inline_code_spans(en, tr) is None

    def test_restore_changes_nothing_outside_the_flagged_spans(self) -> None:
        en = "Before text. Use `create`, `close`, and `equals` here. After text."
        tr = "Avant le texte. Utilisez `créer`, `close`, et `identité` ici. Après le texte."
        fixed = restore_inline_code_spans(en, tr)
        assert fixed is not None
        assert fixed.startswith("Avant le texte. Utilisez ")
        assert fixed.endswith(" ici. Après le texte.")
        assert "`close`" in fixed  # the one already-clean span, untouched
        assert "`create`" in fixed
        assert "`equals`" in fixed
        assert "créer" not in fixed
        assert "identité" not in fixed
