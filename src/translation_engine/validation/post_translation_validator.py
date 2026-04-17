"""
Post-translation validation framework.

This module provides the foundational classes and enums for automated validation
decision-making (ACCEPT/RETRY/REJECT) in the hugo-translator validation engine.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass
from enum import IntEnum
from typing import Any

from .base import ValidationResult


class ValidationDecision(IntEnum):
    """Decision outcome for translation validation.

    The enum values are explicitly set to integers for stable serialization
    and version compatibility across system updates.

    Attributes:
        ACCEPT (0): Translation meets quality standards, proceed to write to disk.
        RETRY (1): Translation has fixable issues, retry with feedback.
        REJECT (2): Translation has critical errors, discard and do not write.

    Example:
        >>> decision = ValidationDecision.ACCEPT
        >>> decision == 0
        True
        >>> decision < ValidationDecision.RETRY
        True
    """

    ACCEPT = 0
    RETRY = 1
    REJECT = 2


@dataclass
class DecisionResult:
    """Result of validation decision engine analysis.

    Contains the decision outcome, explanation, and optional retry feedback
    for translation validation results.

    Attributes:
        decision: ACCEPT/RETRY/REJECT outcome from decision engine.
        decision_reason: Human-readable explanation of why this decision was made.
        retry_feedback: Optional feedback for retry attempt (None if not retrying).
        validation_result: Full validation result details from validators.

    Example:
        >>> result = DecisionResult(
        ...     decision=ValidationDecision.ACCEPT,
        ...     decision_reason="All validation checks passed",
        ...     retry_feedback=None,
        ...     validation_result=validation_result
        ... )
        >>> result.decision == ValidationDecision.ACCEPT
        True
    """

    decision: ValidationDecision
    decision_reason: str
    retry_feedback: str | None
    validation_result: ValidationResult


class PostTranslationValidator(ABC):
    """Base class for post-translation validators.

    Validators check translation quality after model generation but before
    or after writing to disk. This abstract base class defines the contract
    that all post-translation validators must implement.

    Validators can operate in two phases:
    - Pre-write: Check quality before writing translation to disk
    - Post-write: Verify written files after disk write

    Subclasses must implement the validate() method to perform their specific
    validation logic.

    Example:
        >>> class MyValidator(PostTranslationValidator):
        ...     def validate(self, source: str, translation: str, context: Dict[str, Any]) -> ValidationResult:
        ...         # Validation logic here
        ...         return ValidationResult(success=True)
    """

    def __init__(self, name: str | None = None):
        """
        Initialize validator.

        Args:
            name: Optional custom name for this validator instance
        """
        self.name = name or self.__class__.__name__

    @abstractmethod
    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate translation quality.

        Implementations should check translation quality against source text
        and return a ValidationResult indicating any issues found.

        Args:
            source: Original source text to validate against.
            translation: Translated text to validate.
            context: Optional validation context (frontmatter, site profile,
                language pair, file path, etc.). Extensible dictionary to avoid
                breaking signature changes.

        Returns:
            ValidationResult containing success status and any validation issues found.

        Raises:
            NotImplementedError: If subclass does not implement this method.
        """
        pass
