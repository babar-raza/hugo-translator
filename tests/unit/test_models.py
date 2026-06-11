"""
Unit tests for translation engine data models.

Tests focus on:
- INF-03: Validation metrics extensions
- Backward compatibility with existing code
- Default values and field initialization
- Serialization and data integrity
"""

from pathlib import Path

from src.translation_engine.models import (
    DirectoryResult,
    TranslationResult,
    TranslationStats,
    ValidationDecision,
)


class TestValidationDecision:
    """Test ValidationDecision enum."""

    def test_enum_values(self):
        """Test enum values are correctly defined."""
        assert ValidationDecision.ACCEPT == 0
        assert ValidationDecision.RETRY == 1
        assert ValidationDecision.REJECT == 2

    def test_enum_ordering(self):
        """Test enum values are ordered by severity."""
        assert ValidationDecision.ACCEPT < ValidationDecision.RETRY
        assert ValidationDecision.RETRY < ValidationDecision.REJECT

    def test_enum_membership(self):
        """Test enum membership."""
        assert ValidationDecision.ACCEPT in ValidationDecision
        assert ValidationDecision.RETRY in ValidationDecision
        assert ValidationDecision.REJECT in ValidationDecision


class TestTranslationStatsValidationFields:
    """Test TranslationStats validation metrics (INF-03)."""

    def test_default_validation_fields(self):
        """Test validation fields have correct default values."""
        stats = TranslationStats()

        # Validation state flags
        assert stats.validation_passed is False
        assert stats.validation_failed is False
        assert stats.validation_retried == 0
        assert stats.validation_decision == ""

        # Issue counts
        assert stats.validation_errors == 0
        assert stats.validation_warnings == 0
        assert stats.validation_info == 0

        # Timing
        assert stats.validation_duration_ms == 0.0
        assert stats.retry_duration_ms == 0.0

    def test_validation_passed_state(self):
        """Test validation passed state."""
        stats = TranslationStats(
            validation_passed=True,
            validation_decision="ACCEPT",
            validation_duration_ms=150.5,
        )

        assert stats.validation_passed is True
        assert stats.validation_failed is False
        assert stats.validation_decision == "ACCEPT"
        assert stats.validation_duration_ms == 150.5

    def test_validation_failed_state(self):
        """Test validation failed state."""
        stats = TranslationStats(
            validation_failed=True,
            validation_decision="REJECT",
            validation_errors=5,
            validation_warnings=3,
            validation_info=2,
        )

        assert stats.validation_passed is False
        assert stats.validation_failed is True
        assert stats.validation_decision == "REJECT"
        assert stats.validation_errors == 5
        assert stats.validation_warnings == 3
        assert stats.validation_info == 2

    def test_validation_retry_state(self):
        """Test validation retry state."""
        stats = TranslationStats(
            validation_retried=2,
            validation_decision="RETRY",
            retry_duration_ms=350.25,
        )

        assert stats.validation_retried == 2
        assert stats.validation_decision == "RETRY"
        assert stats.retry_duration_ms == 350.25

    def test_validation_with_all_metrics(self):
        """Test all validation metrics together."""
        stats = TranslationStats(
            total_segments=100,
            tm_hits=50,
            validation_passed=True,
            validation_retried=1,
            validation_decision="ACCEPT",
            validation_errors=0,
            validation_warnings=2,
            validation_info=5,
            validation_duration_ms=200.0,
            retry_duration_ms=100.0,
        )

        # Existing fields still work
        assert stats.total_segments == 100
        assert stats.tm_hits == 50
        assert stats.tm_hit_rate == 0.5

        # New validation fields
        assert stats.validation_passed is True
        assert stats.validation_retried == 1
        assert stats.validation_decision == "ACCEPT"
        assert stats.validation_errors == 0
        assert stats.validation_warnings == 2
        assert stats.validation_info == 5
        assert stats.validation_duration_ms == 200.0
        assert stats.retry_duration_ms == 100.0


