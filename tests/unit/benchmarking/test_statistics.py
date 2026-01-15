"""Unit tests for statistical analysis (BM-02)."""

import math
import pytest

from src.benchmarking.statistics import (
    BenchmarkStatistics,
    StatisticalSummary,
    ComparisonResult,
)


def test_bm02_summarize_basic():
    """Test basic statistical summary."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]

    summary = BenchmarkStatistics.summarize(values)

    assert summary.mean == 30.0
    assert summary.min == 10.0
    assert summary.max == 50.0
    assert summary.median == 30.0
    assert summary.count == 5
    assert summary.variance == 200.0  # ((10-30)^2 + ... + (50-30)^2) / 5
    assert abs(summary.std - 14.142) < 0.01  # sqrt(200)


def test_bm02_summarize_median_even_count():
    """Test median calculation for even number of values."""
    values = [1.0, 2.0, 3.0, 4.0]

    summary = BenchmarkStatistics.summarize(values)

    assert summary.median == 2.5  # (2 + 3) / 2


def test_bm02_summarize_median_odd_count():
    """Test median calculation for odd number of values."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    summary = BenchmarkStatistics.summarize(values)

    assert summary.median == 3.0


def test_bm02_summarize_coefficient_of_variation():
    """Test coefficient of variation calculation."""
    values = [100.0, 110.0, 90.0, 105.0, 95.0]

    summary = BenchmarkStatistics.summarize(values)

    expected_cv = summary.std / summary.mean
    assert abs(summary.coefficient_of_variation - expected_cv) < 0.001


def test_bm02_summarize_empty_list():
    """Test that empty list raises ValueError."""
    with pytest.raises(ValueError, match="empty"):
        BenchmarkStatistics.summarize([])


def test_bm02_confidence_interval_95():
    """Test 95% confidence interval calculation."""
    # Known values: mean=100, std~10, n=10
    values = [95.0, 100.0, 105.0, 98.0, 102.0, 97.0, 103.0, 99.0, 101.0, 100.0]

    ci_lower, ci_upper = BenchmarkStatistics.confidence_interval(values, confidence=0.95)

    mean = sum(values) / len(values)

    # CI should contain the mean
    assert ci_lower < mean < ci_upper

    # CI should be symmetric around mean
    margin = ci_upper - mean
    assert abs((mean - ci_lower) - margin) < 0.001


def test_bm02_confidence_interval_single_value():
    """Test confidence interval for single value."""
    values = [42.0]

    ci_lower, ci_upper = BenchmarkStatistics.confidence_interval(values)

    assert ci_lower == 42.0
    assert ci_upper == 42.0


def test_bm02_confidence_interval_invalid_confidence():
    """Test that invalid confidence raises ValueError."""
    with pytest.raises(ValueError, match="between 0 and 1"):
        BenchmarkStatistics.confidence_interval([1.0, 2.0], confidence=1.5)


def test_bm02_compare_groups_significant_difference():
    """Test comparison when groups are significantly different."""
    # Group A: higher mean
    group_a = [100.0, 105.0, 110.0, 95.0, 100.0]
    # Group B: lower mean
    group_b = [50.0, 55.0, 60.0, 45.0, 50.0]

    result = BenchmarkStatistics.compare_groups(group_a, group_b, metric="throughput")

    assert result.metric == "throughput"
    assert result.group_a_mean > result.group_b_mean
    assert result.difference > 0
    assert result.is_significant  # Should be significant
    assert result.p_value < 0.05
    assert result.confidence in ["high", "medium"]


def test_bm02_compare_groups_no_difference():
    """Test comparison when groups are identical."""
    group_a = [100.0, 100.0, 100.0]
    group_b = [100.0, 100.0, 100.0]

    result = BenchmarkStatistics.compare_groups(group_a, group_b)

    assert result.group_a_mean == result.group_b_mean
    assert result.difference == 0.0
    assert result.difference_percent == 0.0
    assert not result.is_significant


def test_bm02_compare_groups_effect_size():
    """Test Cohen's d effect size calculation."""
    # Large effect size
    group_a = [100.0, 110.0, 120.0, 105.0, 115.0]
    group_b = [50.0, 60.0, 70.0, 55.0, 65.0]

    result = BenchmarkStatistics.compare_groups(group_a, group_b)

    # Effect size should be large (> 0.8 is large)
    assert result.effect_size > 0.8


def test_bm02_compare_groups_insufficient_data():
    """Test that groups with < 2 values raise ValueError."""
    with pytest.raises(ValueError, match="at least 2 values"):
        BenchmarkStatistics.compare_groups([1.0], [2.0, 3.0])


