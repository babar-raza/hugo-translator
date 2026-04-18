"""
Unit tests for post-translation validation framework.

Tests cover ValidationDecision enum, DecisionResult dataclass,
PostTranslationValidator abstract base class, and ValidationDecisionEngine stub.
"""

from typing import Any

import pytest

from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)
from src.translation_engine.validation.decision_engine import ValidationDecisionEngine
from src.translation_engine.validation.post_translation_validator import (
    DecisionResult,
    PostTranslationValidator,
    ValidationDecision,
)


class TestValidationDecision:
    """Test suite for ValidationDecision enum."""

    def test_enum_values(self) -> None:
        """Test that enum values have correct integer mappings."""
        assert ValidationDecision.ACCEPT == 0
        assert ValidationDecision.RETRY == 1
        assert ValidationDecision.REJECT == 2

    def test_enum_value_stability(self) -> None:
        """Test that enum values are stable for serialization."""
        # These values must never change for backward compatibility
        assert ValidationDecision.ACCEPT.value == 0
        assert ValidationDecision.RETRY.value == 1
        assert ValidationDecision.REJECT.value == 2

    def test_enum_ordering(self) -> None:
        """Test that enum values have correct ordering."""
        assert ValidationDecision.ACCEPT < ValidationDecision.RETRY
        assert ValidationDecision.RETRY < ValidationDecision.REJECT
        assert ValidationDecision.ACCEPT < ValidationDecision.REJECT

    def test_enum_from_int(self) -> None:
        """Test that enum can be constructed from integer values."""
        assert ValidationDecision(0) == ValidationDecision.ACCEPT
        assert ValidationDecision(1) == ValidationDecision.RETRY
        assert ValidationDecision(2) == ValidationDecision.REJECT

    def test_enum_invalid_value(self) -> None:
        """Test that invalid integer values raise ValueError."""
        with pytest.raises(ValueError):
            ValidationDecision(3)
        with pytest.raises(ValueError):
            ValidationDecision(-1)

    def test_enum_comparison(self) -> None:
        """Test enum comparison operations."""
        accept = ValidationDecision.ACCEPT
        retry = ValidationDecision.RETRY
        reject = ValidationDecision.REJECT

        assert accept == ValidationDecision.ACCEPT
        assert retry != accept
        assert reject > accept
        assert accept <= retry
        assert reject >= retry

    def test_enum_string_representation(self) -> None:
        """Test string representation of enum values.

        IntEnum returns integer value as string, not the full enum name.
        This is expected behavior for IntEnum.
        """
        assert str(ValidationDecision.ACCEPT) == "0"
        assert str(ValidationDecision.RETRY) == "1"
        assert str(ValidationDecision.REJECT) == "2"

    def test_enum_name_access(self) -> None:
        """Test accessing enum by name."""
        assert ValidationDecision["ACCEPT"] == ValidationDecision.ACCEPT
        assert ValidationDecision["RETRY"] == ValidationDecision.RETRY
        assert ValidationDecision["REJECT"] == ValidationDecision.REJECT

    def test_enum_membership(self) -> None:
        """Test enum membership checks."""
        assert ValidationDecision.ACCEPT in ValidationDecision
        assert 0 in ValidationDecision.__members__.values()


