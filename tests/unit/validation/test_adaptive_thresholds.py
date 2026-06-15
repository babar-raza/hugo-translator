"""Tests for TC-AGT-03: Adaptive threshold provider behavior and safety clamps."""

from dataclasses import dataclass
from unittest.mock import MagicMock

import pytest

from src.translation_engine.validation.decision_engine import AdaptiveThresholdProvider


@dataclass
class FakeOutcome:
    """Minimal outcome for testing."""

    acceptance_rate: float


class FakeRunHistory:
    """Fake run history that returns controlled outcomes."""

    def __init__(self, outcomes: list[FakeOutcome]):
        self._outcomes = outcomes

    def get_recent_outcomes(self, site_id: str, target_lang: str, limit: int = 20):
        return self._outcomes


class TestAdaptiveThresholdClamps:
    """Test that adaptive thresholds stay within safe bounds."""

    def test_disabled_returns_static(self):
        """When disabled, static threshold is returned unchanged."""
        provider = AdaptiveThresholdProvider(
            run_history=None,
            config={"enabled": False},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3

    def test_no_history_returns_static(self):
        """When no run history, static threshold is returned."""
        provider = AdaptiveThresholdProvider(
            run_history=None,
            config={"enabled": True},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3

    def test_insufficient_runs_returns_static(self):
        """When fewer than min_history_runs, static threshold is returned."""
        history = FakeRunHistory([FakeOutcome(0.99)] * 3)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 10},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3

    def test_high_acceptance_tightens_threshold(self):
        """Acceptance rate > 0.95 reduces threshold by 1."""
        history = FakeRunHistory([FakeOutcome(0.99)] * 10)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 5, "max_delta": 1},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 2

    def test_low_acceptance_loosens_threshold(self):
        """Acceptance rate < 0.70 increases threshold by 1."""
        history = FakeRunHistory([FakeOutcome(0.50)] * 10)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 5, "max_delta": 1},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 4

    def test_moderate_acceptance_keeps_static(self):
        """Acceptance rate 0.70-0.95 keeps threshold unchanged."""
        history = FakeRunHistory([FakeOutcome(0.85)] * 10)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 5, "max_delta": 1},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3

    def test_hard_clamp_lower_bound(self):
        """Threshold cannot go below 1."""
        history = FakeRunHistory([FakeOutcome(0.99)] * 10)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 5, "max_delta": 1},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=1)
        assert result["reject_on_error_count"] >= 1

    def test_hard_clamp_upper_bound(self):
        """Threshold cannot go above 5."""
        history = FakeRunHistory([FakeOutcome(0.10)] * 10)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 5, "max_delta": 1},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=5)
        assert result["reject_on_error_count"] <= 5

    def test_max_delta_enforced(self):
        """Adjustment never exceeds max_delta from static value."""
        history = FakeRunHistory([FakeOutcome(0.99)] * 10)
        provider = AdaptiveThresholdProvider(
            run_history=history,
            config={"enabled": True, "min_history_runs": 5, "max_delta": 1},
        )
        static = 3
        result = provider.get_thresholds("test.site", "de", static_reject_count=static)
        adjusted = result["reject_on_error_count"]
        assert abs(adjusted - static) <= 1

    def test_exception_in_history_returns_static(self):
        """Exception in run history returns static threshold."""
        bad_history = MagicMock()
        bad_history.get_recent_outcomes.side_effect = RuntimeError("DB error")
        provider = AdaptiveThresholdProvider(
            run_history=bad_history,
            config={"enabled": True, "min_history_runs": 5},
        )
        result = provider.get_thresholds("test.site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3
