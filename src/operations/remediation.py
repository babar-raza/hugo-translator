"""Auto-remediation engine for SLO breach response.

V1: dry-run only, LOG_ALERT action only. No live actions until operator opts in.
"""

from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from enum import Enum
from pathlib import Path
from typing import Any

import yaml

logger = logging.getLogger(__name__)


class RemediationAction(Enum):
    """Available remediation actions.

    V1: Only LOG_ALERT is implemented. Others raise NotImplementedError.
    """

    LOG_ALERT = "log_alert"
    RESTART_WORKERS = "restart_workers"  # Future: not implemented in V1
    REDUCE_BATCH_SIZE = "reduce_batch_size"  # Future: not implemented in V1


@dataclass(frozen=True)
class RemediationRule:
    metric: str
    threshold: float
    comparison: str  # "above" or "below"
    action: RemediationAction
    cooldown_minutes: int
    description: str


@dataclass
class RemediationEvent:
    rule: RemediationRule
    metric_value: float
    action_taken: RemediationAction
    timestamp: float
    outcome: str
    dry_run: bool


class RemediationEngine:
    """Evaluates metrics against rules and takes remediation actions.

    Default is dry_run=True — all events are logged but no action is taken.
    V1 only supports LOG_ALERT. RESTART_WORKERS and REDUCE_BATCH_SIZE raise
    NotImplementedError.
    """

    def __init__(self, rules: list[RemediationRule], dry_run: bool = True) -> None:
        self._rules = rules
        self._dry_run = dry_run
        self._cooldowns: dict[str, float] = {}  # rule key -> last action timestamp
        self._event_history: list[RemediationEvent] = []

    def check_and_act(self, metrics: dict[str, float]) -> list[RemediationEvent]:
        """Evaluate all rules against provided metrics. Returns list of events."""
        events: list[RemediationEvent] = []
        for rule in self._rules:
            if rule.metric not in metrics:
                continue
            value = metrics[rule.metric]
            if not self._is_breached(rule, value):
                continue
            if self._is_on_cooldown(rule):
                logger.debug("Rule '%s' on cooldown, skipping", rule.description)
                continue
            event = self._execute_action(rule, value)
            events.append(event)
            self._event_history.append(event)
        return events

    def get_event_history(self, limit: int = 50) -> list[RemediationEvent]:
        """Return recent remediation events."""
        return self._event_history[-limit:]

    def _is_breached(self, rule: RemediationRule, value: float) -> bool:
        if rule.comparison == "below":
            return value < rule.threshold
        elif rule.comparison == "above":
            return value > rule.threshold
        return False

    def _is_on_cooldown(self, rule: RemediationRule) -> bool:
        key = f"{rule.metric}:{rule.action.value}"
        last_action = self._cooldowns.get(key)
        if last_action is None:
            return False
        elapsed_minutes = (time.time() - last_action) / 60.0
        return elapsed_minutes < rule.cooldown_minutes

    def _execute_action(self, rule: RemediationRule, value: float) -> RemediationEvent:
        now = time.time()
        key = f"{rule.metric}:{rule.action.value}"

        if self._dry_run:
            logger.info(
                "[DRY-RUN] Would execute %s for '%s' (value=%.3f, threshold=%.3f)",
                rule.action.value,
                rule.description,
                value,
                rule.threshold,
            )
            event = RemediationEvent(
                rule=rule,
                metric_value=value,
                action_taken=rule.action,
                timestamp=now,
                outcome="dry_run",
                dry_run=True,
            )
            self._cooldowns[key] = now
            return event

        # Live execution
        if rule.action == RemediationAction.LOG_ALERT:
            logger.warning(
                "[REMEDIATION] %s: %s (value=%.3f, threshold=%.3f)",
                rule.action.value,
                rule.description,
                value,
                rule.threshold,
            )
            outcome = "logged"
        elif rule.action in (
            RemediationAction.RESTART_WORKERS,
            RemediationAction.REDUCE_BATCH_SIZE,
        ):
            raise NotImplementedError(
                f"Action {rule.action.value} is not implemented in V1. Only LOG_ALERT is supported."
            )
        else:
            outcome = "unknown_action"

        self._cooldowns[key] = now
        return RemediationEvent(
            rule=rule,
            metric_value=value,
            action_taken=rule.action,
            timestamp=now,
            outcome=outcome,
            dry_run=False,
        )


def load_rules_from_yaml(path: str | Path) -> tuple[list[RemediationRule], bool]:
    """Load remediation rules from a YAML config file.

    Returns (rules, dry_run) tuple.
    """
    with open(path, encoding="utf-8") as f:
        data: dict[str, Any] = yaml.safe_load(f)

    dry_run = data.get("dry_run", True)
    rules: list[RemediationRule] = []
    for entry in data.get("rules", []):
        rules.append(
            RemediationRule(
                metric=entry["metric"],
                threshold=float(entry["threshold"]),
                comparison=entry["comparison"],
                action=RemediationAction(entry["action"]),
                cooldown_minutes=int(entry["cooldown_minutes"]),
                description=entry["description"],
            )
        )
    return rules, dry_run
