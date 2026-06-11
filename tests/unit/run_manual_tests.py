"""
Manual test runner for SR test files (when pytest not available).
Runs basic smoke tests to verify core functionality.
"""

import sys

sys.path.insert(0, ".")

from src.observability.progress import ProgressSnapshot, ProgressTracker


def test_error_count_zero_on_all_success():
    """SR-01: Verify error count is 0 when all files succeed."""
    tracker = ProgressTracker()
    tracker.start()

    # Simulate 63 successful files
    for i in range(63):
        tracker.file_started(f"file_{i}.md")
        tracker.file_completed(success=True)

    snapshot = tracker.get_snapshot()
    tracker.stop()

    assert snapshot.files_done == 63, f"Expected 63 done, got {snapshot.files_done}"
    assert snapshot.files_failed == 0, f"Expected 0 failed, got {snapshot.files_failed}"
    assert snapshot.error_count == 0, f"Expected 0 errors, got {snapshot.error_count}"
    print("[PASS] test_error_count_zero_on_all_success")


def test_cache_operations_match_segment_total():
    """SR-03: Verify cache_hits + cache_misses = segments_done + segments_failed."""
    tracker = ProgressTracker()
    tracker.start()

    # 100 cache hits
    for _ in range(100):
        tracker.cache_hit()
        tracker.segments_completed(1)

    # 50 cache misses (successful)
    for _ in range(50):
        tracker.cache_miss()
    tracker.segments_completed(50)

    # 20 cache misses (failed)
    for _ in range(20):
        tracker.cache_miss()
    for _ in range(20):
        tracker.segment_failed()

    snapshot = tracker.get_snapshot()
    tracker.stop()

    cache_total = snapshot.cache_hits + snapshot.cache_misses
    segments_total = snapshot.segments_done + snapshot.segments_failed

    assert snapshot.cache_hits == 100, f"Expected 100 hits, got {snapshot.cache_hits}"
    assert snapshot.cache_misses == 70, f"Expected 70 misses, got {snapshot.cache_misses}"
    assert snapshot.segments_done == 150, f"Expected 150 done, got {snapshot.segments_done}"
    assert snapshot.segments_failed == 20, f"Expected 20 failed, got {snapshot.segments_failed}"
    assert cache_total == segments_total, (
        f"Cache ops ({cache_total}) != segments ({segments_total})"
    )
    print("[PASS] test_cache_operations_match_segment_total")


def test_segments_failed_infrastructure():
    """SR-05: Verify segments_failed field exists and works."""
    # Test ProgressSnapshot dataclass
    snapshot = ProgressSnapshot(timestamp=0, start_time=0, elapsed_s=0)
    assert hasattr(snapshot, "segments_failed"), "segments_failed field missing"
    assert snapshot.segments_failed == 0, f"Expected 0, got {snapshot.segments_failed}"

    # Test ProgressTracker
    tracker = ProgressTracker()
    tracker.start()
    tracker.segment_failed()
    snap = tracker.get_snapshot()
    assert snap.segments_failed == 1, f"Expected 1, got {snap.segments_failed}"
    tracker.stop()

    print("[PASS] test_segments_failed_infrastructure")


if __name__ == "__main__":
    print("Running manual smoke tests...")
    print()

    try:
        test_error_count_zero_on_all_success()
        test_cache_operations_match_segment_total()
        test_segments_failed_infrastructure()
        print()
        print("=" * 60)
        print("All manual tests PASSED (3/3)")
        print("=" * 60)
    except AssertionError as e:
        print(f"\n[FAIL] TEST FAILED: {e}")
        sys.exit(1)
    except Exception as e:
        print(f"\n[ERROR] {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
