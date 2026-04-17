"""
Tests for SR-04: Add metrics validation to catch contradictions.

Verifies that contradictory metrics are detected and logged as warnings.
"""

import logging

from src.observability.progress import ProgressTracker


def test_validation_catches_error_contradiction(caplog):
    """Verify validation detects Success=N, Failed=0, Errors=N (SR-04)."""
    caplog.set_level(logging.WARNING)

    tracker = ProgressTracker()
    tracker.start()

    # Simulate the bug: 10 successful files, 0 failures, but 10 errors counted
    for i in range(10):
        tracker.file_started(f"file_{i}.md")
        # Incorrectly call record_error even though file succeeds
        tracker.record_error("spurious_error", f"Error {i}", f"file_{i}.md")
        tracker.file_completed(success=True)  # File succeeds despite error

    tracker.stop()

    # Check for validation warning
    validation_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING
        and "METRICS VALIDATION" in record.message
        and "CONTRADICTION" in record.message
    ]

    assert len(validation_warnings) > 0, "Expected CONTRADICTION warning"
    warning_msg = validation_warnings[0].message
    assert "0 failed files" in warning_msg
    assert "10 errors" in warning_msg


def test_validation_no_warnings_on_consistent_metrics(caplog):
    """Verify no warnings when metrics are consistent (SR-04)."""
    caplog.set_level(logging.WARNING)

    tracker = ProgressTracker()
    tracker.start()

    # 10 successful files, no errors
    for i in range(10):
        tracker.file_started(f"file_{i}.md")
        tracker.file_completed(success=True)

    tracker.stop()

    # Check that no METRICS VALIDATION warnings were logged
    validation_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING
        and "METRICS VALIDATION" in record.message
    ]

    assert len(validation_warnings) == 0, "Expected no validation warnings for consistent metrics"


def test_validation_allows_failures_with_matching_errors(caplog):
    """Verify validation accepts failures with matching error count (SR-04)."""
    caplog.set_level(logging.WARNING)

    tracker = ProgressTracker()
    tracker.start()

    # 7 successful files
    for i in range(7):
        tracker.file_started(f"success_{i}.md")
        tracker.file_completed(success=True)

    # 3 failed files with 3 errors (1:1 ratio is acceptable)
    for i in range(3):
        tracker.file_started(f"failed_{i}.md")
        tracker.record_error("translation_error", f"Failed {i}", f"failed_{i}.md")
        tracker.file_completed(success=False)

    tracker.stop()

    # Should not trigger CONTRADICTION warning (failures match errors)
    contradiction_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING
        and "METRICS VALIDATION" in record.message
        and "CONTRADICTION" in record.message
    ]

    assert len(contradiction_warnings) == 0, "Should not warn when errors match failures"


def test_validation_detects_segment_gap(caplog):
    """Verify validation detects segment accounting gap (SR-04, GAP-SR-03)."""
    caplog.set_level(logging.WARNING)

    tracker = ProgressTracker()
    tracker.start()

    # Simulate the segment gap: cache ops don't match segments processed
    # Record 10,000 cache hits
    for _ in range(100):
        tracker.add_cache_hit()

    # Record 2,000 cache misses
    for _ in range(20):
        tracker.add_cache_miss()

    # But only 5,000 segments completed (should be 12,000)
    tracker.segments_completed(5000, duration_s=1.0)

    tracker.stop()

    # Check for SEGMENT GAP warning
    segment_gap_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING
        and "METRICS VALIDATION" in record.message
        and "SEGMENT GAP" in record.message
    ]

    assert len(segment_gap_warnings) > 0, "Expected SEGMENT GAP warning"
    warning_msg = segment_gap_warnings[0].message
    assert "cache ops" in warning_msg
    assert "segments" in warning_msg


def test_validation_error_ratio_anomaly(caplog):
    """Verify validation detects when errors vastly exceed failures (SR-04)."""
    caplog.set_level(logging.WARNING)

    tracker = ProgressTracker()
    tracker.start()

    # 1 failed file but 10 errors (10:1 ratio triggers anomaly)
    tracker.file_started("failed.md")
    for i in range(10):
        tracker.record_error("multiple_errors", f"Error {i}", "failed.md")
    tracker.file_completed(success=False)

    tracker.stop()

    # Check for ANOMALY warning
    anomaly_warnings = [
        record for record in caplog.records
        if record.levelno == logging.WARNING
        and "METRICS VALIDATION" in record.message
        and "ANOMALY" in record.message
    ]

    assert len(anomaly_warnings) > 0, "Expected ANOMALY warning for high error ratio"
    warning_msg = anomaly_warnings[0].message
    assert "10 errors" in warning_msg
    assert "1 failures" in warning_msg
