"""
Unit tests for ValidationDecisionEngine.

Tests cover:
- Decision rules (REJECT on critical errors, RETRY on fixable errors, ACCEPT on no errors)
- Critical validator detection (PlaceholderValidator, CodeBlockValidator, LinkValidator)
- Error count thresholds
- Retry budget enforcement
- Retry feedback generation and escalation
- Configuration-driven behavior
- Edge cases (empty results, missing context)
- Telemetry integration (DEC-03)
"""

from unittest.mock import Mock, call

from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.translation_engine.validation.decision_engine import ValidationDecisionEngine
from src.translation_engine.validation.post_translation_validator import (
    ValidationDecision,
)


class TestValidationDecisionEngine:
    """Test suite for ValidationDecisionEngine."""

    def setup_method(self):
        """Set up test fixtures."""
        # Default config matching validation.yaml
        self.default_config = {
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
        self.engine = ValidationDecisionEngine(self.default_config)

    # ==================== Decision Rule Tests ====================

    def test_reject_on_critical_error_placeholder_validator(self):
        """Test REJECT decision when PlaceholderValidator fails."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="PlaceholderValidator",
                    message="Missing placeholders in translation: {{CODE_1}}",
                    location="placeholders",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Critical validator failed: PlaceholderValidator" in decision.decision_reason
        assert decision.retry_feedback is None

    def test_reject_on_critical_error_code_block_validator(self):
        """Test REJECT decision when CodeBlockValidator fails."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CodeBlockValidator",
                    message="Code block corrupted in translation",
                    location="line 10",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Critical validator failed: CodeBlockValidator" in decision.decision_reason
        assert decision.retry_feedback is None

    def test_reject_on_critical_error_link_validator(self):
        """Test REJECT decision when LinkValidator fails."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="LinkValidator",
                    message="Broken link in translation",
                    location="line 5",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Critical validator failed: LinkValidator" in decision.decision_reason
        assert decision.retry_feedback is None

    def test_reject_on_critical_error_message_placeholder(self):
        """Test REJECT when error message contains 'placeholder'."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CustomValidator",
                    message="Placeholder integrity violated",
                    location="body",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "PlaceholderError" in decision.decision_reason

    def test_reject_on_critical_error_message_code_block(self):
        """Test REJECT when error message contains 'code block'."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CustomValidator",
                    message="Code block format is corrupted",
                    location="body",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "CodeBlockError" in decision.decision_reason

    def test_reject_on_critical_error_message_link(self):
        """Test REJECT when error message contains 'link'."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CustomValidator",
                    message="Link validation failed",
                    location="body",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "LinkError" in decision.decision_reason

    def test_reject_on_high_error_count(self):
        """Test REJECT when error count exceeds threshold."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Heading count mismatch",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="List structure damaged",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="TerminologyPreservationValidator",
                    message="Company name mistranslated",
                ),
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Error count 3 >= threshold 3" in decision.decision_reason
        assert decision.retry_feedback is None

    def test_reject_on_error_count_threshold(self):
        """Test REJECT at exact error count threshold."""
        # Config with threshold of 2
        config = {
            "decision_rules": {
                "reject_on_error_count": 2,
                "max_retry_attempts": 2,
                "accept_after_max_retries": True,
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error 1",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error 2",
                ),
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Error count 2 >= threshold 2" in decision.decision_reason

    def test_retry_with_fixable_errors(self):
        """Test RETRY decision when fixable errors are present."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Heading mismatch: expected 3, got 2",
                    location="body",
                    details={"suggestion": "Add missing heading"},
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="source text")

        assert decision.decision == ValidationDecision.RETRY
        assert "Retryable errors, attempt 1/2" in decision.decision_reason
        assert decision.retry_feedback is not None
        assert "VALIDATION FEEDBACK" in decision.retry_feedback

    def test_retry_on_terminology_warning(self):
        """Test RETRY when terminology warnings present (if configured)."""
        result = ValidationResult(
            success=True,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Company name 'Aspose' should be preserved",
                    location="line 5",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        # With no errors and accept_warnings=True, should ACCEPT
        assert decision.decision == ValidationDecision.ACCEPT

    def test_accept_no_errors(self):
        """Test ACCEPT decision when no errors are present."""
        result = ValidationResult(success=True, issues=[])
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.ACCEPT
        assert "No errors, warnings acceptable" in decision.decision_reason
        assert decision.retry_feedback is None

    def test_accept_with_warnings_only(self):
        """Test ACCEPT when only warnings are present."""
        result = ValidationResult(
            success=True,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Minor terminology issue",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    validator="InfoValidator",
                    message="Informational note",
                ),
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.ACCEPT
        assert "No errors, warnings acceptable" in decision.decision_reason

    def test_accept_after_max_retries(self):
        """Test ACCEPT after exhausting retry budget."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Minor structure issue",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=2, source="test")

        assert decision.decision == ValidationDecision.ACCEPT
        assert "Best effort after 2 retries" in decision.decision_reason
        assert decision.retry_feedback is None

    def test_reject_after_max_retries_strict_mode(self):
        """Test REJECT after max retries when accept_after_max_retries=False."""
        config = {
            "decision_rules": {
                "reject_on_error_count": 3,
                "max_retry_attempts": 2,
                "accept_after_max_retries": False,  # Strict mode
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Persistent error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=2, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Failed after 2 retries" in decision.decision_reason

    def test_reject_warnings_when_accept_warnings_false(self):
        """Test behavior when accept_warnings=False."""
        config = {
            "decision_rules": {
                "reject_on_error_count": 3,
                "max_retry_attempts": 2,
                "accept_after_max_retries": True,
                "accept_warnings": False,  # Strict mode
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=True,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Warning",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        # With warnings but accept_warnings=False, should try to retry
        assert decision.decision == ValidationDecision.RETRY

    # ==================== Retry Feedback Tests ====================

    def test_feedback_brief_on_first_retry(self):
        """Test brief feedback on first retry attempt."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Heading count mismatch",
                    location="body",
                    details={"suggestion": "Add missing heading"},
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.RETRY
        feedback = decision.retry_feedback
        assert "VALIDATION FEEDBACK" in feedback
        assert "CRITICAL" not in feedback
        assert "FINAL ATTEMPT" not in feedback
        # First attempt: brief, just message
        assert "Heading count mismatch" in feedback
        # Should not have detailed location on first attempt
        assert "Location:" not in feedback

    def test_feedback_detailed_on_second_retry(self):
        """Test detailed feedback on second retry attempt."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Heading count mismatch",
                    location="body section",
                    details={"suggestion": "Add missing heading"},
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=1, source="test")

        assert decision.decision == ValidationDecision.RETRY
        feedback = decision.retry_feedback
        assert "CRITICAL VALIDATION FEEDBACK" in feedback
        assert "FINAL ATTEMPT" not in feedback
        # Second attempt: detailed with validator, location, fix
        assert "[CompletenessValidator]" in feedback
        assert "Location: body section" in feedback
        assert "Fix: Add missing heading" in feedback

    def test_feedback_explicit_on_final_retry(self):
        """Test explicit instructions on final retry attempt."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Heading count mismatch",
                    location="body section",
                    details={"suggestion": "Add missing heading"},
                )
            ],
        )
        # Max retry attempts is 2, so retry_count=1 is the final attempt (attempts 0, 1)
        # Actually, max_retry_attempts=2 means we can retry up to 2 times
        # So retry_count can be 0, 1 (within budget)
        # At retry_count=2, we've exhausted the budget
        # Let's check the final retry feedback when retry_count is at the edge
        config = {
            "decision_rules": {
                "reject_on_error_count": 3,
                "max_retry_attempts": 3,  # Allow 3 retries
                "accept_after_max_retries": True,
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        decision = engine.make_decision(result, retry_count=2, source="test")

        assert decision.decision == ValidationDecision.RETRY
        feedback = decision.retry_feedback
        assert "FINAL ATTEMPT" in feedback
        assert "This is CRITICAL - translation will be REJECTED if not fixed." in feedback
        assert "REQUIRED ACTION: Add missing heading" in feedback

    def test_feedback_warnings_included_on_later_retries(self):
        """Test that warnings are included in feedback on retry attempt 2+."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error message",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Warning message",
                ),
            ],
        )

        # First attempt: no warnings in feedback
        decision = self.engine.make_decision(result, retry_count=0, source="test")
        assert "WARNINGS" not in decision.retry_feedback

        # Second attempt: warnings included
        decision = self.engine.make_decision(result, retry_count=1, source="test")
        assert "WARNINGS (should fix if possible):" in decision.retry_feedback
        assert "[TerminologyPreservationValidator] Warning message" in decision.retry_feedback

    def test_feedback_specific_instructions_completeness(self):
        """Test specific instructions for CompletenessValidator errors."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Missing segments in translation",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        feedback = decision.retry_feedback
        assert "⚠ COMPLETENESS:" in feedback
        assert "Ensure ALL source segments are translated" in feedback

    def test_feedback_specific_instructions_terminology(self):
        """Test specific instructions for TerminologyPreservationValidator errors."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="TerminologyPreservationValidator",
                    message="Company name mistranslated",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        feedback = decision.retry_feedback
        assert "⚠ TERMINOLOGY:" in feedback
        assert "Aspose" in feedback
        assert "EXACTLY as they appear in source" in feedback

    def test_feedback_specific_instructions_shortcode(self):
        """ShortcodePreservationValidator is CRITICAL: always REJECTS, no retry feedback.

        ShortcodePreservationValidator was added to CRITICAL_VALIDATORS (Fix 1.1, RC-4).
        Errors from this validator cause immediate REJECT without retry feedback,
        even at retry_count=0 and with accept_after_max_retries=True.
        """
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="ShortcodePreservationValidator",
                    message="Shortcode corrupted",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert decision.retry_feedback is None
        assert "ShortcodePreservationValidator" in decision.decision_reason

    def test_feedback_specific_instructions_structure(self):
        """Test specific instructions for StructureValidator errors."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="StructureValidator",
                    message="Structure mismatch",
                )
            ],
        )
        # StructureValidator is now a critical validator, so make_decision returns REJECT
        # with retry_feedback=None. Test the feedback method directly instead.
        feedback = self.engine._generate_retry_feedback(result, retry_count=0)
        assert "⚠ STRUCTURE:" in feedback
        assert "Maintain the same number and level" in feedback

    def test_feedback_multiple_error_types(self):
        """Test feedback with multiple error types includes all instructions."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Missing segments",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="TerminologyPreservationValidator",
                    message="Terminology error",
                ),
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        feedback = decision.retry_feedback
        assert "⚠ COMPLETENESS:" in feedback
        assert "⚠ TERMINOLOGY:" in feedback

    # ==================== Configuration Tests ====================

    def test_custom_error_threshold(self):
        """Test custom reject_on_error_count threshold."""
        config = {
            "decision_rules": {
                "reject_on_error_count": 1,  # Reject on first error
                "max_retry_attempts": 2,
                "accept_after_max_retries": True,
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Single error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT
        assert "Error count 1 >= threshold 1" in decision.decision_reason

    def test_custom_max_retry_attempts(self):
        """Test custom max_retry_attempts configuration."""
        config = {
            "decision_rules": {
                "reject_on_error_count": 3,
                "max_retry_attempts": 1,  # Only 1 retry
                "accept_after_max_retries": True,
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )

        # First attempt: should retry
        decision = engine.make_decision(result, retry_count=0, source="test")
        assert decision.decision == ValidationDecision.RETRY

        # After 1 retry: should accept
        decision = engine.make_decision(result, retry_count=1, source="test")
        assert decision.decision == ValidationDecision.ACCEPT

    def test_disable_specific_rejection_triggers(self):
        """Test disabling specific rejection triggers."""
        config = {
            "decision_rules": {
                "reject_on_error_count": 3,
                "reject_on_placeholder_error": False,  # Disabled
                "max_retry_attempts": 2,
                "accept_after_max_retries": True,
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CustomValidator",
                    message="Placeholder error detected",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        # With reject_on_placeholder_error=False, should not immediately reject
        # Should try to retry instead
        assert decision.decision == ValidationDecision.RETRY

    def test_empty_config_uses_defaults(self):
        """Test that empty config uses default values."""
        engine = ValidationDecisionEngine({})

        # Should use default thresholds
        assert engine.reject_on_error_count == 3
        assert engine.max_retry_attempts == 2
        assert engine.accept_warnings is True
        assert engine.accept_after_max_retries is True

    # ==================== Edge Cases ====================

    def test_empty_validation_result(self):
        """Test decision with empty validation result."""
        result = ValidationResult(success=True, issues=[])
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.ACCEPT

    def test_retry_count_at_boundary(self):
        """Test retry count exactly at max_retry_attempts boundary."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )

        # At retry_count=1, should still retry (max_retry_attempts=2)
        decision = self.engine.make_decision(result, retry_count=1, source="test")
        assert decision.decision == ValidationDecision.RETRY

        # At retry_count=2, should accept (exhausted)
        decision = self.engine.make_decision(result, retry_count=2, source="test")
        assert decision.decision == ValidationDecision.ACCEPT

    def test_mixed_severity_issues(self):
        """Test decision with mixed severity issues."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error 1",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Warning 1",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    validator="InfoValidator",
                    message="Info 1",
                ),
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        # Should count only errors for threshold
        assert decision.decision == ValidationDecision.RETRY
        assert "Retryable errors" in decision.decision_reason

    def test_is_retryable_with_structure_errors(self):
        """Test _is_retryable identifies structure errors."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="StructureValidator",
                    message="Structure error",
                )
            ],
        )
        assert self.engine._is_retryable(result) is True

    def test_is_retryable_with_terminology_warnings(self):
        """Test _is_retryable identifies terminology warnings."""
        result = ValidationResult(
            success=True,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Terminology warning",
                )
            ],
        )
        assert self.engine._is_retryable(result) is True

    def test_is_retryable_default_behavior(self):
        """Test _is_retryable defaults to True."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="UnknownValidator",
                    message="Unknown error",
                )
            ],
        )
        # Should default to retryable
        assert self.engine._is_retryable(result) is True

    def test_critical_validator_case_sensitive(self):
        """Test that critical validator check is case-sensitive."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="PlaceholderValidator",  # Exact match
                    message="Error",
                )
            ],
        )
        assert self.engine._check_critical_failure(result) == "PlaceholderValidator"

    def test_decision_result_includes_validation_result(self):
        """Test that DecisionResult includes original validation result."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="StructureValidator",
                    message="Error",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")

        assert decision.validation_result is result
        assert len(decision.validation_result.issues) == 1

    def test_retry_count_included_in_reason(self):
        """Test that retry count is included in decision reason."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=0, source="test")
        assert "attempt 1/2" in decision.decision_reason

        decision = self.engine.make_decision(result, retry_count=1, source="test")
        assert "attempt 2/2" in decision.decision_reason

    def test_feedback_without_suggestion_in_details(self):
        """Test feedback generation when issue has no suggestion in details."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error without suggestion",
                    location="body",
                    details={},  # No suggestion
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=1, source="test")

        feedback = decision.retry_feedback
        # Should not crash, and should not include "Fix:" line
        assert "Fix:" not in feedback
        assert "Error without suggestion" in feedback

    def test_feedback_without_location(self):
        """Test feedback generation when issue has no location."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error without location",
                    location=None,  # No location
                )
            ],
        )
        decision = self.engine.make_decision(result, retry_count=1, source="test")

        feedback = decision.retry_feedback
        # Should not crash, and should not include "Location:" line
        assert "Location:" not in feedback
        assert "Error without location" in feedback

    def test_feedback_empty_issues_list(self):
        """Test feedback generation with empty issues list (edge case)."""
        result = ValidationResult(success=True, issues=[])
        # Force a retry decision by using retry_count within budget
        # This shouldn't normally happen, but let's test the feedback method
        feedback = self.engine._generate_retry_feedback(result, retry_count=0)

        # Should handle gracefully
        assert "VALIDATION FEEDBACK" in feedback
        # No errors or warnings sections
        assert "ERRORS" not in feedback

    def test_zero_retry_budget(self):
        """Test behavior with zero retry budget."""
        config = {
            "decision_rules": {
                "reject_on_error_count": 3,
                "max_retry_attempts": 0,  # No retries allowed
                "accept_after_max_retries": True,
                "accept_warnings": True,
            }
        }
        engine = ValidationDecisionEngine(config)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        # With max_retry_attempts=0, retry_count=0 should be at limit
        assert decision.decision == ValidationDecision.ACCEPT
        assert "Best effort after 0 retries" in decision.decision_reason


