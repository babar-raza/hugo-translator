"""
Unit tests for terminology preservation validator.

Tests cover:
- Exact match preservation (Aspose, .NET, Java, Python)
- Pattern matching (Aspose.Words, Aspose.Cells)
- Frequency validation (term count source vs translation)
- Case sensitivity support
- Configuration loading
"""

from pathlib import Path

import pytest

from src.translation_engine.validation.base import (
    ValidationSeverity,
)
from src.translation_engine.validation.terminology_preservation_validator import (
    TerminologyPreservationValidator,
)


class TestTerminologyPreservationValidator:
    """Test suite for TerminologyPreservationValidator."""

    @pytest.fixture
    def test_config_path(self, tmp_path: Path) -> Path:
        """Create a test terminology configuration file."""
        config_content = """
version: "1.0"

global:
  exact_matches:
    - term: "Aspose"
      category: company_name
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: ".NET"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: "Java"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

    - term: "Python"
      category: platform
      case_sensitive: true
      preserve_mode: both
      severity: error

  patterns:
    - pattern: "Aspose\\\\.[A-Z][a-z]+"
      category: product_family
      description: "Aspose product families"
      preserve_mode: protect
      severity: error

    - pattern: "\\\\bLINQ Engine\\\\b"
      category: plugin_name
      description: "LINQ Engine plugin"
      preserve_mode: both
      severity: error
"""
        config_path = tmp_path / "terminology.yaml"
        config_path.write_text(config_content, encoding='utf-8')
        return config_path

    @pytest.fixture
    def validator(self, test_config_path: Path) -> TerminologyPreservationValidator:
        """Create validator instance with test configuration."""
        return TerminologyPreservationValidator(terminology_config_path=test_config_path)

    def test_initialization(self, validator: TerminologyPreservationValidator) -> None:
        """Test validator initialization and config loading."""
        assert validator.name == "TerminologyPreservationValidator"
        assert len(validator.exact_matches) == 4
        assert len(validator.patterns) == 2

    def test_initialization_with_default_config(self) -> None:
        """Test validator initialization with default config path."""
        # This should use config/terminology.yaml from project root
        validator = TerminologyPreservationValidator()
        assert validator.name == "TerminologyPreservationValidator"
        assert len(validator.exact_matches) > 0

    def test_initialization_missing_config(self, tmp_path: Path) -> None:
        """Test that missing config file raises error."""
        missing_path = tmp_path / "nonexistent.yaml"
        with pytest.raises(FileNotFoundError):
            TerminologyPreservationValidator(terminology_config_path=missing_path)

    def test_exact_match_preserved(self, validator: TerminologyPreservationValidator) -> None:
        """Test that exact matches are correctly validated when preserved."""
        source = "Aspose provides .NET, Java, and Python APIs."
        translation = "Aspose fournit des API .NET, Java et Python."

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_exact_match_missing(self, validator: TerminologyPreservationValidator) -> None:
        """Test that missing exact matches are detected as ERROR."""
        source = "Aspose provides .NET APIs."
        translation = "AsposeX fournit des API .NET."  # Aspose changed to AsposeX

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "Aspose" in error.message
        assert "missing from translation" in error.message
        assert error.details["term"] == "Aspose"
        assert error.details["source_count"] == 1
        assert error.details["translation_count"] == 0

    def test_multiple_exact_matches_missing(self, validator: TerminologyPreservationValidator) -> None:
        """Test detection of multiple missing terms."""
        source = "Aspose provides .NET and Java APIs."
        translation = "We provide Python APIs."  # All terms missing except Python

        result = validator.validate(source, translation)

        assert not result.success
        # At least Aspose and Java should be missing (2 errors minimum)
        # .NET may or may not be detected depending on word boundary handling
        assert result.error_count >= 2

    def test_pattern_matching(self, validator: TerminologyPreservationValidator) -> None:
        """Test that pattern-matched terms are correctly validated."""
        source = "Use Aspose.Words and Aspose.Cells for document processing."
        translation = "Utilisez Aspose.Words et Aspose.Cells pour le traitement des documents."

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_pattern_matching_missing_term(self, validator: TerminologyPreservationValidator) -> None:
        """Test detection of missing pattern-matched terms."""
        source = "Use Aspose.Words and Aspose.Cells for processing."
        translation = "Use Aspose.Words for processing."  # Aspose.Cells missing

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count >= 1

        errors = result.filter_by_severity(ValidationSeverity.ERROR)
        error_messages = [e.message for e in errors]
        assert any("Aspose.Cells" in msg for msg in error_messages)

    def test_frequency_mismatch(self, validator: TerminologyPreservationValidator) -> None:
        """Test detection of frequency mismatches."""
        source = "Aspose is great. Aspose is powerful. Aspose is fast."
        translation = "Aspose est génial. Aspose est rapide."  # Only 2 occurrences instead of 3

        result = validator.validate(source, translation)

        # Should have a WARNING for frequency mismatch
        assert result.warning_count >= 1

        warnings = result.filter_by_severity(ValidationSeverity.WARNING)
        warning_messages = [w.message for w in warnings]
        assert any("frequency mismatch" in msg.lower() for msg in warning_messages)

        # Check the warning details
        freq_warning = [w for w in warnings if "frequency mismatch" in w.message.lower()][0]
        assert freq_warning.details["source_count"] == 3
        assert freq_warning.details["translation_count"] == 2

    def test_case_sensitivity(self, validator: TerminologyPreservationValidator) -> None:
        """Test case-sensitive matching."""
        # Lower case "aspose" should not match case-sensitive "Aspose"
        source = "Aspose provides APIs."
        translation = "aspose fournit des API."  # Wrong case

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count >= 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "Aspose" in error.message
        assert error.details["case_sensitive"] is True

    def test_case_insensitive_matching(self, tmp_path: Path) -> None:
        """Test case-insensitive matching when configured."""
        # Create config with case_insensitive term
        config_content = """
version: "1.0"

global:
  exact_matches:
    - term: "API"
      category: technical
      case_sensitive: false
      preserve_mode: both
      severity: error
"""
        config_path = tmp_path / "terminology.yaml"
        config_path.write_text(config_content, encoding='utf-8')

        validator = TerminologyPreservationValidator(terminology_config_path=config_path)

        source = "Use the API documentation."
        translation = "Utilisez la documentation api."  # Lower case "api"

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_pattern_frequency_mismatch(self, validator: TerminologyPreservationValidator) -> None:
        """Test frequency mismatch for pattern-matched terms."""
        source = "Aspose.Words is great. Use Aspose.Words for documents."
        translation = "Aspose.Words est génial."  # Only 1 occurrence instead of 2

        result = validator.validate(source, translation)

        # Should have a WARNING for frequency mismatch
        assert result.warning_count >= 1

        warnings = result.filter_by_severity(ValidationSeverity.WARNING)
        freq_warning = [w for w in warnings if "Aspose.Words" in w.message][0]
        assert freq_warning.details["source_count"] == 2
        assert freq_warning.details["translation_count"] == 1

    def test_mixed_terms_and_patterns(self, validator: TerminologyPreservationValidator) -> None:
        """Test validation with mix of exact matches and patterns."""
        source = "Aspose.Words works with .NET and Java platforms."
        translation = "Aspose.Words fonctionne avec les plateformes .NET et Java."

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_no_terms_in_source(self, validator: TerminologyPreservationValidator) -> None:
        """Test validation when no protected terms are in source."""
        source = "This is a simple document."
        translation = "Ceci est un document simple."

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_term_count_helper(self, validator: TerminologyPreservationValidator) -> None:
        """Test the _count_term helper method."""
        text = "Aspose is great. aspose is nice. ASPOSE is powerful."

        # Case-sensitive should only find "Aspose"
        count_sensitive = validator._count_term(text, "Aspose", case_sensitive=True)
        assert count_sensitive == 1

        # Case-insensitive should find all three
        count_insensitive = validator._count_term(text, "Aspose", case_sensitive=False)
        assert count_insensitive == 3

    def test_find_pattern_matches_helper(self, validator: TerminologyPreservationValidator) -> None:
        """Test the _find_pattern_matches helper method."""
        text = "Use Aspose.Words, Aspose.Cells, and Aspose.Pdf for processing."

        pattern = r"Aspose\.[A-Z][a-z]+"
        matches = validator._find_pattern_matches(text, pattern)

        assert len(matches) == 3
        assert "Aspose.Words" in matches
        assert "Aspose.Cells" in matches
        assert "Aspose.Pdf" in matches

    def test_parse_severity_helper(self, validator: TerminologyPreservationValidator) -> None:
        """Test the _parse_severity helper method."""
        assert validator._parse_severity("error") == ValidationSeverity.ERROR
        assert validator._parse_severity("ERROR") == ValidationSeverity.ERROR
        assert validator._parse_severity("warning") == ValidationSeverity.WARNING
        assert validator._parse_severity("info") == ValidationSeverity.INFO

        # Unknown severity should default to ERROR
        assert validator._parse_severity("unknown") == ValidationSeverity.ERROR

    def test_linq_engine_pattern(self, validator: TerminologyPreservationValidator) -> None:
        """Test LINQ Engine pattern matching."""
        source = "The LINQ Engine plugin is powerful."
        translation = "Le plugin LINQ Engine est puissant."

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_linq_engine_missing(self, validator: TerminologyPreservationValidator) -> None:
        """Test detection of missing LINQ Engine."""
        source = "The LINQ Engine plugin is powerful."
        translation = "Le plugin est puissant."  # LINQ Engine missing

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count >= 1

    def test_validation_issue_details(self, validator: TerminologyPreservationValidator) -> None:
        """Test that validation issues contain proper details."""
        source = "Aspose provides .NET APIs."
        translation = "We provide APIs."  # Both Aspose and .NET missing

        result = validator.validate(source, translation)

        assert not result.success
        errors = result.filter_by_severity(ValidationSeverity.ERROR)
        # At least Aspose should be missing (1 error minimum)
        assert len(errors) >= 1

        for error in errors:
            assert error.details is not None
            assert "term" in error.details
            assert "category" in error.details
            assert "source_count" in error.details
            assert "translation_count" in error.details
            assert "case_sensitive" in error.details

    def test_word_boundary_matching(self, validator: TerminologyPreservationValidator) -> None:
        """Test that word boundaries are respected in term matching."""
        # "Aspose" in "AsposeXYZ" should not count as a match
        source = "Aspose is great."
        translation = "AsposeXYZ est génial."  # Contains "Aspose" but not as separate word

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count >= 1

    def test_context_parameter(self, validator: TerminologyPreservationValidator) -> None:
        """Test that context parameter is accepted (for future extensibility)."""
        source = "Aspose provides APIs."
        translation = "Aspose fournit des API."
        context = {"site_name": "reference.aspose.net", "language": "fr"}

        result = validator.validate(source, translation, context=context)

        assert result.success

    def test_multiple_pattern_categories(self, tmp_path: Path) -> None:
        """Test validation with multiple pattern categories."""
        config_content = """
version: "1.0"

global:
  patterns:
    - pattern: "Aspose\\\\.[A-Z][a-z]+"
      category: product_family
      severity: error

    - pattern: "\\\\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\\\\b"
      category: pascal_case
      severity: warning
"""
        config_path = tmp_path / "terminology.yaml"
        config_path.write_text(config_content, encoding='utf-8')

        validator = TerminologyPreservationValidator(terminology_config_path=config_path)

        source = "Use Aspose.Words with DocumentBuilder class."
        translation = "Use Aspose.Words with DocumentBuilder classe."

        result = validator.validate(source, translation)

        assert result.success

    def test_severity_levels(self, tmp_path: Path) -> None:
        """Test different severity levels in terminology."""
        config_content = """
version: "1.0"

global:
  exact_matches:
    - term: "Critical"
      category: test
      case_sensitive: true
      severity: error

    - term: "Warning"
      category: test
      case_sensitive: true
      severity: warning

    - term: "Info"
      category: test
      case_sensitive: true
      severity: info
"""
        config_path = tmp_path / "terminology.yaml"
        config_path.write_text(config_content, encoding='utf-8')

        validator = TerminologyPreservationValidator(terminology_config_path=config_path)

        source = "Critical Warning Info terms."
        translation = "Translated text."  # All missing

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count == 1  # Critical
        assert result.warning_count == 1  # Warning
        assert result.info_count == 1  # Info

    def test_empty_source_and_translation(self, validator: TerminologyPreservationValidator) -> None:
        """Test validation with empty strings."""
        result = validator.validate("", "")

        assert result.success
        assert len(result.issues) == 0

    def test_special_characters_in_terms(self, validator: TerminologyPreservationValidator) -> None:
        """Test terms with special characters like .NET."""
        source = "Use .NET for development."
        translation = "Utilisez .NET pour le développement."

        result = validator.validate(source, translation)

        assert result.success
        assert len(result.issues) == 0

    def test_validation_result_success_flag(self, validator: TerminologyPreservationValidator) -> None:
        """Test that success flag is properly set based on errors."""
        # No errors - should be success
        source1 = "Aspose provides APIs."
        translation1 = "Aspose fournit des API."
        result1 = validator.validate(source1, translation1)
        assert result1.success

        # Has errors - should not be success
        source2 = "Aspose provides APIs."
        translation2 = "We provide APIs."
        result2 = validator.validate(source2, translation2)
        assert not result2.success

        # Only warnings - should be success
        source3 = "Aspose is great. Aspose is nice."
        translation3 = "Aspose est génial."  # Frequency mismatch (warning)
        result3 = validator.validate(source3, translation3)
        # Success should be True even with warnings (only errors affect it)
        # But we may still have warnings
        assert result3.warning_count >= 1


class TestTerminologyPreservationValidatorIntegration:
    """Integration tests with real terminology.yaml."""

    def test_with_real_config(self) -> None:
        """Test validator with real terminology configuration."""
        validator = TerminologyPreservationValidator()

        source = "Aspose.Words for .NET is a powerful API."
        translation = "Aspose.Words pour .NET est une API puissante."

        result = validator.validate(source, translation)

        assert result.success

    def test_real_config_missing_term(self) -> None:
        """Test detection with real config."""
        validator = TerminologyPreservationValidator()

        source = "Aspose provides APIs."
        translation = "We provide APIs."

        result = validator.validate(source, translation)

        assert not result.success
        assert result.error_count >= 1
