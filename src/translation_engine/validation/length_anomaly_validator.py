"""
Length anomaly validator for translation quality assurance.

This module detects abnormal translation lengths that indicate truncation,
hallucination, or translation model failure. Translations that are significantly
longer or shorter than their source indicate potential quality issues.

Checks:
- Character ratio anomaly (>3.0 = ERROR, >2.0 = WARNING)
- Word ratio anomaly (>2.5 = ERROR, >1.8 = WARNING)
- Language-specific multipliers (de: 1.2, ar: 0.8, zh: 0.7)
- Minimum segment length threshold to avoid false positives on short text

Example:
    validator = LengthAnomalyValidator(config={
        "max_char_ratio": 3.0,
        "max_word_ratio": 2.5,
        "language_multipliers": {"de": 1.2, "ar": 0.8, "zh": 0.7}
    })
    result = validator.validate(
        source=source_text,
        translation=translated_text,
        context={"target_language": "de"}
    )
    if result.has_errors():
        print(f"Length anomalies detected: {result.error_count} issues")
"""

import re
from typing import Any

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator


class LengthAnomalyValidator(PostTranslationValidator):
    """Validates that translations have reasonable length ratios compared to source.

    Detects two main types of length anomalies:
    1. Character-level ratio: Catches truncations and hallucinations at character level
    2. Word-level ratio: Provides language-aware length checking based on word count

    Language multipliers account for linguistic differences:
    - German (de): 1.2 - German expands text by ~20%
    - Arabic (ar): 0.8 - Arabic compresses text by ~20%
    - Chinese (zh): 0.7 - Chinese is highly compressed

    Example:
        validator = LengthAnomalyValidator()
        result = validator.validate(
            source="Hello world",
            translation="Hallo Welt sehr lang text",
            context={"target_language": "de"}
        )
    """

    # Default error and warning thresholds
    DEFAULT_MAX_CHAR_RATIO = 3.0
    DEFAULT_CHAR_RATIO_WARNING = 2.0
    DEFAULT_MAX_WORD_RATIO = 2.5
    DEFAULT_WORD_RATIO_WARNING = 1.8
    DEFAULT_MIN_SEGMENT_LENGTH = 10

    # Default language multipliers (expansiveness factor)
    DEFAULT_LANGUAGE_MULTIPLIERS = {
        "de": 1.2,  # German expands ~20%
        "ar": 0.8,  # Arabic compresses ~20%
        "zh": 0.7,  # Chinese is compact
    }

    def __init__(self, config: dict[str, Any] | None = None):
        """Initialize length anomaly validator.

        Args:
            config: Configuration dict with optional keys:
                - max_char_ratio (float): Max character ratio for ERROR (default: 3.0)
                - char_ratio_warning (float): Max character ratio for WARNING (default: 2.0)
                - max_word_ratio (float): Max word ratio for ERROR (default: 2.5)
                - word_ratio_warning (float): Max word ratio for WARNING (default: 1.8)
                - min_segment_length (int): Minimum segment length to check (default: 10)
                - language_multipliers (dict): Language-specific expansion factors
        """
        super().__init__()
        config = config or {}

        # Character ratio thresholds
        self.max_char_ratio = config.get("max_char_ratio", self.DEFAULT_MAX_CHAR_RATIO)
        self.char_ratio_warning = config.get("char_ratio_warning", self.DEFAULT_CHAR_RATIO_WARNING)

        # Word ratio thresholds
        self.max_word_ratio = config.get("max_word_ratio", self.DEFAULT_MAX_WORD_RATIO)
        self.word_ratio_warning = config.get("word_ratio_warning", self.DEFAULT_WORD_RATIO_WARNING)

        # Minimum segment length to check (avoid false positives on very short text)
        self.min_segment_length = config.get("min_segment_length", self.DEFAULT_MIN_SEGMENT_LENGTH)

        # Language-specific multipliers
        self.language_multipliers = config.get(
            "language_multipliers",
            self.DEFAULT_LANGUAGE_MULTIPLIERS
        )

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate translation for length anomalies.

        Args:
            source: Original source text
            translation: Translated text to check
            context: Optional context with 'target_language' and 'translation_map'

        Returns:
            ValidationResult with length anomaly issues
        """
        if context is None:
            context = {}

        issues = []
        target_language = context.get("target_language", "en")

        # Get language multiplier
        multiplier = self.language_multipliers.get(target_language, 1.0)

        # Get translation segments from context, or treat entire translation as single segment
        translation_map = context.get("translation_map", {})
        source_segments = context.get("source_segments", {})

        if not translation_map:
            # Fall back to treating entire text as single segment
            translation_map = {0: translation}
            source_segments = {0: source} if source else {}

        # Check each segment
        for segment_id, trans_text in translation_map.items():
            # Get corresponding source segment
            src_text = source_segments.get(segment_id, "") if isinstance(source_segments, dict) else ""

            if not src_text or len(src_text) < self.min_segment_length:
                # Skip segments below minimum length
                continue

            if not trans_text:
                # Skip empty translations (handled by completeness validator)
                continue

            # Check character ratio
            char_issues = self._check_character_ratio(
                src_text, trans_text, multiplier, segment_id
            )
            issues.extend(char_issues)

            # Check word ratio
            word_issues = self._check_word_ratio(
                src_text, trans_text, multiplier, segment_id
            )
            issues.extend(word_issues)

        # Determine success based on whether we have errors
        has_errors = any(issue.severity == ValidationSeverity.ERROR for issue in issues)

        return ValidationResult(
            success=not has_errors,
            issues=issues,
            metadata={
                "segments_checked": len([s for s in translation_map.values() if s]),
                "error_count": sum(1 for i in issues if i.severity == ValidationSeverity.ERROR),
                "warning_count": sum(1 for i in issues if i.severity == ValidationSeverity.WARNING),
                "target_language": target_language,
                "language_multiplier": multiplier,
            },
        )

    def _check_character_ratio(
        self,
        source_text: str,
        translation_text: str,
        multiplier: float,
        segment_id: int,
    ) -> list[ValidationIssue]:
        """Check character-level length ratio for anomalies.

        Args:
            source_text: Source segment text
            translation_text: Translated segment text
            multiplier: Language multiplier to adjust thresholds
            segment_id: Segment identifier for error reporting

        Returns:
            List of validation issues found
        """
        issues = []

        src_chars = len(source_text)
        trans_chars = len(translation_text)

        if src_chars == 0:
            return issues

        ratio = trans_chars / src_chars

        # Apply language multiplier to thresholds
        adjusted_max_ratio = self.max_char_ratio * multiplier
        adjusted_warning_ratio = self.char_ratio_warning * multiplier

        if ratio > adjusted_max_ratio:
            issues.append(
                ValidationIssue(
                    validator="LengthAnomalyValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Character ratio {ratio:.2f} exceeds maximum {adjusted_max_ratio:.2f} "
                    f"(source: {src_chars} chars, translation: {trans_chars} chars)",
                    location=f"segment_{segment_id}",
                    details={
                        "ratio": ratio,
                        "source_length": src_chars,
                        "translation_length": trans_chars,
                        "threshold": adjusted_max_ratio,
                        "check_type": "character_ratio",
                        "suggestion": "Translation may be hallucinated or corrupted - retry translation",
                    },
                )
            )
        elif ratio > adjusted_warning_ratio:
            issues.append(
                ValidationIssue(
                    validator="LengthAnomalyValidator",
                    severity=ValidationSeverity.WARNING,
                    message=f"Character ratio {ratio:.2f} exceeds warning threshold {adjusted_warning_ratio:.2f} "
                    f"(source: {src_chars} chars, translation: {trans_chars} chars)",
                    location=f"segment_{segment_id}",
                    details={
                        "ratio": ratio,
                        "source_length": src_chars,
                        "translation_length": trans_chars,
                        "threshold": adjusted_warning_ratio,
                        "check_type": "character_ratio",
                    },
                )
            )

        return issues

    def _check_word_ratio(
        self,
        source_text: str,
        translation_text: str,
        multiplier: float,
        segment_id: int,
    ) -> list[ValidationIssue]:
        """Check word-level length ratio for anomalies.

        Args:
            source_text: Source segment text
            translation_text: Translated segment text
            multiplier: Language multiplier to adjust thresholds
            segment_id: Segment identifier for error reporting

        Returns:
            List of validation issues found
        """
        issues = []

        src_words = len(self._tokenize(source_text))
        trans_words = len(self._tokenize(translation_text))

        if src_words == 0:
            return issues

        ratio = trans_words / src_words

        # Apply language multiplier to thresholds
        adjusted_max_ratio = self.max_word_ratio * multiplier
        adjusted_warning_ratio = self.word_ratio_warning * multiplier

        if ratio > adjusted_max_ratio:
            issues.append(
                ValidationIssue(
                    validator="LengthAnomalyValidator",
                    severity=ValidationSeverity.ERROR,
                    message=f"Word ratio {ratio:.2f} exceeds maximum {adjusted_max_ratio:.2f} "
                    f"(source: {src_words} words, translation: {trans_words} words)",
                    location=f"segment_{segment_id}",
                    details={
                        "ratio": ratio,
                        "source_length": src_words,
                        "translation_length": trans_words,
                        "threshold": adjusted_max_ratio,
                        "check_type": "word_ratio",
                        "suggestion": "Translation may contain hallucinated content - review and retry",
                    },
                )
            )
        elif ratio > adjusted_warning_ratio:
            issues.append(
                ValidationIssue(
                    validator="LengthAnomalyValidator",
                    severity=ValidationSeverity.WARNING,
                    message=f"Word ratio {ratio:.2f} exceeds warning threshold {adjusted_warning_ratio:.2f} "
                    f"(source: {src_words} words, translation: {trans_words} words)",
                    location=f"segment_{segment_id}",
                    details={
                        "ratio": ratio,
                        "source_length": src_words,
                        "translation_length": trans_words,
                        "threshold": adjusted_warning_ratio,
                        "check_type": "word_ratio",
                    },
                )
            )

        return issues

    def _tokenize(self, text: str) -> list[str]:
        """Tokenize text into words.

        Args:
            text: Text to tokenize

        Returns:
            List of words
        """
        # Simple word tokenization: split on whitespace and punctuation
        words = re.findall(r'\b[\w]+\b', text)
        return words
