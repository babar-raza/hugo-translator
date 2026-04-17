"""Terminology auto-discovery from source corpus.

This module implements pattern-based discovery to find new terminology:
- Aspose products (Aspose.*)
- Platform names (.NET, Java-like)
- PascalCase identifiers (API references)
- Repeated brand names

Discovery uses frequency analysis and confidence scoring to identify
likely terminology that should be protected during translation.
"""

import os
import re
from collections import Counter
from dataclasses import dataclass


@dataclass
class DiscoveredTerm:
    """A term discovered through corpus analysis.

    Attributes:
        term_text: The discovered term
        category: Suggested category
        frequency: Number of occurrences in corpus
        confidence: Confidence score (0.0-1.0)
        examples: Example contexts where term appears
    """
    term_text: str
    category: str
    frequency: int
    confidence: float
    examples: list[str]


class TerminologyDiscovery:
    """Discovers new terminology from source corpus.

    Uses pattern-based discovery to find:
    - New Aspose products (Aspose.NewProduct)
    - New platform names (similar to .NET, Java)
    - Frequent PascalCase identifiers (API references)
    - Repeated brand names

    Example:
        discovery = TerminologyDiscovery(config)
        corpus = [file1_content, file2_content, ...]
        discovered = discovery.discover_terms(corpus)
        discovery.save_discovered_terms(discovered, "data/terminology/discovered_terms.yaml")
    """

    def __init__(self, config: dict):
        """Initialize discovery with configuration.

        Args:
            config: Auto-discovery config from terminology.yaml
        """
        self.enabled = config.get('enabled', False)
        self.min_frequency = config.get('min_frequency', 3)
        self.confidence_threshold = config.get('confidence_threshold', 0.8)

        # Patterns for discovery
        self.discovery_patterns = {
            # Aspose product families: Aspose.Words, Aspose.PDF, Aspose.Cells, …
            'aspose_product': r'Aspose\.[A-Z][a-zA-Z]+',
            # 2+ part PascalCase API identifiers: DocumentBuilder, SaveFormat, MemoryStream
            'pascal_case': r'\b[A-Z][a-z]+(?:[A-Z][a-z]+)+\b',  # 2+ PascalCase parts
            # UPPER_CASE constants (4+ chars): MAX_SIZE, DEFAULT_TIMEOUT
            'constant_name': r'\b[A-Z_]{4,}\b',
            # All-caps acronyms 2-8 chars: GZ, XZ, TAR, ZIP, PPTX, HTML, …
            'file_format': r'\b[A-Z][A-Z0-9]{1,7}\b',
            # Platform names that begin with a dot when NOT embedded in an identifier:
            # " .NET", "(.NET" but NOT "Aspose.NET" (that's aspose_product)
            'dotted_name': r'(?<![a-zA-Z0-9])\.[A-Z][A-Z]+\b',
        }

        # Exception filter (false positives to exclude)
        self.exceptions = {
            # Calendar words
            'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday',
            'Saturday', 'Sunday', 'January', 'February', 'March',
            'April', 'May', 'June', 'July', 'August', 'September',
            'October', 'November', 'December',
            # Common English pronoun/article false positives
            'The', 'This', 'That', 'These', 'Those',
            # Common all-caps English words that are NOT technical identifiers
            'THE', 'AND', 'FOR', 'NOT', 'ARE', 'BUT', 'CAN', 'HAS',
            'GET', 'SET', 'PUT', 'NEW', 'OLD', 'ONE', 'TWO', 'ALL',
            # Generic programming/doc words too broad to protect
            'FILE', 'PATH', 'NAME', 'TYPE', 'CODE', 'DATA', 'TEXT',
            'USER', 'HOST', 'PORT', 'MODE', 'SIZE', 'TIME', 'DATE',
            'FROM', 'THEN', 'WHEN', 'THAN', 'WILL', 'WITH', 'INTO',
            'OVER', 'EACH', 'BOTH', 'ALSO', 'NOTE', 'INFO', 'WARN',
            'TODO', 'LINK', 'MORE', 'STEP', 'TIPS', 'BEST', 'NEXT',
            'OPEN', 'SAVE', 'LOAD', 'SEND', 'READ', 'COPY', 'MOVE',
            'LIST', 'ITEM', 'NEED', 'MAKE', 'TAKE', 'GIVE', 'SHOW',
            # Very common 2-char English initials
            'OK', 'NO', 'GO', 'DO', 'IS', 'IT', 'AT', 'AN', 'IN',
            'ON', 'UP', 'BY', 'OR', 'IF', 'AS', 'BE', 'US',
            # Platform suffixes covered by dotted_name (.NET, .COM, .EXE, .DLL)
            # — exclude bare forms to avoid double-counting
            'NET', 'COM', 'EXE', 'DLL',
        }

    def discover_terms(self, corpus: list[str]) -> list[DiscoveredTerm]:
        """Discover terminology from corpus.

        Args:
            corpus: List of source file contents

        Returns:
            List of discovered terms sorted by confidence
        """
        if not self.enabled:
            return []

        # Extract candidates
        candidates = self._extract_candidates(corpus)

        # Filter by frequency
        candidates = self._filter_by_frequency(candidates)

        # Score confidence
        discovered = self._score_confidence(candidates, corpus)

        # Filter by confidence threshold
        discovered = [
            term for term in discovered
            if term.confidence >= self.confidence_threshold
        ]

        # Sort by confidence (descending)
        discovered.sort(key=lambda t: t.confidence, reverse=True)

        return discovered

    def _extract_candidates(self, corpus: list[str]) -> dict[str, list[str]]:
        """Extract candidate terms using patterns.

        Args:
            corpus: List of source texts

        Returns:
            Dict mapping category to list of candidate terms
        """
        candidates = {}

        for category, pattern in self.discovery_patterns.items():
            candidates[category] = []
            for text in corpus:
                matches = re.findall(pattern, text)
                candidates[category].extend(matches)

        return candidates

    def _filter_by_frequency(self, candidates: dict[str, list[str]]) -> dict[str, Counter]:
        """Filter candidates by minimum frequency.

        Args:
            candidates: Dict of candidate lists

        Returns:
            Dict of counters with frequent terms only
        """
        filtered = {}

        for category, terms in candidates.items():
            counter = Counter(terms)
            # Remove exceptions
            for exception in self.exceptions:
                if exception in counter:
                    del counter[exception]
            # Filter by frequency
            filtered[category] = Counter({
                term: count for term, count in counter.items()
                if count >= self.min_frequency
            })

        return filtered

    def _score_confidence(
        self,
        candidates: dict[str, Counter],
        corpus: list[str]
    ) -> list[DiscoveredTerm]:
        """Score confidence for each candidate.

        Confidence based on:
        - Frequency (higher = more confident)
        - Pattern strength (Aspose.* = high, PascalCase = medium)
        - Context consistency (similar contexts = higher)

        Args:
            candidates: Filtered candidates
            corpus: Source corpus for context extraction

        Returns:
            List of discovered terms with confidence scores
        """
        discovered = []

        for category, counter in candidates.items():
            for term, frequency in counter.items():
                # Base confidence from frequency
                # Normalize: freq 3 = 0.6, freq 10+ = 1.0
                freq_confidence = min(0.6 + (frequency - 3) * 0.05, 1.0)

                # Category confidence
                category_weights = {
                    'aspose_product': 1.0,  # Very confident — always Aspose product
                    'dotted_name': 0.9,     # High — .NET style platform names
                    'file_format': 0.8,     # High — all-caps acronyms in tech docs
                    'pascal_case': 0.75,    # Medium-high — 2+ part API identifiers
                    'constant_name': 0.65,  # Medium — UPPER_CASE may be generic
                }
                category_confidence = category_weights.get(category, 0.5)

                # Combined confidence
                confidence = (freq_confidence + category_confidence) / 2.0

                # Extract examples (first 3 occurrences)
                examples = self._extract_examples(term, corpus, max_examples=3)

                discovered.append(DiscoveredTerm(
                    term_text=term,
                    category=category,
                    frequency=frequency,
                    confidence=confidence,
                    examples=examples
                ))

        return discovered

    def _extract_examples(
        self,
        term: str,
        corpus: list[str],
        max_examples: int = 3
    ) -> list[str]:
        """Extract example contexts for term.

        Args:
            term: Term to find examples for
            corpus: Source corpus
            max_examples: Maximum number of examples

        Returns:
            List of context snippets
        """
        examples = []

        for text in corpus:
            if len(examples) >= max_examples:
                break

            pos = text.find(term)
            if pos != -1:
                # Extract context (50 chars before/after)
                start = max(0, pos - 50)
                end = min(len(text), pos + len(term) + 50)
                context = text[start:end].strip()
                examples.append(f"...{context}...")

        return examples

    def save_discovered_terms(
        self,
        discovered: list[DiscoveredTerm],
        output_path: str
    ):
        """Save discovered terms to YAML for manual review.

        Args:
            discovered: List of discovered terms
            output_path: Path to save YAML file
        """
        import yaml

        os.makedirs(os.path.dirname(output_path), exist_ok=True)

        # Convert to YAML structure
        yaml_data = {
            'version': '1.0',
            'discovered_terms': []
        }

        for term in discovered:
            yaml_data['discovered_terms'].append({
                'term': term.term_text,
                'category': term.category,
                'frequency': term.frequency,
                'confidence': round(term.confidence, 2),
                'examples': term.examples,
                'status': 'pending_review',  # Manual review required
                'suggested_rule': {
                    'preserve_mode': 'protect',
                    'severity': 'warning',
                    'case_sensitive': True
                }
            })

        with open(output_path, 'w', encoding='utf-8') as f:
            yaml.dump(yaml_data, f, default_flow_style=False, allow_unicode=True)

        print(f"Discovered {len(discovered)} terms, saved to {output_path}")
        print("Review and manually add approved terms to config/terminology.yaml")
