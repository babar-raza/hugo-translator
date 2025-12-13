"""Tests for TerminologyDetector.

Tests cover:
- Exact match detection (case-sensitive and case-insensitive)
- Pattern match detection (regex)
- Word boundary enforcement
- Overlapping match resolution (longest wins)
- Edge cases (empty text, no matches, invalid patterns)
"""

import pytest
from src.translation_engine.terminology.models import (
    TermRule,
    PreserveMode,
    TermSeverity,
)
from src.translation_engine.terminology.terminology_detector import TerminologyDetector


class TestTerminologyDetector:
    """Test suite for TerminologyDetector."""

    def test_detect_exact_match_single(self):
        """Test exact match detection for a single occurrence."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose is great")

        assert len(detected) == 1
        assert detected[0].term_text == "Aspose"
        assert detected[0].start_pos == 0
        assert detected[0].end_pos == 6
        assert detected[0].confidence == 1.0
        assert detected[0].rule == rule

    def test_detect_exact_match_multiple(self):
        """Test exact match detection for multiple occurrences."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose is great and Aspose rocks")

        assert len(detected) == 2
        assert detected[0].term_text == "Aspose"
        assert detected[0].start_pos == 0
        assert detected[1].term_text == "Aspose"
        assert detected[1].start_pos == 20

    def test_detect_pattern_match(self):
        """Test pattern match detection using regex."""
        rule = TermRule(
            pattern=r"Aspose\.\w+",
            category="product_family",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose.Words and Aspose.Cells are products")

        assert len(detected) == 2
        assert detected[0].term_text == "Aspose.Words"
        assert detected[0].start_pos == 0
        assert detected[1].term_text == "Aspose.Cells"
        assert detected[1].start_pos == 17

    def test_case_sensitive_exact_match(self):
        """Test case-sensitive exact matching."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR,
            case_sensitive=True
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose and aspose and ASPOSE")

        # Only exact case match should be detected
        assert len(detected) == 1
        assert detected[0].term_text == "Aspose"

    def test_case_insensitive_exact_match(self):
        """Test case-insensitive exact matching."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR,
            case_sensitive=False
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose and aspose and ASPOSE")

        # All case variations should be detected
        assert len(detected) == 3
        assert detected[0].term_text == "Aspose"
        assert detected[1].term_text == "aspose"
        assert detected[2].term_text == "ASPOSE"

    def test_case_sensitive_pattern_match(self):
        """Test case-sensitive pattern matching."""
        rule = TermRule(
            pattern=r"Aspose\.\w+",
            category="product_family",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR,
            case_sensitive=True
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose.Words and aspose.cells")

        # Only properly cased match should be detected
        assert len(detected) == 1
        assert detected[0].term_text == "Aspose.Words"

    def test_case_insensitive_pattern_match(self):
        """Test case-insensitive pattern matching."""
        rule = TermRule(
            pattern=r"Aspose\.\w+",
            category="product_family",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR,
            case_sensitive=False
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose.Words and aspose.cells")

        # Both case variations should be detected
        assert len(detected) == 2
        assert detected[0].term_text == "Aspose.Words"
        assert detected[1].term_text == "aspose.cells"

    def test_word_boundaries_dotnet(self):
        """Test word boundary enforcement for .NET."""
        rule = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR,
            case_sensitive=False
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("internet and .NET framework")

        # Should only match ".NET", not "net" in "internet"
        assert len(detected) == 1
        assert detected[0].term_text == ".NET"
        assert detected[0].start_pos == 13

    def test_word_boundaries_prevents_substring_match(self):
        """Test word boundaries prevent matching within words."""
        rule = TermRule(
            term="Java",
            category="platform",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("JavaScript and Java")

        # Should only match "Java", not "Java" in "JavaScript"
        assert len(detected) == 1
        assert detected[0].term_text == "Java"
        assert detected[0].start_pos == 15

    def test_overlapping_matches_longest_wins(self):
        """Test that longest match wins when overlaps occur."""
        rule1 = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term="Aspose.Words",
            category="product",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule1, rule2])
        detected = detector.detect("Aspose.Words is great")

        # Should only keep "Aspose.Words" (longer match)
        assert len(detected) == 1
        assert detected[0].term_text == "Aspose.Words"

    def test_overlapping_pattern_and_exact(self):
        """Test overlap resolution between pattern and exact matches."""
        rule1 = TermRule(
            pattern=r"Aspose\.\w+",
            category="product_family",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        rule2 = TermRule(
            term="Words",
            category="generic",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.WARNING
        )
        detector = TerminologyDetector([rule1, rule2])
        detected = detector.detect("Aspose.Words documentation")

        # Should only keep "Aspose.Words" (longer match)
        assert len(detected) == 1
        assert detected[0].term_text == "Aspose.Words"

    def test_no_matches_in_text(self):
        """Test behavior when no matches are found."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("This text has no terminology")

        assert len(detected) == 0

    def test_empty_text(self):
        """Test behavior with empty text."""
        rule = TermRule(
            term="Aspose",
            category="company_name",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("")

        assert len(detected) == 0

    def test_invalid_regex_pattern(self):
        """Test that invalid regex patterns are handled gracefully."""
        rule = TermRule(
            pattern=r"[invalid(pattern",  # Invalid regex
            category="test",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("some text")

        # Should return empty list, not raise exception
        assert len(detected) == 0

    def test_multiple_rules_different_categories(self):
        """Test detection with multiple rules from different categories."""
        rules = [
            TermRule(
                term="Aspose",
                category="company_name",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            ),
            TermRule(
                term=".NET",
                category="platform",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR,
                case_sensitive=False
            ),
            TermRule(
                pattern=r"\b[A-Z]{2,}\b",  # Acronyms
                category="acronym",
                preserve_mode=PreserveMode.PROTECT,
                severity=TermSeverity.WARNING
            )
        ]
        detector = TerminologyDetector(rules)
        detected = detector.detect("Aspose.Words for .NET API")

        # Should detect multiple terms
        assert len(detected) >= 2  # At least Aspose and .NET
        term_texts = [d.term_text for d in detected]
        assert "Aspose" in term_texts
        assert ".NET" in term_texts

    def test_preserve_mode_none_filtered(self):
        """Test that rules with PreserveMode.NONE are filtered out."""
        rules = [
            TermRule(
                term="Aspose",
                category="company_name",
                preserve_mode=PreserveMode.NONE,
                severity=TermSeverity.ERROR
            ),
            TermRule(
                term="Words",
                category="product",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            )
        ]
        detector = TerminologyDetector(rules)
        detected = detector.detect("Aspose.Words")

        # Should only detect "Words", not "Aspose"
        assert len(detected) == 1
        assert detected[0].term_text == "Words"

    def test_detection_sorted_by_position(self):
        """Test that detected terms are sorted by start position."""
        rules = [
            TermRule(
                term="Words",
                category="product",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            ),
            TermRule(
                term="Aspose",
                category="company",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            )
        ]
        detector = TerminologyDetector(rules)
        detected = detector.detect("Words from Aspose")

        # Should be sorted by position
        assert len(detected) == 2
        assert detected[0].term_text == "Words"
        assert detected[0].start_pos == 0
        assert detected[1].term_text == "Aspose"
        assert detected[1].start_pos == 11

    def test_adjacent_matches_no_overlap(self):
        """Test detection of adjacent matches without overlap."""
        rules = [
            TermRule(
                term="Aspose",
                category="company",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            ),
            TermRule(
                term="Words",
                category="product",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            )
        ]
        detector = TerminologyDetector(rules)
        detected = detector.detect("Aspose Words")

        # Both should be detected (no overlap)
        assert len(detected) == 2
        assert detected[0].term_text == "Aspose"
        assert detected[1].term_text == "Words"

    def test_pattern_with_groups(self):
        """Test pattern matching with regex groups."""
        rule = TermRule(
            pattern=r"(Aspose)\.(Words|Cells)",
            category="product",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Using Aspose.Words and Aspose.Cells")

        assert len(detected) == 2
        assert detected[0].term_text == "Aspose.Words"
        assert detected[1].term_text == "Aspose.Cells"

    def test_special_characters_in_exact_match(self):
        """Test exact matching with special characters."""
        rule = TermRule(
            term=".NET",
            category="platform",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Using .NET framework")

        assert len(detected) == 1
        assert detected[0].term_text == ".NET"

    def test_multiline_text(self):
        """Test detection in multiline text."""
        rule = TermRule(
            term="Aspose",
            category="company",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        text = """Line 1 with Aspose
Line 2 with Aspose
Line 3"""
        detected = detector.detect(text)

        assert len(detected) == 2
        assert all(d.term_text == "Aspose" for d in detected)

    def test_unicode_text(self):
        """Test detection in text with unicode characters."""
        rule = TermRule(
            term="Aspose",
            category="company",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose 是一个公司 Aspose")

        assert len(detected) == 2
        assert detected[0].term_text == "Aspose"
        assert detected[1].term_text == "Aspose"

    def test_confidence_always_one(self):
        """Test that confidence is always 1.0 for exact/pattern matches."""
        rules = [
            TermRule(
                term="Aspose",
                category="company",
                preserve_mode=PreserveMode.BOTH,
                severity=TermSeverity.ERROR
            ),
            TermRule(
                pattern=r"\w+\.NET",
                category="platform",
                preserve_mode=PreserveMode.PROTECT,
                severity=TermSeverity.ERROR
            )
        ]
        detector = TerminologyDetector(rules)
        detected = detector.detect("Aspose for .NET")

        # All detections should have confidence 1.0
        assert all(d.confidence == 1.0 for d in detected)

    def test_zero_width_pattern_handled(self):
        """Test that zero-width patterns don't cause infinite loops."""
        rule = TermRule(
            pattern=r"\b",  # Zero-width word boundary
            category="test",
            preserve_mode=PreserveMode.PROTECT,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        # This should complete without hanging
        detected = detector.detect("test")
        # Zero-width matches are technically valid but not useful
        assert isinstance(detected, list)

    def test_word_boundary_char_before_blocks_match(self):
        """Test that alphanumeric character before match blocks detection."""
        rule = TermRule(
            term="pose",
            category="test",
            preserve_mode=PreserveMode.BOTH,
            severity=TermSeverity.ERROR
        )
        detector = TerminologyDetector([rule])
        detected = detector.detect("Aspose")  # "pose" is preceded by "As"

        # Should not match "pose" within "Aspose" due to word boundary
        assert len(detected) == 0
