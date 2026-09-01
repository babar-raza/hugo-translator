"""
Integration tests for real-time repetition detection (TASK-4.1).

Tests the real-time repetition detection and retry mechanism in batch translation.
"""

from unittest.mock import Mock

import pytest

from src.translation_engine.extractor.text_unit import TextUnit
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


class TestRealtimeRepetitionDetection:
    """Test suite for real-time repetition detection during batch translation."""

    @pytest.fixture
    def extractor(self):
        """Create TextUnitExtractor instance for testing."""
        extractor = TextUnitExtractor()
        extractor.batch_stats = {
            "total_batches": 0,
            "total_outer_batches": 0,
            "successful_batches": 0,
            "fallback_batches": 0,
            "mapping_failures": 0,
            "language_purity_failures": 0,
            "translation_errors": 0,
            "individual_translations": 0,
        }
        extractor.fasttext_detector = None
        extractor.batch_stats_tracker = None
        extractor.similarity_tracker = None
        return extractor

    @pytest.fixture
    def mock_model(self):
        """Create mock translation model."""
        model = Mock()
        model.translate = Mock()
        return model

    @pytest.fixture
    def sample_units(self) -> list[TextUnit]:
        """Create sample TextUnits for testing."""
        units = []
        for i in range(3):
            unit = TextUnit(
                unit_id=f"unit_{i}",
                source_text=f"This is test sentence {i}.",
                kind="paragraph",
                node_addr=f"0.{i}",
                do_not_translate=False,
            )
            units.append(unit)
        return units

    def test_detect_batch_repetition_detects_ngram_repetition(self, extractor, sample_units):
        """Test that _detect_batch_repetition correctly identifies n-gram repetition."""
        # Setup: Create unit with repetitive translation
        sample_units[
            0
        ].translated_text = "hello world foo hello world foo hello world foo hello world foo"
        sample_units[1].translated_text = "normal translation without repetition"
        sample_units[2].translated_text = "another normal translation"

        # Execute
        has_repetition, problematic_units = extractor._detect_batch_repetition(sample_units)

        # Assert
        assert has_repetition is True
        assert len(problematic_units) == 1
        assert problematic_units[0].unit_id == "unit_0"

    def test_detect_batch_repetition_no_repetition(self, extractor, sample_units):
        """Test that normal translations pass repetition check."""
        # Setup: Normal translations
        sample_units[0].translated_text = "Dies ist ein Testsatz null."
        sample_units[1].translated_text = "Dies ist ein Testsatz eins."
        sample_units[2].translated_text = "Dies ist ein Testsatz zwei."

        # Execute
        has_repetition, problematic_units = extractor._detect_batch_repetition(sample_units)

        # Assert
        assert has_repetition is False
        assert len(problematic_units) == 0

    def test_detect_batch_repetition_ignores_short_texts(self, extractor, sample_units):
        """Test that very short texts are skipped."""
        # Setup: Short text that would technically have repetition
        sample_units[0].translated_text = "foo foo foo"  # Only 11 chars
        sample_units[1].translated_text = "normal translation"
        sample_units[2].translated_text = "another translation"

        # Execute
        has_repetition, problematic_units = extractor._detect_batch_repetition(sample_units)

        # Assert - short text should be ignored
        assert has_repetition is False
        assert len(problematic_units) == 0

    def test_realtime_detection_triggers_retry(self, extractor, mock_model, sample_units):
        """Test that repetition detection triggers retry with adaptive params."""
        # Setup: First translation has repetition, second doesn't
        repetitive_translation = [
            "miteinander miteinander miteinander miteinander miteinander zusammen arbeiten",
            "eins zwei drei vier fünf",
            "sechs sieben acht neun zehn",
        ]
        clean_translation = [
            "zusammen arbeiten mit verschiedenen Werkzeugen und Methoden",
            "eins zwei drei vier fünf",
            "sechs sieben acht neun zehn",
        ]

        # Mock needs to handle multiple calls including potential fallback
        mock_model.translate.side_effect = [repetitive_translation, clean_translation] + [
            [f"Einzelübersetzung {i}" for i in range(3)]
        ] * 10

        # Bypass language purity check for this test
        extractor._verify_translation_language_purity = Mock(return_value=True)

        # Execute
        success = extractor._translate_single_batch_with_repetition_check(
            sample_units, mock_model, "en", "de"
        )

        # Assert
        assert success is True
        assert mock_model.translate.call_count == 2

        # First call: normal parameters
        first_call = mock_model.translate.call_args_list[0]
        assert first_call[1].get("generation_params") is None

        # Second call: adaptive parameters
        second_call = mock_model.translate.call_args_list[1]
        adaptive_params = second_call[1].get("generation_params")
        assert adaptive_params is not None
        assert adaptive_params["no_repeat_ngram_size"] == 4
        assert adaptive_params["repetition_penalty"] == 1.5
        assert adaptive_params["num_beams"] == 2

        # Check stats
        assert extractor.batch_stats["repetition_detected_count"] == 1
        assert extractor.batch_stats["repetition_retry_count"] == 1
        assert extractor.batch_stats["repetition_retry_success"] == 1

    def test_adaptive_parameters_applied(self, extractor, mock_model, sample_units):
        """Test that adaptive parameters are correctly passed to model."""
        # Setup: Return repetitive translation first
        mock_model.translate.side_effect = [
            ["miteinander " * 10, "test", "test"],  # Repetitive
            ["gut übersetzt", "test", "test"],  # Clean after retry
        ]

        # Execute
        extractor._translate_single_batch_with_repetition_check(
            sample_units, mock_model, "en", "de"
        )

        # Assert: Second call should have adaptive params
        assert mock_model.translate.call_count == 2
        second_call = mock_model.translate.call_args_list[1]
        params = second_call[1]["generation_params"]

        assert params["no_repeat_ngram_size"] == 4
        assert params["repetition_penalty"] == 1.5
        assert params["num_beams"] == 2

    def test_batch_splitting_works(self, extractor, mock_model):
        """Test that persistent repetition triggers batch splitting."""
        # Setup: Create 4 units
        units = []
        for i in range(4):
            unit = TextUnit(
                unit_id=f"unit_{i}",
                source_text=f"Test {i}",
                kind="paragraph",
                node_addr=f"0.{i}",
                do_not_translate=False,
            )
            units.append(unit)

        # Mock: Always return repetitive translations
        mock_model.translate.return_value = ["miteinander " * 10] * 4

        # Mock _fallback_to_individual to avoid recursion
        extractor._fallback_to_individual = Mock()

        # Execute
        success = extractor._translate_single_batch_with_repetition_check(
            units, mock_model, "en", "de"
        )

        # Assert: Should have tried splitting
        # Initial call + retry + 2 splits (each with retry) = multiple calls
        assert mock_model.translate.call_count >= 4
        assert extractor.batch_stats.get("repetition_split_count", 0) >= 1

        # Should eventually fall back
        assert success is False

    def test_recursion_limit_prevents_infinite_splitting(self, extractor, mock_model):
        """Test that recursion limit prevents infinite batch splitting."""
        # Setup: Single unit with persistent repetition
        unit = TextUnit(
            unit_id="unit_0",
            source_text="Test",
            kind="paragraph",
            node_addr="0.0",
            do_not_translate=False,
        )

        # Mock: Always return repetitive translation
        mock_model.translate.return_value = ["miteinander " * 10]

        # Mock fallback
        extractor._fallback_to_individual = Mock()

        # Execute with high retry count (simulating deep recursion)
        success = extractor._translate_single_batch_with_repetition_check(
            [unit], mock_model, "en", "de", retry_count=2
        )

        # Assert: Should stop and fallback (not infinite loop)
        assert success is False
        extractor._fallback_to_individual.assert_called_once()

    def test_no_repetition_skips_retry(self, extractor, mock_model, sample_units):
        """Test that clean translations don't trigger unnecessary retries."""
        # Setup: Clean translation
        mock_model.translate.return_value = [
            "Dies ist ein Testsatz.",
            "Das ist ein weiterer Satz.",
            "Noch ein dritter Satz.",
        ]

        # Execute
        success = extractor._translate_single_batch_with_repetition_check(
            sample_units, mock_model, "en", "de"
        )

        # Assert
        assert success is True
        assert mock_model.translate.call_count == 1  # No retry
        assert extractor.batch_stats.get("repetition_detected_count", 0) == 0
        assert extractor.batch_stats.get("repetition_retry_count", 0) == 0

    def test_tokenize_for_repetition_check(self, extractor):
        """Test tokenization for repetition checking."""
        text = "Hello, world! This is a test."
        words = extractor._tokenize_for_repetition_check(text)

        assert words == ["hello", "world", "this", "is", "a", "test"]

    def test_fallback_after_failed_retry(self, extractor, mock_model, sample_units):
        """Test that failed retry triggers individual fallback."""
        # Setup: Create a single unit to avoid splitting complexity
        single_unit = [sample_units[0]]

        # Always return repetitive translation
        repetitive = ["miteinander " * 10]

        # Need to provide enough repetitive responses for normal + retry attempts
        mock_model.translate.side_effect = [repetitive, repetitive] + [["gut"]] * 10

        # Bypass language purity check
        extractor._verify_translation_language_purity = Mock(return_value=True)

        # Mock fallback to track calls and prevent actual translation
        def mock_fallback(batch, model, src, tgt):
            for unit in batch:
                unit.translated_text = "fallback translation"

        extractor._fallback_to_individual = Mock(side_effect=mock_fallback)

        # Execute
        success = extractor._translate_single_batch_with_repetition_check(
            single_unit, mock_model, "en", "de"
        )

        # Assert
        assert success is False
        # Should have tried: normal + retry, then fallback (no splitting for size 1)
        assert extractor.batch_stats.get("repetition_detected_count", 0) > 0
        assert extractor.batch_stats.get("repetition_retry_count", 0) > 0
        assert extractor.batch_stats.get("repetition_fallback_count", 0) > 0
        extractor._fallback_to_individual.assert_called_once()

    def test_integration_with_batch_translate_units(self, extractor, mock_model):
        """Test full integration with batch_translate_units."""
        # Setup
        units = []
        for i in range(5):
            unit = TextUnit(
                unit_id=f"unit_{i}",
                source_text=f"Test sentence {i}.",
                kind="paragraph",
                node_addr=f"0.{i}",
                do_not_translate=False,
            )
            units.append(unit)

        # Mock model to return clean translations
        mock_model.translate.return_value = [
            "Testsatz eins.",
            "Testsatz zwei.",
            "Testsatz drei.",
            "Testsatz vier.",
            "Testsatz fünf.",
        ]

        # Mock _yield_safe_batches to return single batch (list of units, not list of list)
        extractor._yield_safe_batches = Mock(return_value=[units])
        extractor._estimate_token_count = Mock(return_value=10)

        # Execute
        result = extractor.batch_translate_units(units, mock_model, "en", "de", batch_size=5)

        # Assert
        assert len(result) == 5
        assert all(u.translated_text is not None for u in result)
        assert extractor.batch_stats["total_batches"] == 1
        assert extractor.batch_stats["successful_batches"] == 1
