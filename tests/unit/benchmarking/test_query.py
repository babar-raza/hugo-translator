"""Unit tests for benchmark query API."""

import pytest
from datetime import datetime, timedelta
from pathlib import Path

from src.benchmarking.query import BenchmarkQueryAPI, BenchmarkQueryBuilder
from src.benchmarking.storage import (
    BenchmarkDatabase,
    BenchmarkResult,
    BenchmarkRun,
    SystemInfo,
)


@pytest.fixture
def test_db():
    """Create in-memory test database."""
    db = BenchmarkDatabase(":memory:")
    return db


@pytest.fixture
def sample_runs(test_db):
    """Populate database with sample runs."""
    # Create sample system info (comprehensive SystemInfo)
    sysinfo_cpu = SystemInfo(
        cpu_model="Intel i7-12700K",
        cpu_cores=12,
        total_ram_gb=32.0,
        gpu_model=None,
        gpu_memory_gb=None,
        os_name="Linux",
        os_version="Ubuntu 22.04",
        python_version="3.11.0",
        torch_version="2.1.0",
        collected_at_utc="2025-12-19T00:00:00Z",
    )

    sysinfo_gpu = SystemInfo(
        cpu_model="AMD Ryzen 9 5950X",
        cpu_cores=16,
        total_ram_gb=64.0,
        gpu_model="NVIDIA RTX 3080",
        gpu_memory_gb=10.0,  # Comprehensive SystemInfo uses gpu_memory_gb
        os_name="Linux",
        os_version="Ubuntu 22.04",
        python_version="3.11.0",
        torch_version="2.1.0",
        collected_at_utc="2025-12-19T00:00:00Z",
    )

    # Create benchmark results
    results_fast = [
        BenchmarkResult(
            sample_id="sample_1",
            model_id="facebook/m2m100_418M",
            device="cpu",
            batch_size=8,
            duration_seconds=1.5,
            tokens_input=100,
            tokens_output=120,
            throughput_tokens_per_sec=80.0,
            peak_memory_mb=500.0,
        )
    ]

    results_slow = [
        BenchmarkResult(
            sample_id="sample_1",
            model_id="facebook/m2m100_1.2B",
            device="cpu",
            batch_size=4,
            duration_seconds=3.0,
            tokens_input=100,
            tokens_output=120,
            throughput_tokens_per_sec=40.0,
            peak_memory_mb=1500.0,
        )
    ]

    results_gpu = [
        BenchmarkResult(
            sample_id="sample_1",
            model_id="facebook/m2m100_418M",
            device="cuda",
            batch_size=16,
            duration_seconds=0.5,
            tokens_input=100,
            tokens_output=120,
            throughput_tokens_per_sec=240.0,
            peak_memory_mb=2000.0,
        )
    ]

    # Create benchmark runs
    now = datetime.now()

    run1 = BenchmarkRun(
        run_id="run_001",
        model_id="facebook/m2m100_418M",
        device="cpu",
        batch_sizes=[8],
        iterations=1,
        corpus_category="technical",
        purpose="baseline",
        tags=["cpu", "baseline"],
        system_info=sysinfo_cpu,
        results=results_fast,
        total_duration_seconds=1.5,
        timestamp_utc=(now - timedelta(days=2)).isoformat(),
    )

    run2 = BenchmarkRun(
        run_id="run_002",
        model_id="facebook/m2m100_1.2B",
        device="cpu",
        batch_sizes=[4],
        iterations=1,
        corpus_category="technical",
        purpose="comparison",
        tags=["cpu", "large_model"],
        system_info=sysinfo_cpu,
        results=results_slow,
        total_duration_seconds=3.0,
        timestamp_utc=(now - timedelta(days=1)).isoformat(),
    )

    run3 = BenchmarkRun(
        run_id="run_003",
        model_id="facebook/m2m100_418M",
        device="cuda",
        batch_sizes=[16],
        iterations=1,
        corpus_category="general",
        purpose="gpu_test",
        tags=["gpu", "performance"],
        system_info=sysinfo_gpu,
        results=results_gpu,
        total_duration_seconds=0.5,
        timestamp_utc=now.isoformat(),
    )

    test_db.save_run(run1)
    test_db.save_run(run2)
    test_db.save_run(run3)

    return [run1, run2, run3]


