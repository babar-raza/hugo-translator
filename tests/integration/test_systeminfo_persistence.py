"""Integration tests for SystemInfo persistence with extended fields.

Tests verify that the comprehensive SystemInfo class from system_info.py
correctly persists and retrieves all 20+ fields through the storage layer.

Coverage:
- Extended hardware fields (CPU frequency, power state, etc.)
- GPU extended fields (compute capability, driver version)
- Round-trip accuracy (save → load → compare)
- NULL handling for optional fields
- Backward compatibility with v4 schema
"""

import tempfile
from pathlib import Path

import pytest

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun
from src.benchmarking.system_info import SystemInfo


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


def test_extended_fields_persist(temp_db):
    """Test all extended hardware fields persist correctly."""
    db = BenchmarkDatabase(temp_db)

    # Create comprehensive SystemInfo with all extended fields
    system_info = SystemInfo(
        # Core fields
        cpu_model="AMD Ryzen 9 7950X",
        cpu_cores=16,
        total_ram_gb=64.0,
        # GPU fields
        gpu_model="NVIDIA RTX 4090",
        gpu_memory_gb=24.0,
        gpu_compute_capability="8.9",
        has_cuda=True,
        cuda_version="12.1",
        gpu_driver_version="535.104.05",
        # Platform
        os_name="Linux",
        os_version="6.2.0",
        platform_system="Linux",
        platform_release="6.2.0-39-generic",
        # Python
        python_version="3.11.6",
        python_implementation="CPython",
        # PyTorch
        torch_version="2.1.2",
        torch_cuda_available=True,
        # Extended CPU fields (BM-09)
        cpu_frequency_mhz=4500.0,
        cpu_frequency_max_mhz=5700.0,
        cpu_tdp_watts=170.0,
        memory_bandwidth_gbps=89.6,
        numa_nodes=1,
        # Power management
        power_management_state="performance",
        # Metadata
        collected_at_utc="2025-12-19T12:00:00Z",
        collector_version="1.0.1",
    )

    # Create and save a benchmark run
    run = BenchmarkRun(
        run_id="test_extended_001",
        model_id="test_model",
        device="cuda",
        batch_sizes=[8],
        iterations=1,
        corpus_category="test",
        purpose="testing extended fields",
        tags=["integration", "extended"],
        system_info=system_info,
        results=[
            BenchmarkResult(
                sample_id="sample_001",
                model_id="test_model",
                device="cuda",
                batch_size=8,
                duration_seconds=1.5,
                tokens_input=100,
                tokens_output=50,
                throughput_tokens_per_sec=100.0,
                peak_memory_mb=1024.0,
            )
        ],
        total_duration_seconds=1.5,
    )

    db.save_run(run)

    # Retrieve and verify
    retrieved = db.get_run("test_extended_001")
    assert retrieved is not None
    si = retrieved.system_info

    # Verify core fields
    assert si.cpu_model == "AMD Ryzen 9 7950X"
    assert si.cpu_cores == 16
    assert si.total_ram_gb == 64.0

    # Verify GPU fields
    assert si.gpu_model == "NVIDIA RTX 4090"
    assert si.gpu_memory_gb == 24.0
    assert si.gpu_compute_capability == "8.9"
    assert si.has_cuda is True
    assert si.cuda_version == "12.1"
    assert si.gpu_driver_version == "535.104.05"

    # Verify platform fields
    assert si.os_name == "Linux"
    assert si.os_version == "6.2.0"
    assert si.platform_system == "Linux"
    assert si.platform_release == "6.2.0-39-generic"

    # Verify Python fields
    assert si.python_version == "3.11.6"
    assert si.python_implementation == "CPython"

    # Verify PyTorch fields
    assert si.torch_version == "2.1.2"
    assert si.torch_cuda_available is True

    # Verify extended CPU fields (BM-09)
    assert si.cpu_frequency_mhz == 4500.0
    assert si.cpu_frequency_max_mhz == 5700.0
    assert si.cpu_tdp_watts == 170.0
    assert si.memory_bandwidth_gbps == 89.6
    assert si.numa_nodes == 1

    # Verify power management
    assert si.power_management_state == "performance"

    # Verify metadata
    assert si.collected_at_utc == "2025-12-19T12:00:00Z"
    assert si.collector_version == "1.0.1"


