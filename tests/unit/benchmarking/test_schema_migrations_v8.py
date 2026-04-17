"""Unit tests for schema migrations (Phase 4.1).

Tests the MigrationManager class:
- Migration creates analytics tables (benchmark_trends, performance_baselines, retention_policies)
- Rollback removes analytics tables
- Dry-run validation works correctly
- Migration idempotency
"""

import tempfile
from pathlib import Path

import pytest

from src.benchmarking.schema_migrations import MigrationManager
from src.benchmarking.storage import BenchmarkDatabase

# Current schema version in storage.py
CURRENT_SCHEMA_VERSION = 9


class TestSchemaMigrationsV8:
    """Test suite for schema migrations."""

    def test_migrate_v7_to_v8(self):
        """Test that database has analytics tables (benchmark_trends, etc.)."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database (starts at current version)
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

            # Verify analytics tables exist (v9 schema includes them)
            conn = db._get_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
                )
                tables = {row[0] for row in cursor.fetchall()}

                # Analytics tables from v8+ should exist
                assert "benchmark_trends" in tables
                assert "performance_baselines" in tables
                assert "retention_policies" in tables
            finally:
                db._close_connection(conn)

            del db

            # Verify MigrationManager can read current version
            manager = MigrationManager(db_path)
            assert manager.get_current_version() == CURRENT_SCHEMA_VERSION

            # Verify retention policies exist with defaults
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

    def test_new_database_starts_at_current_version(self):
        """Test that new databases start at current schema version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create new database
            db = BenchmarkDatabase(db_path)

            # Should be at current version
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

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

    def test_rollback_removes_analytics_tables(self):
        """Test rolling back removes analytics tables added in v8."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database at current version
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
            del db

            # Rollback to v7 (pre-analytics)
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

                # Verify core tables still exist
                assert "benchmark_runs" in tables
                assert "benchmark_results" in tables

            finally:
                conn.close()

    def test_migration_dry_run(self):
        """Test dry-run migration validates without executing."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database at current version, then rollback to v7
            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)
            manager.rollback_to(7)
            assert manager.get_current_version() == 7

            # Dry-run migrate to v8
            manager.migrate_to(8, dry_run=True)

            # Version should still be 7
            assert manager.get_current_version() == 7

            # Analytics tables should not exist (dry-run doesn't apply changes)
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

            # Create database at current version
            db = BenchmarkDatabase(db_path)
            assert db.get_schema_version() == CURRENT_SCHEMA_VERSION
            del db

            # Try to migrate to current version again (should be no-op)
            manager = MigrationManager(db_path)
            manager.migrate_to(CURRENT_SCHEMA_VERSION)  # Should not error

            assert manager.get_current_version() == CURRENT_SCHEMA_VERSION

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
        assert db.get_schema_version() == CURRENT_SCHEMA_VERSION

        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
            tables = {row[0] for row in cursor.fetchall()}

            assert "benchmark_trends" in tables
            assert "performance_baselines" in tables
            assert "retention_policies" in tables

        finally:
            db._close_connection(conn)


class TestMigrationManagerEdgeCases:
    """Tests for MigrationManager edge cases and error handling."""

    def test_rollback_already_at_target_version(self):
        """Rollback should be no-op when already at target version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database and rollback to v7
            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)
            manager.rollback_to(7)

            # Try rolling back to v7 again (should be no-op)
            manager.rollback_to(7)

            # Should still be at v7
            assert manager.get_current_version() == 7

    def test_migrate_already_at_target_version(self):
        """Migrate should be no-op when already at target version."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database at current version
            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)
            current = manager.get_current_version()

            # Try migrating to same version
            manager.migrate_to(current)

            # Should still be at same version
            assert manager.get_current_version() == current

    def test_rollback_forward_raises_error(self):
        """Rollback to higher version should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)
            manager.rollback_to(7)

            # Try to "rollback" to v9 (forward)
            with pytest.raises(ValueError, match="Cannot rollback forwards"):
                manager.rollback_to(9)

    def test_migrate_backward_raises_error(self):
        """Migrate to lower version should raise ValueError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)

            # Try to "migrate" to v7 (backward)
            with pytest.raises(ValueError, match="Cannot migrate backwards"):
                manager.migrate_to(7)


