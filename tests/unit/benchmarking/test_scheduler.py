"""Unit tests for benchmark scheduler (BM-04)."""

import pytest
from pathlib import Path
import tempfile

from src.benchmarking.scheduler import (
    BenchmarkScheduler,
    ResourceEstimator,
    ScheduledBenchmark,
)
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.system_info import SystemInfo
from src.benchmarking.resource_monitor import ResourceEstimate


@pytest.fixture
def temp_db():
    """Create temporary database for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        db_path = Path(tmpdir) / "test_benchmark.db"
        db = BenchmarkDatabase(db_path)
        yield db


@pytest.fixture
def system_info():
    """Create test system info."""
    return SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
        os_name="Linux",
        os_version="5.15.0",
        python_version="3.11.0",
        collected_at_utc="2025-12-24T10:00:00Z",
    )


def test_bm04_resource_estimator():
    """Test ResourceEstimator estimates resources."""
    estimator = ResourceEstimator()
    system_info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
        os_name="Linux",
        os_version="5.15.0",
        python_version="3.11.0",
        collected_at_utc="2025-12-24T10:00:00Z",
    )

    config = {
        "model_id": "facebook/m2m100_418M",
        "device": "cpu",
        "batch_size": 4,
        "corpus_size": 100,
    }

    estimate = estimator.estimate(config, system_info)

    # Should return an estimate
    assert isinstance(estimate, ResourceEstimate)
    assert estimate.estimated_memory_mb > 0
    assert estimate.estimated_duration_seconds > 0
    assert estimate.device_required == "cpu"


def test_bm04_resource_estimator_scales_by_model_size():
    """Test that estimator scales by model size."""
    estimator = ResourceEstimator()
    system_info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
        os_name="Linux",
        os_version="5.15.0",
        python_version="3.11.0",
        collected_at_utc="2025-12-24T10:00:00Z",
    )

    small_config = {"model_id": "facebook/m2m100_418M", "device": "cpu", "batch_size": 1}

    large_config = {"model_id": "facebook/m2m100_1.2B", "device": "cpu", "batch_size": 1}

    small_estimate = estimator.estimate(small_config, system_info)
    large_estimate = estimator.estimate(large_config, system_info)

    # Large model should need more memory
    assert large_estimate.estimated_memory_mb > small_estimate.estimated_memory_mb


def test_bm04_scheduler_init_creates_queue_table(temp_db):
    """Test that scheduler creates queue table."""
    scheduler = BenchmarkScheduler(temp_db)

    # Verify table exists
    with temp_db._get_connection() as conn:
        cursor = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='benchmark_queue'"
        )
        assert cursor.fetchone() is not None


def test_bm04_schedule_job(temp_db):
    """Test scheduling a benchmark job."""
    scheduler = BenchmarkScheduler(temp_db)

    config = {
        "model_id": "test_model",
        "device": "cpu",
        "batch_size": 4,
    }

    job_id = scheduler.schedule(config, priority=5)

    # Should return a job ID
    assert job_id is not None
    assert isinstance(job_id, str)


def test_bm04_get_queue_status(temp_db):
    """Test getting queue status."""
    scheduler = BenchmarkScheduler(temp_db)

    # Schedule a job
    config = {"model_id": "test_model", "device": "cpu"}
    job_id = scheduler.schedule(config)

    # Get queue status
    status = scheduler.get_queue_status()

    # Should have the scheduled job
    assert len(status) == 1
    assert status[0].job_id == job_id
    assert status[0].status == "pending"


def test_bm04_queue_status_ordered_by_priority(temp_db):
    """Test that queue status is ordered by priority."""
    scheduler = BenchmarkScheduler(temp_db)

    # Schedule jobs with different priorities
    job_low = scheduler.schedule({"model_id": "test"}, priority=10)
    job_high = scheduler.schedule({"model_id": "test"}, priority=1)
    job_mid = scheduler.schedule({"model_id": "test"}, priority=5)

    status = scheduler.get_queue_status()

    # Should be ordered by priority (low number = high priority)
    pending = [j for j in status if j.status == "pending"]
    assert pending[0].job_id == job_high  # Priority 1 first
    assert pending[1].job_id == job_mid  # Priority 5 second
    assert pending[2].job_id == job_low  # Priority 10 last


def test_bm04_cancel_job(temp_db):
    """Test cancelling a pending job."""
    scheduler = BenchmarkScheduler(temp_db)

    # Schedule a job
    job_id = scheduler.schedule({"model_id": "test"})

    # Cancel it
    result = scheduler.cancel(job_id)

    assert result is True

    # Verify it's cancelled
    status = scheduler.get_queue_status()
    cancelled = [j for j in status if j.job_id == job_id]
    assert len(cancelled) == 1
    assert cancelled[0].status == "cancelled"


def test_bm04_cancel_nonexistent_job(temp_db):
    """Test cancelling a non-existent job."""
    scheduler = BenchmarkScheduler(temp_db)

    result = scheduler.cancel("nonexistent")

    # Should return False
    assert result is False


def test_bm04_can_run_now(temp_db):
    """Test checking if job can run now."""
    scheduler = BenchmarkScheduler(temp_db)

    # Schedule a small job
    config = {
        "model_id": "tiny_model",
        "device": "cpu",
        "batch_size": 1,
    }

    job_id = scheduler.schedule(config)

    # Check if can run
    can_run = scheduler.can_run_now(job_id)

    # Should be boolean
    assert isinstance(can_run, bool)


def test_bm04_scheduled_benchmark_fields():
    """Test ScheduledBenchmark dataclass."""
    from datetime import datetime

    estimate = ResourceEstimate(
        estimated_memory_mb=1000.0,
        estimated_gpu_memory_mb=None,
        estimated_duration_seconds=60.0,
        device_required="cpu",
        confidence=0.7,
    )

    job = ScheduledBenchmark(
        job_id="job_001",
        config={"model_id": "test"},
        priority=5,
        estimated_resources=estimate,
        status="pending",
        queued_at=datetime.utcnow(),
        started_at=None,
        completed_at=None,
    )

    assert job.job_id == "job_001"
    assert job.status == "pending"
    assert job.priority == 5


def test_bm04_scheduler_loads_config(temp_db):
    """Test scheduler loads config from file."""
    scheduler = BenchmarkScheduler(temp_db)

    # Should have loaded config (defaults at minimum)
    assert "max_cpu_percent" in scheduler.config
    assert "max_memory_percent" in scheduler.config


def test_bm04_scheduler_config_defaults(temp_db):
    """Test scheduler has sensible defaults."""
    scheduler = BenchmarkScheduler(temp_db)

    # Check defaults
    assert scheduler.config["max_cpu_percent"] == 80
    assert scheduler.config["max_memory_percent"] == 85
    assert scheduler.config["min_available_memory_mb"] == 1024


def test_bm04_run_all_with_empty_queue(temp_db):
    """Test run_all with empty queue."""
    scheduler = BenchmarkScheduler(temp_db)

    results = scheduler.run_all()

    # Should return empty list
    assert results == []


def test_bm04_integration_workflow(temp_db):
    """Integration test: schedule → check → cancel workflow."""
    scheduler = BenchmarkScheduler(temp_db)

    # 1. Schedule a job
    job_id = scheduler.schedule(
        {"model_id": "test_model", "device": "cpu"},
        priority=5,
    )

    # 2. Check queue status
    status = scheduler.get_queue_status()
    assert len(status) == 1
    assert status[0].status == "pending"

    # 3. Check if can run
    can_run = scheduler.can_run_now(job_id)
    assert isinstance(can_run, bool)

    # 4. Cancel the job
    cancelled = scheduler.cancel(job_id)
    assert cancelled is True

    # 5. Verify cancelled
    status = scheduler.get_queue_status()
    assert status[0].status == "cancelled"