class TestDecisionResult:
    """Test suite for DecisionResult dataclass."""

    @pytest.fixture
    def mock_validation_result(self) -> ValidationResult:
        """Create a mock ValidationResult for testing."""
        return ValidationResult(
            success=True,
            issues=[],
            metadata={"test": "data"},
        )

    def test_initialization_accept(self, mock_validation_result: ValidationResult) -> None:
        """Test DecisionResult initialization with ACCEPT decision."""
        result = DecisionResult(
            decision=ValidationDecision.ACCEPT,
            decision_reason="All checks passed",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )

        assert result.decision == ValidationDecision.ACCEPT
        assert result.decision_reason == "All checks passed"
        assert result.retry_feedback is None
        assert result.validation_result == mock_validation_result

    def test_initialization_retry(self, mock_validation_result: ValidationResult) -> None:
        """Test DecisionResult initialization with RETRY decision."""
        result = DecisionResult(
            decision=ValidationDecision.RETRY,
            decision_reason="Minor issues found",
            retry_feedback="Fix placeholder syntax in line 42",
            validation_result=mock_validation_result,
        )

        assert result.decision == ValidationDecision.RETRY
        assert result.decision_reason == "Minor issues found"
        assert result.retry_feedback == "Fix placeholder syntax in line 42"
        assert result.validation_result == mock_validation_result

    def test_initialization_reject(self, mock_validation_result: ValidationResult) -> None:
        """Test DecisionResult initialization with REJECT decision."""
        result = DecisionResult(
            decision=ValidationDecision.REJECT,
            decision_reason="Critical errors found",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )

        assert result.decision == ValidationDecision.REJECT
        assert result.decision_reason == "Critical errors found"
        assert result.retry_feedback is None
        assert result.validation_result == mock_validation_result

    def test_dataclass_equality(self, mock_validation_result: ValidationResult) -> None:
        """Test that DecisionResult instances with same data are equal."""
        result1 = DecisionResult(
            decision=ValidationDecision.ACCEPT,
            decision_reason="Test",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )
        result2 = DecisionResult(
            decision=ValidationDecision.ACCEPT,
            decision_reason="Test",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )

        assert result1 == result2

    def test_dataclass_inequality(self, mock_validation_result: ValidationResult) -> None:
        """Test that DecisionResult instances with different data are not equal."""
        result1 = DecisionResult(
            decision=ValidationDecision.ACCEPT,
            decision_reason="Test",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )
        result2 = DecisionResult(
            decision=ValidationDecision.RETRY,
            decision_reason="Test",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )

        assert result1 != result2

    def test_field_access(self, mock_validation_result: ValidationResult) -> None:
        """Test direct field access on DecisionResult."""
        result = DecisionResult(
            decision=ValidationDecision.ACCEPT,
            decision_reason="Test reason",
            retry_feedback="Test feedback",
            validation_result=mock_validation_result,
        )

        # Test that all fields are accessible
        assert isinstance(result.decision, ValidationDecision)
        assert isinstance(result.decision_reason, str)
        assert result.retry_feedback is not None
        assert isinstance(result.validation_result, ValidationResult)

    def test_optional_retry_feedback_none(self, mock_validation_result: ValidationResult) -> None:
        """Test that retry_feedback can be None."""
        result = DecisionResult(
            decision=ValidationDecision.ACCEPT,
            decision_reason="Test",
            retry_feedback=None,
            validation_result=mock_validation_result,
        )

        assert result.retry_feedback is None

    def test_optional_retry_feedback_string(self, mock_validation_result: ValidationResult) -> None:
        """Test that retry_feedback can be a string."""
        feedback = "Please fix the issues"
        result = DecisionResult(
            decision=ValidationDecision.RETRY,
            decision_reason="Test",
            retry_feedback=feedback,
            validation_result=mock_validation_result,
        )

        assert result.retry_feedback == feedback

    def test_with_validation_result_with_issues(self) -> None:
        """Test DecisionResult with ValidationResult containing issues."""
        issues = [
            ValidationIssue(
                severity=ValidationSeverity.ERROR,
                validator="TestValidator",
                message="Test error",
                location="line 42",
            )
        ]
        validation_result = ValidationResult(
            success=False,
            issues=issues,
        )

        result = DecisionResult(
            decision=ValidationDecision.REJECT,
            decision_reason="Errors found",
            retry_feedback=None,
            validation_result=validation_result,
        )

        assert result.validation_result.success is False
        assert len(result.validation_result.issues) == 1
        assert result.validation_result.issues[0].severity == ValidationSeverity.ERROR


