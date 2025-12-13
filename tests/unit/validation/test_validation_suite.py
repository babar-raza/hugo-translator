"""
Comprehensive unit tests for ValidationSuite orchestrator.

Tests cover:
- Running all validators
- Aggregating results
- Short-circuit on critical failures
- Loading validators from config
- Disabled validators are skipped
- 100% coverage
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch, mock_open
from typing import Dict, Any

from src.translation_engine.validation.base import (
    Validator,
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
)
from src.translation_engine.validation.validation_suite import ValidationSuite
from src.translation_engine.validation.completeness_validator import CompletenessValidator
from src.translation_engine.validation.language_consistency_validator import LanguageConsistencyValidator
from src.translation_engine.validation.shortcode_preservation_validator import ShortcodePreservationValidator
from src.translation_engine.validation.placeholder_validator import PlaceholderValidator
from src.translation_engine.validation.structure_validator import StructureValidator
from src.translation_engine.validation.link_validator import LinkValidator


class MockValidator(Validator):
    """Mock validator for testing."""

    def __init__(self, name: str, return_success: bool = True, has_errors: bool = False):
        super().__init__(name=name)
        self.return_success = return_success
        self.has_errors_flag = has_errors
        self.validate_called = False

    def validate(self, source: str, translation: str, context: Dict[str, Any] = None) -> ValidationResult:
        self.validate_called = True
        result = ValidationResult(success=self.return_success)
        if self.has_errors_flag:
            result.issues.append(
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator=self.name,
                    message=f"Test error from {self.name}",
                )
            )
        return result


class TestValidationSuite:
    """Test suite for ValidationSuite class."""

    def test_init_with_default_validators(self):
        """Test initialization with default validators."""
        suite = ValidationSuite()

        # Should have default validators
        assert len(suite.validators) > 0
        assert suite.fail_fast is False
        assert suite.short_circuit_on_critical is False

        # Check for expected validator types
        validator_types = [type(v).__name__ for v in suite.validators]
        assert "PlaceholderValidator" in validator_types
        assert "StructureValidator" in validator_types
        assert "LinkValidator" in validator_types
        assert "CompletenessValidator" in validator_types
        assert "LanguageConsistencyValidator" in validator_types
        assert "ShortcodePreservationValidator" in validator_types

    def test_init_with_custom_validators(self):
        """Test initialization with custom validator list."""
        mock_validators = [
            MockValidator("Validator1"),
            MockValidator("Validator2"),
        ]

        suite = ValidationSuite(validators=mock_validators)

        assert len(suite.validators) == 2
        assert suite.validators[0].name == "Validator1"
        assert suite.validators[1].name == "Validator2"

    def test_init_with_fail_fast(self):
        """Test initialization with fail_fast flag."""
        suite = ValidationSuite(fail_fast=True)
        assert suite.fail_fast is True

    def test_init_with_short_circuit_on_critical(self):
        """Test initialization with short_circuit_on_critical flag."""
        suite = ValidationSuite(short_circuit_on_critical=True)
        assert suite.short_circuit_on_critical is True

    def test_runs_all_validators(self):
        """Test that validate() runs all validators."""
        mock_validators = [
            MockValidator("Validator1", return_success=True),
            MockValidator("Validator2", return_success=True),
            MockValidator("Validator3", return_success=True),
        ]

        suite = ValidationSuite(validators=mock_validators)
        results = suite.validate("source", "translation", {})

        # All validators should be called
        assert len(results) == 3
        assert all(v.validate_called for v in mock_validators)

    def test_aggregates_results(self):
        """Test that validate_aggregated() aggregates all results correctly."""
        mock_validators = [
            MockValidator("Validator1", return_success=True),
            MockValidator("Validator2", return_success=False, has_errors=True),
            MockValidator("Validator3", return_success=True),
        ]

        suite = ValidationSuite(validators=mock_validators)
        result = suite.validate_aggregated("source", "translation", {})

        # Should aggregate all issues
        assert result.success is False  # One validator failed
        assert len(result.issues) == 1  # One error from Validator2
        assert result.issues[0].validator == "Validator2"

    def test_short_circuit_on_critical(self):
        """Test short-circuit behavior when critical failures occur."""
        mock_validators = [
            MockValidator("Validator1", return_success=True),
            MockValidator("Validator2", return_success=False, has_errors=True),
            MockValidator("Validator3", return_success=True),  # Should not run
        ]

        suite = ValidationSuite(
            validators=mock_validators,
            short_circuit_on_critical=True,
        )
        results = suite.validate("source", "translation", {})

        # Should stop after Validator2
        assert len(results) == 2
        assert mock_validators[0].validate_called
        assert mock_validators[1].validate_called
        assert not mock_validators[2].validate_called

    def test_fail_fast_behavior(self):
        """Test fail_fast behavior (legacy)."""
        mock_validators = [
            MockValidator("Validator1", return_success=True),
            MockValidator("Validator2", return_success=False),
            MockValidator("Validator3", return_success=True),  # Should not run
        ]

        suite = ValidationSuite(
            validators=mock_validators,
            fail_fast=True,
        )
        results = suite.validate("source", "translation", {})

        # Should stop after Validator2
        assert len(results) == 2
        assert mock_validators[0].validate_called
        assert mock_validators[1].validate_called
        assert not mock_validators[2].validate_called

    def test_loads_from_config(self):
        """Test loading validators from config file."""
        config_yaml = """
