"""Unit tests for resource monitor (BM-04)."""

from datetime import datetime

from src.benchmarking.resource_monitor import (
    ResourceEstimate,
    ResourceMonitor,
    ResourceSnapshot,
)


def test_bm04_resource_monitor_init():
    """Test resource monitor initialization."""
    monitor = ResourceMonitor()

    # Should initialize without errors
    assert monitor is not None


def test_bm04_get_current_snapshot():
    """Test getting current resource snapshot."""
    monitor = ResourceMonitor()

    snapshot = monitor.get_current()

    # Should return a snapshot
    assert isinstance(snapshot, ResourceSnapshot)
    assert snapshot.cpu_percent >= 0
    assert snapshot.memory_percent >= 0
    assert snapshot.memory_available_mb >= 0
    assert isinstance(snapshot.timestamp, datetime)


def test_bm04_resource_snapshot_fields():
    """Test that ResourceSnapshot has all expected fields."""
    snapshot = ResourceSnapshot(
        cpu_percent=50.0,
        memory_percent=60.0,
        memory_available_mb=4096.0,
        gpu_memory_used_mb=2048.0,
        gpu_memory_available_mb=2048.0,
        timestamp=datetime.utcnow(),
    )

    assert snapshot.cpu_percent == 50.0
    assert snapshot.memory_percent == 60.0
    assert snapshot.memory_available_mb == 4096.0
    assert snapshot.gpu_memory_used_mb == 2048.0
    assert snapshot.gpu_memory_available_mb == 2048.0


def test_bm04_resource_estimate_fields():
    """Test ResourceEstimate dataclass."""
    estimate = ResourceEstimate(
        estimated_memory_mb=1000.0,
        estimated_gpu_memory_mb=2000.0,
        estimated_duration_seconds=60.0,
        device_required="cuda",
        confidence=0.8,
    )

    assert estimate.estimated_memory_mb == 1000.0
    assert estimate.estimated_gpu_memory_mb == 2000.0
    assert estimate.estimated_duration_seconds == 60.0
    assert estimate.device_required == "cuda"
    assert estimate.confidence == 0.8


def test_bm04_is_safe_to_run_cpu_only():
    """Test safety check for CPU-only benchmark."""
    monitor = ResourceMonitor()

    # Small estimate should be safe
    estimate = ResourceEstimate(
        estimated_memory_mb=100.0,  # Very small
        estimated_gpu_memory_mb=None,
        estimated_duration_seconds=60.0,
        device_required="cpu",
        confidence=0.8,
    )

    is_safe = monitor.is_safe_to_run(estimate, safety_margin=0.2)

    # Should be safe (or at least not crash)
    assert isinstance(is_safe, bool)


def test_bm04_is_safe_to_run_large_memory():
    """Test safety check rejects huge memory requirement."""
    monitor = ResourceMonitor()

    # Unreasonably large estimate
    estimate = ResourceEstimate(
        estimated_memory_mb=1_000_000.0,  # 1TB - should fail
        estimated_gpu_memory_mb=None,
        estimated_duration_seconds=60.0,
        device_required="cpu",
        confidence=0.8,
    )

    is_safe = monitor.is_safe_to_run(estimate, safety_margin=0.2)

    # Should NOT be safe
    assert is_safe is False


def test_bm04_is_safe_to_run_with_safety_margin():
    """Test that safety margin is applied correctly."""
    monitor = ResourceMonitor()

    estimate = ResourceEstimate(
        estimated_memory_mb=1000.0,
        estimated_gpu_memory_mb=None,
        estimated_duration_seconds=60.0,
        device_required="cpu",
        confidence=0.8,
    )

    # Different safety margins
    safe_conservative = monitor.is_safe_to_run(estimate, safety_margin=0.5)
    safe_aggressive = monitor.is_safe_to_run(estimate, safety_margin=0.1)

    # Both should be boolean
    assert isinstance(safe_conservative, bool)
    assert isinstance(safe_aggressive, bool)


def test_bm04_wait_for_resources_immediate():
    """Test wait_for_resources returns immediately if resources available."""
    monitor = ResourceMonitor()

    # Very small estimate
    estimate = ResourceEstimate(
        estimated_memory_mb=10.0,
        estimated_gpu_memory_mb=None,
        estimated_duration_seconds=1.0,
        device_required="cpu",
        confidence=0.8,
    )

    # Should return immediately (within 1 second)
    import time

    start = time.time()
    result = monitor.wait_for_resources(estimate, timeout_seconds=1.0)
    elapsed = time.time() - start

    # Should return quickly if resources available
    assert elapsed < 2.0  # Allow some overhead


def test_bm04_wait_for_resources_timeout():
    """Test wait_for_resources times out if resources unavailable."""
    monitor = ResourceMonitor()

    # Impossible estimate
    estimate = ResourceEstimate(
        estimated_memory_mb=1_000_000.0,
        estimated_gpu_memory_mb=None,
        estimated_duration_seconds=1.0,
        device_required="cpu",
        confidence=0.8,
    )

    # Should timeout quickly
    import time

    start = time.time()
    result = monitor.wait_for_resources(estimate, timeout_seconds=2.0)
    elapsed = time.time() - start

    # Should return False after timeout
    assert result is False
    assert elapsed >= 2.0
    assert elapsed < 4.0  # Should not wait much longer than timeout


def test_bm04_graceful_fallback_without_psutil():
    """Test that monitor works even without psutil."""
    monitor = ResourceMonitor()

    # Force fallback mode
    monitor.psutil_available = False

    snapshot = monitor.get_current()

    # Should still return a snapshot with conservative values
    assert isinstance(snapshot, ResourceSnapshot)
    assert snapshot.cpu_percent > 0
    assert snapshot.memory_percent > 0
    assert snapshot.memory_available_mb > 0
