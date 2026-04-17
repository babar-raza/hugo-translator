"""
Validator for ensuring Hugo shortcodes are preserved exactly in translation.

This validator checks that all Hugo shortcodes from source text are present
and unchanged in the translated text. Hugo shortcodes are special markup
that must not be translated or modified.
"""

import re
from collections import Counter
from typing import Any

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator


class ShortcodePreservationValidator(PostTranslationValidator):
    """Validates that Hugo shortcodes are preserved exactly in translation.

    Hugo shortcodes come in several forms:
    - {{< shortcode >}} - self-closing or opening tag
    - {{< /shortcode >}} - closing tag
    - {{% shortcode %}} - with inner content processing
    - {{% /shortcode %}} - closing tag with processing
    - {{/* comment */}} - comments

    Checks:
    - All source shortcodes present in translation
    - Shortcode count matches source
    - No new shortcodes added in translation
    - Parameters unchanged

    Example:
        validator = ShortcodePreservationValidator()
        result = validator.validate(source, translation, context)
    """

    # Hugo shortcode patterns
    # These patterns match all forms of Hugo shortcodes with normalized whitespace
    SHORTCODE_PATTERNS = [
        r'\{\{<\s*[^>]*>\}\}',      # {{< shortcode >}} or {{< /shortcode >}}
        r'\{\{%\s*[^%]*%\}\}',      # {{% shortcode %}} or {{% /shortcode %}}
        r'\{\{/\*.*?\*/\}\}',       # {{/* comment */}}
    ]

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate shortcode preservation.

        Args:
            source: Original source text
            translation: Translated text
            context: Validation context (optional)

        Returns:
            ValidationResult with shortcode issues
        """
        issues = []

        # Extract shortcodes from source and translation
        source_shortcodes = self._extract_shortcodes(source)
        translation_shortcodes = self._extract_shortcodes(translation)

        # Check count match - ERROR only if translation has FEWER shortcodes
        if len(translation_shortcodes) < len(source_shortcodes):
            issues.append(ValidationIssue(
                validator="ShortcodePreservationValidator",
                severity=ValidationSeverity.ERROR,
                message=f"Shortcode count mismatch: source has {len(source_shortcodes)}, translation has {len(translation_shortcodes)}",
                location="shortcodes",
            ))

        # Check each source shortcode exists in translation
        source_counter = Counter(source_shortcodes)
        translation_counter = Counter(translation_shortcodes)

        for shortcode, count in source_counter.items():
            if shortcode not in translation_counter:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Shortcode missing in translation: {shortcode}",
                    location="shortcodes",
                ))
            elif translation_counter[shortcode] < count:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Shortcode count reduced: {shortcode} appears {count} times in source but {translation_counter[shortcode]} in translation",
                    location="shortcodes",
                ))

        # Check for new/corrupted shortcodes in translation
        for shortcode in translation_counter:
            if shortcode not in source_counter:
                issues.append(ValidationIssue(
                    validator="ShortcodePreservationValidator",
                    severity=ValidationSeverity.WARNING,
                    message=f"Unexpected shortcode in translation: {shortcode}",
                    location="shortcodes",
                ))

        return ValidationResult(
            success=len([i for i in issues if i.severity == ValidationSeverity.ERROR]) == 0,
            issues=issues,
            metadata={
                "source_shortcode_count": len(source_shortcodes),
                "translation_shortcode_count": len(translation_shortcodes),
            }
        )

    def _extract_shortcodes(self, text: str) -> list[str]:
        """Extract all Hugo shortcodes from text.

        Args:
            text: Markdown text potentially containing shortcodes

        Returns:
            List of shortcodes found (normalized)
        """
        shortcodes = []
        for pattern in self.SHORTCODE_PATTERNS:
            matches = re.findall(pattern, text, re.DOTALL)
            # Normalize whitespace for comparison
            normalized = [re.sub(r'\s+', ' ', m).strip() for m in matches]
            shortcodes.extend(normalized)
        return shortcodes
