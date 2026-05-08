"""
MetadataMarkdownContaminationValidator — RC-D prevention.

Prevents Markdown heading markers (# / ## / ###) from being injected into
YAML frontmatter scalar fields during translation.

Observed failure mode (RC-D): English source titles end with 'C#' (the
programming language). The MT model produces a translated title that ends
with an orphaned '#' because it treated the '#' as a Markdown heading marker.
Example:
    EN: "How to Read Barcodes Using C#"
    JA: "C#を使用してバーコードを読み取る方法#"   ← trailing # is wrong

Similarly, some models prefix translated titles with '# ' (a heading marker):
    KO: "# C#를 사용하여 바코드를 읽는 방법"     ← leading # is wrong

Checked fields: title, description, linktitle, head_title, head_description,
seoTitle, summary, step1…step10.

All violations are reported as ERRORs (fail-closed).

Safe pattern: The regex deliberately excludes '#' that is immediately preceded
by 'C' or 'c' to preserve valid 'C#' references in translated text.
"""

from __future__ import annotations

import re
from typing import Any

import yaml

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator

# Fields to inspect for Markdown contamination
_CHECKED_FIELDS: frozenset[str] = frozenset(
    ["title", "description", "linktitle", "head_title", "head_description",
     "seoTitle", "summary"]
    + [f"step{i}" for i in range(1, 11)]
)

# Leading heading marker: value starts with one or more '#' followed by space
_LEADING_HASH_RE = re.compile(r"^#{1,6}\s+")

# Trailing orphaned '#': value ends with '#' or '#.' NOT preceded by C or c.
# This preserves 'C#' (programming language) while catching orphaned hashes.
_TRAILING_HASH_RE = re.compile(r"(?<![Cc])#\.?\s*$")


def _parse_frontmatter(text: str) -> dict | None:
    """Extract and parse YAML frontmatter from Markdown text.

    Returns parsed dict or None if frontmatter cannot be parsed.
    """
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    try:
        fm = yaml.safe_load(parts[1])
        return fm if isinstance(fm, dict) else None
    except yaml.YAMLError:
        return None


class MetadataMarkdownContaminationValidator(PostTranslationValidator):
    """Detects Markdown heading markers injected into frontmatter scalar fields.

    Validates that translated frontmatter fields do not contain leading or
    trailing Markdown heading markers ('#'). These are injected by MT models
    that incorrectly treat the '#' in 'C#' as a Markdown heading indicator.

    All violations are ERRORs — Markdown-contaminated titles cannot be
    published because they render as broken headings or expose raw '#' chars.
    """

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Check translated frontmatter fields for Markdown heading contamination.

        Args:
            source: Original source Markdown text (used for context only).
            translation: Translated Markdown text to validate.
            context: Optional validation context dict.

        Returns:
            ValidationResult with ERROR issues for any contaminated fields.
        """
        fm = _parse_frontmatter(translation)
        if fm is None:
            # Cannot parse frontmatter — other validators will catch this.
            return ValidationResult(
                success=True,
                issues=[],
                metadata={"validator": self.name, "skipped": "no_frontmatter"},
            )

        issues: list[ValidationIssue] = []

        for field in _CHECKED_FIELDS:
            value = fm.get(field)
            if not isinstance(value, str) or not value:
                continue

            if _LEADING_HASH_RE.match(value):
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"RC-D: frontmatter field '{field}' starts with a Markdown "
                            f"heading marker. Value: {value[:80]!r}"
                        ),
                        validator=self.name,
                        location=f"frontmatter.{field}",
                    )
                )
            elif _TRAILING_HASH_RE.search(value):
                issues.append(
                    ValidationIssue(
                        severity=ValidationSeverity.ERROR,
                        message=(
                            f"RC-D: frontmatter field '{field}' ends with an orphaned '#' "
                            f"(not preceded by 'C'/'c'). Value: {value[:80]!r}"
                        ),
                        validator=self.name,
                        location=f"frontmatter.{field}",
                    )
                )

        return ValidationResult(
            success=len(issues) == 0,
            issues=issues,
            metadata={"validator": self.name, "checked_fields": len(_CHECKED_FIELDS)},
        )
