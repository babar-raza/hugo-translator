"""
SHORTCODE-007: Regex Preservation Validator

Validates that preserve_patterns are preserved in translation via post-translation checking.

This replaces PlaceholderManager's in-band protection with post-translation validation.
If patterns are not preserved, the validation fails and triggers retry/fallback.
"""
import re
from typing import Any

from .base import ValidationResult, ValidationSeverity, Validator


class RegexPreservationValidator(Validator):
    """
    Validator for preserve_patterns integrity.

    Strategy (SHORTCODE-007 - Prompt 6):
    - No pre-translation substitution (PlaceholderManager disabled in AST path)
    - Post-translation validation checks that regex patterns are preserved
    - Validation failures trigger retry with smaller batches or mark NEEDS_REVIEW

    This validator ensures patterns like:
    - Hugo shortcodes: {{< ... >}}
    - Technical identifiers: SaveFormat.Pdf, Aspose.Words
    - URLs: https://example.com
    - File extensions: .docx, .pdf

    Are preserved exactly in the translation (count match + exact string match).
    """

    def __init__(
        self,
        preserve_patterns: list[str] | None = None,
        name: str | None = None,
        strict_mode: bool = False
    ):
        """
        Initialize regex preservation validator.

        Args:
            preserve_patterns: List of regex patterns to check for preservation
            name: Optional custom name
            strict_mode: If True, require exact match. If False, allow count match.
        """
        super().__init__(name or "RegexPreservationValidator")
        self.preserve_patterns = preserve_patterns or []
        self.strict_mode = strict_mode

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate that preserve_patterns are preserved in translation.

        Checks:
        1. Extract all regex matches from source
        2. Extract all regex matches from translation
        3. Verify count matches (or exact string matches in strict mode)

        Args:
            source: Original source text
            translation: Translated text
            context: Optional context (may contain preserve_patterns override)

        Returns:
            ValidationResult indicating if patterns are preserved
        """
        # Get patterns from context or use defaults
        patterns = context.get("preserve_patterns", self.preserve_patterns) if context else self.preserve_patterns

        if not patterns:
            # No patterns to validate
            return ValidationResult(success=True)

        issues = []

        for pattern_str in patterns:
            try:
                pattern = re.compile(pattern_str)

                # Extract matches from source
                source_matches = pattern.findall(source)
                translation_matches = pattern.findall(translation)

                # Check if counts match
                if len(source_matches) != len(translation_matches):
                    issues.append(
                        self.create_issue(
                            severity=ValidationSeverity.ERROR,
                            message=(
                                f"Pattern '{pattern_str}' count mismatch: "
                                f"source has {len(source_matches)} matches, "
                                f"translation has {len(translation_matches)} matches"
                            ),
                            details={
                                "pattern": pattern_str,
                                "source_matches": source_matches,
                                "translation_matches": translation_matches,
                                "source_text": source[:200],
                                "translation_text": translation[:200]
                            }
                        )
                    )
                    continue

                # In strict mode, check if exact strings are preserved
                if self.strict_mode and source_matches:
                    # Check if all source matches appear in translation matches
                    source_set = set(source_matches)
                    translation_set = set(translation_matches)

                    missing = source_set - translation_set
                    if missing:
                        issues.append(
                            self.create_issue(
                                severity=ValidationSeverity.ERROR,
                                message=(
                                    f"Pattern '{pattern_str}' exact match failure: "
                                    f"missing {len(missing)} unique matches in translation"
                                ),
                                details={
                                    "pattern": pattern_str,
                                    "missing_matches": list(missing),
                                    "source_matches": source_matches,
                                    "translation_matches": translation_matches
                                }
                            )
                        )

            except re.error as e:
                # Invalid regex pattern
                issues.append(
                    self.create_issue(
                        severity=ValidationSeverity.WARNING,
                        message=f"Invalid regex pattern '{pattern_str}': {str(e)}",
                        details={"pattern": pattern_str, "error": str(e)}
                    )
                )

        # Validation succeeds if no ERROR-level issues
        success = not any(issue.severity == ValidationSeverity.ERROR for issue in issues)

        return ValidationResult(
            success=success,
            issues=issues,
            metadata={
                "patterns_checked": len(patterns),
                "strict_mode": self.strict_mode
            }
        )


class ShortcodePreservationValidator(RegexPreservationValidator):
    """
    Specialized validator for Hugo shortcode preservation.

    SHORTCODE-007: After parser splits shortcodes into INLINE_HTML nodes,
    they should never appear in MT input and must be preserved in output.

    This validator ensures shortcodes are byte-for-byte identical in source and translation.
    """

    SHORTCODE_PATTERNS = [
        r'\{\{<[^>]*>\}\}',  # {{< shortcode >}}
        r'\{\{%[^%]*%\}\}',  # {{% shortcode %}}
        r'\{\{/\*.*?\*/\}\}',  # {{/* comment */}}
    ]

    def __init__(self, name: str | None = None):
        """Initialize shortcode preservation validator with default patterns."""
        super().__init__(
            preserve_patterns=self.SHORTCODE_PATTERNS,
            name=name or "ShortcodePreservationValidator",
            strict_mode=True  # Shortcodes must be exact matches
        )

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """
        Validate that Hugo shortcodes are preserved byte-for-byte.

        This is critical for SHORTCODE-007: shortcodes should never be translated
        and must appear identically in the output.
        """
        result = super().validate(source, translation, context)

        # Add additional metadata for debugging
        result.metadata.update({
            "validator_type": "shortcode_preservation",
            "shortcode_007_check": True
        })

        return result
