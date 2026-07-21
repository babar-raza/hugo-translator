"""
Regression tests for batch size recovery (Concern #10 fix).

These tests ensure that batch size can increase after being reduced,
preventing the integer rounding bug where int(4 * 1.10) = 4 (no increase).

The fix uses math.ceil + max(current+1, ...) to guarantee at least +1 increase.
"""

import json
import math

import pytest


class TestBatchSizeRecoveryFormula:
    """
    Tests for the batch size increase formula.

    These tests verify the mathematical logic of the fix without
    requiring full BatchStatsTracker instantiation.
    """

    def test_small_batch_increases_by_at_least_one(self):
        """
        Verify that small batch sizes increase by at least 1.

        BUG (before fix): int(4 * 1.10) = int(4.4) = 4 (no increase)
        FIX: max(current+1, ceil(current*factor)) = max(5, 5) = 5
        """
        current_size = 4
        increase_factor = 1.10

        # Calculate expected new size using the fixed formula
        proportional_increase = math.ceil(current_size * increase_factor)
        new_size = max(current_size + 1, proportional_increase)

        # Verify increase happened
        assert new_size > current_size, (
            f"Batch size should increase from {current_size} to at least {current_size + 1}"
        )
        assert new_size == 5, f"Expected 5, got {new_size}"

    @pytest.mark.parametrize(
        "current,expected_min",
        [
            (1, 2),  # 1 * 1.10 = 1.1 -> ceil=2, max(2,2)=2
            (2, 3),  # 2 * 1.10 = 2.2 -> ceil=3, max(3,3)=3
            (3, 4),  # 3 * 1.10 = 3.3 -> ceil=4, max(4,4)=4
            (4, 5),  # 4 * 1.10 = 4.4 -> ceil=5, max(5,5)=5
            (5, 6),  # 5 * 1.10 = 5.5 -> ceil=6, max(6,6)=6
            (9, 10),  # 9 * 1.10 = 9.9 -> ceil=10, max(10,10)=10
            (10, 11),  # 10 * 1.10 = 11.0 -> ceil=11, max(11,11)=11
        ],
    )
    def test_batch_size_increases_for_various_sizes(self, current, expected_min):
        """Verify batch size increases correctly for various starting sizes."""
        increase_factor = 1.10
        proportional_increase = math.ceil(current * increase_factor)
        new_size = max(current + 1, proportional_increase)

        assert new_size >= expected_min, (
            f"From {current}: expected at least {expected_min}, got {new_size}"
        )
        assert new_size > current, f"Batch size must increase from {current}"

    def test_old_buggy_formula_would_fail(self):
        """
        Demonstrate that the old formula (int truncation) would fail.

        This test documents the bug that was fixed.
        """
        current_size = 4
        increase_factor = 1.10

        # OLD (buggy) formula
        old_new_size = int(current_size * increase_factor)

        # NEW (fixed) formula
        proportional_increase = math.ceil(current_size * increase_factor)
        new_new_size = max(current_size + 1, proportional_increase)

        # Old formula would NOT increase
        assert old_new_size == current_size, "Old formula should have no increase (this is the bug)"

        # New formula DOES increase
        assert new_new_size > current_size, "New formula should increase"

    def test_batch_capped_at_baseline(self):
        """Verify batch size doesn't exceed baseline."""
        baseline = 10
        current_size = 9
        increase_factor = 1.10

        proportional_increase = math.ceil(current_size * increase_factor)
        new_size_uncapped = max(current_size + 1, proportional_increase)
        new_size = min(baseline, new_size_uncapped)

        assert new_size <= baseline, f"Batch size {new_size} should not exceed baseline {baseline}"

    @pytest.mark.parametrize(
        "current,baseline,expected",
        [
            (4, 11, 5),  # 4 -> 5, under baseline
            (10, 11, 11),  # 10 -> 11, at baseline
            (11, 11, 11),  # 11 -> 11, already at baseline
            (8, 8, 8),  # 8 -> 8, already at baseline
        ],
    )
    def test_baseline_capping_scenarios(self, current, baseline, expected):
        """Test various baseline capping scenarios."""
        increase_factor = 1.10
        proportional_increase = math.ceil(current * increase_factor)
        new_size_uncapped = max(current + 1, proportional_increase)
        new_size = min(baseline, new_size_uncapped)

        # Only increase if under baseline
        if current < baseline:
            assert new_size > current or new_size == baseline, "Should increase or be at baseline"
        assert new_size <= baseline, "Should not exceed baseline"


