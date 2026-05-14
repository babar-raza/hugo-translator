"""Unit tests for data retention engine (Phase 4.3).

Tests the RetentionEngine class:
- Retention policy management
- Dry-run mode
- Actual data deletion
- Status reporting
"""

import tempfile
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.benchmarking.retention import (
    RetentionEngine,
    RetentionPolicy,
    RetentionResult,
)
from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkResult,
    BenchmarkRun,
    SystemInfo,
)


class TestRetentionPolicy:
    """Tests for RetentionPolicy dataclass."""

    def test_from_row(self):
        """Test creating RetentionPolicy from database row."""
        # Mock a sqlite3.Row-like dict
        class MockRow(dict):
            def __getitem__(self, key):
                return dict.__getitem__(self, key)

        row = MockRow({
            "id": 1,
            "policy_name": "test_policy",
            "target_table": "benchmark_results",
            "retention_days": 90,
            "enabled": 1,
            "last_cleanup": "2024-01-15T12:00:00",
            "created_at": "2024-01-01T00:00:00",
            "updated_at": "2024-01-15T12:00:00",
        })

        policy = RetentionPolicy.from_row(row)

        assert policy.id == 1
        assert policy.policy_name == "test_policy"
        assert policy.target_table == "benchmark_results"
        assert policy.retention_days == 90
        assert policy.enabled is True
        assert policy.last_cleanup == "2024-01-15T12:00:00"


class TestRetentionResult:
    """Tests for RetentionResult dataclass."""

    def test_to_dict(self):
        """Test converting RetentionResult to dictionary."""
        result = RetentionResult(
            policy_name="test_policy",
            target_table="benchmark_results",
            rows_deleted=100,
            dry_run=False,
            cutoff_date="2024-01-01T00:00:00",
        )

        result_dict = result.to_dict()

        assert result_dict["policy_name"] == "test_policy"
        assert result_dict["rows_deleted"] == 100
        assert result_dict["dry_run"] is False
        assert result_dict["error"] is None

    def test_to_dict_with_error(self):
        """Test RetentionResult with error."""
        result = RetentionResult(
            policy_name="test_policy",
            target_table="benchmark_results",
            rows_deleted=0,
            dry_run=False,
            cutoff_date="2024-01-01T00:00:00",
            error="Test error",
        )

        result_dict = result.to_dict()
        assert result_dict["error"] == "Test error"


