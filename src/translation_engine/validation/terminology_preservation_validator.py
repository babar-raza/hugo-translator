"""
Terminology preservation validator.

Ensures that critical terminology (Aspose, .NET, product families, API references)
is preserved correctly in translations according to terminology.yaml rules.
"""

import re
import yaml
from pathlib import Path
from typing import Any, Dict, List, Optional, Set

from .base import Validator, ValidationResult, ValidationSeverity


class TerminologyPreservationValidator(Validator):
    """
    Validates terminology preservation in translations.

    Checks:
    - Exact match preservation (Aspose, .NET, Java, Python)
    - Pattern-based matching (Aspose.Words, Aspose.Cells, etc.)
    - Frequency validation (term count in source vs translation)
    - Case sensitivity support
    """

    def __init__(
        self,
        terminology_config_path: Optional[Path] = None,
        name: Optional[str] = None,
    ):
        """
        Initialize terminology preservation validator.

        Args:
            terminology_config_path: Path to terminology.yaml config
            name: Optional custom name
        """
        super().__init__(name)

        # Default to config/terminology.yaml if not specified
        if terminology_config_path is None:
            # Assume we're in src/translation_engine/validation/
            # Navigate to project root: ../../../config/terminology.yaml
            current_file = Path(__file__)
            project_root = current_file.parent.parent.parent.parent
            terminology_config_path = project_root / "config" / "terminology.yaml"

        self.terminology_config_path = terminology_config_path
        self.exact_matches: List[Dict[str, Any]] = []
        self.patterns: List[Dict[str, Any]] = []

        self._load_terminology()

    def _load_terminology(self) -> None:
        """Load terminology configuration from YAML file."""
        if not self.terminology_config_path.exists():
            raise FileNotFoundError(
                f"Terminology config not found: {self.terminology_config_path}"
            )

        with open(self.terminology_config_path, 'r', encoding='utf-8') as f:
            config = yaml.safe_load(f)

        # Load global terminology
        if 'global' in config:
            global_config = config['global']

            # Load exact matches
            if 'exact_matches' in global_config:
                self.exact_matches = global_config['exact_matches']

            # Load patterns
            if 'patterns' in global_config:
                self.patterns = global_config['patterns']

    def validate(
        self,
        source: str,
        translation: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> ValidationResult:
        """
        Validate terminology preservation.

        Args:
            source: Source text
            translation: Translated text
            context: Optional context (may include site_name for site-specific rules)

        Returns:
            ValidationResult with any terminology issues
        """
        result = ValidationResult(success=True)

        # Validate exact matches
        for term_config in self.exact_matches:
            self._validate_exact_match(source, translation, term_config, result)

        # Validate patterns
        for pattern_config in self.patterns:
            self._validate_pattern(source, translation, pattern_config, result)

        # Update success based on error count
        if result.has_errors():
            result.success = False

        return result

    def _validate_exact_match(
        self,
        source: str,
        translation: str,
        term_config: Dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """
        Validate exact match term preservation.

        Args:
            source: Source text
            translation: Translated text
            term_config: Term configuration from terminology.yaml
            result: ValidationResult to add issues to
        """
        term = term_config['term']
        case_sensitive = term_config.get('case_sensitive', True)
        severity_str = term_config.get('severity', 'error')
        category = term_config.get('category', 'unknown')

        # Convert severity string to enum
        severity = self._parse_severity(severity_str)

        # Count occurrences in source and translation
        source_count = self._count_term(source, term, case_sensitive)
        translation_count = self._count_term(translation, term, case_sensitive)

        # Check if term is missing from translation
        if source_count > 0 and translation_count == 0:
            result.issues.append(
                self.create_issue(
                    severity,
                    f"Term '{term}' ({category}) appears {source_count} time(s) in source but is missing from translation",
                    location=f"terminology.{category}",
                    details={
                        "term": term,
                        "category": category,
                        "source_count": source_count,
                        "translation_count": translation_count,
                        "case_sensitive": case_sensitive,
                    },
                )
            )
        # Check for frequency mismatch
        elif source_count > 0 and translation_count != source_count:
            result.issues.append(
                self.create_issue(
                    ValidationSeverity.WARNING,
                    f"Term '{term}' ({category}) frequency mismatch: source has {source_count}, translation has {translation_count}",
                    location=f"terminology.{category}",
                    details={
                        "term": term,
                        "category": category,
                        "source_count": source_count,
                        "translation_count": translation_count,
                        "case_sensitive": case_sensitive,
                    },
                )
            )

    def _validate_pattern(
        self,
        source: str,
        translation: str,
        pattern_config: Dict[str, Any],
        result: ValidationResult,
    ) -> None:
        """
        Validate pattern-based term preservation.

        Args:
            source: Source text
            translation: Translated text
            pattern_config: Pattern configuration from terminology.yaml
            result: ValidationResult to add issues to
        """
        pattern = pattern_config['pattern']
        category = pattern_config.get('category', 'unknown')
        severity_str = pattern_config.get('severity', 'error')

        # Convert severity string to enum
        severity = self._parse_severity(severity_str)

        # Find all matches in source and translation
        source_matches = self._find_pattern_matches(source, pattern)
        translation_matches = self._find_pattern_matches(translation, pattern)

        # Check if pattern matches are missing
        missing_terms = source_matches - translation_matches
        if missing_terms:
            result.issues.append(
                self.create_issue(
                    severity,
                    f"Pattern-matched terms ({category}) missing from translation: {', '.join(sorted(missing_terms))}",
                    location=f"terminology.{category}",
                    details={
                        "pattern": pattern,
                        "category": category,
                        "missing_terms": list(sorted(missing_terms)),
                        "source_matches": list(sorted(source_matches)),
                        "translation_matches": list(sorted(translation_matches)),
                    },
                )
            )

        # Check frequency for each matched term
        for term in source_matches & translation_matches:
            source_count = self._count_term(source, term, case_sensitive=True)
            translation_count = self._count_term(translation, term, case_sensitive=True)

            if source_count != translation_count:
                result.issues.append(
                    self.create_issue(
                        ValidationSeverity.WARNING,
                        f"Pattern-matched term '{term}' ({category}) frequency mismatch: source has {source_count}, translation has {translation_count}",
                        location=f"terminology.{category}",
                        details={
                            "term": term,
                            "pattern": pattern,
                            "category": category,
                            "source_count": source_count,
                            "translation_count": translation_count,
                        },
                    )
                )

    def _count_term(self, text: str, term: str, case_sensitive: bool) -> int:
        """
        Count occurrences of a term in text.

        Args:
            text: Text to search
            term: Term to count
            case_sensitive: Whether to use case-sensitive matching

        Returns:
            Number of occurrences
        """
        # Escape the term for regex
        escaped_term = re.escape(term)

        # Add word boundaries, but only if the term starts/ends with word characters
        # This handles special cases like ".NET" which starts with a non-word character
        prefix = r'\b' if term[0].isalnum() or term[0] == '_' else ''
        suffix = r'\b' if term[-1].isalnum() or term[-1] == '_' else ''

        pattern = prefix + escaped_term + suffix

        if case_sensitive:
            return len(re.findall(pattern, text))
        else:
            return len(re.findall(pattern, text, re.IGNORECASE))

    def _find_pattern_matches(self, text: str, pattern: str) -> Set[str]:
        """
        Find all unique matches for a pattern in text.

        Args:
            text: Text to search
            pattern: Regex pattern

        Returns:
            Set of unique matched strings
        """
        matches = re.findall(pattern, text)
        return set(matches)

    def _parse_severity(self, severity_str: str) -> ValidationSeverity:
        """
        Parse severity string to ValidationSeverity enum.

        Args:
            severity_str: Severity string (error, warning, info)

        Returns:
            ValidationSeverity enum value
        """
        severity_map = {
            'error': ValidationSeverity.ERROR,
            'warning': ValidationSeverity.WARNING,
            'info': ValidationSeverity.INFO,
        }
        return severity_map.get(severity_str.lower(), ValidationSeverity.ERROR)
