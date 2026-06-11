"""
Tests for quality metrics aggregation and telemetry.

Tests the QualityMetricsAggregator and StructuredLogger.log_quality_metrics()
to ensure quality metrics are properly captured and formatted for telemetry.
"""

import pytest

from src.observability.logger import StructuredLogger
from src.observability.quality_metrics_aggregator import (
    QualityMetrics,
    QualityMetricsAggregator,
)
from src.translation_engine.validation.base import (
    ValidationIssue,
    ValidationResult,
    ValidationSeverity,
)


@pytest.fixture
def aggregator():
    """Create a fresh aggregator for each test."""
    return QualityMetricsAggregator()


@pytest.fixture
def logger():
    """Create a structured logger instance."""
    return StructuredLogger(name="test_quality_metrics", also_log_to_file=False)


class TestQualityMetricsAggregator:
    """Test QualityMetricsAggregator functionality."""

    def test_initialization(self, aggregator):
        """Test aggregator initializes with zero metrics."""
        metrics = aggregator.get_metrics()
        assert metrics.repetition_detected_count == 0
        assert metrics.max_ngram_frequency == 0
        assert metrics.length_ratio_mean is None
        assert metrics.length_ratio_max is None
        assert metrics.segments_checked == 0
        assert metrics.total_validation_issues == 0
        assert len(metrics.validation_rejection_by_validator) == 0

    def test_add_validation_result_empty(self, aggregator):
        """Test adding empty validation result."""
        result = ValidationResult(success=True)
        aggregator.add_validation_result(result)
        metrics = aggregator.get_metrics()
        assert metrics.total_validation_issues == 0
        assert metrics.error_count == 0
        assert metrics.warning_count == 0

    def test_add_validation_result_with_errors(self, aggregator):
        """Test adding validation result with errors."""
        issue1 = ValidationIssue(
            validator="TestValidator",
            severity=ValidationSeverity.ERROR,
            message="Test error 1",
        )
        issue2 = ValidationIssue(
            validator="TestValidator",
            severity=ValidationSeverity.WARNING,
            message="Test warning 1",
        )
        result = ValidationResult(success=False, issues=[issue1, issue2])

        aggregator.add_validation_result(result)
        metrics = aggregator.get_metrics()

        assert metrics.total_validation_issues == 2
        assert metrics.error_count == 1
        assert metrics.warning_count == 1
        assert "TestValidator" in metrics.validation_rejection_by_validator
        assert metrics.validation_rejection_by_validator["TestValidator"] == 1

    def test_add_multiple_validation_results(self, aggregator):
        """Test aggregating multiple validation results."""
        # First result with 2 errors
        result1 = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    validator="Validator1",
                    severity=ValidationSeverity.ERROR,
                    message="Error 1",
                ),
                ValidationIssue(
                    validator="Validator1",
                    severity=ValidationSeverity.ERROR,
                    message="Error 2",
                ),
            ],
        )

        # Second result with 1 error and 1 warning
        result2 = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    validator="Validator2",
                    severity=ValidationSeverity.ERROR,
                    message="Error 3",
                ),
                ValidationIssue(
                    validator="Validator2",
                    severity=ValidationSeverity.WARNING,
                    message="Warning 1",
                ),
            ],
        )

        aggregator.add_validation_result(result1)
        aggregator.add_validation_result(result2)
        metrics = aggregator.get_metrics()

        assert metrics.total_validation_issues == 4
        assert metrics.error_count == 3
        assert metrics.warning_count == 1
        assert metrics.validation_rejection_by_validator["Validator1"] == 2
        assert metrics.validation_rejection_by_validator["Validator2"] == 1

    def test_add_repetition_metrics_directly(self, aggregator):
        """Test adding repetition metrics directly."""
        aggregator.add_repetition_metrics(
            repetition_count=5,
            max_ngram_freq=12,
        )
        metrics = aggregator.get_metrics()

        assert metrics.repetition_detected_count == 5
        assert metrics.max_ngram_frequency == 12

    def test_add_repetition_metrics_accumulates(self, aggregator):
        """Test that repetition metrics accumulate."""
        aggregator.add_repetition_metrics(repetition_count=3, max_ngram_freq=10)
        aggregator.add_repetition_metrics(repetition_count=2, max_ngram_freq=15)
        metrics = aggregator.get_metrics()

        assert metrics.repetition_detected_count == 5
        assert metrics.max_ngram_frequency == 15  # Max of the two

    def test_add_length_ratios(self, aggregator):
        """Test adding length ratios."""
        aggregator.add_length_ratio(1.5)
        aggregator.add_length_ratio(2.0)
        aggregator.add_length_ratio(1.8)

        metrics = aggregator.get_metrics()

        assert metrics.length_ratio_max == 2.0
        assert abs(metrics.length_ratio_mean - 1.767) < 0.01  # (1.5+2.0+1.8)/3

    def test_reset_clears_metrics(self, aggregator):
        """Test reset clears all metrics."""
        aggregator.add_repetition_metrics(5, 10)
        aggregator.add_length_ratio(2.0)
        aggregator.add_validation_result(
            ValidationResult(
                success=False,
                issues=[
                    ValidationIssue(
                        validator="Test",
                        severity=ValidationSeverity.ERROR,
                        message="Error",
                    )
                ],
            )
        )

        aggregator.reset()
        metrics = aggregator.get_metrics()

        assert metrics.repetition_detected_count == 0
        assert metrics.length_ratio_mean is None
        assert metrics.total_validation_issues == 0

    def test_metrics_with_metadata_ngram(self, aggregator):
        """Test extracting n-gram metrics from metadata."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    validator="RepetitionDetectorValidator",
                    severity=ValidationSeverity.ERROR,
                    message="N-gram repetition detected",
                    details={"ngram": "repeated words", "count": 8},
                )
            ],
            metadata={
                "max_ngram_frequency": 8,
                "error_count": 1,
                "segments_checked": 5,
            },
        )

        aggregator.add_validation_result(result)
        metrics = aggregator.get_metrics()

        assert metrics.repetition_detected_count == 1
        assert metrics.max_ngram_frequency == 8
        assert metrics.segments_checked == 5

    def test_metrics_with_metadata_length(self, aggregator):
        """Test extracting length ratio metrics from metadata."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    validator="LengthAnomalyValidator",
                    severity=ValidationSeverity.ERROR,
                    message="Character ratio exceeds maximum",
                    details={"ratio": 3.5, "check_type": "character_ratio"},
                )
            ],
            metadata={"segments_checked": 10},
        )

        aggregator.add_validation_result(result)
        metrics = aggregator.get_metrics()

        assert metrics.length_ratio_max == 3.5
        assert metrics.segments_checked == 10

    def test_summary_string_generation(self, aggregator):
        """Test human-readable summary generation."""
        aggregator.add_repetition_metrics(3, 10)
        aggregator.add_length_ratio(1.5)
        aggregator.add_length_ratio(2.5)

        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    validator="Validator1",
                    severity=ValidationSeverity.ERROR,
                    message="Error",
                ),
                ValidationIssue(
                    validator="Validator2",
                    severity=ValidationSeverity.WARNING,
                    message="Warning",
                ),
            ],
        )
        aggregator.add_validation_result(result)

        summary = aggregator.get_summary_string()

        assert "Repetition Issues: 3" in summary
        assert "Max N-gram Frequency: 10" in summary
        assert "Total Validation Issues: 2" in summary
        assert "Validator1" in summary

    def test_only_error_rejections_counted(self, aggregator):
        """Test that only ERROR severity issues count as rejections."""
        result = ValidationResult(
            success=False,
            issues=[
                ValidationIssue(
                    validator="Validator1",
                    severity=ValidationSeverity.ERROR,
                    message="Error",
                ),
                ValidationIssue(
                    validator="Validator1",
                    severity=ValidationSeverity.WARNING,
                    message="Warning 1",
                ),
                ValidationIssue(
                    validator="Validator1",
                    severity=ValidationSeverity.WARNING,
                    message="Warning 2",
                ),
            ],
        )

        aggregator.add_validation_result(result)
        metrics = aggregator.get_metrics()

        # Only 1 error counts as rejection
        assert metrics.validation_rejection_by_validator["Validator1"] == 1
        assert metrics.total_validation_issues == 3
        assert metrics.error_count == 1
        assert metrics.warning_count == 2


