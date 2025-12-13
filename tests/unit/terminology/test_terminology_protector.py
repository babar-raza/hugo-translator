"""Tests for TerminologyProtector.

This module tests the TerminologyProtector class which protects terminology
by replacing detected terms with placeholders and restoring them afterward.

Test coverage:
- Protection: terms -> {TERM_N} placeholders
- Restoration: placeholders -> original terms
- Ordering: nested/adjacent terms handled correctly
- Restoration failure handling: missing placeholders
"""

import pytest
from src.translation_engine.terminology.models import (
    TermRule,
    DetectedTerm,
    PreserveMode,
    TermSeverity,
)
from src.translation_engine.terminology.terminology_protector import TerminologyProtector


class TestTerminologyProtector:
    """Test suite for TerminologyProtector."""

    def test_protect_single_term(self):
        """Test protection of a single term."""
        protector = TerminologyProtector()
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose is great", detected_terms)

        assert protected.original_text == "Aspose is great"
        assert protected.protected_text == "{TERM_0} is great"
        assert len(protected.term_mapping) == 1
        assert protected.term_mapping[0].term_text == "Aspose"

    def test_protect_multiple_terms(self):
        """Test protection of multiple terms."""
        protector = TerminologyProtector()
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule1,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            ),
            DetectedTerm(
                term_text=".NET",
                rule=rule2,
                start_pos=11,
                end_pos=15,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose for .NET rocks", detected_terms)

        assert protected.original_text == "Aspose for .NET rocks"
        assert protected.protected_text == "{TERM_0} for {TERM_1} rocks"
        assert len(protected.term_mapping) == 2
        assert protected.term_mapping[0].term_text == "Aspose"
        assert protected.term_mapping[1].term_text == ".NET"

    def test_protect_no_terms(self):
        """Test protection with no detected terms."""
        protector = TerminologyProtector()
        protected = protector.protect("Hello world", [])

        assert protected.original_text == "Hello world"
        assert protected.protected_text == "Hello world"
        assert len(protected.term_mapping) == 0

    def test_protect_adjacent_terms(self):
        """Test protection of adjacent terms."""
        protector = TerminologyProtector()
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term="Words",
            category="product",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule1,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            ),
            DetectedTerm(
                term_text="Words",
                rule=rule2,
                start_pos=7,
                end_pos=12,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose Words", detected_terms)

        assert protected.protected_text == "{TERM_0} {TERM_1}"
        assert protected.term_mapping[0].term_text == "Aspose"
        assert protected.term_mapping[1].term_text == "Words"

    def test_protect_nested_terms(self):
        """Test protection when one term could be nested in another.

        This tests the ordering logic - longer terms should be processed
        to avoid substring conflicts.
        """
        protector = TerminologyProtector()
        rule = TermRule(
            pattern=r"Aspose\.Words",
            category="product",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose.Words",
                rule=rule,
                start_pos=0,
                end_pos=12,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose.Words is great", detected_terms)

        assert protected.protected_text == "{TERM_0} is great"
        assert protected.term_mapping[0].term_text == "Aspose.Words"

    def test_restore_single_term(self):
        """Test restoration of a single term."""
        protector = TerminologyProtector()
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose is great", detected_terms)
        restored = protector.restore(protected)

        assert restored == "Aspose is great"

    def test_restore_multiple_terms(self):
        """Test restoration of multiple terms."""
        protector = TerminologyProtector()
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule1,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            ),
            DetectedTerm(
                term_text=".NET",
                rule=rule2,
                start_pos=11,
                end_pos=15,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose for .NET rocks", detected_terms)
        restored = protector.restore(protected)

        assert restored == "Aspose for .NET rocks"

    def test_restore_with_translation(self):
        """Test restoration after simulated translation.

        Simulates the translation step by modifying the protected text
        while keeping placeholders intact.
        """
        protector = TerminologyProtector()
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule1,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            ),
            DetectedTerm(
                term_text=".NET",
                rule=rule2,
                start_pos=11,
                end_pos=15,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose for .NET rocks", detected_terms)

        # Simulate translation: "for" -> "pour", "rocks" -> "déchire"
        # Original protected: "{TERM_0} for {TERM_1} rocks"
        # Translated: "{TERM_0} pour {TERM_1} déchire"
        from src.translation_engine.terminology.models import ProtectedSegment
        translated = ProtectedSegment(
            original_text=protected.original_text,
            protected_text="{TERM_0} pour {TERM_1} déchire",
            term_mapping=protected.term_mapping
        )

        restored = protector.restore(translated)
        assert restored == "Aspose pour .NET déchire"

    def test_restore_missing_placeholder(self):
        """Test restoration when a placeholder is missing.

        This tests graceful handling when translation removes a placeholder.
        The missing placeholder should simply not be replaced.
        """
        protector = TerminologyProtector()
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose",
                rule=rule1,
                start_pos=0,
                end_pos=6,
                confidence=1.0
            ),
            DetectedTerm(
                term_text=".NET",
                rule=rule2,
                start_pos=11,
                end_pos=15,
                confidence=1.0
            )
        ]

        protected = protector.protect("Aspose for .NET rocks", detected_terms)

        # Simulate translation that removes {TERM_1}
        from src.translation_engine.terminology.models import ProtectedSegment
        translated = ProtectedSegment(
            original_text=protected.original_text,
            protected_text="{TERM_0} pour quelque chose",  # {TERM_1} is missing
            term_mapping=protected.term_mapping
        )

        restored = protector.restore(translated)

        # Should restore {TERM_0} but not {TERM_1} since it's missing
        assert restored == "Aspose pour quelque chose"

    def test_protect_restore_cycle(self):
        """Test full protection-restoration cycle."""
        protector = TerminologyProtector()
        rule = TermRule(
            pattern=r"Aspose\.\w+",
            category="product",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        detected_terms = [
            DetectedTerm(
                term_text="Aspose.Words",
                rule=rule,
                start_pos=0,
                end_pos=12,
                confidence=1.0
            ),
            DetectedTerm(
                term_text="Aspose.Cells",
                rule=rule,
                start_pos=17,
                end_pos=29,
                confidence=1.0
            )
        ]

        original_text = "Aspose.Words and Aspose.Cells"
        protected = protector.protect(original_text, detected_terms)
        restored = protector.restore(protected)

        assert restored == original_text

    def test_protect_terms_at_different_positions(self):
        """Test protection of terms at various positions in text."""
        protector = TerminologyProtector()
        rule = TermRule(
            term="test",
            category="test_term",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )

        # Terms at beginning, middle, and end
        # "test is in the test and at end test"
        # Position: 0-4 for first "test", 15-19 for second "test", 31-35 for third "test"
        detected_terms = [
            DetectedTerm(
                term_text="test",
                rule=rule,
                start_pos=0,
                end_pos=4,
                confidence=1.0
            ),
            DetectedTerm(
                term_text="test",
                rule=rule,
                start_pos=15,
                end_pos=19,
                confidence=1.0
            ),
            DetectedTerm(
                term_text="test",
                rule=rule,
                start_pos=31,
                end_pos=35,
                confidence=1.0
            )
        ]

        protected = protector.protect("test is in the test and at end test", detected_terms)

        assert protected.protected_text == "{TERM_0} is in the {TERM_1} and at end {TERM_2}"
        assert len(protected.term_mapping) == 3

    def test_empty_text(self):
        """Test protection of empty text."""
        protector = TerminologyProtector()
        protected = protector.protect("", [])

        assert protected.original_text == ""
        assert protected.protected_text == ""
        assert len(protected.term_mapping) == 0

    def test_restore_empty_text(self):
        """Test restoration of empty text."""
        protector = TerminologyProtector()
        from src.translation_engine.terminology.models import ProtectedSegment

        protected = ProtectedSegment(
            original_text="",
            protected_text="",
            term_mapping={}
        )

        restored = protector.restore(protected)
        assert restored == ""
