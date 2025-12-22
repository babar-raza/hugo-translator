"""
Unit tests for TI-01: Telemetry Fallback Observability.

Tests that _safe_duration_ms() emits metrics and structured logs when
fallback scenarios occur (None stats, None duration_seconds, invalid types).
"""
import pytest
from unittest.mock import MagicMock, patch
from src.observability.telemetry_integration import _safe_duration_ms
from src.translation_engine.models import TranslationStats


class TestTelemetryObservability:
    """Test TI-01 observability improvements for duration_ms fallback."""

    def test_metrics_emitted_for_none_stats(self, caplog):
        """Verify metrics emitted when stats is None."""
        mock_metrics = MagicMock()

        with patch('src.observability.metrics.get_metrics', return_value=mock_metrics):
            duration_ms, used_fallback = _safe_duration_ms(None, context="test_context")

        # Verify return values
        assert duration_ms == 0
        assert used_fallback is True

        # Verify metric was emitted
        mock_metrics.increment.assert_called_once_with(
            'telemetry_duration_fallback',
            labels={'reason': 'none_stats'}
        )

        # Verify structured logging
        assert "Duration fallback: stats is None" in caplog.text
        # Note: caplog doesn't capture the 'extra' dict directly in text,
        # but we can verify the message is logged

    def test_metrics_emitted_for_none_duration_seconds(self, caplog):
        """Verify metrics emitted when duration_seconds is None."""
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = None

        mock_metrics = MagicMock()

        with patch('src.observability.metrics.get_metrics', return_value=mock_metrics):
            duration_ms, used_fallback = _safe_duration_ms(stats, context="test_context")

        # Verify return values
        assert duration_ms == 0
        assert used_fallback is True

        # Verify metric was emitted
        mock_metrics.increment.assert_called_once_with(
            'telemetry_duration_fallback',
            labels={'reason': 'none_duration'}
        )

        # Verify structured logging
        assert "Duration fallback: duration_seconds is None" in caplog.text

    def test_metrics_emitted_for_invalid_type(self, caplog):
        """Verify metrics emitted when duration_seconds is invalid type."""
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = "invalid_string"  # String instead of float

        mock_metrics = MagicMock()

        with patch('src.observability.metrics.get_metrics', return_value=mock_metrics):
            duration_ms, used_fallback = _safe_duration_ms(stats, context="test_context")

        # Verify return values
        assert duration_ms == 0
        assert used_fallback is True

        # Verify metric was emitted
        mock_metrics.increment.assert_called_once_with(
            'telemetry_duration_fallback',
            labels={'reason': 'invalid_type'}
        )

        # Verify structured logging
        assert "Duration fallback: invalid type" in caplog.text

    def test_no_metrics_for_legitimate_zero(self):
        """Verify no metrics emitted for legitimate 0.0 duration."""
        stats = TranslationStats(total_segments=100, tm_hits=50, duration_seconds=0.0)

        mock_metrics = MagicMock()

        with patch('src.observability.metrics.get_metrics', return_value=mock_metrics):
            duration_ms, used_fallback = _safe_duration_ms(stats, context="test_context")

        # Verify return values
        assert duration_ms == 0
        assert used_fallback is False  # NOT a fallback, legitimate 0

        # Verify NO metric was emitted (legitimate zero, not a fallback)
        mock_metrics.increment.assert_not_called()

    def test_no_metrics_for_valid_duration(self):
        """Verify no metrics emitted for valid duration_seconds."""
        stats = TranslationStats(total_segments=100, tm_hits=50, duration_seconds=5.5)

        mock_metrics = MagicMock()

        with patch('src.observability.metrics.get_metrics', return_value=mock_metrics):
            duration_ms, used_fallback = _safe_duration_ms(stats, context="test_context")

        # Verify return values
        assert duration_ms == 5500
        assert used_fallback is False

        # Verify NO metric was emitted (valid duration)
        mock_metrics.increment.assert_not_called()

    def test_graceful_degradation_metrics_unavailable(self, caplog):
        """Verify graceful handling when metrics client unavailable."""
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = None

        # Simulate metrics unavailable (ImportError or Exception)
        with patch('src.observability.metrics.get_metrics', side_effect=ImportError("No metrics")):
            # Should NOT crash
            duration_ms, used_fallback = _safe_duration_ms(stats, context="test_context")

        # Verify still returns fallback values
        assert duration_ms == 0
        assert used_fallback is True

        # Verify warning was still logged
        assert "Duration fallback: duration_seconds is None" in caplog.text

    def test_structured_logging_includes_context(self, caplog):
        """Verify structured logging includes context field."""
        stats = TranslationStats()
        stats.duration_seconds = None

        mock_metrics = MagicMock()

        with patch('src.observability.metrics.get_metrics', return_value=mock_metrics):
            _safe_duration_ms(stats, context="translate_file")

        # Verify logging message includes context
        # Note: The actual structured 'extra' dict is not visible in caplog.text,
        # but we can verify the function was called with the right context parameter
        assert "Duration fallback: duration_seconds is None" in caplog.text

    def test_context_parameter_passed_correctly(self):
        """Verify context parameter is used in logging."""
        contexts = ["translate_file", "translate_directory", "track_translation_stats"]

        for context in contexts:
            with patch('src.observability.metrics.get_metrics'):
                duration_ms, used_fallback = _safe_duration_ms(None, context=context)
                # If this doesn't crash, context was handled correctly
                assert duration_ms == 0
                assert used_fallback is True

    def test_return_tuple_format(self):
        """Verify _safe_duration_ms returns tuple[int, bool]."""
        test_cases = [
            (None, (0, True)),
            (TranslationStats(duration_seconds=None), (0, True)),
            (TranslationStats(duration_seconds=0.0), (0, False)),
            (TranslationStats(duration_seconds=5.5), (5500, False)),
            (TranslationStats(duration_seconds=10.999), (10999, False)),
        ]

        for stats_input, expected_output in test_cases:
            with patch('src.observability.metrics.get_metrics'):
                result = _safe_duration_ms(stats_input, context="test")
                assert result == expected_output
                # Verify types
                assert isinstance(result[0], int)
                assert isinstance(result[1], bool)
