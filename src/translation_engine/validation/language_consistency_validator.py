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

        # NEW: Check sentence-by-sentence for language purity
        # Split into sentences using simple heuristic
        sentences = self._split_into_sentences(cleaned_text)

        total_sentences = 0
        correct_lang_count = 0
        wrong_lang_sentences = []

        try:
            for i, sentence in enumerate(sentences):
                # Skip very short sentences (< 15 chars) as they're unreliable
                if len(sentence.strip()) < 15:
                    continue

                total_sentences += 1

                try:
                    detected_langs = langdetect.detect_langs(sentence)
                    if not detected_langs:
                        continue

                    top_lang = detected_langs[0]
                    detected_code = top_lang.lang
                    confidence = top_lang.prob

                    if detected_code == target_lang and confidence >= 0.7:
                        correct_lang_count += 1
                    else:
                        # Log wrong language sentence (truncate for readability)
                        snippet = sentence[:80] + "..." if len(sentence) > 80 else sentence
                        wrong_lang_sentences.append({
                            "sentence_num": i + 1,
                            "snippet": snippet,
                            "detected": detected_code,
                            "confidence": confidence
                        })

                except langdetect.LangDetectException:
                    # Skip sentences that fail detection
                    continue

            if total_sentences == 0:
                issues.append(
                    ValidationIssue(
                        validator="LanguageConsistencyValidator",
                        severity=ValidationSeverity.WARNING,
                        message="No sentences long enough for reliable detection",
                        location="translation",
                    )
                )
                return ValidationResult(success=True, issues=issues)

            # Calculate purity percentage
            purity_pct = (correct_lang_count / total_sentences) * 100

            # Require 95% of sentences to be in correct language
            if purity_pct < 95.0:
                # Create detailed error message
                examples = "; ".join([
                    f"Sent {s['sentence_num']}: '{s['snippet']}' ({s['detected']}, conf={s['confidence']:.2f})"
                    for s in wrong_lang_sentences[:3]  # Show first 3 examples
                ])

                issues.append(
                    ValidationIssue(
                        validator="LanguageConsistencyValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Mixed language detected: only {purity_pct:.1f}% of sentences are {target_lang}. Examples: {examples}",
                        location="translation",
                    )
                )

            return ValidationResult(
                success=len([i for i in issues if i.severity == ValidationSeverity.ERROR]) == 0,
                issues=issues,
                metadata={
                    "target_language": target_lang,
                    "total_sentences": total_sentences,
                    "correct_language_count": correct_lang_count,
                    "purity_percentage": purity_pct,
                    "wrong_language_samples": wrong_lang_sentences[:5]
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

    def _split_into_sentences(self, text: str) -> list:
        """Split text into sentences using simple heuristic.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        # Split on period, exclamation, question mark followed by space and capital letter
        # or end of string
        sentences = re.split(r'[.!?]+(?:\s+(?=[A-Z])|$)', text)

        # Filter out empty strings and strip whitespace
        sentences = [s.strip() for s in sentences if s.strip()]

        return sentences

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
