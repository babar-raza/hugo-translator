"""
Validation decision engine for making ACCEPT/RETRY/REJECT decisions.

This module provides the ValidationDecisionEngine class that analyzes validation
results and makes intelligent decisions based on error severity, retry budget,
and configurable thresholds.

Decision Rules:
1. REJECT if critical validator failed (placeholder, code block, link errors)
2. REJECT if error count >= reject_on_error_count threshold
3. ACCEPT if no errors (only warnings/info)
4. RETRY if fixable errors present and retry budget available
5. ACCEPT/REJECT after exhausting retries based on config

Implemented in taskcards DEC-01, DEC-02, and DEC-03.
"""

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_metrics_logger = logging.getLogger(__name__)
_METRICS_LOG = Path("data/logs/validation_metrics.jsonl")
# Cached flag so the config is not re-read on every call
_local_log_enabled: bool | None = None

from .base import ValidationResult, ValidationSeverity
from .post_translation_validator import DecisionResult, ValidationDecision


class ValidationDecisionEngine:
    """Makes automated ACCEPT/RETRY/REJECT decisions based on validation results.

    Decision Rules:
    1. REJECT if:
       - Critical validator failed (placeholder error, code block error, link error)
       - Error count >= reject_on_error_count threshold
       - No retries remaining and quality insufficient

    2. RETRY if:
       - Fixable errors present (structure, terminology)
       - Retry budget available (retry_count < max_retry_attempts)
       - Warnings exceed threshold (if retry_on_terminology_warning)

    3. ACCEPT if:
       - No errors (only warnings/info)
       - Warnings within threshold
       - Best effort after exhausting retries

    Example:
        >>> engine = ValidationDecisionEngine(config)
        >>> decision = engine.make_decision(
        ...     validation_result=result,
        ...     retry_count=0,
        ...     source=source_text
        ... )
        >>> if decision.decision == ValidationDecision.REJECT:
        ...     # Discard translation
        ... elif decision.decision == ValidationDecision.RETRY:
        ...     # Retry with decision.retry_feedback
        ... else:
        ...     # Accept translation
    """

    # Critical validators that always trigger REJECT on error
    CRITICAL_VALIDATORS = {
        "PlaceholderValidator",
        "CodeBlockValidator",
        "LinkValidator",
        "StructureValidator",
        "ShortcodePreservationValidator",  # defense-in-depth: class default accept_after_max_retries=True creates gap when instantiated directly
    }

    def __init__(self, config: dict[str, Any], telemetry=None, run_context=None) -> None:
        """Initialize decision engine with configuration.

        Args:
            config: Decision rules from validation.yaml
            telemetry: Optional telemetry instance for tracking metrics
            run_context: Optional run context for telemetry events
        """
        self.config = config
        self.decision_rules = config.get("decision_rules", {})

        # Load thresholds
        self.reject_on_error_count = self.decision_rules.get("reject_on_error_count", 3)
        self.max_retry_attempts = self.decision_rules.get("max_retry_attempts", 2)
        self.accept_warnings = self.decision_rules.get("accept_warnings", True)
        self.accept_after_max_retries = self.decision_rules.get("accept_after_max_retries", True)

        # Specific rejection triggers
        self.reject_on_placeholder_error = self.decision_rules.get("reject_on_placeholder_error", True)
        self.reject_on_code_block_error = self.decision_rules.get("reject_on_code_block_error", True)
        self.reject_on_link_error = self.decision_rules.get("reject_on_link_error", True)
        self.reject_on_repetition_error = self.decision_rules.get("reject_on_repetition_error", True)

        # Retry triggers
        self.retry_on_structure_error = self.decision_rules.get("retry_on_structure_error", True)
        self.retry_on_terminology_warning = self.decision_rules.get("retry_on_terminology_warning", True)

        # Telemetry integration (DEC-03)
        self.telemetry = telemetry
        self.run_context = run_context

    def make_decision(
        self,
        validation_result: ValidationResult,
        retry_count: int,
        source: str,
    ) -> DecisionResult:
        """Make ACCEPT/RETRY/REJECT decision based on validation result.

        Args:
            validation_result: Aggregated validation result from all validators
            retry_count: Number of retries already attempted
            source: Original source text (for feedback generation)

        Returns:
            DecisionResult with decision and optional retry feedback
        """
        # Count errors and warnings for telemetry
        error_count = len([i for i in validation_result.issues if i.severity == ValidationSeverity.ERROR])
        warning_count = len([i for i in validation_result.issues if i.severity == ValidationSeverity.WARNING])

        # Collect validator results for telemetry
        validator_results = {}
        for issue in validation_result.issues:
            if issue.severity == ValidationSeverity.ERROR:
                validator_results[issue.validator] = False
        # Mark validators without errors as passed (if we have the full list)
        # For now, just track failed validators

        # Rule 1: Critical validator failed → REJECT
        critical_failure = self._check_critical_failure(validation_result)
        if critical_failure:
            decision_result = DecisionResult(
                decision=ValidationDecision.REJECT,
                decision_reason=f"Critical validator failed: {critical_failure}",
                retry_feedback=None,
                validation_result=validation_result,
            )
            self._track_decision(decision_result, retry_count, error_count, warning_count, validator_results)
            self._track_validation_errors(validation_result)
            return decision_result

        # Rule 2: Error count >= threshold → REJECT
        if error_count >= self.reject_on_error_count:
            decision_result = DecisionResult(
                decision=ValidationDecision.REJECT,
                decision_reason=f"Error count {error_count} >= threshold {self.reject_on_error_count}",
                retry_feedback=None,
                validation_result=validation_result,
            )
            self._track_decision(decision_result, retry_count, error_count, warning_count, validator_results)
            self._track_validation_errors(validation_result)
            return decision_result

        # Rule 3: No errors, warnings OK → ACCEPT
        if error_count == 0:
            if self.accept_warnings or warning_count == 0:
                decision_result = DecisionResult(
                    decision=ValidationDecision.ACCEPT,
                    decision_reason="No errors, warnings acceptable",
                    retry_feedback=None,
                    validation_result=validation_result,
                )
                self._track_decision(decision_result, retry_count, error_count, warning_count, validator_results)
                return decision_result

        # Rule 4: Errors + retries available → RETRY
        if retry_count < self.max_retry_attempts:
            if self._is_retryable(validation_result):
                retry_feedback = self._generate_retry_feedback(validation_result, retry_count)
                decision_result = DecisionResult(
                    decision=ValidationDecision.RETRY,
                    decision_reason=f"Retryable errors, attempt {retry_count + 1}/{self.max_retry_attempts}",
                    retry_feedback=retry_feedback,
                    validation_result=validation_result,
                )
                self._track_decision(decision_result, retry_count, error_count, warning_count, validator_results)
                self._track_validation_errors(validation_result)
                return decision_result

        # Rule 5: Exhausted retries → ACCEPT or REJECT
        # Never accept if a critical validator still reports errors
        critical_still_failing = self._check_critical_failure(validation_result)
        if self.accept_after_max_retries and not critical_still_failing:
            decision_result = DecisionResult(
                decision=ValidationDecision.ACCEPT,
                decision_reason=f"Best effort after {retry_count} retries",
                retry_feedback=None,
                validation_result=validation_result,
            )
            self._track_decision(decision_result, retry_count, error_count, warning_count, validator_results)
            self._track_validation_errors(validation_result)
            return decision_result
        else:
            decision_result = DecisionResult(
                decision=ValidationDecision.REJECT,
                decision_reason=f"Failed after {retry_count} retries",
                retry_feedback=None,
                validation_result=validation_result,
            )
            self._track_decision(decision_result, retry_count, error_count, warning_count, validator_results)
            self._track_validation_errors(validation_result)
            return decision_result

    def _check_critical_failure(self, validation_result: ValidationResult) -> str | None:
        """Check if any critical validator failed.

        Args:
            validation_result: Validation result to check

        Returns:
            Name of critical validator that failed, or None
        """
        for issue in validation_result.issues:
            if issue.severity == ValidationSeverity.ERROR:
                if issue.validator in self.CRITICAL_VALIDATORS:
                    return issue.validator

                # Check specific rejection triggers
                if "placeholder" in issue.message.lower() and self.reject_on_placeholder_error:
                    return "PlaceholderError"
                if "code block" in issue.message.lower() and self.reject_on_code_block_error:
                    return "CodeBlockError"
                if "link" in issue.message.lower() and self.reject_on_link_error:
                    return "LinkError"
                if issue.validator == "RepetitionDetectorValidator" and self.reject_on_repetition_error:
                    return "RepetitionError"

        return None

    def _is_retryable(self, validation_result: ValidationResult) -> bool:
        """Check if errors are retryable.

        Args:
            validation_result: Validation result

        Returns:
            True if errors can be fixed with retry
        """
        for issue in validation_result.issues:
            # Structure errors are retryable
            if issue.severity == ValidationSeverity.ERROR and "structure" in issue.validator.lower():
                if self.retry_on_structure_error:
                    return True

            # Terminology warnings may trigger retry
            if issue.severity == ValidationSeverity.WARNING and "terminology" in issue.validator.lower():
                if self.retry_on_terminology_warning:
                    return True

        return True  # Default to retryable unless critical

    def _generate_retry_feedback(
        self,
        validation_result: ValidationResult,
        retry_count: int,
    ) -> str:
        """Generate actionable feedback for retry attempt.

        Feedback escalation by attempt:
        - Attempt 1: Brief summary of issues
        - Attempt 2: Detailed issues with locations
        - Attempt 3: Examples and explicit instructions

        Args:
            validation_result: Validation result with issues
            retry_count: Current retry count (0-based)

        Returns:
            Formatted feedback string for translation prompt
        """
        feedback_parts = []

        # Header based on retry attempt
        if retry_count == 0:
            feedback_parts.append("VALIDATION FEEDBACK - Please address the following issues:")
        elif retry_count == 1:
            feedback_parts.append("CRITICAL VALIDATION FEEDBACK - Previous translation had issues. Pay close attention:")
        else:
            feedback_parts.append("FINAL ATTEMPT - This is the last retry. You MUST fix these issues:")

        # Group issues by severity and validator
        errors = [i for i in validation_result.issues if i.severity == ValidationSeverity.ERROR]
        warnings = [i for i in validation_result.issues if i.severity == ValidationSeverity.WARNING]

        # Add errors with escalating detail
        if errors:
            feedback_parts.append("\nERRORS (must fix):")
            for idx, issue in enumerate(errors, 1):
                if retry_count == 0:
                    # Brief
                    feedback_parts.append(f"{idx}. {issue.message}")
                elif retry_count == 1:
                    # Detailed
                    feedback_parts.append(f"{idx}. [{issue.validator}] {issue.message}")
                    if issue.location:
                        feedback_parts.append(f"   Location: {issue.location}")
                    if issue.details and "suggestion" in issue.details:
                        feedback_parts.append(f"   Fix: {issue.details['suggestion']}")
                else:
                    # Explicit with examples
                    feedback_parts.append(f"{idx}. [{issue.validator}] {issue.message}")
                    if issue.location:
                        feedback_parts.append(f"   Location: {issue.location}")
                    if issue.details and "suggestion" in issue.details:
                        feedback_parts.append(f"   REQUIRED ACTION: {issue.details['suggestion']}")
                    feedback_parts.append("   This is CRITICAL - translation will be REJECTED if not fixed.")

        # Add warnings for final attempt
        if warnings and retry_count >= 1:
            feedback_parts.append("\nWARNINGS (should fix if possible):")
            for idx, issue in enumerate(warnings, 1):
                feedback_parts.append(f"{idx}. [{issue.validator}] {issue.message}")

        # Add specific instructions based on error types
        error_types = set(i.validator for i in errors)

        if "CompletenessValidator" in error_types:
            feedback_parts.append("\n⚠ COMPLETENESS: Ensure ALL source segments are translated. No segments should be skipped.")

        if "TerminologyPreservationValidator" in error_types:
            feedback_parts.append("\n⚠ TERMINOLOGY: Preserve company names (Aspose), product names (Aspose.Words), and platform names (.NET) EXACTLY as they appear in source.")

        if "ShortcodePreservationValidator" in error_types:
            feedback_parts.append("\n⚠ SHORTCODES: Hugo shortcodes ({{< ... >}}) must be preserved EXACTLY. Do not translate shortcode names or parameters.")

        if "StructureValidator" in error_types:
            feedback_parts.append("\n⚠ STRUCTURE: Maintain the same number and level of headings, lists, and code blocks as the source.")

        return "\n".join(feedback_parts)

    def _track_decision(
        self,
        decision_result: DecisionResult,
        retry_count: int,
        error_count: int,
        warning_count: int,
        validator_results: dict[str, bool],
    ) -> None:
        """Track validation decision via telemetry.

        Args:
            decision_result: The decision result
            retry_count: Number of retries attempted
            error_count: Number of validation errors
            warning_count: Number of validation warnings
            validator_results: Dict mapping validator names to pass/fail status
        """
        if not self.telemetry or not self.run_context:
            return

        self.telemetry.track_validation_decision(
            run_context=self.run_context,
            decision=decision_result.decision.value,
            retry_count=retry_count,
            error_count=error_count,
            warning_count=warning_count,
            validator_results=validator_results,
            feedback_provided=decision_result.retry_feedback is not None,
        )

    def _track_validation_errors(self, validation_result: ValidationResult) -> None:
        """Track individual validation errors via telemetry.

        Args:
            validation_result: Validation result with issues
        """
        if not self.telemetry or not self.run_context:
            return

        for issue in validation_result.issues:
            # Only track ERROR and WARNING severity issues
            if issue.severity in (ValidationSeverity.ERROR, ValidationSeverity.WARNING):
                # Determine error type from validator name
                error_type = issue.validator.replace("Validator", "").lower()

                self.telemetry.track_validation_error(
                    run_context=self.run_context,
                    validator_name=issue.validator,
                    error_type=error_type,
                    severity=issue.severity.value,
                    message=issue.message,
                )


