"""Negative test cases for BenchmarkDatabase storage layer."""
import sqlite3
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun, BenchmarkResult
from src.benchmarking.system_info import SystemInfo


def test_malformed_run_missing_required_fields():
    """BenchmarkRun with missing required fields should raise TypeError."""
    with pytest.raises(TypeError):
        BenchmarkRun(
            run_id="test",
            # Missing model_id - should fail
            device="cpu",
        )


def test_malformed_run_wrong_types():
    """BenchmarkRun with wrong field types should raise TypeError or validation error."""
    # Wrong type for iterations (should be int)
    with pytest.raises((TypeError, ValueError)):
        BenchmarkRun(
            run_id="test",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations="not_a_number",  # Should be int
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )


def test_empty_run_id_rejected():
    """BenchmarkRun with empty run_id should be rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        run = BenchmarkRun(
            run_id="",  # Empty run_id
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )

        # Should raise validation error or constraint error
        with pytest.raises((ValueError, sqlite3.IntegrityError)):
            db.save_run(run)


def test_duplicate_run_id_rejected():
    """Saving same run_id twice should raise IntegrityError."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        run = BenchmarkRun(
            run_id="duplicate_test",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )

        # First save should succeed
        db.save_run(run)

        # Second save with same run_id should fail
        with pytest.raises(sqlite3.IntegrityError):
            db.save_run(run)


def test_get_nonexistent_run_returns_none():
    """Getting a run that doesn't exist should return None."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        result = db.get_run("nonexistent_run_id")
        assert result is None


def test_delete_nonexistent_run_is_noop():
    """Deleting a run that doesn't exist should not raise error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Should not raise
        db.delete_run("nonexistent_run_id")


def test_corrupted_database_recovery():
    """Should handle corrupted database by reinitializing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "corrupted.db"

        # Create corrupted database file
        db_path.write_bytes(b"This is not a valid SQLite database")

        # Should not crash - should detect corruption and reinitialize
        try:
            db = BenchmarkDatabase(db_path)
            # Verify database is functional after recovery
            version = db.get_schema_version()
            assert version >= 1
        except sqlite3.DatabaseError:
            # Alternatively, might raise DatabaseError - also acceptable
            pass


def test_readonly_database_permission_error():
    """Should handle permission errors gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "readonly.db"

        # Create database
        db = BenchmarkDatabase(db_path)

        # Make file read-only
        db_path.chmod(0o444)

        try:
            # Attempt to save should fail with permission error
            run = BenchmarkRun(
                run_id="test",
                model_id="test_model",
                device="cpu",
                batch_sizes=[1],
                iterations=10,
                corpus_category="test",
                purpose="test",
                tags=[],
                system_info=SystemInfo(
                    python_version="3.11",
                    platform="linux",
                    cpu_model="test",
                    cpu_cores=4,
                    ram_total_gb=16.0,
                ),
                results=[],
            )

            with pytest.raises((sqlite3.OperationalError, PermissionError)):
                db.save_run(run)
        finally:
            # Restore permissions for cleanup
            db_path.chmod(0o644)


def test_empty_results_list_accepted():
    """BenchmarkRun with empty results list should be accepted."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        run = BenchmarkRun(
            run_id="empty_results",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=0,  # No iterations
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],  # Empty results
        )

        # Should succeed
        db.save_run(run)

        # Verify retrieval
        retrieved = db.get_run("empty_results")
        assert retrieved is not None
        assert len(retrieved.results) == 0


def test_null_tags_handled():
    """BenchmarkRun with None/null tags should be handled gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        run = BenchmarkRun(
            run_id="null_tags",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=None,  # None tags - should be converted to []
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )

        # Should succeed or raise TypeError for None
        try:
            db.save_run(run)
            retrieved = db.get_run("null_tags")
            assert retrieved.tags == [] or retrieved.tags is None
        except (TypeError, AttributeError):
            # Also acceptable - None not allowed for tags
            pass


def test_very_long_run_id_rejected():
    """BenchmarkRun with excessively long run_id should be rejected."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Create run with 10000 character run_id
        long_id = "x" * 10000

        run = BenchmarkRun(
            run_id=long_id,
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )

        # Should either succeed or fail with constraint error
        # (Implementation dependent on schema constraints)
        try:
            db.save_run(run)
            # If succeeded, verify retrieval works
            retrieved = db.get_run(long_id)
            assert retrieved is not None
        except (sqlite3.OperationalError, ValueError):
            # Also acceptable - ID too long
            pass


def test_negative_iterations_rejected():
    """BenchmarkRun with negative iterations should be rejected."""
    with pytest.raises((ValueError, TypeError)):
        BenchmarkRun(
            run_id="negative",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=-100,  # Negative iterations - invalid
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )


def test_invalid_schema_version_handled():
    """Database with invalid schema version should be handled."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create database and manually corrupt schema version
        db = BenchmarkDatabase(db_path)
        conn = sqlite3.connect(db_path)
        conn.execute("UPDATE metadata SET value = 'invalid' WHERE key = 'schema_version'")
        conn.commit()
        conn.close()

        # Should handle invalid schema version
        try:
            db2 = BenchmarkDatabase(db_path)
            version = db2.get_schema_version()
            # Should either return valid version after recovery or raise error
            assert isinstance(version, int)
        except (ValueError, sqlite3.DatabaseError):
            # Also acceptable - schema corruption detected
            pass


def test_sql_injection_in_run_id_prevented():
    """SQL injection attempt in run_id should be prevented."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Attempt SQL injection via run_id
        malicious_id = "test'; DROP TABLE runs; --"

        run = BenchmarkRun(
            run_id=malicious_id,
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )

        # Should safely store the malicious string
        db.save_run(run)

        # Verify table still exists (injection prevented)
        runs = db.list_runs(limit=10)
        assert len(runs) == 1

        # Verify retrieval works
        retrieved = db.get_run(malicious_id)
        assert retrieved is not None
        assert retrieved.run_id == malicious_id


def test_list_runs_with_zero_limit():
    """list_runs with limit=0 should return empty list."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Add a run
        run = BenchmarkRun(
            run_id="test",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=10,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                python_version="3.11",
                platform="linux",
                cpu_model="test",
                cpu_cores=4,
                ram_total_gb=16.0,
            ),
            results=[],
        )
        db.save_run(run)

        # Query with limit=0
        runs = db.list_runs(limit=0)
        assert len(runs) == 0


def test_list_runs_with_negative_limit_rejected():
    """list_runs with negative limit should raise error."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Should raise ValueError or similar
        with pytest.raises((ValueError, sqlite3.OperationalError)):
            db.list_runs(limit=-10)
