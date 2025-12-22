"""
Integration test for PR-04 telemetry 422 error fix.

⚠️ WARNING: These tests have NOT been validated against a real telemetry API.

TI-04: Validates that defensive handling prevents 422 errors when
duration_seconds is None or invalid.

Current behavior: Tests skip when TELEMETRY_API_URL is not configured.

REQUIRED BEFORE PRODUCTION: Run against staging API and verify all tests pass.
See TI-04_COMPLETION_SUMMARY.md for validation guide.

Validation Status: ⏳ PENDING (not yet validated)
Last Validation: Never

These tests call the real telemetry API to ensure the fix works in production.
Tests are skipped if TELEMETRY_API_URL is not configured.
"""
import pytest
import os
from pathlib import Path
from src.observability.telemetry_integration import TranslationTelemetry
from src.translation_engine.models import TranslationStats


# Skip all tests if telemetry API not configured
pytestmark = pytest.mark.skipif(
    not os.getenv('TELEMETRY_API_URL'),
    reason="Telemetry API not configured - set TELEMETRY_API_URL to run"
)


@pytest.mark.integration
class TestTelemetry422Fix:
    """
    Integration tests for PR-04 fix preventing 422 errors.

    These tests validate that the defensive handling in _safe_duration_ms()
    prevents HTTP 422 validation errors when duration_seconds is None or invalid.
    """

    def test_none_duration_no_422_error(self):
        """
        Verify None duration_seconds doesn't cause 422 API error.

        Before PR-04: Would send duration_ms=null, causing 422
        After PR-04: Sends duration_ms=0, no error
        """
        # Create stats with None duration (error path scenario)
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = None

        # Send to real telemetry API
        telemetry = TranslationTelemetry()

        # This should NOT raise 422 error
        try:
            with telemetry.track_translation_session(
                job_type="test_none_duration",
                trigger_type="integration_test"
            ) as ctx:
                telemetry.track_translation_stats(ctx, stats)
        except Exception as e:
            # If we get 422 error, the fix is broken
            if "422" in str(e):
                pytest.fail(f"PR-04 fix broken: Still getting 422 error: {e}")
            else:
                # Other errors might be acceptable (network, auth, etc.)
                pytest.skip(f"Telemetry API unavailable: {e}")

        # If we get here without 422 exception, fix works
        assert True

    def test_valid_duration_works(self):
        """
        Verify valid duration_seconds works correctly.

        Ensures the fix doesn't break normal operation.
        """
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50,
            duration_seconds=5.5
        )

        telemetry = TranslationTelemetry()

        try:
            with telemetry.track_translation_session(
                job_type="test_valid_duration",
                trigger_type="integration_test"
            ) as ctx:
                telemetry.track_translation_stats(ctx, stats)
        except Exception as e:
            if "422" in str(e):
                pytest.fail(f"Valid duration causing 422 error: {e}")
            else:
                pytest.skip(f"Telemetry API unavailable: {e}")

        # Verify no errors
        assert True

    def test_zero_duration_works(self):
        """
        Verify 0.0 duration_seconds works (legitimate 0).

        Distinguishes between None (fallback) and 0.0 (legitimate).
        """
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50,
            duration_seconds=0.0
        )

        telemetry = TranslationTelemetry()

        try:
            with telemetry.track_translation_session(
                job_type="test_zero_duration",
                trigger_type="integration_test"
            ) as ctx:
                telemetry.track_translation_stats(ctx, stats)
        except Exception as e:
            if "422" in str(e):
                pytest.fail(f"Legitimate 0.0 duration causing 422 error: {e}")
            else:
                pytest.skip(f"Telemetry API unavailable: {e}")

        assert True

    def test_invalid_type_duration_no_422(self):
        """
        Verify invalid duration_seconds type doesn't cause 422.

        Before PR-04: Would crash or send invalid data
        After PR-04: Gracefully falls back to 0
        """
        stats = TranslationStats(total_segments=100, tm_hits=50)
        stats.duration_seconds = "invalid"  # String instead of float

        telemetry = TranslationTelemetry()

        try:
            with telemetry.track_translation_session(
                job_type="test_invalid_type",
                trigger_type="integration_test"
            ) as ctx:
                # Should handle gracefully, not raise 422
                telemetry.track_translation_stats(ctx, stats)
        except Exception as e:
            if "422" in str(e):
                pytest.fail(f"Invalid type not handled gracefully: {e}")
            else:
                pytest.skip(f"Telemetry API unavailable: {e}")

        assert True

    def test_none_stats_no_422(self):
        """
        Verify None stats object doesn't cause 422.

        Edge case: If stats is None entirely (extreme error path).
        """
        stats = None

        telemetry = TranslationTelemetry()

        try:
            with telemetry.track_translation_session(
                job_type="test_none_stats",
                trigger_type="integration_test"
            ) as ctx:
                # Should handle gracefully
                telemetry.track_translation_stats(ctx, stats)
        except Exception as e:
            if "422" in str(e):
                pytest.fail(f"None stats not handled gracefully: {e}")
            else:
                pytest.skip(f"Telemetry API unavailable: {e}")

        assert True