def test_query_builder_by_model(test_db, sample_runs):
    """Test filtering by model ID."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder().by_model("facebook/m2m100_418M")
    results = api.query(builder)

    assert len(results) == 2
    assert all(r.model_id == "facebook/m2m100_418M" for r in results)


def test_query_builder_by_device(test_db, sample_runs):
    """Test filtering by device."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder().by_device("cpu")
    results = api.query(builder)

    assert len(results) == 2
    assert all(r.device == "cpu" for r in results)


def test_query_builder_by_hardware(test_db, sample_runs):
    """Test filtering by hardware specs."""
    api = BenchmarkQueryAPI(test_db)

    # Filter by CPU cores
    builder = BenchmarkQueryBuilder().by_hardware(cpu_cores=12)
    results = api.query(builder)
    assert len(results) == 2
    assert all(r.system_info.cpu_cores == 12 for r in results)

    # Filter by RAM range
    builder = BenchmarkQueryBuilder().by_hardware(ram_gb_min=60.0)
    results = api.query(builder)
    assert len(results) == 1
    assert results[0].system_info.total_ram_gb == 64.0


def test_query_builder_by_tags(test_db, sample_runs):
    """Test filtering by tags."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder().by_tags("gpu")
    results = api.query(builder)

    assert len(results) == 1
    assert "gpu" in results[0].tags


def test_query_builder_by_corpus_category(test_db, sample_runs):
    """Test filtering by corpus category."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder().by_corpus_category("technical")
    results = api.query(builder)

    assert len(results) == 2
    assert all(r.corpus_category == "technical" for r in results)


def test_query_builder_by_date_range(test_db, sample_runs):
    """Test filtering by date range."""
    api = BenchmarkQueryAPI(test_db)
    now = datetime.now()

    # Last 24 hours only
    builder = BenchmarkQueryBuilder().by_date_range(start=now - timedelta(hours=24))
    results = api.query(builder)

    assert len(results) == 1
    assert results[0].run_id == "run_003"


def test_query_builder_sort(test_db, sample_runs):
    """Test sorting results."""
    api = BenchmarkQueryAPI(test_db)

    # Sort by timestamp ascending
    builder = BenchmarkQueryBuilder().sort_by("timestamp_utc", ascending=True)
    results = api.query(builder)

    assert results[0].run_id == "run_001"
    assert results[-1].run_id == "run_003"


def test_query_builder_limit_offset(test_db, sample_runs):
    """Test pagination."""
    api = BenchmarkQueryAPI(test_db)

    # First page
    builder = BenchmarkQueryBuilder().limit(2).offset(0)
    results = api.query(builder)
    assert len(results) == 2

    # Second page
    builder = BenchmarkQueryBuilder().limit(2).offset(2)
    results = api.query(builder)
    assert len(results) == 1


def test_query_builder_chaining(test_db, sample_runs):
    """Test chaining multiple filters."""
    api = BenchmarkQueryAPI(test_db)

    builder = (
        BenchmarkQueryBuilder()
        .by_model("facebook/m2m100_418M")
        .by_device("cpu")
        .by_hardware(cpu_cores=12)
    )
    results = api.query(builder)

    assert len(results) == 1
    assert results[0].run_id == "run_001"


def test_aggregate_avg(test_db, sample_runs):
    """Test average aggregation."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder().by_device("cpu")

    avg_throughput = api.aggregate(builder, "throughput_tokens_per_sec", "avg")
    assert avg_throughput is not None
    assert 55.0 < avg_throughput < 65.0  # Average of 80 and 40


def test_aggregate_min_max(test_db, sample_runs):
    """Test min/max aggregation."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder()

    min_throughput = api.aggregate(builder, "throughput_tokens_per_sec", "min")
    max_throughput = api.aggregate(builder, "throughput_tokens_per_sec", "max")

    assert min_throughput == 40.0
    assert max_throughput == 240.0


