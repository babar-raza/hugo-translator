"""
Completeness validator for translation quality assurance.

This module validates that all source segments have been translated with 100% coverage.
"""

import re
from typing import Any, Dict, Optional

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator


class CompletenessValidator(PostTranslationValidator):
    """Validates that all source segments have been translated.

    Checks:
    - All extracted segments have corresponding translations
    - No missing translations in the translation map
    - No untranslated placeholder text remains
    - Translation coverage is 100%

    Example:
        validator = CompletenessValidator()
        result = validator.validate(
            source=source_text,
            translation=translated_text,
            context=validation_context
        )
        if result.has_errors():
            print(f"Missing segments: {result.error_count}")
    """

    def validate(
        self,
        source: str,
        translation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Validate translation completeness.

        Args:
            source: Original source text
            translation: Translated text
            context: Contains segments, translation map, placeholders

        Returns:
            ValidationResult with completeness issues
        """
        if context is None:
            context = {}

        issues = []

        # Check 1: All segments have translations
        translation_map = context.get("translation_map", {})
        source_segments = context.get("source_segments", [])

        for segment_id, segment_text in enumerate(source_segments):
            if segment_id not in translation_map:
                issues.append(
                    ValidationIssue(
                        validator="CompletenessValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Segment {segment_id} not translated",
                        location=f"segment_{segment_id}",
                        details={"suggestion": "Ensure all segments passed to translation model"},
                    )
                )

        # Check 2: No empty translations
        for segment_id, translated_text in translation_map.items():
            if not translated_text or translated_text.strip() == "":
                issues.append(
                    ValidationIssue(
                        validator="CompletenessValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Segment {segment_id} has empty translation",
                        location=f"segment_{segment_id}",
                        details={"suggestion": "Translation must not be empty"},
                    )
                )

        # Check 3: No untranslated placeholders
        placeholder_pattern = r"\{PLACEHOLDER_\d+\}|\{TERM_\d+\}|\{SHORTCODE_\d+\}"
        untranslated_placeholders = re.findall(placeholder_pattern, translation)

        if untranslated_placeholders:
            # Show first 5 placeholders in the suggestion
            placeholder_sample = untranslated_placeholders[:5]
            issues.append(
                ValidationIssue(
                    validator="CompletenessValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Found {len(untranslated_placeholders)} untranslated placeholders",
                    location="translation_output",
                    details={
                        "suggestion": f"Placeholders must be restored: {placeholder_sample}",
                        "untranslated_count": len(untranslated_placeholders),
                    },
                )
            )

        # Calculate coverage
        total_segments = len(source_segments)
        translated_segments = len(
            [t for t in translation_map.values() if t and t.strip()]
        )
        coverage = (
            (translated_segments / total_segments * 100) if total_segments > 0 else 0.0
        )

        return ValidationResult(
            success=len(issues) == 0,
            issues=issues,
            metadata={"coverage_percent": coverage},
        )
