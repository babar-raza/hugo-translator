"""
Unit tests for VerificationAgent base infrastructure.

Tests:
- Agent runs registered checks
- Results aggregate from multiple checks
- VerificationResult dataclass behavior
- VerificationIssue dataclass behavior
- Fail-fast mode
- Error handling for check failures
"""
import pytest
from typing import Any, Dict, List, Optional

from src.verification import (
    VerificationAgent,
    VerificationCheck,
    VerificationIssue,
    VerificationResult,
)


# Test fixtures - mock checks for testing
class PassingCheck(VerificationCheck):
    """Check that always passes (returns no issues)."""

    @property
    def name(self) -> str:
        return "passing_check"

    def run(
        self,
        source: Dict[str, Any],
        translated: Dict[str, Any],
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationIssue]:
        return []


class WarningCheck(VerificationCheck):
    """Check that returns a warning."""

    @property
    def name(self) -> str:
        return "warning_check"

    def run(
        self,
        source: Dict[str, Any],
        translated: Dict[str, Any],
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationIssue]:
        return [
            VerificationIssue(
                severity="warning",
                check_name=self.name,
                location="frontmatter.title",
                message="Minor issue detected",
            )
        ]


class ErrorCheck(VerificationCheck):
    """Check that returns an error."""

    @property
    def name(self) -> str:
        return "error_check"

    def run(
        self,
        source: Dict[str, Any],
        translated: Dict[str, Any],
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationIssue]:
        return [
            VerificationIssue(
                severity="error",
                check_name=self.name,
                location="frontmatter.description",
                message="Critical issue detected",
                source_text="Expected text",
                translated_text="Wrong text",
            )
        ]


class ExceptionCheck(VerificationCheck):
    """Check that raises an exception."""

    @property
    def name(self) -> str:
        return "exception_check"

    def run(
        self,
        source: Dict[str, Any],
        translated: Dict[str, Any],
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationIssue]:
        raise ValueError("Simulated check failure")


class DisabledCheck(VerificationCheck):
    """Check that is disabled."""

    @property
    def name(self) -> str:
        return "disabled_check"

    def is_enabled(self, context: Optional[Dict[str, Any]] = None) -> bool:
        return False

    def run(
        self,
        source: Dict[str, Any],
        translated: Dict[str, Any],
        target_lang: str,
        context: Optional[Dict[str, Any]] = None,
    ) -> List[VerificationIssue]:
        return [
            VerificationIssue(
                severity="error",
                check_name=self.name,
                location="should_not_run",
                message="This should not appear",
            )
        ]


class TestVerificationIssue:
    """Tests for VerificationIssue dataclass."""

    def test_issue_creation(self):
        """Test creating a verification issue."""
        issue = VerificationIssue(
            severity="error",
            check_name="test_check",
            location="frontmatter.title",
            message="Test message",
        )

        assert issue.severity == "error"
        assert issue.check_name == "test_check"
        assert issue.location == "frontmatter.title"
        assert issue.message == "Test message"
        assert issue.source_text is None
        assert issue.translated_text is None
        assert issue.metadata == {}

    def test_issue_with_optional_fields(self):
        """Test issue with all optional fields."""
        issue = VerificationIssue(
            severity="warning",
            check_name="test_check",
            location="body",
            message="Test",
            source_text="Source",
            translated_text="Translated",
            metadata={"key": "value"},
        )

        assert issue.source_text == "Source"
        assert issue.translated_text == "Translated"
        assert issue.metadata == {"key": "value"}

    def test_issue_to_dict(self):
        """Test serialization to dictionary."""
        issue = VerificationIssue(
            severity="error",
            check_name="test",
            location="loc",
            message="msg",
            source_text="src",
            translated_text="tgt",
        )

        d = issue.to_dict()

        assert d["severity"] == "error"
        assert d["check_name"] == "test"
        assert d["location"] == "loc"
        assert d["message"] == "msg"
        assert d["source_text"] == "src"
        assert d["translated_text"] == "tgt"

    def test_issue_to_dict_truncates_long_text(self):
        """Test that long text is truncated in serialization."""
        long_text = "x" * 500
        issue = VerificationIssue(
            severity="info",
            check_name="test",
            location="loc",
            message="msg",
            source_text=long_text,
            translated_text=long_text,
        )

        d = issue.to_dict()

        assert len(d["source_text"]) == 200
        assert len(d["translated_text"]) == 200