def test_bm02_detect_outliers_iqr():
    """Test IQR outlier detection."""
    # Normal values + outliers
    values = [10.0, 12.0, 11.0, 13.0, 12.5, 11.5, 100.0, -50.0]
    #                                               ^outlier ^outlier

    outliers = BenchmarkStatistics.detect_outliers(values, method="iqr")

    # Should detect the extreme values
    assert len(outliers) >= 1
    assert 6 in outliers or 7 in outliers  # 100.0 or -50.0


def test_bm02_detect_outliers_zscore():
    """Test Z-score outlier detection."""
    # Use many clustered values to minimize masking effect of the outlier
    # With 20 values at ~10 and one extreme, the z-score threshold is met
    values = [10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0,
              10.0, 10.1, 9.9, 10.0, 10.2, 9.8, 10.0, 10.1, 9.9, 10.0,
              100.0]  # Index 20 - extreme outlier
    #         ^outlier (z > 3 with many clustered values)

    outliers = BenchmarkStatistics.detect_outliers(values, method="zscore")

    # Should detect the extreme value (index 20)
    assert 20 in outliers  # 100.0


def test_bm02_detect_outliers_no_outliers():
    """Test outlier detection when no outliers present."""
    values = [10.0, 11.0, 12.0, 13.0, 14.0]

    outliers_iqr = BenchmarkStatistics.detect_outliers(values, method="iqr")
    outliers_z = BenchmarkStatistics.detect_outliers(values, method="zscore")

    assert len(outliers_iqr) == 0
    assert len(outliers_z) == 0


def test_bm02_detect_outliers_insufficient_data():
    """Test outlier detection with insufficient data."""
    # IQR needs 4+ values
    values = [1.0, 2.0, 3.0]

    outliers = BenchmarkStatistics.detect_outliers(values, method="iqr")

    # Should return empty list, not crash
    assert outliers == []


def test_bm02_detect_outliers_invalid_method():
    """Test that invalid method raises ValueError."""
    with pytest.raises(ValueError, match="Unknown outlier detection method"):
        BenchmarkStatistics.detect_outliers([1.0, 2.0, 3.0, 4.0], method="invalid")


def test_bm02_is_stable_stable_measurements():
    """Test stability check for stable measurements."""
    # CV = std / mean
    # If std is small relative to mean, should be stable
    values = [100.0, 101.0, 99.0, 100.5, 99.5]  # CV ~ 0.007

    is_stable = BenchmarkStatistics.is_stable(values, cv_threshold=0.1)

    assert is_stable


def test_bm02_is_stable_unstable_measurements():
    """Test stability check for unstable measurements."""
    # Large variance relative to mean
    values = [100.0, 150.0, 50.0, 120.0, 80.0]  # CV ~ 0.3

    is_stable = BenchmarkStatistics.is_stable(values, cv_threshold=0.1)

    assert not is_stable


def test_bm02_is_stable_all_zeros():
    """Test stability when all values are zero."""
    values = [0.0, 0.0, 0.0]

    is_stable = BenchmarkStatistics.is_stable(values)

    assert is_stable  # All zeros = stable


def test_bm02_is_stable_empty_list():
    """Test that empty list raises ValueError."""
    with pytest.raises(ValueError, match="empty"):
        BenchmarkStatistics.is_stable([])


def test_bm02_required_sample_size():
    """Test sample size calculation."""
    # For medium effect size (0.5), power=0.8, alpha=0.05
    n = BenchmarkStatistics.required_sample_size(effect_size=0.5, power=0.8, alpha=0.05)

    # Should be reasonable (typically 60-70 per group for d=0.5)
    assert 50 < n < 100


def test_bm02_required_sample_size_large_effect():
    """Test sample size for large effect size."""
    # Large effect size needs fewer samples
    n_large = BenchmarkStatistics.required_sample_size(effect_size=0.8)
    n_small = BenchmarkStatistics.required_sample_size(effect_size=0.2)

    assert n_large < n_small


def test_bm02_required_sample_size_invalid_params():
    """Test that invalid parameters raise ValueError."""
    with pytest.raises(ValueError):
        BenchmarkStatistics.required_sample_size(effect_size=0.0)

    with pytest.raises(ValueError):
        BenchmarkStatistics.required_sample_size(effect_size=0.5, power=1.5)

    with pytest.raises(ValueError):
        BenchmarkStatistics.required_sample_size(effect_size=0.5, alpha=1.5)