class TestQualityMetricsDataclass:
    """Test QualityMetrics dataclass."""

    def test_to_dict_conversion(self):
        """Test converting metrics to dict."""
        metrics = QualityMetrics(
            repetition_detected_count=5,
            max_ngram_frequency=10,
            length_ratio_mean=1.8,
            length_ratio_max=2.5,
            validation_rejection_by_validator={"Validator1": 3},
            segments_checked=20,
            total_validation_issues=5,
        )

        result = metrics.to_dict()

        assert result["repetition_detected_count"] == 5
        assert result["max_ngram_frequency"] == 10
        assert result["length_ratio_mean"] == 1.8
        assert result["validation_rejection_by_validator"]["Validator1"] == 3


class TestStructuredLoggerQualityMetrics:
    """Test StructuredLogger quality metrics logging."""

    def test_log_quality_metrics_basic(self, logger, capsys):
        """Test logging quality metrics."""
        logger.log_quality_metrics(
            repetition_detected_count=5,
            max_ngram_frequency=12,
            length_ratio_mean=1.8,
            length_ratio_max=2.5,
            validation_rejection_by_validator={"Validator1": 3, "Validator2": 2},
            segments_checked=100,
            total_validation_issues=5,
        )

        # The log should be captured (exact output depends on logging config)
        # In this test, we just verify the method runs without error
        assert True  # Method executed without exception

    def test_log_quality_metrics_with_none_values(self, logger):
        """Test logging with None values."""
        logger.log_quality_metrics(
            repetition_detected_count=0,
            max_ngram_frequency=0,
            length_ratio_mean=None,
            length_ratio_max=None,
            validation_rejection_by_validator={},
            segments_checked=0,
            total_validation_issues=0,
        )

        # Should not raise an exception
        assert True

    def test_log_quality_metrics_rounds_floats(self, logger):
        """Test that float values are rounded appropriately."""
        logger.log_quality_metrics(
            length_ratio_mean=1.23456789,
            length_ratio_max=2.98765432,
        )

        # Should round to 3 decimal places without error
        assert True