def test_round_trip_accuracy(temp_db):
    """Test save/load preserves all data exactly."""
    db = BenchmarkDatabase(temp_db)

    # Create SystemInfo with various field combinations
    original = SystemInfo(
        cpu_model="Intel Core i9-13900K",
        cpu_cores=24,
        total_ram_gb=128.0,
        gpu_model="NVIDIA RTX 3090",
        gpu_memory_gb=24.0,
        gpu_compute_capability="8.6",
        has_cuda=True,
        cuda_version="11.8",
        os_name="Windows",
        os_version="11",
        python_version="3.10.11",
        torch_version="2.0.1",
        cpu_frequency_mhz=3000.0,
        cpu_frequency_max_mhz=5800.0,
        collected_at_utc="2025-12-19T14:30:00Z",
    )

    # Save
    run = BenchmarkRun(
        run_id="test_roundtrip_001",
        model_id="test_model",
        device="cuda",
        batch_sizes=[4],
        iterations=1,
        corpus_category="test",
        purpose="round-trip test",
        tags=["roundtrip"],
        system_info=original,
        results=[],
        total_duration_seconds=0.0,
    )
    db.save_run(run)

    # Load
    retrieved = db.get_run("test_roundtrip_001")
    assert retrieved is not None
    loaded = retrieved.system_info

    # Compare all fields
    assert loaded.cpu_model == original.cpu_model
    assert loaded.cpu_cores == original.cpu_cores
    assert loaded.total_ram_gb == original.total_ram_gb
    assert loaded.gpu_model == original.gpu_model
    assert loaded.gpu_memory_gb == original.gpu_memory_gb
    assert loaded.gpu_compute_capability == original.gpu_compute_capability
    assert loaded.has_cuda == original.has_cuda
    assert loaded.cuda_version == original.cuda_version
    assert loaded.os_name == original.os_name
    assert loaded.os_version == original.os_version
    assert loaded.python_version == original.python_version
    assert loaded.torch_version == original.torch_version
    assert loaded.cpu_frequency_mhz == original.cpu_frequency_mhz
    assert loaded.cpu_frequency_max_mhz == original.cpu_frequency_max_mhz
    assert loaded.collected_at_utc == original.collected_at_utc


def test_null_handling(temp_db):
    """Test optional fields handle NULL gracefully."""
    db = BenchmarkDatabase(temp_db)

    # Create SystemInfo with minimal required fields (many NULLs)
    minimal = SystemInfo(
        cpu_model="Generic CPU",
        cpu_cores=4,
        total_ram_gb=8.0,
        # All optional fields left as default (None or False)
    )

    # Save
    run = BenchmarkRun(
        run_id="test_null_001",
        model_id="test_model",
        device="cpu",
        batch_sizes=[2],
        iterations=1,
        corpus_category="test",
        purpose="NULL handling test",
        tags=["null"],
        system_info=minimal,
        results=[],
        total_duration_seconds=0.0,
    )
    db.save_run(run)

    # Load and verify NULLs handled correctly
    retrieved = db.get_run("test_null_001")
    assert retrieved is not None
    si = retrieved.system_info

    # Required fields present
    assert si.cpu_model == "Generic CPU"
    assert si.cpu_cores == 4
    assert si.total_ram_gb == 8.0

    # Optional fields are None or default
    assert si.gpu_model is None
    assert si.gpu_memory_gb is None
    assert si.gpu_compute_capability is None
    assert si.has_cuda is False
    assert si.cuda_version is None
    assert si.gpu_driver_version is None
    assert si.cpu_frequency_mhz is None
    assert si.cpu_frequency_max_mhz is None
    assert si.cpu_tdp_watts is None
    assert si.memory_bandwidth_gbps is None
    assert si.numa_nodes == 1  # Default value
    assert si.power_management_state is None


