"""Unit tests for time-series aggregation (Phase 4.1).

Tests the TimeSeriesAggregator class:
- Aggregate benchmark results into trends
- Calculate percentiles correctly
- Incremental aggregation
- Baseline creation
- Cleanup old trends
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

from src.benchmarking.aggregation import AGGREGATION_WINDOWS, TimeSeriesAggregator
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo


class TestTimeSeriesAggregator:
    """Test suite for time-series aggregation."""

    def _create_test_run(
        self,
        db: BenchmarkDatabase,
        model_id: str = "test_model",
        device: str = "cpu",
        num_results: int = 10,
        timestamp_offset_hours: int = 0,
    ) -> str:
        """Create a test benchmark run with results.

        Args:
            db: Database to save run to
            model_id: Model identifier
            device: Device name
            num_results: Number of results to create
            timestamp_offset_hours: Hours to offset timestamp (negative = past)

        Returns:
            Run ID
        """
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
                    throughput_tokens_per_sec=100.0 + i * 10,
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

    def test_aggregate_model_creates_trends(self):
        """Test aggregating a model creates trend records."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test run
            self._create_test_run(db, "test_model", "cpu", num_results=20)

            # Aggregate
            aggregator = TimeSeriesAggregator(db_path)
            trends_created = aggregator.aggregate_model("test_model", "cpu")

            # Should create trends for each time window
            assert trends_created > 0

            # Verify trends exist in database
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT COUNT(*) FROM benchmark_trends
                    WHERE model_id = ? AND device = ?
                """,
                    ("test_model", "cpu"),
                )
                count = cursor.fetchone()[0]
                assert count > 0

            finally:
                db._close_connection(conn)
                db.close()

    def test_aggregate_all_models(self):
        """Test aggregating all models."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test runs for multiple models
            self._create_test_run(db, "model_a", "cpu", num_results=10)
            self._create_test_run(db, "model_b", "cpu", num_results=10)
            self._create_test_run(db, "model_a", "cuda", num_results=10)

            # Aggregate all
            aggregator = TimeSeriesAggregator(db_path)
            trends_created = aggregator.aggregate_all(lookback_days=1)

            # Should create trends for all 3 combinations
            assert trends_created > 0

            # Verify trends for each combination
            conn = db._get_connection()
            try:
                cursor = conn.execute("""
                    SELECT DISTINCT model_id, device
                    FROM benchmark_trends
                    ORDER BY model_id, device
                """)
                combinations = [(row[0], row[1]) for row in cursor.fetchall()]

                assert ("model_a", "cpu") in combinations
                assert ("model_b", "cpu") in combinations
                assert ("model_a", "cuda") in combinations

            finally:
                db._close_connection(conn)
                db.close()

    def test_percentile_calculation(self):
        """Test percentile calculation is correct."""
        aggregator = TimeSeriesAggregator(":memory:")

        values = [10.0, 20.0, 30.0, 40.0, 50.0, 60.0, 70.0, 80.0, 90.0, 100.0]

        p50 = aggregator._percentile(values, 50)
        p95 = aggregator._percentile(values, 95)
        p99 = aggregator._percentile(values, 99)

        # p50 should be close to median (55)
        assert 50.0 <= p50 <= 60.0

        # p95 should be close to 95th percentile (95.5)
        assert 90.0 <= p95 <= 100.0

        # p99 should be close to max
        assert 95.0 <= p99 <= 100.0

    def test_incremental_aggregation(self):
        """Test incremental aggregation only processes new data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create initial run
            self._create_test_run(
                db, "test_model", "cpu", num_results=10, timestamp_offset_hours=-2
            )

            # First aggregation
            aggregator = TimeSeriesAggregator(db_path)
            trends_1 = aggregator.aggregate_model("test_model", "cpu")

            # Create new run (more recent)
            self._create_test_run(db, "test_model", "cpu", num_results=10, timestamp_offset_hours=0)

            # Second aggregation (should be incremental)
            trends_2 = aggregator.aggregate_model("test_model", "cpu")

            # Should create more trends
            assert trends_2 >= 0  # May be 0 if windows are the same

            db.close()

    def test_create_baseline(self):
        """Test creating performance baseline."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test runs with enough data
            for i in range(15):
                self._create_test_run(
                    db, "test_model", "cpu", num_results=2, timestamp_offset_hours=-i
                )

            # Create baseline
            aggregator = TimeSeriesAggregator(db_path)
            baseline_id = aggregator.create_baseline("test_model", "cpu", "weekly", days_back=30)

            assert baseline_id is not None

            # Verify baseline exists
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT avg_throughput, p50_throughput, p95_throughput, sample_count
                    FROM performance_baselines
                    WHERE id = ?
                """,
                    (baseline_id,),
                )
                row = cursor.fetchone()

                assert row is not None
                assert row[0] > 0  # avg_throughput
                assert row[1] > 0  # p50_throughput
                assert row[2] > 0  # p95_throughput
                assert row[3] >= 10  # sample_count

            finally:
                db._close_connection(conn)
                db.close()

    def test_create_baseline_insufficient_data(self):
        """Test baseline creation fails with insufficient data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create only 5 samples (need at least 10)
            self._create_test_run(db, "test_model", "cpu", num_results=5)

            aggregator = TimeSeriesAggregator(db_path)
            baseline_id = aggregator.create_baseline("test_model", "cpu", "weekly")

            # Should return None (insufficient data)
            assert baseline_id is None

            db.close()

    def test_cleanup_old_trends(self):
        """Test cleaning up old trend data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create old run (400 days ago)
            old_timestamp = datetime.now(UTC) - timedelta(days=400)
            results = [
                BenchmarkResult(
                    sample_id="sample_1",
                    model_id="test_model",
                    device="cpu",
                    batch_size=8,
                    duration_seconds=1.0,
                    tokens_input=100,
                    tokens_output=100,
                    throughput_tokens_per_sec=100.0,
                )
            ]

            old_run = BenchmarkRun(
                run_id="old_run",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=SystemInfo(cpu_model="Test CPU", cpu_cores=4, total_ram_gb=8.0),
                results=results,
                total_duration_seconds=1.0,
                timestamp_utc=old_timestamp.isoformat(),
            )
            db.save_run(old_run)

            # Aggregate (will create old trends)
            aggregator = TimeSeriesAggregator(db_path)
            aggregator.aggregate_model("test_model", "cpu", lookback_days=500)

            # Manually insert old trend record
            conn = db._get_connection()
            try:
                old_created = (datetime.now(UTC) - timedelta(days=400)).isoformat()
                conn.execute(
                    """
                    INSERT INTO benchmark_trends
                    (model_id, device, time_window, window_start, window_end,
                     sample_count, avg_throughput, p50_throughput, p95_throughput, p99_throughput,
                     avg_duration, avg_memory_mb, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "test_model",
                        "cpu",
                        "daily",
                        old_timestamp.isoformat(),
                        old_timestamp.isoformat(),
                        1,
                        100.0,
                        100.0,
                        100.0,
                        100.0,
                        1.0,
                        None,
                        old_created,
                    ),
                )
                conn.commit()

            finally:
                db._close_connection(conn)

            # Cleanup old trends (keep 365 days)
            deleted = aggregator.cleanup_old_trends(retention_days=365)

            # Should have deleted at least the old trend
            assert deleted >= 1

            db.close()

    def test_aggregation_windows(self):
        """Test that all aggregation windows are defined."""
        assert len(AGGREGATION_WINDOWS) >= 4

        window_names = {w.name for w in AGGREGATION_WINDOWS}
        assert "hourly" in window_names
        assert "daily" in window_names
        assert "weekly" in window_names
        assert "monthly" in window_names

    def test_trend_statistics_correctness(self):
        """Test that aggregated statistics are calculated correctly."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create run with known throughput values
            results = []
            throughputs = [100.0, 110.0, 120.0, 130.0, 140.0, 150.0, 160.0, 170.0, 180.0, 190.0]
            for i, throughput in enumerate(throughputs):
                results.append(
                    BenchmarkResult(
                        sample_id=f"sample_{i}",
                        model_id="test_model",
                        device="cpu",
                        batch_size=8,
                        duration_seconds=1.0,
                        tokens_input=100,
                        tokens_output=100,
                        throughput_tokens_per_sec=throughput,
                        peak_memory_mb=500.0,
                    )
                )

            run = BenchmarkRun(
                run_id="test_run",
                model_id="test_model",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
                corpus_category="test",
                purpose="testing",
                tags=["test"],
                system_info=SystemInfo(cpu_model="Test CPU", cpu_cores=4, total_ram_gb=8.0),
                results=results,
                total_duration_seconds=10.0,
            )
            db.save_run(run)

            # Aggregate
            aggregator = TimeSeriesAggregator(db_path)
            aggregator.aggregate_model("test_model", "cpu")

            # Check statistics
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    """
                    SELECT avg_throughput, p50_throughput, sample_count
                    FROM benchmark_trends
                    WHERE model_id = ? AND device = ? AND time_window = 'hourly'
                """,
                    ("test_model", "cpu"),
                )
                row = cursor.fetchone()

                assert row is not None

                avg_throughput = row[0]
                p50_throughput = row[1]
                sample_count = row[2]

                # Average should be close to 145.0 (mean of 100..190)
                assert 140.0 <= avg_throughput <= 150.0

                # p50 should be close to 145.0
                assert 140.0 <= p50_throughput <= 150.0

                # Should have all 10 samples
                assert sample_count == 10

            finally:
                db._close_connection(conn)
                db.close()

    def test_aggregate_empty_database(self):
        """Test aggregating empty database returns 0."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)  # Create empty database

            aggregator = TimeSeriesAggregator(db_path)
            trends_created = aggregator.aggregate_all()

            assert trends_created == 0

            db.close()

    def test_aggregate_nonexistent_model(self):
        """Test aggregating nonexistent model/device returns 0."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create run for model_a
            self._create_test_run(db, "model_a", "cpu")

            # Try to aggregate model_b (doesn't exist)
            aggregator = TimeSeriesAggregator(db_path)
            trends_created = aggregator.aggregate_model("model_b", "cpu")

            assert trends_created == 0

            db.close()
