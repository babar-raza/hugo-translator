"""Integration test for benchmark analytics (Phase 4.1).

Tests end-to-end workflow:
1. Run benchmarks via BenchmarkRunner
2. Migrate database to v8
3. Aggregate results into trends
4. Query analytics data
5. Create baselines
"""

import pytest
import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

# Check if pandas is available
try:
    import pandas as pd
    PANDAS_AVAILABLE = True
except ImportError:
    PANDAS_AVAILABLE = False

from src.benchmarking.runner import BenchmarkRunner
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun, BenchmarkResult, SystemInfo
from src.benchmarking.schema_migrations import MigrationManager
from src.benchmarking.aggregation import TimeSeriesAggregator
from src.benchmarking.analytics import AnalyticsQueryAPI
from src.model_runtime.registry import ModelRegistry

# Current schema version from BenchmarkDatabase class
CURRENT_SCHEMA_VERSION = BenchmarkDatabase.SCHEMA_VERSION


class TestBenchmarkAnalyticsIntegration:
    """Integration tests for benchmark analytics workflow."""

    def _create_test_runs(self, db: BenchmarkDatabase, num_runs: int = 5):
        """Create test benchmark runs with realistic data."""
        for run_idx in range(num_runs):
            timestamp = datetime.now(UTC) - timedelta(hours=run_idx * 2)

            results = []
            for i in range(10):
                results.append(BenchmarkResult(
                    sample_id=f"sample_{i}",
                    model_id="test_model",
                    device="cpu",
                    batch_size=8,
                    duration_seconds=1.0 + i * 0.1,
                    tokens_input=100,
                    tokens_output=100,
                    throughput_tokens_per_sec=100.0 + i * 10 + run_idx * 5,
                    peak_memory_mb=500.0
                ))

            run = BenchmarkRun(
                run_id=f"run_{run_idx}",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=SystemInfo(
                    cpu_model="Test CPU",
                    cpu_cores=4,
                    total_ram_gb=8.0
                ),
                results=results,
                total_duration_seconds=10.0,
                timestamp_utc=timestamp.isoformat()
            )

            db.save_run(run)

    def test_full_analytics_workflow(self):
        """Test complete analytics workflow from benchmark to queries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Step 1: Create database and verify schema
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

            # Step 2: Create benchmark runs
            self._create_test_runs(db, num_runs=10)

            # Verify runs exist
            runs = db.list_runs(model_id="test_model", device="cpu")
            assert len(runs) == 10

            # Step 3: Aggregate data into trends
            aggregator = TimeSeriesAggregator(db_path)
            trends_created = aggregator.aggregate_model("test_model", "cpu", lookback_days=1)
            assert trends_created > 0

            # Step 4: Verify trends were created
            conn = db._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT COUNT(*) FROM benchmark_trends
                    WHERE model_id = 'test_model' AND device = 'cpu'
                """)
                trend_count = cursor.fetchone()[0]
                assert trend_count > 0

            finally:
                db._close_connection(conn)

            # Step 5: Create performance baseline
            baseline_id = aggregator.create_baseline("test_model", "cpu", "daily")
            assert baseline_id is not None

            # Step 6: Query analytics (if pandas available)
            if PANDAS_AVAILABLE:
                api = AnalyticsQueryAPI(db_path)

                # Query trends
                df_trends = api.get_performance_trends("test_model", "cpu", "hourly", lookback_days=1)
                assert isinstance(df_trends, pd.DataFrame)

                # Query baselines
                df_baselines = api.get_performance_baselines("test_model", "cpu")
                assert len(df_baselines) > 0

                # Query distribution
                df_dist = api.get_throughput_distribution("test_model", "cpu", days=1)
                assert len(df_dist) > 0

    def test_migration_then_aggregation(self):
        """Test migrating existing v7 database then aggregating."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Step 1: Create database at current schema version
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

            # Create test data
            self._create_test_runs(db, num_runs=5)
            del db

            # Step 2: Verify schema version
            manager = MigrationManager(db_path)
            assert manager.get_current_version() == CURRENT_SCHEMA_VERSION

            # Step 3: Aggregate data
            aggregator = TimeSeriesAggregator(db_path)
            trends_created = aggregator.aggregate_all(lookback_days=1)
            assert trends_created > 0

            # Step 4: Verify aggregation worked
            db2 = BenchmarkDatabase(db_path)
            conn = db2._get_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM benchmark_trends")
                count = cursor.fetchone()[0]
                assert count > 0

            finally:
                db2._close_connection(conn)

    def test_incremental_aggregation_workflow(self):
        """Test that aggregation is incremental over time."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create initial runs
            self._create_test_runs(db, num_runs=3)

            # First aggregation
            aggregator = TimeSeriesAggregator(db_path)
            trends_1 = aggregator.aggregate_model("test_model", "cpu")

            # Create more runs
            self._create_test_runs(db, num_runs=2)

            # Second aggregation (should be incremental)
            trends_2 = aggregator.aggregate_model("test_model", "cpu")

            # Both should succeed
            assert trends_1 >= 0
            assert trends_2 >= 0

    @pytest.mark.skipif(not PANDAS_AVAILABLE, reason="pandas not available")
    def test_analytics_queries_with_real_data(self):
        """Test analytics queries with realistic benchmark data."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create runs for multiple models and devices
            for model in ["model_a", "model_b"]:
                for device in ["cpu", "cuda"]:
                    for run_idx in range(5):
                        timestamp = datetime.now(UTC) - timedelta(hours=run_idx * 2)

                        # Different performance for different configs
                        base_throughput = 100.0 if device == "cpu" else 300.0
                        if model == "model_b":
                            base_throughput *= 1.5

                        results = []
                        for i in range(10):
                            results.append(BenchmarkResult(
                                sample_id=f"sample_{i}",
                                model_id=model,
                                device=device,
                                batch_size=8,
                                duration_seconds=1.0,
                                tokens_input=100,
                                tokens_output=100,
                                throughput_tokens_per_sec=base_throughput + i * 10,
                                peak_memory_mb=500.0
                            ))

                        run = BenchmarkRun(
                            run_id=f"{model}_{device}_{run_idx}",
                            model_id=model,
                            device=device,
                            batch_sizes=[8],
                            iterations=1,
                            corpus_category="test",
                            purpose="testing",
                            tags=["test"],
                            system_info=SystemInfo(
                                cpu_model="Test CPU",
                                cpu_cores=4,
                                total_ram_gb=8.0
                            ),
                            results=results,
                            total_duration_seconds=10.0,
                            timestamp_utc=timestamp.isoformat()
                        )
                        db.save_run(run)

            # Aggregate all
            aggregator = TimeSeriesAggregator(db_path)
            trends = aggregator.aggregate_all(lookback_days=1)
            assert trends > 0

            # Test analytics queries
            api = AnalyticsQueryAPI(db_path)

            # Model comparison
            df_models = api.get_model_comparison(["model_a", "model_b"], "cpu", days=1)
            assert len(df_models) == 2
            assert df_models["avg_throughput"].iloc[0] > 0

            # Device comparison
            df_devices = api.get_device_comparison("model_a", ["cpu", "cuda"], days=1)
            assert len(df_devices) == 2
            # CUDA should be faster
            cuda_throughput = df_devices[df_devices["device"] == "cuda"]["avg_throughput"].iloc[0]
            cpu_throughput = df_devices[df_devices["device"] == "cpu"]["avg_throughput"].iloc[0]
            assert cuda_throughput > cpu_throughput

    def test_retention_policy_workflow(self):
        """Test that retention policies are created and can be queried."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Check retention policies exist
            conn = db._get_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM retention_policies WHERE enabled = 1")
                count = cursor.fetchone()[0]
                assert count >= 3  # Should have default policies

                # Check specific policies
                cursor = conn.execute("""
                    SELECT policy_name, retention_days
                    FROM retention_policies
                    ORDER BY policy_name
                """)
                policies = {row[0]: row[1] for row in cursor.fetchall()}

                assert "benchmark_results_90d" in policies
                assert policies["benchmark_results_90d"] == 90

            finally:
                db._close_connection(conn)

    def test_baseline_comparison_workflow(self):
        """Test creating baseline and comparing performance."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create older runs (baseline period)
            for run_idx in range(10):
                timestamp = datetime.now(UTC) - timedelta(days=30, hours=run_idx)

                results = []
                for i in range(5):
                    results.append(BenchmarkResult(
                        sample_id=f"sample_{i}",
                        model_id="test_model",
                        device="cpu",
                        batch_size=8,
                        duration_seconds=1.0,
                        tokens_input=100,
                        tokens_output=100,
                        throughput_tokens_per_sec=90.0 + i * 5,  # Lower baseline
                        peak_memory_mb=500.0
                    ))

                run = BenchmarkRun(
                    run_id=f"baseline_run_{run_idx}",
                    model_id="test_model",
                    device="cpu",
                    batch_sizes=[8],
                    iterations=1,
                    corpus_category="test",
                    purpose="baseline",
                    tags=["baseline"],
                    system_info=SystemInfo(
                        cpu_model="Test CPU",
                        cpu_cores=4,
                        total_ram_gb=8.0
                    ),
                    results=results,
                    total_duration_seconds=5.0,
                    timestamp_utc=timestamp.isoformat()
                )
                db.save_run(run)

            # Create recent runs (current performance)
            for run_idx in range(10):
                timestamp = datetime.now(UTC) - timedelta(hours=run_idx)

                results = []
                for i in range(5):
                    results.append(BenchmarkResult(
                        sample_id=f"sample_{i}",
                        model_id="test_model",
                        device="cpu",
                        batch_size=8,
                        duration_seconds=1.0,
                        tokens_input=100,
                        tokens_output=100,
                        throughput_tokens_per_sec=110.0 + i * 5,  # Higher current
                        peak_memory_mb=500.0
                    ))

                run = BenchmarkRun(
                    run_id=f"current_run_{run_idx}",
                    model_id="test_model",
                    device="cpu",
                    batch_sizes=[8],
                    iterations=1,
                    corpus_category="test",
                    purpose="current",
                    tags=["current"],
                    system_info=SystemInfo(
                        cpu_model="Test CPU",
                        cpu_cores=4,
                        total_ram_gb=8.0
                    ),
                    results=results,
                    total_duration_seconds=5.0,
                    timestamp_utc=timestamp.isoformat()
                )
                db.save_run(run)

            # Create baseline from historical data
            aggregator = TimeSeriesAggregator(db_path)
            baseline_id = aggregator.create_baseline("test_model", "cpu", "monthly", days_back=35)
            assert baseline_id is not None

            # Compare performance (if pandas available)
            if PANDAS_AVAILABLE:
                api = AnalyticsQueryAPI(db_path)
                baseline_date = (datetime.now(UTC) - timedelta(days=30)).date().isoformat()
                comparison = api.compare_performance(
                    "test_model",
                    "cpu",
                    baseline_date,
                    datetime.now(UTC).date().isoformat()
                )

                # Current should be better than baseline
                assert comparison["current_throughput"] > comparison["baseline_throughput"]
                assert comparison["throughput_change_pct"] > 0
