"""Tests for database schema migrations (SR-05)."""

import pytest
import sqlite3
import tempfile
from pathlib import Path

from src.benchmarking.storage import BenchmarkDatabase


def create_v0_database(db_path: Path) -> sqlite3.Connection:
    """Create a v0 (empty) database for testing migrations."""
    conn = sqlite3.connect(str(db_path))
    # Create version table but don't insert any version
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS schema_version (
            version INTEGER PRIMARY KEY,
            applied_at TEXT NOT NULL
        )
    """
    )
    conn.commit()
    return conn


def test_migration_from_v0_to_v4():
    """Test full migration path from empty database to v4."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create empty database
        conn = create_v0_database(db_path)
        conn.close()

        # Initialize BenchmarkDatabase (should trigger migrations)
        db = BenchmarkDatabase(db_path)

        # Verify schema version is 4
        assert db.get_schema_version() == 4

        # Verify all tables exist
        conn = db._get_connection()
        try:
            cursor = conn.execute(
                "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
            )
            tables = {row[0] for row in cursor.fetchall()}

            expected_tables = {
                "schema_version",
                "benchmark_runs",
                "system_info",
                "benchmark_results",
                "recommendation_feedback",
                "recommendation_weights",
            }

            assert expected_tables.issubset(tables), f"Missing tables: {expected_tables - tables}"
        finally:
            db._close_connection(conn)


def test_migration_idempotent():
    """Test that migrations can run multiple times safely."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Initialize database (runs migrations once)
        db1 = BenchmarkDatabase(db_path)
        assert db1.get_schema_version() == 4

        # Re-initialize same database (should not error)
        db2 = BenchmarkDatabase(db_path)
        assert db2.get_schema_version() == 4

        # Verify only one entry per version in schema_version table
        conn = db2._get_connection()
        try:
            cursor = conn.execute("SELECT version, COUNT(*) as count FROM schema_version GROUP BY version")
            version_counts = {row[0]: row[1] for row in cursor.fetchall()}

            # Each version should appear exactly once
            for version in [1, 2, 3, 4]:
                assert version_counts.get(version, 0) == 1, f"Version {version} appears {version_counts.get(version, 0)} times"
        finally:
            db2._close_connection(conn)


def test_schema_version_tracking():
    """Test that schema_version table is correctly maintained."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Check all versions are recorded
            cursor = conn.execute("SELECT version FROM schema_version ORDER BY version")
            versions = [row[0] for row in cursor.fetchall()]

            assert versions == [1, 2, 3, 4], f"Expected [1, 2, 3, 4], got {versions}"

            # Check timestamps are present
            cursor = conn.execute("SELECT version, applied_at FROM schema_version")
            for row in cursor.fetchall():
                version, applied_at = row
                assert applied_at is not None, f"Version {version} missing timestamp"
                assert len(applied_at) > 0, f"Version {version} has empty timestamp"
        finally:
            db._close_connection(conn)


def test_foreign_keys_enabled():
    """Test that foreign keys are enabled after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            cursor = conn.execute("PRAGMA foreign_keys")
            fk_enabled = cursor.fetchone()[0]
            assert fk_enabled == 1, "Foreign keys should be enabled"
        finally:
            db._close_connection(conn)


def test_wal_mode_enabled():
    """Test that WAL mode is enabled after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            cursor = conn.execute("PRAGMA journal_mode")
            journal_mode = cursor.fetchone()[0]
            assert journal_mode.lower() == "wal", f"Expected WAL mode, got {journal_mode}"
        finally:
            db._close_connection(conn)


def test_indices_created():
    """Test that all expected indices are created."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='index' ORDER BY name")
            indices = {row[0] for row in cursor.fetchall()}

            expected_indices = {
                "idx_runs_model",
                "idx_runs_device",
                "idx_runs_timestamp",
                "idx_results_run",
                "idx_runs_model_device",
                "idx_runs_model_device_timestamp",
                "idx_sysinfo_cpu_ram",
                "idx_results_throughput",
                "idx_feedback_recommendation",
                "idx_feedback_model",
                "idx_feedback_timestamp",
                "idx_weights_timestamp",
            }

            missing_indices = expected_indices - indices
            assert not missing_indices, f"Missing indices: {missing_indices}"
        finally:
            db._close_connection(conn)


def test_integrity_check_passes():
    """Test that database integrity check passes after migration."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Run integrity check
        assert db.verify_integrity() is True


def test_memory_database_migration():
    """Test migrations work with in-memory database."""
    db = BenchmarkDatabase(":memory:")

    # Verify schema version
    assert db.get_schema_version() == 4

    # Verify tables exist
    conn = db._get_connection()
    try:
        cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        tables = {row[0] for row in cursor.fetchall()}

        assert "benchmark_runs" in tables
        assert "recommendation_feedback" in tables
        assert "recommendation_weights" in tables
    finally:
        db._close_connection(conn)
