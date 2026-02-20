"""
Repetition detector validator for translation quality assurance.

This module detects content repetition patterns in translations that indicate
model failure modes (e.g., the "miteinander" bug in commit fd6368d where a word
was repeated ~60 times).

Checks:
- N-gram repetition (default 3-gram, threshold: >=3 occurrences = ERROR)
- Word frequency anomalies (>30% of content = ERROR, excluding stop words)
- Sentence duplication (identical sentence >=2 times = ERROR)
- Technical term whitelist support (Aspose.Slides, .NET, etc. can repeat)

Example:
    validator = RepetitionDetectorValidator(config={
        "ngram_size": 3,
        "ngram_threshold": 3,
        "word_freq_threshold": 0.30
    })
    result = validator.validate(
        source=source_text,
        translation=translated_text,
        context=validation_context
    )
    if result.has_errors():
        print(f"Repetition detected: {result.error_count} issues")
"""

import re
from collections import Counter
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

import yaml

from .base import ValidationIssue, ValidationResult, ValidationSeverity
from .post_translation_validator import PostTranslationValidator


class RepetitionDetectorValidator(PostTranslationValidator):
    """Validates that translations do not contain excessive repetition.

    Detects three types of repetition issues:
    1. N-gram repetition: Same word sequence repeated multiple times
    2. Word frequency: Single word appearing too frequently
    3. Sentence duplication: Identical sentences repeated

    Technical terms from config/terminology/technical_terms.yaml are whitelisted
    and exempt from repetition checks.

    Example:
        validator = RepetitionDetectorValidator()
        result = validator.validate(
            source=english_text,
            translation=german_text,
            context={'translation_map': {0: 'text'}}
        )
    """

    # Common stop words to exclude from word frequency checks
    STOP_WORDS = {
        # English
        'a', 'an', 'and', 'are', 'as', 'at', 'be', 'by', 'for', 'from',
        'has', 'he', 'in', 'is', 'it', 'its', 'of', 'on', 'that', 'the',
        'to', 'was', 'will', 'with', 'we', 'you', 'they', 'this', 'these',
        'those', 'have', 'had', 'been', 'has', 'have', 'do', 'does', 'did',
        # German
        'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einer',
        'einem', 'einen', 'und', 'oder', 'aber', 'wenn', 'als', 'wie',
        'auch', 'noch', 'nur', 'von', 'zu', 'mit', 'auf', 'für', 'an',
        'bei', 'nach', 'über', 'unter', 'durch', 'ist', 'sind', 'war',
        'waren', 'hat', 'haben', 'wird', 'werden', 'sich', 'nicht',
        # French
        'le', 'la', 'les', 'un', 'une', 'des', 'et', 'ou', 'mais', 'si',
        'comme', 'dans', 'de', 'du', 'pour', 'avec', 'sans', 'sur', 'sous',
        'par', 'est', 'sont', 'était', 'étaient', 'a', 'ont', 'se', 'ne',
        # Spanish
        'el', 'la', 'los', 'las', 'un', 'una', 'unos', 'unas', 'y', 'o',
        'pero', 'si', 'como', 'en', 'de', 'del', 'para', 'con', 'sin',
        'sobre', 'por', 'es', 'son', 'era', 'eran', 'ha', 'han', 'se', 'no',
    }

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize repetition detector validator.

        Args:
            config: Configuration dict with optional keys:
                - ngram_size (int): Size of n-grams to check (default: 3)
                - ngram_threshold (int): Max n-gram occurrences before ERROR (default: 3)
                - ngram_warning_threshold (int): Occurrences for WARNING (default: 2)
                - word_freq_threshold (float): Max word frequency ratio (default: 0.30)
                - word_freq_warning_threshold (float): Warning threshold (default: 0.20)
                - sentence_dup_threshold (int): Max sentence duplicates (default: 2)
                - terminology_file (Path): Path to technical_terms.yaml
        """
        super().__init__()
        config = config or {}

        # N-gram detection config
        self.ngram_size = config.get("ngram_size", 3)
        self.ngram_threshold = config.get("ngram_threshold", 3)
        self.ngram_warning_threshold = config.get("ngram_warning_threshold", 2)

        # Word frequency config
        self.word_freq_threshold = config.get("word_freq_threshold", 0.30)
        self.word_freq_warning_threshold = config.get("word_freq_warning_threshold", 0.20)

        # Sentence duplication config
        self.sentence_dup_threshold = config.get("sentence_dup_threshold", 2)

        # Load technical terms whitelist
        self.whitelist_terms = self._load_whitelist(config)

    def _load_whitelist(self, config: Dict[str, Any]) -> Set[str]:
        """Load technical terms whitelist from YAML file.

        Args:
            config: Configuration dict with optional 'terminology_file' key

        Returns:
            Set of normalized technical terms (lowercase)
        """
        terminology_file = config.get("terminology_file")

        # Default to config/terminology/technical_terms.yaml
        if terminology_file is None:
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent.parent
            terminology_file = project_root / "config" / "terminology" / "technical_terms.yaml"

        # Load terms from YAML
        terms = set()
        try:
            if Path(terminology_file).exists():
                with open(terminology_file, 'r', encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'terms' in data:
                        # Normalize to lowercase for case-insensitive matching
                        terms = {term.lower() for term in data['terms']}
        except Exception:
            # If loading fails, continue with empty whitelist
            pass

        return terms

    def validate(
        self,
        source: str,
        translation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """Validate translation for repetition issues.

        Args:
            source: Original source text (unused, for signature compatibility)
            translation: Translated text to check
            context: Optional context with 'translation_map' (dict[segment_id -> text])

        Returns:
            ValidationResult with repetition issues
        """
        if context is None:
            context = {}

        issues = []

        # Get translation segments from context
        translation_map = context.get("translation_map", {})

        # If no translation_map, treat entire translation as single segment
        if not translation_map:
            translation_map = {0: translation}

        # Check each segment for repetition issues
        for segment_id, segment_text in translation_map.items():
            if not segment_text or len(segment_text.strip()) < 20:
                # Skip very short segments (unreliable for repetition detection)
                continue

            # Check 1: N-gram repetition
            ngram_issues = self._check_ngram_repetition(segment_text, str(segment_id))
            issues.extend(ngram_issues)

            # Check 2: Word frequency
            word_freq_issues = self._check_word_frequency(segment_text, str(segment_id))
            issues.extend(word_freq_issues)

            # Check 3: Sentence duplication
            sentence_dup_issues = self._check_sentence_duplication(segment_text, str(segment_id))
            issues.extend(sentence_dup_issues)

            # Check 4: Heading-specific repetition (bypasses 20-char minimum)
            heading_issues = self._check_heading_repetition(segment_text, str(segment_id))
            issues.extend(heading_issues)

        # Determine success based on whether we have errors
        has_errors = any(issue.severity == ValidationSeverity.ERROR for issue in issues)

        return ValidationResult(
            success=not has_errors,
            issues=issues,
            metadata={
                "segments_checked": len(translation_map),
                "error_count": sum(1 for i in issues if i.severity == ValidationSeverity.ERROR),
                "warning_count": sum(1 for i in issues if i.severity == ValidationSeverity.WARNING),
            },
        )

    def _check_ngram_repetition(
        self, text: str, segment_id: str
    ) -> List[ValidationIssue]:
        """Check for n-gram repetition in text.

        Args:
            text: Text to check
            segment_id: Segment identifier for error reporting

        Returns:
            List of validation issues found
        """
        issues = []

        # Tokenize text into words
        words = self._tokenize(text)

        if len(words) < self.ngram_size:
            return issues

        # Generate n-grams
        ngrams = []
        for i in range(len(words) - self.ngram_size + 1):
            ngram = tuple(words[i:i + self.ngram_size])
            # Skip n-grams containing whitelisted terms
            if not any(word in self.whitelist_terms for word in ngram):
                ngrams.append(ngram)

        # Count n-gram occurrences
        ngram_counts = Counter(ngrams)

        # Report n-grams exceeding thresholds
        for ngram, count in ngram_counts.most_common():
            if count >= self.ngram_threshold:
                ngram_text = " ".join(ngram)
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"{self.ngram_size}-gram '{ngram_text}' repeated {count} times (threshold: {self.ngram_threshold})",
                        location=f"segment_{segment_id}",
                        details={
                            "ngram": ngram_text,
                            "count": count,
                            "threshold": self.ngram_threshold,
                            "suggestion": "Translation appears to have repetitive content - retry translation",
                        },
                    )
                )
            elif count >= self.ngram_warning_threshold:
                ngram_text = " ".join(ngram)
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.WARNING,
                        message=f"{self.ngram_size}-gram '{ngram_text}' repeated {count} times (warning threshold: {self.ngram_warning_threshold})",
                        location=f"segment_{segment_id}",
                        details={
                            "ngram": ngram_text,
                            "count": count,
                            "threshold": self.ngram_warning_threshold,
                        },
                    )
                )

        return issues

    def _check_word_frequency(
        self, text: str, segment_id: str
    ) -> List[ValidationIssue]:
        """Check for excessive word frequency in text.

        Args:
            text: Text to check
            segment_id: Segment identifier for error reporting

        Returns:
            List of validation issues found
        """
        issues = []

        # Tokenize text into words
        words = self._tokenize(text)

        if len(words) < 10:  # Skip very short texts
            return issues

        # Filter out stop words and whitelisted terms
        filtered_words = [
            word for word in words
            if word not in self.STOP_WORDS and word not in self.whitelist_terms
        ]

        if not filtered_words:
            return issues

        # Count word occurrences
        word_counts = Counter(filtered_words)
        total_words = len(filtered_words)

        # Check for words exceeding frequency thresholds
        for word, count in word_counts.most_common(5):  # Check top 5 most common
            frequency = count / total_words

            if frequency > self.word_freq_threshold:
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Word '{word}' appears {count} times ({frequency:.1%} of content, threshold: {self.word_freq_threshold:.0%})",
                        location=f"segment_{segment_id}",
                        details={
                            "word": word,
                            "count": count,
                            "frequency": frequency,
                            "threshold": self.word_freq_threshold,
                            "suggestion": "Single word dominates content - likely translation failure",
                        },
                    )
                )
            elif frequency > self.word_freq_warning_threshold:
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.WARNING,
                        message=f"Word '{word}' appears {count} times ({frequency:.1%} of content, warning threshold: {self.word_freq_warning_threshold:.0%})",
                        location=f"segment_{segment_id}",
                        details={
                            "word": word,
                            "count": count,
                            "frequency": frequency,
                            "threshold": self.word_freq_warning_threshold,
                        },
                    )
                )

        return issues

    def _check_sentence_duplication(
        self, text: str, segment_id: str
    ) -> List[ValidationIssue]:
        """Check for duplicate sentences in text.

        Args:
            text: Text to check
            segment_id: Segment identifier for error reporting

        Returns:
            List of validation issues found
        """
        issues = []

        # Split into sentences
        sentences = self._split_sentences(text)

        if len(sentences) < 2:  # Need at least 2 sentences for duplication
            return issues

        # Normalize sentences (lowercase, strip whitespace)
        normalized_sentences = [
            self._normalize_sentence(s) for s in sentences
        ]

        # Count sentence occurrences
        sentence_counts = Counter(normalized_sentences)

        # Report duplicates
        for sentence, count in sentence_counts.items():
            if count >= self.sentence_dup_threshold:
                # Get original sentence (not normalized) for better error message
                original_sentence = next(
                    (s for s in sentences if self._normalize_sentence(s) == sentence),
                    sentence
                )
                # Truncate long sentences for readability
                display_sentence = (
                    original_sentence[:100] + "..."
                    if len(original_sentence) > 100
                    else original_sentence
                )

                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Sentence repeated {count} times: '{display_sentence}'",
                        location=f"segment_{segment_id}",
                        details={
                            "sentence": original_sentence,
                            "count": count,
                            "threshold": self.sentence_dup_threshold,
                            "suggestion": "Duplicate sentences detected - retry translation",
                        },
                    )
                )

        return issues

    def _tokenize(self, text: str) -> List[str]:
        """Tokenize text into words.

        Args:
            text: Text to tokenize

        Returns:
            List of normalized words (lowercase)
        """
        # Remove punctuation and split on whitespace
        # Keep only alphanumeric and basic punctuation
        words = re.findall(r'\b[\w]+\b', text.lower())
        return words

    def _split_sentences(self, text: str) -> List[str]:
        """Split text into sentences.

        Args:
            text: Text to split

        Returns:
            List of sentences
        """
        # Split on period, exclamation, question mark followed by space
        # More sophisticated than simple split to handle abbreviations better
        sentences = re.split(r'[.!?]+\s+', text)

        # Filter empty and very short sentences
        sentences = [s.strip() for s in sentences if len(s.strip()) > 5]

        return sentences

    def _normalize_sentence(self, sentence: str) -> str:
        """Normalize sentence for comparison.

        Args:
            sentence: Sentence to normalize

        Returns:
            Normalized sentence (lowercase, trimmed)
        """
        # Lowercase and remove extra whitespace
        normalized = re.sub(r'\s+', ' ', sentence.lower().strip())
        return normalized

    def _check_heading_repetition(
        self, text: str, segment_id: str
    ) -> List[ValidationIssue]:
        """Check heading lines for excessive single-word repetition.

        This check bypasses the 20-character segment minimum so that short
        headings like '## خطوة خطوة خطوة خطوة خطوة' are also caught.

        Args:
            text: Full segment text (may contain markdown headings)
            segment_id: Segment identifier for error reporting

        Returns:
            List of validation issues found
        """
        heading_threshold = 4  # word repeated > 4 times in a heading = ERROR
        issues = []

        for line in text.splitlines():
            stripped = line.strip()
            if not stripped.startswith('#'):
                continue
            heading_text = stripped.lstrip('#').strip()
            if not heading_text:
                continue

            words = self._tokenize(heading_text)
            if not words:
                continue

            counts = Counter(words)
            for word, count in counts.items():
                if word in self.whitelist_terms or word in self.STOP_WORDS:
                    continue
                if count > heading_threshold:
                    issues.append(
                        ValidationIssue(
                            validator="RepetitionDetectorValidator",
                            severity=ValidationSeverity.ERROR,
                            message=(
                                f"Heading word '{word}' repeated {count}x "
                                f"(threshold: {heading_threshold}): "
                                f"'{heading_text[:80]}'"
                            ),
                            location=f"heading_segment_{segment_id}",
                            details={
                                "word": word,
                                "count": count,
                                "threshold": heading_threshold,
                                "heading": heading_text[:120],
                                "suggestion": "Heading contains repeated words — likely translation hallucination",
                            },
                        )
                    )

        return issues