def test_gpu_fields_persist_correctly(temp_db):
    """Test GPU-specific extended fields persist correctly."""
    db = BenchmarkDatabase(temp_db)

    system_info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=32.0,
        # GPU fields
        gpu_model="NVIDIA A100",
        gpu_memory_gb=80.0,
        gpu_compute_capability="8.0",
        has_cuda=True,
        cuda_version="12.3",
        gpu_driver_version="545.23.08",
        torch_cuda_available=True,
    )

    run = BenchmarkRun(
        run_id="test_gpu_001",
        model_id="test_model",
        device="cuda",
        batch_sizes=[16],
        iterations=1,
        corpus_category="test",
        purpose="GPU fields test",
        tags=["gpu"],
        system_info=system_info,
        results=[],
        total_duration_seconds=0.0,
    )
    db.save_run(run)

    retrieved = db.get_run("test_gpu_001")
    assert retrieved is not None
    si = retrieved.system_info

    # Verify all GPU fields
    assert si.gpu_model == "NVIDIA A100"
    assert si.gpu_memory_gb == 80.0
    assert si.gpu_compute_capability == "8.0"
    assert si.has_cuda is True
    assert si.cuda_version == "12.3"
    assert si.gpu_driver_version == "545.23.08"
    assert si.torch_cuda_available is True


def test_multiple_runs_different_hardware(temp_db):
    """Test multiple runs with different hardware profiles."""
    db = BenchmarkDatabase(temp_db)

    # Run 1: High-end GPU system
    gpu_system = SystemInfo(
        cpu_model="AMD Threadripper 3990X",
        cpu_cores=64,
        total_ram_gb=256.0,
        gpu_model="NVIDIA H100",
        gpu_memory_gb=80.0,
        gpu_compute_capability="9.0",
        has_cuda=True,
        cuda_version="12.3",
        cpu_frequency_mhz=2900.0,
        cpu_frequency_max_mhz=4300.0,
        numa_nodes=4,
        power_management_state="performance",
    )

    # Run 2: CPU-only system
    cpu_system = SystemInfo(
        cpu_model="Intel Xeon Gold 6248R",
        cpu_cores=48,
        total_ram_gb=192.0,
        gpu_model=None,
        gpu_memory_gb=None,
        has_cuda=False,
        cpu_frequency_mhz=3000.0,
        numa_nodes=2,
        power_management_state="balanced",
    )

    # Save both runs
    for idx, (sys_info, device) in enumerate([(gpu_system, "cuda"), (cpu_system, "cpu")]):
        run = BenchmarkRun(
            run_id=f"test_multi_{idx:03d}",
            model_id="test_model",
            device=device,
            batch_sizes=[8],
            iterations=1,
            corpus_category="test",
            purpose="multiple hardware test",
            tags=["multi"],
            system_info=sys_info,
            results=[],
            total_duration_seconds=0.0,
        )
        db.save_run(run)

    # Verify both runs stored correctly
    gpu_run = db.get_run("test_multi_000")
    assert gpu_run is not None
    assert gpu_run.system_info.gpu_model == "NVIDIA H100"
    assert gpu_run.system_info.numa_nodes == 4

    cpu_run = db.get_run("test_multi_001")
    assert cpu_run is not None
    assert cpu_run.system_info.gpu_model is None
    assert cpu_run.system_info.numa_nodes == 2
    assert cpu_run.system_info.power_management_state == "balanced"


def test_schema_version_after_migration(temp_db):
    """Test database schema version is v5 after migration."""
    db = BenchmarkDatabase(temp_db)
    assert db.get_schema_version() == 10


def test_backward_compatibility_null_extended_fields(temp_db):
    """Test that runs created before v5 can still be read (NULL extended fields)."""
    db = BenchmarkDatabase(temp_db)

    # Simulate a minimal SystemInfo (like v4 would have created)
    minimal_system_info = SystemInfo(
        cpu_model="Legacy CPU",
        cpu_cores=2,
        total_ram_gb=4.0,
        # Only basic fields, extended fields will be NULL in DB
    )

    run = BenchmarkRun(
        run_id="test_legacy_001",
        model_id="test_model",
        device="cpu",
        batch_sizes=[1],
        iterations=1,
        corpus_category="test",
        purpose="backward compatibility test",
        tags=["legacy"],
        system_info=minimal_system_info,
        results=[],
        total_duration_seconds=0.0,
    )
    db.save_run(run)

    # Should retrieve without errors
    retrieved = db.get_run("test_legacy_001")
    assert retrieved is not None
    assert retrieved.system_info.cpu_model == "Legacy CPU"
    # Extended fields should have default values
    assert retrieved.system_info.cpu_frequency_mhz is None
    assert retrieved.system_info.gpu_driver_version is None
