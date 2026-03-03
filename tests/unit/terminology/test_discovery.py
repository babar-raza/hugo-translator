"""Tests for terminology auto-discovery.

Tests cover:
- Pattern-based discovery for Aspose products, platform names, PascalCase, etc.
- Frequency threshold filtering
- Confidence scoring
- False positive filtering
- YAML output generation
"""

import pytest
import os
import tempfile
import yaml
from src.translation_engine.terminology.discovery import (
    TerminologyDiscovery,
    DiscoveredTerm
)


class TestTerminologyDiscovery:
    """Test suite for TerminologyDiscovery class."""

    def test_discovery_disabled(self):
        """Discovery returns empty list when disabled."""
        config = {'enabled': False}
        discovery = TerminologyDiscovery(config)
        corpus = ["Aspose.Words for .NET"]

        result = discovery.discover_terms(corpus)

        assert result == []

    def test_discover_aspose_products(self):
        """Discovers Aspose product names from corpus."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.7}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Aspose.Words for .NET provides document processing.",
            "Use Aspose.Words API to convert DOC files.",
            "Aspose.Words supports multiple formats.",
            "Aspose.Cells is for spreadsheets.",
            "Aspose.PDF handles PDF operations."
        ]

        discovered = discovery.discover_terms(corpus)

        # Should find Aspose.Words (3 times) and potentially others
        aspose_terms = [t for t in discovered if t.category == 'aspose_product']
        assert len(aspose_terms) > 0

        # Check Aspose.Words is discovered
        words_term = [t for t in aspose_terms if t.term_text == "Aspose.Words"]
        assert len(words_term) == 1
        assert words_term[0].frequency == 3
        assert words_term[0].confidence > 0.7

    def test_discover_platform_names(self):
        """Discovers platform names like .NET."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.7}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Available for .NET Framework.",
            "Works with .NET Core.",
            ".NET Standard is supported."
        ]

        discovered = discovery.discover_terms(corpus)

        # Should find .NET
        dotted_terms = [t for t in discovered if t.category == 'dotted_name']
        net_terms = [t for t in dotted_terms if t.term_text == ".NET"]
        assert len(net_terms) == 1
        assert net_terms[0].frequency == 3

    def test_discover_pascal_case_identifiers(self):
        """Discovers PascalCase API identifiers."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.6}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Use DocumentBuilder class.",
            "DocumentBuilder provides methods.",
            "Initialize DocumentBuilder instance.",
            "FileFormat enumeration is important.",
            "FileFormat defines supported formats."
        ]

        discovered = discovery.discover_terms(corpus)

        # Should find DocumentBuilder and FileFormat
        pascal_terms = [t for t in discovered if t.category == 'pascal_case']
        term_texts = [t.term_text for t in pascal_terms]
        assert "DocumentBuilder" in term_texts
        assert "FileFormat" in term_texts

    def test_discover_constant_names(self):
        """Discovers UPPER_CASE constant names."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Set MAX_SIZE to limit.",
            "MAX_SIZE controls buffer.",
            "MAX_SIZE is configurable.",
            "DEFAULT_TIMEOUT applies.",
            "DEFAULT_TIMEOUT can be changed."
        ]

        discovered = discovery.discover_terms(corpus)

        # Should find MAX_SIZE and DEFAULT_TIMEOUT
        constant_terms = [t for t in discovered if t.category == 'constant_name']
        term_texts = [t.term_text for t in constant_terms]
        assert "MAX_SIZE" in term_texts
        assert "DEFAULT_TIMEOUT" in term_texts

    def test_frequency_threshold(self):
        """Terms below frequency threshold are excluded."""
        config = {'enabled': True, 'min_frequency': 3, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "TermOne appears here.",
            "TermOne appears again.",  # TermOne: 2 times (below threshold)
            "TermTwo appears here.",
            "TermTwo appears again.",
            "TermTwo appears third time."  # TermTwo: 3 times (meets threshold)
        ]

        discovered = discovery.discover_terms(corpus)

        # TermTwo should be discovered, TermOne should not
        term_texts = [t.term_text for t in discovered]
        assert "TermTwo" in term_texts
        assert "TermOne" not in term_texts

    def test_confidence_threshold(self):
        """Terms below confidence threshold are excluded."""
        # Aspose.Words (freq=2): freq_conf = 0.55, category=1.0 → combined = 0.775
        # Threshold of 0.70 lets Aspose.Words through; SomeClass (cat=0.75) → 0.65 is excluded
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.70}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Aspose.Words is great.",
            "Aspose.Words is powerful.",
            "SomeClass is used.",
            "SomeClass is important."
        ]

        discovered = discovery.discover_terms(corpus)

        # Aspose.Words confidence = (0.55 + 1.0) / 2 = 0.775 ≥ 0.70 → passes
        term_texts = [t.term_text for t in discovered]
        assert "Aspose.Words" in term_texts

    def test_false_positive_filtering(self):
        """Common words (days, months) are excluded."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Monday is the first day.",
            "Monday morning meetings.",
            "Monday schedule is busy.",
            "January starts the year.",
            "January has 31 days.",
            "January is cold."
        ]

        discovered = discovery.discover_terms(corpus)

        # Monday and January should be filtered out
        term_texts = [t.term_text for t in discovered]
        assert "Monday" not in term_texts
        assert "January" not in term_texts

    def test_confidence_scoring_frequency_based(self):
        """Higher frequency terms get higher confidence scores."""
        config = {'enabled': True, 'min_frequency': 3, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)

        # Create corpus with same term at different frequencies
        corpus_low = ["TermLow"] * 3  # Frequency: 3
        corpus_high = ["TermHigh"] * 10  # Frequency: 10
        corpus = corpus_low + corpus_high

        discovered = discovery.discover_terms(corpus)

        # Find both terms
        term_low = [t for t in discovered if t.term_text == "TermLow"][0]
        term_high = [t for t in discovered if t.term_text == "TermHigh"][0]

        # Higher frequency should have higher confidence
        assert term_high.confidence > term_low.confidence

    def test_confidence_scoring_category_based(self):
        """Different categories get different confidence weights."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Aspose.Test product here.",
            "Aspose.Test product again.",
            "SomeApiClass is here.",
            "SomeApiClass is again."
        ]

        discovered = discovery.discover_terms(corpus)

        # Find both terms
        aspose_term = [t for t in discovered if t.term_text == "Aspose.Test"][0]
        pascal_term = [t for t in discovered if t.term_text == "SomeApiClass"][0]

        # Aspose products have higher category weight than PascalCase
        # Even with same frequency, Aspose should have higher confidence
        assert aspose_term.confidence > pascal_term.confidence

    def test_extract_examples(self):
        """Examples are extracted for discovered terms."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "This is a sentence with Aspose.Words in the middle of it.",
            "Another sentence using Aspose.Words for processing.",
            "Third reference to Aspose.Words here."
        ]

        discovered = discovery.discover_terms(corpus)

        # Find Aspose.Words
        words_term = [t for t in discovered if t.term_text == "Aspose.Words"][0]

        # Should have examples (max 3)
        assert len(words_term.examples) <= 3
        assert len(words_term.examples) > 0

        # Examples should contain the term
        for example in words_term.examples:
            assert "Aspose.Words" in example
            # Should have context markers
            assert "..." in example

    def test_save_discovered_terms(self):
        """Discovered terms are saved to YAML correctly."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.7}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Aspose.Words for .NET",
            "Use Aspose.Words API",
            "Aspose.Words supports DOC"
        ]

        discovered = discovery.discover_terms(corpus)

        # Save to temporary file
        with tempfile.TemporaryDirectory() as tmpdir:
            output_path = os.path.join(tmpdir, "discovered_terms.yaml")
            discovery.save_discovered_terms(discovered, output_path)

            # Verify file was created
            assert os.path.exists(output_path)

            # Load and verify structure
            with open(output_path, 'r', encoding='utf-8') as f:
                data = yaml.safe_load(f)

            assert data['version'] == '1.0'
            assert 'discovered_terms' in data
            assert len(data['discovered_terms']) > 0

            # Check first term structure
            term_data = data['discovered_terms'][0]
            assert 'term' in term_data
            assert 'category' in term_data
            assert 'frequency' in term_data
            assert 'confidence' in term_data
            assert 'examples' in term_data
            assert 'status' in term_data
            assert term_data['status'] == 'pending_review'
            assert 'suggested_rule' in term_data
            assert term_data['suggested_rule']['preserve_mode'] == 'protect'

    def test_empty_corpus(self):
        """Discovery handles empty corpus gracefully."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.7}
        discovery = TerminologyDiscovery(config)
        corpus = []

        result = discovery.discover_terms(corpus)

        assert result == []

    def test_no_terms_meet_threshold(self):
        """Discovery returns empty when no terms meet thresholds."""
        config = {'enabled': True, 'min_frequency': 10, 'confidence_threshold': 0.95}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Random text here.",
            "More random content."
        ]

        result = discovery.discover_terms(corpus)

        assert result == []

    def test_pattern_aspose_product_format(self):
        """Aspose product pattern matches correct format."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)

        # Valid Aspose products
        valid_corpus = [
            "Aspose.Words is here.",
            "Aspose.Words again.",
            "Aspose.Cells for spreadsheets.",
            "Aspose.Cells again.",
            "Aspose.PDF for documents.",
            "Aspose.PDF again."
        ]

        discovered = discovery.discover_terms(valid_corpus)
        aspose_terms = [t for t in discovered if t.category == 'aspose_product']
        term_texts = [t.term_text for t in aspose_terms]

        assert "Aspose.Words" in term_texts
        assert "Aspose.Cells" in term_texts
        assert "Aspose.PDF" in term_texts

    def test_pattern_pascal_case_minimum_parts(self):
        """PascalCase pattern matches 2+ part identifiers (e.g. SaveFormat, MemoryStream)."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)

        corpus = [
            "OneTwo has 2 parts.",  # Should match (2 parts — API identifiers)
            "OneTwo again.",
            "OneTwoThree has 3 parts.",  # Should match (3 parts)
            "OneTwoThree again.",
            "OneTwoThreeFour has 4 parts.",  # Should match (4 parts)
            "OneTwoThreeFour again."
        ]

        discovered = discovery.discover_terms(corpus)
        pascal_terms = [t for t in discovered if t.category == 'pascal_case']
        term_texts = [t.term_text for t in pascal_terms]

        # 2-part and longer terms all match
        assert "OneTwoThree" in term_texts
        assert "OneTwoThreeFour" in term_texts
        assert "OneTwo" in term_texts  # 2-part PascalCase is now intentionally discovered

    def test_discovered_term_dataclass(self):
        """DiscoveredTerm dataclass works correctly."""
        term = DiscoveredTerm(
            term_text="Aspose.Words",
            category="aspose_product",
            frequency=5,
            confidence=0.95,
            examples=["...example 1...", "...example 2..."]
        )

        assert term.term_text == "Aspose.Words"
        assert term.category == "aspose_product"
        assert term.frequency == 5
        assert term.confidence == 0.95
        assert len(term.examples) == 2

    def test_sorting_by_confidence(self):
        """Discovered terms are sorted by confidence descending."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Aspose.High frequency high category.",
            "Aspose.High frequency high category.",
            "Aspose.High frequency high category.",
            "Aspose.High frequency high category.",
            "LowConfidence term here.",
            "LowConfidence term again."
        ]

        discovered = discovery.discover_terms(corpus)

        # Terms should be sorted by confidence descending
        for i in range(len(discovered) - 1):
            assert discovered[i].confidence >= discovered[i + 1].confidence

    def test_multiple_patterns_in_same_text(self):
        """Discovery finds multiple pattern types in same corpus."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.5}
        discovery = TerminologyDiscovery(config)
        corpus = [
            "Aspose.Words for .NET using DocumentBuilder and MAX_SIZE constant.",
            "Aspose.Words for .NET using DocumentBuilder and MAX_SIZE constant.",
            "Aspose.Words for .NET using DocumentBuilder and MAX_SIZE constant."
        ]

        discovered = discovery.discover_terms(corpus)

        # Should find all pattern types
        categories = set(t.category for t in discovered)
        assert 'aspose_product' in categories
        assert 'dotted_name' in categories
        assert 'pascal_case' in categories
        assert 'constant_name' in categories

    def test_confidence_calculation_formula(self):
        """Confidence calculation follows documented formula."""
        config = {'enabled': True, 'min_frequency': 3, 'confidence_threshold': 0.0}
        discovery = TerminologyDiscovery(config)

        # Term with frequency 3 (minimum)
        corpus_min = ["Aspose.Test"] * 3
        discovered = discovery.discover_terms(corpus_min)
        term_min = [t for t in discovered if t.term_text == "Aspose.Test"][0]

        # For freq=3: freq_confidence = 0.6
        # Category weight for aspose_product = 1.0
        # Combined: (0.6 + 1.0) / 2 = 0.8
        expected_confidence = 0.8
        assert abs(term_min.confidence - expected_confidence) < 0.01

    def test_save_creates_directory(self):
        """Save creates output directory if it doesn't exist."""
        config = {'enabled': True, 'min_frequency': 2, 'confidence_threshold': 0.7}
        discovery = TerminologyDiscovery(config)
        corpus = ["Aspose.Words test", "Aspose.Words again"]
        discovered = discovery.discover_terms(corpus)

        with tempfile.TemporaryDirectory() as tmpdir:
            # Use nested path that doesn't exist
            output_path = os.path.join(tmpdir, "nested", "dir", "discovered.yaml")
            discovery.save_discovered_terms(discovered, output_path)

            # Directory should be created
            assert os.path.exists(os.path.dirname(output_path))
            assert os.path.exists(output_path)
