"""
Tests for SR-01: Fix error counter logic in progress tracker.

Verifies that error count matches actual file failures, not intermediate errors
that get recovered (e.g., one language fails but other languages succeed).
"""

import logging
import pytest
from src.observability.progress import ProgressTracker


def test_error_count_zero_on_all_success():
    """Verify error count is 0 when all files succeed (SR-01)."""
    tracker = ProgressTracker()
    tracker.start()

    # Simulate 63 successful files (matching production scenario)
    for i in range(63):
        tracker.file_started(f"file_{i}.md")
        tracker.file_completed(success=True)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    # SR-01: If all files succeed, error count MUST be 0
    assert snapshot.files_done == 63, "Expected 63 successful files"
    assert snapshot.files_failed == 0, "Expected 0 failed files"
    assert snapshot.error_count == 0, f"Expected 0 errors but got {snapshot.error_count}"


def test_error_count_matches_failures():
    """Verify error count equals actual failure count (SR-01)."""
    tracker = ProgressTracker()
    tracker.start()

    # 7 successful files
    for i in range(7):
        tracker.file_started(f"success_{i}.md")
        tracker.file_completed(success=True)

    # 3 failed files with errors
    for i in range(3):
        tracker.file_started(f"failed_{i}.md")
        tracker.record_error("translation_error", f"Failed {i}", f"failed_{i}.md")
        tracker.file_completed(success=False)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    # SR-01: Error count must match failure count (3 failures = 3 errors)
    assert snapshot.files_done == 7, "Expected 7 successful files"
    assert snapshot.files_failed == 3, "Expected 3 failed files"
    assert snapshot.error_count == 3, f"Expected 3 errors but got {snapshot.error_count}"


def test_retries_that_succeed_have_zero_errors():
    """Verify retries that eventually succeed don't count as errors (SR-01)."""
    tracker = ProgressTracker()
    tracker.start()

    # Simulate file with retries that eventually succeeds
    tracker.file_started("retried.md")
    tracker.add_retry()  # Retry 1
    tracker.add_retry()  # Retry 2
    tracker.file_completed(success=True)  # But ultimately succeeds

    snapshot = tracker.get_snapshot()
    tracker.stop()

    # SR-01: Retries that succeed should not count as errors
    assert snapshot.files_done == 1, "Expected 1 successful file"
    assert snapshot.files_failed == 0, "Expected 0 failed files"
    assert snapshot.retries == 2, "Expected 2 retries"
    assert snapshot.error_count == 0, f"Expected 0 errors but got {snapshot.error_count}"


def test_no_error_without_record_error_call():
    """Verify errors aren't auto-incremented on file_completed(success=False) (SR-01)."""
    tracker = ProgressTracker()
    tracker.start()

    # Fail a file WITHOUT calling record_error()
    # (This tests that file_completed doesn't auto-increment errors)
    tracker.file_started("failed.md")
    tracker.file_completed(success=False)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    # SR-01: Failing a file without record_error() should not increment error count
    # (Though in practice, record_error should always be called before file_completed(False))
    assert snapshot.files_failed == 1, "Expected 1 failed file"
    assert snapshot.error_count == 0, f"Expected 0 errors (no record_error called)"


def test_mixed_scenario_realistic():
    """Verify realistic scenario: mix of success, failure, retries (SR-01)."""
    tracker = ProgressTracker()
    tracker.start()

    # 50 files succeed without issues
    for i in range(50):
        tracker.file_started(f"success_{i}.md")
        tracker.file_completed(success=True)

    # 10 files succeed after retries (no errors)
    for i in range(10):
        tracker.file_started(f"retried_{i}.md")
        tracker.add_retry()
        tracker.file_completed(success=True)

    # 3 files fail with errors
    for i in range(3):
        tracker.file_started(f"failed_{i}.md")
        tracker.record_error("translation_error", f"Error {i}", f"failed_{i}.md")
        tracker.file_completed(success=False)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    # SR-01: Error count must equal failures, not successes or retries
    assert snapshot.files_done == 60, "Expected 60 successful files"
    assert snapshot.files_failed == 3, "Expected 3 failed files"
    assert snapshot.retries == 10, "Expected 10 retries"
    assert snapshot.error_count == 3, f"Expected 3 errors but got {snapshot.error_count}"
