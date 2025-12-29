"""
Tests for SR-02: Ensure all counted errors produce ERROR-level logs.

Verifies that every call to record_error() produces a corresponding ERROR log entry.
"""

import logging
import pytest
from src.observability.progress import ProgressTracker


def test_error_counted_emits_error_log(caplog):
    """Verify ERROR log emitted when error counted (SR-02)."""
    caplog.set_level(logging.ERROR)

    tracker = ProgressTracker()
    tracker.start()

    # Record an error
    tracker.record_error("test_error", "Test error message", "test_file.md")

    # Verify ERROR log was emitted
    error_logs = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(error_logs) == 1, "Expected exactly 1 ERROR log for 1 recorded error"

    log_message = error_logs[0].message
    assert "Error #1 recorded" in log_message
    assert "test_error" in log_message
    assert "Test error message" in log_message
    assert "test_file.md" in log_message

    tracker.stop()


def test_multiple_errors_produce_multiple_logs(caplog):
    """Verify each error produces its own ERROR log (SR-02)."""
    caplog.set_level(logging.ERROR)

    tracker = ProgressTracker()
    tracker.start()

    # Record multiple errors
    tracker.record_error("error_type_1", "First error", "file1.md")
    tracker.record_error("error_type_2", "Second error", "file2.md")
    tracker.record_error("error_type_3", "Third error", "file3.md")

    # Verify ERROR logs match error count
    error_logs = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(error_logs) == 3, "Expected 3 ERROR logs for 3 recorded errors"

    # Verify error numbers increment
    assert "Error #1" in error_logs[0].message
    assert "Error #2" in error_logs[1].message
    assert "Error #3" in error_logs[2].message

    tracker.stop()


def test_error_log_without_file_path(caplog):
    """Verify ERROR log works when file_path is empty (SR-02)."""
    caplog.set_level(logging.ERROR)

    tracker = ProgressTracker()
    tracker.start()

    # Record error without file path
    tracker.record_error("model_error", "Model failed", "")

    # Verify ERROR log was emitted with "no file context"
    error_logs = [record for record in caplog.records if record.levelno == logging.ERROR]
    assert len(error_logs) == 1

    log_message = error_logs[0].message
    assert "Error #1 recorded" in log_message
    assert "model_error" in log_message
    assert "no file context" in log_message

    tracker.stop()


def test_final_error_count_matches_log_count(caplog):
    """Verify final error count equals number of ERROR logs (SR-02)."""
    caplog.set_level(logging.ERROR)

    tracker = ProgressTracker()
    tracker.start()

    # Record 5 errors
    for i in range(5):
        tracker.record_error(f"error_{i}", f"Error {i}", f"file_{i}.md")

    # Get final snapshot
    snapshot = tracker.get_snapshot()

    # Count ERROR logs from record_error (exclude other ERROR logs)
    error_logs = [
        record for record in caplog.records
        if record.levelno == logging.ERROR and "Error #" in record.message
    ]

    assert snapshot.error_count == 5, "Expected error_count = 5"
    assert len(error_logs) == 5, "Expected 5 ERROR logs"

    tracker.stop()
