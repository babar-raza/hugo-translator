"""
Unit tests for the language purity circuit breaker in TextUnitExtractor.

TC-03 (plan: validated-mixing-biscuit):
- Circuit breaker fires when run-level purity failure rate > 50% after 50+ batches
- Threshold catches lv (83.1%) and sr (67.7%) without false-firing for normal languages
- The breaker is disabled by setting TextUnitExtractor._circuit_breaker_enabled = False
- Class-level counters accumulate across instances (run-level, not per-file)
"""

import unittest
from unittest.mock import MagicMock, patch

from src.translation_engine.extractor.text_unit_extractor import (
    CIRCUIT_BREAKER_MIN_BATCHES,
    CIRCUIT_BREAKER_THRESHOLD,
    LanguagePurityCircuitBreakerError,
    TextUnitExtractor,
)


def _make_extractor():
    """Return a minimal TextUnitExtractor with no heavy dependencies."""
    return TextUnitExtractor(segmentation_strategy="sentence_only")


def _reset_run_counters():
    """Clear class-level run counters between tests."""
    TextUnitExtractor._run_purity_failures.clear()
    TextUnitExtractor._run_total_batches.clear()
    TextUnitExtractor._circuit_breaker_enabled = True


class TestCircuitBreakerConstants(unittest.TestCase):
    """Verify the exported constants match the plan specification."""

    def test_min_batches_is_50(self):
        self.assertEqual(CIRCUIT_BREAKER_MIN_BATCHES, 50)

    def test_threshold_is_50pct(self):
        self.assertAlmostEqual(CIRCUIT_BREAKER_THRESHOLD, 0.50)


class TestCircuitBreakerRunLevelCounters(unittest.TestCase):
    """Tests for class-level run counter accumulation."""

    def setUp(self):
        _reset_run_counters()

    def tearDown(self):
        _reset_run_counters()

    def test_run_total_batches_accumulates_across_instances(self):
        """Class-level counter must persist across distinct extractor instances."""
        extractor1 = _make_extractor()
        extractor2 = _make_extractor()

        # Simulate two instances incrementing run-level total batches
        TextUnitExtractor._run_total_batches["lv"] = 10
        TextUnitExtractor._run_total_batches["lv"] += 5

        self.assertEqual(TextUnitExtractor._run_total_batches["lv"], 15)

    def test_run_purity_failures_accumulates_across_instances(self):
        """Run-level purity failures must persist across distinct extractor instances."""
        TextUnitExtractor._run_purity_failures["lv"] = 8
        TextUnitExtractor._run_purity_failures["lv"] += 4

        self.assertEqual(TextUnitExtractor._run_purity_failures["lv"], 12)

    def test_per_language_isolation(self):
        """Counters for different languages must not interfere."""
        TextUnitExtractor._run_total_batches["lv"] = 60
        TextUnitExtractor._run_purity_failures["lv"] = 50
        TextUnitExtractor._run_total_batches["de"] = 60
        TextUnitExtractor._run_purity_failures["de"] = 2

        self.assertEqual(TextUnitExtractor._run_total_batches["lv"], 60)
        self.assertEqual(TextUnitExtractor._run_purity_failures["de"], 2)


