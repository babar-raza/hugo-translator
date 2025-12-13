"""
Unit tests for ShortcodePreservationValidator.

Tests cover:
- Happy path: All shortcodes preserved
- Missing shortcode detection
- Extra shortcode detection (warning)
- Count mismatch detection
- All shortcode types: {{< >}}, {{% %}}, {{/* */}}
- Edge cases: whitespace normalization, multiple shortcodes, nested content
"""

import pytest
from typing import Any, Dict, Optional

from src.translation_engine.validation.shortcode_preservation_validator import (
    ShortcodePreservationValidator,
)
from src.translation_engine.validation.base import (
    ValidationResult,
    ValidationSeverity,
)


class TestShortcodePreservationValidator:
    """Test suite for ShortcodePreservationValidator."""

    @pytest.fixture
    def validator(self) -> ShortcodePreservationValidator:
        """Create validator instance for testing."""
        return ShortcodePreservationValidator()

    # Happy path tests

    def test_shortcodes_preserved_single_angle_bracket(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that single {{< >}} shortcode is preserved correctly."""
        source = "Text {{< gist abc123 >}} more text"
        translation = "Texto {{< gist abc123 >}} más texto"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 1
        assert result.metadata["translation_shortcode_count"] == 1

    def test_shortcodes_preserved_single_percent(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that single {{% %}} shortcode is preserved correctly."""
        source = "Text {{% note %}} content {{% /note %}} more"
        translation = "Texto {{% note %}} contenido {{% /note %}} más"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 2
        assert result.metadata["translation_shortcode_count"] == 2

    def test_shortcodes_preserved_comment(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that {{/* */}} comment shortcode is preserved correctly."""
        source = "Text {{/* this is a comment */}} more text"
        translation = "Texto {{/* this is a comment */}} más texto"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 1
        assert result.metadata["translation_shortcode_count"] == 1

    def test_all_shortcode_types_together(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test all shortcode types in same text: {{< >}}, {{% %}}, {{/* */}}."""
        source = """
        Text {{< gist abc123 >}} some content
        {{% note %}}Important{{% /note %}}
        {{/* internal comment */}}
        More text {{< figure src="image.jpg" >}}
        """
        translation = """
        Texto {{< gist abc123 >}} algún contenido
        {{% note %}}Importante{{% /note %}}
        {{/* internal comment */}}
        Más texto {{< figure src="image.jpg" >}}
        """

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 5
        assert result.metadata["translation_shortcode_count"] == 5

    def test_shortcodes_preserved_with_whitespace_normalization(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that shortcodes with different whitespace are normalized and matched."""
        source = "Text {{<  gist   abc123  >}} more"
        translation = "Texto {{< gist abc123 >}} más"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0

    def test_no_shortcodes_in_either(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that text without shortcodes passes validation."""
        source = "Just plain text without any shortcodes"
        translation = "Solo texto plano sin ningún shortcode"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 0
        assert result.metadata["translation_shortcode_count"] == 0

    def test_multiple_identical_shortcodes_preserved(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that multiple identical shortcodes are all preserved."""
        source = "{{< icon star >}} Rating {{< icon star >}} {{< icon star >}}"
        translation = "{{< icon star >}} Calificación {{< icon star >}} {{< icon star >}}"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 3
        assert result.metadata["translation_shortcode_count"] == 3

    # Failure tests - Missing shortcode

    def test_missing_shortcode_error(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that missing shortcode in translation produces ERROR."""
        source = "Text {{< gist abc123 >}} more text"
        translation = "Texto más texto"  # Missing shortcode

        result = validator.validate(source, translation, {})

        assert result.success is False
        assert len(result.issues) == 2  # Count mismatch + missing shortcode

        # Check for missing shortcode error
        missing_errors = [
            i for i in result.issues
            if "missing" in i.message.lower() and i.severity == ValidationSeverity.ERROR
        ]
        assert len(missing_errors) == 1
        assert "{{< gist abc123 >}}" in missing_errors[0].message

    def test_missing_one_of_multiple_shortcodes(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that missing one shortcode when multiple exist produces ERROR."""
        source = "{{< a >}} text {{< b >}} more {{< c >}}"
        translation = "{{< a >}} texto más {{< c >}}"  # Missing {{< b >}}

        result = validator.validate(source, translation, {})

        assert result.success is False

        # Check for missing shortcode error
        missing_errors = [
            i for i in result.issues
            if "missing" in i.message.lower() and i.severity == ValidationSeverity.ERROR
        ]
        assert len(missing_errors) == 1
        assert "{{< b >}}" in missing_errors[0].message

    def test_missing_closing_tag(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that missing closing tag produces ERROR."""
        source = "{{% note %}}Content{{% /note %}}"
        translation = "{{% note %}}Contenido"  # Missing closing tag

        result = validator.validate(source, translation, {})

        assert result.success is False
        assert len(result.issues) >= 1

        error_issues = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(error_issues) >= 1

    # Failure tests - Extra shortcode

    def test_extra_shortcode_warning(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that extra shortcode in translation produces WARNING."""
        source = "Text without shortcode"
        translation = "Texto {{< extra >}} con shortcode"  # Extra shortcode

        result = validator.validate(source, translation, {})

        # Success should be True (warnings don't fail validation)
        assert result.success is True
        assert len(result.issues) == 1  # Only unexpected shortcode warning

        # Check for unexpected shortcode warning
        warnings = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]
        assert len(warnings) == 1
        assert "unexpected" in warnings[0].message.lower()
        assert "{{< extra >}}" in warnings[0].message

    def test_extra_shortcode_added_to_existing(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that adding extra shortcode to existing ones produces WARNING."""
        source = "Text {{< a >}} more"
        translation = "Texto {{< a >}} más {{< b >}}"  # Added {{< b >}}

        result = validator.validate(source, translation, {})

        # Success should be True (warnings don't fail)
        assert result.success is True

        warnings = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]
        assert len(warnings) == 1
        assert "{{< b >}}" in warnings[0].message

    # Failure tests - Count mismatch

    def test_count_mismatch_fewer_in_translation(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that fewer shortcodes in translation produces ERROR."""
        source = "{{< a >}} {{< a >}} {{< a >}}"
        translation = "{{< a >}}"  # Only one instead of three

        result = validator.validate(source, translation, {})

        assert result.success is False

        # Should have count mismatch error and count reduced error
        error_issues = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(error_issues) >= 1

        # Check for count error message
        count_errors = [i for i in error_issues if "count" in i.message.lower()]
        assert len(count_errors) >= 1

    def test_count_mismatch_more_in_translation(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that more shortcodes in translation produces ERROR and WARNING."""
        source = "{{< a >}}"
        translation = "{{< a >}} {{< b >}} {{< c >}}"  # Three instead of one

        result = validator.validate(source, translation, {})

        # Should fail due to count mismatch
        assert result.success is True  # Warnings don't fail validation

        # Should have warnings for extra shortcodes
        warnings = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]
        assert len(warnings) >= 2  # {{< b >}} and {{< c >}} are unexpected

    def test_count_reduced_for_same_shortcode(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that reducing count of same shortcode produces specific ERROR."""
        source = "{{< icon star >}} {{< icon star >}} {{< icon star >}}"
        translation = "{{< icon star >}}"  # Only one instead of three

        result = validator.validate(source, translation, {})

        assert result.success is False

        # Should have count reduced error
        reduced_errors = [
            i for i in result.issues
            if "count reduced" in i.message.lower() and i.severity == ValidationSeverity.ERROR
        ]
        assert len(reduced_errors) == 1
        assert "3" in reduced_errors[0].message  # Source count
        assert "1" in reduced_errors[0].message  # Translation count

    # Edge cases

    def test_shortcode_with_parameters(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test shortcodes with parameters are preserved."""
        source = '{{< figure src="image.jpg" title="My Title" >}}'
        translation = '{{< figure src="image.jpg" title="My Title" >}}'

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert len(result.issues) == 0

    def test_shortcode_with_newlines(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test shortcodes with newlines are handled correctly."""
        source = """{{< figure
            src="image.jpg"
            title="Title" >}}"""
        translation = "{{< figure src=\"image.jpg\" title=\"Title\" >}}"

        result = validator.validate(source, translation, {})

        # Should pass due to whitespace normalization
        assert result.success is True

    def test_shortcode_in_code_block_not_extracted(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that shortcodes in text are extracted regardless of markdown context.

        Note: This validator extracts ALL shortcode patterns from text.
        It doesn't parse markdown structure to distinguish code blocks.
        This is intentional - if a shortcode pattern appears anywhere,
        it should be preserved in translation.
        """
        source = "Text {{< shortcode >}} more"
        translation = "Texto {{< shortcode >}} más"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert result.metadata["source_shortcode_count"] == 1
        assert result.metadata["translation_shortcode_count"] == 1

    def test_empty_source_and_translation(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test empty strings pass validation."""
        result = validator.validate("", "", {})

        assert result.success is True
        assert len(result.issues) == 0
        assert result.metadata["source_shortcode_count"] == 0
        assert result.metadata["translation_shortcode_count"] == 0

    def test_validation_with_context(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that validator accepts context parameter (even if unused)."""
        source = "{{< test >}}"
        translation = "{{< test >}}"
        context = {"file_path": "test.md", "language": "es"}

        result = validator.validate(source, translation, context)

        assert result.success is True

    def test_validation_without_context(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that validator works without context parameter."""
        source = "{{< test >}}"
        translation = "{{< test >}}"

        result = validator.validate(source, translation, None)

        assert result.success is True

    def test_complex_shortcode_with_closing_tag(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test paired shortcodes with opening and closing tags."""
        source = "{{< highlight python >}}code here{{< /highlight >}}"
        translation = "{{< highlight python >}}código aquí{{< /highlight >}}"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert result.metadata["source_shortcode_count"] == 2
        assert result.metadata["translation_shortcode_count"] == 2

    def test_mixed_quote_styles_in_parameters(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test shortcodes with mixed quote styles in parameters."""
        source = """{{< figure src='image.jpg' title="My Title" >}}"""
        translation = """{{< figure src='image.jpg' title="My Title" >}}"""

        result = validator.validate(source, translation, {})

        assert result.success is True

    def test_multiline_comment(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test multiline comment shortcode."""
        source = """Text {{/* This is a
        multiline comment
        spanning several lines */}} more"""
        translation = """Texto {{/* This is a
        multiline comment
        spanning several lines */}} más"""

        result = validator.validate(source, translation, {})

        assert result.success is True

    def test_shortcode_at_start_of_text(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test shortcode at the very start of text."""
        source = "{{< banner >}}Text after"
        translation = "{{< banner >}}Texto después"

        result = validator.validate(source, translation, {})

        assert result.success is True

    def test_shortcode_at_end_of_text(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test shortcode at the very end of text."""
        source = "Text before {{< end >}}"
        translation = "Texto antes {{< end >}}"

        result = validator.validate(source, translation, {})

        assert result.success is True

    def test_consecutive_shortcodes(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test multiple shortcodes with no text between them."""
        source = "{{< a >}}{{< b >}}{{< c >}}"
        translation = "{{< a >}}{{< b >}}{{< c >}}"

        result = validator.validate(source, translation, {})

        assert result.success is True
        assert result.metadata["source_shortcode_count"] == 3
        assert result.metadata["translation_shortcode_count"] == 3


class TestShortcodeExtraction:
    """Test suite for _extract_shortcodes internal method."""

    @pytest.fixture
    def validator(self) -> ShortcodePreservationValidator:
        """Create validator instance for testing."""
        return ShortcodePreservationValidator()

    def test_extract_angle_bracket_shortcode(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test extraction of {{< >}} shortcode."""
        text = "Text {{< gist abc123 >}} more"
        shortcodes = validator._extract_shortcodes(text)

        assert len(shortcodes) == 1
        assert shortcodes[0] == "{{< gist abc123 >}}"

    def test_extract_percent_shortcode(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test extraction of {{% %}} shortcode."""
        text = "Text {{% note %}} more"
        shortcodes = validator._extract_shortcodes(text)

        assert len(shortcodes) == 1
        assert shortcodes[0] == "{{% note %}}"

    def test_extract_comment_shortcode(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test extraction of {{/* */}} shortcode."""
        text = "Text {{/* comment */}} more"
        shortcodes = validator._extract_shortcodes(text)

        assert len(shortcodes) == 1
        assert shortcodes[0] == "{{/* comment */}}"

    def test_extract_multiple_types(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test extraction of multiple shortcode types."""
        text = "{{< a >}} {{% b %}} {{/* c */}}"
        shortcodes = validator._extract_shortcodes(text)

        assert len(shortcodes) == 3
        assert "{{< a >}}" in shortcodes
        assert "{{% b %}}" in shortcodes
        assert "{{/* c */}}" in shortcodes

    def test_extract_with_whitespace_normalization(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that whitespace is normalized in extracted shortcodes."""
        text = "{{<  multiple   spaces  >}}"
        shortcodes = validator._extract_shortcodes(text)

        assert len(shortcodes) == 1
        # Whitespace should be normalized to single spaces
        assert shortcodes[0] == "{{< multiple spaces >}}"

    def test_extract_empty_string(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test extraction from empty string."""
        shortcodes = validator._extract_shortcodes("")

        assert len(shortcodes) == 0
        assert shortcodes == []

    def test_extract_no_shortcodes(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test extraction from text without shortcodes."""
        text = "Just plain text without any shortcodes"
        shortcodes = validator._extract_shortcodes(text)

        assert len(shortcodes) == 0


class TestValidationResultStructure:
    """Test suite for ValidationResult structure and metadata."""

    @pytest.fixture
    def validator(self) -> ShortcodePreservationValidator:
        """Create validator instance for testing."""
        return ShortcodePreservationValidator()

    def test_result_has_correct_structure(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that ValidationResult has correct structure."""
        source = "{{< test >}}"
        translation = "{{< test >}}"

        result = validator.validate(source, translation, {})

        assert isinstance(result, ValidationResult)
        assert hasattr(result, "success")
        assert hasattr(result, "issues")
        assert hasattr(result, "metadata")

    def test_result_metadata_contains_counts(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that metadata contains shortcode counts."""
        source = "{{< a >}} {{< b >}}"
        translation = "{{< a >}} {{< b >}}"

        result = validator.validate(source, translation, {})

        assert "source_shortcode_count" in result.metadata
        assert "translation_shortcode_count" in result.metadata
        assert result.metadata["source_shortcode_count"] == 2
        assert result.metadata["translation_shortcode_count"] == 2

    def test_issues_have_correct_fields(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that issues have all required fields."""
        source = "{{< test >}}"
        translation = ""  # Missing shortcode

        result = validator.validate(source, translation, {})

        assert len(result.issues) > 0
        for issue in result.issues:
            assert hasattr(issue, "validator")
            assert hasattr(issue, "severity")
            assert hasattr(issue, "message")
            assert hasattr(issue, "location")
            assert issue.validator == "ShortcodePreservationValidator"
            assert issue.location == "shortcodes"

    def test_error_severity_for_missing_shortcode(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that missing shortcode has ERROR severity."""
        source = "{{< test >}}"
        translation = ""

        result = validator.validate(source, translation, {})

        error_issues = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(error_issues) > 0

    def test_warning_severity_for_extra_shortcode(
        self, validator: ShortcodePreservationValidator
    ) -> None:
        """Test that extra shortcode has WARNING severity."""
        source = ""
        translation = "{{< test >}}"

        result = validator.validate(source, translation, {})

        warning_issues = [i for i in result.issues if i.severity == ValidationSeverity.WARNING]
        assert len(warning_issues) > 0
