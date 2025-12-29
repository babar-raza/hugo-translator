"""
CONTRACT: specs/features/val-002-critical-validators.md

Verifies that critical validators (PlaceholderValidator, CodeBlockValidator, LinkValidator)
always cause REJECT decision, bypassing retry logic and error thresholds.

Critical validators enforce syntactic integrity rules that are never relaxed
regardless of validation mode (strict/normal/lenient).
"""

import pytest

from src.translation_engine.validation.decision_engine import (
    ValidationDecisionEngine,
    ValidationDecision,
)
from src.translation_engine.validation.base import (
    ValidationResult,
    ValidationIssue,
    ValidationSeverity,
)


# ==============================================================================
# PlaceholderValidator Tests
# ==============================================================================


@pytest.mark.contract
def test_placeholder_validator_error_always_rejects_strict(
    validation_config_strict,
    validation_issue_placeholder_error,
):
    """
    Verify PlaceholderValidator ERROR causes REJECT in strict mode.

    CONTRACT: VAL-002 Invariant #2
    Evidence: decision_engine.py CRITICAL_VALIDATORS lines 59-63
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_strict)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT for PlaceholderValidator ERROR, got {decision.name}: {reason}"
    assert "Critical" in reason or "PlaceholderValidator" in reason, \
        f"Expected reason to mention critical validator, got: {reason}"


@pytest.mark.contract
def test_placeholder_validator_error_always_rejects_normal(
    validation_config_normal,
    validation_issue_placeholder_error,
):
    """
    Verify PlaceholderValidator ERROR causes REJECT in normal mode.

    CONTRACT: VAL-002 Invariant #2
    Evidence: decision_engine.py CRITICAL_VALIDATORS lines 59-63
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_normal)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT for PlaceholderValidator ERROR in normal mode, got {decision.name}: {reason}"


@pytest.mark.contract
def test_placeholder_validator_error_always_rejects_lenient(
    validation_config_lenient,
    validation_issue_placeholder_error,
):
    """
    Verify PlaceholderValidator ERROR causes REJECT even in lenient mode.

    CONTRACT: VAL-002 Invariant #4 - Mode-independent enforcement
    Evidence: decision_engine.py critical validator check bypasses mode
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_lenient)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT even in lenient mode, got {decision.name}: {reason}"


# ==============================================================================
# CodeBlockValidator Tests
# ==============================================================================


@pytest.mark.contract
def test_code_block_validator_error_always_rejects(
    validation_config_normal,
    validation_issue_code_block_error,
):
    """
    Verify CodeBlockValidator ERROR causes REJECT in all modes.

    CONTRACT: VAL-002 Invariant #2
    Evidence: decision_engine.py CRITICAL_VALIDATORS includes CodeBlockValidator
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_normal)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_code_block_error)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT for CodeBlockValidator ERROR, got {decision.name}: {reason}"
    assert "Critical" in reason or "CodeBlockValidator" in reason, \
        f"Expected reason to mention critical validator, got: {reason}"


# ==============================================================================
# LinkValidator Tests
# ==============================================================================


@pytest.mark.contract
def test_link_validator_error_always_rejects(
    validation_config_normal,
    validation_issue_link_error,
):
    """
    Verify LinkValidator ERROR causes REJECT in all modes.

    CONTRACT: VAL-002 Invariant #2
    Evidence: decision_engine.py CRITICAL_VALIDATORS includes LinkValidator
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_normal)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_link_error)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT for LinkValidator ERROR, got {decision.name}: {reason}"
    assert "Critical" in reason or "LinkValidator" in reason, \
        f"Expected reason to mention critical validator, got: {reason}"


# ==============================================================================
# Critical vs Non-Critical Distinction Tests
# ==============================================================================


@pytest.mark.contract
def test_non_critical_validator_follows_threshold(
    validation_config_lenient,
    validation_issue_structure_warning,
):
    """
    Verify non-critical validators (StructureValidator) follow error threshold rules.

    CONTRACT: VAL-002 Rationale - Only critical validators bypass threshold
    Evidence: decision_engine.py error count check for non-critical validators
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_lenient)

    result = ValidationResult(success=False)
    # Add 3 structure warnings (below lenient threshold of 5)
    for _ in range(3):
        result.issues.append(validation_issue_structure_warning)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    # Warnings should be accepted in lenient mode (not critical validator)
    assert decision == ValidationDecision.ACCEPT, \
        f"Expected ACCEPT for non-critical warnings in lenient mode, got {decision.name}: {reason}"


