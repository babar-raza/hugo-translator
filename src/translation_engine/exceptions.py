"""
Exception types for translation engine operations.

This module defines the exception hierarchy for the translation engine,
including specialized exceptions for validation failures and retryable errors.
"""

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .models import ValidationResult


class TranslationError(Exception):
    """Base exception for translation engine errors.

    All translation-related exceptions inherit from this base class,
    allowing for consistent error handling throughout the pipeline.
    """
    pass


class TranslationRejectedError(TranslationError):
    """Raised when translation is rejected due to critical validation failures.

    This exception indicates that the translation has failed validation checks
    and cannot be accepted. The translation should not be retried without
    addressing the underlying issues.

    Attributes:
        file_path: Path to source file that was being translated
        validation_result: Full validation result with detailed issues
        rejection_reason: Human-readable reason for rejection

    Example:
        >>> error = TranslationRejectedError(
        ...     message="Translation failed critical validation",
        ...     file_path="/content/post.md",
        ...     validation_result=result,
        ...     rejection_reason="Front matter structure invalid"
        ... )
        >>> raise error
    """

    def __init__(
        self,
        message: str,
        file_path: str,
        validation_result: 'ValidationResult',
        rejection_reason: str
    ):
        """Initialize TranslationRejectedError.

        Args:
            message: Error message describing the rejection
            file_path: Path to the file being translated
            validation_result: Full validation result with issues
            rejection_reason: Human-readable reason for rejection
        """
        super().__init__(message)
        self.file_path = file_path
        self.validation_result = validation_result
        self.rejection_reason = rejection_reason


class TranslationRetryableError(TranslationError):
    """Raised when translation can be retried with feedback.

    This exception indicates that the translation has encountered issues
    that can potentially be corrected through a retry with additional
    feedback or context. The error includes retry-specific information
    to guide the retry attempt.

    Attributes:
        file_path: Path to source file that was being translated
        validation_result: Full validation result with detailed issues
        retry_feedback: Feedback to include in retry attempt
        retry_count: Number of retries attempted so far (default: 0)

    Example:
        >>> error = TranslationRetryableError(
        ...     message="Translation validation failed, retry possible",
        ...     file_path="/content/post.md",
        ...     validation_result=result,
        ...     retry_feedback="Preserve code block formatting",
        ...     retry_count=1
        ... )
        >>> raise error
    """

    def __init__(
        self,
        message: str,
        file_path: str,
        validation_result: 'ValidationResult',
        retry_feedback: str,
        retry_count: int = 0
    ):
        """Initialize TranslationRetryableError.

        Args:
            message: Error message describing the retryable failure
            file_path: Path to the file being translated
            validation_result: Full validation result with issues
            retry_feedback: Feedback to provide to the retry attempt
            retry_count: Number of retries attempted so far (default: 0)
        """
        super().__init__(message)
        self.file_path = file_path
        self.validation_result = validation_result
        self.retry_feedback = retry_feedback
        self.retry_count = retry_count