class TestValidationDecisionEngineTelemetry:
    """Test suite for telemetry integration in ValidationDecisionEngine (DEC-03)."""

    def setup_method(self):
        """Set up test fixtures."""
        self.default_config = {
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

        # Create mock telemetry and run_context
        self.mock_telemetry = Mock()
        self.mock_run_context = Mock()

    # ==================== Telemetry Event Tests ====================

    def test_telemetry_validation_decision_emitted_accept(self):
        """Test that validation_decision_made event is emitted on ACCEPT."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(success=True, issues=[])
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.ACCEPT

        # Verify telemetry.track_validation_decision was called
        self.mock_telemetry.track_validation_decision.assert_called_once_with(
            run_context=self.mock_run_context,
            decision=ValidationDecision.ACCEPT,
            retry_count=0,
            error_count=0,
            warning_count=0,
            validator_results={},
            feedback_provided=False,
        )

    def test_telemetry_validation_decision_emitted_retry(self):
        """Test that validation_decision_made event is emitted on RETRY."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Structure error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.RETRY

        # Verify telemetry.track_validation_decision was called
        self.mock_telemetry.track_validation_decision.assert_called_once_with(
            run_context=self.mock_run_context,
            decision=ValidationDecision.RETRY,
            retry_count=0,
            error_count=1,
            warning_count=0,
            validator_results={"CompletenessValidator": False},
            feedback_provided=True,
        )

    def test_telemetry_validation_decision_emitted_reject(self):
        """Test that validation_decision_made event is emitted on REJECT."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="PlaceholderValidator",
                    message="Critical error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.REJECT

        # Verify telemetry.track_validation_decision was called
        self.mock_telemetry.track_validation_decision.assert_called_once_with(
            run_context=self.mock_run_context,
            decision=ValidationDecision.REJECT,
            retry_count=0,
            error_count=1,
            warning_count=0,
            validator_results={"PlaceholderValidator": False},
            feedback_provided=False,
        )

    def test_telemetry_validation_error_emitted(self):
        """Test that validation_error events are emitted for each failed validator."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Structure error",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Terminology warning",
                ),
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.RETRY

        # Verify telemetry.track_validation_error was called for each error/warning
        assert self.mock_telemetry.track_validation_error.call_count == 2

        # Check first call (ERROR)
        call_args_list = self.mock_telemetry.track_validation_error.call_args_list
        assert call_args_list[0] == call(
            run_context=self.mock_run_context,
            validator_name="CompletenessValidator",
            error_type="completeness",
            severity="error",
            message="Structure error",
        )

        # Check second call (WARNING)
        assert call_args_list[1] == call(
            run_context=self.mock_run_context,
            validator_name="TerminologyPreservationValidator",
            error_type="terminologypreservation",
            severity="warning",
            message="Terminology warning",
        )

    def test_telemetry_validation_error_not_emitted_on_accept_no_issues(self):
        """Test that validation_error events are not emitted when there are no issues."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(success=True, issues=[])
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.ACCEPT

        # Verify no validation errors were tracked
        self.mock_telemetry.track_validation_error.assert_not_called()

    def test_telemetry_with_multiple_errors(self):
        """Test telemetry with multiple errors and warnings."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="ShortcodePreservationValidator",
                    message="Error 1",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error 2",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Warning 1",
                ),
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        # ShortcodePreservationValidator is CRITICAL → REJECT immediately at retry_count=0
        assert decision.decision == ValidationDecision.REJECT

        # Verify telemetry.track_validation_decision was called with correct counts
        self.mock_telemetry.track_validation_decision.assert_called_once_with(
            run_context=self.mock_run_context,
            decision=ValidationDecision.REJECT.value,
            retry_count=0,
            error_count=2,
            warning_count=1,
            validator_results={
                "ShortcodePreservationValidator": False,
                "CompletenessValidator": False,
            },
            feedback_provided=False,
        )

        # Verify telemetry.track_validation_error was called for each error/warning
        assert self.mock_telemetry.track_validation_error.call_count == 3

    def test_telemetry_not_called_when_disabled(self):
        """Test that telemetry is not called when telemetry is None."""
        engine = ValidationDecisionEngine(self.default_config)  # No telemetry

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.RETRY
        # No assertions needed - just verify no exceptions are raised

    def test_telemetry_not_called_when_run_context_none(self):
        """Test that telemetry is not called when run_context is None."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=None,  # No run_context
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        assert decision.decision == ValidationDecision.RETRY

        # Verify telemetry methods were not called
        self.mock_telemetry.track_validation_decision.assert_not_called()
        self.mock_telemetry.track_validation_error.assert_not_called()

    def test_telemetry_validator_results_only_failed_validators(self):
        """Test that validator_results only includes failed validators."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="StructureValidator",
                    message="Error",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.WARNING,
                    validator="TerminologyPreservationValidator",
                    message="Warning",
                ),
                ValidationIssue(
                    severity=ValidationSeverity.INFO,
                    validator="InfoValidator",
                    message="Info",
                ),
            ],
        )
        decision = engine.make_decision(result, retry_count=0, source="test")

        # Verify only ERROR-severity validators are in validator_results
        call_args = self.mock_telemetry.track_validation_decision.call_args
        validator_results = call_args.kwargs["validator_results"]
        assert validator_results == {"StructureValidator": False}

    def test_telemetry_feedback_provided_flag(self):
        """Test that feedback_provided flag is set correctly."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        # Case 1: ACCEPT with no feedback
        result_accept = ValidationResult(success=True, issues=[])
        decision = engine.make_decision(result_accept, retry_count=0, source="test")

        call_args = self.mock_telemetry.track_validation_decision.call_args
        assert call_args.kwargs["feedback_provided"] is False

        # Reset mock
        self.mock_telemetry.reset_mock()

        # Case 2: RETRY with feedback
        result_retry = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="CompletenessValidator",
                    message="Error",
                )
            ],
        )
        decision = engine.make_decision(result_retry, retry_count=0, source="test")

        call_args = self.mock_telemetry.track_validation_decision.call_args
        assert call_args.kwargs["feedback_provided"] is True

        # Reset mock
        self.mock_telemetry.reset_mock()

        # Case 3: REJECT with no feedback
        result_reject = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="PlaceholderValidator",
                    message="Critical error",
                )
            ],
        )
        decision = engine.make_decision(result_reject, retry_count=0, source="test")

        call_args = self.mock_telemetry.track_validation_decision.call_args
        assert call_args.kwargs["feedback_provided"] is False

    def test_telemetry_retry_count_tracking(self):
        """Test that retry_count is correctly tracked in telemetry."""
        engine = ValidationDecisionEngine(
            self.default_config,
            telemetry=self.mock_telemetry,
            run_context=self.mock_run_context,
        )

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="StructureValidator",
                    message="Error",
                )
            ],
        )

        # First attempt
        decision = engine.make_decision(result, retry_count=0, source="test")
        call_args = self.mock_telemetry.track_validation_decision.call_args
        assert call_args.kwargs["retry_count"] == 0

        # Reset mock
        self.mock_telemetry.reset_mock()

        # Second attempt
        decision = engine.make_decision(result, retry_count=1, source="test")
        call_args = self.mock_telemetry.track_validation_decision.call_args
        assert call_args.kwargs["retry_count"] == 1

        # Reset mock
        self.mock_telemetry.reset_mock()

        # Third attempt (exhausted)
        decision = engine.make_decision(result, retry_count=2, source="test")
        call_args = self.mock_telemetry.track_validation_decision.call_args
        assert call_args.kwargs["retry_count"] == 2


class TestShortcodePreservationValidatorCritical:
    """RC-4 regression tests: ShortcodePreservationValidator in CRITICAL_VALIDATORS.

    Verifies that a ShortcodePreservationValidator ERROR causes REJECT even when
    accept_after_max_retries=True and retry_count has reached max_retry_attempts.

    Before Fix 1.1, this validator was absent from CRITICAL_VALIDATORS, so with
    accept_after_max_retries=True the engine would ACCEPT a translation with broken
    shortcode balance after exhausting retries. 52 pre-RC-5 files were created this way.
    """

    def _make_config(self, accept_after_max_retries: bool, max_retries: int = 2) -> dict:
        return {
            "decision_rules": {
                "reject_on_error_count": 99,  # high threshold — must not trigger
                "reject_on_placeholder_error": False,
                "reject_on_code_block_error": False,
                "reject_on_link_error": False,
                "max_retry_attempts": max_retries,
                "retry_on_structure_error": True,
                "retry_on_terminology_warning": False,
                "accept_warnings": True,
                "accept_after_max_retries": accept_after_max_retries,
            }
        }

    def _make_shortcode_error_result(self) -> "ValidationResult":
        return ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="ShortcodePreservationValidator",
                    message="Orphan closing shortcode: {{% /steps %}} has no matching opener",
                    location="body",
                )
            ],
        )

    def test_shortcode_error_rejects_when_accept_after_max_retries_true_and_retries_exhausted(self):
        """CRITICAL_VALIDATORS gate fires for ShortcodePreservationValidator even with
        accept_after_max_retries=True and retry_count at max.

        This is the exact condition under which the 52 shortcode-broken files were
        written before the RC-4 fix: retries exhausted, accept_after_max_retries=True,
        ShortcodePreservationValidator not in CRITICAL_VALIDATORS.
        """
        config = self._make_config(accept_after_max_retries=True, max_retries=2)
        engine = ValidationDecisionEngine(config)
        result = self._make_shortcode_error_result()

        # retry_count == max_retry_attempts (retries exhausted)
        decision = engine.make_decision(result, retry_count=2, source="test source")

        assert decision.decision == ValidationDecision.REJECT, (
            f"Expected REJECT via CRITICAL_VALIDATORS gate but got {decision.decision}. "
            f"Reason: {decision.decision_reason}"
        )
        assert "ShortcodePreservationValidator" in decision.decision_reason

    def test_shortcode_error_also_rejects_at_first_attempt(self):
        """CRITICAL gate fires on the very first attempt (retry_count=0)."""
        config = self._make_config(accept_after_max_retries=True)
        engine = ValidationDecisionEngine(config)
        result = self._make_shortcode_error_result()

        decision = engine.make_decision(result, retry_count=0, source="test source")

        assert decision.decision == ValidationDecision.REJECT
        assert "ShortcodePreservationValidator" in decision.decision_reason

    def test_shortcode_validator_is_in_critical_validators_set(self):
        """Validates that ShortcodePreservationValidator is registered in CRITICAL_VALIDATORS."""
        assert "ShortcodePreservationValidator" in ValidationDecisionEngine.CRITICAL_VALIDATORS, (
            "ShortcodePreservationValidator must be in CRITICAL_VALIDATORS to prevent "
            "accept_after_max_retries=True from writing shortcode-broken files."
        )


class TestSemanticSimilarityValidatorCritical:
    """HT-QUALITY-GATES-001 Part 22 (plan 5.4 item 2) regression tests:
    SemanticSimilarityValidator in CRITICAL_VALIDATORS.

    Before this fix, SemanticSimilarityValidator ERRORs (cosine similarity
    < 0.40, "meaning diverges significantly from source") were structurally
    excluded from ever blocking a write on MT backends (~34/36 locales) via
    file_pipeline.py's accept-best-effort bypass (BUG-022-FIX/
    TC-RETRY-FIX-018), which only escalates to a hard reject for validators
    in CRITICAL_VALIDATORS. Confirmed in root cause F: this was true even
    on the rare occasions the validator's encoder happened to be wired up,
    since membership in this set -- not just "did the validator fire" -- is
    what the accept-best-effort bypass actually checks.
    """

    def _make_config(self, accept_after_max_retries: bool, max_retries: int = 2) -> dict:
        return {
            "decision_rules": {
                "reject_on_error_count": 99,  # high threshold — must not trigger
                "reject_on_placeholder_error": False,
                "reject_on_code_block_error": False,
                "reject_on_link_error": False,
                "max_retry_attempts": max_retries,
                "retry_on_structure_error": True,
                "retry_on_terminology_warning": False,
                "accept_warnings": True,
                "accept_after_max_retries": accept_after_max_retries,
            }
        }

    def _make_semantic_divergence_result(self) -> "ValidationResult":
        return ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="SemanticSimilarityValidator",
                    message="Semantic similarity 0.310 < 0.4 — translation meaning "
                            "diverges significantly from source",
                    location="document",
                    details={"similarity": 0.31, "threshold": 0.4},
                )
            ],
        )

    def test_semantic_divergence_rejects_when_retries_exhausted(self):
        """The exact condition MT-backend translations hit most often:
        retries exhausted, accept_after_max_retries=True. Before this fix,
        a severely-diverged translation would ship anyway at this point."""
        config = self._make_config(accept_after_max_retries=True, max_retries=2)
        engine = ValidationDecisionEngine(config)
        result = self._make_semantic_divergence_result()

        decision = engine.make_decision(result, retry_count=2, source="test source")

        assert decision.decision == ValidationDecision.REJECT, (
            f"Expected REJECT via CRITICAL_VALIDATORS gate but got {decision.decision}. "
            f"Reason: {decision.decision_reason}"
        )
        assert "SemanticSimilarityValidator" in decision.decision_reason

    def test_semantic_divergence_also_rejects_at_first_attempt(self):
        config = self._make_config(accept_after_max_retries=True)
        engine = ValidationDecisionEngine(config)
        result = self._make_semantic_divergence_result()

        decision = engine.make_decision(result, retry_count=0, source="test source")

        assert decision.decision == ValidationDecision.REJECT
        assert "SemanticSimilarityValidator" in decision.decision_reason

    def test_semantic_similarity_validator_is_in_critical_validators_set(self):
        assert "SemanticSimilarityValidator" in ValidationDecisionEngine.CRITICAL_VALIDATORS, (
            "SemanticSimilarityValidator must be in CRITICAL_VALIDATORS or its ERROR "
            "issues are silently accepted as best-effort on MT backends, exactly like "
            "the ShortcodePreservationValidator gap this same fix pattern already closed."
        )
