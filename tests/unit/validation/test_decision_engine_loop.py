"""Tests proving the ACCEPT/RETRY/REJECT decision loop behavior.

These tests verify the core agentic behavior: the decision engine
makes iterative decisions with feedback, retries fixable errors,
and rejects when quality gates fail or budget is exhausted.
"""

import pytest

from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.translation_engine.validation.decision_engine import ValidationDecisionEngine
from src.translation_engine.validation.post_translation_validator import (
    ValidationDecision,
)

# Minimal config matching production defaults
DEFAULT_CONFIG = {
    "decision_rules": {
        "reject_on_error_count": 3,
        "max_retry_attempts": 2,
        "accept_warnings": True,
        "accept_after_max_retries": True,
        "reject_on_placeholder_error": True,
        "reject_on_code_block_error": True,
        "reject_on_link_error": True,
        "reject_on_repetition_error": True,
        "retry_on_structure_error": True,
        "retry_on_terminology_warning": True,
    }
}


def _make_result(errors=None, warnings=None, success=None):
    """Build a ValidationResult with specified issues."""
    issues = []
    for e in errors or []:
        validator_name = e.get("validator", "TestValidator")
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator=validator_name,
                message=e.get("message", "error"),
            )
        )
    for w in warnings or []:
        issues.append(
            ValidationIssue(
                severity=ValidationSeverity.WARNING,
                validator=w.get("validator", "TestValidator"),
                message=w.get("message", "warning"),
            )
        )
    if success is None:
        success = len([i for i in issues if i.severity == ValidationSeverity.ERROR]) == 0
    return ValidationResult(success=success, issues=issues)


class TestDecisionEngineLoop:
    """Tests proving iterative ACCEPT/RETRY/REJECT behavior."""

    def test_clean_translation_accepted_immediately(self):
        """A translation with no issues is ACCEPTED on first attempt."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        result = _make_result()
        decision = engine.make_decision(result, retry_count=0, source="Hello world")
        assert decision.decision == ValidationDecision.ACCEPT

    def test_fixable_error_triggers_retry_with_feedback(self):
        """A fixable error triggers RETRY on first attempt with feedback."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        result = _make_result(
            errors=[{"validator": "CompletenessValidator", "message": "heading level mismatch"}]
        )
        decision = engine.make_decision(result, retry_count=0, source="# Hello")
        assert decision.decision == ValidationDecision.RETRY
        assert decision.retry_feedback is not None
        assert len(decision.retry_feedback) > 0

    def test_retry_budget_decrements(self):
        """Each retry attempt consumes budget; second retry still allowed."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        result = _make_result(
            errors=[{"validator": "CompletenessValidator", "message": "heading error"}]
        )

        d1 = engine.make_decision(result, retry_count=0, source="# Hello")
        assert d1.decision == ValidationDecision.RETRY

        d2 = engine.make_decision(result, retry_count=1, source="# Hello")
        assert d2.decision == ValidationDecision.RETRY

    def test_exhausted_budget_accepts_best_effort(self):
        """After max retries with accept_after_max_retries=True, ACCEPT best effort."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        result = _make_result(
            errors=[{"validator": "CompletenessValidator", "message": "heading error"}]
        )

        decision = engine.make_decision(result, retry_count=2, source="# Hello")
        assert decision.decision == ValidationDecision.ACCEPT

    def test_exhausted_budget_rejects_when_configured(self):
        """After max retries with accept_after_max_retries=False, REJECT."""
        config = {
            "decision_rules": {
                **DEFAULT_CONFIG["decision_rules"],
                "accept_after_max_retries": False,
            }
        }
        engine = ValidationDecisionEngine(config)
        result = _make_result(
            errors=[{"validator": "CompletenessValidator", "message": "heading error"}]
        )

        decision = engine.make_decision(result, retry_count=2, source="# Hello")
        assert decision.decision == ValidationDecision.REJECT

    def test_critical_validator_error_rejects_immediately(self):
        """A critical validator error (PlaceholderValidator) triggers immediate REJECT."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        result = _make_result(
            errors=[{"validator": "PlaceholderValidator", "message": "missing placeholder"}]
        )

        decision = engine.make_decision(result, retry_count=0, source="Hello {{placeholder}}")
        assert decision.decision == ValidationDecision.REJECT

    def test_too_many_errors_rejects(self):
        """Exceeding reject_on_error_count triggers REJECT."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        errors = [{"validator": "CompletenessValidator", "message": f"error {i}"} for i in range(4)]
        result = _make_result(errors=errors)

        decision = engine.make_decision(result, retry_count=0, source="text")
        assert decision.decision == ValidationDecision.REJECT

    def test_warnings_only_accepted(self):
        """Warnings without errors result in ACCEPT."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)
        result = _make_result(
            warnings=[
                {"validator": "TerminologyPreservationValidator", "message": "term suggestion"}
            ]
        )

        decision = engine.make_decision(result, retry_count=0, source="Aspose.Words")
        assert decision.decision == ValidationDecision.ACCEPT

    def test_full_retry_loop_simulation(self):
        """Simulate a complete retry loop: RETRY -> RETRY -> ACCEPT (best effort)."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)

        # Attempt 0: fixable error -> RETRY
        bad_result = _make_result(
            errors=[{"validator": "CompletenessValidator", "message": "mismatch"}]
        )
        d0 = engine.make_decision(bad_result, retry_count=0, source="# Title")
        assert d0.decision == ValidationDecision.RETRY

        # Attempt 1: still has error -> RETRY
        d1 = engine.make_decision(bad_result, retry_count=1, source="# Title")
        assert d1.decision == ValidationDecision.RETRY

        # Attempt 2: budget exhausted, best effort -> ACCEPT
        d2 = engine.make_decision(bad_result, retry_count=2, source="# Title")
        assert d2.decision == ValidationDecision.ACCEPT

    def test_retry_then_clean_accepts(self):
        """First attempt retries, second attempt is clean -> ACCEPT."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)

        bad_result = _make_result(
            errors=[{"validator": "CompletenessValidator", "message": "heading mismatch"}]
        )
        d0 = engine.make_decision(bad_result, retry_count=0, source="# Title")
        assert d0.decision == ValidationDecision.RETRY

        clean_result = _make_result()
        d1 = engine.make_decision(clean_result, retry_count=1, source="# Title")
        assert d1.decision == ValidationDecision.ACCEPT

    def test_decision_result_has_reason(self):
        """Every decision includes a human-readable reason."""
        engine = ValidationDecisionEngine(DEFAULT_CONFIG)

        clean = _make_result()
        d = engine.make_decision(clean, retry_count=0, source="text")
        assert d.decision_reason is not None
        assert len(d.decision_reason) > 0
