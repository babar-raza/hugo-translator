"""
Tests for SR-03: Fix segment accounting discrepancy.

Verifies that cache_hits + cache_misses = segments_done + segments_failed.
"""

import pytest
from src.observability.progress import ProgressTracker


def test_cache_operations_match_segment_total():
    """Verify cache_hits + cache_misses = segments_done + segments_failed (SR-03)."""
    tracker = ProgressTracker()
    tracker.start()

    # Simulate 100 cache hits
    for _ in range(100):
        tracker.cache_hit()
        tracker.segments_completed(1)

    # Simulate 50 cache misses (translated successfully)
    for _ in range(50):
        tracker.cache_miss()
    tracker.segments_completed(50)

    # Simulate 20 cache misses (translation failed)
    for _ in range(20):
        tracker.cache_miss()
    for _ in range(20):
        tracker.segment_failed()

    snapshot = tracker.get_snapshot()
    tracker.stop()

    # SR-03: cache_hits + cache_misses should equal segments_done + segments_failed
    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 100, "Expected 100 cache hits"
    assert snapshot.cache_misses == 70, "Expected 70 cache misses"
    assert snapshot.segments_done == 150, "Expected 150 successful segments"
    assert snapshot.segments_failed == 20, "Expected 20 failed segments"
    assert cache_total == segments_total, (
        f"Cache ops ({cache_total}) should equal segments processed ({segments_total})"
    )


def test_all_cache_hits_no_gap():
    """Verify accounting when all segments are cache hits (SR-03)."""
    tracker = ProgressTracker()
    tracker.start()

    # All cache hits
    for _ in range(1000):
        tracker.cache_hit()
        tracker.segments_completed(1)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 1000
    assert snapshot.cache_misses == 0
    assert snapshot.segments_done == 1000
    assert snapshot.segments_failed == 0
    assert cache_total == segments_total, "No gap should exist with all cache hits"


def test_all_cache_misses_success():
    """Verify accounting when all segments are cache misses that succeed (SR-03)."""
    tracker = ProgressTracker()
    tracker.start()

    # All cache misses, translated successfully
    for _ in range(500):
        tracker.cache_miss()
    tracker.segments_completed(500)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 0
    assert snapshot.cache_misses == 500
    assert snapshot.segments_done == 500
    assert snapshot.segments_failed == 0
    assert cache_total == segments_total, "No gap should exist when all translations succeed"


def test_batch_failure_accounted():
    """Verify failed batches are accounted in segment totals (SR-03)."""
    tracker = ProgressTracker()
    tracker.start()

    # 100 cache hits
    for _ in range(100):
        tracker.cache_hit()
        tracker.segments_completed(1)

    # 50 cache misses, batch fails
    for _ in range(50):
        tracker.cache_miss()
    # Batch translation failed - mark segments as failed
    for _ in range(50):
        tracker.segment_failed()

    snapshot = tracker.get_snapshot()
    tracker.stop()

    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 100
    assert snapshot.cache_misses == 50
    assert snapshot.segments_done == 100
    assert snapshot.segments_failed == 50
    assert cache_total == 150
    assert segments_total == 150
    assert cache_total == segments_total, (
        "Failed batch segments must be counted to prevent accounting gap"
    )


def test_mixed_success_failure_batches():
    """Verify accounting with multiple batches, some succeed and some fail (SR-03)."""
    tracker = ProgressTracker()
    tracker.start()

    # Batch 1: 100 cache hits
    for _ in range(100):
        tracker.cache_hit()
        tracker.segments_completed(1)

    # Batch 2: 30 cache misses, succeeds
    for _ in range(30):
        tracker.cache_miss()
    tracker.segments_completed(30)

    # Batch 3: 20 cache misses, fails
    for _ in range(20):
        tracker.cache_miss()
    for _ in range(20):
        tracker.segment_failed()

    # Batch 4: 50 cache misses, succeeds
    for _ in range(50):
        tracker.cache_miss()
    tracker.segments_completed(50)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 100
    assert snapshot.cache_misses == 100  # 30 + 20 + 50
    assert snapshot.segments_done == 180  # 100 (hits) + 30 + 50
    assert snapshot.segments_failed == 20
    assert cache_total == 200
    assert segments_total == 200
    assert cache_total == segments_total, "Accounting should be correct with mixed outcomes"


def test_no_gap_regression():
    """Verify the production bug (7,045 segment gap) is fixed (SR-03)."""
    tracker = ProgressTracker()
    tracker.start()

    # Simulate production scenario that caused the gap:
    # 174,667 cache hits
    for _ in range(174_667):
        tracker.cache_hit()
        tracker.segments_completed(1)

    # 10,658 cache misses translated successfully
    for _ in range(10_658):
        tracker.cache_miss()
    tracker.segments_completed(10_658)

    # 7,045 cache misses in batches that failed (this was the gap!)
    for _ in range(7_045):
        tracker.cache_miss()
    # SR-03 fix: now we track these as failed instead of losing them
    for _ in range(7_045):
        tracker.segment_failed()

    snapshot = tracker.get_snapshot()
    tracker.stop()

    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 174_667
    assert snapshot.cache_misses == 17_703  # 10,658 + 7,045
    assert cache_total == 192_370  # Matches production cache ops
    assert segments_total == 192_370, (
        f"SR-03 regression: expected {cache_total} segments but got {segments_total}"
    )
