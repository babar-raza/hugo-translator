"""
TI-06: Reproduction tests for telemetry 422 root cause.

These tests demonstrate minimal cases where duration_seconds becomes None,
causing HTTP 422 errors before PR-04 defensive fix.

**Purpose**: Provide executable proof that _safe_duration_ms() correctly
handles all scenarios where duration_seconds could be None or invalid.

**Root Cause Reference**: See docs/analysis/telemetry_422_root_cause.md
"""

import pytest
from src.translation_engine.models import TranslationStats
from src.observability.telemetry_integration import _safe_duration_ms


class TestDurationNoneReproduction:
    """Reproduction tests demonstrating how None duration_seconds can occur."""

    def test_reproduce_none_duration_explicit_assignment(self):
        """
        Reproduce None duration via explicit assignment.

        This is the most likely way None occurred in production:
        error handling code explicitly set duration_seconds = None.

        **Before PR-04**: Would calculate int(None * 1000) → TypeError or null → 422
        **After PR-04**: Defensive handling returns (0, True)
        """
        stats = TranslationStats(total_segments=100, tm_hits=50)
        assert stats.duration_seconds == 0.0  # Default is 0.0

        # Simulate old error handling code
        stats.duration_seconds = None

        # After PR-04: Defensive handling
        duration_ms, used_fallback = _safe_duration_ms(stats, context="test_explicit_none")

        assert duration_ms == 0, "Expected fallback to 0 when duration_seconds is None"
        assert used_fallback is True, "Expected fallback flag to be True"

    def test_reproduce_none_stats_object(self):
        """
        Reproduce None stats object scenario (extreme edge case).

        This can happen if:
        - Error during TranslationStats creation
        - Exception in try-except returns None instead of stats
        - Defensive code explicitly passes None

        **Before PR-04**: Would crash with AttributeError or send null → 422
        **After PR-04**: Returns (0, True)
        """
        stats = None

        duration_ms, used_fallback = _safe_duration_ms(stats, context="test_none_object")

        assert duration_ms == 0, "Expected fallback to 0 when stats is None"
        assert used_fallback is True, "Expected fallback flag to be True"

    def test_reproduce_invalid_type_duration(self):
        """
        Reproduce invalid type for duration_seconds.

        This can happen if:
        - Corrupted data from cache/database
        - Serialization/deserialization bug
        - Manual testing with wrong type

        **Before PR-04**: Would crash with TypeError or send invalid value → 422
        **After PR-04**: Catches exception and returns (0, True)
        """
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = "invalid_string"  # Type violation

        duration_ms, used_fallback = _safe_duration_ms(stats, context="test_invalid_type")

        assert duration_ms == 0, "Expected fallback to 0 when duration_seconds is invalid type"
        assert used_fallback is True, "Expected fallback flag to be True"

    def test_reproduce_negative_duration(self):
        """
        Reproduce negative duration_seconds.

        This shouldn't happen in normal operation but could occur due to:
        - Time synchronization issues
        - Manual testing
        - Bug in duration calculation

        **Expected**: Negative values are converted to negative milliseconds
        (This is NOT a fallback scenario, it's handled correctly)
        """
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = -1.5

        duration_ms, used_fallback = _safe_duration_ms(stats, context="test_negative")

        assert duration_ms == -1500, "Expected negative milliseconds for negative seconds"
        assert used_fallback is False, "Negative is valid, not a fallback"

    def test_legitimate_zero_not_flagged(self):
        """
        Verify legitimate 0.0 duration is NOT treated as fallback.

        Very fast translations (cache hits, empty files) can have 0.0 duration.
        This is valid and should NOT trigger fallback metrics.

        **Expected**: Returns (0, False) - valid zero, not a fallback
        """
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = 0.0

        duration_ms, used_fallback = _safe_duration_ms(stats, context="test_legitimate_zero")

        assert duration_ms == 0, "Expected 0 milliseconds for 0.0 seconds"
        assert used_fallback is False, "Legitimate zero should NOT be flagged as fallback"

    @pytest.mark.skip(reason="Cannot reproduce in current code - documents legacy hypothesis")
    def test_hypothetical_early_return_without_finally(self):
        """
        Hypothetical scenario: Early return before finally block sets duration.

        **Legacy Hypothesis**: In old code, if translate_file() returned early
        (exception, validation failure, etc.) before the finally block that
        sets duration_seconds, the TranslationStats would have None duration.

        **Current Code**: engine.py has finally block (lines 575-578) that ALWAYS
        sets result.stats.duration_seconds before returning, so this scenario
        cannot be reproduced.

        **This test documents our hypothesis about legacy code behavior.**

        Evidence supporting this hypothesis:
        - PR-04 was created to fix 422 errors
        - 422 errors are caused by null duration_ms
        - Lazy import was added in TI-01 for defensive handling
        - Root cause analysis found 3 code paths that could create TranslationStats
        """
        pass
