"""Tests for AdaptiveThresholdProvider (TC-AGENT-03 + TC-FIX-01)."""

from __future__ import annotations

from dataclasses import dataclass, field
from unittest.mock import MagicMock

import pytest

from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.translation_engine.validation.decision_engine import (
    AdaptiveThresholdProvider,
    ValidationDecisionEngine,
)
from src.translation_engine.validation.post_translation_validator import ValidationDecision


def _make_validation_result(error_count: int = 0) -> ValidationResult:
    """Create a ValidationResult with the given number of ERROR-severity issues."""
    issues = [
        ValidationIssue(
            validator="DummyValidator",
            severity=ValidationSeverity.ERROR,
            message=f"error {i}",
        )
        for i in range(error_count)
    ]
    return ValidationResult(success=(error_count == 0), issues=issues)


@dataclass
class FakeOutcome:
    acceptance_rate: float


def _make_provider(
    outcomes: list[FakeOutcome] | None = None,
    enabled: bool = True,
    min_runs: int = 5,
    max_delta: int = 1,
    raises: bool = False,
) -> AdaptiveThresholdProvider:
    mock_history = MagicMock()
    if raises:
        mock_history.get_recent_outcomes.side_effect = RuntimeError("DB error")
    elif outcomes is not None:
        mock_history.get_recent_outcomes.return_value = outcomes
    else:
        mock_history.get_recent_outcomes.return_value = []

    return AdaptiveThresholdProvider(
        run_history=mock_history,
        config={"enabled": enabled, "min_history_runs": min_runs, "max_delta": max_delta},
    )


class TestHighAcceptanceTightens:
    def test_high_acceptance_tightens_by_one(self) -> None:
        """0.96 average -> reject_on_error_count = static - 1 = 2."""
        outcomes = [FakeOutcome(0.96)] * 10
        provider = _make_provider(outcomes)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 2


class TestLowAcceptanceLoosens:
    def test_low_acceptance_loosens_by_one(self) -> None:
        """0.65 average -> reject_on_error_count = static + 1 = 4."""
        outcomes = [FakeOutcome(0.65)] * 10
        provider = _make_provider(outcomes)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 4


class TestNormalAcceptance:
    def test_normal_acceptance_uses_static(self) -> None:
        """0.85 average -> no change."""
        outcomes = [FakeOutcome(0.85)] * 10
        provider = _make_provider(outcomes)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3


class TestInsufficientHistory:
    def test_insufficient_history_uses_static(self) -> None:
        """< 5 runs -> no change."""
        outcomes = [FakeOutcome(0.96)] * 3
        provider = _make_provider(outcomes, min_runs=5)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3


class TestNoneProvider:
    def test_none_provider_uses_static(self) -> None:
        """Backward compat: no provider -> zero behavior change."""
        engine = ValidationDecisionEngine(
            {"decision_rules": {"reject_on_error_count": 3}},
            adaptive_provider=None,
        )
        assert engine.reject_on_error_count == 3


class TestClamping:
    def test_threshold_clamped_min_1_max_5(self) -> None:
        # Static=1, high acceptance would try 0, should clamp to 1
        outcomes = [FakeOutcome(0.99)] * 10
        provider = _make_provider(outcomes)
        result = provider.get_thresholds("site", "de", static_reject_count=1)
        assert result["reject_on_error_count"] == 1  # min clamp

        # Static=5, low acceptance would try 6, should clamp to 5
        outcomes_low = [FakeOutcome(0.50)] * 10
        provider_low = _make_provider(outcomes_low)
        result_low = provider_low.get_thresholds("site", "de", static_reject_count=5)
        assert result_low["reject_on_error_count"] == 5  # max clamp


class TestMaxDelta:
    def test_max_delta_enforced(self) -> None:
        """Static=3, max_delta=1 -> can only reach 2 or 4."""
        # High acceptance
        outcomes_high = [FakeOutcome(0.99)] * 10
        provider = _make_provider(outcomes_high, max_delta=1)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 2

        # Low acceptance
        outcomes_low = [FakeOutcome(0.50)] * 10
        provider_low = _make_provider(outcomes_low, max_delta=1)
        result_low = provider_low.get_thresholds("site", "de", static_reject_count=3)
        assert result_low["reject_on_error_count"] == 4

    def test_max_delta_zero_means_no_change(self) -> None:
        outcomes = [FakeOutcome(0.99)] * 10
        provider = _make_provider(outcomes, max_delta=0)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3


class TestDBError:
    def test_db_error_falls_back_to_static(self) -> None:
        provider = _make_provider(raises=True)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3


class TestDisabled:
    def test_disabled_returns_static(self) -> None:
        outcomes = [FakeOutcome(0.99)] * 10
        provider = _make_provider(outcomes, enabled=False)
        result = provider.get_thresholds("site", "de", static_reject_count=3)
        assert result["reject_on_error_count"] == 3


class TestMakeDecisionUsesAdaptiveThreshold:
    """TC-FIX-01 integration: make_decision must call get_thresholds and use the result."""

    def test_make_decision_uses_adaptive_threshold(self) -> None:
        """Provider returns reject_count=5; 4 errors should ACCEPT (below 5), not REJECT."""
        # Provider loosens threshold to 5 (high miss rate scenario)
        outcomes = [FakeOutcome(0.60)] * 10  # low acceptance -> loosen by 1
        provider = _make_provider(outcomes, min_runs=5)
        # Static = 4; provider returns 5
        engine = ValidationDecisionEngine(
            {"decision_rules": {"reject_on_error_count": 4, "max_retry_attempts": 0}},
            adaptive_provider=provider,
        )
        # 4 errors: with static threshold 4 → REJECT; with adapted threshold 5 → RETRY/ACCEPT
        vr = _make_validation_result(error_count=4)
        decision = engine.make_decision(
            vr, retry_count=0, source="src", site_id="docs.aspose.net", target_lang="de"
        )
        # With effective_reject_count=5, 4 errors < 5 → does NOT hit Rule 2 REJECT
        assert decision.decision != ValidationDecision.REJECT, (
            f"Expected non-REJECT with adapted threshold=5, got {decision.decision} — "
            f"adaptive provider was not consulted"
        )

    def test_make_decision_without_kwargs_uses_static(self) -> None:
        """Backward compat: calling without site_id/target_lang uses static threshold."""
        outcomes = [FakeOutcome(0.60)] * 10
        provider = _make_provider(outcomes, min_runs=5)
        # Static = 3; provider would return 4 but we don't pass site_id/target_lang
        engine = ValidationDecisionEngine(
            {"decision_rules": {"reject_on_error_count": 3, "max_retry_attempts": 0}},
            adaptive_provider=provider,
        )
        # 3 errors with static=3 → REJECT (3 >= 3)
        vr = _make_validation_result(error_count=3)
        decision = engine.make_decision(vr, retry_count=0, source="src")
        assert decision.decision == ValidationDecision.REJECT, (
            f"Expected REJECT with static threshold=3, got {decision.decision}"
        )
        # Provider should NOT have been called (no site_id passed)
        provider._run_history.get_recent_outcomes.assert_not_called()
