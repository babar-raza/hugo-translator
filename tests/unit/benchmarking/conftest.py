"""Shared pytest fixtures for benchmarking tests."""

import gc
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun
from src.benchmarking.system_info import SystemInfo


@pytest.fixture
def temp_db():
    """Create a temporary database that is properly closed on cleanup.

    This fixture ensures the database is closed before the temp directory
    is removed, preventing file locking issues on Windows.
    """
    # Use ignore_cleanup_errors=True to handle Windows file locking
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        db_path = Path(tmpdir) / "test.db"
        db = BenchmarkDatabase(db_path)
        yield db
        # Close the database
        db.close()
        # Force garbage collection to release any lingering references
        gc.collect()
        # Extra cleanup for Windows: delete WAL files explicitly
        for ext in ["-wal", "-shm"]:
            wal_path = Path(str(db_path) + ext)
            if wal_path.exists():
                try:
                    wal_path.unlink()
                except PermissionError:
                    pass


@pytest.fixture
def memory_db():
    """Create an in-memory database for fast tests.

    In-memory databases don't have file locking issues.
    """
    db = BenchmarkDatabase(":memory:")
    yield db
    db.close()


@pytest.fixture
def make_system_info():
    """Factory for SystemInfo with sensible defaults.

    Usage:
        def test_something(make_system_info):
            info = make_system_info()  # All defaults
            info = make_system_info(cpu_cores=16)  # Override specific fields
    """

    def _factory(**kwargs):
        defaults = dict(
            cpu_model="Test CPU",
            cpu_cores=8,
            total_ram_gb=16.0,
            os_name="Linux",
            os_version="5.15.0",
            python_version="3.11.0",
            platform_system="Linux",
            platform_release="5.15.0-generic",
            python_implementation="CPython",
            collected_at_utc=datetime.now(timezone.utc).isoformat(),
        )
        defaults.update(kwargs)
        return SystemInfo(**defaults)

    return _factory


@pytest.fixture
def make_benchmark_result():
    """Factory for BenchmarkResult with sensible defaults.

    Usage:
        def test_something(make_benchmark_result):
            result = make_benchmark_result()  # All defaults
            result = make_benchmark_result(batch_size=16)  # Override specific fields
    """

    def _factory(sample_id="sample_001", **kwargs):
        defaults = dict(
            model_id="test_model",
            device="cpu",
            batch_size=8,
            duration_seconds=1.0,
            tokens_input=100,
            tokens_output=100,
            throughput_tokens_per_sec=200.0,
            peak_memory_mb=512.0,
        )
        defaults.update(kwargs)
        return BenchmarkResult(sample_id=sample_id, **defaults)

    return _factory


@pytest.fixture
def make_benchmark_run(make_system_info, make_benchmark_result):
    """Factory for BenchmarkRun with FK prerequisites.

    Usage:
        def test_something(make_benchmark_run):
            run = make_benchmark_run()  # All defaults
            run = make_benchmark_run(model_id="custom_model")  # Override specific fields
    """

    def _factory(run_id="test_run", with_results=False, **kwargs):
        defaults = dict(
            model_id="test_model",
            device="cpu",
            batch_sizes=[8],
            iterations=1,
            corpus_category="test",
            purpose="test",
            tags=[],
            system_info=make_system_info(),
            results=[make_benchmark_result()] if with_results else [],
            total_duration_seconds=1.0,
        )
        defaults.update(kwargs)
        return BenchmarkRun(run_id=run_id, **defaults)

    return _factory


@pytest.fixture
def sample_system_info(make_system_info):
    """Pre-built SystemInfo instance for simple tests."""
    return make_system_info()


@pytest.fixture
def sample_benchmark_run(make_benchmark_run):
    """Pre-built BenchmarkRun instance for simple tests."""
    return make_benchmark_run(with_results=True)
