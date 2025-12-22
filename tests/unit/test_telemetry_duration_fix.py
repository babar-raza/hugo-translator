"""
Unit tests for PR-04: Telemetry API 422 Error Fix.

Tests that duration_ms is never None when passed to telemetry API.
"""
import pytest
from unittest.mock import MagicMock
from src.observability.telemetry_integration import TranslationTelemetry
from src.translation_engine.models import TranslationStats


class TestTelemetryDurationFix:
    """Test that PR-04 fix prevents None duration_ms values (422 errors)."""

    def test_track_stats_with_none_duration_seconds(self):
        """Verify duration_ms=0 when duration_seconds is None."""
        # Create stats with explicit None duration_seconds
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50
        )
        stats.duration_seconds = None  # Explicit None

        # Create telemetry and mock run_context
        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True  # Force enabled
        mock_run_context = MagicMock()

        # Call track_translation_stats
        telemetry.track_translation_stats(mock_run_context, stats)

        # Verify set_metrics was called with duration_ms=0 (not None)
        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 0
        assert call_kwargs['duration_ms'] is not None

    def test_track_stats_with_zero_duration_seconds(self):
        """Verify duration_ms=0 when duration_seconds is 0.0."""
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50,
            duration_seconds=0.0
        )

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        mock_run_context = MagicMock()

        telemetry.track_translation_stats(mock_run_context, stats)

        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 0
        assert call_kwargs['duration_ms'] is not None

    def test_track_stats_with_valid_duration_seconds(self):
        """Verify duration_ms calculated correctly for valid duration_seconds."""
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50,
            duration_seconds=5.5  # 5.5 seconds = 5500 ms
        )

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        mock_run_context = MagicMock()

        telemetry.track_translation_stats(mock_run_context, stats)

        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 5500
        assert isinstance(call_kwargs['duration_ms'], int)

    def test_track_stats_with_none_stats_object(self):
        """Verify graceful handling when stats object itself is None."""
        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        mock_run_context = MagicMock()

        # Pass None as stats
        telemetry.track_translation_stats(mock_run_context, None)

        # Should still call set_metrics with default values
        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 0
        assert call_kwargs['duration_ms'] is not None

    def test_track_stats_with_invalid_duration_type(self):
        """Verify graceful handling of invalid duration_seconds type."""
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50
        )
        stats.duration_seconds = "invalid"  # String instead of float

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True
        mock_run_context = MagicMock()

        # Should not raise exception, defaults to 0
        telemetry.track_translation_stats(mock_run_context, stats)

        mock_run_context.set_metrics.assert_called_once()
        call_kwargs = mock_run_context.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 0
        assert call_kwargs['duration_ms'] is not None

    def test_duration_ms_always_integer_type(self):
        """Verify duration_ms is always int, never float or None."""
        test_values = [0.0, 1.5, 10.999, 100.0, None]

        telemetry = TranslationTelemetry(enabled=False)
        telemetry.enabled = True

        for value in test_values:
            stats = TranslationStats()
            stats.duration_seconds = value
            mock_run_context = MagicMock()

            telemetry.track_translation_stats(mock_run_context, stats)

            call_kwargs = mock_run_context.set_metrics.call_args[1]
            duration_ms = call_kwargs['duration_ms']

            # Must be int, never None or float
            assert isinstance(duration_ms, int), f"duration_ms should be int, got {type(duration_ms)} for value {value}"
            assert duration_ms is not None, f"duration_ms should never be None for value {value}"
            assert duration_ms >= 0, f"duration_ms should be non-negative, got {duration_ms} for value {value}"
