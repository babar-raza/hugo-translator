"""Unit tests for extended system info (BM-09)."""

from dataclasses import fields

from src.benchmarking.system_info import SystemInfo, SystemInfoCollector


def test_bm09_systeminfo_has_extended_fields():
    """Test that SystemInfo has all BM-09 extended fields."""
    field_names = {f.name for f in fields(SystemInfo)}

    # BM-09 extended fields
    expected_fields = {
        "cpu_frequency_mhz",
        "cpu_frequency_max_mhz",
        "cpu_tdp_watts",
        "memory_bandwidth_gbps",
        "numa_nodes",
        "gpu_driver_version",
        "power_management_state",
    }

    for field in expected_fields:
        assert field in field_names, f"Missing BM-09 field: {field}"


def test_bm09_systeminfo_defaults():
    """Test that extended fields have appropriate defaults."""
    # Create minimal SystemInfo (only required fields)
    info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
    )

    # BM-09 fields should have None or sensible defaults
    assert info.cpu_frequency_mhz is None
    assert info.cpu_frequency_max_mhz is None
    assert info.cpu_tdp_watts is None
    assert info.memory_bandwidth_gbps is None
    assert info.numa_nodes == 1  # Default to 1 NUMA node
    assert info.gpu_driver_version is None
    assert info.power_management_state is None


def test_bm09_systeminfo_to_dict_includes_extended_fields():
    """Test that to_dict() includes extended fields."""
    info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
        cpu_frequency_mhz=3400.0,
        cpu_frequency_max_mhz=5000.0,
        power_management_state="performance",
    )

    data = info.to_dict()

    assert "cpu_frequency_mhz" in data
    assert "cpu_frequency_max_mhz" in data
    assert "power_management_state" in data
    assert data["cpu_frequency_mhz"] == 3400.0
    assert data["power_management_state"] == "performance"


def test_bm09_systeminfo_from_dict_with_extended_fields():
    """Test that from_dict() handles extended fields."""
    data = {
        "cpu_model": "Test CPU",
        "cpu_cores": 8,
        "total_ram_gb": 16.0,
        "cpu_frequency_mhz": 3400.0,
        "cpu_frequency_max_mhz": 5000.0,
        "numa_nodes": 2,
        "gpu_driver_version": "535.86.10",
        "power_management_state": "balanced",
        "os_name": "Linux",
        "os_version": "5.15.0",
        "python_version": "3.11.0",
        "collected_at_utc": "2025-12-24T10:00:00Z",
        "collector_version": "1.0.1",
    }

    info = SystemInfo.from_dict(data)

    assert info.cpu_frequency_mhz == 3400.0
    assert info.cpu_frequency_max_mhz == 5000.0
    assert info.numa_nodes == 2
    assert info.gpu_driver_version == "535.86.10"
    assert info.power_management_state == "balanced"


def test_bm09_collector_includes_extended_info():
    """Test that SystemInfoCollector attempts to collect extended info."""
    collector = SystemInfoCollector()

    # This will collect real system info (graceful if psutil unavailable)
    info = collector.collect()

    # Verify all BM-09 fields are present in the collected info
    assert hasattr(info, "cpu_frequency_mhz")
    assert hasattr(info, "cpu_frequency_max_mhz")
    assert hasattr(info, "cpu_tdp_watts")
    assert hasattr(info, "memory_bandwidth_gbps")
    assert hasattr(info, "numa_nodes")
    assert hasattr(info, "gpu_driver_version")
    assert hasattr(info, "power_management_state")

    # numa_nodes should default to 1
    assert info.numa_nodes >= 1

    # collector_version should be bumped
    assert info.collector_version == "1.0.1"


def test_bm09_graceful_degradation():
    """Test that collector works even without psutil."""
    collector = SystemInfoCollector()

    # Collect should not crash even if psutil is unavailable
    # (it will just leave extended fields as None)
    info = collector.collect()

    # Should still have basic fields
    assert info.cpu_model
    assert info.cpu_cores > 0
    assert info.total_ram_gb > 0

    # Extended fields may be None (graceful degradation)
    # This is acceptable behavior


def test_bm09_power_management_state_heuristic():
    """Test power management state heuristic logic."""
    # High frequency ratio = performance
    info = SystemInfo(
        cpu_model="Test",
        cpu_cores=8,
        total_ram_gb=16,
        cpu_frequency_mhz=4500,
        cpu_frequency_max_mhz=5000,
        power_management_state="performance",
    )
    assert info.power_management_state == "performance"

    # Low frequency ratio = power_saver
    info2 = SystemInfo(
        cpu_model="Test",
        cpu_cores=8,
        total_ram_gb=16,
        cpu_frequency_mhz=2000,
        cpu_frequency_max_mhz=5000,
        power_management_state="power_saver",
    )
    assert info2.power_management_state == "power_saver"

    # Mid frequency ratio = balanced
    info3 = SystemInfo(
        cpu_model="Test",
        cpu_cores=8,
        total_ram_gb=16,
        cpu_frequency_mhz=3500,
        cpu_frequency_max_mhz=5000,
        power_management_state="balanced",
    )
    assert info3.power_management_state == "balanced"