version: "1.0"
validators:
  yaml:
    enabled: true
  placeholder:
    enabled: true
  structure:
    enabled: false
  link:
    enabled: true
  completeness:
    enabled: true
  language_consistency:
    enabled: true
    confidence_threshold: 0.9
  shortcode_preservation:
    enabled: true
  frontmatter_protection:
    enabled: false
  terminology_preservation:
    enabled: false
  file_placement:
    enabled: false
"""

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            suite = ValidationSuite.from_config(Path("config/validation.yaml"))

        # Check enabled validators
        validator_types = [type(v).__name__ for v in suite.validators]

        # Enabled validators
        assert "YAMLValidator" in validator_types
        assert "PlaceholderValidator" in validator_types
        assert "LinkValidator" in validator_types
        assert "CompletenessValidator" in validator_types
        assert "LanguageConsistencyValidator" in validator_types
        assert "ShortcodePreservationValidator" in validator_types

        # Disabled validators
        assert "StructureValidator" not in validator_types
        assert "FrontmatterProtectionValidator" not in validator_types
        assert "TerminologyPreservationValidator" not in validator_types
        assert "FilePlacementValidator" not in validator_types

    def test_disabled_validators_skipped(self):
        """Test that disabled validators are not included."""
        config_yaml = """
version: "1.0"
validators:
  yaml:
    enabled: false
  placeholder:
    enabled: false
  structure:
    enabled: false
  link:
    enabled: false
  completeness:
    enabled: false
  language_consistency:
    enabled: false
  shortcode_preservation:
    enabled: false
  frontmatter_protection:
    enabled: false
  terminology_preservation:
    enabled: false
  file_placement:
    enabled: false
"""

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            suite = ValidationSuite.from_config(Path("config/validation.yaml"))

        # No validators should be loaded
        assert len(suite.validators) == 0

    def test_config_with_validator_parameters(self):
        """Test loading validators with custom parameters from config."""
        config_yaml = """
version: "1.0"
validators:
  language_consistency:
    enabled: true
    confidence_threshold: 0.95
"""

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            suite = ValidationSuite.from_config(Path("config/validation.yaml"))

        # Find LanguageConsistencyValidator
        lang_validator = None
        for validator in suite.validators:
            if isinstance(validator, LanguageConsistencyValidator):
                lang_validator = validator
                break

        assert lang_validator is not None
        assert lang_validator.confidence_threshold == 0.95

    def test_from_config_with_site_profile(self):
        """Test from_config with site profile for validators that need it."""
        config_yaml = """
version: "1.0"
validators:
  frontmatter_protection:
    enabled: true
"""

        mock_site_profile = MagicMock()

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            suite = ValidationSuite.from_config(
                Path("config/validation.yaml"),
                site_profile=mock_site_profile,
            )

        # FrontmatterProtectionValidator should be loaded
        validator_types = [type(v).__name__ for v in suite.validators]
        assert "FrontmatterProtectionValidator" in validator_types

    def test_from_config_without_site_profile_skips_dependent_validators(self):
        """Test that validators requiring site_profile are skipped if not provided."""
        config_yaml = """
version: "1.0"
validators:
  frontmatter_protection:
    enabled: true
"""

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            suite = ValidationSuite.from_config(Path("config/validation.yaml"))

        # FrontmatterProtectionValidator should NOT be loaded (no site_profile)
        validator_types = [type(v).__name__ for v in suite.validators]
        assert "FrontmatterProtectionValidator" not in validator_types

    def test_from_config_with_config_service(self):
        """Test from_config with config_service for FilePlacementValidator."""
        config_yaml = """
version: "1.0"
validators:
  file_placement:
    enabled: true
