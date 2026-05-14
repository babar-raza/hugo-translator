"""Tests for database schema migrations.

Verifies that migrations work correctly and preserve data during upgrades.
"""

import sqlite3
import tempfile
from pathlib import Path

import pytest

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo

# Current schema version from BenchmarkDatabase class
CURRENT_SCHEMA_VERSION = BenchmarkDatabase.SCHEMA_VERSION


class TestSchemaMigrations:
    """Test suite for schema migrations."""

    def _create_v1_database(self, db_path: Path) -> None:
        """Create a v1 database schema manually."""
        conn = sqlite3.connect(str(db_path))
        try:
            # Create schema_version table
            conn.execute(
                """
                CREATE TABLE schema_version (
                    version INTEGER PRIMARY KEY,
                    applied_at TEXT NOT NULL
                )
                """
            )

            # Create v1 tables
            conn.execute(
                """
                CREATE TABLE benchmark_runs (
                    run_id TEXT PRIMARY KEY,
                    model_id TEXT NOT NULL,
                    device TEXT NOT NULL,
                    batch_sizes TEXT NOT NULL,
                    iterations INTEGER NOT NULL,
                    corpus_category TEXT,
                    purpose TEXT NOT NULL,
                    tags TEXT NOT NULL,
                    total_duration_seconds REAL NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    metadata TEXT NOT NULL
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE system_info (
                    run_id TEXT PRIMARY KEY,
                    cpu_model TEXT NOT NULL,
                    cpu_cores INTEGER NOT NULL,
                    total_ram_gb REAL NOT NULL,
                    gpu_model TEXT,
                    gpu_vram_gb REAL,
                    os_name TEXT NOT NULL,
                    os_version TEXT NOT NULL,
                    python_version TEXT NOT NULL,
                    torch_version TEXT NOT NULL,
                    transformers_version TEXT NOT NULL,
                    timestamp_utc TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
                )
                """
            )

            conn.execute(
                """
                CREATE TABLE benchmark_results (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    run_id TEXT NOT NULL,
                    sample_id TEXT NOT NULL,
                    model_id TEXT NOT NULL,
                    device TEXT NOT NULL,
                    batch_size INTEGER NOT NULL,
                    duration_seconds REAL NOT NULL,
                    tokens_input INTEGER NOT NULL,
                    tokens_output INTEGER NOT NULL,
                    throughput_tokens_per_sec REAL NOT NULL,
                    peak_memory_mb REAL,
                    errors TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
                )
                """
            )

            # Basic indices from v1
            conn.execute("CREATE INDEX idx_runs_model ON benchmark_runs(model_id)")
            conn.execute("CREATE INDEX idx_runs_device ON benchmark_runs(device)")
            conn.execute("CREATE INDEX idx_runs_timestamp ON benchmark_runs(timestamp_utc)")
            conn.execute("CREATE INDEX idx_results_run ON benchmark_results(run_id)")

            # Mark as v1
            conn.execute(
                "INSERT INTO schema_version (version, applied_at) VALUES (1, datetime('now'))"
            )

            conn.commit()
        finally:
            conn.close()

    def test_v1_to_v4_full_migration(self):
        """Test migrating from v1 all the way to v4."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v1 database
            self._create_v1_database(db_path)

            # Insert test data
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    """
                    INSERT INTO benchmark_runs VALUES
                    ('run1', 'model1', 'cpu', '[8, 16]', 10, 'test', 'testing',
                     '["tag1"]', 100.0, '2024-01-01T00:00:00Z', '{}')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO system_info VALUES
                    ('run1', 'Intel i7', 8, 16.0, NULL, NULL, 'Linux', '5.15',
                     '3.10', '2.0.0', '4.30.0', '2024-01-01T00:00:00Z')
                    """
                )
                conn.execute(
                    """
                    INSERT INTO benchmark_results VALUES
                    (1, 'run1', 'sample1', 'model1', 'cpu', 8, 10.0, 100, 120, 12.0, 500.0, '[]')
                    """
                )
                conn.commit()
            finally:
                conn.close()

            # Open with BenchmarkDatabase (should trigger migrations)
            db = BenchmarkDatabase(db_path)

            # Verify schema version is 4
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

            # Verify data preserved
            run = db.get_run('run1')
            assert run is not None
            assert run.model_id == 'model1'
            assert run.device == 'cpu'
            assert len(run.results) == 1
            assert run.results[0].sample_id == 'sample1'

            # Verify new tables exist
            conn = db._get_connection()
            try:
                # Check recommendation_feedback table
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_feedback'"
                )
                assert cursor.fetchone() is not None

                # Check recommendation_weights table
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_weights'"
                )
                assert cursor.fetchone() is not None

                # Check foreign key enforcement
                cursor = conn.execute("PRAGMA foreign_keys")
                assert cursor.fetchone()[0] == 1

            finally:
                db._close_connection(conn)

    def test_migration_idempotent(self):
        """Test that migrations can run multiple times safely."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database and run migrations
            db1 = BenchmarkDatabase(db_path)
            version1 = db1.get_schema_version()

            # Close and reopen (should not re-run migrations)
            del db1

            db2 = BenchmarkDatabase(db_path)
            version2 = db2.get_schema_version()

            # Versions should match
            assert version1 == version2
            assert version2 == CURRENT_SCHEMA_VERSION

    def test_v2_to_v4_migration(self):
        """Test migrating from v2 to v4."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v1 then migrate to v2
            self._create_v1_database(db_path)

            # Manually apply v2 migration
            conn = sqlite3.connect(str(db_path))
            try:
                conn.execute(
                    "CREATE INDEX idx_runs_model_device ON benchmark_runs(model_id, device)"
                )
                conn.execute(
                    "CREATE INDEX idx_runs_model_device_timestamp ON benchmark_runs(model_id, device, timestamp_utc)"
                )
                conn.execute(
                    "CREATE INDEX idx_sysinfo_cpu_ram ON system_info(cpu_cores, total_ram_gb)"
                )
                conn.execute(
                    "CREATE INDEX idx_results_throughput ON benchmark_results(throughput_tokens_per_sec)"
                )
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) VALUES (2, datetime('now'))"
                )
                conn.commit()
            finally:
                conn.close()

            # Open with BenchmarkDatabase (should migrate v2 -> v3 -> v4)
            db = BenchmarkDatabase(db_path)

            # Verify migrated to v4
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

            # Verify new tables exist
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_feedback'"
                )
                assert cursor.fetchone() is not None

                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' AND name='recommendation_weights'"
                )
                assert cursor.fetchone() is not None
            finally:
                db._close_connection(conn)

    def test_foreign_key_constraints(self):
        """Test that foreign key constraints are enforced."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Insert test run
            test_run = BenchmarkRun(
                run_id="test_run",
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
                    total_ram_gb=8.0,
                ),
                results=[
                    BenchmarkResult(
                        sample_id="sample1",
                        model_id="test_model",
                        device="cpu",
                        batch_size=8,
                        duration_seconds=1.0,
                        tokens_input=100,
                        tokens_output=100,
                        throughput_tokens_per_sec=100.0,
                    )
                ],
                total_duration_seconds=1.0,
            )
            db.save_run(test_run)

            # Try to insert feedback with invalid recommendation_id
            conn = db._get_connection()
            try:
                with pytest.raises(sqlite3.IntegrityError):
                    conn.execute(
                        """
                        INSERT INTO recommendation_feedback
                        (feedback_id, recommendation_id, model_id_recommended, model_id_used,
                         device_recommended, device_used, predicted_throughput, actual_throughput,
                         predicted_memory_mb, actual_memory_mb, success, quality_score,
                         failure_reason, timestamp_utc, system_info_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            "feedback1",
                            "nonexistent_run",  # Invalid FK
                            "model1",
                            "model1",
                            "cpu",
                            "cpu",
                            100.0,
                            95.0,
                            1000.0,
                            950.0,
                            1,
                            None,
                            None,
                            "2024-01-01T00:00:00Z",
                            "{}",
                        ),
                    )
                    conn.commit()
                # Rollback after pytest.raises captures the exception
                conn.rollback()
            finally:
                db._close_connection(conn)
                db.close()

    def test_cascading_delete(self):
        """Test that cascading deletes work for foreign keys."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Insert test run
            test_run = BenchmarkRun(
                run_id="test_run",
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
                    total_ram_gb=8.0,
                ),
                results=[],
                total_duration_seconds=1.0,
            )
            db.save_run(test_run)

            # Insert feedback referencing this run
            conn = db._get_connection()
            try:
                conn.execute(
                    """
                    INSERT INTO recommendation_feedback
                    (feedback_id, recommendation_id, model_id_recommended, model_id_used,
                     device_recommended, device_used, predicted_throughput, actual_throughput,
                     predicted_memory_mb, actual_memory_mb, success, quality_score,
                     failure_reason, timestamp_utc, system_info_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        "feedback1",
                        "test_run",
                        "test_model",
                        "test_model",
                        "cpu",
                        "cpu",
                        100.0,
                        95.0,
                        1000.0,
                        950.0,
                        1,
                        None,
                        None,
                        "2024-01-01T00:00:00Z",
                        "{}",
                    ),
                )
                conn.commit()

                # Verify feedback exists
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM recommendation_feedback WHERE recommendation_id = ?",
                    ("test_run",),
                )
                assert cursor.fetchone()[0] == 1

            finally:
                db._close_connection(conn)

            # Delete the run
            db.delete_run("test_run")

            # Verify feedback was cascaded-deleted
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM recommendation_feedback WHERE recommendation_id = ?",
                    ("test_run",),
                )
                assert cursor.fetchone()[0] == 0
            finally:
                db._close_connection(conn)

    def test_new_database_starts_at_v4(self):
        """Test that new databases start directly at schema v4."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            # Should be at v4
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

            # All tables should exist
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = [row[0] for row in cursor.fetchall()]

                assert "benchmark_runs" in tables
                assert "system_info" in tables
                assert "benchmark_results" in tables
                assert "recommendation_feedback" in tables
                assert "recommendation_weights" in tables
                assert "schema_version" in tables

            finally:
                db._close_connection(conn)

    def test_wal_mode_enabled(self):
        """Test that WAL mode is enabled."""
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            db = BenchmarkDatabase(db_path)

            conn = db._get_connection()
            try:
                cursor = conn.execute("PRAGMA journal_mode")
                mode = cursor.fetchone()[0]
                # Should be 'wal' or 'WAL'
                assert mode.lower() == "wal"
            finally:
                db._close_connection(conn)
