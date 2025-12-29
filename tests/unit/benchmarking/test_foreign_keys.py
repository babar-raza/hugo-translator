"""Tests for foreign key constraints (SR-08)."""

import pytest
import sqlite3
import tempfile
from pathlib import Path

from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkRun,
    BenchmarkResult,
    SystemInfo,
)


def test_foreign_keys_enabled_by_default():
    """Test that foreign keys are enabled on all connections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            cursor = conn.execute("PRAGMA foreign_keys")
            fk_enabled = cursor.fetchone()[0]
            assert fk_enabled == 1, "Foreign keys must be enabled"
        finally:
            db._close_connection(conn)


def test_system_info_fk_constraint():
    """Test that system_info enforces foreign key to benchmark_runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Try to insert system_info without corresponding benchmark_run
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute(
                    """
                    INSERT INTO system_info
                    (run_id, cpu_model, cpu_cores, total_ram_gb, os_name, os_version,
                     python_version, torch_version, transformers_version, timestamp_utc)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "nonexistent_run",
                        "Test CPU",
                        4,
                        16.0,
                        "Linux",
                        "5.15",
                        "3.11",
                        "2.0",
                        "4.0",
                        "2025-12-24T00:00:00Z",
                    ),
                )
                conn.commit()

            assert "FOREIGN KEY constraint failed" in str(exc_info.value)
        except sqlite3.IntegrityError:
            # Expected - rollback
            conn.rollback()
        finally:
            db._close_connection(conn)


def test_benchmark_results_fk_constraint():
    """Test that benchmark_results enforces foreign key to benchmark_runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Try to insert results without corresponding benchmark_run
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute(
                    """
                    INSERT INTO benchmark_results
                    (run_id, sample_id, model_id, device, batch_size, duration_seconds,
                     tokens_input, tokens_output, throughput_tokens_per_sec, errors)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "nonexistent_run",
                        "sample_001",
                        "model",
                        "cpu",
                        1,
                        1.0,
                        100,
                        100,
                        100.0,
                        "[]",
                    ),
                )
                conn.commit()

            assert "FOREIGN KEY constraint failed" in str(exc_info.value)
        except sqlite3.IntegrityError:
            # Expected - rollback
            conn.rollback()
        finally:
            db._close_connection(conn)


def test_recommendation_feedback_fk_constraint():
    """Test that recommendation_feedback enforces foreign key to benchmark_runs."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Try to insert feedback without corresponding benchmark_run
            with pytest.raises(sqlite3.IntegrityError) as exc_info:
                conn.execute(
                    """
                    INSERT INTO recommendation_feedback
                    (feedback_id, recommendation_id, model_id_recommended, model_id_used,
                     device_recommended, device_used, predicted_throughput, actual_throughput,
                     predicted_memory_mb, actual_memory_mb, success, timestamp_utc, system_info_json)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        "feedback_001",
                        "nonexistent_run",
                        "model",
                        "model",
                        "cpu",
                        "cpu",
                        100.0,
                        100.0,
                        1000.0,
                        1000.0,
                        1,
                        "2025-12-24T00:00:00Z",
                        "{}",
                    ),
                )
                conn.commit()

            assert "FOREIGN KEY constraint failed" in str(exc_info.value)
        except sqlite3.IntegrityError:
            # Expected - rollback
            conn.rollback()
        finally:
            db._close_connection(conn)


def test_cascading_delete_system_info():
    """Test that deleting a run cascades to system_info."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Save a run
        run = BenchmarkRun(
            run_id="test_cascade_1",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=1,
            corpus_category="test",
            purpose="test",
            tags=["test"],
            system_info=SystemInfo(
                cpu_model="Test CPU",
                cpu_cores=4,
                total_ram_gb=16.0,
                os_name="Linux",
                os_version="5.15",
                python_version="3.11",
            ),
            results=[],
            total_duration_seconds=1.0,
        )
        db.save_run(run)

        # Verify system_info exists
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM system_info WHERE run_id = ?", ("test_cascade_1",))
            count_before = cursor.fetchone()[0]
            assert count_before == 1, "System info should exist before delete"
        finally:
            db._close_connection(conn)

        # Delete the run
        db.delete_run("test_cascade_1")

        # Verify system_info was cascaded (deleted)
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM system_info WHERE run_id = ?", ("test_cascade_1",))
            count_after = cursor.fetchone()[0]
            assert count_after == 0, "System info should be deleted via CASCADE"
        finally:
            db._close_connection(conn)


def test_cascading_delete_benchmark_results():
    """Test that deleting a run cascades to benchmark_results."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Save a run with results
        run = BenchmarkRun(
            run_id="test_cascade_2",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=1,
            corpus_category="test",
            purpose="test",
            tags=["test"],
            system_info=SystemInfo(
                cpu_model="Test CPU",
                cpu_cores=4,
                total_ram_gb=16.0,
                os_name="Linux",
                os_version="5.15",
                python_version="3.11",
            ),
            results=[
                BenchmarkResult(
                    sample_id="sample_001",
                    model_id="test_model",
                    device="cpu",
                    batch_size=1,
                    duration_seconds=1.0,
                    tokens_input=100,
                    tokens_output=100,
                    throughput_tokens_per_sec=100.0,
                ),
                BenchmarkResult(
                    sample_id="sample_002",
                    model_id="test_model",
                    device="cpu",
                    batch_size=1,
                    duration_seconds=1.0,
                    tokens_input=100,
                    tokens_output=100,
                    throughput_tokens_per_sec=100.0,
                ),
            ],
            total_duration_seconds=2.0,
        )
        db.save_run(run)

        # Verify results exist
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?", ("test_cascade_2",))
            count_before = cursor.fetchone()[0]
            assert count_before == 2, "Results should exist before delete"
        finally:
            db._close_connection(conn)

        # Delete the run
        db.delete_run("test_cascade_2")

        # Verify results were cascaded (deleted)
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?", ("test_cascade_2",))
            count_after = cursor.fetchone()[0]
            assert count_after == 0, "Results should be deleted via CASCADE"
        finally:
            db._close_connection(conn)


def test_cascading_delete_recommendation_feedback():
    """Test that deleting a run cascades to recommendation_feedback."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Save a run
        run = BenchmarkRun(
            run_id="test_cascade_3",
            model_id="test_model",
            device="cpu",
            batch_sizes=[1],
            iterations=1,
            corpus_category="test",
            purpose="test",
            tags=["test"],
            system_info=SystemInfo(
                cpu_model="Test CPU",
                cpu_cores=4,
                total_ram_gb=16.0,
                os_name="Linux",
                os_version="5.15",
                python_version="3.11",
            ),
            results=[],
            total_duration_seconds=1.0,
        )
        db.save_run(run)

        # Insert feedback referencing this run
        conn = db._get_connection()
        try:
            conn.execute(
                """
                INSERT INTO recommendation_feedback
                (feedback_id, recommendation_id, model_id_recommended, model_id_used,
                 device_recommended, device_used, predicted_throughput, actual_throughput,
                 predicted_memory_mb, actual_memory_mb, success, timestamp_utc, system_info_json)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "feedback_cascade",
                    "test_cascade_3",
                    "model",
                    "model",
                    "cpu",
                    "cpu",
                    100.0,
                    100.0,
                    1000.0,
                    1000.0,
                    1,
                    "2025-12-24T00:00:00Z",
                    "{}",
                ),
            )
            conn.commit()

            # Verify feedback exists
            cursor = conn.execute(
                "SELECT COUNT(*) FROM recommendation_feedback WHERE recommendation_id = ?", ("test_cascade_3",)
            )
            count_before = cursor.fetchone()[0]
            assert count_before == 1, "Feedback should exist before delete"
        finally:
            db._close_connection(conn)

        # Delete the run
        db.delete_run("test_cascade_3")

        # Verify feedback was cascaded (deleted)
        conn = db._get_connection()
        try:
            cursor = conn.execute(
                "SELECT COUNT(*) FROM recommendation_feedback WHERE recommendation_id = ?", ("test_cascade_3",)
            )
            count_after = cursor.fetchone()[0]
            assert count_after == 0, "Feedback should be deleted via CASCADE"
        finally:
            db._close_connection(conn)


def test_fk_violation_prevents_orphaned_records():
    """Test that FK constraints prevent orphaned records."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Attempt to insert multiple orphaned records
            test_cases = [
                (
                    "system_info",
                    """INSERT INTO system_info
                       (run_id, cpu_model, cpu_cores, total_ram_gb, os_name, os_version,
                        python_version, torch_version, transformers_version, timestamp_utc)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("orphan_1", "CPU", 4, 16.0, "Linux", "5.15", "3.11", "2.0", "4.0", "2025-12-24T00:00:00Z"),
                ),
                (
                    "benchmark_results",
                    """INSERT INTO benchmark_results
                       (run_id, sample_id, model_id, device, batch_size, duration_seconds,
                        tokens_input, tokens_output, throughput_tokens_per_sec, errors)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    ("orphan_2", "sample", "model", "cpu", 1, 1.0, 100, 100, 100.0, "[]"),
                ),
                (
                    "recommendation_feedback",
                    """INSERT INTO recommendation_feedback
                       (feedback_id, recommendation_id, model_id_recommended, model_id_used,
                        device_recommended, device_used, predicted_throughput, actual_throughput,
                        predicted_memory_mb, actual_memory_mb, success, timestamp_utc, system_info_json)
                       VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        "feedback",
                        "orphan_3",
                        "model",
                        "model",
                        "cpu",
                        "cpu",
                        100.0,
                        100.0,
                        1000.0,
                        1000.0,
                        1,
                        "2025-12-24T00:00:00Z",
                        "{}",
                    ),
                ),
            ]

            for table_name, insert_sql, params in test_cases:
                with pytest.raises(sqlite3.IntegrityError) as exc_info:
                    conn.execute(insert_sql, params)
                    conn.commit()

                assert "FOREIGN KEY constraint failed" in str(
                    exc_info.value
                ), f"{table_name} should enforce FK constraint"
                conn.rollback()
        finally:
            db._close_connection(conn)


def test_fk_preserved_across_connections():
    """Test that FK enforcement persists across multiple connections."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"

        # Create database with first connection
        db1 = BenchmarkDatabase(db_path)

        # Close and create new database instance
        db2 = BenchmarkDatabase(db_path)

        # Verify FK still enabled
        conn = db2._get_connection()
        try:
            cursor = conn.execute("PRAGMA foreign_keys")
            fk_enabled = cursor.fetchone()[0]
            assert fk_enabled == 1, "FK should remain enabled across connections"
        finally:
            db2._close_connection(conn)
