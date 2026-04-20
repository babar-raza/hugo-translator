"""
Completeness validator for translation quality assurance.

This module validates that all source segments have been translated with 100% coverage.
"""

import re
from typing import Any

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
        context: dict[str, Any] | None = None,
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

        # Check 4: Document-level length ratio (detects severe truncation)
        # Strip frontmatter (---...---) and code blocks (```...```) before comparing.
        # Conservative floor: 0.30 (translation must be at least 30% of source length).
        # CJK scripts are naturally compact; the 0.30 floor is intentionally loose.
        self._check_length_ratio(source, translation, issues)

        return ValidationResult(
            success=len(issues) == 0,
            issues=issues,
            metadata={"coverage_percent": coverage},
        )

    def _check_length_ratio(
        self,
        source: str,
        translation: str,
        issues: list,
    ) -> None:
        """Detect severe truncation by comparing document character lengths.

        Strips frontmatter and fenced code blocks before comparing so that
        code-heavy articles don't produce false positives. The min ratio (0.30)
        is conservative enough to allow compact CJK output without flagging it.

        Args:
            source: Source document text
            translation: Translated document text
            issues: List to append ValidationIssue objects to
        """
        MIN_RATIO = 0.30
        MAX_RATIO = 4.0
        MIN_SOURCE_LEN = 100  # Skip very short documents

        def _strip_boilerplate(text: str) -> str:
            # Remove YAML frontmatter
            text = re.sub(r'^---\s*\n.*?\n---\s*\n', '', text, flags=re.DOTALL)
            # Remove fenced code blocks
            text = re.sub(r'```.*?```', '', text, flags=re.DOTALL)
            return text.strip()

        src_clean = _strip_boilerplate(source)
        trn_clean = _strip_boilerplate(translation)

        src_len = len(src_clean)
        trn_len = len(trn_clean)

        if src_len < MIN_SOURCE_LEN:
            return  # Too short to be meaningful

        ratio = trn_len / src_len if src_len > 0 else 1.0

        if ratio < MIN_RATIO:
            issues.append(
                ValidationIssue(
                    validator="CompletenessValidator",
                    severity=ValidationSeverity.ERROR,
                    message=(
                        f"Translation severely truncated: {trn_len} chars vs "
                        f"{src_len} source chars (ratio {ratio:.2f}, min {MIN_RATIO})"
                    ),
                    location="document",
                    details={
                        "ratio": ratio,
                        "src_len": src_len,
                        "trn_len": trn_len,
                        "suggestion": "Translation appears truncated — check for LLM cutoff",
                    },
                )
            )
        elif ratio > MAX_RATIO:
            issues.append(
                ValidationIssue(
                    validator="CompletenessValidator",
                    severity=ValidationSeverity.WARNING,
                    message=(
                        f"Translation unusually long: {trn_len} chars vs "
                        f"{src_len} source chars (ratio {ratio:.2f})"
                    ),
                    location="document",
                    details={"ratio": ratio, "src_len": src_len, "trn_len": trn_len},
                )
            )
