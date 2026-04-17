"""
Unit tests for YAML validator.
"""

import pytest

from src.translation_engine.validation import (
    YAMLValidator,
)


class TestYAMLValidator:
    """Test YAMLValidator."""

    @pytest.fixture
    def validator(self):
        """Create YAML validator."""
        return YAMLValidator()

    def test_valid_yaml(self, validator):
        """Test validation with valid YAML."""
        source = """
title: "Hello World"
description: "A test page"
tags:
  - test
  - example
"""
        translation = """
title: "Bonjour le monde"
description: "Une page de test"
tags:
  - test
  - exemple
"""
        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0

    def test_invalid_source_yaml(self, validator):
        """Test with invalid source YAML."""
        source = """
title: "Unterminated quote
description: "Test"
"""
        translation = """
title: "Valid"
description: "Test"
"""
        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count > 0
        assert any("Invalid source YAML" in issue.message for issue in result.issues)

    def test_invalid_translation_yaml(self, validator):
        """Test with invalid translation YAML."""
        source = """
title: "Valid"
description: "Test"
"""
        translation = """
title: "Valid"
description: "Test"
extra: [unmatched bracket
"""
        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count > 0
        assert any("Invalid translation YAML" in issue.message for issue in result.issues)

    def test_missing_keys(self, validator):
        """Test with missing keys in translation."""
        source = """
title: "Test"
description: "A test"
tags: ["one", "two"]
"""
        translation = """
title: "Tester"
description: "Un test"
"""
        result = validator.validate(source, translation)

        assert result.error_count > 0
        assert any(
            "missing keys" in issue.message.lower() for issue in result.issues
        )
        assert any("tags" in str(issue.details) for issue in result.issues if issue.details)

    def test_extra_keys(self, validator):
        """Test with extra keys in translation."""
        source = """
title: "Test"
description: "A test"
"""
        translation = """
title: "Tester"
description: "Un test"
extra_key: "Should not be here"
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any(
            "extra keys" in issue.message.lower() for issue in result.issues
        )

    def test_type_mismatch(self, validator):
        """Test with type mismatches."""
        source = """
title: "Test"
count: 42
tags: ["one", "two"]
"""
        translation = """
title: "Tester"
count: "quarante-deux"
tags: "un, deux"
"""
        result = validator.validate(source, translation)

        assert result.error_count >= 2  # count and tags type mismatches
        type_issues = [
            issue for issue in result.issues if "type mismatch" in issue.message.lower()
        ]
        assert len(type_issues) == 2

    def test_list_length_mismatch(self, validator):
        """Test with list length mismatches."""
        source = """
tags: ["one", "two", "three"]
"""
        translation = """
tags: ["un", "deux"]
"""
        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any(
            "list length mismatch" in issue.message.lower() for issue in result.issues
        )

    def test_unquoted_colon_warning(self, validator):
        """Test warning for unquoted colons in values."""
        source = """
title: "Test"
"""
        translation = """
title: Test: A subtitle without quotes
"""
        result = validator.validate(source, translation)

        # The YAML parser will actually fail to parse this (it's an error, not a warning)
        # because unquoted colons in values break YAML syntax
        assert result.error_count > 0
        assert any("yaml" in issue.message.lower() for issue in result.issues)

    def test_empty_yaml(self, validator):
        """Test with empty YAML."""
        source = ""
        translation = ""

        result = validator.validate(source, translation)

        # Empty YAML should be valid (empty dict)
        assert result.success is True

    def test_non_dict_yaml(self, validator):
        """Test with non-dict YAML."""
        source = "- item1\n- item2"
        translation = "- item1\n- item2"

        result = validator.validate(source, translation)

        # Should fail because YAML is a list, not a dict
        assert result.success is False
        assert any("must be a dictionary" in issue.message for issue in result.issues)
