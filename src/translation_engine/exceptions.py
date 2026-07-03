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


class TranslationIncomplete(TranslationError):
    """Raised when a translation pass leaves too many units untranslated.

    TC-AST-01: When the fraction of fallback (untranslated) nodes exceeds
    ``ast_fallback_node_tolerance`` in ``config/global.yaml``, the output would
    contain source-language text mixed into the target-language document.

    TC-SAS-01: When the fraction of translatable units returned same-as-source
    (model returned source text unchanged) exceeds ``same_as_source_tolerance``
    in ``config/global.yaml``, the output would contain undetected source-language
    leakage. Excluded: ``do_not_translate=True`` units (preserved YAML fields, code).

    The engine must treat both cases as a blocking failure rather than writing the file.

    Attributes:
        missing_count: Number of AST nodes with no translation unit.
        total_count: Total translatable AST nodes checked.
        ratio: ``missing_count / total_count``.
        tolerance: Configured tolerance threshold (0.0 = zero tolerance).
    """

    def __init__(
        self,
        message: str,
        missing_count: int = 0,
        total_count: int = 0,
        ratio: float = 0.0,
        tolerance: float = 0.0,
    ):
        super().__init__(message)
        self.missing_count = missing_count
        self.total_count = total_count
        self.ratio = ratio
        self.tolerance = tolerance


class ShutdownRequested(TranslationError):
    """Raised when graceful shutdown is requested during translation.

    SR-02: This exception enables CTRL+C to interrupt file translation
    by allowing the translation loop to check for shutdown requests
    periodically and cleanly exit mid-file instead of only between files.

    When this exception is raised:
    1. The current file's translated segments are saved to the L3 index
    2. The file is marked as incomplete in the progress tracker
    3. The translation engine performs its shutdown sequence
    4. The application exits gracefully

    Attributes:
        file_path: Path to file being translated when shutdown was requested
        segments_completed: Number of segments successfully translated before shutdown

    Example:
        >>> if self._check_shutdown():
        ...     raise ShutdownRequested(
        ...         file_path="/content/post.md",
        ...         segments_completed=15
        ...     )
    """

    def __init__(self, file_path: str = "", segments_completed: int = 0):
        """Initialize ShutdownRequested.

        Args:
            file_path: Path to the file being translated
            segments_completed: Number of segments completed before shutdown
        """
        message = "Shutdown requested"
        if file_path:
            message += f" while translating {file_path}"
        if segments_completed > 0:
            message += f" (completed {segments_completed} segments)"

        super().__init__(message)
        self.file_path = file_path
        self.segments_completed = segments_completed