class TestRetentionEngine:
    """Test suite for RetentionEngine."""

    def _create_test_run(
        self,
        db: BenchmarkDatabase,
        run_id: str,
        model_id: str = "test_model",
        device: str = "cpu",
        num_results: int = 5,
        timestamp: datetime | None = None,
    ) -> str:
        """Create a test benchmark run.

        Args:
            db: Database to save run to
            run_id: Run identifier
            model_id: Model identifier
            device: Device name
            num_results: Number of results to create
            timestamp: Run timestamp (defaults to now)

        Returns:
            Run ID
        """
        if timestamp is None:
            timestamp = datetime.now(UTC)

        results = []
        for i in range(num_results):
            results.append(BenchmarkResult(
                sample_id=f"sample_{i}",
                model_id=model_id,
                device=device,
                batch_size=8,
                duration_seconds=1.0 + i * 0.1,
                tokens_input=100,
                tokens_output=100,
                throughput_tokens_per_sec=100.0 + i * 10,
                peak_memory_mb=500.0,
            ))

        run = BenchmarkRun(
            run_id=run_id,
            model_id=model_id,
            device=device,
            batch_sizes=[8],
            iterations=1,
            corpus_category="test",
            purpose="testing",
            tags=["test"],
            system_info=SystemInfo(
                cpu_model="Test CPU",
                cpu_cores=4,
                total_ram_gb=8.0,
            ),
            results=results,
            total_duration_seconds=10.0,
            timestamp_utc=timestamp.isoformat(),
        )

        db.save_run(run)
        return run.run_id

    def test_list_policies(self):
        """Test listing retention policies."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)
            policies = engine.list_policies()

            # Default policies from schema v8
            assert len(policies) >= 3

            policy_names = {p.policy_name for p in policies}
            assert "benchmark_results_90d" in policy_names
            assert "benchmark_trends_365d" in policy_names
            assert "performance_baselines_730d" in policy_names

    def test_list_policies_enabled_only(self):
        """Test listing only enabled policies."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)

            # Disable one policy
            engine.update_policy("benchmark_results_90d", enabled=False)

            all_policies = engine.list_policies(enabled_only=False)
            enabled_policies = engine.list_policies(enabled_only=True)

            assert len(enabled_policies) < len(all_policies)

            # Verify disabled policy not in enabled list
            enabled_names = {p.policy_name for p in enabled_policies}
            assert "benchmark_results_90d" not in enabled_names

    def test_get_policy(self):
        """Test getting a specific policy."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)
            policy = engine.get_policy("benchmark_results_90d")

            assert policy is not None
            assert policy.policy_name == "benchmark_results_90d"
            assert policy.target_table == "benchmark_results"
            assert policy.retention_days == 90

    def test_get_policy_not_found(self):
        """Test getting non-existent policy."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)
            policy = engine.get_policy("nonexistent_policy")

            assert policy is None

    def test_update_policy(self):
        """Test updating a policy."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)

            # Update retention days
            updated = engine.update_policy("benchmark_results_90d", retention_days=60)
            assert updated is True

            policy = engine.get_policy("benchmark_results_90d")
            assert policy.retention_days == 60

    def test_update_policy_enabled(self):
        """Test enabling/disabling a policy."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)

            # Disable policy
            engine.update_policy("benchmark_results_90d", enabled=False)
            policy = engine.get_policy("benchmark_results_90d")
            assert policy.enabled is False

            # Re-enable policy
            engine.update_policy("benchmark_results_90d", enabled=True)
            policy = engine.get_policy("benchmark_results_90d")
            assert policy.enabled is True

    def test_create_policy(self):
        """Test creating a new policy."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)

            policy_id = engine.create_policy(
                policy_name="custom_policy",
                target_table="benchmark_runs",
                retention_days=30,
            )

            assert policy_id is not None

            policy = engine.get_policy("custom_policy")
            assert policy is not None
            assert policy.policy_name == "custom_policy"
            assert policy.retention_days == 30
            assert policy.enabled is True

    def test_create_policy_invalid_table(self):
        """Test creating policy with invalid table."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)

            with pytest.raises(ValueError):
                engine.create_policy(
                    policy_name="invalid_policy",
                    target_table="invalid_table",
                    retention_days=30,
                )

    def test_delete_policy(self):
        """Test deleting a policy."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            BenchmarkDatabase(db_path)

            engine = RetentionEngine(db_path)

            # Create and delete policy
            engine.create_policy(
                policy_name="temp_policy",
                target_table="benchmark_runs",
                retention_days=30,
            )

            deleted = engine.delete_policy("temp_policy")
            assert deleted is True

            policy = engine.get_policy("temp_policy")
            assert policy is None

    def test_get_retention_status(self):
        """Test getting retention status."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test run
            self._create_test_run(db, "run1")

            engine = RetentionEngine(db_path)
            status = engine.get_retention_status()

            assert "total_policies" in status
            assert "enabled_policies" in status
            assert "policies" in status
            assert len(status["policies"]) >= 3

    def test_execute_retention_dry_run(self):
        """Test dry run mode doesn't delete data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create old run (150 days ago)
            old_timestamp = datetime.now(UTC) - timedelta(days=150)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            # Create recent run
            self._create_test_run(db, "recent_run")

            # Verify initial state
            runs_before = db.list_runs()
            assert len(runs_before) == 2

            engine = RetentionEngine(db_path)
            results = engine.execute_retention(dry_run=True)

            # Verify data not deleted
            runs_after = db.list_runs()
            assert len(runs_after) == 2

            # Verify results indicate what would be deleted
            assert any(r.rows_deleted > 0 for r in results)
            assert all(r.dry_run for r in results)

    def test_execute_retention_actual(self):
        """Test actual retention execution deletes old data."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create old run (150 days ago)
            old_timestamp = datetime.now(UTC) - timedelta(days=150)
            self._create_test_run(db, "old_run", num_results=5, timestamp=old_timestamp)

            # Create recent run
            self._create_test_run(db, "recent_run", num_results=5)

            # Verify initial state
            runs_before = db.list_runs()
            assert len(runs_before) == 2

            engine = RetentionEngine(db_path)

            # Execute retention (default 90 day policy)
            results = engine.execute_retention(dry_run=False)

            # Verify old data deleted
            runs_after = db.list_runs()
            assert len(runs_after) == 1

            # Should keep the recent run
            assert runs_after[0][0] == "recent_run"

    def test_execute_retention_specific_policies(self):
        """Test executing specific policies only."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create test data
            old_timestamp = datetime.now(UTC) - timedelta(days=150)
            self._create_test_run(db, "old_run", timestamp=old_timestamp)

            engine = RetentionEngine(db_path)

            # Execute only specific policy
            results = engine.execute_retention(
                policy_names=["benchmark_results_90d"],
                dry_run=True,
            )

            # Should only execute one policy
            assert len(results) == 1
            assert results[0].policy_name == "benchmark_results_90d"

    def test_execute_retention_no_enabled_policies(self):
        """Test retention with all policies disabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            self._create_test_run(db, "run1")

            engine = RetentionEngine(db_path)

            # Disable all policies
            for policy in engine.list_policies():
                engine.update_policy(policy.policy_name, enabled=False)

            results = engine.execute_retention()

            # Should return empty results
            assert len(results) == 0

    def test_vacuum_database(self):
        """Test database vacuum operation."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Create and delete runs to create unused space
            for i in range(10):
                self._create_test_run(db, f"run_{i}", num_results=20)

            for i in range(5):
                db.delete_run(f"run_{i}")

            engine = RetentionEngine(db_path)

            # Vacuum should not raise
            reduction = engine.vacuum_database()

            # Reduction might be 0 or positive
            assert reduction >= 0


class TestRetentionEngineWithTrends:
    """Test retention for trends and baselines tables."""

    def _setup_db_with_trends(self, db_path: Path):
        """Setup database with trend data."""
        import sqlite3

        db = BenchmarkDatabase(db_path)

        conn = sqlite3.connect(str(db_path))
        try:
            # Insert old trend data
            old_timestamp = (datetime.now(UTC) - timedelta(days=400)).isoformat()
            conn.execute("""
                INSERT INTO benchmark_trends
                (model_id, device, time_window, window_start, window_end,
                 sample_count, avg_throughput, p50_throughput, p95_throughput, p99_throughput,
                 avg_duration, avg_memory_mb, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("test_model", "cpu", "daily", old_timestamp, old_timestamp,
                  10, 100.0, 100.0, 100.0, 100.0, 1.0, 500.0, old_timestamp))

            # Insert recent trend data
            recent_timestamp = datetime.now(UTC).isoformat()
            conn.execute("""
                INSERT INTO benchmark_trends
                (model_id, device, time_window, window_start, window_end,
                 sample_count, avg_throughput, p50_throughput, p95_throughput, p99_throughput,
                 avg_duration, avg_memory_mb, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, ("test_model", "cpu", "daily", recent_timestamp, recent_timestamp,
                  10, 100.0, 100.0, 100.0, 100.0, 1.0, 500.0, recent_timestamp))

            conn.commit()
        finally:
            conn.close()

        return db

    def test_retention_on_trends(self):
        """Test retention deletes old trends."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            self._setup_db_with_trends(db_path)

            engine = RetentionEngine(db_path)

            # Execute retention on trends
            results = engine.execute_retention(
                policy_names=["benchmark_trends_365d"],
                dry_run=False,
            )

            # Should have deleted old trend
            assert len(results) == 1
            assert results[0].rows_deleted > 0
