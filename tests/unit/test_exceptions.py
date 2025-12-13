"""
Unit tests for translation engine exception types.

Tests cover:
- TranslationError base class
- TranslationRejectedError (initialization, attributes, inheritance)
- TranslationRetryableError (initialization, retry context, inheritance)
- Exception hierarchy and inheritance chain
- Edge cases (None values, missing fields)
"""

import pytest
from src.translation_engine.exceptions import (
    TranslationError,
    TranslationRejectedError,
    TranslationRetryableError,
)
from src.translation_engine.models import ValidationResult, ValidationIssue


class TestTranslationError:
    """Tests for the base TranslationError class."""

    def test_base_exception_creation(self):
        """Test that TranslationError can be created with a message."""
        error = TranslationError("Test error message")
        assert str(error) == "Test error message"

    def test_base_exception_inheritance(self):
        """Test that TranslationError inherits from Exception."""
        error = TranslationError("Test error")
        assert isinstance(error, Exception)

    def test_base_exception_can_be_raised(self):
        """Test that TranslationError can be raised and caught."""
        with pytest.raises(TranslationError) as exc_info:
            raise TranslationError("Test error")
        assert str(exc_info.value) == "Test error"


class TestTranslationRejectedError:
    """Tests for TranslationRejectedError."""

    def test_initialization(self):
        """Test TranslationRejectedError initialization with all attributes."""
        validation_result = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity="error",
                    rule="front_matter_structure",
                    message="Invalid front matter format"
                )
            ]
        )

        error = TranslationRejectedError(
            message="Translation rejected",
            file_path="/content/post.md",
            validation_result=validation_result,
            rejection_reason="Critical validation errors"
        )

        assert str(error) == "Translation rejected"
        assert error.file_path == "/content/post.md"
        assert error.validation_result == validation_result
        assert error.rejection_reason == "Critical validation errors"

    def test_attributes_accessible(self):
        """Test that all attributes are accessible after initialization."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRejectedError(
            message="Test message",
            file_path="/test/file.md",
            validation_result=validation_result,
            rejection_reason="Test reason"
        )

        # All attributes should be accessible
        assert hasattr(error, "file_path")
        assert hasattr(error, "validation_result")
        assert hasattr(error, "rejection_reason")
        assert error.file_path == "/test/file.md"
        assert error.validation_result.valid is False
        assert error.rejection_reason == "Test reason"

    def test_inheritance_from_translation_error(self):
        """Test that TranslationRejectedError inherits from TranslationError."""
        validation_result = ValidationResult(valid=False)
        error = TranslationRejectedError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        assert isinstance(error, TranslationError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test that TranslationRejectedError can be raised and caught."""
        validation_result = ValidationResult(valid=False)

        with pytest.raises(TranslationRejectedError) as exc_info:
            raise TranslationRejectedError(
                message="Rejection test",
                file_path="/test.md",
                validation_result=validation_result,
                rejection_reason="Test rejection"
            )

        assert str(exc_info.value) == "Rejection test"
        assert exc_info.value.file_path == "/test.md"
        assert exc_info.value.rejection_reason == "Test rejection"

    def test_caught_as_base_exception(self):
        """Test that TranslationRejectedError can be caught as TranslationError."""
        validation_result = ValidationResult(valid=False)

        with pytest.raises(TranslationError) as exc_info:
            raise TranslationRejectedError(
                message="Test",
                file_path="/test.md",
                validation_result=validation_result,
                rejection_reason="Test"
            )

        assert isinstance(exc_info.value, TranslationRejectedError)

    def test_with_complex_validation_result(self):
        """Test TranslationRejectedError with complex validation result."""
        validation_result = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity="error",
                    rule="front_matter",
                    message="Missing required field",
                    location="line 1"
                ),
                ValidationIssue(
                    severity="error",
                    rule="content_structure",
                    message="Invalid markdown structure",
                    location="line 15"
                ),
                ValidationIssue(
                    severity="warning",
                    rule="style",
                    message="Inconsistent heading levels"
                )
            ]
        )

        error = TranslationRejectedError(
            message="Multiple critical errors",
            file_path="/content/complex.md",
            validation_result=validation_result,
            rejection_reason="Front matter and structure errors"
        )

        assert len(error.validation_result.issues) == 3
        assert len(error.validation_result.errors) == 2
        assert len(error.validation_result.warnings) == 1

    def test_with_empty_file_path(self):
        """Test TranslationRejectedError with empty file path."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRejectedError(
            message="Test",
            file_path="",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        assert error.file_path == ""

    def test_with_none_validation_result(self):
        """Test TranslationRejectedError handles None validation_result."""
        # This tests that the exception can be created with None,
        # though in production this should be avoided
        error = TranslationRejectedError(
            message="Test",
            file_path="/test.md",
            validation_result=None,
            rejection_reason="Test"
        )

        assert error.validation_result is None

    def test_missing_required_field_raises_type_error(self):
        """Test that missing required fields raise TypeError."""
        validation_result = ValidationResult(valid=False)

        with pytest.raises(TypeError):
            # Missing rejection_reason parameter
            TranslationRejectedError(
                message="Test",
                file_path="/test.md",
                validation_result=validation_result
            )


class TestTranslationRetryableError:
    """Tests for TranslationRetryableError."""

    def test_initialization(self):
        """Test TranslationRetryableError initialization with all attributes."""
        validation_result = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity="error",
                    rule="code_block_format",
                    message="Code block formatting inconsistent"
                )
            ]
        )

        error = TranslationRetryableError(
            message="Translation validation failed, retry possible",
            file_path="/content/post.md",
            validation_result=validation_result,
            retry_feedback="Preserve code block formatting",
            retry_count=1
        )

        assert str(error) == "Translation validation failed, retry possible"
        assert error.file_path == "/content/post.md"
        assert error.validation_result == validation_result
        assert error.retry_feedback == "Preserve code block formatting"
        assert error.retry_count == 1

    def test_default_retry_count(self):
        """Test that retry_count defaults to 0."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Test feedback"
        )

        assert error.retry_count == 0

    def test_attributes_accessible(self):
        """Test that all attributes are accessible after initialization."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRetryableError(
            message="Test message",
            file_path="/test/file.md",
            validation_result=validation_result,
            retry_feedback="Fix formatting",
            retry_count=2
        )

        # All attributes should be accessible
        assert hasattr(error, "file_path")
        assert hasattr(error, "validation_result")
        assert hasattr(error, "retry_feedback")
        assert hasattr(error, "retry_count")
        assert error.file_path == "/test/file.md"
        assert error.validation_result.valid is False
        assert error.retry_feedback == "Fix formatting"
        assert error.retry_count == 2

    def test_inheritance_from_translation_error(self):
        """Test that TranslationRetryableError inherits from TranslationError."""
        validation_result = ValidationResult(valid=False)
        error = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Test"
        )

        assert isinstance(error, TranslationError)
        assert isinstance(error, Exception)

    def test_can_be_raised_and_caught(self):
        """Test that TranslationRetryableError can be raised and caught."""
        validation_result = ValidationResult(valid=False)

        with pytest.raises(TranslationRetryableError) as exc_info:
            raise TranslationRetryableError(
                message="Retry test",
                file_path="/test.md",
                validation_result=validation_result,
                retry_feedback="Test feedback",
                retry_count=1
            )

        assert str(exc_info.value) == "Retry test"
        assert exc_info.value.file_path == "/test.md"
        assert exc_info.value.retry_feedback == "Test feedback"
        assert exc_info.value.retry_count == 1

    def test_caught_as_base_exception(self):
        """Test that TranslationRetryableError can be caught as TranslationError."""
        validation_result = ValidationResult(valid=False)

        with pytest.raises(TranslationError) as exc_info:
            raise TranslationRetryableError(
                message="Test",
                file_path="/test.md",
                validation_result=validation_result,
                retry_feedback="Test"
            )

        assert isinstance(exc_info.value, TranslationRetryableError)

    def test_retry_context_progression(self):
        """Test retry count can be incremented across multiple attempts."""
        validation_result = ValidationResult(valid=False)

        # First attempt
        error1 = TranslationRetryableError(
            message="First attempt",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Initial feedback",
            retry_count=0
        )
        assert error1.retry_count == 0

        # Second attempt
        error2 = TranslationRetryableError(
            message="Second attempt",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Updated feedback",
            retry_count=1
        )
        assert error2.retry_count == 1

        # Third attempt
        error3 = TranslationRetryableError(
            message="Third attempt",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Final feedback",
            retry_count=2
        )
        assert error3.retry_count == 2

    def test_with_complex_validation_result(self):
        """Test TranslationRetryableError with complex validation result."""
        validation_result = ValidationResult(
            valid=False,
            issues=[
                ValidationIssue(
                    severity="error",
                    rule="formatting",
                    message="Inconsistent formatting",
                    location="segment 5"
                ),
                ValidationIssue(
                    severity="warning",
                    rule="terminology",
                    message="Inconsistent term usage"
                )
            ]
        )

        error = TranslationRetryableError(
            message="Retryable validation errors",
            file_path="/content/doc.md",
            validation_result=validation_result,
            retry_feedback="Maintain consistent formatting and terminology",
            retry_count=1
        )

        assert len(error.validation_result.issues) == 2
        assert len(error.validation_result.errors) == 1
        assert len(error.validation_result.warnings) == 1

    def test_with_empty_retry_feedback(self):
        """Test TranslationRetryableError with empty retry feedback."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback=""
        )

        assert error.retry_feedback == ""

    def test_with_none_validation_result(self):
        """Test TranslationRetryableError handles None validation_result."""
        # This tests that the exception can be created with None,
        # though in production this should be avoided
        error = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=None,
            retry_feedback="Test"
        )

        assert error.validation_result is None

    def test_missing_required_field_raises_type_error(self):
        """Test that missing required fields raise TypeError."""
        validation_result = ValidationResult(valid=False)

        with pytest.raises(TypeError):
            # Missing retry_feedback parameter
            TranslationRetryableError(
                message="Test",
                file_path="/test.md",
                validation_result=validation_result
            )