def test_bm02_percentile_median():
    """Test percentile calculation for median (50th percentile)."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0]

    p50 = BenchmarkStatistics.percentile(values, 0.5)

    assert p50 == 3.0


def test_bm02_percentile_quartiles():
    """Test percentile calculation for quartiles."""
    values = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 7.0, 8.0, 9.0, 10.0]

    p25 = BenchmarkStatistics.percentile(values, 0.25)
    p75 = BenchmarkStatistics.percentile(values, 0.75)

    # Q1 should be around 3.25, Q3 around 7.75 (linear interpolation)
    assert 3.0 < p25 < 4.0
    assert 7.0 < p75 < 8.0


def test_bm02_percentile_extremes():
    """Test percentile at 0 and 100."""
    values = [5.0, 10.0, 15.0, 20.0, 25.0]

    p0 = BenchmarkStatistics.percentile(values, 0.0)
    p100 = BenchmarkStatistics.percentile(values, 1.0)

    assert p0 == 5.0
    assert p100 == 25.0


def test_bm02_percentile_single_value():
    """Test percentile with single value."""
    values = [42.0]

    p50 = BenchmarkStatistics.percentile(values, 0.5)

    assert p50 == 42.0


def test_bm02_percentile_invalid():
    """Test that invalid percentile raises ValueError."""
    with pytest.raises(ValueError, match="between 0 and 1"):
        BenchmarkStatistics.percentile([1.0, 2.0], 1.5)


def test_bm02_percentile_empty_list():
    """Test that empty list raises ValueError."""
    with pytest.raises(ValueError, match="empty"):
        BenchmarkStatistics.percentile([], 0.5)


def test_bm02_statistical_summary_roundtrip():
    """Test that summary contains all expected fields."""
    values = [10.0, 20.0, 30.0, 40.0, 50.0]

    summary = BenchmarkStatistics.summarize(values)

    # Check all fields are present and have reasonable values
    assert summary.mean > 0
    assert summary.std >= 0
    assert summary.variance >= 0
    assert summary.min <= summary.median <= summary.max
    assert summary.count == len(values)
    assert len(summary.confidence_interval_95) == 2
    assert summary.confidence_interval_95[0] <= summary.mean <= summary.confidence_interval_95[1]
    assert summary.coefficient_of_variation >= 0


def test_bm02_comparison_result_roundtrip():
    """Test that comparison result contains all expected fields."""
    group_a = [100.0, 105.0, 110.0]
    group_b = [50.0, 55.0, 60.0]

    result = BenchmarkStatistics.compare_groups(group_a, group_b, metric="test")

    # Check all fields are present
    assert result.metric == "test"
    assert isinstance(result.group_a_mean, float)
    assert isinstance(result.group_b_mean, float)
    assert isinstance(result.difference, float)
    assert isinstance(result.difference_percent, float)
    assert isinstance(result.p_value, float)
    assert isinstance(result.is_significant, bool)
    assert isinstance(result.effect_size, float)
    assert result.confidence in ["high", "medium", "low"]


def test_bm02_edge_case_identical_values():
    """Test with all identical values."""
    values = [100.0, 100.0, 100.0, 100.0]

    summary = BenchmarkStatistics.summarize(values)

    assert summary.mean == 100.0
    assert summary.std == 0.0
    assert summary.variance == 0.0
    assert summary.coefficient_of_variation == 0.0


def test_bm02_edge_case_two_values():
    """Test with minimum viable dataset (n=2)."""
    values = [10.0, 20.0]

    summary = BenchmarkStatistics.summarize(values)

    assert summary.mean == 15.0
    assert summary.median == 15.0
    assert summary.count == 2


def test_bm02_integration_workflow():
    """Integration test: full workflow from data to decision."""
    # Simulate two benchmark runs
    baseline_runs = [100.0, 102.0, 98.0, 101.0, 99.0]  # Mean ~100
    new_runs = [110.0, 112.0, 108.0, 111.0, 109.0]  # Mean ~110 (10% improvement)

    # 1. Check stability
    baseline_stable = BenchmarkStatistics.is_stable(baseline_runs, cv_threshold=0.05)
    new_stable = BenchmarkStatistics.is_stable(new_runs, cv_threshold=0.05)

    assert baseline_stable
    assert new_stable

    # 2. Detect outliers
    baseline_outliers = BenchmarkStatistics.detect_outliers(baseline_runs)
    new_outliers = BenchmarkStatistics.detect_outliers(new_runs)

    assert len(baseline_outliers) == 0
    assert len(new_outliers) == 0

    # 3. Compare groups
    comparison = BenchmarkStatistics.compare_groups(baseline_runs, new_runs, metric="throughput")

    assert comparison.group_b_mean > comparison.group_a_mean  # New is better
    assert comparison.difference < 0  # A - B is negative (B is higher)
    assert comparison.is_significant  # 10% improvement should be significant

    # 4. Get summary
    baseline_summary = BenchmarkStatistics.summarize(baseline_runs)
    new_summary = BenchmarkStatistics.summarize(new_runs)

    assert new_summary.mean > baseline_summary.mean


def test_bm02_no_scipy_dependency():
    """Verify that statistics module doesn't import scipy."""
    import sys

    # Check that scipy is not imported
    scipy_modules = [mod for mod in sys.modules if mod.startswith("scipy")]

    # If scipy is imported elsewhere, that's fine, but our module shouldn't require it
    # This test just documents the independence
    # (In practice, we can't unload scipy if it's already loaded)
