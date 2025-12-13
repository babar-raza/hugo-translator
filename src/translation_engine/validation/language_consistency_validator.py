"""
Language consistency validator using langdetect library.

Validates that translated content is in the correct target language.
Uses Google's langdetect library for language detection with deterministic seeding.
"""

import re
from typing import Any, Dict, Optional

import langdetect
from langdetect import DetectorFactory

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator

# Set seed for deterministic results
DetectorFactory.seed = 0


class LanguageConsistencyValidator(PostTranslationValidator):
    """Validates that translated content is in the correct target language.

    Uses Google's langdetect library for language detection.
    Performs sample-based detection to handle long documents efficiently.

    Checks:
    - Detected language matches target language
    - Confidence >= threshold (default 0.85)
    - Code blocks, URLs, and shortcodes ignored

    Example:
        validator = LanguageConsistencyValidator(confidence_threshold=0.85)
        result = validator.validate(
            source=english_text,
            translation=german_text,
            context={'target_lang': 'de'}
        )
    """

    def __init__(self, confidence_threshold: float = 0.85):
        """Initialize language consistency validator.

        Args:
            confidence_threshold: Minimum confidence for language detection (default 0.85)
        """
        super().__init__()
        self.confidence_threshold = confidence_threshold

    def validate(
        self,
        source: str,
        translation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Validate language consistency.

        Args:
            source: Original source text (unused, for signature compatibility)
            translation: Translated text to check
            context: Must contain 'target_lang' (ISO 639-1 code like 'de', 'fr')

        Returns:
            ValidationResult with language issues
        """
        issues = []
        context = context or {}
        target_lang = context.get("target_lang")

        if not target_lang:
            issues.append(
                ValidationIssue(
                    validator="LanguageConsistencyValidator",
                    severity=ValidationSeverity.WARNING,
                    message="No target language specified, skipping check",
                    location="context",
                )
            )
            return ValidationResult(
                success=True,
                issues=issues,
            )

        # Clean text for detection
        cleaned_text = self._clean_text_for_detection(translation)

        if len(cleaned_text) < 20:
            issues.append(
                ValidationIssue(
                    validator="LanguageConsistencyValidator",
                    severity=ValidationSeverity.INFO,
                    message="Text too short for reliable language detection",
                    location="translation",
                )
            )
            return ValidationResult(
                success=True,
                issues=issues,
            )

        # Detect language
        try:
            detected_langs = langdetect.detect_langs(cleaned_text)
            if not detected_langs:
                issues.append(
                    ValidationIssue(
                        validator="LanguageConsistencyValidator",
                        severity=ValidationSeverity.WARNING,
                        message="Could not detect language",
                        location="translation",
                    )
                )
                return ValidationResult(
                    success=False,
                    issues=issues,
                )

            top_lang = detected_langs[0]
            detected_code = top_lang.lang
            confidence = top_lang.prob

            # Check if detected language matches target
            if detected_code != target_lang:
                issues.append(
                    ValidationIssue(
                        validator="LanguageConsistencyValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Wrong language detected: {detected_code} (expected {target_lang})",
                        location="translation",
                    )
                )

            # Check confidence
            if confidence < self.confidence_threshold:
                issues.append(
                    ValidationIssue(
                        validator="LanguageConsistencyValidator",
                        severity=ValidationSeverity.WARNING,
                        message=f"Low detection confidence: {confidence:.2f} < {self.confidence_threshold}",
                        location="translation",
                    )
                )

            return ValidationResult(
                success=len([i for i in issues if i.severity == ValidationSeverity.ERROR]) == 0,
                issues=issues,
                metadata={
                    "detected_language": detected_code,
                    "confidence": confidence,
                    "target_language": target_lang,
                },
            )

        except langdetect.LangDetectException as e:
            issues.append(
                ValidationIssue(
                    validator="LanguageConsistencyValidator",
                    severity=ValidationSeverity.WARNING,
                    message=f"Language detection failed: {str(e)}",
                    location="translation",
                )
            )
            return ValidationResult(
                success=False,
                issues=issues,
            )

    def _clean_text_for_detection(self, text: str) -> str:
        """Remove code blocks, URLs, and shortcodes from text.

        Args:
            text: Raw translation text

        Returns:
            Cleaned text suitable for language detection
        """
        # Remove code blocks (``` ... ```)
        text = re.sub(r"```.*?```", "", text, flags=re.DOTALL)

        # Remove inline code (`...`)
        text = re.sub(r"`[^`]+`", "", text)

        # Remove markdown links but keep text (BEFORE removing URLs to preserve link text)
        text = re.sub(r"\[([^\]]+)\]\([^\)]*\)", r"\1", text)

        # Remove URLs
        text = re.sub(r"https?://\S+", "", text)

        # Remove Hugo shortcodes ({{< ... >}}, {{/* ... */}})
        text = re.sub(r"\{\{[<{%].*?[>}%]\}\}", "", text, flags=re.DOTALL)

        # Remove placeholders
        text = re.sub(r"\{(?:PLACEHOLDER|TERM|SHORTCODE)_\d+\}", "", text)

        # Remove excessive whitespace
        text = re.sub(r"\s+", " ", text).strip()

        return text
