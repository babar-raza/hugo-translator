"""Terminology detection using exact and pattern matching.

This module provides the TerminologyDetector class which scans text for
terminology based on exact string matches or regex patterns. It handles:
- Exact string matching (case-sensitive or insensitive)
- Regex pattern matching
- Word boundary enforcement (to avoid false positives like "net" in "internet")
- Overlap resolution (longest match wins)
"""

import re
from typing import List
from src.translation_engine.terminology.models import TermRule, DetectedTerm, PreserveMode


class TerminologyDetector:
    """Detects terminology in text using exact and pattern matching.

    Supports:
    - Exact string matching (case-sensitive or insensitive)
    - Regex pattern matching
    - Word boundary enforcement
    - Overlapping match resolution (longest wins)

    Example:
        detector = TerminologyDetector(rules)
        detected = detector.detect("Aspose.Words for .NET")
        # Returns [DetectedTerm("Aspose.Words", ...), DetectedTerm(".NET", ...)]
    """

    def __init__(self, rules: List[TermRule]):
        """Initialize detector with terminology rules.

        Args:
            rules: List of term rules to apply
        """
        # Filter out rules with PreserveMode.NONE as they don't need detection
        self.rules = [r for r in rules if r.preserve_mode != PreserveMode.NONE]

    def detect(self, text: str) -> List[DetectedTerm]:
        """Detect all terminology in text.

        Args:
            text: Text to scan for terminology

        Returns:
            List of detected terms, sorted by position
        """
        detected = []

        for rule in self.rules:
            if rule.term:
                # Exact matching
                detected.extend(self._detect_exact(text, rule))
            elif rule.pattern:
                # Pattern matching
                detected.extend(self._detect_pattern(text, rule))

        # Remove overlaps (keep longest match)
        detected = self._resolve_overlaps(detected)

        # Sort by position
        detected.sort(key=lambda t: t.start_pos)

        return detected

    def _detect_exact(self, text: str, rule: TermRule) -> List[DetectedTerm]:
        """Detect exact term matches.

        Args:
            text: Text to search
            rule: Rule with exact term

        Returns:
            List of detected terms
        """
        detected = []
        search_text = text if rule.case_sensitive else text.lower()
        search_term = rule.term if rule.case_sensitive else rule.term.lower()

        start = 0
        while True:
            pos = search_text.find(search_term, start)
            if pos == -1:
                break

            # Check word boundaries for some terms (.NET, Java)
            # This prevents matching "net" in "internet" or "java" in "javascript"
            if self._is_word_boundary_match(text, pos, len(search_term)):
                detected.append(DetectedTerm(
                    term_text=text[pos:pos + len(search_term)],
                    rule=rule,
                    start_pos=pos,
                    end_pos=pos + len(search_term),
                    confidence=1.0
                ))

            start = pos + 1

        return detected

    def _detect_pattern(self, text: str, rule: TermRule) -> List[DetectedTerm]:
        """Detect pattern matches.

        Args:
            text: Text to search
            rule: Rule with regex pattern

        Returns:
            List of detected terms
        """
        detected = []
        flags = 0 if rule.case_sensitive else re.IGNORECASE

        try:
            for match in re.finditer(rule.pattern, text, flags):
                detected.append(DetectedTerm(
                    term_text=match.group(0),
                    rule=rule,
                    start_pos=match.start(),
                    end_pos=match.end(),
                    confidence=1.0
                ))
        except re.error as e:
            # Invalid regex pattern - log warning and skip
            # In production, this should log via logging module
            pass

        return detected

    def _is_word_boundary_match(self, text: str, pos: int, length: int) -> bool:
        """Check if match is at word boundary.

        For terms like ".NET", we want word boundaries.
        For company names embedded in other words, we may not.

        Args:
            text: Full text
            pos: Match start position
            length: Match length

        Returns:
            True if match is at word boundary or boundary check not needed
        """
        # Check character before
        if pos > 0:
            char_before = text[pos - 1]
            if char_before.isalnum():
                return False

        # Check character after
        if pos + length < len(text):
            char_after = text[pos + length]
            if char_after.isalnum():
                return False

        return True

    def _resolve_overlaps(self, detected: List[DetectedTerm]) -> List[DetectedTerm]:
        """Resolve overlapping matches (keep longest).

        Args:
            detected: List of detected terms (may overlap)

        Returns:
            List with overlaps removed
        """
        if not detected:
            return []

        # Sort by start position, then by length (descending)
        sorted_terms = sorted(detected, key=lambda t: (t.start_pos, -(t.end_pos - t.start_pos)))

        result = []
        last_end = -1

        for term in sorted_terms:
            # Skip if overlaps with previous term
            if term.start_pos < last_end:
                continue

            result.append(term)
            last_end = term.end_pos

        return result
