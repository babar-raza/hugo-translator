"""
Language Detection Check for verification.

Detects when translated content is not in the expected target language,
which indicates untranslated or mixed-language content.
"""

import logging
import re
from typing import Any

from .base import VerificationCheck, VerificationIssue

logger = logging.getLogger(__name__)

# Lazy import for langdetect to handle missing dependency gracefully
_langdetect = None


def _get_langdetect():
    """Lazy import langdetect module."""
    global _langdetect
    if _langdetect is None:
        try:
            import langdetect
            from langdetect import DetectorFactory

            # Set seed for reproducible results
            DetectorFactory.seed = 0
            _langdetect = langdetect
        except ImportError:
            raise ImportError(
                "langdetect is required for LanguageDetectionCheck. "
                "Install with: pip install langdetect"
            )
    return _langdetect


class LanguageDetectionCheck(VerificationCheck):
    """
    Verification check that detects wrong-language content.

    Scans translated document fields and flags those where the detected
    language does not match the expected target language.

    Features:
    - Configurable minimum text length to avoid false positives on short strings
    - Configurable confidence threshold
    - Graceful handling of detection failures
    - Skips technical content (code, URLs, patterns)

    Example:
        check = LanguageDetectionCheck(
            min_text_length=20,
            confidence_threshold=0.85
        )

        issues = check.run(source_doc, translated_doc, "de")
        for issue in issues:
            print(f"{issue.location}: {issue.message}")
    """

    # Patterns that indicate technical content to skip
    SKIP_PATTERNS = [
        # Code patterns
        "{{",
        "}}",
        "<%",
        "%>",
        "```",
        # URL patterns
        "http://",
        "https://",
        "www.",
        # File paths
        ".exe",
        ".dll",
        ".pdf",
        ".docx",
        # API references (likely to stay in English)
        "API",
        "SDK",
        "HTTP",
        "REST",
        "JSON",
        "XML",
    ]
    ALWAYS_SKIP_PATTERNS = [
        "{{",
        "}}",
        "<%",
        "%>",
        "```",
        "http://",
        "https://",
        "www.",
    ]
    PROTECTED_FRONTMATTER_TREES = {
        "evidence",
        "grade_reasons",
    }
    # Language classifiers can be dominated by required ASCII product/platform
    # tokens in an otherwise-correct short title.  For example, langdetect
    # classifies a Korean title containing ``Aspose.Cells FOSS`` and ``Rust``
    # as Estonian with high confidence even though the ordinary prose is
    # Korean.  Remove only syntax-shaped identifiers and the small governed
    # platform lexicon from the classifier input.  The untranslated-unit and
    # terminology gates still validate those tokens independently.
    TECHNICAL_SIGNAL_RE = re.compile(
        r"(?<![A-Za-z0-9_])(?:"
        r"Aspose(?:\.[A-Za-z][A-Za-z0-9]*)+|"
        r"\.NET|C\+\+|C#|"
        r"FOSS|SDK|API|HTTP|REST|JSON|XML|XLSX|PDF|DOCX|"
        r"Rust|Python|Java|JavaScript|Microsoft|Office|"
        r"[A-Za-z][A-Za-z0-9_+#-]*(?:\.[A-Za-z0-9_+#-]+)+|"
        r"[A-Z][A-Z0-9_+#-]{1,}|"
        r"[A-Z][a-z0-9]+(?:[A-Z][A-Za-z0-9]*)+"
        r")(?![A-Za-z0-9_.])"
    )
    # ``langdetect`` is character n-gram based and consistently classifies
    # short Korean technical titles as English when immutable product tokens
    # (for example, ``Aspose.Cells FOSS`` and ``Rust``) are present.  Hangul
    # is an independent, deterministic language-script signal, so use it to
    # disambiguate that known false-positive class.  The minimum count and
    # ratio deliberately remain high enough that adding a token Korean word
    # to otherwise untranslated English prose cannot pass this check.
    TARGET_SCRIPT_RANGES = {
        "ko": (
            (0x1100, 0x11FF),  # Hangul Jamo
            (0x3130, 0x318F),  # Hangul Compatibility Jamo
            (0xAC00, 0xD7AF),  # Hangul syllables
        ),
        "zh": (
            (0x3400, 0x4DBF),  # CJK Unified Ideographs Extension A
            (0x4E00, 0x9FFF),  # CJK Unified Ideographs
        ),
    }
    MIN_TARGET_SCRIPT_CHARS = 6
    MIN_TARGET_SCRIPT_RATIO = 0.30

    def __init__(
        self,
        min_text_length: int = 20,
        confidence_threshold: float = 0.7,
        check_frontmatter: bool = True,
        check_body: bool = True,
    ):
        """
        Initialize language detection check.

        Args:
            min_text_length: Minimum text length to check (shorter strings skipped)
            confidence_threshold: Minimum confidence for detection (0.0-1.0)
            check_frontmatter: Whether to check frontmatter fields
            check_body: Whether to check body content
        """
        self.min_text_length = min_text_length
        self.confidence_threshold = confidence_threshold
        self.check_frontmatter = check_frontmatter
        self.check_body = check_body

    @property
    def name(self) -> str:
        return "language_detection"

    def run(
        self,
        source: dict[str, Any],
        translated: dict[str, Any],
        target_lang: str,
        context: dict[str, Any] | None = None,
    ) -> list[VerificationIssue]:
        """
        Check all text fields for wrong-language content.

        Args:
            source: Source document data
            translated: Translated document data
            target_lang: Expected target language code
            context: Optional context

        Returns:
            List of issues for fields with wrong language
        """
        issues = []

        # Check frontmatter fields
        if self.check_frontmatter and "frontmatter" in translated:
            frontmatter_issues = self._check_dict_fields(
                translated["frontmatter"],
                target_lang,
                "frontmatter",
                context,
            )
            issues.extend(frontmatter_issues)

        # Check body content
        if self.check_body and "body" in translated:
            body = translated["body"]
            if isinstance(body, str) and len(body) >= self.min_text_length:
                body_issues = self._check_text(
                    body,
                    target_lang,
                    "body",
                    context,
                )
                if body_issues:
                    issues.extend(body_issues)

        return issues

    def _check_dict_fields(
        self,
        data: dict[str, Any],
        target_lang: str,
        path: str,
        context: dict[str, Any] | None = None,
    ) -> list[VerificationIssue]:
        """
        Recursively check dictionary fields for language issues.

        Args:
            data: Dictionary to check
            target_lang: Expected target language
            path: Current path (for location reporting)

        Returns:
            List of verification issues
        """
        issues = []

        for key, value in data.items():
            current_path = f"{path}.{key}"
            if path == "frontmatter" and key in self.PROTECTED_FRONTMATTER_TREES:
                continue

            if isinstance(value, str):
                if len(value) >= self.min_text_length:
                    field_issues = self._check_text(value, target_lang, current_path, context)
                    issues.extend(field_issues)

            elif isinstance(value, list):
                for idx, item in enumerate(value):
                    item_path = f"{current_path}[{idx}]"
                    if isinstance(item, str):
                        if len(item) >= self.min_text_length:
                            item_issues = self._check_text(item, target_lang, item_path, context)
                            issues.extend(item_issues)
                    elif isinstance(item, dict):
                        dict_issues = self._check_dict_fields(item, target_lang, item_path, context)
                        issues.extend(dict_issues)

            elif isinstance(value, dict):
                nested_issues = self._check_dict_fields(value, target_lang, current_path, context)
                issues.extend(nested_issues)

        return issues

    def _check_text(
        self,
        text: str,
        target_lang: str,
        location: str,
        context: dict[str, Any] | None = None,
    ) -> list[VerificationIssue]:
        """
        Check a single text field for language issues.

        Args:
            text: Text to check
            target_lang: Expected target language
            location: Field location for reporting

        Returns:
            List with issue if wrong language, empty otherwise
        """
        # Skip technical content
        if self._is_technical_content(text):
            logger.debug(f"Skipping technical content at {location}")
            return []

        # A strong, target-exclusive script signal is more reliable than
        # langdetect for short mixed technical strings.  This is an
        # additional positive attestation, not a skip: English-only and
        # token-level mixed-language strings still proceed to detection and
        # fail normally.
        if self._has_strong_target_script_evidence(text, target_lang):
            return []

        # Required product names, file formats, and platform identifiers must
        # not outvote the actual prose in short fields such as titles.
        detection_text = self._language_signal_text(text)
        if sum(1 for char in detection_text if char.isalpha()) < 2:
            logger.debug(f"No non-technical language signal at {location}")
            return []

        # Detect language
        detected_lang, confidence = self._detect_language(detection_text)

        if detected_lang is None:
            if (context or {}).get("validation_policy") == "zero-defect":
                return [
                    VerificationIssue(
                        severity="error",
                        check_name=self.name,
                        location=location,
                        message="Language detector produced no verdict under zero-defect policy",
                        metadata={
                            "expected_lang": target_lang,
                            "validator_unavailable": True,
                        },
                    )
                ]
            # Standard policy retains the historical graceful handling.
            logger.debug(f"Language detection failed for {location}")
            return []

        # Check if detected language matches target
        if detected_lang != target_lang and confidence >= self.confidence_threshold:
            # Check for language code variations (e.g., "en" vs "en-us")
            if not self._languages_match(detected_lang, target_lang):
                return [
                    VerificationIssue(
                        severity="error",
                        check_name=self.name,
                        location=location,
                        message=f"Expected {target_lang}, detected {detected_lang} (confidence: {confidence:.2f})",
                        translated_text=text[:100] if len(text) > 100 else text,
                        metadata={
                            "detected_lang": detected_lang,
                            "expected_lang": target_lang,
                            "confidence": confidence,
                        },
                    )
                ]

        return []

    @classmethod
    def _language_signal_text(cls, text: str) -> str:
        """Return prose-only classifier input without governed technical tokens."""
        stripped = cls.TECHNICAL_SIGNAL_RE.sub(" ", text)
        return re.sub(r"\s+", " ", stripped).strip()

    @classmethod
    def _has_strong_target_script_evidence(cls, text: str, target_lang: str) -> bool:
        """Return whether text has substantial target-exclusive script evidence."""
        target_base = target_lang.lower().split("-")[0]
        ranges = cls.TARGET_SCRIPT_RANGES.get(target_base)
        if not ranges:
            return False

        letters = [char for char in text if char.isalpha()]
        if not letters:
            return False
        target_count = sum(
            any(start <= ord(char) <= end for start, end in ranges) for char in letters
        )
        return (
            target_count >= cls.MIN_TARGET_SCRIPT_CHARS
            and target_count / len(letters) >= cls.MIN_TARGET_SCRIPT_RATIO
        )

    def _detect_language(self, text: str) -> tuple[str | None, float]:
        """
        Detect language of text.

        Args:
            text: Text to analyze

        Returns:
            Tuple of (language_code, confidence) or (None, 0.0) if detection fails
        """
        try:
            langdetect = _get_langdetect()

            # langdetect returns probabilities, we get the best match
            result = langdetect.detect_langs(text)
            if result:
                best = result[0]
                return best.lang, best.prob

            return None, 0.0

        except Exception as e:
            logger.debug(f"Language detection failed: {e}")
            return None, 0.0

    def _is_technical_content(self, text: str) -> bool:
        """
        Check if text is technical content that should be skipped.

        Args:
            text: Text to check

        Returns:
            True if text appears to be technical content
        """
        # Check for skip patterns
        text_upper = text.upper()
        if any(pattern.upper() in text_upper for pattern in self.ALWAYS_SKIP_PATTERNS):
            return True
        for pattern in self.SKIP_PATTERNS:
            if pattern.upper() in text_upper:
                # Allow if pattern is small part of text
                if len(pattern) > len(text) * 0.3:
                    return True

        # Check if mostly code/symbols (low letter ratio)
        letters = sum(1 for c in text if c.isalpha())
        if len(text) > 0 and letters / len(text) < 0.4:
            return True

        return False

    def _languages_match(self, detected: str, expected: str) -> bool:
        """
        Check if detected and expected languages match.

        Handles language code variations (e.g., "en" matches "en-US").

        Args:
            detected: Detected language code
            expected: Expected language code

        Returns:
            True if languages match
        """
        # Normalize to lowercase and strip region
        detected_base = detected.lower().split("-")[0]
        expected_base = expected.lower().split("-")[0]

        return detected_base == expected_base

    def is_enabled(self, context: dict[str, Any] | None = None) -> bool:
        """Check if language detection is enabled."""
        if context and "disable_language_check" in context:
            return not context["disable_language_check"]
        return True
