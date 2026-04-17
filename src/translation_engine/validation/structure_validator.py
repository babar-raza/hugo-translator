"""
Structure preservation validators for markdown and YAML.

Ensures that translation preserves the structure of the source:
- Markdown: headings, lists, code blocks, links, formatting
- YAML: comments, quotes, literal blocks, line counts
"""

import re
from dataclasses import dataclass, field
from typing import Any

import structlog

from .base import ValidationResult, ValidationSeverity, Validator

logger = structlog.get_logger(__name__)


class StructureValidator(Validator):
    """
    Validates markdown structure preservation.

    Checks:
    - Heading levels and count preserved
    - List structure preserved
    - Code block structure preserved
    - Link/image count preserved
    - Bold/italic formatting count preserved
    """

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate markdown structure preservation.

        Args:
            source: Source markdown text
            translation: Translated markdown text
            context: Optional context

        Returns:
            ValidationResult with any structure issues
        """
        result = ValidationResult(success=True)

        # Check headings
        self._check_headings(source, translation, result)

        # Check lists
        self._check_lists(source, translation, result)

        # Check code blocks
        self._check_code_blocks(source, translation, result)

        # Check links and images
        self._check_links(source, translation, result)

        # Check formatting
        self._check_formatting(source, translation, result)

        return result

    def _check_headings(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check heading structure.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_headings = self._extract_headings(source)
        translation_headings = self._extract_headings(translation)

        # Check count
        if len(source_headings) != len(translation_headings):
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"Heading count mismatch: source has {len(source_headings)}, translation has {len(translation_headings)}",
                    location="headings",
                    details={
                        "source_count": len(source_headings),
                        "translation_count": len(translation_headings),
                    },
                )
            )

        # Check levels
        if len(source_headings) == len(translation_headings):
            for i, (source_level, translation_level) in enumerate(
                zip(source_headings, translation_headings, strict=False)
            ):
                if source_level != translation_level:
                    result.issues.append(
                        self.create_issue(
                            ValidationSeverity.WARNING,
                            f"Heading level mismatch at position {i + 1}: source is h{source_level}, translation is h{translation_level}",
                            location=f"heading {i + 1}",
                            details={
                                "source_level": source_level,
                                "translation_level": translation_level,
                            },
                        )
                    )

    def _extract_headings(self, text: str) -> list[int]:
        """
        Extract heading levels from markdown.

        Args:
            text: Markdown text

        Returns:
            List of heading levels (1-6)
        """
        headings = []
        for match in re.finditer(r"^(#{1,6})\s+", text, re.MULTILINE):
            level = len(match.group(1))
            headings.append(level)
        return headings

    def _check_lists(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check list structure.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_lists = self._count_list_items(source)
        translation_lists = self._count_list_items(translation)

        if source_lists != translation_lists:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"List item count mismatch: source has {source_lists}, translation has {translation_lists}",
                    location="lists",
                    details={
                        "source_count": source_lists,
                        "translation_count": translation_lists,
                    },
                )
            )

    def _count_list_items(self, text: str) -> int:
        """
        Count list items in markdown.

        Args:
            text: Markdown text

        Returns:
            Total number of list items
        """
        # Match unordered (-/*/+) and ordered (1.) list items
        pattern = r"^[\s]*[-*+]|\d+\.\s+"
        return len(re.findall(pattern, text, re.MULTILINE))

    def _check_code_blocks(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check code block structure.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_blocks = self._count_code_blocks(source)
        translation_blocks = self._count_code_blocks(translation)

        if source_blocks != translation_blocks:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.ERROR,
                    f"Code block count mismatch: source has {source_blocks}, translation has {translation_blocks}",
                    location="code blocks",
                    details={
                        "source_count": source_blocks,
                        "translation_count": translation_blocks,
                    },
                )
            )
            result.success = False

    def _count_code_blocks(self, text: str) -> int:
        """
        Count code blocks (fenced and indented).

        Args:
            text: Markdown text

        Returns:
            Number of code blocks
        """
        # Count fenced code blocks (```)
        fenced = len(re.findall(r"^```", text, re.MULTILINE)) // 2

        # Count inline code (`)
        inline = len(re.findall(r"`[^`]+`", text))

        return fenced + inline

    def _check_links(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check link and image count.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_links = self._count_links(source)
        translation_links = self._count_links(translation)

        if source_links != translation_links:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"Link/image count mismatch: source has {source_links}, translation has {translation_links}",
                    location="links",
                    details={
                        "source_count": source_links,
                        "translation_count": translation_links,
                    },
                )
            )

    def _count_links(self, text: str) -> int:
        """
        Count links and images in markdown.

        Args:
            text: Markdown text

        Returns:
            Total number of links and images
        """
        # Match [text](url) and ![alt](url)
        links = len(re.findall(r"!?\[([^\]]+)\]\(([^)]+)\)", text))
        return links

    def _check_formatting(
        self, source: str, translation: str, result: ValidationResult
    ) -> None:
        """
        Check bold/italic formatting count.

        Args:
            source: Source text
            translation: Translation text
            result: ValidationResult to add issues to
        """
        source_bold = self._count_formatting(source, r"\*\*([^*]+)\*\*")
        translation_bold = self._count_formatting(translation, r"\*\*([^*]+)\*\*")

        if abs(source_bold - translation_bold) > 2:  # Allow small deviation
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.INFO,
                    f"Bold formatting count differs: source has {source_bold}, translation has {translation_bold}",
                    location="formatting",
                    details={
                        "source_count": source_bold,
                        "translation_count": translation_bold,
                    },
                )
            )

        source_italic = self._count_formatting(source, r"\*([^*]+)\*")
        translation_italic = self._count_formatting(translation, r"\*([^*]+)\*")

        if abs(source_italic - translation_italic) > 2:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.INFO,
                    f"Italic formatting count differs: source has {source_italic}, translation has {translation_italic}",
                    location="formatting",
                    details={
                        "source_count": source_italic,
                        "translation_count": translation_italic,
                    },
                )
            )

    def _count_formatting(self, text: str, pattern: str) -> int:
        """
        Count formatting markers.

        Args:
            text: Markdown text
            pattern: Regex pattern to match

        Returns:
            Count of matches
        """
        return len(re.findall(pattern, text))


# ============================================================================
# YAML Structure Validation (for Hugo frontmatter)
# ============================================================================


@dataclass
class YAMLStructureIssue:
    """A single YAML structural issue."""

    issue_type: str
    description: str
    severity: str  # 'warning' or 'error'


@dataclass
class YAMLStructureValidationResult:
    """Result of YAML structure validation."""

    source_lines: int
    target_lines: int
    line_drift_percent: float
    issues: list[YAMLStructureIssue] = field(default_factory=list)

    @property
    def is_valid(self) -> bool:
        """Check if validation passed (no errors, acceptable drift)."""
        return self.line_drift_percent < 20.0 and not any(
            i.severity == "error" for i in self.issues
        )


class YAMLStructureValidator:
    """
    Validates YAML structural parity between source and target files.

    Checks:
    - Line count drift percentage
    - Comment preservation (# Static, # Head, etc.)
    - Literal block scalar usage (|)
    - Overall structure integrity

    Use this validator to ensure translated Hugo frontmatter maintains
    the same structure as the original EN files.
    """

    def __init__(
        self,
        warn_threshold: float = 10.0,
        error_threshold: float = 20.0,
    ):
        """
        Initialize validator with thresholds.

        Args:
            warn_threshold: Drift percentage to trigger warning (default 10%)
            error_threshold: Drift percentage to trigger error (default 20%)
        """
        self.warn_threshold = warn_threshold
        self.error_threshold = error_threshold

    def validate(
        self,
        source_content: str,
        target_content: str,
    ) -> YAMLStructureValidationResult:
        """
        Compare source and target YAML structure.

        Args:
            source_content: Original source file content (EN)
            target_content: Translated target file content

        Returns:
            Validation result with drift metrics and list of issues
        """
        source_lines = len(source_content.strip().split("\n"))
        target_lines = len(target_content.strip().split("\n"))

        # Calculate drift percentage
        drift = (
            abs(source_lines - target_lines) / max(source_lines, 1) * 100
        )

        issues: list[YAMLStructureIssue] = []

        # Check line count drift
        if drift > self.error_threshold:
            issues.append(
                YAMLStructureIssue(
                    issue_type="line_count_drift",
                    description=(
                        f"Line count drift {drift:.1f}% exceeds error threshold "
                        f"{self.error_threshold}% (source: {source_lines}, target: {target_lines})"
                    ),
                    severity="error",
                )
            )
        elif drift > self.warn_threshold:
            issues.append(
                YAMLStructureIssue(
                    issue_type="line_count_drift",
                    description=(
                        f"Line count drift {drift:.1f}% exceeds warning threshold "
                        f"{self.warn_threshold}% (source: {source_lines}, target: {target_lines})"
                    ),
                    severity="warning",
                )
            )

        # Check for comment preservation
        self._check_comments(source_content, target_content, issues)

        # Check for literal block preservation
        self._check_literal_blocks(source_content, target_content, issues)

        result = YAMLStructureValidationResult(
            source_lines=source_lines,
            target_lines=target_lines,
            line_drift_percent=drift,
            issues=issues,
        )

        # Log validation result
        logger.info(
            "yaml_structure_validation",
            source_lines=source_lines,
            target_lines=target_lines,
            drift_percent=round(drift, 1),
            issue_count=len(issues),
            is_valid=result.is_valid,
        )

        return result

    def _check_comments(
        self,
        source: str,
        target: str,
        issues: list[YAMLStructureIssue],
    ) -> None:
        """Check that YAML section comments are preserved."""
        # Extract comments from source (lines starting with #)
        source_comments = set(re.findall(r"^#\s*\w+", source, re.MULTILINE))
        target_comments = set(re.findall(r"^#\s*\w+", target, re.MULTILINE))

        missing_comments = source_comments - target_comments
        for comment in missing_comments:
            issues.append(
                YAMLStructureIssue(
                    issue_type="missing_comment",
                    description=f'Comment "{comment}" from source not found in target',
                    severity="warning",
                )
            )

    def _check_literal_blocks(
        self,
        source: str,
        target: str,
        issues: list[YAMLStructureIssue],
    ) -> None:
        """Check that literal block scalars (|) are preserved."""
        source_literals = source.count(": |")
        target_literals = target.count(": |")

        if source_literals > 0 and target_literals < source_literals:
            issues.append(
                YAMLStructureIssue(
                    issue_type="literal_block_loss",
                    description=(
                        f"Source has {source_literals} literal blocks, "
                        f"target has {target_literals}"
                    ),
                    severity="warning",
                )
            )

    def validate_files(
        self,
        source_path: str,
        target_path: str,
    ) -> YAMLStructureValidationResult:
        """
        Validate structure between two files.

        Args:
            source_path: Path to source file
            target_path: Path to target file

        Returns:
            Validation result
        """
        from pathlib import Path

        source_content = Path(source_path).read_text(encoding="utf-8")
        target_content = Path(target_path).read_text(encoding="utf-8")

        return self.validate(source_content, target_content)
