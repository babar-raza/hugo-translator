"""Unit tests for schema migrations v8 (Phase 4.1).

Tests the MigrationManager class and v7->v8 migration:
- Migration to v8 creates analytics tables
- Rollback from v8 to v7 removes analytics tables
- Dry-run validation works correctly
- Migration idempotency
"""

import pytest
import sqlite3
import tempfile
from pathlib import Path

from src.benchmarking.schema_migrations import MigrationManager, MigrationError
from src.benchmarking.storage import BenchmarkDatabase


class TestSchemaMigrationsV8:
    """Test suite for v8 schema migrations."""

    def test_migrate_v7_to_v8(self):
        """Test migrating from v7 to v8 creates analytics tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v7 database
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == 7

            # Verify analytics tables don't exist yet
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                assert "benchmark_trends" not in tables
                assert "performance_baselines" not in tables
                assert "retention_policies" not in tables
            finally:
                db._close_connection(conn)

            # Close v7 database
            del db

            # Migrate to v8
            manager = MigrationManager(db_path)
            assert manager.get_current_version() == 7

            manager.migrate_to(8)
            assert manager.get_current_version() == 8

            # Verify analytics tables exist
            conn = manager._create_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                assert "benchmark_trends" in tables
                assert "performance_baselines" in tables
                assert "retention_policies" in tables

                # Verify retention policies have default entries
                cursor = conn.execute("SELECT COUNT(*) FROM retention_policies")
                policy_count = cursor.fetchone()[0]
                assert policy_count >= 3

                # Verify default policies exist
                cursor = conn.execute(
                    "SELECT policy_name FROM retention_policies ORDER BY policy_name"
                )
                policies = [row[0] for row in cursor.fetchall()]
                assert "benchmark_results_90d" in policies
                assert "benchmark_trends_365d" in policies
                assert "performance_baselines_730d" in policies

            finally:
                conn.close()

    def test_new_database_starts_at_v8(self):
        """Test that new databases start directly at v8."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create new database
            db = BenchmarkDatabase(db_path)

            # Should be at v8
            assert db.get_schema_version() == 8

            # All analytics tables should exist
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                assert "benchmark_trends" in tables
                assert "performance_baselines" in tables
                assert "retention_policies" in tables

            finally:
                db._close_connection(conn)

    def test_rollback_v8_to_v7(self):
        """Test rolling back from v8 to v7 removes analytics tables."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v8 database
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == 8
            del db

            # Rollback to v7
            manager = MigrationManager(db_path)
            manager.rollback_to(7)
            assert manager.get_current_version() == 7

            # Verify analytics tables removed
            conn = manager._create_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                assert "benchmark_trends" not in tables
                assert "performance_baselines" not in tables
                assert "retention_policies" not in tables

                # Verify v7 tables still exist
                assert "benchmark_runs" in tables
                assert "benchmark_results" in tables

            finally:
                conn.close()

    def test_migration_dry_run(self):
        """Test dry-run migration validates without executing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v7 database
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == 7
            del db

            # Dry-run migrate to v8
            manager = MigrationManager(db_path)
            manager.migrate_to(8, dry_run=True)

            # Version should still be 7
            assert manager.get_current_version() == 7

            # Analytics tables should not exist
            conn = manager._create_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                assert "benchmark_trends" not in tables

            finally:
                conn.close()

    def test_migration_idempotent(self):
        """Test that migrations can run multiple times safely."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create v8 database
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == 8
            del db

            # Try to migrate to v8 again (should be no-op)
            manager = MigrationManager(db_path)
            manager.migrate_to(8)  # Should not error

            assert manager.get_current_version() == 8

    def test_list_migrations(self):
        """Test listing available migrations."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            manager = MigrationManager(db_path)
            migrations = manager.list_migrations()

            # Should have v8 migration
            v8_migration = next((m for m in migrations if m["version"] == 8), None)
            assert v8_migration is not None
            assert "analytics" in v8_migration["description"].lower()

    def test_benchmark_trends_schema(self):
        """Test benchmark_trends table has correct schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            conn = db._get_connection()
            try:
                # Get column info for benchmark_trends
                cursor = conn.execute("PRAGMA table_info(benchmark_trends)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}

                # Verify required columns
                assert "model_id" in columns
                assert "device" in columns
                assert "time_window" in columns
                assert "window_start" in columns
                assert "window_end" in columns
                assert "sample_count" in columns
                assert "avg_throughput" in columns
                assert "p50_throughput" in columns
                assert "p95_throughput" in columns
                assert "p99_throughput" in columns
                assert "avg_duration" in columns
                assert "avg_memory_mb" in columns

                # Verify unique constraint exists
                cursor = conn.execute(
                    "SELECT sql FROM sqlite_master WHERE type='table' AND name='benchmark_trends'"
                )
                schema_sql = cursor.fetchone()[0]
                assert "UNIQUE" in schema_sql

            finally:
                db._close_connection(conn)

    def test_performance_baselines_schema(self):
        """Test performance_baselines table has correct schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            conn = db._get_connection()
            try:
                # Get column info
                cursor = conn.execute("PRAGMA table_info(performance_baselines)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}

                # Verify required columns
                assert "model_id" in columns
                assert "device" in columns
                assert "baseline_type" in columns
                assert "baseline_date" in columns
                assert "avg_throughput" in columns
                assert "p50_throughput" in columns
                assert "p95_throughput" in columns
                assert "sample_count" in columns
                assert "metadata" in columns

            finally:
                db._close_connection(conn)

    def test_retention_policies_schema(self):
        """Test retention_policies table has correct schema."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            conn = db._get_connection()
            try:
                # Get column info
                cursor = conn.execute("PRAGMA table_info(retention_policies)")
                columns = {row[1]: row[2] for row in cursor.fetchall()}

                # Verify required columns
                assert "policy_name" in columns
                assert "target_table" in columns
                assert "retention_days" in columns
                assert "enabled" in columns
                assert "last_cleanup" in columns

            finally:
                db._close_connection(conn)

    def test_v8_indices_created(self):
        """Test that v8 creates required indices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
                )
                indices = {row[0] for row in cursor.fetchall()}

                # Verify v8 indices exist
                assert "idx_trends_model_device" in indices
                assert "idx_trends_window" in indices
                assert "idx_trends_model_device_window" in indices
                assert "idx_baselines_model_device" in indices
                assert "idx_baselines_type_date" in indices

            finally:
                db._close_connection(conn)

    def test_migration_error_handling(self):
        """Test migration error handling."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            manager = MigrationManager(db_path)

            # Try to migrate to invalid version
            with pytest.raises(ValueError):
                manager.migrate_to(5)  # Can't go backwards

            # Try to rollback to invalid version
            with pytest.raises(ValueError):
                manager.rollback_to(10)  # Can't go forwards

    def test_memory_database_migration(self):
        """Test migrations work with in-memory database."""
        db = BenchmarkDatabase(":memory:")
        assert db.get_schema_version() == 8

        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            assert "benchmark_trends" in tables
            assert "performance_baselines" in tables
            assert "retention_policies" in tables

        finally:
            db._close_connection(conn)
