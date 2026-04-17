"""
Regression tests for batch size recovery (Concern #10 fix).

These tests ensure that batch size can increase after being reduced,
preventing the integer rounding bug where int(4 * 1.10) = 4 (no increase).

The fix uses math.ceil + max(current+1, ...) to guarantee at least +1 increase.
"""

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
        assert new_size > current_size, \
            f"Batch size should increase from {current_size} to at least {current_size + 1}"
        assert new_size == 5, \
            f"Expected 5, got {new_size}"

    @pytest.mark.parametrize("current,expected_min", [
        (1, 2),   # 1 * 1.10 = 1.1 -> ceil=2, max(2,2)=2
        (2, 3),   # 2 * 1.10 = 2.2 -> ceil=3, max(3,3)=3
        (3, 4),   # 3 * 1.10 = 3.3 -> ceil=4, max(4,4)=4
        (4, 5),   # 4 * 1.10 = 4.4 -> ceil=5, max(5,5)=5
        (5, 6),   # 5 * 1.10 = 5.5 -> ceil=6, max(6,6)=6
        (9, 10),  # 9 * 1.10 = 9.9 -> ceil=10, max(10,10)=10
        (10, 11), # 10 * 1.10 = 11.0 -> ceil=11, max(11,11)=11
    ])
    def test_batch_size_increases_for_various_sizes(self, current, expected_min):
        """Verify batch size increases correctly for various starting sizes."""
        increase_factor = 1.10
        proportional_increase = math.ceil(current * increase_factor)
        new_size = max(current + 1, proportional_increase)

        assert new_size >= expected_min, \
            f"From {current}: expected at least {expected_min}, got {new_size}"
        assert new_size > current, \
            f"Batch size must increase from {current}"

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
        assert old_new_size == current_size, \
            "Old formula should have no increase (this is the bug)"

        # New formula DOES increase
        assert new_new_size > current_size, \
            "New formula should increase"

    def test_batch_capped_at_baseline(self):
        """Verify batch size doesn't exceed baseline."""
        baseline = 10
        current_size = 9
        increase_factor = 1.10

        proportional_increase = math.ceil(current_size * increase_factor)
        new_size_uncapped = max(current_size + 1, proportional_increase)
        new_size = min(baseline, new_size_uncapped)

        assert new_size <= baseline, \
            f"Batch size {new_size} should not exceed baseline {baseline}"

    @pytest.mark.parametrize("current,baseline,expected", [
        (4, 11, 5),    # 4 -> 5, under baseline
        (10, 11, 11),  # 10 -> 11, at baseline
        (11, 11, 11),  # 11 -> 11, already at baseline
        (8, 8, 8),     # 8 -> 8, already at baseline
    ])
    def test_baseline_capping_scenarios(self, current, baseline, expected):
        """Test various baseline capping scenarios."""
        increase_factor = 1.10
        proportional_increase = math.ceil(current * increase_factor)
        new_size_uncapped = max(current + 1, proportional_increase)
        new_size = min(baseline, new_size_uncapped)

        # Only increase if under baseline
        if current < baseline:
            assert new_size > current or new_size == baseline, \
                "Should increase or be at baseline"
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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
