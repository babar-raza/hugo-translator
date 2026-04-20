"""
Language consistency validator using langdetect library.

Validates that translated content is in the correct target language.
Uses Google's langdetect library for language detection with deterministic seeding.
"""

import re
from typing import Any

import langdetect
from langdetect import DetectorFactory

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator

# Set seed for deterministic results
DetectorFactory.seed = 0

# ---------------------------------------------------------------------------
# Unicode script-range patterns used for script-mixing detection.
# Latin is intentionally excluded from forbidden-script lists because
# product names, API identifiers, and URLs legitimately appear in any language.
# ---------------------------------------------------------------------------
_SCRIPT_ARABIC     = re.compile(r'[\u0600-\u06FF\u0750-\u077F\u08A0-\u08FF]')
_SCRIPT_CYRILLIC   = re.compile(r'[\u0400-\u04FF]')
_SCRIPT_HEBREW     = re.compile(r'[\u0590-\u05FF]')
_SCRIPT_CHINESE    = re.compile(r'[\u4E00-\u9FFF]')
_SCRIPT_JAPANESE   = re.compile(r'[\u3040-\u30FF\u31F0-\u31FF]')
_SCRIPT_KOREAN     = re.compile(r'[\uAC00-\uD7AF]')
_SCRIPT_DEVANAGARI = re.compile(r'[\u0900-\u097F]')
_SCRIPT_THAI       = re.compile(r'[\u0E00-\u0E7F]')

# For each target language, the list of Unicode-script patterns that must NOT
# appear in translated content (outside code blocks / frontmatter).
_FORBIDDEN_SCRIPTS: dict[str, list[re.Pattern]] = {
    # Cyrillic-script languages
    'bg': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ru': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'uk': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sr': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'mk': [_SCRIPT_ARABIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    # Arabic-script languages
    'ar': [_SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'fa': [_SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ur': [_SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    # Latin-script languages
    'fr': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'de': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'es': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'it': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'pt': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'nl': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'pl': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'cs': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sk': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ro': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'hu': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sv': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'da': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'fi': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'nb': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'no': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'tr': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'id': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ms': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'vi': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'af': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ca': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ga': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'az': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'et': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'lt': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'lv': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'hr': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'sl': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    # East-Asian
    'zh': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ja': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    'ko': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_DEVANAGARI, _SCRIPT_THAI],
    # South / Southeast Asian
    'hi': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_THAI],
    'th': [_SCRIPT_ARABIC, _SCRIPT_CYRILLIC, _SCRIPT_HEBREW, _SCRIPT_CHINESE, _SCRIPT_JAPANESE, _SCRIPT_KOREAN, _SCRIPT_DEVANAGARI],
}

# Lines shorter than this are skipped in the script-mixing check (too short / noise)
_SCRIPT_MIX_MIN_LINE_LEN = 15
# Fraction of content lines that may contain a forbidden script before flagging
_SCRIPT_MIX_THRESHOLD = 0.06


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

    def __init__(
        self,
        confidence_threshold: float = 0.85,
        per_language_overrides: dict | None = None,
    ):
        """Initialize language consistency validator.

        Args:
            confidence_threshold: Minimum confidence for language detection (default 0.85)
            per_language_overrides: Optional dict mapping lang codes to override dicts.
                Each override may contain:
                  - purity_threshold (float): min % of sentences in target lang (0–100)
                  - confidence_threshold (float): min langdetect confidence per sentence
                Example: {'es': {'purity_threshold': 98.0, 'confidence_threshold': 0.90}}
        """
        super().__init__()
        self.confidence_threshold = confidence_threshold
        self.per_language_overrides: dict = per_language_overrides or {}

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
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

        # Resolve per-language overrides (ES/IT/CS have stricter thresholds)
        lang_overrides = self.per_language_overrides.get(target_lang, {})
        effective_confidence = lang_overrides.get('confidence_threshold', self.confidence_threshold)
        effective_purity = lang_overrides.get('purity_threshold', 95.0)

        # Unicode script-mixing check (fast, no ML, catches inline foreign phrases).
        # Runs before the slower langdetect pass but does NOT short-circuit so that
        # purity_percentage is always included in the returned metadata.
        script_issues = self._check_script_mixing(translation, target_lang)
        issues.extend(script_issues)

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

                    if detected_code == target_lang and confidence >= effective_confidence:
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

            # Require effective_purity% of sentences to be in correct language
            # (default 95%; stricter for ES/IT/CS via per_language_overrides)
            if purity_pct < effective_purity:
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

    def _check_script_mixing(
        self,
        text: str,
        target_lang: str,
    ) -> list[ValidationIssue]:
        """Detect Unicode script contamination using character-range analysis.

        Unlike langdetect / fasttext which return the *dominant* language and
        therefore miss short inline phrases in a foreign script, this method
        checks every content line for characters from scripts that are
        incompatible with the target language.

        Latin characters are deliberately allowed in all languages because
        product names, API identifiers, and URLs legitimately appear anywhere.

        Args:
            text: Full translated document text (including markdown).
            target_lang: ISO 639-1 target language code (e.g. 'bg', 'ar').

        Returns:
            List with at most one ValidationIssue (ERROR) if contamination
            exceeds the threshold, otherwise empty list.
        """
        forbidden = _FORBIDDEN_SCRIPTS.get(target_lang)
        if not forbidden:
            return []

        # Strip content that legitimately contains foreign characters
        clean = re.sub(r'```.*?```', '', text, flags=re.DOTALL)   # fenced code
        clean = re.sub(r'`[^`]+`', '', clean)                      # inline code
        clean = re.sub(r'^---.*?^---', '', clean, flags=re.DOTALL | re.MULTILINE)  # frontmatter
        clean = re.sub(r'https?://\S+', '', clean)                 # URLs
        clean = re.sub(r'\{\{[<{%].*?[>}%]\}\}', '', clean, flags=re.DOTALL)  # shortcodes

        lines = [
            ln for ln in clean.splitlines()
            if len(ln.strip()) >= _SCRIPT_MIX_MIN_LINE_LEN
        ]
        if not lines:
            return []

        contaminated: list[str] = []
        for line in lines:
            for pattern in forbidden:
                if pattern.search(line):
                    contaminated.append(line.strip()[:120])
                    break  # one forbidden script per line is enough

        if not contaminated:
            return []

        ratio = len(contaminated) / len(lines)
        if ratio <= _SCRIPT_MIX_THRESHOLD:
            return []

        examples = " | ".join(contaminated[:3])
        return [
            ValidationIssue(
                validator="LanguageConsistencyValidator",
                severity=ValidationSeverity.ERROR,
                message=(
                    f"Script mixing detected: {len(contaminated)}/{len(lines)} lines "
                    f"({ratio * 100:.1f}%) contain characters from a script incompatible "
                    f"with '{target_lang}'. Examples: {examples}"
                ),
                location="translation",
                details={
                    "contaminated_lines": len(contaminated),
                    "total_lines": len(lines),
                    "ratio": ratio,
                    "target_lang": target_lang,
                    "examples": contaminated[:5],
                },
            )
        ]

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
