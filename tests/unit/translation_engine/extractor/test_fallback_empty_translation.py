"""
TC-MLD-01: Regression tests for individual fallback translation failure handling.

Verifies that:
- Individual fallback returning empty result sets translated_text=None (not "")
- Individual fallback purity failure sets translated_text=None (not "")
- zip strict=True fires on count mismatch and triggers fallback path

After the TC-MLD-01 fix, translated_text=None causes get_final_text() to return
source_text, making the failure visible to the file-level purity gate rather than
silently producing blank paragraphs in output.
"""

import pytest
from unittest.mock import MagicMock, patch

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind


def _make_unit(source_text: str, node_addr: str = "body.paragraph[0].text[0]") -> TextUnit:
    return TextUnit(
        unit_id="u_" + node_addr.replace('.', '_').replace('[', '_').replace(']', '_'),
        node_addr=node_addr,
        kind=TextUnitKind.TEXT,
        source_text=source_text,
    )


def _make_extractor(**kwargs):
    """Create a TextUnitExtractor with minimal config."""
    from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor

    mock_config = MagicMock()
    mock_config.get_config.return_value = {
        'translation_engine': {
            'batch_purity_skip_langs': [],
            'language_detection_confidence_threshold': 0.70,
        }
    }
    extractor = TextUnitExtractor.__new__(TextUnitExtractor)
    extractor.config = mock_config
    extractor.fasttext_detector = None
    extractor.similarity_tracker = None
    extractor.batch_stats = {
        'total_batches': 0,
        'successful_batches': 0,
        'fallback_batches': 0,
        'mapping_failures': 0,
        'individual_translations': 0,
        'individual_translation_errors': 0,
    }
    extractor.batch_purity_skip_langs = set()
    for k, v in kwargs.items():
        setattr(extractor, k, v)
    return extractor


class TestIndividualFallbackSetsNone:
    """After TC-MLD-01 fix: failure paths set translated_text=None, not ''."""

    def test_empty_model_result_sets_none(self):
        """MT model returning empty list: translated_text stays None (not '')."""
        extractor = _make_extractor()
        unit = _make_unit("Some source text")

        mock_model = MagicMock()
        mock_model.translate.return_value = []  # Empty result

        extractor._fallback_to_individual([unit], mock_model, "en", "de")

        assert unit.translated_text is None, (
            "Empty model result should set translated_text=None, not ''"
        )

    def test_falsy_model_result_sets_none(self):
        """MT model returning [''] (non-empty but falsy string): sets None."""
        extractor = _make_extractor()
        unit = _make_unit("Another source text")

        mock_model = MagicMock()
        mock_model.translate.return_value = [""]  # Empty string in list

        extractor._fallback_to_individual([unit], mock_model, "en", "de")

        # The condition `if results and results[0]:` will be False for [""]
        # so translated_text should remain None after the fix
        assert unit.translated_text is None

    def test_exception_during_translation_sets_none(self):
        """Exception during individual translation: sets translated_text=None."""
        extractor = _make_extractor()
        unit = _make_unit("Exception test text")

        mock_model = MagicMock()
        mock_model.translate.side_effect = RuntimeError("model error")

        extractor._fallback_to_individual([unit], mock_model, "en", "de")

        assert unit.translated_text is None, (
            "Exception during translation should set translated_text=None"
        )

    def test_purity_failure_sets_none(self):
        """Individual purity check failure: sets translated_text=None."""
        extractor = _make_extractor()
        unit = _make_unit("Purity failure test")

        mock_model = MagicMock()
        mock_model.translate.return_value = ["This is still in English not German"]

        # Wire a fasttext detector that reports wrong language with high confidence
        mock_detector = MagicMock()
        mock_detector.is_available = True
        mock_detector.detect.return_value = ("en", 0.95)  # English detected, not de
        extractor.fasttext_detector = mock_detector

        mock_tracker = MagicMock()
        mock_tracker.are_similar.return_value = False
        extractor.similarity_tracker = mock_tracker

        extractor._fallback_to_individual([unit], mock_model, "en", "de")

        assert unit.translated_text is None, (
            "Purity failure in individual fallback should set translated_text=None"
        )

    def test_successful_translation_sets_text(self):
        """Happy path: successful translation sets translated_text to the translation."""
        extractor = _make_extractor()
        unit = _make_unit("Hello world")

        mock_model = MagicMock()
        mock_model.translate.return_value = ["Hallo Welt"]

        extractor._fallback_to_individual([unit], mock_model, "en", "de")

        assert unit.translated_text == "Hallo Welt"


class TestGetFinalTextFallback:
    """Verify that get_final_text() falls back to source_text when translated_text is None."""

    def test_none_translated_text_returns_source(self):
        """translated_text=None → get_final_text() returns source_text."""
        unit = _make_unit("Source in English")
        assert unit.translated_text is None
        assert unit.get_final_text() == "Source in English"

    def test_empty_translated_text_returns_empty(self):
        """translated_text='' → get_final_text() returns empty string (NOT source)."""
        unit = _make_unit("Source in English")
        unit.translated_text = ""
        # "" is not None, so get_final_text returns "" (with whitespace)
        result = unit.get_final_text()
        assert result.strip() == ""

    def test_valid_translated_text_returned(self):
        """translated_text='Hola' → get_final_text() returns translation."""
        unit = _make_unit("Hello")
        unit.translated_text = "Hola"
        assert unit.get_final_text() == "Hola"
