"""
Manual validation script to demonstrate the ValidationDecisionEngine in action.
This script shows examples of all decision paths and feedback generation.
"""
import sys
sys.path.insert(0, r'C:\Users\prora\AppData\Roaming\Python\Python313\site-packages')

from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.translation_engine.validation.decision_engine import ValidationDecisionEngine
from src.translation_engine.validation.post_translation_validator import ValidationDecision


def print_decision(name: str, decision_result):
    """Print formatted decision result."""
    print(f"\n{'='*70}")
    print(f"TEST: {name}")
    print(f"{'='*70}")
    print(f"Decision: {decision_result.decision.name}")
    print(f"Reason: {decision_result.decision_reason}")
    if decision_result.retry_feedback:
        print(f"\nRetry Feedback:\n{decision_result.retry_feedback}")
    print()


def main():
    """Run validation examples."""
    print("ValidationDecisionEngine - Manual Validation")
    print("=" * 70)

    # Load config
    config = {
        "decision_rules": {
            "reject_on_error_count": 3,
            "reject_on_placeholder_error": True,
            "reject_on_code_block_error": True,
            "reject_on_link_error": True,
            "max_retry_attempts": 2,
            "retry_on_structure_error": True,
            "retry_on_terminology_warning": True,
            "accept_warnings": True,
            "accept_after_max_retries": True,
        }
    }

    engine = ValidationDecisionEngine(config)

    # Test 1: ACCEPT - No errors
    result1 = ValidationResult(success=True, issues=[])
    decision1 = engine.make_decision(result1, retry_count=0, source="test")
    print_decision("ACCEPT - No Errors", decision1)
    assert decision1.decision == ValidationDecision.ACCEPT

    # Test 2: REJECT - Critical validator (PlaceholderValidator)
    result2 = ValidationResult(
        success=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="PlaceholderValidator",
                message="Missing placeholder {{CODE_1}} in translation",
                location="line 5",
            )
        ],
    )
    decision2 = engine.make_decision(result2, retry_count=0, source="test")
    print_decision("REJECT - Critical Validator (PlaceholderValidator)", decision2)
    assert decision2.decision == ValidationDecision.REJECT

    # Test 3: RETRY - Fixable structure error (Attempt 1)
    result3 = ValidationResult(
        success=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="StructureValidator",
                message="Heading count mismatch: expected 3, got 2",
                location="markdown body",
                details={"suggestion": "Add the missing heading level"},
            )
        ],
    )
    decision3 = engine.make_decision(result3, retry_count=0, source="test")
    print_decision("RETRY - Structure Error (Attempt 1 - Brief Feedback)", decision3)
    assert decision3.decision == ValidationDecision.RETRY
    assert "VALIDATION FEEDBACK" in decision3.retry_feedback

    # Test 4: RETRY - Same error on second attempt (Detailed feedback)
    decision4 = engine.make_decision(result3, retry_count=1, source="test")
    print_decision("RETRY - Structure Error (Attempt 2 - Detailed Feedback)", decision4)
    assert decision4.decision == ValidationDecision.RETRY
    assert "CRITICAL VALIDATION FEEDBACK" in decision4.retry_feedback
    assert "Location:" in decision4.retry_feedback

    # Test 5: ACCEPT - After exhausting retries
    decision5 = engine.make_decision(result3, retry_count=2, source="test")
    print_decision("ACCEPT - After Max Retries (Best Effort)", decision5)
    assert decision5.decision == ValidationDecision.ACCEPT

    # Test 6: RETRY - Multiple error types with validator-specific instructions
    result6 = ValidationResult(
        success=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="CompletenessValidator",
                message="3 segments missing from translation",
                location="segments 5, 8, 12",
            ),
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="TerminologyPreservationValidator",
                message="Company name 'Aspose' translated incorrectly",
                location="line 3",
            ),
        ],
    )
    decision6 = engine.make_decision(result6, retry_count=0, source="test")
    print_decision("RETRY - Multiple Error Types with Instructions", decision6)
    assert decision6.decision == ValidationDecision.RETRY
    assert "⚠ COMPLETENESS:" in decision6.retry_feedback
    assert "⚠ TERMINOLOGY:" in decision6.retry_feedback

    # Test 7: REJECT - High error count
    result7 = ValidationResult(
        success=False,
        issues=[
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="StructureValidator",
                message="Error 1",
            ),
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="StructureValidator",
                message="Error 2",
            ),
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="StructureValidator",
                message="Error 3",
            ),
        ],
    )
    decision7 = engine.make_decision(result7, retry_count=0, source="test")
    print_decision("REJECT - Error Count Threshold Exceeded", decision7)
    assert decision7.decision == ValidationDecision.REJECT

    # Test 8: Final attempt feedback (most urgent)
    config_strict = {
        "decision_rules": {
            "reject_on_error_count": 5,
            "max_retry_attempts": 3,
            "accept_after_max_retries": True,
            "accept_warnings": True,
        }
    }
    engine_strict = ValidationDecisionEngine(config_strict)
    decision8 = engine_strict.make_decision(result3, retry_count=2, source="test")
    print_decision("RETRY - Final Attempt (Most Urgent Feedback)", decision8)
    assert decision8.decision == ValidationDecision.RETRY
    assert "FINAL ATTEMPT" in decision8.retry_feedback
    assert "REQUIRED ACTION" in decision8.retry_feedback

    print("=" * 70)
    print("✓ All manual validation tests passed!")
    print("✓ Decision engine is working correctly")
    print("✓ Feedback escalation is functioning properly")
    print("=" * 70)


if __name__ == "__main__":
    try:
        main()
        sys.exit(0)
    except Exception as e:
        print(f"\n❌ Validation failed: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        sys.exit(1)