class TestVerificationResult:
    """Tests for VerificationResult dataclass."""

    def test_empty_result_passes(self):
        """Test that empty result passes."""
        result = VerificationResult()

        assert result.passed is True
        assert result.error_count == 0
        assert result.warning_count == 0
        assert result.info_count == 0

    def test_result_with_warning_passes(self):
        """Test that result with only warnings passes."""
        result = VerificationResult(
            issues=[
                VerificationIssue(
                    severity="warning",
                    check_name="test",
                    location="loc",
                    message="msg",
                )
            ]
        )

        assert result.passed is True
        assert result.warning_count == 1
        assert result.error_count == 0

    def test_result_with_error_fails(self):
        """Test that result with error fails."""
        result = VerificationResult(
            issues=[
                VerificationIssue(
                    severity="error",
                    check_name="test",
                    location="loc",
                    message="msg",
                )
            ]
        )

        assert result.passed is False
        assert result.error_count == 1

    def test_add_issue(self):
        """Test adding issues to result."""
        result = VerificationResult()
        result.add_issue(
            VerificationIssue(
                severity="info",
                check_name="test",
                location="loc",
                message="msg",
            )
        )

        assert len(result.issues) == 1
        assert result.info_count == 1

    def test_merge_results(self):
        """Test merging two results."""
        result1 = VerificationResult(
            issues=[
                VerificationIssue(
                    severity="warning",
                    check_name="test1",
                    location="loc1",
                    message="msg1",
                )
            ],
            check_results={"check1": {"passed": True}},
        )

        result2 = VerificationResult(
            issues=[
                VerificationIssue(
                    severity="error",
                    check_name="test2",
                    location="loc2",
                    message="msg2",
                )
            ],
            check_results={"check2": {"passed": False}},
        )

        result1.merge(result2)

        assert len(result1.issues) == 2
        assert result1.warning_count == 1
        assert result1.error_count == 1
        assert "check1" in result1.check_results
        assert "check2" in result1.check_results

    def test_result_to_dict(self):
        """Test serialization to dictionary."""
        result = VerificationResult(
            issues=[
                VerificationIssue(
                    severity="warning",
                    check_name="test",
                    location="loc",
                    message="msg",
                )
            ],
            check_results={"test": {"passed": True}},
            metadata={"key": "value"},
        )

        d = result.to_dict()

        assert d["passed"] is True
        assert d["warning_count"] == 1
        assert d["error_count"] == 0
        assert len(d["issues"]) == 1
        assert d["check_results"] == {"test": {"passed": True}}
        assert d["metadata"] == {"key": "value"}


