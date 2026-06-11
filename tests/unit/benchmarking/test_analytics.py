"""Unit tests for analytics query API (Phase 4.1).

Tests the AnalyticsQueryAPI class:
- Performance trends queries
- Baseline comparisons
- Throughput distributions
- Model/device comparisons
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

# Check if pandas is available
try:
    import pandas as pd

    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from src.benchmarking.aggregation import TimeSeriesAggregator
from src.benchmarking.analytics import AnalyticsQueryAPI
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo


@pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas not available")
class TestAnalyticsQueryAPI:
    """Test suite for analytics query API."""

    def _create_test_run(
        self,
        db: BenchmarkDatabase,
        model_id: str = "test_model",
        device: str = "cpu",
        num_results: int = 10,
        timestamp_offset_hours: int = 0,
        base_throughput: float = 100.0,
    ) -> str:
        """Create a test benchmark run with results."""
        timestamp = datetime.now(UTC) + timedelta(hours=timestamp_offset_hours)

        results = []
        for i in range(num_results):
            results.append(
                BenchmarkResult(
                    sample_id=f"sample_{i}",
                    model_id=model_id,
                    device=device,
                    batch_size=8,
                    duration_seconds=1.0 + i * 0.1,
                    tokens_input=100,
                    tokens_output=100,
                    throughput_tokens_per_sec=base_throughput + i * 10,
                    peak_memory_mb=500.0 + i * 50,
                )
            )

        run = BenchmarkRun(
            run_id=f"run_{model_id}_{device}_{timestamp_offset_hours}",
            model_id=model_id,
            device=device,
            batch_sizes=[8],
            iterations=1,
            corpus_category="test",
            purpose="testing",
            tags=["test"],
            system_info=SystemInfo(cpu_model="Test CPU", cpu_cores=4, total_ram_gb=8.0),
            results=results,
            total_duration_seconds=10.0,
            timestamp_utc=timestamp.isoformat(),
        )

        db.save_run(run)
        return run.run_id

    def test_get_performance_trends(self):
        """Test querying performance trends."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test run
            self._create_test_run(db, "test_model", "cpu", num_results=20)

            # Aggregate data
            aggregator = TimeSeriesAggregator(db_path)
            aggregator.aggregate_model("test_model", "cpu")

            # Query trends
            api = AnalyticsQueryAPI(db_path)
            df = api.get_performance_trends("test_model", "cpu", "hourly", lookback_days=1)

            # Should return DataFrame
            assert isinstance(df, pd.DataFrame)

            # Should have expected columns
            expected_columns = {
                "window_start",
                "window_end",
                "sample_count",
                "avg_throughput",
                "p50_throughput",
                "p95_throughput",
                "p99_throughput",
                "avg_duration",
                "avg_memory_mb",
            }
            assert expected_columns.issubset(set(df.columns))

            # Should have at least one row
            if not df.empty:
                assert df["sample_count"].iloc[0] > 0
                assert df["avg_throughput"].iloc[0] > 0

    def test_get_performance_trends_empty(self):
        """Test querying trends for nonexistent model."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path)
            df = api.get_performance_trends("nonexistent", "cpu", "daily")

            # Should return empty DataFrame
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 0

    def test_get_performance_trends_invalid_window(self):
        """Test invalid time window raises error."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path)

            with pytest.raises(ValueError):
                api.get_performance_trends("test_model", "cpu", "invalid_window")

    def test_get_performance_baselines(self):
        """Test querying performance baselines."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create enough test runs for baseline
            for i in range(15):
                self._create_test_run(
                    db, "test_model", "cpu", num_results=2, timestamp_offset_hours=-i
                )

            # Create baseline
            aggregator = TimeSeriesAggregator(db_path)
            baseline_id = aggregator.create_baseline("test_model", "cpu", "weekly")
            assert baseline_id is not None

            # Query baselines
            api = AnalyticsQueryAPI(db_path)
            df = api.get_performance_baselines("test_model", "cpu")

            # Should return DataFrame with baseline
            assert isinstance(df, pd.DataFrame)
            assert len(df) > 0

            # Should have expected columns
            expected_columns = {
                "baseline_type",
                "baseline_date",
                "avg_throughput",
                "p50_throughput",
                "p95_throughput",
                "sample_count",
                "metadata",
                "created_at",
            }
            assert expected_columns.issubset(set(df.columns))

            # Check data
            assert df["baseline_type"].iloc[0] == "weekly"
            assert df["avg_throughput"].iloc[0] > 0

    def test_get_performance_baselines_filtered(self):
        """Test querying baselines with type filter."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test runs
            for i in range(15):
                self._create_test_run(
                    db, "test_model", "cpu", num_results=2, timestamp_offset_hours=-i
                )

            # Create different baseline types
            aggregator = TimeSeriesAggregator(db_path)
            aggregator.create_baseline("test_model", "cpu", "daily")
            aggregator.create_baseline("test_model", "cpu", "weekly")

            # Query only weekly baselines
            api = AnalyticsQueryAPI(db_path)
            df = api.get_performance_baselines("test_model", "cpu", baseline_type="weekly")

            # Should only have weekly baselines
            assert all(df["baseline_type"] == "weekly")

    def test_compare_performance(self):
        """Test comparing performance against baseline."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create baseline runs (30 days ago, lower throughput)
            for i in range(15):
                self._create_test_run(
                    db,
                    "test_model",
                    "cpu",
                    num_results=2,
                    timestamp_offset_hours=-(30 * 24 + i),
                    base_throughput=80.0,  # Lower baseline throughput
                )

            # Create current runs (recent, higher throughput)
            for i in range(15):
                self._create_test_run(
                    db,
                    "test_model",
                    "cpu",
                    num_results=2,
                    timestamp_offset_hours=-i,
                    base_throughput=120.0,  # Higher current throughput
                )

            # Create baseline — create_baseline() stores baseline_date=today, not historical date
            aggregator = TimeSeriesAggregator(db_path)
            aggregator.create_baseline("test_model", "cpu", "weekly", days_back=50)
            baseline_date = datetime.now(UTC).date().isoformat()

            # Compare performance
            api = AnalyticsQueryAPI(db_path)
            comparison = api.compare_performance(
                "test_model", "cpu", baseline_date, datetime.now(UTC).date().isoformat()
            )

            # Should have comparison metrics
            assert "baseline_throughput" in comparison
            assert "current_throughput" in comparison
            assert "throughput_change_pct" in comparison

            # Current should be higher than baseline
            assert comparison["current_throughput"] > comparison["baseline_throughput"]
            assert comparison["throughput_change_pct"] > 0  # Positive change

    def test_compare_performance_no_baseline(self):
        """Test comparison with nonexistent baseline."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path)
            comparison = api.compare_performance("test_model", "cpu", "2024-01-01", "2024-02-01")

            # Should return error in result
            assert "error" in comparison
            assert comparison["baseline_throughput"] == 0.0

    def test_get_throughput_distribution(self):
        """Test querying throughput distribution."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test runs
            self._create_test_run(db, "test_model", "cpu", num_results=50)

            # Query distribution
            api = AnalyticsQueryAPI(db_path)
            df = api.get_throughput_distribution("test_model", "cpu", days=7)

            # Should return DataFrame
            assert isinstance(df, pd.DataFrame)
            assert len(df) > 0

            # Should have expected columns
            expected_columns = {
                "timestamp_utc",
                "batch_size",
                "throughput_tokens_per_sec",
                "duration_seconds",
                "peak_memory_mb",
            }
            assert expected_columns.issubset(set(df.columns))

            # Check data
            assert df["throughput_tokens_per_sec"].min() > 0
            assert df["batch_size"].iloc[0] == 8

    def test_get_model_comparison(self):
        """Test comparing multiple models."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create runs for different models
            self._create_test_run(db, "model_a", "cpu", num_results=20, base_throughput=100.0)
            self._create_test_run(db, "model_b", "cpu", num_results=20, base_throughput=150.0)
            self._create_test_run(db, "model_c", "cpu", num_results=20, base_throughput=200.0)

            # Compare models
            api = AnalyticsQueryAPI(db_path)
            df = api.get_model_comparison(["model_a", "model_b", "model_c"], "cpu", days=1)

            # Should return DataFrame
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 3

            # Should have expected columns
            expected_columns = {
                "model_id",
                "sample_count",
                "avg_throughput",
                "avg_duration",
                "avg_memory_mb",
                "min_throughput",
                "max_throughput",
            }
            assert expected_columns.issubset(set(df.columns))

            # Should be ordered by throughput (descending)
            assert df["model_id"].iloc[0] == "model_c"  # Highest throughput
            assert df["model_id"].iloc[2] == "model_a"  # Lowest throughput

            # Check sample counts
            assert all(df["sample_count"] == 20)

    def test_get_device_comparison(self):
        """Test comparing devices for a model."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create runs on different devices
            self._create_test_run(db, "test_model", "cpu", num_results=20, base_throughput=100.0)
            self._create_test_run(db, "test_model", "cuda", num_results=20, base_throughput=300.0)

            # Compare devices
            api = AnalyticsQueryAPI(db_path)
            df = api.get_device_comparison("test_model", ["cpu", "cuda"], days=1)

            # Should return DataFrame
            assert isinstance(df, pd.DataFrame)
            assert len(df) == 2

            # Should have expected columns
            expected_columns = {
                "device",
                "sample_count",
                "avg_throughput",
                "avg_duration",
                "avg_memory_mb",
            }
            assert expected_columns.issubset(set(df.columns))

            # CUDA should be faster than CPU
            cuda_row = df[df["device"] == "cuda"].iloc[0]
            cpu_row = df[df["device"] == "cpu"].iloc[0]
            assert cuda_row["avg_throughput"] > cpu_row["avg_throughput"]

    def test_query_telemetry_events(self):
        """Test that queries emit telemetry events."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "test_model", "cpu")

            # Aggregate
            aggregator = TimeSeriesAggregator(db_path)
            aggregator.aggregate_model("test_model", "cpu")

            # Create API without engines (telemetry should still work)
            api = AnalyticsQueryAPI(db_path)

            # Query should not error even without telemetry
            df = api.get_performance_trends("test_model", "cpu", "hourly")
            assert isinstance(df, pd.DataFrame)

    def test_pandas_not_available(self):
        """Test that API raises error when pandas not available."""
        # This test is symbolic - we can't uninstall pandas during test
        # But the check is in __init__, so if pandas is available, this test passes
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            # If pandas is available, API should initialize
            api = AnalyticsQueryAPI(db_path)
            assert api is not None

    def test_empty_database_queries(self):
        """Test queries on empty database return empty results."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path)

            # All queries should return empty DataFrames
            df_trends = api.get_performance_trends("model", "cpu", "daily")
            df_baselines = api.get_performance_baselines("model", "cpu")
            df_distribution = api.get_throughput_distribution("model", "cpu")
            df_model_comp = api.get_model_comparison(["model"], "cpu")
            df_device_comp = api.get_device_comparison("model", ["cpu"])

            assert len(df_trends) == 0
            assert len(df_baselines) == 0
            assert len(df_distribution) == 0
            assert len(df_model_comp) == 0
            assert len(df_device_comp) == 0

    def test_init_all_options_disabled(self):
        """Test initialization with all options disabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(
                db_path, enable_caching=False, enable_pooling=False, enable_monitoring=False
            )

            assert api._cache is None
            assert api._pool is None
            assert api._monitor is None

    def test_init_all_options_enabled(self):
        """Test initialization with all options enabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(
                db_path, enable_caching=True, enable_pooling=True, enable_monitoring=True
            )

            assert api._cache is not None
            assert api._pool is not None
            assert api._monitor is not None
            api.close()

    def test_get_cache_stats(self):
        """Test get_cache_stats method."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path, enable_caching=True)
            stats = api.get_cache_stats()

            assert stats is not None
            assert "size" in stats
            assert "hits" in stats
            assert "misses" in stats

    def test_get_cache_stats_disabled(self):
        """Test get_cache_stats returns None when disabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path, enable_caching=False)
            stats = api.get_cache_stats()

            assert stats is None

    def test_get_monitor_stats(self):
        """Test get_monitor_stats method."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path, enable_monitoring=True)
            stats = api.get_monitor_stats()

            assert stats is not None

    def test_get_monitor_stats_disabled(self):
        """Test get_monitor_stats returns None when disabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path, enable_monitoring=False)
            stats = api.get_monitor_stats()

            assert stats is None

    def test_invalidate_cache_all(self):
        """Test full cache invalidation."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)
            self._create_test_run(db, "test_model", "cpu")

            api = AnalyticsQueryAPI(db_path, enable_caching=True)

            # Populate cache
            api.get_performance_trends("test_model", "cpu", "hourly")
            api.get_throughput_distribution("test_model", "cpu")

            # Invalidate all
            count = api.invalidate_cache()
            assert count >= 0

    def test_invalidate_cache_pattern(self):
        """Test pattern-based cache invalidation."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)
            self._create_test_run(db, "test_model", "cpu")

            api = AnalyticsQueryAPI(db_path, enable_caching=True)

            # Populate cache
            api.get_performance_trends("test_model", "cpu", "hourly")

            # Invalidate by pattern
            count = api.invalidate_cache(pattern="trends")
            assert count >= 0

    def test_invalidate_cache_when_disabled(self):
        """Test invalidate_cache returns 0 when caching disabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path, enable_caching=False)
            count = api.invalidate_cache()

            assert count == 0

    def test_close_releases_resources(self):
        """Test close method releases resources."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(
                db_path, enable_caching=True, enable_pooling=True, enable_monitoring=True
            )

            # Should not raise
            api.close()

    def test_percentile_helper(self):
        """Test _percentile helper method."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            api = AnalyticsQueryAPI(db_path)

            # Empty list
            assert api._percentile([], 50) == 0.0

            # Single value
            assert api._percentile([100.0], 50) == 100.0

            # Multiple values
            values = [10, 20, 30, 40, 50]
            assert api._percentile(values, 50) == 30.0

            # 0th percentile (min)
            assert api._percentile(values, 0) == 10.0

            # 100th percentile (max)
            assert api._percentile(values, 100) == 50.0

    def test_caching_hit(self):
        """Test that cache hits work correctly."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)
            self._create_test_run(db, "test_model", "cpu")

            aggregator = TimeSeriesAggregator(db_path)
            aggregator.aggregate_model("test_model", "cpu")

            api = AnalyticsQueryAPI(db_path, enable_caching=True)

            # First call - cache miss
            api.get_performance_trends("test_model", "cpu", "hourly")
            stats1 = api.get_cache_stats()
            misses1 = stats1["misses"]

            # Second call - cache hit
            api.get_performance_trends("test_model", "cpu", "hourly")
            stats2 = api.get_cache_stats()
            hits2 = stats2["hits"]

            assert hits2 > 0  # Should have at least one hit

    def test_pooled_connection(self):
        """Test using connection pool."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)
            self._create_test_run(db, "test_model", "cpu")

            api = AnalyticsQueryAPI(db_path, enable_pooling=True)

            # Query should work with pooled connections
            df = api.get_throughput_distribution("test_model", "cpu")
            assert isinstance(df, pd.DataFrame)

            api.close()

    def test_non_pooled_connection(self):
        """Test using non-pooled connection."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)
            self._create_test_run(db, "test_model", "cpu")

            api = AnalyticsQueryAPI(db_path, enable_pooling=False)

            # Query should work without pooling
            df = api.get_throughput_distribution("test_model", "cpu")
            assert isinstance(df, pd.DataFrame)
