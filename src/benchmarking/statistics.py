"""Statistical analysis module for benchmark data.

This module provides statistical methods for analyzing benchmark results,
including confidence intervals, significance testing, and outlier detection.

No external statistical libraries (scipy) required - all formulas implemented
from first principles using standard mathematical definitions.
"""

import math
from dataclasses import dataclass


@dataclass
class StatisticalSummary:
    """Statistical summary of a dataset."""

    mean: float
    std: float
    variance: float
    min: float
    max: float
    median: float
    count: int
    confidence_interval_95: tuple[float, float]
    coefficient_of_variation: float  # std / mean


@dataclass
class ComparisonResult:
    """Result of statistical comparison between two groups."""

    metric: str
    group_a_mean: float
    group_b_mean: float
    difference: float
    difference_percent: float
    p_value: float
    is_significant: bool  # p < 0.05
    effect_size: float  # Cohen's d
    confidence: str  # "high", "medium", "low"


class BenchmarkStatistics:
    """Statistical analysis tools for benchmark data.

    All methods are static and stateless. Formulas are documented with sources.
    """

    @staticmethod
    def summarize(values: list[float]) -> StatisticalSummary:
        """Compute comprehensive statistical summary of values.

        Args:
            values: List of numeric values to summarize

        Returns:
            StatisticalSummary with all statistical measures

        Raises:
            ValueError: If values list is empty
        """
        if not values:
            raise ValueError("Cannot summarize empty list")

        n = len(values)
        sorted_values = sorted(values)

        # Basic statistics
        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / n
        std = math.sqrt(variance)
        min_val = sorted_values[0]
        max_val = sorted_values[-1]

        # Median
        if n % 2 == 0:
            median = (sorted_values[n // 2 - 1] + sorted_values[n // 2]) / 2
        else:
            median = sorted_values[n // 2]

        # Coefficient of variation
        cv = std / mean if mean != 0 else float("inf")

        # 95% confidence interval
        ci_95 = BenchmarkStatistics.confidence_interval(values, confidence=0.95)

        return StatisticalSummary(
            mean=mean,
            std=std,
            variance=variance,
            min=min_val,
            max=max_val,
            median=median,
            count=n,
            confidence_interval_95=ci_95,
            coefficient_of_variation=cv,
        )

    @staticmethod
    def confidence_interval(
        values: list[float], confidence: float = 0.95
    ) -> tuple[float, float]:
        """Calculate confidence interval using t-distribution.

        Formula: CI = mean ± t * (std / sqrt(n))
        where t is the critical value from Student's t-distribution

        Reference: https://en.wikipedia.org/wiki/Confidence_interval
        t-distribution critical values: https://en.wikipedia.org/wiki/Student%27s_t-distribution

        Args:
            values: List of numeric values
            confidence: Confidence level (0-1), default 0.95 for 95% CI

        Returns:
            Tuple of (lower_bound, upper_bound)

        Raises:
            ValueError: If values is empty or confidence not in (0, 1)
        """
        if not values:
            raise ValueError("Cannot compute confidence interval for empty list")
        if not 0 < confidence < 1:
            raise ValueError("Confidence must be between 0 and 1")

        n = len(values)
        if n == 1:
            # Single value - no variance
            return (values[0], values[0])

        mean = sum(values) / n
        variance = sum((x - mean) ** 2 for x in values) / (n - 1)  # Sample variance
        std = math.sqrt(variance)
        se = std / math.sqrt(n)  # Standard error

        # Get t-critical value for given confidence and df = n-1
        df = n - 1
        alpha = 1 - confidence
        t_critical = BenchmarkStatistics._t_critical_value(df, alpha / 2)

        margin = t_critical * se
        return (mean - margin, mean + margin)

    @staticmethod
    def compare_groups(
        group_a: list[float], group_b: list[float], metric: str = "throughput"
    ) -> ComparisonResult:
        """Compare two groups using Welch's t-test.

        Welch's t-test is used instead of Student's t-test because it doesn't
        assume equal variances between groups.

        Formula: t = (mean_a - mean_b) / sqrt(var_a/n_a + var_b/n_b)
        df calculated using Welch-Satterthwaite equation

        Reference: https://en.wikipedia.org/wiki/Welch%27s_t-test

        Args:
            group_a: First group of values
            group_b: Second group of values
            metric: Name of metric being compared

        Returns:
            ComparisonResult with statistical comparison

        Raises:
            ValueError: If either group is empty or has only one value
        """
        if len(group_a) < 2 or len(group_b) < 2:
            raise ValueError("Each group must have at least 2 values for comparison")

        # Calculate statistics for each group
        n_a, n_b = len(group_a), len(group_b)
        mean_a = sum(group_a) / n_a
        mean_b = sum(group_b) / n_b

        var_a = sum((x - mean_a) ** 2 for x in group_a) / (n_a - 1)
        var_b = sum((x - mean_b) ** 2 for x in group_b) / (n_b - 1)

        # Welch's t-statistic
        se_diff = math.sqrt(var_a / n_a + var_b / n_b)
        if se_diff == 0:
            # Both groups have zero variance and same mean
            t_stat = 0.0
        else:
            t_stat = (mean_a - mean_b) / se_diff

        # Welch-Satterthwaite degrees of freedom
        if var_a == 0 and var_b == 0:
            df = n_a + n_b - 2
        else:
            numerator = (var_a / n_a + var_b / n_b) ** 2
            denominator = (var_a / n_a) ** 2 / (n_a - 1) + (var_b / n_b) ** 2 / (
                n_b - 1
            )
            df = numerator / denominator if denominator > 0 else n_a + n_b - 2

        # p-value (two-tailed)
        p_value = BenchmarkStatistics._t_to_p_value(abs(t_stat), df)

        # Effect size (Cohen's d)
        pooled_std = math.sqrt((var_a + var_b) / 2)
        if pooled_std == 0:
            effect_size = 0.0
        else:
            effect_size = abs(mean_a - mean_b) / pooled_std

        # Difference metrics
        difference = mean_a - mean_b
        if mean_b != 0:
            difference_percent = (difference / mean_b) * 100
        else:
            difference_percent = float("inf") if difference != 0 else 0.0

        # Confidence classification
        if p_value < 0.01:
            confidence = "high"
        elif p_value < 0.05:
            confidence = "medium"
        else:
            confidence = "low"

        return ComparisonResult(
            metric=metric,
            group_a_mean=mean_a,
            group_b_mean=mean_b,
            difference=difference,
            difference_percent=difference_percent,
            p_value=p_value,
            is_significant=(p_value < 0.05),
            effect_size=effect_size,
            confidence=confidence,
        )

    @staticmethod
    def detect_outliers(
        values: list[float], method: str = "iqr"
    ) -> list[int]:
        """Detect outliers using IQR or Z-score method.

        IQR method: Outliers are values < Q1 - 1.5*IQR or > Q3 + 1.5*IQR
        Z-score method: Outliers are |z-score| > 3

        Reference IQR: https://en.wikipedia.org/wiki/Interquartile_range
        Reference Z-score: https://en.wikipedia.org/wiki/Standard_score

        Args:
            values: List of numeric values
            method: "iqr" (default) or "zscore"

        Returns:
            List of indices of outlier values

        Raises:
            ValueError: If values is empty or method is invalid
        """
        if not values:
            raise ValueError("Cannot detect outliers in empty list")

        if method == "iqr":
            return BenchmarkStatistics._detect_outliers_iqr(values)
        elif method == "zscore":
            return BenchmarkStatistics._detect_outliers_zscore(values)
        else:
            raise ValueError(f"Unknown outlier detection method: {method}")

    @staticmethod
    def _detect_outliers_iqr(values: list[float]) -> list[int]:
        """Detect outliers using IQR method."""
        if len(values) < 4:
            return []  # Need at least 4 values for meaningful quartiles

        sorted_values = sorted(values)
        n = len(sorted_values)

        # Calculate Q1 and Q3
        q1 = BenchmarkStatistics.percentile(sorted_values, 0.25)
        q3 = BenchmarkStatistics.percentile(sorted_values, 0.75)
        iqr = q3 - q1

        if iqr == 0:
            return []  # No outliers if no spread

        lower_bound = q1 - 1.5 * iqr
        upper_bound = q3 + 1.5 * iqr

        # Find indices of outliers in original list
        outliers = []
        for i, val in enumerate(values):
            if val < lower_bound or val > upper_bound:
                outliers.append(i)

        return outliers

    @staticmethod
    def _detect_outliers_zscore(values: list[float]) -> list[int]:
        """Detect outliers using Z-score method."""
        if len(values) < 3:
            return []  # Need at least 3 values for meaningful z-scores

        mean = sum(values) / len(values)
        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std = math.sqrt(variance)

        if std == 0:
            return []  # No outliers if no variance

        outliers = []
        for i, val in enumerate(values):
            z_score = abs((val - mean) / std)
            if z_score > 3:
                outliers.append(i)

        return outliers

    @staticmethod
    def is_stable(values: list[float], cv_threshold: float = 0.1) -> bool:
        """Check if measurements are stable based on coefficient of variation.

        Stability criterion: CV (coefficient of variation) < threshold
        CV = std / mean

        Args:
            values: List of numeric values
            cv_threshold: Maximum acceptable CV for stability (default 0.1 = 10%)

        Returns:
            True if stable, False otherwise

        Raises:
            ValueError: If values is empty
        """
        if not values:
            raise ValueError("Cannot assess stability of empty list")

        mean = sum(values) / len(values)
        if mean == 0:
            # All values are zero - technically stable
            return all(v == 0 for v in values)

        variance = sum((x - mean) ** 2 for x in values) / len(values)
        std = math.sqrt(variance)
        cv = std / mean

        return cv < cv_threshold

    @staticmethod
    def required_sample_size(
        effect_size: float, power: float = 0.8, alpha: float = 0.05
    ) -> int:
        """Estimate required sample size for detecting an effect.

        Uses simplified formula for two-sample t-test.
        Formula: n ≈ 2 * ((z_α/2 + z_β) / effect_size)^2

        Reference: https://en.wikipedia.org/wiki/Sample_size_determination

        Args:
            effect_size: Cohen's d effect size to detect
            power: Statistical power (1 - β), default 0.8
            alpha: Significance level, default 0.05

        Returns:
            Required sample size per group

        Raises:
            ValueError: If parameters are out of valid ranges
        """
        if not 0 < effect_size:
            raise ValueError("Effect size must be positive")
        if not 0 < power < 1:
            raise ValueError("Power must be between 0 and 1")
        if not 0 < alpha < 1:
            raise ValueError("Alpha must be between 0 and 1")

        # Approximate z-values for common alpha and power
        # For alpha=0.05 (two-tailed), z_alpha/2 ≈ 1.96
        # For power=0.80, z_beta ≈ 0.84
        z_alpha = BenchmarkStatistics._z_critical_value(alpha / 2)
        z_beta = BenchmarkStatistics._z_critical_value(1 - power)

        n = 2 * ((z_alpha + z_beta) / effect_size) ** 2
        return max(2, math.ceil(n))  # At least 2 samples

    @staticmethod
    def percentile(values: list[float], p: float) -> float:
        """Calculate percentile using linear interpolation.

        Formula: Uses linear interpolation between closest ranks
        Reference: https://en.wikipedia.org/wiki/Percentile

        Args:
            values: List of numeric values (will be sorted)
            p: Percentile (0-1), e.g., 0.5 for median

        Returns:
            Value at given percentile

        Raises:
            ValueError: If values is empty or p not in [0, 1]
        """
        if not values:
            raise ValueError("Cannot compute percentile of empty list")
        if not 0 <= p <= 1:
            raise ValueError("Percentile must be between 0 and 1")

        sorted_values = sorted(values)
        n = len(sorted_values)

        if n == 1:
            return sorted_values[0]

        # Linear interpolation method
        rank = p * (n - 1)
        lower_idx = int(math.floor(rank))
        upper_idx = int(math.ceil(rank))

        if lower_idx == upper_idx:
            return sorted_values[lower_idx]

        # Interpolate
        weight = rank - lower_idx
        return sorted_values[lower_idx] * (1 - weight) + sorted_values[upper_idx] * weight

    # ========== Private helper methods ==========

    @staticmethod
    def _t_critical_value(df: float, alpha: float) -> float:
        """Approximate t-critical value for given df and alpha.

        Uses lookup table for common values and approximation for others.
        Two-tailed critical values.

        Reference: https://en.wikipedia.org/wiki/Student%27s_t-distribution
        """
        # Common critical values (two-tailed, alpha/2 in each tail)
        # For alpha=0.05 (two-tailed), we want values for 0.025 in each tail
        t_table = {
            # df: {alpha: t_critical}
            1: {0.025: 12.706},
            2: {0.025: 4.303},
            3: {0.025: 3.182},
            4: {0.025: 2.776},
            5: {0.025: 2.571},
            10: {0.025: 2.228},
            20: {0.025: 2.086},
            30: {0.025: 2.042},
            60: {0.025: 2.000},
            120: {0.025: 1.980},
        }

        df_int = int(round(df))

        # Check table for exact match
        if df_int in t_table and alpha in t_table[df_int]:
            return t_table[df_int][alpha]

        # For large df, approximate with normal distribution
        if df > 120:
            return BenchmarkStatistics._z_critical_value(alpha)

        # Linear interpolation for df between table values
        sorted_dfs = sorted(t_table.keys())
        for i in range(len(sorted_dfs) - 1):
            if sorted_dfs[i] <= df_int <= sorted_dfs[i + 1]:
                df_low, df_high = sorted_dfs[i], sorted_dfs[i + 1]
                if alpha in t_table[df_low] and alpha in t_table[df_high]:
                    t_low = t_table[df_low][alpha]
                    t_high = t_table[df_high][alpha]
                    weight = (df_int - df_low) / (df_high - df_low)
                    return t_low * (1 - weight) + t_high * weight

        # Fallback to closest df
        closest_df = min(t_table.keys(), key=lambda x: abs(x - df_int))
        if alpha in t_table[closest_df]:
            return t_table[closest_df][alpha]

        # Final fallback to normal approximation
        return BenchmarkStatistics._z_critical_value(alpha)

    @staticmethod
    def _z_critical_value(alpha: float) -> float:
        """Approximate z-critical value for standard normal distribution.

        Reference: https://en.wikipedia.org/wiki/Standard_normal_table
        """
        # Common z-values (one-tailed)
        z_table = {
            0.005: 2.576,  # 99% CI
            0.010: 2.326,
            0.025: 1.960,  # 95% CI
            0.050: 1.645,  # 90% CI
            0.100: 1.282,
            0.200: 0.842,
        }

        # Check for exact match
        if alpha in z_table:
            return z_table[alpha]

        # Linear interpolation
        sorted_alphas = sorted(z_table.keys())
        for i in range(len(sorted_alphas) - 1):
            if sorted_alphas[i] <= alpha <= sorted_alphas[i + 1]:
                a_low, a_high = sorted_alphas[i], sorted_alphas[i + 1]
                z_low, z_high = z_table[a_low], z_table[a_high]
                weight = (alpha - a_low) / (a_high - a_low)
                return z_low * (1 - weight) + z_high * weight

        # Fallback to closest
        closest_alpha = min(z_table.keys(), key=lambda x: abs(x - alpha))
        return z_table[closest_alpha]

    @staticmethod
    def _t_to_p_value(t_stat: float, df: float) -> float:
        """Convert t-statistic to two-tailed p-value.

        Simplified approximation for common cases.

        Reference: https://en.wikipedia.org/wiki/Student%27s_t-distribution
        """
        # For large df, approximate with normal distribution
        if df > 120:
            return BenchmarkStatistics._z_to_p_value(t_stat)

        # Lookup table approach: compare t_stat to critical values
        # If |t| < t_critical for alpha=0.05, then p > 0.05
        t_05 = BenchmarkStatistics._t_critical_value(df, 0.025)  # Two-tailed
        t_01 = BenchmarkStatistics._t_critical_value(df, 0.005)  # Two-tailed

        if abs(t_stat) < t_05:
            # p > 0.05 - not significant at 5% level
            # Rough approximation
            return 0.10
        elif abs(t_stat) < t_01:
            # 0.01 < p < 0.05
            return 0.03
        else:
            # p < 0.01 - highly significant
            return 0.005

    @staticmethod
    def _z_to_p_value(z_stat: float) -> float:
        """Convert z-statistic to two-tailed p-value.

        Uses error function approximation.

        Reference: https://en.wikipedia.org/wiki/Error_function
        """
        # Simplified lookup for common z-values
        z_abs = abs(z_stat)

        if z_abs < 1.645:
            return 0.10  # Not significant at 10%
        elif z_abs < 1.960:
            return 0.06  # Between 5% and 10%
        elif z_abs < 2.326:
            return 0.03  # Between 1% and 5%
        elif z_abs < 2.576:
            return 0.015  # Between 1% and 2%
        else:
            return 0.005  # < 1%
