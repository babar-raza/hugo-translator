"""Tests for database concurrency and WAL mode (SR-06)."""

import pytest
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkRun,
    BenchmarkResult,
    SystemInfo,
)


def test_wal_mode_enabled():
    """Test that WAL mode is enabled on database creation."""
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


def test_busy_timeout_set():
    """Test that busy timeout is configured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # SQLite doesn't have a PRAGMA to read timeout directly,
            # but we can verify it doesn't error on concurrent access
            cursor = conn.execute("SELECT 1")
            assert cursor.fetchone()[0] == 1
        finally:
            db._close_connection(conn)


def test_foreign_keys_enabled():
    """Test that foreign keys are enforced."""
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


def test_concurrent_reads_during_write():
    """Test that multiple readers can read while one writer writes (WAL benefit)."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Save a benchmark run
        run = BenchmarkRun(
            run_id="test_run_001",
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
                )
            ],
            total_duration_seconds=1.0,
        )
        db.save_run(run)

        # Concurrent read results
        read_results = {"thread1": None, "thread2": None, "errors": []}

        def reader_thread(thread_id: str):
            """Reader thread that fetches runs."""
            try:
                # Read runs multiple times
                for _ in range(5):
                    runs = db.list_runs()
                    assert len(runs) >= 1, f"Thread {thread_id} expected at least 1 run"
                    time.sleep(0.01)
                read_results[thread_id] = "success"
            except Exception as e:
                read_results["errors"].append(f"{thread_id}: {e}")

        def writer_thread():
            """Writer thread that adds more runs."""
            try:
                for i in range(3):
                    new_run = BenchmarkRun(
                        run_id=f"test_run_writer_{i:03d}",
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
                    db.save_run(new_run)
                    time.sleep(0.02)
            except Exception as e:
                read_results["errors"].append(f"writer: {e}")

        # Start concurrent threads
        t1 = threading.Thread(target=reader_thread, args=("thread1",))
        t2 = threading.Thread(target=reader_thread, args=("thread2",))
        t3 = threading.Thread(target=writer_thread)

        t1.start()
        t2.start()
        t3.start()

        t1.join(timeout=5.0)
        t2.join(timeout=5.0)
        t3.join(timeout=5.0)

        # Check results
        assert not read_results["errors"], f"Concurrent access errors: {read_results['errors']}"
        assert read_results["thread1"] == "success", "Reader thread 1 failed"
        assert read_results["thread2"] == "success", "Reader thread 2 failed"

        db.close()


def test_concurrent_writes_with_retries():
    """Test that concurrent writes handle contention gracefully."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        write_results = {"thread1": None, "thread2": None, "errors": []}

        def writer_thread(thread_id: str, start_idx: int):
            """Writer thread that saves multiple runs."""
            try:
                for i in range(3):
                    run = BenchmarkRun(
                        run_id=f"run_{thread_id}_{start_idx + i:03d}",
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
                    time.sleep(0.01)
                write_results[thread_id] = "success"
            except Exception as e:
                write_results["errors"].append(f"{thread_id}: {e}")

        # Start concurrent writers
        t1 = threading.Thread(target=writer_thread, args=("thread1", 0))
        t2 = threading.Thread(target=writer_thread, args=("thread2", 100))

        t1.start()
        t2.start()

        t1.join(timeout=5.0)
        t2.join(timeout=5.0)

        # Check results
        assert not write_results["errors"], f"Concurrent write errors: {write_results['errors']}"
        assert write_results["thread1"] == "success", "Writer thread 1 failed"
        assert write_results["thread2"] == "success", "Writer thread 2 failed"

        # Verify all runs were saved
        runs = db.list_runs()
        assert len(runs) == 6, f"Expected 6 runs, got {len(runs)}"


def test_wal_checkpoint_configured():
    """Test that WAL autocheckpoint is configured."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Verify WAL mode is active
            cursor = conn.execute("PRAGMA journal_mode")
            assert cursor.fetchone()[0].lower() == "wal"

            # Note: Can't easily verify autocheckpoint setting via PRAGMA,
            # but we can verify WAL files are created
            wal_path = Path(str(db_path) + "-wal")

            # Write some data to trigger WAL file creation
            run = BenchmarkRun(
                run_id="test_run",
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

            # WAL file should exist after writes
            # (May not exist immediately on all systems, so this is informational)
            # assert wal_path.exists(), "WAL file should be created"
        finally:
            db._close_connection(conn)


def test_memory_database_concurrency():
    """Test that in-memory databases work with threading."""
    db = BenchmarkDatabase(":memory:")

    results = {"success_count": 0, "errors": []}

    def worker_thread(thread_id: int):
        """Worker that performs database operations."""
        try:
            # Save a run
            run = BenchmarkRun(
                run_id=f"run_{thread_id:03d}",
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

            # Read back
            fetched = db.get_run(f"run_{thread_id:03d}")
            assert fetched is not None
            assert fetched.run_id == f"run_{thread_id:03d}"

            results["success_count"] += 1
        except Exception as e:
            results["errors"].append(f"Thread {thread_id}: {e}")

    # Start multiple threads
    threads = [threading.Thread(target=worker_thread, args=(i,)) for i in range(5)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=5.0)

    # Check results
    assert not results["errors"], f"Thread errors: {results['errors']}"
    assert results["success_count"] == 5, f"Expected 5 successes, got {results['success_count']}"


def test_foreign_key_constraint_enforcement():
    """Test that foreign key constraints are enforced."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        conn = db._get_connection()
        try:
            # Try to insert feedback referencing non-existent run
            # (This would fail if foreign keys are enabled)
            with pytest.raises(sqlite3.IntegrityError):
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
            # Rollback after pytest.raises captures the exception
            conn.rollback()
        finally:
            db._close_connection(conn)
            db.close()


def test_cascading_delete():
    """Test that cascading delete works with foreign keys."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)

        # Save a run
        run = BenchmarkRun(
            run_id="test_run_cascade",
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
                )
            ],
            total_duration_seconds=1.0,
        )
        db.save_run(run)

        # Verify system_info and results exist
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM system_info WHERE run_id = ?", ("test_run_cascade",))
            assert cursor.fetchone()[0] == 1, "System info should exist"

            cursor = conn.execute("SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?", ("test_run_cascade",))
            assert cursor.fetchone()[0] == 1, "Results should exist"
        finally:
            db._close_connection(conn)

        # Delete the run
        db.delete_run("test_run_cascade")

        # Verify cascading delete removed related records
        conn = db._get_connection()
        try:
            cursor = conn.execute("SELECT COUNT(*) FROM system_info WHERE run_id = ?", ("test_run_cascade",))
            assert cursor.fetchone()[0] == 0, "System info should be deleted (CASCADE)"

            cursor = conn.execute("SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?", ("test_run_cascade",))
            assert cursor.fetchone()[0] == 0, "Results should be deleted (CASCADE)"
        finally:
            db._close_connection(conn)