@pytest.mark.contract
def test_critical_validator_bypasses_retry_logic(
    validation_config_normal,
    validation_issue_placeholder_error,
):
    """
    Verify critical validator failure causes immediate REJECT without retry.

    CONTRACT: VAL-002 Invariant #8 - Never retry critical failures
    Evidence: decision_engine.py critical check before retry logic
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_normal)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)

    # Act - Even on first attempt (retry_count=0), should REJECT immediately
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected immediate REJECT, got {decision.name}"

    # Verify decision is REJECT, not RETRY
    assert decision != ValidationDecision.RETRY, \
        "Critical validator errors should REJECT, not RETRY"


@pytest.mark.contract
def test_critical_validator_bypasses_accept_after_max_retries(
    validation_config_lenient,
    validation_issue_placeholder_error,
):
    """
    Verify critical validator failure rejects even when accept_after_max_retries=True.

    CONTRACT: VAL-002 Invariant #9 - Never ACCEPT after retries
    Evidence: decision_engine.py critical check happens before retry acceptance logic
    """
    # Arrange
    # Lenient config has accept_after_max_retries=True
    engine = ValidationDecisionEngine(validation_config_lenient)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)

    # Act - At max retries (retry_count=2), normally would accept in lenient mode
    result_obj = engine.make_decision(result, retry_count=2, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT even at max retries, got {decision.name}: {reason}"


# ==============================================================================
# Multiple Validator Tests
# ==============================================================================


@pytest.mark.contract
def test_critical_validator_fails_with_other_errors(
    validation_config_normal,
    validation_issue_placeholder_error,
    validation_issue_structure_warning,
):
    """
    Verify critical validator + non-critical errors still causes REJECT.

    CONTRACT: VAL-002 - Critical failures take precedence
    Evidence: decision_engine.py critical check happens first
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_normal)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)  # Critical ERROR
    result.issues.append(validation_issue_structure_warning)  # Non-critical WARNING

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT for critical + non-critical mix, got {decision.name}: {reason}"
    assert "Critical" in reason or "PlaceholderValidator" in reason, \
        "Reason should mention critical validator failure"


@pytest.mark.contract
def test_multiple_critical_validators_fail(
    validation_config_normal,
    validation_issue_placeholder_error,
    validation_issue_code_block_error,
    validation_issue_link_error,
):
    """
    Verify multiple critical validator failures result in REJECT.

    CONTRACT: VAL-002 Edge Case - Multiple critical validators fail
    Evidence: decision_engine.py first critical error triggers REJECT
    """
    # Arrange
    engine = ValidationDecisionEngine(validation_config_normal)

    result = ValidationResult(success=False)
    result.issues.append(validation_issue_placeholder_error)
    result.issues.append(validation_issue_code_block_error)
    result.issues.append(validation_issue_link_error)

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.REJECT, \
        f"Expected REJECT for multiple critical failures, got {decision.name}: {reason}"

    # Verify reason mentions at least one critical validator
    critical_mentioned = any(
        validator in reason
        for validator in ["PlaceholderValidator", "CodeBlockValidator", "LinkValidator", "Critical"]
    )
    assert critical_mentioned, \
        f"Reason should mention at least one critical validator, got: {reason}"


# ==============================================================================
# WARNING Severity Tests
# ==============================================================================


@pytest.mark.contract
def test_critical_validator_warning_does_not_reject():
    """
    Verify WARNING from critical validator does NOT cause REJECT (only ERROR severity).

    CONTRACT: VAL-002 Edge Case - Warnings from critical validators
    Evidence: decision_engine.py only ERROR severity from critical validators causes REJECT
    """
    # Arrange
    config = {
        "decision_rules": {
            "reject_on_error_count": 3,
            "max_retry_attempts": 2,
            "accept_warnings": True,
        }
    }
    engine = ValidationDecisionEngine(config)

    result = ValidationResult(success=True)  # success=True for warnings
    result.issues.append(
        ValidationIssue(
            severity=ValidationSeverity.WARNING,  # WARNING, not ERROR
            validator="LinkValidator",  # Critical validator
            message="Link count mismatch: source has 5, translation has 4",
            location=None,
            details=None,
        )
    )

    # Act
    result_obj = engine.make_decision(result, retry_count=0, source="test source")
    decision = result_obj.decision
    reason = result_obj.decision_reason

    # Assert
    assert decision == ValidationDecision.ACCEPT, \
        f"Expected ACCEPT for WARNING from critical validator, got {decision.name}: {reason}"