class TestTranslationResultDecisionFields:
    """Test TranslationResult validation decision fields (INF-03)."""

    def test_default_decision_fields(self):
        """Test decision fields have correct default values."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
        )

        assert result.validation_decision is None
        assert result.decision_reason is None
        assert result.retry_attempts == 0
        assert result.retry_history == []

    def test_decision_accept(self):
        """Test ACCEPT decision state."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            validation_decision=ValidationDecision.ACCEPT,
            decision_reason="Translation quality is excellent",
        )

        assert result.validation_decision == ValidationDecision.ACCEPT
        assert result.decision_reason == "Translation quality is excellent"
        assert result.retry_attempts == 0

    def test_decision_retry(self):
        """Test RETRY decision state."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            validation_decision=ValidationDecision.RETRY,
            decision_reason="Minor issues detected, retry recommended",
            retry_attempts=1,
        )

        assert result.validation_decision == ValidationDecision.RETRY
        assert result.decision_reason == "Minor issues detected, retry recommended"
        assert result.retry_attempts == 1

    def test_decision_reject(self):
        """Test REJECT decision state."""
        result = TranslationResult(
            success=False,
            file_path=Path("test.md"),
            validation_decision=ValidationDecision.REJECT,
            decision_reason="Critical errors found, translation rejected",
        )

        assert result.validation_decision == ValidationDecision.REJECT
        assert result.decision_reason == "Critical errors found, translation rejected"
        assert result.success is False

    def test_retry_history(self):
        """Test retry history tracking."""
        retry_history = [
            {
                "attempt": 1,
                "errors": 3,
                "decision": "RETRY",
                "reason": "First retry: placeholder issues",
            },
            {
                "attempt": 2,
                "errors": 1,
                "decision": "ACCEPT",
                "reason": "Second retry: minor warnings only",
            },
        ]

        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            validation_decision=ValidationDecision.ACCEPT,
            decision_reason="Accepted after retries",
            retry_attempts=2,
            retry_history=retry_history,
        )

        assert result.retry_attempts == 2
        assert len(result.retry_history) == 2
        assert result.retry_history[0]["attempt"] == 1
        assert result.retry_history[1]["decision"] == "ACCEPT"

    def test_decision_with_stats(self):
        """Test decision fields work with stats."""
        stats = TranslationStats(
            validation_passed=True,
            validation_retried=2,
            validation_errors=0,
            validation_warnings=1,
        )

        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            stats=stats,
            validation_decision=ValidationDecision.ACCEPT,
            decision_reason="Accepted after 2 retries",
            retry_attempts=2,
        )

        assert result.stats.validation_passed is True
        assert result.stats.validation_retried == 2
        assert result.validation_decision == ValidationDecision.ACCEPT
        assert result.retry_attempts == 2


class TestBackwardCompatibility:
    """Test backward compatibility with existing code."""

    def test_translation_stats_creation_without_validation_fields(self):
        """Test creating TranslationStats without validation fields still works."""
        stats = TranslationStats(
            total_segments=100,
            tm_hits=75,
            translated_segments=25,
            duration_seconds=5.0,
        )

        # Existing fields work
        assert stats.total_segments == 100
        assert stats.tm_hits == 75
        assert stats.translated_segments == 25
        assert stats.duration_seconds == 5.0

        # New fields have defaults
        assert stats.validation_passed is False
        assert stats.validation_errors == 0
        assert stats.validation_duration_ms == 0.0

    def test_translation_result_creation_without_decision_fields(self):
        """Test creating TranslationResult without decision fields still works."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            outputs={"fr": Path("test.fr.md")},
        )

        # Existing fields work
        assert result.success is True
        assert result.file_path == Path("test.md")
        assert "fr" in result.outputs

        # New fields have defaults
        assert result.validation_decision is None
        assert result.retry_attempts == 0
        assert result.retry_history == []

    def test_directory_result_aggregate_stats_with_validation(self):
        """Test DirectoryResult aggregates validation metrics correctly."""
        file1 = TranslationResult(
            success=True,
            file_path=Path("file1.md"),
            stats=TranslationStats(
                total_segments=50,
                validation_passed=True,
                validation_errors=0,
                validation_warnings=2,
                validation_duration_ms=100.0,
            ),
        )

        file2 = TranslationResult(
            success=True,
            file_path=Path("file2.md"),
            stats=TranslationStats(
                total_segments=30,
                validation_passed=True,
                validation_errors=0,
                validation_warnings=1,
                validation_duration_ms=75.0,
            ),
        )

        dir_result = DirectoryResult(
            success=True,
            directory=Path("content/"),
            file_results=[file1, file2],
            duration_seconds=10.0,
        )

        agg = dir_result.aggregate_stats

        # Existing aggregation works
        assert agg.total_segments == 80

        # New validation aggregation works
        assert agg.validation_passed is True
        assert agg.validation_errors == 0
        assert agg.validation_warnings == 3
        assert agg.validation_duration_ms == 175.0

    def test_existing_tests_still_pass(self):
        """Test that existing test patterns still work."""
        # Pattern from existing tests
        stats = TranslationStats()
        assert stats.total_segments == 0
        assert stats.tm_hits == 0
        assert stats.translated_segments == 0

        # TM hit rate calculation still works
        stats = TranslationStats(total_segments=100, tm_hits=75)
        assert stats.tm_hit_rate == 0.75

        # String representation still works
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
        )
        str_repr = str(result)
        assert "SUCCESS" in str_repr
        assert "test.md" in str_repr