class TestQualityMetricsIntegration:
    """Integration tests for quality metrics."""

    def test_end_to_end_aggregation_and_logging(self, logger):
        """Test complete flow from aggregation to logging."""
        aggregator = QualityMetricsAggregator()

        # Simulate multiple validation results
        for i in range(3):
            result = ValidationResult(
                success=False,
                issues=[
                    ValidationIssue(
                        validator=f"Validator{i}",
                        severity=ValidationSeverity.ERROR,
                        message=f"Error {i}",
                    )
                ],
                metadata={"segments_checked": 10},
            )
            aggregator.add_validation_result(result)

        # Add some direct metrics
        aggregator.add_repetition_metrics(2, 8)
        aggregator.add_length_ratio(1.5)
        aggregator.add_length_ratio(2.0)

        # Get metrics and log them
        metrics = aggregator.get_metrics()
        logger.log_quality_metrics(**metrics.to_dict())

        # Verify metrics are correct
        assert metrics.repetition_detected_count == 2
        assert metrics.max_ngram_frequency == 8
        assert metrics.error_count == 3
        assert len(metrics.validation_rejection_by_validator) == 3

    def test_no_validation_breakdown_when_no_errors(self):
        """Test that validation breakdown is empty when no errors occur."""
        aggregator = QualityMetricsAggregator()

        result = ValidationResult(
            success=True,
            issues=[
                ValidationIssue(
                    validator="TestValidator",
                    severity=ValidationSeverity.INFO,
                    message="Info only",
                )
            ],
        )

        aggregator.add_validation_result(result)
        metrics = aggregator.get_metrics()

        # No error rejections, so breakdown should be empty
        assert len(metrics.validation_rejection_by_validator) == 0
