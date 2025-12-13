"""
Unit tests for placeholder validator.
"""

import pytest

from src.translation_engine.validation import (
    PlaceholderValidator,
    ValidationSeverity,
)


class TestPlaceholderValidator:
    """Test PlaceholderValidator."""

    @pytest.fixture
    def validator(self):
        """Create placeholder validator."""
        return PlaceholderValidator()

    def test_no_placeholders(self, validator):
        """Test with no placeholders."""
        source = "This is a simple text"
        translation = "Ceci est un texte simple"

        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0

    def test_matching_placeholders(self, validator):
        """Test with matching placeholders."""
        source = "Click {{LINK_1}} to read {{CODE_2}}"
        translation = "Cliquez sur {{LINK_1}} pour lire {{CODE_2}}"

        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0

    def test_missing_placeholders(self, validator):
        """Test with missing placeholders in translation."""
        source = "Click {{LINK_1}} to read {{CODE_2}}"
        translation = "Cliquez sur {{LINK_1}} pour lire"

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count > 0
        assert any("missing" in issue.message.lower() for issue in result.issues)
        assert any("CODE_2" in str(issue.details) for issue in result.issues if issue.details)

    def test_extra_placeholders(self, validator):
        """Test with extra placeholders in translation."""
        source = "Click {{LINK_1}}"
        translation = "Cliquez sur {{LINK_1}} et {{LINK_2}}"

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count > 0
        assert any("extra" in issue.message.lower() for issue in result.issues)

    def test_placeholder_order_strict(self):
        """Test placeholder order with strict checking."""
        validator = PlaceholderValidator(strict_order=True)

        source = "First {{CODE_1}} then {{LINK_2}}"
        translation = "D'abord {{LINK_2}} puis {{CODE_1}}"

        result = validator.validate(source, translation)

        # Should have warning about order
        assert result.warning_count > 0
        assert any("order" in issue.message.lower() for issue in result.issues)

    def test_placeholder_order_not_strict(self):
        """Test placeholder order without strict checking."""
        validator = PlaceholderValidator(strict_order=False)

        source = "First {{CODE_1}} then {{LINK_2}}"
        translation = "D'abord {{LINK_2}} puis {{CODE_1}}"

        result = validator.validate(source, translation)

        # Should not have order warning
        assert not any("order" in issue.message.lower() for issue in result.issues)

    def test_frequency_mismatch(self, validator):
        """Test placeholder frequency mismatch."""
        source = "Use {{CODE_1}} and {{CODE_1}} again"
        translation = "Utilisez {{CODE_1}} une fois"

        result = validator.validate(source, translation)

        # Should have warning about frequency
        assert result.warning_count > 0
        assert any("frequency" in issue.message.lower() for issue in result.issues)

    def test_multiple_placeholder_types(self, validator):
        """Test with multiple placeholder types."""
        source = "Check {{LINK_1}}, {{CODE_2}}, and {{SHORTCODE_3}}"
        translation = "Vérifiez {{LINK_1}}, {{CODE_2}}, et {{SHORTCODE_3}}"

        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0

    def test_custom_placeholder_pattern(self):
        """Test with custom placeholder pattern."""
        # Use different pattern: [[TYPE_NUM]]
        validator = PlaceholderValidator(
            placeholder_pattern=r"\[\[([A-Z_]+)_(\d+)\]\]"
        )

        source = "Click [[LINK_1]] to read [[CODE_2]]"
        translation = "Cliquez sur [[LINK_1]] pour lire [[CODE_2]]"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_placeholder_at_boundaries(self, validator):
        """Test placeholders at text boundaries."""
        source = "{{CODE_1}} starts and ends {{CODE_2}}"
        translation = "{{CODE_1}} commence et finit {{CODE_2}}"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_adjacent_placeholders(self, validator):
        """Test adjacent placeholders."""
        source = "{{CODE_1}}{{CODE_2}}"
        translation = "{{CODE_1}}{{CODE_2}}"

        result = validator.validate(source, translation)

        assert result.success is True
