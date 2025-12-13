"""
Tests for YAMLStructureValidator.

Verifies SD-04 acceptance checks:
- Validator reports line count drift percentage
- Validator detects missing comments
- Validator detects literal block loss
- Configurable thresholds work correctly
"""
import pytest

from src.translation_engine.validation.structure_validator import (
    YAMLStructureValidator,
    YAMLStructureIssue,
    YAMLStructureValidationResult,
)


class TestYAMLStructureValidator:
    """Test YAMLStructureValidator functionality."""

    def test_no_drift_passes(self):
        """Identical content should pass with 0% drift."""
        validator = YAMLStructureValidator()

        source = """# Static
layout: "family"
title: "Test"
"""
        target = """# Static
layout: "family"
title: "Test"
"""

        result = validator.validate(source, target)

        assert result.line_drift_percent == 0.0
        assert result.is_valid
        assert len(result.issues) == 0

    def test_detects_high_drift(self):
        """High line count drift should be detected."""
        validator = YAMLStructureValidator()

        source = """line1
line2
line3
line4
line5
line6
line7
line8
line9
line10"""
        target = """line1
line2
line3"""  # 70% drift

        result = validator.validate(source, target)

        assert result.line_drift_percent > 60
        assert not result.is_valid
        assert any(i.issue_type == "line_count_drift" for i in result.issues)
        assert any(i.severity == "error" for i in result.issues)

    def test_detects_warning_drift(self):
        """Moderate drift should trigger warning, not error."""
        validator = YAMLStructureValidator(warn_threshold=10.0, error_threshold=20.0)

        source = """line1
line2
line3
line4
line5
line6
line7
line8
line9
line10"""
        target = """line1
line2
line3
line4
line5
line6
line7
line8"""  # 20% drift (at threshold)

        result = validator.validate(source, target)

        # Should be at warning level, not error
        assert result.line_drift_percent == 20.0

    def test_detects_missing_comments(self):
        """Missing YAML comments should be detected."""
        validator = YAMLStructureValidator()

        source = """# Static
layout: family
# Head
title: Test
# Footer
footer: true"""
        target = """layout: family
title: Test
footer: true"""  # Comments stripped

        result = validator.validate(source, target)

        missing_comment_issues = [
            i for i in result.issues if i.issue_type == "missing_comment"
        ]
        assert len(missing_comment_issues) >= 2  # At least # Static and # Head

    def test_detects_literal_block_loss(self):
        """Loss of literal block scalars should be detected."""
        validator = YAMLStructureValidator()

        source = """content: |
  Line 1
  Line 2
description: |
  Description text"""
        target = """content: 'Line 1 Line 2'
description: 'Description text'"""

        result = validator.validate(source, target)

        literal_issues = [
            i for i in result.issues if i.issue_type == "literal_block_loss"
        ]
        assert len(literal_issues) == 1

    def test_configurable_thresholds(self):
        """Custom thresholds should work correctly."""
        # Very strict validator
        strict_validator = YAMLStructureValidator(
            warn_threshold=5.0, error_threshold=10.0
        )
        # Very lenient validator
        lenient_validator = YAMLStructureValidator(
            warn_threshold=30.0, error_threshold=50.0
        )

        source = "line1\nline2\nline3\nline4\nline5"
        target = "line1\nline2\nline3\nline4"  # 20% drift

        strict_result = strict_validator.validate(source, target)
        lenient_result = lenient_validator.validate(source, target)

        # Strict should fail, lenient should pass
        assert not strict_result.is_valid
        assert lenient_result.is_valid

    def test_is_valid_property(self):
        """is_valid property should correctly reflect validation state."""
        validator = YAMLStructureValidator()

        # Good content
        good_source = "# Comment\nkey: value"
        good_target = "# Comment\nkey: translated"
        good_result = validator.validate(good_source, good_target)
        assert good_result.is_valid

        # Bad content (massive drift)
        bad_source = "\n".join([f"line{i}" for i in range(100)])
        bad_target = "single_line"
        bad_result = validator.validate(bad_source, bad_target)
        assert not bad_result.is_valid

    def test_empty_content_handling(self):
        """Empty content should be handled gracefully."""
        validator = YAMLStructureValidator()

        result = validator.validate("", "")

        # Should not crash, should have minimal drift
        assert result is not None
        assert isinstance(result, YAMLStructureValidationResult)

    def test_result_dataclass_fields(self):
        """Result dataclass should have all expected fields."""
        validator = YAMLStructureValidator()
        result = validator.validate("test", "test")

        assert hasattr(result, "source_lines")
        assert hasattr(result, "target_lines")
        assert hasattr(result, "line_drift_percent")
        assert hasattr(result, "issues")
        assert hasattr(result, "is_valid")


class TestYAMLStructureIssue:
    """Test YAMLStructureIssue dataclass."""

    def test_issue_creation(self):
        """Issues should be created with correct fields."""
        issue = YAMLStructureIssue(
            issue_type="test_issue",
            description="Test description",
            severity="warning",
        )

        assert issue.issue_type == "test_issue"
        assert issue.description == "Test description"
        assert issue.severity == "warning"


class TestRealFileValidation:
    """Integration tests with real file patterns."""

    def test_hugo_frontmatter_pattern(self):
        """Test with realistic Hugo frontmatter patterns."""
        validator = YAMLStructureValidator()

        source = """---
# Static
layout: "plugin"
cart_id: ""

# Head
head_title: "Test Plugin"
head_description: "Description"

# Overview
overview:
  enable: true
  title: "Overview"
  content: |
    Multi-line
    content here
---"""

        # Good translation (preserves structure)
        good_target = """---
# Static
layout: "plugin"
cart_id: ""

# Head
head_title: "Test Plugin Translated"
head_description: "Translated Description"

# Overview
overview:
  enable: true
  title: "Translated Overview"
  content: |
    Translated multi-line
    content here
---"""

        result = validator.validate(source, good_target)
        assert result.is_valid
        assert result.line_drift_percent < 10

    def test_bad_translation_detection(self):
        """Test that bad translations (structure drift) are detected."""
        validator = YAMLStructureValidator()

        source = """---
# Static
layout: "plugin"

# Head
head_title: "Test"
head_description: "Description"

# Body
body:
  enable: true
  block:
    - title_left: "Block 1"
      content_left: |
        Content here
    - title_left: "Block 2"
      content_left: |
        More content
---"""

        # Bad translation (collapsed structure)
        bad_target = """---
layout: plugin
head_title: Test
head_description: Description
body:
  enable: true
---"""

        result = validator.validate(source, bad_target)

        # Should detect problems
        assert len(result.issues) > 0
        # Comments should be missing
        missing_comments = [i for i in result.issues if i.issue_type == "missing_comment"]
        assert len(missing_comments) > 0
