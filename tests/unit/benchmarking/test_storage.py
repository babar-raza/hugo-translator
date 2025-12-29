"""Unit tests for benchmark storage layer.

Test coverage:
1. Table creation and schema verification
2. Run insertion and retrieval
3. Filtering and pagination
4. JSON export/import
5. Run comparison
6. Concurrent reads (WAL mode)
7. Deletion and cascading
8. Integrity checks
"""

import json
import sqlite3
import tempfile
import threading
import time
from pathlib import Path

import pytest

from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkResult,
    BenchmarkRun,
    SystemInfo,
)


@pytest.fixture
def temp_db():
    """Create a temporary database for testing."""
    with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
        db_path = Path(f.name)
    yield db_path
    # Cleanup
    if db_path.exists():
        db_path.unlink()
    # Clean up WAL files
    for suffix in ["-wal", "-shm"]:
        wal_path = Path(str(db_path) + suffix)
        if wal_path.exists():
            wal_path.unlink()


@pytest.fixture
def sample_system_info():
    """Sample system information (comprehensive SystemInfo)."""
    return SystemInfo(
        cpu_model="Intel Core i7-9700K",
        cpu_cores=8,
        total_ram_gb=16.0,
        gpu_model="NVIDIA RTX 3060",
        gpu_memory_gb=12.0,  # Comprehensive SystemInfo uses gpu_memory_gb
        os_name="Windows",
        os_version="10.0.19045",
        python_version="3.10.12",
        torch_version="2.1.0",
        collected_at_utc="2025-12-19T00:00:00Z",
    )


@pytest.fixture
def sample_results(test_model):
    """Sample benchmark results."""
    return [
        BenchmarkResult(
            sample_id="sample_001",
            model_id=test_model,
            device="cpu",
            batch_size=8,
            duration_seconds=2.5,
            tokens_input=120,
            tokens_output=115,
            throughput_tokens_per_sec=48.0,
            peak_memory_mb=512.0,
        ),
        BenchmarkResult(
            sample_id="sample_002",
            model_id=test_model,
            device="cpu",
            batch_size=8,
            duration_seconds=2.3,
            tokens_input=100,
            tokens_output=95,
            throughput_tokens_per_sec=43.5,
            peak_memory_mb=510.0,
        ),
    ]


@pytest.fixture
def sample_run(test_model, sample_system_info, sample_results):
    """Sample benchmark run."""
    return BenchmarkRun(
        run_id="test_run_001",
        model_id=test_model,
        device="cpu",
        batch_sizes=[8, 16],
        iterations=5,
        corpus_category="technical",
        purpose="cpu regression test",
        tags=["cpu", "regression"],
        system_info=sample_system_info,
        results=sample_results,
        total_duration_seconds=12.5,
        metadata={"note": "test run"},
    )