class TestExceptionInheritance:
    """Tests for exception inheritance hierarchy."""

    def test_rejected_error_is_translation_error(self):
        """Test TranslationRejectedError is a TranslationError."""
        validation_result = ValidationResult(valid=False)
        error = TranslationRejectedError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        assert isinstance(error, TranslationError)

    def test_retryable_error_is_translation_error(self):
        """Test TranslationRetryableError is a TranslationError."""
        validation_result = ValidationResult(valid=False)
        error = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Test"
        )

        assert isinstance(error, TranslationError)

    def test_both_inherit_from_exception(self):
        """Test both exceptions inherit from base Exception."""
        validation_result = ValidationResult(valid=False)

        rejected = TranslationRejectedError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        retryable = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Test"
        )

        assert isinstance(rejected, Exception)
        assert isinstance(retryable, Exception)

    def test_can_catch_both_as_translation_error(self):
        """Test that both exceptions can be caught as TranslationError."""
        validation_result = ValidationResult(valid=False)

        # Test with TranslationRejectedError
        try:
            raise TranslationRejectedError(
                message="Test",
                file_path="/test.md",
                validation_result=validation_result,
                rejection_reason="Test"
            )
        except TranslationError as e:
            assert isinstance(e, TranslationRejectedError)

        # Test with TranslationRetryableError
        try:
            raise TranslationRetryableError(
                message="Test",
                file_path="/test.md",
                validation_result=validation_result,
                retry_feedback="Test"
            )
        except TranslationError as e:
            assert isinstance(e, TranslationRetryableError)

    def test_exceptions_are_distinct_types(self):
        """Test that the two exception types are distinct."""
        validation_result = ValidationResult(valid=False)

        rejected = TranslationRejectedError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        retryable = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Test"
        )

        assert type(rejected) != type(retryable)
        assert not isinstance(rejected, TranslationRetryableError)
        assert not isinstance(retryable, TranslationRejectedError)


