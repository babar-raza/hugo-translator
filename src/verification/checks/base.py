"""
Base classes for verification checks.

Provides abstract base class for pluggable verification checks and
dataclasses for verification issues and results.
"""
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Literal


class IssueSeverity(str, Enum):
    """Severity level for verification issues."""

    ERROR = "error"
    WARNING = "warning"
    INFO = "info"


@dataclass
class VerificationIssue:
    """
    A single verification issue found during post-translation checks.

    Attributes:
        severity: Issue severity level (error, warning, info)
        check_name: Name of the check that found this issue
        location: Path to the problematic field (e.g., "frontmatter.body.block[0].title_left")
        message: Human-readable description of the issue
        source_text: Optional source text that was expected
        translated_text: Optional translated text that has the issue
        metadata: Additional context-specific data
    """

    severity: Literal["error", "warning", "info"]
    check_name: str
    location: str
    message: str
    source_text: str | None = None
    translated_text: str | None = None
    metadata: dict[str, Any] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        result = {
            "severity": self.severity,
            "check_name": self.check_name,
            "location": self.location,
            "message": self.message,
        }
        if self.source_text:
            result["source_text"] = self.source_text[:200]  # Truncate for readability
        if self.translated_text:
            result["translated_text"] = self.translated_text[:200]
        if self.metadata:
            result["metadata"] = self.metadata
        return result


@dataclass
class VerificationResult:
    """
    Result of verification checks on a translated document.

    Attributes:
        passed: Whether all checks passed (no errors)
        issues: List of verification issues found
        check_results: Per-check result summaries
        metadata: Additional result metadata
    """

    issues: list[VerificationIssue] = field(default_factory=list)
    check_results: dict[str, dict[str, Any]] = field(default_factory=dict)
    metadata: dict[str, Any] = field(default_factory=dict)

    @property
    def passed(self) -> bool:
        """Check if verification passed (no errors)."""
        return not any(
            issue.severity == "error" for issue in self.issues
        )

    @property
    def error_count(self) -> int:
        """Count of error-severity issues."""
        return sum(1 for issue in self.issues if issue.severity == "error")

    @property
    def warning_count(self) -> int:
        """Count of warning-severity issues."""
        return sum(1 for issue in self.issues if issue.severity == "warning")

    @property
    def info_count(self) -> int:
        """Count of info-severity issues."""
        return sum(1 for issue in self.issues if issue.severity == "info")

    def add_issue(self, issue: VerificationIssue) -> None:
        """Add an issue to the result."""
        self.issues.append(issue)

    def merge(self, other: "VerificationResult") -> None:
        """Merge another result into this one."""
        self.issues.extend(other.issues)
        self.check_results.update(other.check_results)

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary for serialization."""
        return {
            "passed": self.passed,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
            "info_count": self.info_count,
            "issues": [issue.to_dict() for issue in self.issues],
            "check_results": self.check_results,
            "metadata": self.metadata,
        }


class VerificationCheck(ABC):
    """
    Abstract base class for verification checks.

    Subclasses implement specific verification logic (e.g., language detection,
    completeness checking, truncation detection).

    Example:
        class LanguageDetectionCheck(VerificationCheck):
            def run(self, source, translated, target_lang) -> List[VerificationIssue]:
                # Implementation here
                pass
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Unique name for this check."""
        pass

    @abstractmethod
    def run(
        self,
        source: dict[str, Any],
        translated: dict[str, Any],
        target_lang: str,
        context: dict[str, Any] | None = None,
    ) -> list[VerificationIssue]:
        """
        Run verification check on translated content.

        Args:
            source: Source document data (frontmatter + body)
            translated: Translated document data
            target_lang: Target language code (e.g., "de", "fr")
            context: Optional additional context (site profile, etc.)

        Returns:
            List of verification issues found (empty if check passes)
        """
        pass

    def is_enabled(self, context: dict[str, Any] | None = None) -> bool:
        """
        Check if this verification is enabled.

        Override in subclasses to implement conditional enabling.

        Args:
            context: Optional context with configuration

        Returns:
            True if check should run, False to skip
        """
        return True