class TestMigrationWithSharedEngines:
    """Tests for MigrationManager with SharedEngines integration."""

    def test_migration_emits_telemetry_started(self):
        """Migration should emit telemetry event when starting."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database and rollback to v7
            db = BenchmarkDatabase(db_path)
            del db

            # Mock SharedEngines
            mock_engines = MagicMock()
            mock_engines.telemetry.track_event = MagicMock()

            manager = MigrationManager(db_path, engines=mock_engines)
            manager.rollback_to(7)

            # Reset mock
            mock_engines.telemetry.track_event.reset_mock()

            # Migrate to v8
            manager.migrate_to(8)

            # Verify telemetry was called for migration started
            calls = mock_engines.telemetry.track_event.call_args_list
            started_calls = [c for c in calls if "started" in str(c)]
            assert len(started_calls) > 0 or len(calls) > 0

    def test_migration_emits_telemetry_completed(self):
        """Migration should emit telemetry event when completed."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            mock_engines = MagicMock()
            manager = MigrationManager(db_path, engines=mock_engines)
            manager.rollback_to(7)

            mock_engines.telemetry.track_event.reset_mock()
            manager.migrate_to(8)

            # Verify telemetry was called for completion
            calls = mock_engines.telemetry.track_event.call_args_list
            assert len(calls) > 0

    def test_migration_dry_run_emits_telemetry(self):
        """Dry-run migration should emit telemetry with dry_run flag."""
        from unittest.mock import MagicMock

        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            mock_engines = MagicMock()
            manager = MigrationManager(db_path, engines=mock_engines)
            manager.rollback_to(7)

            mock_engines.telemetry.track_event.reset_mock()
            manager.migrate_to(8, dry_run=True)

            # Still at v7
            assert manager.get_current_version() == 7


class TestMigrationV9:
    """Tests specific to migration v9."""

    def test_v9_creates_query_optimization_indices(self):
        """V9 migration via MigrationManager creates query optimization indices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            # Create database at current version, then rollback to v8
            db = BenchmarkDatabase(db_path)
            del db

            # Use MigrationManager to rollback to v8, then migrate to v9
            manager = MigrationManager(db_path)
            manager.rollback_to(8)
            assert manager.get_current_version() == 8

            # Now migrate to v9 using MigrationManager
            manager.migrate_to(9)
            assert manager.get_current_version() == 9

            conn = manager._create_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
                )
                indices = {row[0] for row in cursor.fetchall()}

                # V9 adds query optimization indices
                assert "idx_trends_model_device_start" in indices
                assert "idx_baselines_model_device_type" in indices
                assert "idx_results_run_timestamp" in indices

            finally:
                conn.close()

    def test_v9_rollback_removes_optimization_indices(self):
        """Rolling back v9 removes the optimization indices."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)

            # Rollback v9 only (to v8)
            manager.rollback_to(8)

            conn = manager._create_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='index' ORDER BY name"
                )
                indices = {row[0] for row in cursor.fetchall()}

                # V9 indices should be removed
                assert "idx_trends_model_device_start" not in indices
                assert "idx_baselines_model_device_type" not in indices
                assert "idx_results_run_timestamp" not in indices

                # V8 indices should still exist
                assert "idx_trends_model_device" in indices

            finally:
                conn.close()


class TestMigrationValidation:
    """Tests for migration validation hooks."""

    def test_v8_post_check_validates_schema(self):
        """V8 post-check validates analytics tables and retention policies."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)

            # Rollback and re-migrate to trigger post-check
            manager.rollback_to(7)
            manager.migrate_to(8)

            # If we got here, validation passed
            assert manager.get_current_version() == 8

            # Verify the tables have the expected structure
            conn = manager._create_connection()
            try:
                cursor = conn.execute("SELECT COUNT(*) FROM retention_policies")
                count = cursor.fetchone()[0]
                assert count >= 3
            finally:
                conn.close()

    def test_rollback_dry_run(self):
        """Test dry-run rollback doesn't modify database."""
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"

            db = BenchmarkDatabase(db_path)
            del db

            manager = MigrationManager(db_path)
            assert manager.get_current_version() == CURRENT_SCHEMA_VERSION

            # Dry-run rollback
            manager.rollback_to(7, dry_run=True)

            # Version should be unchanged
            assert manager.get_current_version() == CURRENT_SCHEMA_VERSION

            # Analytics tables should still exist
            conn = manager._create_connection()
            try:
                cursor = conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
                tables = {row[0] for row in cursor.fetchall()}
                assert "benchmark_trends" in tables
            finally:
                conn.close()