class TestPostTranslationValidator:
    """Test suite for PostTranslationValidator abstract base class."""

    def test_cannot_instantiate_abstract_class(self) -> None:
        """Test that PostTranslationValidator cannot be instantiated directly."""
        with pytest.raises(TypeError) as exc_info:
            PostTranslationValidator()  # type: ignore

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_must_implement_validate_method(self) -> None:
        """Test that subclasses must implement validate method."""

        class IncompleteValidator(PostTranslationValidator):
            pass

        with pytest.raises(TypeError) as exc_info:
            IncompleteValidator()  # type: ignore

        assert "Can't instantiate abstract class" in str(exc_info.value)

    def test_concrete_implementation_with_validate(self) -> None:
        """Test that concrete implementation with validate method can be instantiated."""

        class ConcreteValidator(PostTranslationValidator):
            def validate(
                self,
                source: str,
                translation: str,
                context: dict[str, Any] | None = None,
            ) -> ValidationResult:
                return ValidationResult(success=True)

        validator = ConcreteValidator()
        assert isinstance(validator, PostTranslationValidator)

    def test_concrete_implementation_validate_signature(self) -> None:
        """Test that concrete implementation respects validate signature."""

        class TestValidator(PostTranslationValidator):
            def validate(
                self,
                source: str,
                translation: str,
                context: dict[str, Any] | None = None,
            ) -> ValidationResult:
                return ValidationResult(
                    success=True,
                    metadata={"source_len": len(source), "translation_len": len(translation)},
                )

        validator = TestValidator()
        result = validator.validate("source text", "translation text")

        assert isinstance(result, ValidationResult)
        assert result.success is True
        assert result.metadata["source_len"] == 11
        assert result.metadata["translation_len"] == 16

    def test_validate_with_context(self) -> None:
        """Test validator validate method with context parameter."""

        class ContextAwareValidator(PostTranslationValidator):
            def validate(
                self,
                source: str,
                translation: str,
                context: dict[str, Any] | None = None,
            ) -> ValidationResult:
                if context and context.get("strict_mode"):
                    return ValidationResult(success=False, issues=[])
                return ValidationResult(success=True)

        validator = ContextAwareValidator()

        # Without context
        result1 = validator.validate("test", "test")
        assert result1.success is True

        # With context, non-strict
        result2 = validator.validate("test", "test", {"strict_mode": False})
        assert result2.success is True

        # With context, strict
        result3 = validator.validate("test", "test", {"strict_mode": True})
        assert result3.success is False

    def test_validate_returns_validation_result(self) -> None:
        """Test that validate method returns ValidationResult instance."""

        class SimpleValidator(PostTranslationValidator):
            def validate(
                self,
                source: str,
                translation: str,
                context: dict[str, Any] | None = None,
            ) -> ValidationResult:
                return ValidationResult(
                    success=len(source) == len(translation),
                    issues=[],
                )

        validator = SimpleValidator()
        result = validator.validate("abc", "xyz")

        assert isinstance(result, ValidationResult)
        assert result.success is True

    def test_validate_with_issues(self) -> None:
        """Test validator that returns ValidationResult with issues."""

        class IssueDetectingValidator(PostTranslationValidator):
            def validate(
                self,
                source: str,
                translation: str,
                context: dict[str, Any] | None = None,
            ) -> ValidationResult:
                issues = []
                if len(translation) == 0:
                    issues.append(
                        ValidationIssue(
                            severity=ValidationSeverity.ERROR,
                            validator="IssueDetectingValidator",
                            message="Translation is empty",
                        )
                    )
                return ValidationResult(
                    success=len(issues) == 0,
                    issues=issues,
                )

        validator = IssueDetectingValidator()

        # Valid case
        result1 = validator.validate("test", "test")
        assert result1.success is True
        assert len(result1.issues) == 0

        # Invalid case
        result2 = validator.validate("test", "")
        assert result2.success is False
        assert len(result2.issues) == 1
        assert result2.issues[0].severity == ValidationSeverity.ERROR