def append_validation_metric(
    *,
    file_path: str,
    lang: str,
    decision: str,
    validator_results: dict[str, bool],
    retry_count: int,
    error_count: int = 0,
    warning_count: int = 0,
) -> None:
    """Append a validation outcome record to the local metrics log (T3-D).

    Gated by ``telemetry.local_validation_log: true`` in config/global.yaml.
    All exceptions are silently swallowed to remain non-blocking.

    Args:
        file_path: Relative or absolute path to the translated file.
        lang: Target language code (e.g. 'es', 'de').
        decision: 'accept', 'reject', or 'retry'.
        validator_results: Mapping of validator name → passed (True/False).
        retry_count: Number of retries used before this decision.
        error_count: Total ERROR-severity issues.
        warning_count: Total WARNING-severity issues.
    """
    global _local_log_enabled
    try:
        # Lazy read config flag — cache to avoid repeated YAML reads
        if _local_log_enabled is None:
            try:
                from src.utils.config_loader import get_global_config
                _local_log_enabled = bool(
                    get_global_config().get("telemetry", {}).get("local_validation_log", False)
                )
            except Exception:
                _local_log_enabled = False
        if not _local_log_enabled:
            return

        record = {
            "ts": datetime.now(timezone.utc).isoformat(),
            "file": str(file_path),
            "lang": lang,
            "decision": decision,
            "retry_count": retry_count,
            "error_count": error_count,
            "warning_count": warning_count,
            "validator_results": validator_results,
        }
        _METRICS_LOG.parent.mkdir(parents=True, exist_ok=True)
        with _METRICS_LOG.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(record, ensure_ascii=False) + "\n")
    except Exception as exc:
        _metrics_logger.debug("append_validation_metric: write failed (non-fatal): %s", exc)
