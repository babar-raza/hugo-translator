"""Tests for the auto-remediation engine (TC-PRACT-03)."""

from __future__ import annotations

import tempfile
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.operations.remediation import (
    RemediationAction,
    RemediationEngine,
    RemediationRule,
    load_rules_from_yaml,
)


def _make_rule(
    metric: str = "acceptance_rate",
    threshold: float = 0.70,
    comparison: str = "below",
    action: RemediationAction = RemediationAction.LOG_ALERT,
    cooldown_minutes: int = 60,
    description: str = "Test rule",
) -> RemediationRule:
    return RemediationRule(
        metric=metric,
        threshold=threshold,
        comparison=comparison,
        action=action,
        cooldown_minutes=cooldown_minutes,
        description=description,
    )


class TestRuleTriggering:
    def test_rule_triggers_on_breach(self) -> None:
        rule = _make_rule(threshold=0.70, comparison="below")
        engine = RemediationEngine([rule], dry_run=False)
        events = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events) == 1
        assert events[0].metric_value == 0.50
        assert events[0].action_taken == RemediationAction.LOG_ALERT
        assert events[0].dry_run is False

    def test_rule_silent_when_healthy(self) -> None:
        rule = _make_rule(threshold=0.70, comparison="below")
        engine = RemediationEngine([rule], dry_run=False)
        events = engine.check_and_act({"acceptance_rate": 0.85})
        assert len(events) == 0

    def test_rule_triggers_above_comparison(self) -> None:
        rule = _make_rule(
            metric="worker_failure_count",
            threshold=3,
            comparison="above",
        )
        engine = RemediationEngine([rule], dry_run=False)
        events = engine.check_and_act({"worker_failure_count": 5})
        assert len(events) == 1

    def test_rule_silent_when_at_threshold(self) -> None:
        rule = _make_rule(threshold=0.70, comparison="below")
        engine = RemediationEngine([rule], dry_run=False)
        events = engine.check_and_act({"acceptance_rate": 0.70})
        assert len(events) == 0

    def test_missing_metric_ignored(self) -> None:
        rule = _make_rule(metric="acceptance_rate")
        engine = RemediationEngine([rule], dry_run=False)
        events = engine.check_and_act({"other_metric": 0.50})
        assert len(events) == 0


class TestCooldown:
    def test_cooldown_prevents_repeated_action(self) -> None:
        rule = _make_rule(cooldown_minutes=60)
        engine = RemediationEngine([rule], dry_run=False)

        events1 = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events1) == 1

        events2 = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events2) == 0

    def test_cooldown_expires_allows_action(self) -> None:
        rule = _make_rule(cooldown_minutes=1)
        engine = RemediationEngine([rule], dry_run=False)

        events1 = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events1) == 1

        # Simulate cooldown expiry by patching time
        with patch("src.operations.remediation.time.time", return_value=time.time() + 120):
            events2 = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events2) == 1


class TestDryRun:
    def test_dry_run_default_true(self) -> None:
        rule = _make_rule()
        engine = RemediationEngine([rule])  # no dry_run arg
        events = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events) == 1
        assert events[0].dry_run is True
        assert events[0].outcome == "dry_run"

    def test_dry_run_explicit_false(self) -> None:
        rule = _make_rule()
        engine = RemediationEngine([rule], dry_run=False)
        events = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events) == 1
        assert events[0].dry_run is False
        assert events[0].outcome == "logged"


class TestMultipleRules:
    def test_multiple_rules_independent(self) -> None:
        rule_a = _make_rule(metric="acceptance_rate", threshold=0.70, comparison="below")
        rule_b = _make_rule(
            metric="worker_failure_count",
            threshold=3,
            comparison="above",
            description="Failures rule",
        )
        engine = RemediationEngine([rule_a, rule_b], dry_run=False)
        events = engine.check_and_act(
            {
                "acceptance_rate": 0.50,
                "worker_failure_count": 5,
            }
        )
        assert len(events) == 2

    def test_only_breached_rules_fire(self) -> None:
        rule_a = _make_rule(metric="acceptance_rate", threshold=0.70, comparison="below")
        rule_b = _make_rule(
            metric="worker_failure_count",
            threshold=3,
            comparison="above",
        )
        engine = RemediationEngine([rule_a, rule_b], dry_run=False)
        events = engine.check_and_act(
            {
                "acceptance_rate": 0.90,  # healthy
                "worker_failure_count": 5,  # breached
            }
        )
        assert len(events) == 1
        assert events[0].rule.metric == "worker_failure_count"


class TestEventHistory:
    def test_event_history_recorded(self) -> None:
        rule = _make_rule(cooldown_minutes=0)
        engine = RemediationEngine([rule], dry_run=False)

        # Override cooldown to allow multiple firings
        with patch.object(engine, "_is_on_cooldown", return_value=False):
            engine.check_and_act({"acceptance_rate": 0.50})
            engine.check_and_act({"acceptance_rate": 0.40})

        history = engine.get_event_history()
        assert len(history) == 2
        assert history[0].metric_value == 0.50
        assert history[1].metric_value == 0.40

    def test_event_history_limit(self) -> None:
        rule = _make_rule()
        engine = RemediationEngine([rule], dry_run=True)

        with patch.object(engine, "_is_on_cooldown", return_value=False):
            for _ in range(10):
                engine.check_and_act({"acceptance_rate": 0.50})

        history = engine.get_event_history(limit=3)
        assert len(history) == 3


class TestUnimplementedActions:
    def test_restart_workers_raises(self) -> None:
        rule = _make_rule(action=RemediationAction.RESTART_WORKERS)
        engine = RemediationEngine([rule], dry_run=False)
        with pytest.raises(NotImplementedError, match="not implemented in V1"):
            engine.check_and_act({"acceptance_rate": 0.50})

    def test_reduce_batch_size_raises(self) -> None:
        rule = _make_rule(action=RemediationAction.REDUCE_BATCH_SIZE)
        engine = RemediationEngine([rule], dry_run=False)
        with pytest.raises(NotImplementedError, match="not implemented in V1"):
            engine.check_and_act({"acceptance_rate": 0.50})

    def test_unimplemented_in_dry_run_does_not_raise(self) -> None:
        rule = _make_rule(action=RemediationAction.RESTART_WORKERS)
        engine = RemediationEngine([rule], dry_run=True)
        events = engine.check_and_act({"acceptance_rate": 0.50})
        assert len(events) == 1
        assert events[0].dry_run is True


class TestYamlLoading:
    def test_load_rules_from_yaml(self, tmp_path: Path) -> None:
        yaml_content = """
dry_run: true
rules:
  - metric: acceptance_rate
    threshold: 0.70
    comparison: below
    action: log_alert
    cooldown_minutes: 60
    description: "Test rule"
"""
        config_file = tmp_path / "rules.yaml"
        config_file.write_text(yaml_content, encoding="utf-8")

        rules, dry_run = load_rules_from_yaml(config_file)
        assert dry_run is True
        assert len(rules) == 1
        assert rules[0].metric == "acceptance_rate"
        assert rules[0].threshold == 0.70
        assert rules[0].action == RemediationAction.LOG_ALERT

    def test_load_production_config(self) -> None:
        config_path = Path(__file__).resolve().parents[3] / "config" / "remediation_rules.yaml"
        if config_path.exists():
            rules, dry_run = load_rules_from_yaml(config_path)
            assert dry_run is True  # production config must default to dry_run
            assert len(rules) >= 2