class TestValidationDecisionEngine:
    """Test suite for ValidationDecisionEngine stub implementation."""

    @pytest.fixture
    def mock_validation_result(self) -> ValidationResult:
        """Create a mock ValidationResult for testing."""
        return ValidationResult(success=True, issues=[])

    def test_initialization(self) -> None:
        """Test ValidationDecisionEngine initialization with config."""
        config = {"max_retries": 3, "threshold": 0.8}
        engine = ValidationDecisionEngine(config=config)

        assert engine.config == config

    def test_initialization_empty_config(self) -> None:
        """Test ValidationDecisionEngine initialization with empty config."""
        engine = ValidationDecisionEngine(config={})

        assert engine.config == {}

    def test_make_decision_returns_accept(self, mock_validation_result: ValidationResult) -> None:
        """Test that stub implementation always returns ACCEPT decision."""
        engine = ValidationDecisionEngine(config={})
        decision = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test source",
        )

        assert isinstance(decision, DecisionResult)
        assert decision.decision == ValidationDecision.ACCEPT

    def test_make_decision_reason(self, mock_validation_result: ValidationResult) -> None:
        """Test that decision includes a reason."""
        engine = ValidationDecisionEngine(config={})
        decision = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test source",
        )

        assert decision.decision_reason is not None
        assert len(decision.decision_reason) > 0

    def test_make_decision_no_retry_feedback(self, mock_validation_result: ValidationResult) -> None:
        """Test that stub implementation returns no retry feedback."""
        engine = ValidationDecisionEngine(config={})
        decision = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test source",
        )

        assert decision.retry_feedback is None

    def test_make_decision_includes_validation_result(
        self, mock_validation_result: ValidationResult
    ) -> None:
        """Test that decision includes original validation result."""
        engine = ValidationDecisionEngine(config={})
        decision = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test source",
        )

        assert decision.validation_result == mock_validation_result

    def test_make_decision_with_failed_validation(self) -> None:
        """Test stub behavior with failed validation result."""
        validation_result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    severity=ValidationSeverity.ERROR,
                    validator="TestValidator",
                    message="Test error",
                )
            ],
        )
        engine = ValidationDecisionEngine(config={})
        decision = engine.make_decision(
            validation_result=validation_result,
            retry_count=0,
            source="test source",
        )

        # With retry_count=0 and a retryable error, engine returns RETRY
        assert decision.decision == ValidationDecision.RETRY

    def test_make_decision_with_retry_count(self, mock_validation_result: ValidationResult) -> None:
        """Test stub behavior with different retry counts."""
        engine = ValidationDecisionEngine(config={})

        # First attempt
        decision1 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test",
        )
        assert decision1.decision == ValidationDecision.ACCEPT

        # Second attempt (retry)
        decision2 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=1,
            source="test",
        )
        assert decision2.decision == ValidationDecision.ACCEPT

        # Third attempt
        decision3 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=2,
            source="test",
        )
        assert decision3.decision == ValidationDecision.ACCEPT

    def test_make_decision_with_different_sources(
        self, mock_validation_result: ValidationResult
    ) -> None:
        """Test stub behavior with different source texts."""
        engine = ValidationDecisionEngine(config={})

        decision1 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="short",
        )
        decision2 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="much longer source text with more content",
        )

        # Stub returns same decision regardless
        assert decision1.decision == ValidationDecision.ACCEPT
        assert decision2.decision == ValidationDecision.ACCEPT

    def test_make_decision_deterministic(self, mock_validation_result: ValidationResult) -> None:
        """Test that multiple calls with same inputs produce identical results."""
        engine = ValidationDecisionEngine(config={})

        decision1 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test",
        )
        decision2 = engine.make_decision(
            validation_result=mock_validation_result,
            retry_count=0,
            source="test",
        )

        assert decision1.decision == decision2.decision
        assert decision1.decision_reason == decision2.decision_reason
        assert decision1.retry_feedback == decision2.retry_feedback