@pytest.mark.benchmarking
@pytest.mark.unit
class TestBenchmarkDatabase:
    """Test BenchmarkDatabase functionality."""

    def test_table_creation_and_schema(self, temp_db):
        """Test 1: Verify tables are created with correct schema."""
        db = BenchmarkDatabase(temp_db)

        # Verify tables exist
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' ORDER BY name"
        )
        tables = [row[0] for row in cursor.fetchall()]
        conn.close()

        assert "benchmark_runs" in tables
        assert "system_info" in tables
        assert "benchmark_results" in tables
        assert "schema_version" in tables

        # Verify WAL mode
        conn = sqlite3.connect(str(temp_db))
        cursor = conn.execute("PRAGMA journal_mode")
        mode = cursor.fetchone()[0]
        conn.close()
        assert mode.lower() == "wal"

        # Verify schema version
        assert db.get_schema_version() == 1

    def test_save_and_retrieve_run(self, temp_db, sample_run):
        """Test 2: Verify saving and retrieving a complete benchmark run."""
        db = BenchmarkDatabase(temp_db)

        # Save run
        db.save_run(sample_run)

        # Retrieve run
        retrieved = db.get_run(sample_run.run_id)

        assert retrieved is not None
        assert retrieved.run_id == sample_run.run_id
        assert retrieved.model_id == sample_run.model_id
        assert retrieved.device == sample_run.device
        assert retrieved.batch_sizes == sample_run.batch_sizes
        assert retrieved.iterations == sample_run.iterations
        assert retrieved.corpus_category == sample_run.corpus_category
        assert retrieved.purpose == sample_run.purpose
        assert retrieved.tags == sample_run.tags
        assert retrieved.total_duration_seconds == sample_run.total_duration_seconds

        # Verify system info
        assert retrieved.system_info.cpu_model == sample_run.system_info.cpu_model
        assert retrieved.system_info.cpu_cores == sample_run.system_info.cpu_cores
        assert retrieved.system_info.gpu_model == sample_run.system_info.gpu_model

        # Verify results
        assert len(retrieved.results) == len(sample_run.results)
        assert retrieved.results[0].sample_id == sample_run.results[0].sample_id
        assert retrieved.results[0].throughput_tokens_per_sec == sample_run.results[0].throughput_tokens_per_sec

    def test_list_runs_filtering_pagination(self, temp_db, test_model, sample_run, sample_system_info):
        """Test 3: Verify filtering and pagination of run listings."""
        db = BenchmarkDatabase(temp_db)

        # Create multiple runs with different models and devices
        runs = [
            BenchmarkRun(
                run_id=f"run_{i:03d}",
                model_id=test_model if i % 2 == 0 else "opus_en_fr",
                device="cpu" if i % 3 == 0 else "cuda",
                batch_sizes=[8],
                iterations=1,
                corpus_category="technical",
                purpose="test",
                tags=["test"],
                system_info=sample_system_info,
                results=[],
                total_duration_seconds=1.0,
            )
            for i in range(10)
        ]

        for run in runs:
            db.save_run(run)

        # Test listing all runs
        all_runs = db.list_runs(limit=100)
        assert len(all_runs) == 10

        # Test model filtering
        m2m_runs = db.list_runs(model_id=test_model)
        assert len(m2m_runs) == 5
        assert all(r[1] == test_model for r in m2m_runs)

        # Test device filtering
        cpu_runs = db.list_runs(device="cpu")
        assert len(cpu_runs) == 4
        assert all(r[2] == "cpu" for r in cpu_runs)

        # Test pagination
        page1 = db.list_runs(limit=3, offset=0)
        page2 = db.list_runs(limit=3, offset=3)
        assert len(page1) == 3
        assert len(page2) == 3
        assert page1[0][0] != page2[0][0]  # Different run IDs

    def test_json_export_import(self, temp_db, sample_run):
        """Test 4: Verify JSON export and import roundtrip."""
        db = BenchmarkDatabase(temp_db)

        # Save original run
        db.save_run(sample_run)

        # Export to JSON
        exported = db.export_run(sample_run.run_id)
        assert exported is not None
        assert exported["run_id"] == sample_run.run_id

        # Verify JSON is serializable
        json_str = json.dumps(exported)
        assert len(json_str) > 0

        # Create new database and import
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            new_db_path = Path(f.name)

        try:
            new_db = BenchmarkDatabase(new_db_path)
            new_db.import_run(exported)

            # Verify imported run matches original
            imported = new_db.get_run(sample_run.run_id)
            assert imported is not None
            assert imported.run_id == sample_run.run_id
            assert imported.model_id == sample_run.model_id
            assert len(imported.results) == len(sample_run.results)
        finally:
            if new_db_path.exists():
                new_db_path.unlink()
            for suffix in ["-wal", "-shm"]:
                wal_path = Path(str(new_db_path) + suffix)
                if wal_path.exists():
                    wal_path.unlink()

    def test_compare_runs(self, temp_db, test_model, sample_system_info):
        """Test 5: Verify run comparison on different metrics."""
        db = BenchmarkDatabase(temp_db)

        # Create two runs with different performance characteristics
        run1 = BenchmarkRun(
            run_id="fast_run",
            model_id="opus_en_fr",
            device="cpu",
            batch_sizes=[8],
            iterations=2,
            corpus_category="technical",
            purpose="comparison test",
            tags=["fast"],
            system_info=sample_system_info,
            results=[
                BenchmarkResult(
                    sample_id="s1",
                    model_id="opus_en_fr",
                    device="cpu",
                    batch_size=8,
                    duration_seconds=1.0,
                    tokens_input=100,
                    tokens_output=95,
                    throughput_tokens_per_sec=100.0,
                    peak_memory_mb=256.0,
                )
            ],
            total_duration_seconds=2.0,
        )

        run2 = BenchmarkRun(
            run_id="slow_run",
            model_id=test_model,
            device="cpu",
            batch_sizes=[8],
            iterations=2,
            corpus_category="technical",
            purpose="comparison test",
            tags=["slow"],
            system_info=sample_system_info,
            results=[
                BenchmarkResult(
                    sample_id="s2",
                    model_id=test_model,
                    device="cpu",
                    batch_size=8,
                    duration_seconds=2.0,
                    tokens_input=100,
                    tokens_output=95,
                    throughput_tokens_per_sec=50.0,
                    peak_memory_mb=512.0,
                )
            ],
            total_duration_seconds=4.0,
        )

        db.save_run(run1)
        db.save_run(run2)

        # Compare throughput
        comparison = db.compare_runs(["fast_run", "slow_run"], metric="throughput_tokens_per_sec")
        assert comparison["metric"] == "throughput_tokens_per_sec"
        assert len(comparison["runs"]) == 2

        fast_data = next(r for r in comparison["runs"] if r["run_id"] == "fast_run")
        slow_data = next(r for r in comparison["runs"] if r["run_id"] == "slow_run")

        assert fast_data["avg"] == 100.0
        assert slow_data["avg"] == 50.0
        assert fast_data["avg"] > slow_data["avg"]

        # Compare memory
        mem_comparison = db.compare_runs(["fast_run", "slow_run"], metric="peak_memory_mb")
        assert mem_comparison["metric"] == "peak_memory_mb"
        fast_mem = next(r for r in mem_comparison["runs"] if r["run_id"] == "fast_run")
        slow_mem = next(r for r in mem_comparison["runs"] if r["run_id"] == "slow_run")
        assert slow_mem["avg"] > fast_mem["avg"]

    def test_concurrent_reads(self, temp_db, sample_run):
        """Test 6: Verify WAL mode allows concurrent reads."""
        db = BenchmarkDatabase(temp_db)
        db.save_run(sample_run)

        results = []
        errors = []

        def read_run():
            """Read run from database."""
            try:
                local_db = BenchmarkDatabase(temp_db)
                run = local_db.get_run(sample_run.run_id)
                if run:
                    results.append(run.run_id)
            except Exception as e:
                errors.append(str(e))

        # Launch multiple concurrent readers
        threads = [threading.Thread(target=read_run) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All reads should succeed
        assert len(errors) == 0, f"Concurrent read errors: {errors}"
        assert len(results) == 5
        assert all(r == sample_run.run_id for r in results)

    def test_delete_run_cascading(self, temp_db, sample_run):
        """Test 7: Verify deletion and cascading to related tables."""
        db = BenchmarkDatabase(temp_db)

        # Save run
        db.save_run(sample_run)

        # Verify run exists
        assert db.get_run(sample_run.run_id) is not None

        # Delete run
        deleted = db.delete_run(sample_run.run_id)
        assert deleted is True

        # Verify run is deleted
        assert db.get_run(sample_run.run_id) is None

        # Verify cascading deletion of system_info and results
        conn = sqlite3.connect(str(temp_db))

        cursor = conn.execute("SELECT COUNT(*) FROM system_info WHERE run_id = ?", (sample_run.run_id,))
        assert cursor.fetchone()[0] == 0

        cursor = conn.execute(
            "SELECT COUNT(*) FROM benchmark_results WHERE run_id = ?", (sample_run.run_id,)
        )
        assert cursor.fetchone()[0] == 0

        conn.close()

        # Test deleting non-existent run
        deleted = db.delete_run("nonexistent_run")
        assert deleted is False

    def test_integrity_check(self, temp_db, sample_run):
        """Test 8: Verify database integrity checks."""
        db = BenchmarkDatabase(temp_db)

        # Empty database should pass
        assert db.verify_integrity() is True

        # Database with data should pass
        db.save_run(sample_run)
        assert db.verify_integrity() is True

        # Verify foreign key constraints
        conn = sqlite3.connect(str(temp_db))
        conn.execute("PRAGMA foreign_keys = ON")

        # Try to insert orphan system_info (should fail)
        with pytest.raises(sqlite3.IntegrityError):
            conn.execute(
                """
                INSERT INTO system_info
                (run_id, cpu_model, cpu_cores, total_ram_gb, os_name, os_version,
                 python_version, torch_version, transformers_version, timestamp_utc)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    "nonexistent_run",
                    "CPU",
                    4,
                    8.0,
                    "OS",
                    "1.0",
                    "3.10",
                    "2.0",
                    "4.0",
                    "2025-01-01T00:00:00",
                ),
            )

        conn.close()


@pytest.mark.benchmarking
@pytest.mark.unit
class TestDataclasses:
    """Test dataclass serialization and deserialization."""

    def test_system_info_serialization(self, sample_system_info):
        """Test SystemInfo to_dict and from_dict roundtrip."""
        data = sample_system_info.to_dict()
        assert isinstance(data, dict)
        assert data["cpu_model"] == sample_system_info.cpu_model

        reconstructed = SystemInfo.from_dict(data)
        assert reconstructed.cpu_model == sample_system_info.cpu_model
        assert reconstructed.gpu_memory_gb == sample_system_info.gpu_memory_gb

    def test_benchmark_result_serialization(self, sample_results):
        """Test BenchmarkResult to_dict and from_dict roundtrip."""
        result = sample_results[0]
        data = result.to_dict()
        assert isinstance(data, dict)
        assert data["sample_id"] == result.sample_id

        reconstructed = BenchmarkResult.from_dict(data)
        assert reconstructed.sample_id == result.sample_id
        assert reconstructed.throughput_tokens_per_sec == result.throughput_tokens_per_sec

    def test_benchmark_run_serialization(self, sample_run):
        """Test BenchmarkRun to_dict and from_dict roundtrip."""
        data = sample_run.to_dict()
        assert isinstance(data, dict)
        assert data["run_id"] == sample_run.run_id

        reconstructed = BenchmarkRun.from_dict(data)
        assert reconstructed.run_id == sample_run.run_id
        assert reconstructed.model_id == sample_run.model_id
        assert len(reconstructed.results) == len(sample_run.results)
        assert reconstructed.system_info.cpu_model == sample_run.system_info.cpu_model


@pytest.mark.benchmarking
@pytest.mark.unit
def test_in_memory_database():
    """Test database creation with :memory: for isolation."""
    db = BenchmarkDatabase(":memory:")
    assert db.get_schema_version() == 1
    assert db.verify_integrity() is True

    # Verify tables exist
    assert db.list_runs() == []
