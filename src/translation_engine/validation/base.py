"""
Base validator classes and shared validation models.
"""

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from typing import Any


class ValidationSeverity(str, Enum):
    """Severity levels for validation issues."""

    ERROR = "error"  # Critical issues that must be fixed
    WARNING = "warning"  # Issues that should be reviewed
    INFO = "info"  # Informational notices


@dataclass
class ValidationIssue:
    """A single validation issue."""

    severity: ValidationSeverity
    validator: str  # Name of validator that found this issue
    message: str
    location: str | None = None  # Where in the document (e.g., "frontmatter.title", "line 42")
    details: dict[str, Any] | None = None

    def __str__(self) -> str:
        """Human-readable representation."""
        parts = [f"[{self.severity.value.upper()}]", f"{self.validator}:", self.message]
        if self.location:
            parts.insert(2, f"at {self.location}")
        return " ".join(parts)


@dataclass
class ValidationResult:
    """Result of validating a translation."""

    success: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    file_path: Path | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def error_count(self) -> int:
        """Count of error-level issues."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.ERROR)

    @property
    def warning_count(self) -> int:
        """Count of warning-level issues."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.WARNING)

    @property
    def info_count(self) -> int:
        """Count of info-level issues."""
        return sum(1 for issue in self.issues if issue.severity == ValidationSeverity.INFO)

    def filter_by_severity(self, severity: ValidationSeverity) -> list[ValidationIssue]:
        """Get issues of specific severity."""
        return [issue for issue in self.issues if issue.severity == severity]

    def has_errors(self) -> bool:
        """Check if there are any error-level issues."""
        return self.error_count > 0

    def has_warnings(self) -> bool:
        """Check if there are any warning-level issues."""
        return self.warning_count > 0

    def merge(self, other: "ValidationResult") -> "ValidationResult":
        """Merge another result into this one."""
        self.issues.extend(other.issues)
        self.success = self.success and other.success
        self.metadata.update(other.metadata)
        return self


class Validator(ABC):
    """
    Base class for all validators.

    Validators check specific aspects of translation quality:
    - YAML syntax
    - Placeholder integrity
    - Markdown structure
    - Link validity
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
        """
        Validate a translation against its source.

        Args:
            source: Original source text
            translation: Translated text
            context: Optional context (language pair, file path, etc.)

        Returns:
            ValidationResult with any issues found
        """
        pass

    def create_issue(
        self,
        severity: ValidationSeverity,
        message: str,
        location: str | None = None,
        details: dict[str, Any] | None = None,
    ) -> ValidationIssue:
        """
        Helper to create a validation issue.

        Args:
            severity: Issue severity level
            message: Human-readable message
            location: Optional location in document
            details: Optional additional details

        Returns:
            ValidationIssue instance
        """
        return ValidationIssue(
            severity=severity,
            validator=self.name,
            message=message,
            location=location,
            details=details,
        )