class TestBatchFormulaEdgeCases:
    """Edge case tests for the batch increase formula."""

    def test_minimum_batch_size_one(self):
        """Batch size 1 should increase to 2."""
        current = 1
        increase_factor = 1.10
        proportional = math.ceil(current * increase_factor)
        new_size = max(current + 1, proportional)
        assert new_size == 2, f"Size 1 should increase to 2, got {new_size}"

    def test_large_batch_size(self):
        """Large batch sizes should still work correctly."""
        current = 100
        increase_factor = 1.10
        proportional = math.ceil(current * increase_factor)
        new_size = max(current + 1, proportional)
        # 100 * 1.10 = 110.00000000000001 (floating point), so ceil = 111
        # The key assertion is that it increases
        assert new_size > current, f"Size {current} should increase"
        assert new_size >= 101, f"Size should be at least 101, got {new_size}"

    def test_increase_factor_variations(self):
        """Different increase factors should work."""
        current = 4

        # 5% increase: ceil(4*1.05) = ceil(4.2) = 5, max(5,5) = 5
        factor_5 = 1.05
        new_5 = max(current + 1, math.ceil(current * factor_5))
        assert new_5 == 5

        # 20% increase: ceil(4*1.20) = ceil(4.8) = 5, max(5,5) = 5
        factor_20 = 1.20
        new_20 = max(current + 1, math.ceil(current * factor_20))
        assert new_20 == 5

        # 50% increase: ceil(4*1.50) = ceil(6.0) = 6, max(5,6) = 6
        factor_50 = 1.50
        new_50 = max(current + 1, math.ceil(current * factor_50))
        assert new_50 == 6


class TestBatchSizeGrowsPastColdStartBaseline:
    """
    Regression test for the 2026-07-16 baseline-vs-max_size ceiling bug.

    BatchStatsTracker.update_language_stats() previously capped the INCREASE
    path at `baseline` (the cold-start value assigned once when a language's
    tracker entry is first created, e.g. 8 for Cyrillic) instead of `max_size`
    (the configured ceiling, e.g. 20-25). Since `baseline` is never revised
    upward, this silently pinned every language at its cold-start batch size
    forever, regardless of how many thousands of successful batches it ran —
    confirmed live in production (.translation_progress/batch_stats.json,
    2026-07-16): 27/27 tracked languages stuck exactly at baseline after up
    to 9,022 batches each. These tests exercise the real
    BatchStatsTracker.update_language_stats() method end-to-end (unlike the
    formula-only tests above, which reimplement the arithmetic standalone
    and would pass identically whether the bug were present or not).
    """

    def _make_tracker(self, tmp_path, max_batch_size=20, initial_batch_size=8):
        from src.translation_engine.extractor.batch_stats_tracker import BatchStatsTracker

        config = {
            "enabled": True,
            "fallback_rate_threshold": 0.05,
            "reduction_factor": 0.80,
            "increase_factor": 1.10,
            "min_batches_before_increase": 5,
            "stats_file": str(tmp_path / "batch_stats.json"),
            "stats_retention_days": 30,
            "rolling_window_size": 50,
            "language_overrides": {
                "bg": {
                    "initial_batch_size": initial_batch_size,
                    "min_batch_size": 4,
                    "max_batch_size": max_batch_size,
                },
            },
        }
        return BatchStatsTracker(config)

    def _run_successful_batches(self, tracker, lang, n, batch_size):
        for _ in range(n):
            tracker.record_batch_result(
                language=lang, batch_size=batch_size, success=True, fallback_reason=None
            )

    def test_batch_size_grows_past_cold_start_baseline(self, tmp_path):
        """Sustained success must be able to grow batch size past baseline,
        up to max_size -- this is the exact scenario the bug prevented."""
        tracker = self._make_tracker(tmp_path, max_batch_size=20, initial_batch_size=8)

        assert tracker.get_batch_size("bg") == 8  # cold-start baseline

        # Repeatedly rack up 5 consecutive successes and adapt, simulating
        # many healthy translation batches over time (as happened live).
        for _ in range(15):
            self._run_successful_batches(tracker, "bg", 5, tracker.get_batch_size("bg"))
            tracker.update_language_stats("bg")

        final_size = tracker.get_batch_size("bg")
        assert final_size > 8, (
            f"Batch size should grow past cold-start baseline (8) after sustained "
            f"success, got stuck at {final_size} -- this is the bug being regression-tested"
        )
        assert final_size == 20, f"Should reach configured max_size (20), got {final_size}"

    def test_batch_size_does_not_exceed_max_size(self, tmp_path):
        """Growth must still respect the configured ceiling -- the fix must
        not remove the cap entirely, only correct which field it caps at."""
        tracker = self._make_tracker(tmp_path, max_batch_size=20, initial_batch_size=8)

        for _ in range(30):
            self._run_successful_batches(tracker, "bg", 5, tracker.get_batch_size("bg"))
            tracker.update_language_stats("bg")

        assert tracker.get_batch_size("bg") <= 20, "Must never exceed configured max_batch_size"

    def test_reduce_path_unaffected_by_fix(self, tmp_path):
        """The REDUCE path (high fallback rate) must still work exactly as
        before -- this fix only touches the INCREASE ceiling."""
        tracker = self._make_tracker(tmp_path, max_batch_size=20, initial_batch_size=8)

        for i in range(10):
            success = i < 3  # mostly failures -> high fallback rate
            tracker.record_batch_result(
                language="bg", batch_size=8, success=success,
                fallback_reason=None if success else "language_purity",
            )
        tracker.update_language_stats("bg")

        assert tracker.get_batch_size("bg") < 8, "High fallback rate should still reduce batch size"


