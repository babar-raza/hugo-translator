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
from typing import Any

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
        'those', 'have', 'had', 'been', 'do', 'does', 'did',
        # German
        'der', 'die', 'das', 'den', 'dem', 'des', 'ein', 'eine', 'einer',
        'einem', 'einen', 'und', 'oder', 'aber', 'wenn', 'als', 'wie',
        'auch', 'noch', 'nur', 'von', 'zu', 'mit', 'auf', 'für', 'bei', 'nach', 'über', 'unter', 'durch', 'ist', 'sind', 'war',
        'waren', 'hat', 'haben', 'wird', 'werden', 'sich', 'nicht',
        # French
        'le', 'la', 'les', 'un', 'une', 'et', 'ou', 'mais', 'si',
        'comme', 'dans', 'de', 'du', 'pour', 'avec', 'sans', 'sur', 'sous',
        'par', 'est', 'sont', 'était', 'étaient', 'ont', 'se', 'ne',
        # Spanish
        'el', 'los', 'las', 'una', 'unos', 'unas', 'y', 'o',
        'pero', 'como', 'en', 'del', 'para', 'con', 'sin',
        'sobre', 'por', 'es', 'son', 'era', 'eran', 'ha', 'han', 'no',
    }

    def __init__(self, config: dict[str, Any] | None = None):
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

        # Locale-scoped canonical translated phrases.  A single English term
        # can legitimately expand to a multi-word target-language phrase
        # ("spreadsheet" -> "hoja de cálculo").  Count-only cross-lingual
        # n-gram ceilings cannot model that expansion, so profiles may exempt
        # only n-grams wholly contained in reviewed canonical phrases.
        localized = config.get("localized_phrase_whitelist", {}) or {}
        self.localized_phrase_whitelist = {
            str(locale).lower(): tuple(
                str(phrase).strip().lower()
                for phrase in phrases
                if str(phrase).strip()
            )
            for locale, phrases in localized.items()
            if isinstance(phrases, list)
        }

        # Load technical terms whitelist
        self.whitelist_terms = self._load_whitelist(config)

    def _load_whitelist(self, config: dict[str, Any]) -> set[str]:
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
                with open(terminology_file, encoding='utf-8') as f:
                    data = yaml.safe_load(f)
                    if data and 'terms' in data:
                        # Normalize to lowercase for case-insensitive matching
                        terms = {term.lower() for term in data['terms']}
        except Exception:
            # If loading fails, continue with empty whitelist
            pass

        return terms

    # Minimum number of source tokens required before computing ceilings.
    # Short sources (< 30 words) produce unreliable frequency statistics —
    # e.g. a 2-word source gives 50% word frequency for each word, which would
    # incorrectly raise the translation's word-frequency threshold.
    _MIN_SOURCE_WORDS_FOR_CEILING = 30

    def _source_ngram_ceiling(self, source: str) -> int:
        """Compute the maximum n-gram repetition count in the source text.

        Because source and translation use different languages, we cannot compare
        individual n-grams across them. Instead we use the source's *maximum*
        n-gram count as a document-level ceiling: if the source's most-repeated
        3-gram appears N times, every n-gram in the translation is allowed up to
        N × 1.5 repetitions before triggering an ERROR.

        This prevents false positives on SEO/tutorial articles whose English
        source intentionally repeats keyword phrases (e.g. "document versioning
        system" 11×), while still catching true model hallucinations that add
        repetition far beyond anything the source contained.

        Returns 0 for sources shorter than _MIN_SOURCE_WORDS_FOR_CEILING — their
        frequency statistics are unreliable and should not override the threshold.

        Args:
            source: English source text

        Returns:
            Maximum n-gram count in source (0 if source is empty or too short)
        """
        words = self._tokenize(source)
        if len(words) < max(self.ngram_size, self._MIN_SOURCE_WORDS_FOR_CEILING):
            return 0
        ngrams = [
            tuple(words[i:i + self.ngram_size])
            for i in range(len(words) - self.ngram_size + 1)
            if not any(w in self.whitelist_terms for w in words[i:i + self.ngram_size])
        ]
        if not ngrams:
            return 0
        return Counter(ngrams).most_common(1)[0][1]

    def _source_max_word_freq(self, source: str) -> float:
        """Compute the maximum word frequency in the source text.

        Used as a document-level ceiling for word-frequency checks: if a word
        dominates the source at frequency F, the same (or any) word is allowed
        up to F × 1.1 frequency in the translation before triggering an ERROR.

        Returns 0.0 for sources shorter than _MIN_SOURCE_WORDS_FOR_CEILING —
        their word-frequency statistics are unreliable (e.g. a 2-word source
        has 50% frequency for each word, which would incorrectly disable the
        word-frequency check).

        Args:
            source: English source text

        Returns:
            Max word frequency ratio in source (0.0 if source is empty or too short)
        """
        words = self._tokenize(source)
        filtered = [
            w for w in words
            if w not in self.STOP_WORDS and w not in self.whitelist_terms
        ]
        if len(filtered) < self._MIN_SOURCE_WORDS_FOR_CEILING:
            return 0.0
        total = len(filtered)
        top_count = Counter(filtered).most_common(1)[0][1]
        return top_count / total

    def validate(
        self,
        source: str,
        translation: str,
        context: dict[str, Any] | None = None,
    ) -> ValidationResult:
        """Validate translation for repetition issues.

        Args:
            source: Original source text — used to derive a document-level
                    repetition ceiling so source-faithful keyword density in
                    translations is not flagged as model hallucination
            translation: Translated text to check
            context: Optional context with 'translation_map' (dict[segment_id -> text])

        Returns:
            ValidationResult with repetition issues
        """
        if context is None:
            context = {}

        issues = []

        # Derive document-level source ceilings (cross-lingual: we cannot compare
        # individual n-grams across languages, so we use the source's MAXIMUM
        # n-gram / word-freq counts to scale thresholds for the whole translation).
        src_ngram_ceil = self._source_ngram_ceiling(source) if source else 0
        src_word_freq_ceil = self._source_max_word_freq(source) if source else 0.0

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

            # Check 1: N-gram repetition (source-ceiling-scaled)
            ngram_issues = self._check_ngram_repetition(
                segment_text,
                str(segment_id),
                src_ngram_ceil,
                target_lang=str(context.get("target_lang", "")).lower(),
            )
            issues.extend(ngram_issues)

            # Check 2: Word frequency (source-ceiling-scaled)
            word_freq_issues = self._check_word_frequency(
                segment_text, str(segment_id), src_word_freq_ceil
            )
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
        self,
        text: str,
        segment_id: str,
        source_ngram_ceiling: int = 0,
        target_lang: str = "",
    ) -> list[ValidationIssue]:
        """Check for n-gram repetition in text.

        Args:
            text: Text to check
            segment_id: Segment identifier for error reporting
            source_ngram_ceiling: Maximum n-gram count observed in the source.
                When > 0, thresholds are scaled document-wide: any n-gram in
                the translation is allowed up to ceiling×1.5 repetitions before
                triggering an ERROR. This is cross-lingual safe (no word-for-word
                comparison) and prevents false positives on SEO/tutorial articles.

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
        localized_whitelist_ngrams: set[tuple[str, ...]] = set()
        for phrase in self.localized_phrase_whitelist.get(target_lang, ()):
            phrase_words = self._tokenize(phrase)
            localized_whitelist_ngrams.update(
                tuple(phrase_words[index:index + self.ngram_size])
                for index in range(len(phrase_words) - self.ngram_size + 1)
            )
        for i in range(len(words) - self.ngram_size + 1):
            ngram = tuple(words[i:i + self.ngram_size])
            # Skip n-grams containing whitelisted terms
            if (
                ngram not in localized_whitelist_ngrams
                and not any(word in self.whitelist_terms for word in ngram)
            ):
                ngrams.append(ngram)

        # Count n-gram occurrences
        ngram_counts = Counter(ngrams)

        # Document-level scaled thresholds.
        # If source already has a 3-gram repeated N times (SEO/tutorial articles),
        # any n-gram in the translation is allowed up to N×1.5 repetitions before
        # we flag an ERROR — model hallucinations add far more than 1.5× source.
        effective_error_threshold = max(
            self.ngram_threshold,
            int(source_ngram_ceiling * 1.5) + 1 if source_ngram_ceiling else 0,
        )
        effective_warn_threshold = max(
            self.ngram_warning_threshold,
            # Keep the warning band calibrated to the configured ERROR
            # threshold.  Production profiles raise ngram_threshold to avoid
            # ordinary document-level phrase reuse, and zero-defect promotes
            # every warning to blocking.  Leaving the legacy warning default
            # at 2 would therefore negate the configured threshold entirely.
            max(1, self.ngram_threshold - 1),
            int(source_ngram_ceiling * 1.2) + 1 if source_ngram_ceiling else 0,
        )

        # Report n-grams exceeding thresholds
        for ngram, count in ngram_counts.most_common():
            if count >= effective_error_threshold:
                ngram_text = " ".join(ngram)
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"{self.ngram_size}-gram '{ngram_text}' repeated {count} times (threshold: {effective_error_threshold}, src_ceiling: {source_ngram_ceiling})",
                        location=f"segment_{segment_id}",
                        details={
                            "ngram": ngram_text,
                            "count": count,
                            "threshold": effective_error_threshold,
                            "source_ngram_ceiling": source_ngram_ceiling,
                            "suggestion": "Translation appears to have repetitive content - retry translation",
                        },
                    )
                )
            elif count >= effective_warn_threshold:
                ngram_text = " ".join(ngram)
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.WARNING,
                        message=f"{self.ngram_size}-gram '{ngram_text}' repeated {count} times (warning threshold: {effective_warn_threshold}, src_ceiling: {source_ngram_ceiling})",
                        location=f"segment_{segment_id}",
                        details={
                            "ngram": ngram_text,
                            "count": count,
                            "threshold": effective_warn_threshold,
                            "source_ngram_ceiling": source_ngram_ceiling,
                        },
                    )
                )

        return issues

    def _check_word_frequency(
        self, text: str, segment_id: str,
        source_word_freq_ceiling: float = 0.0
    ) -> list[ValidationIssue]:
        """Check for excessive word frequency in text.

        Args:
            text: Text to check
            segment_id: Segment identifier for error reporting
            source_word_freq_ceiling: Maximum word frequency ratio observed in
                the source (after stop-word filtering). When the source itself
                has a dominant word at frequency F, the effective error threshold
                is raised to F×1.1, preventing false positives on keyword-dense
                articles. Cross-lingual safe — no word-for-word comparison.

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

        # Document-level effective threshold: if source has a dominant word at
        # frequency F, allow up to F×1.1 in the translation (mirrors source density).
        effective_error_threshold = max(
            self.word_freq_threshold,
            source_word_freq_ceiling * 1.1 if source_word_freq_ceiling >= self.word_freq_threshold else 0.0,
        )
        effective_warn_threshold = max(
            self.word_freq_warning_threshold,
            source_word_freq_ceiling * 1.05 if source_word_freq_ceiling >= self.word_freq_warning_threshold else 0.0,
        )

        # Check for words exceeding frequency thresholds
        for word, count in word_counts.most_common(5):  # Check top 5 most common
            frequency = count / total_words

            if frequency > effective_error_threshold:
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.ERROR,
                        message=f"Word '{word}' appears {count} times ({frequency:.1%} of content, threshold: {effective_error_threshold:.0%}, src_ceiling: {source_word_freq_ceiling:.1%})",
                        location=f"segment_{segment_id}",
                        details={
                            "word": word,
                            "count": count,
                            "frequency": frequency,
                            "threshold": effective_error_threshold,
                            "source_word_freq_ceiling": source_word_freq_ceiling,
                            "suggestion": "Single word dominates content - likely translation failure",
                        },
                    )
                )
            elif frequency > effective_warn_threshold:
                issues.append(
                    ValidationIssue(
                        validator="RepetitionDetectorValidator",
                        severity=ValidationSeverity.WARNING,
                        message=f"Word '{word}' appears {count} times ({frequency:.1%} of content, warning threshold: {effective_warn_threshold:.0%})",
                        location=f"segment_{segment_id}",
                        details={
                            "word": word,
                            "count": count,
                            "frequency": frequency,
                            "threshold": effective_warn_threshold,
                        },
                    )
                )

        return issues

    def _check_sentence_duplication(
        self, text: str, segment_id: str
    ) -> list[ValidationIssue]:
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

    def _tokenize(self, text: str) -> list[str]:
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

    def _split_sentences(self, text: str) -> list[str]:
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
    ) -> list[ValidationIssue]:
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