class TestVerificationAgent:
    """Tests for VerificationAgent."""

    @pytest.fixture
    def sample_source(self):
        """Sample source document."""
        return {
            "frontmatter": {"title": "Test Title", "description": "Test Description"},
            "body": "Test body content",
        }

    @pytest.fixture
    def sample_translated(self):
        """Sample translated document."""
        return {
            "frontmatter": {"title": "Testtitel", "description": "Testbeschreibung"},
            "body": "Testinhalt",
        }

    def test_agent_creation_empty(self):
        """Test creating agent with no checks."""
        agent = VerificationAgent()

        assert len(agent) == 0
        assert agent.get_check_names() == []

    def test_agent_creation_with_checks(self):
        """Test creating agent with checks."""
        agent = VerificationAgent([PassingCheck(), WarningCheck()])

        assert len(agent) == 2
        assert "passing_check" in agent.get_check_names()
        assert "warning_check" in agent.get_check_names()

    def test_agent_add_check(self):
        """Test adding a check to agent."""
        agent = VerificationAgent()
        agent.add_check(PassingCheck())

        assert len(agent) == 1
        assert "passing_check" in agent.get_check_names()

    def test_agent_remove_check(self):
        """Test removing a check from agent."""
        agent = VerificationAgent([PassingCheck(), WarningCheck()])

        assert agent.remove_check("passing_check") is True
        assert len(agent) == 1
        assert "passing_check" not in agent.get_check_names()

    def test_agent_remove_nonexistent_check(self):
        """Test removing a check that doesn't exist."""
        agent = VerificationAgent([PassingCheck()])

        assert agent.remove_check("nonexistent") is False
        assert len(agent) == 1

    def test_verify_no_checks(self, sample_source, sample_translated):
        """Test verification with no checks."""
        agent = VerificationAgent()

        result = agent.verify(sample_source, sample_translated, "de")

        assert result.passed is True
        assert len(result.issues) == 0

    def test_verify_passing_check(self, sample_source, sample_translated):
        """Test verification with passing check."""
        agent = VerificationAgent([PassingCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        assert result.passed is True
        assert len(result.issues) == 0
        assert "passing_check" in result.metadata["checks_run"]

    def test_verify_warning_check(self, sample_source, sample_translated):
        """Test verification with warning check (still passes)."""
        agent = VerificationAgent([WarningCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        assert result.passed is True  # Warnings don't fail
        assert result.warning_count == 1
        assert "warning_check" in result.metadata["checks_run"]

    def test_verify_error_check(self, sample_source, sample_translated):
        """Test verification with error check (fails)."""
        agent = VerificationAgent([ErrorCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        assert result.passed is False
        assert result.error_count == 1
        assert "error_check" in result.metadata["checks_run"]

    def test_verify_multiple_checks(self, sample_source, sample_translated):
        """Test verification runs all checks."""
        agent = VerificationAgent([PassingCheck(), WarningCheck(), ErrorCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        assert result.passed is False
        assert result.error_count == 1
        assert result.warning_count == 1
        assert len(result.metadata["checks_run"]) == 3

    def test_verify_aggregates_results(self, sample_source, sample_translated):
        """Test that results from all checks are aggregated."""
        agent = VerificationAgent([WarningCheck(), ErrorCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        assert len(result.issues) == 2
        check_names = {issue.check_name for issue in result.issues}
        assert "warning_check" in check_names
        assert "error_check" in check_names

    def test_verify_records_check_results(self, sample_source, sample_translated):
        """Test that per-check results are recorded."""
        agent = VerificationAgent([PassingCheck(), ErrorCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        assert "passing_check" in result.check_results
        assert result.check_results["passing_check"]["passed"] is True
        assert result.check_results["passing_check"]["issue_count"] == 0

        assert "error_check" in result.check_results
        assert result.check_results["error_check"]["passed"] is False
        assert result.check_results["error_check"]["error_count"] == 1

    def test_verify_fail_fast(self, sample_source, sample_translated):
        """Test fail-fast mode stops on first error."""
        agent = VerificationAgent(
            [ErrorCheck(), WarningCheck()],  # Error first
            fail_fast=True,
        )

        result = agent.verify(sample_source, sample_translated, "de")

        # Should have stopped after error_check
        assert len(result.metadata["checks_run"]) == 1
        assert "error_check" in result.metadata["checks_run"]
        assert "warning_check" not in result.metadata["checks_run"]

    def test_verify_handles_check_exception(self, sample_source, sample_translated):
        """Test that check exceptions are handled gracefully."""
        agent = VerificationAgent([ExceptionCheck(), PassingCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        # Should have error from exception and continue to next check
        assert result.error_count == 1
        assert "exception_check" in result.check_results
        assert "passing_check" in result.check_results

        # Check exception is recorded as issue
        exception_issues = [
            i for i in result.issues if i.check_name == "exception_check"
        ]
        assert len(exception_issues) == 1
        assert "Simulated check failure" in exception_issues[0].message

    def test_verify_skips_disabled_check(self, sample_source, sample_translated):
        """Test that disabled checks are skipped."""
        agent = VerificationAgent([DisabledCheck(), PassingCheck()])

        result = agent.verify(sample_source, sample_translated, "de")

        # Disabled check should be skipped, not run
        assert "disabled_check" in result.metadata["checks_skipped"]
        assert "disabled_check" not in result.metadata["checks_run"]
        assert result.error_count == 0  # Disabled check's error should not appear

    def test_verify_with_context(self, sample_source, sample_translated):
        """Test that context is passed to checks."""

        class ContextAwareCheck(VerificationCheck):
            @property
            def name(self) -> str:
                return "context_check"

            def run(
                self,
                source: Dict[str, Any],
                translated: Dict[str, Any],
                target_lang: str,
                context: Optional[Dict[str, Any]] = None,
            ) -> List[VerificationIssue]:
                if context and context.get("skip"):
                    return []
                return [
                    VerificationIssue(
                        severity="error",
                        check_name=self.name,
                        location="test",
                        message="Context not found",
                    )
                ]

        agent = VerificationAgent([ContextAwareCheck()])

        # Without context - should fail
        result1 = agent.verify(sample_source, sample_translated, "de")
        assert result1.error_count == 1

        # With skip context - should pass
        result2 = agent.verify(
            sample_source, sample_translated, "de", context={"skip": True}
        )
        assert result2.error_count == 0

    def test_agent_repr(self):
        """Test string representation."""
        agent = VerificationAgent([PassingCheck(), ErrorCheck()])

        repr_str = repr(agent)

        assert "VerificationAgent" in repr_str
        assert "passing_check" in repr_str
        assert "error_check" in repr_str
