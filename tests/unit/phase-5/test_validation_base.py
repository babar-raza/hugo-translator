"""
Unit tests for validation base classes.
"""

from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
    Validator,
)


class TestValidationSeverity:
    """Test ValidationSeverity enum."""

    def test_severity_values(self):
        """Test severity enum values."""
        assert ValidationSeverity.ERROR.value == "error"
        assert ValidationSeverity.WARNING.value == "warning"
        assert ValidationSeverity.INFO.value == "info"


class TestValidationIssue:
    """Test ValidationIssue dataclass."""

    def test_create_issue(self):
        """Test creating validation issue."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            validator="TestValidator",
            message="Test error message",
            location="line 42",
            details={"key": "value"},
        )

        assert issue.severity == ValidationSeverity.ERROR
        assert issue.validator == "TestValidator"
        assert issue.message == "Test error message"
        assert issue.location == "line 42"
        assert issue.details == {"key": "value"}

    def test_issue_str_representation(self):
        """Test string representation of issue."""
        issue = ValidationIssue(
            severity=ValidationSeverity.ERROR,
            validator="TestValidator",
            message="Test message",
            location="line 10",
        )

        str_repr = str(issue)
        assert "[ERROR]" in str_repr
        assert "TestValidator" in str_repr
        assert "Test message" in str_repr
        assert "at line 10" in str_repr

    def test_issue_without_location(self):
        """Test issue without location."""
        issue = ValidationIssue(
            severity=ValidationSeverity.WARNING,
            validator="TestValidator",
            message="Test message",
        )

        str_repr = str(issue)
        assert "[WARNING]" in str_repr
        assert " at " not in str_repr  # Check for " at " with spaces, not just "at"


class TestValidationResult:
    """Test ValidationResult dataclass."""

    def test_create_result(self):
        """Test creating validation result."""
        result = ValidationResult(success=True)

        assert result.success is True
        assert result.issues == []
        assert result.metadata == {}

    def test_error_count(self):
        """Test counting errors."""
        result = ValidationResult(success=False)
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="Test",
                message="Error 1",
            )
        )
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                validator="Test",
                message="Warning 1",
            )
        )
        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="Test",
                message="Error 2",
            )
        )

        assert result.error_count == 2
        assert result.warning_count == 1
        assert result.info_count == 0

    def test_filter_by_severity(self):
        """Test filtering issues by severity."""
        result = ValidationResult(success=False)
        result.issues = [
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="Test",
                message="Error",
            ),
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                validator="Test",
                message="Warning",
            ),
            ValidationIssue(
                severity=ValidationSeverity.INFO,
                validator="Test",
                message="Info",
            ),
        ]

        errors = result.filter_by_severity(ValidationSeverity.ERROR)
        warnings = result.filter_by_severity(ValidationSeverity.WARNING)
        infos = result.filter_by_severity(ValidationSeverity.INFO)

        assert len(errors) == 1
        assert len(warnings) == 1
        assert len(infos) == 1
        assert errors[0].message == "Error"
        assert warnings[0].message == "Warning"
        assert infos[0].message == "Info"

    def test_has_errors(self):
        """Test checking for errors."""
        result = ValidationResult(success=True)
        assert not result.has_errors()

        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                validator="Test",
                message="Warning",
            )
        )
        assert not result.has_errors()

        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="Test",
                message="Error",
            )
        )
        assert result.has_errors()

    def test_has_warnings(self):
        """Test checking for warnings."""
        result = ValidationResult(success=True)
        assert not result.has_warnings()

        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.INFO,
                validator="Test",
                message="Info",
            )
        )
        assert not result.has_warnings()

        result.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                validator="Test",
                message="Warning",
            )
        )
        assert result.has_warnings()

    def test_merge_results(self):
        """Test merging validation results."""
        result1 = ValidationResult(success=True)
        result1.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                validator="Test1",
                message="Warning 1",
            )
        )
        result1.metadata["key1"] = "value1"

        result2 = ValidationResult(success=False)
        result2.issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="Test2",
                message="Error 1",
            )
        )
        result2.metadata["key2"] = "value2"

        result1.merge(result2)

        assert result1.success is False
        assert len(result1.issues) == 2
        assert result1.metadata["key1"] == "value1"
        assert result1.metadata["key2"] == "value2"


class TestValidator:
    """Test Validator base class."""

    def test_validator_init(self):
        """Test validator initialization."""

        class TestValidator(Validator):
            def validate(self, source, translation, context=None):
                return ValidationResult(success=True)

        validator = TestValidator()
        assert validator.name == "TestValidator"

        validator = TestValidator(name="CustomName")
        assert validator.name == "CustomName"

    def test_create_issue_helper(self):
        """Test create_issue helper method."""

        class TestValidator(Validator):
            def validate(self, source, translation, context=None):
                return ValidationResult(success=True)

        validator = TestValidator()
        issue = validator.create_issue(
            ValidationSeverity.ERROR,
            "Test message",
            location="test location",
            details={"test": "data"},
        )

        assert issue.severity == ValidationSeverity.ERROR
        assert issue.validator == "TestValidator"
        assert issue.message == "Test message"
        assert issue.location == "test location"
        assert issue.details == {"test": "data"}