class TestConcurrentProcessSaveNoClobber:
    """
    Regression test for the 2026-07-16 concurrent-save clobbering bug,
    found while verifying the baseline/max_size fix in live production.

    Multiple OS processes (one per heal/shard job) share one
    batch_stats.json file, each with its own in-memory BatchStatsTracker
    loaded once at startup. The old save() wrote self.languages verbatim,
    so a process that never touched language X (but loaded a stale copy
    of it at startup) would silently revert X's batch size to that stale
    value the next time it saved -- confirmed live: 'fi' is processed by
    both unified_shard_5 and review_latin_m2m; despite 3,974 consecutive
    successes, current_batch_size never moved off baseline.
    """

    def _make_tracker(self, stats_file, max_batch_size=20):
        from src.translation_engine.extractor.batch_stats_tracker import BatchStatsTracker

        config = {
            "enabled": True,
            "fallback_rate_threshold": 0.05,
            "reduction_factor": 0.80,
            "increase_factor": 1.10,
            "min_batches_before_increase": 5,
            "stats_file": str(stats_file),
            "language_overrides": {
                "fi": {"initial_batch_size": 8, "min_batch_size": 4, "max_batch_size": max_batch_size},
            },
        }
        return BatchStatsTracker(config)

    def test_second_process_stale_copy_does_not_revert_first_process_growth(self, tmp_path):
        """Simulates the exact live scenario: process A grows 'fi' and
        saves; process B, which never touched 'fi' but loaded a stale copy
        at startup, must NOT revert it when B saves."""
        stats_file = tmp_path / "batch_stats.json"

        # Process A: owns 'fi', grows it, saves.
        proc_a = self._make_tracker(stats_file)
        for _ in range(10):
            for _ in range(5):
                proc_a.record_batch_result("fi", proc_a.get_batch_size("fi"), success=True)
            proc_a.update_language_stats("fi")
        proc_a.save()
        grown_size = proc_a.get_batch_size("fi")
        assert grown_size > 8, "sanity check: process A should have grown past baseline"

        # Process B: starts fresh, loads A's on-disk state (including grown
        # 'fi'), but never touches 'fi' itself -- it works on a different
        # language entirely. Its in-memory 'fi' copy is a snapshot from load().
        proc_b = self._make_tracker(stats_file)
        proc_b.load()
        for _ in range(10):
            proc_b.record_batch_result("de", 20, success=True)
        proc_b.save()

        # Re-read from disk: 'fi' must still reflect A's growth, not B's
        # untouched (but present-in-memory) stale snapshot.
        with open(stats_file, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["languages"]["fi"]["current_batch_size"] == grown_size, (
            "Process B saving must not revert 'fi' to the stale value it loaded "
            "but never modified -- this is the exact bug that kept every "
            "dual-owned language pinned at baseline in production"
        )

    def test_dirty_language_from_this_process_always_wins_on_its_own_save(self, tmp_path):
        """A process's own updates to a language it owns must always be
        reflected in its own save, regardless of what's on disk."""
        stats_file = tmp_path / "batch_stats.json"

        proc_a = self._make_tracker(stats_file)
        proc_a.record_batch_result("fi", 8, success=True)
        proc_a.save()

        # Someone else writes a completely different snapshot in between.
        with open(stats_file, "w", encoding="utf-8") as f:
            json.dump({"version": "1.0", "languages": {"fi": {"current_batch_size": 999,
                       "baseline_batch_size": 8, "rolling_stats": {"total_batches": 0,
                       "successful_batches": 0, "fallback_batches": 0, "ema_fallback_rate": 0.0},
                       "consecutive_successes": 0, "consecutive_purity_failures": 0}}}, f)

        for _ in range(4):
            proc_a.record_batch_result("fi", 8, success=True)
        proc_a.save()

        with open(stats_file, encoding="utf-8") as f:
            on_disk = json.load(f)
        assert on_disk["languages"]["fi"]["current_batch_size"] != 999, (
            "Process A owns 'fi' (dirty) -- its own save must win over an "
            "unrelated external snapshot for a language it actively modified"
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