class TestExceptionEdgeCases:
    """Tests for edge cases and error conditions."""

    def test_rejected_error_with_long_message(self):
        """Test TranslationRejectedError with very long message."""
        validation_result = ValidationResult(valid=False)
        long_message = "Error: " + "x" * 1000

        error = TranslationRejectedError(
            message=long_message,
            file_path="/test.md",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        assert len(str(error)) == len(long_message)

    def test_retryable_error_with_large_retry_count(self):
        """Test TranslationRetryableError with large retry count."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRetryableError(
            message="Test",
            file_path="/test.md",
            validation_result=validation_result,
            retry_feedback="Test",
            retry_count=999
        )

        assert error.retry_count == 999

    def test_unicode_in_file_paths(self):
        """Test exceptions with unicode characters in file paths."""
        validation_result = ValidationResult(valid=False)

        rejected = TranslationRejectedError(
            message="Test",
            file_path="/content/文档.md",
            validation_result=validation_result,
            rejection_reason="Test"
        )

        retryable = TranslationRetryableError(
            message="Test",
            file_path="/content/документ.md",
            validation_result=validation_result,
            retry_feedback="Test"
        )

        assert rejected.file_path == "/content/文档.md"
        assert retryable.file_path == "/content/документ.md"

    def test_unicode_in_messages(self):
        """Test exceptions with unicode characters in messages."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRejectedError(
            message="翻訳が拒否されました",
            file_path="/test.md",
            validation_result=validation_result,
            rejection_reason="Перевод отклонен"
        )

        assert str(error) == "翻訳が拒否されました"
        assert error.rejection_reason == "Перевод отклонен"

    def test_special_characters_in_paths(self):
        """Test exceptions with special characters in file paths."""
        validation_result = ValidationResult(valid=False)

        error = TranslationRetryableError(
            message="Test",
            file_path="/content/file with spaces & special-chars_123.md",
            validation_result=validation_result,
            retry_feedback="Test"
        )

        assert error.file_path == "/content/file with spaces & special-chars_123.md"