def test_group_by(test_db, sample_runs):
    """Test grouping and aggregation."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder()

    grouped = api.group_by(builder, "device", "throughput_tokens_per_sec")

    assert "cpu" in grouped
    assert "cuda" in grouped
    assert grouped["cuda"] > grouped["cpu"]  # GPU faster


def test_find_best(test_db, sample_runs):
    """Test finding best runs."""
    api = BenchmarkQueryAPI(test_db)

    # Best overall
    best = api.find_best()
    assert len(best) == 1
    assert best[0].device == "cuda"  # GPU has highest throughput

    # Best on CPU only
    best_cpu = api.find_best(hardware_profile={"cpu_cores": 12})
    assert len(best_cpu) == 1
    assert best_cpu[0].device == "cpu"


def test_find_similar_hardware(test_db, sample_runs):
    """Test finding runs on similar hardware."""
    api = BenchmarkQueryAPI(test_db)

    # Find runs similar to CPU system
    target = SystemInfo(
        cpu_model="Intel i7-12700K",
        cpu_cores=12,
        total_ram_gb=30.0,  # Slightly different
        os_name="Linux",
        os_version="Ubuntu 22.04",
        python_version="3.11.0",
        torch_version="2.1.0",
        transformers_version="4.36.0",
    )

    similar = api.find_similar_hardware(target, tolerance=0.1)
    assert len(similar) >= 1
    assert all(abs(r.system_info.total_ram_gb - 30.0) / 30.0 <= 0.2 for r in similar)


def test_empty_results(test_db, sample_runs):
    """Test handling of empty results."""
    api = BenchmarkQueryAPI(test_db)

    # Query that returns nothing
    builder = BenchmarkQueryBuilder().by_model("nonexistent_model")
    results = api.query(builder)
    assert len(results) == 0

    # Aggregation on empty results
    avg = api.aggregate(builder, "throughput_tokens_per_sec", "avg")
    assert avg is None


def test_invalid_aggregation_function(test_db, sample_runs):
    """Test error handling for invalid aggregation function."""
    api = BenchmarkQueryAPI(test_db)
    builder = BenchmarkQueryBuilder()

    with pytest.raises(ValueError, match="Unknown aggregation function"):
        api.aggregate(builder, "throughput_tokens_per_sec", "invalid_func")


def test_build_sql_query():
    """Test SQL query generation."""
    builder = BenchmarkQueryBuilder()
    builder.by_model("test_model").by_device("cpu").limit(10)

    sql, params = builder.build()

    assert "SELECT DISTINCT r.* FROM benchmark_runs r" in sql
    assert "r.model_id = ?" in sql
    assert "r.device = ?" in sql
    assert "LIMIT 10" in sql
    assert params == ["test_model", "cpu"]


def test_build_sql_with_joins():
    """Test SQL query with system_info join."""
    builder = BenchmarkQueryBuilder()
    builder.by_hardware(cpu_cores=12, ram_gb_min=30.0)

    sql, params = builder.build()

    assert "LEFT JOIN system_info s ON r.run_id = s.run_id" in sql
    assert "s.cpu_cores = ?" in sql
    assert "s.total_ram_gb >= ?" in sql
    assert params == [12, 30.0]


def test_schema_migration_v2(test_db):
    """Test that schema migration to v2 was applied."""
    assert test_db.get_schema_version() == 2

    # Verify indices exist by querying sqlite_master
    conn = test_db._get_connection()
    try:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
        )
        indices = [row[0] for row in cursor.fetchall()]

        # Check for v2 indices
        assert "idx_runs_model_device" in indices
        assert "idx_runs_model_device_timestamp" in indices
        assert "idx_sysinfo_cpu_ram" in indices
        assert "idx_results_throughput" in indices
    finally:
        test_db._close_connection(conn)