class TestValidationFieldEdgeCases:
    """Test edge cases for validation fields."""

    def test_negative_counts_not_validated(self):
        """Test that negative counts are accepted (no validation enforced)."""
        # Note: The spec doesn't require validation, just storage
        stats = TranslationStats(
            validation_errors=-1,  # Should be prevented by application logic
            validation_warnings=-1,
        )

        # Fields accept any int value
        assert stats.validation_errors == -1
        assert stats.validation_warnings == -1

    def test_empty_retry_history_is_list(self):
        """Test retry_history defaults to empty list, not None."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
        )

        assert result.retry_history == []
        assert isinstance(result.retry_history, list)

        # Can append to it
        result.retry_history.append({"attempt": 1})
        assert len(result.retry_history) == 1

    def test_validation_decision_none_vs_empty_string(self):
        """Test distinction between None and empty string for decision fields."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
        )

        # TranslationResult.validation_decision is Optional[ValidationDecision] (None)
        assert result.validation_decision is None

        # TranslationStats.validation_decision is str (empty string)
        stats = TranslationStats()
        assert stats.validation_decision == ""
        assert isinstance(stats.validation_decision, str)

    def test_multiple_files_mixed_validation_states(self):
        """Test aggregation with mixed validation states."""
        file1 = TranslationResult(
            success=True,
            file_path=Path("file1.md"),
            stats=TranslationStats(
                validation_passed=True,
                validation_failed=False,
            ),
        )

        file2 = TranslationResult(
            success=False,
            file_path=Path("file2.md"),
            stats=TranslationStats(
                validation_passed=False,
                validation_failed=True,
            ),
        )

        dir_result = DirectoryResult(
            success=False,
            directory=Path("content/"),
            file_results=[file1, file2],
        )

        agg = dir_result.aggregate_stats

        # If any file passed, validation_passed is True
        # If any file failed, validation_failed is True
        assert agg.validation_passed is True
        assert agg.validation_failed is True


class TestSerializationAndDataIntegrity:
    """Test that models can be serialized and maintain data integrity."""

    def test_translation_stats_dict_conversion(self):
        """Test TranslationStats can be converted to dict (for serialization)."""
        stats = TranslationStats(
            total_segments=100,
            validation_passed=True,
            validation_errors=0,
            validation_warnings=2,
            validation_duration_ms=150.5,
        )

        # dataclass can be converted to dict
        stats_dict = stats.__dict__

        assert stats_dict["total_segments"] == 100
        assert stats_dict["validation_passed"] is True
        assert stats_dict["validation_errors"] == 0
        assert stats_dict["validation_duration_ms"] == 150.5

    def test_translation_result_with_enum_field(self):
        """Test TranslationResult with ValidationDecision enum."""
        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            validation_decision=ValidationDecision.ACCEPT,
        )

        # Enum value is accessible
        assert result.validation_decision == ValidationDecision.ACCEPT
        assert result.validation_decision.value == 0
        assert result.validation_decision.name == "ACCEPT"

    def test_retry_history_preserves_structure(self):
        """Test retry_history preserves complex data structures."""
        complex_history = [
            {
                "attempt": 1,
                "timestamp": "2024-01-01T12:00:00",
                "errors": 3,
                "issues": [
                    {"type": "placeholder", "message": "Missing {{var}}"},
                    {"type": "yaml", "message": "Invalid frontmatter"},
                ],
            },
        ]

        result = TranslationResult(
            success=True,
            file_path=Path("test.md"),
            retry_history=complex_history,
        )

        # Complex structure is preserved
        assert len(result.retry_history) == 1
        assert result.retry_history[0]["attempt"] == 1
        assert len(result.retry_history[0]["issues"]) == 2
        assert result.retry_history[0]["issues"][0]["type"] == "placeholder"
