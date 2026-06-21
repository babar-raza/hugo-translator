"""
Unit tests for validation suite.
"""

from src.translation_engine.validation import (
    LinkValidator,
    PlaceholderValidator,
    ValidationResult,
    ValidationSuite,
    Validator,
    YAMLValidator,
)


class TestValidationSuite:
    """Test ValidationSuite."""

    def test_default_validators(self):
        """Test suite with default validators."""
        suite = ValidationSuite()

        # Should have 8 default validators (3 legacy + 5 post-translation)
        assert len(suite.validators) == 8
        validator_names = [v.name for v in suite.validators]
        # Legacy validators
        assert "PlaceholderValidator" in validator_names
        assert "StructureValidator" in validator_names
        assert "LinkValidator" in validator_names
        # Post-translation validators
        assert "CompletenessValidator" in validator_names
        assert "LanguageConsistencyValidator" in validator_names
        assert "ShortcodePreservationValidator" in validator_names
        assert "MetadataMarkdownContaminationValidator" in validator_names
        assert "RepetitionDetectorValidator" in validator_names

    def test_custom_validators(self):
        """Test suite with custom validators."""
        validators = [PlaceholderValidator(), YAMLValidator()]
        suite = ValidationSuite(validators=validators)

        assert len(suite.validators) == 2
        assert suite.validators[0].name == "PlaceholderValidator"
        assert suite.validators[1].name == "YAMLValidator"

    def test_validate_simple(self):
        """Test simple validation."""
        suite = ValidationSuite()

        source = "This is [a link](url) with {{CODE_1}}"
        translation = "Ceci est [un lien](url) avec {{CODE_1}}"
        context = {"target_lang": "fr"}  # Provide target language for LanguageConsistencyValidator

        # Use validate_aggregated for single result
        result = suite.validate_aggregated(source, translation, context)

        assert result.success is True
        assert len(result.issues) == 0

    def test_validate_with_errors(self):
        """Test validation with errors."""
        suite = ValidationSuite()

        source = "This has {{CODE_1}} and {{LINK_2}}"
        translation = "Ceci a {{CODE_1}}"  # Missing placeholder

        # Use validate_aggregated for single result
        result = suite.validate_aggregated(source, translation)

        assert result.success is False
        assert result.error_count > 0

    def test_validate_aggregates_results(self):
        """Test that results are aggregated from all validators."""
        suite = ValidationSuite()

        source = """
# Heading 1
## Heading 2

[Link](url1)
{{CODE_1}}
"""
        translation = """
# Titre 1

[Lien](url2)
{{CODE_1}}
"""  # Missing heading, changed URL

        # Use validate_aggregated for single result
        result = suite.validate_aggregated(source, translation)

        # Should have issues from multiple validators
        assert len(result.issues) > 0
        # Check that issues come from different validators
        validators_with_issues = {issue.validator for issue in result.issues}
        assert len(validators_with_issues) >= 2

    def test_fail_fast(self):
        """Test fail_fast mode."""
        # Create suite with fail_fast
        suite = ValidationSuite(fail_fast=True)

        # Source with multiple issues
        source = "{{CODE_1}} {{CODE_2}} [Link](url)"
        translation = "[Lien](url)"  # Missing both placeholders

        # Use validate_aggregated for single result
        result = suite.validate_aggregated(source, translation)

        # Should stop after first validator with error
        assert result.success is False

    def test_validate_with_yaml(self):
        """Test validate_with_yaml for complete documents."""
        suite = ValidationSuite()

        source_yaml = """
title: "Test"
description: "A test"
"""
        translation_yaml = """
title: "Tester"
description: "Un test"
"""

        source_body = "This is {{CODE_1}}"
        translation_body = "Ceci est {{CODE_1}}"

        result = suite.validate_with_yaml(
            source_yaml, translation_yaml, source_body, translation_body
        )

        assert result.success is True

    def test_validate_with_yaml_errors(self):
        """Test validate_with_yaml with errors."""
        suite = ValidationSuite()

        source_yaml = """
title: "Test"
tags: ["one", "two"]
"""
        translation_yaml = """
title: "Tester"
"""  # Missing tags

        source_body = "This is {{CODE_1}}"
        translation_body = "This is missing placeholder"

        result = suite.validate_with_yaml(
            source_yaml, translation_yaml, source_body, translation_body
        )

        assert result.success is False
        # Should have errors from both YAML and body validation
        assert result.error_count >= 2

    def test_add_validator(self):
        """Test adding validator to suite."""
        suite = ValidationSuite(validators=[])
        assert len(suite.validators) == 0

        suite.add_validator(PlaceholderValidator())
        assert len(suite.validators) == 1

        suite.add_validator(LinkValidator())
        assert len(suite.validators) == 2

    def test_remove_validator(self):
        """Test removing validator from suite."""
        suite = ValidationSuite()
        initial_count = len(suite.validators)

        # Remove placeholder validator
        removed = suite.remove_validator("PlaceholderValidator")
        assert removed is True
        assert len(suite.validators) == initial_count - 1

        # Try to remove non-existent validator
        removed = suite.remove_validator("NonExistentValidator")
        assert removed is False

    def test_get_validator(self):
        """Test getting validator by name."""
        suite = ValidationSuite()

        validator = suite.get_validator("PlaceholderValidator")
        assert validator is not None
        assert isinstance(validator, PlaceholderValidator)

        validator = suite.get_validator("NonExistent")
        assert validator is None

    def test_context_passing(self):
        """Test that context is passed to validators."""

        # Create custom validator that checks context
        class ContextCheckingValidator(Validator):
            def validate(self, source, translation, context=None):
                result = ValidationResult(success=True)
                if context and "test_key" in context:
                    result.metadata["context_received"] = True
                return result

        suite = ValidationSuite(validators=[ContextCheckingValidator()])

        context = {"test_key": "test_value"}
        # Use validate_aggregated for single result
        result = suite.validate_aggregated("source", "translation", context)

        assert result.metadata.get("context_received") is True

    def test_empty_suite(self):
        """Test suite with no validators."""
        suite = ValidationSuite(validators=[])

        # Use validate_aggregated for single result
        result = suite.validate_aggregated("source", "translation")

        assert result.success is True
        assert len(result.issues) == 0
