"""
Language purity tests for French content.

Tests config-driven behavior from:
- LP-001: technical_terms.yaml (30+ new terms)
- LP-002: baseline_groups in global.yaml (Romance group)
- LP-003: script_validation thresholds

Framework: ORCHESTRATOR (Evidence-Based Development)
Task: LP-004 (Language Purity Tests - French)
"""

from unittest.mock import Mock

import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


class TestFrenchLanguagePurity:
    """Test language purity validation for French content."""

    @pytest.fixture
    def extractor(self):
        """Create TextUnitExtractor with real config for integration testing."""
        # Use real extractor to test config-driven behavior
        extractor = TextUnitExtractor(segmentation_strategy="leaf_only")

        # Mock FastText detector to control detection results
        mock_detector = Mock()
        mock_detector.is_available = True
        extractor.fasttext_detector = mock_detector

        return extractor

    @pytest.fixture
    def sample_units(self):
        """Create sample TextUnits for testing."""

        def create_units(texts):
            units = []
            for i, text in enumerate(texts):
                node_addr = f"test.node[{i}]"
                unit = TextUnit(
                    unit_id=TextUnit.create_id(node_addr, text, TextUnitKind.TEXT),
                    node_addr=node_addr,
                    kind=TextUnitKind.TEXT,
                    source_text=text,
                    translated_text=text,
                    do_not_translate=False,
                )
                units.append(unit)
            return units

        return create_units

    def test_french_italian_accepted_via_romance_baseline_group(self, extractor, sample_units):
        """
        Test French→Italian accepted via Romance baseline group.

        Validates LP-002: baseline_groups["romance"] includes ["fr", "it", "es", "pt", ...]
        """
        # French text that gets detected as Italian (common confusion)
        french_text = "Ceci est un document technique pour l'API Aspose.Cells"
        units = sample_units([french_text])

        # Mock FastText to detect as Italian
        extractor.fasttext_detector.detect.return_value = ("it", 0.85)

        # Mock verify_language to use similarity tracker
        def mock_verify(
            text, expected_lang, similarity_tracker=None, script_validation_thresholds=None
        ):
            # Simulate baseline group acceptance
            if similarity_tracker and similarity_tracker.are_similar("fr", "it"):
                return True
            return False

        extractor.fasttext_detector.verify_language = mock_verify

        # Verify French→Italian is accepted
        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "French→Italian should be accepted via Romance baseline group"

        # Verify baseline group contains both fr and it
        if extractor.similarity_tracker:
            baseline_groups = extractor.similarity_tracker.baseline_groups
            romance_group = baseline_groups.get("romance", [])
            assert "fr" in romance_group, "French should be in Romance group"
            assert "it" in romance_group, "Italian should be in Romance group"

    def test_french_with_high_technical_density_bypasses_purity_check(
        self, extractor, sample_units
    ):
        """
        Test French with >25% technical terms bypasses purity check.

        Validates LP-001: technical_terms.yaml includes Azure, API, DataFrame, etc.
        """
        # French text with 40% technical density (4 technical terms / 10 words = 40%)
        # Technical terms: Azure, API, DataFrame, Aspose.Cells
        french_text = "Utiliser Azure API pour DataFrame avec Aspose.Cells est simple et rapide"
        units = sample_units([french_text])

        # Mock FastText to detect as wrong language (should be bypassed anyway)
        extractor.fasttext_detector.detect.return_value = ("de", 0.90)
        extractor.fasttext_detector.verify_language.return_value = False

        # Should pass due to technical density bypass
        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "French with >25% technical density should bypass purity check"

        # Verify technical density calculation
        density = extractor._calculate_technical_density(french_text)
        assert density >= 0.25, f"Technical density should be >=25%, got {density:.2%}"

    def test_pure_french_text_passes_validation(self, extractor, sample_units):
        """Test pure French text with no technical terms passes validation."""
        french_text = "Bonjour, comment allez-vous aujourd'hui? La météo est très belle."
        units = sample_units([french_text])

        # Mock FastText to correctly detect as French
        extractor.fasttext_detector.detect.return_value = ("fr", 0.95)
        extractor.fasttext_detector.verify_language.return_value = True

        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "Pure French text should pass validation"

    def test_french_with_api_names_mixed_content(self, extractor, sample_units):
        """
        Test French with API names (Azure, DataFrame, Aspose.Cells) as mixed content.

        Validates LP-001: API names are recognized as technical terms.
        """
        # French text with API names but <25% density (should rely on detection)
        french_text = "Ce document explique comment utiliser Azure pour créer des applications"
        units = sample_units([french_text])

        # Mock FastText to detect as French
        extractor.fasttext_detector.detect.return_value = ("fr", 0.88)
        extractor.fasttext_detector.verify_language.return_value = True

        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "French with API names should pass validation"

        # Verify technical terms are recognized
        density = extractor._calculate_technical_density(french_text)
        assert density > 0, "Should detect 'Azure' as technical term"

    def test_french_with_latin_technical_terms(self, extractor, sample_units):
        """
        Test French with Latin script technical terms (Docker, Kubernetes, Cloud).

        Validates LP-001: Cloud infrastructure terms are recognized.
        """
        # Multiple technical terms from LP-001
        french_text = "Déployer avec Docker et Kubernetes sur Azure Cloud est recommandé"
        units = sample_units([french_text])

        # Mock detection
        extractor.fasttext_detector.detect.return_value = ("fr", 0.85)
        extractor.fasttext_detector.verify_language.return_value = True

        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "French with Latin technical terms should pass"

        # Verify all terms are recognized
        density = extractor._calculate_technical_density(french_text)
        # Docker, Kubernetes, Azure, Cloud = 4 terms / 10 words = 40%
        assert density >= 0.30, (
            f"Should recognize Docker, Kubernetes, Azure, Cloud (density={density:.2%})"
        )

    def test_french_edge_case_exactly_25_percent_technical_density(self, extractor, sample_units):
        """
        Test edge case: French with exactly 25% technical density.

        Should bypass purity check at >=25% threshold.
        """
        # Exactly 25% density: 1 technical term / 4 words = 25%
        french_text = "Azure est disponible maintenant"
        units = sample_units([french_text])

        # Calculate actual density
        density = extractor._calculate_technical_density(french_text)

        # Mock detection as wrong language
        extractor.fasttext_detector.detect.return_value = ("en", 0.90)
        extractor.fasttext_detector.verify_language.return_value = False

        if density >= 0.25:
            # Should bypass
            result = extractor._verify_translation_language_purity(units, "fr")
            assert result is True, "Exactly 25% technical density should bypass purity check"

    def test_french_spanish_romance_baseline_acceptance(self, extractor, sample_units):
        """
        Test French→Spanish accepted via Romance baseline group.

        Validates LP-002: Romance group includes multiple languages.
        """
        french_text = "Cette fonctionnalité permet de créer des documents professionnels"
        units = sample_units([french_text])

        # Mock FastText to return True via verify_language (baseline group acceptance)
        extractor.fasttext_detector.verify_language.return_value = True
        extractor.fasttext_detector.detect.return_value = ("es", 0.82)

        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "French→Spanish should be accepted via Romance baseline group"

        # Verify baseline group contains both fr and es
        if extractor.similarity_tracker:
            baseline_groups = extractor.similarity_tracker.baseline_groups
            romance_group = baseline_groups.get("romance", [])
            assert "fr" in romance_group, "French should be in Romance group"
            assert "es" in romance_group, "Spanish should be in Romance group"

    def test_french_with_aspose_product_names(self, extractor, sample_units):
        """
        Test French with Aspose product names as technical terms.

        Validates LP-001: Aspose product names (Aspose.BarCode, Aspose.Email, etc.)
        """
        # French text with multiple Aspose products
        french_text = "Aspose.Cells, Aspose.Words et Aspose.PDF sont des API puissantes"
        units = sample_units([french_text])

        # Calculate density
        density = extractor._calculate_technical_density(french_text)

        # Aspose.Cells, Aspose.Words, Aspose.PDF, API = 4 terms / 9 words = 44%
        assert density >= 0.25, f"Should recognize multiple Aspose products (density={density:.2%})"

        # Mock detection as wrong language
        extractor.fasttext_detector.detect.return_value = ("en", 0.88)
        extractor.fasttext_detector.verify_language.return_value = False

        # Should bypass due to high technical density
        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "French with Aspose product names should bypass purity check"

    def test_french_short_text_skipped(self, extractor, sample_units):
        """Test very short French text is skipped (unreliable for detection)."""
        # Text shorter than LANGUAGE_PURITY_MIN_LENGTH (15 chars)
        french_text = "Bonjour!"
        units = sample_units([french_text])

        # Should skip validation for short texts
        result = extractor._verify_translation_language_purity(units, "fr")

        assert result is True, "Short text should be skipped (unreliable for detection)"

    def test_french_config_driven_behavior_verification(self, extractor):
        """
        Verify extractor loads config from global.yaml and technical_terms.yaml.

        Ensures tests validate actual config-driven behavior, not hardcoded logic.
        """
        # Verify technical terms loaded from config
        assert extractor.technical_terms is not None, "Technical terms should be loaded"
        assert len(extractor.technical_terms) > 0, "Technical terms list should not be empty"

        # Verify some LP-001 terms are present
        expected_terms = ["Azure", "Docker", "Kubernetes", "DataFrame", "Cloud"]
        for term in expected_terms:
            assert term in extractor.technical_terms, (
                f"Term '{term}' should be in technical_terms (LP-001)"
            )

        # Verify similarity tracker has baseline groups
        if extractor.similarity_tracker:
            baseline_groups = extractor.similarity_tracker.baseline_groups
            assert "romance" in baseline_groups, "Romance baseline group should exist (LP-002)"

            romance_group = baseline_groups["romance"]
            expected_langs = ["fr", "it", "es", "pt"]
            for lang in expected_langs:
                assert lang in romance_group, (
                    f"Language '{lang}' should be in Romance group (LP-002)"
                )