"""

        mock_config_service = MagicMock()

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            suite = ValidationSuite.from_config(
                Path("config/validation.yaml"),
                config_service=mock_config_service,
            )

        # FilePlacementValidator should be loaded
        validator_types = [type(v).__name__ for v in suite.validators]
        assert "FilePlacementValidator" in validator_types

    def test_add_validator(self):
        """Test adding a validator dynamically."""
        suite = ValidationSuite(validators=[])
        assert len(suite.validators) == 0

        new_validator = MockValidator("DynamicValidator")
        suite.add_validator(new_validator)

        assert len(suite.validators) == 1
        assert suite.validators[0].name == "DynamicValidator"

    def test_remove_validator(self):
        """Test removing a validator by name."""
        mock_validators = [
            MockValidator("Validator1"),
            MockValidator("Validator2"),
            MockValidator("Validator3"),
        ]

        suite = ValidationSuite(validators=mock_validators)
        assert len(suite.validators) == 3

        # Remove Validator2
        removed = suite.remove_validator("Validator2")
        assert removed is True
        assert len(suite.validators) == 2
        assert suite.validators[0].name == "Validator1"
        assert suite.validators[1].name == "Validator3"

    def test_remove_validator_not_found(self):
        """Test removing a non-existent validator."""
        suite = ValidationSuite(validators=[MockValidator("Validator1")])

        removed = suite.remove_validator("NonExistent")
        assert removed is False
        assert len(suite.validators) == 1

    def test_get_validator(self):
        """Test getting a validator by name."""
        mock_validators = [
            MockValidator("Validator1"),
            MockValidator("Validator2"),
        ]

        suite = ValidationSuite(validators=mock_validators)

        validator = suite.get_validator("Validator2")
        assert validator is not None
        assert validator.name == "Validator2"

    def test_get_validator_not_found(self):
        """Test getting a non-existent validator."""
        suite = ValidationSuite(validators=[MockValidator("Validator1")])

        validator = suite.get_validator("NonExistent")
        assert validator is None

    def test_validate_with_yaml(self):
        """Test validate_with_yaml method."""
        suite = ValidationSuite(validators=[])

        source_yaml = "---\ntitle: Test\n---\n"
        translation_yaml = "---\ntitle: Test\n---\n"
        source_body = "Source body"
        translation_body = "Translation body"

        result = suite.validate_with_yaml(
            source_yaml,
            translation_yaml,
            source_body,
            translation_body,
            {},
        )

        # Should return a ValidationResult
        assert isinstance(result, ValidationResult)

    def test_validate_returns_list_of_results(self):
        """Test that validate() returns a list of ValidationResult objects."""
        mock_validators = [
            MockValidator("Validator1"),
            MockValidator("Validator2"),
        ]

        suite = ValidationSuite(validators=mock_validators)
        results = suite.validate("source", "translation", {})

        assert isinstance(results, list)
        assert len(results) == 2
        assert all(isinstance(r, ValidationResult) for r in results)

    def test_validate_aggregated_returns_single_result(self):
        """Test that validate_aggregated() returns a single ValidationResult."""
        mock_validators = [
            MockValidator("Validator1"),
            MockValidator("Validator2"),
        ]

        suite = ValidationSuite(validators=mock_validators)
        result = suite.validate_aggregated("source", "translation", {})

        assert isinstance(result, ValidationResult)
        assert not isinstance(result, list)

    def test_validate_with_context(self):
        """Test that context is passed to validators."""
        class ContextCheckValidator(Validator):
            def __init__(self):
                super().__init__("ContextCheck")
                self.received_context = None

            def validate(self, source, translation, context=None):
                self.received_context = context
                return ValidationResult(success=True)

        validator = ContextCheckValidator()
        suite = ValidationSuite(validators=[validator])

        test_context = {"target_lang": "de", "custom_key": "custom_value"}
        suite.validate("source", "translation", test_context)

        assert validator.received_context == test_context

    def test_default_config_path_resolution(self):
        """Test that default config path is correctly resolved."""
        config_yaml = """
version: "1.0"
validators:
  placeholder:
    enabled: true
"""

        with patch("builtins.open", mock_open(read_data=config_yaml)):
            # Call without config_path to use default
            suite = ValidationSuite.from_config()

        # Should create suite without errors
        assert len(suite.validators) > 0

    def test_short_circuit_does_not_trigger_on_warnings(self):
        """Test that short-circuit only triggers on errors, not warnings."""
        class WarningValidator(Validator):
            def __init__(self, name):
                super().__init__(name)

            def validate(self, source, translation, context=None):
                result = ValidationResult(success=True)
                result.issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.WARNING,
                        validator=self.name,
                        message="Test warning",
                    )
                )
                return result

        mock_validators = [
            WarningValidator("Validator1"),
            WarningValidator("Validator2"),
            WarningValidator("Validator3"),
        ]

        suite = ValidationSuite(
            validators=mock_validators,
            short_circuit_on_critical=True,
        )
        results = suite.validate("source", "translation", {})

        # All validators should run (warnings don't trigger short-circuit)
        assert len(results) == 3

    def test_empty_validators_list(self):
        """Test behavior with empty validators list."""
        suite = ValidationSuite(validators=[])

        results = suite.validate("source", "translation", {})
        assert len(results) == 0

        aggregated = suite.validate_aggregated("source", "translation", {})
        assert aggregated.success is True
        assert len(aggregated.issues) == 0

    def test_multiple_errors_aggregation(self):
        """Test aggregation of multiple errors from different validators."""
        class MultiErrorValidator(Validator):
            def __init__(self, name, error_count):
                super().__init__(name)
                self.error_count = error_count

            def validate(self, source, translation, context=None):
                result = ValidationResult(success=False)
                for i in range(self.error_count):
                    result.issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            validator=self.name,
                            message=f"Error {i+1}",
                        )
                    )
                return result

        mock_validators = [
            MultiErrorValidator("Validator1", 2),
            MultiErrorValidator("Validator2", 3),
        ]

        suite = ValidationSuite(validators=mock_validators)
        result = suite.validate_aggregated("source", "translation", {})

        # Should have 5 total errors
        assert result.error_count == 5
        assert len(result.issues) == 5
        assert result.success is False
