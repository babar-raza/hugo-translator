"""
Unit tests for CompletenessValidator.

Tests cover:
- 100% translation coverage (all segments translated)
- Missing segment detection (source segments without translations)
- Empty translation detection (empty string translations)
- Untranslated placeholder detection ({PLACEHOLDER_X}, {TERM_X}, {SHORTCODE_X})
- Partial coverage scenarios (50%, 75%)
- Edge cases (0 segments, all empty)
"""

import pytest

from src.translation_engine.validation.completeness_validator import (
    CompletenessValidator,
)
from src.translation_engine.validation.base import ValidationSeverity


class TestCompletenessValidator:
    """Test suite for CompletenessValidator."""

    def setup_method(self):
        """Set up test fixtures."""
        self.validator = CompletenessValidator()

    def test_all_segments_translated(self):
        """Test successful validation when all segments are translated."""
        context = {
            "source_segments": ["Hello", "World"],
            "translation_map": {0: "Hola", 1: "Mundo"},
        }
        result = self.validator.validate("Hello World", "Hola Mundo", context)

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["coverage_percent"] == 100.0
        assert result.error_count == 0

    def test_missing_segment(self):
        """Test detection of missing segment in translation map."""
        context = {
            "source_segments": ["Hello", "World"],
            "translation_map": {0: "Hola"},  # Segment 1 missing
        }
        result = self.validator.validate("Hello World", "Hola", context)

        assert result.success is False
        assert result.error_count == 1
        assert len(result.issues) == 1

        issue = result.issues[0]
        assert issue.severity == ValidationSeverity.ERROR
        assert issue.validator == "CompletenessValidator"
        assert "Segment 1 not translated" in issue.message
        assert issue.location == "segment_1"
        assert "Ensure all segments passed to translation model" in issue.details["suggestion"]

    def test_empty_translation(self):
        """Test detection of empty translation for a segment."""
        context = {
            "source_segments": ["Hello", "World"],
            "translation_map": {0: "Hola", 1: ""},  # Segment 1 is empty
        }
        result = self.validator.validate("Hello World", "Hola", context)

        assert result.success is False
        assert result.error_count == 1

        issue = result.issues[0]
        assert issue.severity == ValidationSeverity.ERROR
        assert "Segment 1 has empty translation" in issue.message
        assert issue.location == "segment_1"
        assert "Translation must not be empty" in issue.details["suggestion"]

    def test_whitespace_only_translation(self):
        """Test detection of whitespace-only translation."""
        context = {
            "source_segments": ["Hello", "World"],
            "translation_map": {0: "Hola", 1: "   "},  # Only whitespace
        }
        result = self.validator.validate("Hello World", "Hola   ", context)

        assert result.success is False
        assert result.error_count == 1

        issue = result.issues[0]
        assert "Segment 1 has empty translation" in issue.message

    def test_untranslated_placeholder(self):
        """Test detection of untranslated PLACEHOLDER marker."""
        context = {
            "source_segments": ["Hello"],
            "translation_map": {0: "Hola"},
        }
        translation = "Hola {PLACEHOLDER_0}"
        result = self.validator.validate("Hello", translation, context)

        assert result.success is False
        assert result.error_count == 1

        issue = result.issues[0]
        assert issue.severity == ValidationSeverity.ERROR
        assert "Found 1 untranslated placeholders" in issue.message
        assert issue.location == "translation_output"
        assert "{PLACEHOLDER_0}" in str(issue.details["suggestion"])

    def test_untranslated_term_placeholder(self):
        """Test detection of untranslated TERM marker."""
        context = {
            "source_segments": ["Technical term"],
            "translation_map": {0: "Technical term"},
        }
        translation = "Technical {TERM_5} here"
        result = self.validator.validate("Technical term", translation, context)

        assert result.success is False
        assert result.error_count == 1

        issue = result.issues[0]
        assert "Found 1 untranslated placeholders" in issue.message
        assert "{TERM_5}" in str(issue.details["suggestion"])

    def test_untranslated_shortcode_placeholder(self):
        """Test detection of untranslated SHORTCODE marker."""
        context = {
            "source_segments": ["Some text"],
            "translation_map": {0: "Algún texto"},
        }
        translation = "Algún texto {SHORTCODE_123}"
        result = self.validator.validate("Some text", translation, context)

        assert result.success is False
        assert result.error_count == 1

        issue = result.issues[0]
        assert "Found 1 untranslated placeholders" in issue.message
        assert "{SHORTCODE_123}" in str(issue.details["suggestion"])

    def test_multiple_untranslated_placeholders(self):
        """Test detection of multiple untranslated placeholders."""
        context = {
            "source_segments": ["Text with placeholders"],
            "translation_map": {0: "Texto con placeholders"},
        }
        translation = (
            "Texto {PLACEHOLDER_0} con {TERM_1} varios {SHORTCODE_2} marcadores"
        )
        result = self.validator.validate("Text with placeholders", translation, context)

        assert result.success is False
        assert result.error_count == 1

        issue = result.issues[0]
        assert "Found 3 untranslated placeholders" in issue.message
        assert issue.details["untranslated_count"] == 3

    def test_placeholder_sample_limit(self):
        """Test that placeholder suggestion shows max 5 placeholders."""
        context = {
            "source_segments": ["Text"],
            "translation_map": {0: "Text"},
        }
        # Create translation with 7 placeholders
        translation = " ".join([f"{{PLACEHOLDER_{i}}}" for i in range(7)])
        result = self.validator.validate("Text", translation, context)

        assert result.success is False
        issue = result.issues[0]
        # Should show first 5 placeholders only
        suggestion = issue.details["suggestion"]
        assert "PLACEHOLDER_0" in suggestion
        assert "PLACEHOLDER_4" in suggestion
        # Count total untranslated
        assert issue.details["untranslated_count"] == 7

    def test_partial_coverage_50_percent(self):
        """Test partial translation coverage (50%)."""
        context = {
            "source_segments": ["One", "Two", "Three", "Four"],
            "translation_map": {0: "Uno", 1: "Dos"},  # Only 2 of 4 translated
        }
        result = self.validator.validate("One Two Three Four", "Uno Dos", context)

        assert result.success is False
        assert result.error_count == 2  # 2 missing segments
        assert result.metadata["coverage_percent"] == 50.0

    def test_partial_coverage_75_percent(self):
        """Test partial translation coverage (75%)."""
        context = {
            "source_segments": ["One", "Two", "Three", "Four"],
            "translation_map": {
                0: "Uno",
                1: "Dos",
                2: "Tres",
            },  # 3 of 4 translated
        }
        result = self.validator.validate(
            "One Two Three Four", "Uno Dos Tres", context
        )

        assert result.success is False
        assert result.error_count == 1  # 1 missing segment
        assert result.metadata["coverage_percent"] == 75.0

    def test_zero_segments(self):
        """Test edge case with zero segments."""
        context = {
            "source_segments": [],
            "translation_map": {},
        }
        result = self.validator.validate("", "", context)

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["coverage_percent"] == 0.0

    def test_all_segments_empty_translations(self):
        """Test edge case where all segments have empty translations."""
        context = {
            "source_segments": ["One", "Two"],
            "translation_map": {0: "", 1: ""},
        }
        result = self.validator.validate("One Two", "", context)

        assert result.success is False
        assert result.error_count == 2
        assert result.metadata["coverage_percent"] == 0.0

    def test_mixed_failures(self):
        """Test multiple failure types simultaneously."""
        context = {
            "source_segments": ["One", "Two", "Three"],
            "translation_map": {
                0: "Uno",
                1: "",  # Empty translation
                # Segment 2 missing entirely
            },
        }
        translation = "Uno {PLACEHOLDER_0}"  # Plus untranslated placeholder
        result = self.validator.validate("One Two Three", translation, context)

        assert result.success is False
        # Should have 3 errors: empty translation, missing segment, untranslated placeholder
        assert result.error_count == 3

        # Verify each error type is present
        messages = [issue.message for issue in result.issues]
        assert any("empty translation" in msg for msg in messages)
        assert any("not translated" in msg for msg in messages)
        assert any("untranslated placeholders" in msg for msg in messages)

    def test_empty_context(self):
        """Test validation with empty context."""
        result = self.validator.validate("Hello", "Hola", {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["coverage_percent"] == 0.0

    def test_none_context(self):
        """Test validation with None context."""
        result = self.validator.validate("Hello", "Hola", None)

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["coverage_percent"] == 0.0

    def test_missing_translation_map_in_context(self):
        """Test when translation_map is missing from context."""
        context = {
            "source_segments": ["Hello", "World"],
            # translation_map missing
        }
        result = self.validator.validate("Hello World", "Hola Mundo", context)

        assert result.success is False
        assert result.error_count == 2  # Both segments missing from empty map

    def test_missing_source_segments_in_context(self):
        """Test when source_segments is missing from context."""
        context = {
            "translation_map": {0: "Hola", 1: "Mundo"},
            # source_segments missing
        }
        result = self.validator.validate("Hello World", "Hola Mundo", context)

        assert result.success is True  # No segments to check
        assert result.metadata["coverage_percent"] == 0.0

    def test_coverage_with_one_empty_one_valid(self):
        """Test coverage calculation with mix of empty and valid translations."""
        context = {
            "source_segments": ["One", "Two"],
            "translation_map": {0: "Uno", 1: ""},  # One valid, one empty
        }
        result = self.validator.validate("One Two", "Uno", context)

        assert result.success is False
        assert result.metadata["coverage_percent"] == 50.0  # Only 1 of 2 is non-empty

    def test_validator_name(self):
        """Test that all issues have correct validator name."""
        context = {
            "source_segments": ["Hello"],
            "translation_map": {},
        }
        result = self.validator.validate("Hello", "", context)

        assert result.success is False
        for issue in result.issues:
            assert issue.validator == "CompletenessValidator"

    def test_placeholder_pattern_precision(self):
        """Test that placeholder pattern only matches expected formats."""
        context = {
            "source_segments": ["Text"],
            "translation_map": {0: "Text"},
        }

        # Should NOT match these:
        translation_valid = "Text with {INVALID} or {PLACEHOLDER} or {123}"
        result = self.validator.validate("Text", translation_valid, context)
        assert result.success is True  # No errors for invalid formats

        # SHOULD match these:
        translation_invalid = "Text {PLACEHOLDER_1} {TERM_2} {SHORTCODE_3}"
        result = self.validator.validate("Text", translation_invalid, context)
        assert result.success is False
        assert result.error_count == 1
        assert "Found 3 untranslated placeholders" in result.issues[0].message

    def test_large_segment_ids(self):
        """Test with large segment IDs to ensure no integer overflow."""
        context = {
            "source_segments": ["Text"] * 1000,
            "translation_map": {i: f"Translation {i}" for i in range(1000)},
        }
        result = self.validator.validate("Text", "Translation", context)

        assert result.success is True
        assert result.metadata["coverage_percent"] == 100.0

    def test_coverage_precision(self):
        """Test that coverage percentage is calculated with precision."""
        context = {
            "source_segments": ["One", "Two", "Three"],
            "translation_map": {0: "Uno", 1: "Dos"},  # 2 of 3
        }
        result = self.validator.validate("Text", "Translation", context)

        # 2/3 = 66.666...
        assert result.metadata["coverage_percent"] == pytest.approx(66.666666, rel=1e-5)