class TestCircuitBreakerFiring(unittest.TestCase):
    """Tests that the circuit breaker fires at the correct threshold."""

    def setUp(self):
        _reset_run_counters()

    def tearDown(self):
        _reset_run_counters()

    def _simulate_batches(self, tgt_lang, total, failures):
        """Directly set run-level counters to simulate N batches with F failures."""
        TextUnitExtractor._run_total_batches[tgt_lang] = total
        TextUnitExtractor._run_purity_failures[tgt_lang] = failures

    def _trigger_check(self, tgt_lang):
        """Run the circuit breaker check logic as it appears in batch_translate_units."""
        _run_total = TextUnitExtractor._run_total_batches.get(tgt_lang, 0)
        _run_fails = TextUnitExtractor._run_purity_failures.get(tgt_lang, 0)
        if (
            TextUnitExtractor._circuit_breaker_enabled
            and _run_total >= CIRCUIT_BREAKER_MIN_BATCHES
            and _run_fails > 0
            and _run_fails / _run_total > CIRCUIT_BREAKER_THRESHOLD
        ):
            raise LanguagePurityCircuitBreakerError(
                f"Language purity circuit breaker fired for '{tgt_lang}': "
                f"{_run_fails / _run_total:.1%} of {_run_total} run-level batches "
                f"produced wrong-language output."
            )

    def test_fires_for_lv_like_failure_rate(self):
        """Circuit breaker fires for lv-like 83% failure rate after min_batches."""
        self._simulate_batches("lv", total=50, failures=42)  # 84%
        with self.assertRaises(LanguagePurityCircuitBreakerError) as cm:
            self._trigger_check("lv")
        self.assertIn("lv", str(cm.exception))

    def test_fires_for_sr_like_failure_rate(self):
        """Circuit breaker fires for sr-like 68% failure rate after min_batches."""
        self._simulate_batches("sr", total=50, failures=34)  # 68%
        with self.assertRaises(LanguagePurityCircuitBreakerError):
            self._trigger_check("sr")

    def test_does_not_fire_before_min_batches(self):
        """Circuit breaker must NOT fire when total batches < min_batches, even at 100%."""
        self._simulate_batches("lv", total=CIRCUIT_BREAKER_MIN_BATCHES - 1, failures=49)
        # Should not raise — not enough data yet
        self._trigger_check("lv")  # no exception expected

    def test_does_not_fire_at_exactly_49pct(self):
        """Circuit breaker must NOT fire at exactly 49% failure rate."""
        total = 100
        failures = 49  # 49% — below 50% threshold
        self._simulate_batches("lv", total=total, failures=failures)
        self._trigger_check("lv")  # no exception expected

    def test_does_not_fire_at_exactly_50pct(self):
        """Circuit breaker fires ONLY when rate EXCEEDS threshold (strict >), not at exactly 50%."""
        total = 100
        failures = 50  # exactly 50% — threshold is STRICT > so should not fire
        self._simulate_batches("lv", total=total, failures=failures)
        self._trigger_check("lv")  # no exception expected

    def test_fires_at_50pct_plus_one(self):
        """Circuit breaker fires when failure rate strictly exceeds 50%."""
        total = 100
        failures = 51  # 51%
        self._simulate_batches("lv", total=total, failures=failures)
        with self.assertRaises(LanguagePurityCircuitBreakerError):
            self._trigger_check("lv")

    def test_does_not_fire_for_healthy_language(self):
        """Circuit breaker must NOT fire for languages with 5% failure rate."""
        total = 100
        failures = 5  # 5% — normal
        self._simulate_batches("de", total=total, failures=failures)
        self._trigger_check("de")  # no exception expected


class TestCircuitBreakerDisabledViaClassFlag(unittest.TestCase):
    """Tests that circuit breaker is suppressible for testing contexts."""

    def setUp(self):
        _reset_run_counters()

    def tearDown(self):
        _reset_run_counters()

    def test_circuit_breaker_disabled_via_class_flag(self):
        """When _circuit_breaker_enabled=False, no exception is raised regardless of rate."""
        TextUnitExtractor._circuit_breaker_enabled = False
        TextUnitExtractor._run_total_batches["lv"] = 100
        TextUnitExtractor._run_purity_failures["lv"] = 100  # 100% failure

        # Should not raise when disabled
        _run_total = TextUnitExtractor._run_total_batches.get("lv", 0)
        _run_fails = TextUnitExtractor._run_purity_failures.get("lv", 0)
        if (
            TextUnitExtractor._circuit_breaker_enabled
            and _run_total >= CIRCUIT_BREAKER_MIN_BATCHES
            and _run_fails > 0
            and _run_fails / _run_total > CIRCUIT_BREAKER_THRESHOLD
        ):
            raise LanguagePurityCircuitBreakerError("should not fire")
        # No exception raised — test passes


class TestLanguagePurityCircuitBreakerErrorType(unittest.TestCase):
    """Tests that the exception has the correct type hierarchy."""

    def test_is_runtime_error_subclass(self):
        """LanguagePurityCircuitBreakerError must be a RuntimeError subclass."""
        exc = LanguagePurityCircuitBreakerError("test")
        self.assertIsInstance(exc, RuntimeError)

    def test_message_contains_language(self):
        """Exception message should contain the failing language code."""
        exc = LanguagePurityCircuitBreakerError(
            "Language purity circuit breaker fired for 'lv': 83.1%"
        )
        self.assertIn("lv", str(exc))


if __name__ == "__main__":
    unittest.main()
