"""
Quality metrics aggregator for translation telemetry.

Aggregates quality metrics from validation results during translation runs,
including repetition detection, length anomalies, and validation breakdowns.

This module provides utilities to collect and aggregate quality metrics
that can be logged as telemetry for monitoring and reporting.

Example:
    aggregator = QualityMetricsAggregator()
    aggregator.add_validation_result(validation_result)
    metrics = aggregator.get_metrics()
    logger.log_quality_metrics(**metrics)
"""

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass
class QualityMetrics:
    """Aggregated quality metrics from validation results."""

    repetition_detected_count: int = 0
    max_ngram_frequency: int = 0
    length_ratio_mean: Optional[float] = None
    length_ratio_max: Optional[float] = None
    validation_rejection_by_validator: Dict[str, int] = None
    segments_checked: int = 0
    total_validation_issues: int = 0
    error_count: int = 0
    warning_count: int = 0

    def __post_init__(self):
        """Initialize default dicts."""
        if self.validation_rejection_by_validator is None:
            self.validation_rejection_by_validator = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert metrics to dictionary for logging."""
        return {
            "repetition_detected_count": self.repetition_detected_count,
            "max_ngram_frequency": self.max_ngram_frequency,
            "length_ratio_mean": self.length_ratio_mean,
            "length_ratio_max": self.length_ratio_max,
            "validation_rejection_by_validator": self.validation_rejection_by_validator,
            "segments_checked": self.segments_checked,
            "total_validation_issues": self.total_validation_issues,
            "error_count": self.error_count,
            "warning_count": self.warning_count,
        }


class QualityMetricsAggregator:
    """
    Aggregates quality metrics from validation results.

    Collects and aggregates metrics related to:
    - Repetition detection (from RepetitionDetectorValidator)
    - Length anomalies (from LengthAnomalyValidator)
    - Validation rejections (per validator breakdown)
    """

    def __init__(self):
        """Initialize metrics aggregator."""
        self.metrics = QualityMetrics()
        self._length_ratios: List[float] = []
        self._validator_results: Dict[str, Dict[str, int]] = {}

    def add_validation_result(self, result: Any) -> None:
        """
        Add a validation result to aggregate metrics from.

        Args:
            result: ValidationResult to extract metrics from
        """
        if not result:
            return

        # Update total issue counts
        if hasattr(result, 'error_count'):
            self.metrics.error_count += result.error_count
        if hasattr(result, 'warning_count'):
            self.metrics.warning_count += result.warning_count
        if hasattr(result, 'issues'):
            self.metrics.total_validation_issues += len(result.issues)

        # Process metadata for validator-specific metrics
        if hasattr(result, 'metadata') and result.metadata:
            self._process_metadata(result.metadata, result)

        # Extract length ratio metrics from issue details (LengthAnomalyValidator)
        if hasattr(result, 'issues'):
            for issue in result.issues:
                if hasattr(issue, 'validator') and issue.validator == "LengthAnomalyValidator":
                    details = getattr(issue, 'details', None) or {}
                    ratio = details.get("ratio")
                    if ratio and isinstance(ratio, (int, float)):
                        self._length_ratios.append(float(ratio))

        # Track rejection counts by validator
        if hasattr(result, 'issues'):
            self._track_validator_rejections(result)

    def _process_metadata(self, metadata: Dict[str, Any], result: Any) -> None:
        """
        Process metadata from validation result to extract quality metrics.

        Args:
            metadata: Metadata dict from ValidationResult
            result: The ValidationResult being processed
        """
        # Extract repetition metrics (from RepetitionDetectorValidator)
        if "ngram" in metadata or "max_ngram_frequency" in metadata:
            # If we see ngram details, increment repetition detected count
            self.metrics.repetition_detected_count += metadata.get("error_count", 0)
            # Track max n-gram frequency
            ngram_freq = metadata.get("max_ngram_frequency", 0)
            if isinstance(ngram_freq, int) and ngram_freq > 0:
                self.metrics.max_ngram_frequency = max(self.metrics.max_ngram_frequency, ngram_freq)

        # Extract length ratio metrics (from LengthAnomalyValidator)
        if "length_ratio" in metadata or "check_type" in metadata:
            ratio = metadata.get("ratio")
            if ratio and isinstance(ratio, (int, float)):
                self._length_ratios.append(float(ratio))

        # Track segments checked
        segments_checked = metadata.get("segments_checked", 0)
        if segments_checked > 0:
            self.metrics.segments_checked = max(self.metrics.segments_checked, segments_checked)

    def _track_validator_rejections(self, result: Any) -> None:
        """
        Track validation rejections by validator name.

        Args:
            result: ValidationResult to extract validator info from
        """
        if not hasattr(result, 'issues'):
            return

        # Import severity constants here to avoid circular imports
        try:
            from src.translation_engine.validation.base import ValidationSeverity
            ERROR_SEVERITY = ValidationSeverity.ERROR
            WARNING_SEVERITY = ValidationSeverity.WARNING
        except ImportError:
            # Fallback to string comparison if import fails
            ERROR_SEVERITY = "error"
            WARNING_SEVERITY = "warning"

        # Count issues by validator
        for issue in result.issues:
            validator_name = issue.validator if hasattr(issue, 'validator') else "unknown"
            if validator_name not in self._validator_results:
                self._validator_results[validator_name] = {
                    "errors": 0,
                    "warnings": 0,
                    "total": 0,
                }

            # Count by severity
            severity = issue.severity if hasattr(issue, 'severity') else None
            if severity == ERROR_SEVERITY or (isinstance(severity, str) and severity.lower() == "error"):
                self._validator_results[validator_name]["errors"] += 1
            elif severity == WARNING_SEVERITY or (isinstance(severity, str) and severity.lower() == "warning"):
                self._validator_results[validator_name]["warnings"] += 1

            self._validator_results[validator_name]["total"] += 1

    def add_repetition_metrics(
        self,
        repetition_count: int,
        max_ngram_freq: int,
    ) -> None:
        """
        Directly add repetition metrics (for cases where validation doesn't capture them).

        Args:
            repetition_count: Number of repetition issues detected
            max_ngram_freq: Maximum n-gram frequency found
        """
        self.metrics.repetition_detected_count += repetition_count
        self.metrics.max_ngram_frequency = max(
            self.metrics.max_ngram_frequency, max_ngram_freq
        )

    def add_length_ratio(self, ratio: float) -> None:
        """
        Add a length ratio measurement.

        Args:
            ratio: Length ratio (translation_length / source_length)
        """
        if isinstance(ratio, (int, float)):
            self._length_ratios.append(float(ratio))

    def get_metrics(self) -> QualityMetrics:
        """
        Get aggregated quality metrics.

        Returns:
            QualityMetrics dataclass with aggregated values
        """
        # Calculate mean and max length ratios
        if self._length_ratios:
            self.metrics.length_ratio_mean = sum(self._length_ratios) / len(self._length_ratios)
            self.metrics.length_ratio_max = max(self._length_ratios)

        # Build validation rejection breakdown
        # Include only validators with issues (errors)
        rejection_breakdown = {}
        for validator_name, stats in self._validator_results.items():
            if stats["errors"] > 0:
                rejection_breakdown[validator_name] = stats["errors"]

        self.metrics.validation_rejection_by_validator = rejection_breakdown

        return self.metrics

    def reset(self) -> None:
        """Reset aggregator for new run."""
        self.metrics = QualityMetrics()
        self._length_ratios = []
        self._validator_results = {}

    def get_summary_string(self) -> str:
        """
        Get human-readable summary of metrics.

        Returns:
            Formatted string summarizing quality metrics
        """
        metrics = self.get_metrics()

        length_mean_str = f"{metrics.length_ratio_mean:.3f}" if metrics.length_ratio_mean is not None else "N/A"
        length_max_str = f"{metrics.length_ratio_max:.3f}" if metrics.length_ratio_max is not None else "N/A"

        lines = [
            "Quality Metrics Summary",
            "=" * 50,
            f"Repetition Issues: {metrics.repetition_detected_count}",
            f"Max N-gram Frequency: {metrics.max_ngram_frequency}",
            f"Length Ratio (Mean): {length_mean_str}",
            f"Length Ratio (Max): {length_max_str}",
            f"Total Segments Checked: {metrics.segments_checked}",
            f"Total Validation Issues: {metrics.total_validation_issues} (Errors: {metrics.error_count}, Warnings: {metrics.warning_count})",
        ]

        if metrics.validation_rejection_by_validator:
            lines.append("")
            lines.append("Validation Rejections by Validator:")
            for validator_name, count in sorted(
                metrics.validation_rejection_by_validator.items(),
                key=lambda x: x[1],
                reverse=True,
            ):
                lines.append(f"  {validator_name}: {count}")

        return "\n".join(lines)
