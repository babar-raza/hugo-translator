"""
Unit tests for LimitingEngine.

Tests resource limiting wrapper with mocked GPUManager and ResourceMonitor.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

# Mock dependencies before importing modules that need them
sys.modules["psutil"] = MagicMock()
sys.modules["torch"] = MagicMock()

from datetime import datetime

from src.benchmarking.resource_monitor import ResourceSnapshot
from src.hardware.gpu_manager import GPUMemoryInfo
from src.shared_engines.limiting_engine import LimitingEngine, ResourceLimits


class TestLimitingEngine(unittest.TestCase):
    """Test LimitingEngine wrapper."""

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_initialization_default_limits(self, mock_gpu_manager, mock_resource_monitor):
        """Test LimitingEngine initializes with default limits."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()

        self.assertIsNotNone(engine.limits)
        self.assertTrue(engine.limits.enable_gpu)
        self.assertEqual(engine.limits.gpu_device_id, -1)
        mock_gpu_manager.assert_called_once()
        mock_resource_monitor.assert_called_once()

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_initialization_custom_limits(self, mock_gpu_manager, mock_resource_monitor):
        """Test LimitingEngine initializes with custom limits."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        limits = ResourceLimits(
            max_cpu_percent=80.0,
            min_memory_mb=2048.0,
            max_gpu_memory_mb=4096,
            enable_gpu=True,
            gpu_device_id=0,
        )

        engine = LimitingEngine(limits=limits)

        self.assertEqual(engine.limits.max_cpu_percent, 80.0)
        self.assertEqual(engine.limits.min_memory_mb, 2048.0)
        self.assertEqual(engine.limits.max_gpu_memory_mb, 4096)
        self.assertTrue(engine.limits.enable_gpu)
        self.assertEqual(engine.limits.gpu_device_id, 0)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_check_resources_available_success(self, mock_gpu_manager, mock_resource_monitor):
        """Test check_resources_available() returns True when resources sufficient."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()

        # Mock sufficient resources
        mock_snapshot = ResourceSnapshot(
            cpu_percent=50.0,
            memory_percent=40.0,
            memory_available_mb=4096.0,
            gpu_memory_used_mb=2048.0,
            gpu_memory_available_mb=6144.0,
            timestamp=datetime.utcnow(),
        )
        mock_monitor_instance.get_current.return_value = mock_snapshot
        mock_resource_monitor.return_value = mock_monitor_instance

        limits = ResourceLimits(max_cpu_percent=80.0, min_memory_mb=2048.0, max_gpu_memory_mb=4096)
        engine = LimitingEngine(limits=limits)

        result = engine.check_resources_available(
            required_memory_mb=2048, required_gpu_memory_mb=4096, device_required="cuda"
        )

        self.assertTrue(result)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_check_resources_available_cpu_too_high(self, mock_gpu_manager, mock_resource_monitor):
        """Test check_resources_available() returns False when CPU usage too high."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()

        # Mock high CPU usage
        mock_snapshot = ResourceSnapshot(
            cpu_percent=95.0,  # Too high
            memory_percent=40.0,
            memory_available_mb=4096.0,
            gpu_memory_used_mb=2048.0,
            gpu_memory_available_mb=6144.0,
            timestamp=datetime.utcnow(),
        )
        mock_monitor_instance.get_current.return_value = mock_snapshot
        mock_resource_monitor.return_value = mock_monitor_instance

        limits = ResourceLimits(max_cpu_percent=80.0)
        engine = LimitingEngine(limits=limits)

        result = engine.check_resources_available()

        self.assertFalse(result)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_check_resources_available_insufficient_memory(
        self, mock_gpu_manager, mock_resource_monitor
    ):
        """Test check_resources_available() returns False when insufficient RAM."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()

        # Mock insufficient memory
        mock_snapshot = ResourceSnapshot(
            cpu_percent=50.0,
            memory_percent=40.0,
            memory_available_mb=1024.0,  # Too low
            gpu_memory_used_mb=2048.0,
            gpu_memory_available_mb=6144.0,
            timestamp=datetime.utcnow(),
        )
        mock_monitor_instance.get_current.return_value = mock_snapshot
        mock_resource_monitor.return_value = mock_monitor_instance

        limits = ResourceLimits(min_memory_mb=2048.0)
        engine = LimitingEngine(limits=limits)

        result = engine.check_resources_available()

        self.assertFalse(result)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_check_resources_available_insufficient_gpu_memory(
        self, mock_gpu_manager, mock_resource_monitor
    ):
        """Test check_resources_available() returns False when insufficient GPU memory."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()

        # Mock insufficient GPU memory
        mock_snapshot = ResourceSnapshot(
            cpu_percent=50.0,
            memory_percent=40.0,
            memory_available_mb=4096.0,
            gpu_memory_used_mb=6144.0,
            gpu_memory_available_mb=2048.0,  # Too low for requirement
            timestamp=datetime.utcnow(),
        )
        mock_monitor_instance.get_current.return_value = mock_snapshot
        mock_resource_monitor.return_value = mock_monitor_instance

        limits = ResourceLimits(max_gpu_memory_mb=4096)
        engine = LimitingEngine(limits=limits)

        result = engine.check_resources_available(
            required_gpu_memory_mb=4096, device_required="cuda"
        )

        self.assertFalse(result)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_wait_for_resources_success(self, mock_gpu_manager, mock_resource_monitor):
        """Test wait_for_resources() returns True when resources become available."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_monitor_instance.wait_for_resources.return_value = True
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        result = engine.wait_for_resources(required_memory_mb=2048, timeout=60)

        self.assertTrue(result)
        mock_monitor_instance.wait_for_resources.assert_called_once()

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_wait_for_resources_timeout(self, mock_gpu_manager, mock_resource_monitor):
        """Test wait_for_resources() returns False on timeout."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_monitor_instance.wait_for_resources.return_value = False
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        result = engine.wait_for_resources(required_memory_mb=2048, timeout=5)

        self.assertFalse(result)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_get_current_resources(self, mock_gpu_manager, mock_resource_monitor):
        """Test get_current_resources() returns ResourceSnapshot."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()

        mock_snapshot = ResourceSnapshot(
            cpu_percent=50.0,
            memory_percent=40.0,
            memory_available_mb=4096.0,
            gpu_memory_used_mb=2048.0,
            gpu_memory_available_mb=6144.0,
            timestamp=datetime.utcnow(),
        )
        mock_monitor_instance.get_current.return_value = mock_snapshot
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        snapshot = engine.get_current_resources()

        self.assertEqual(snapshot, mock_snapshot)
        self.assertEqual(snapshot.cpu_percent, 50.0)
        self.assertEqual(snapshot.memory_available_mb, 4096.0)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_get_gpu_memory(self, mock_gpu_manager, mock_resource_monitor):
        """Test get_gpu_memory() returns GPUMemoryInfo."""
        mock_gpu_instance = Mock()
        mock_memory_info = GPUMemoryInfo(
            total_mb=8192.0, used_mb=2048.0, free_mb=6144.0, reserved_mb=512.0
        )
        mock_gpu_instance.get_gpu_memory.return_value = mock_memory_info
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        mem_info = engine.get_gpu_memory(device_id=0)

        self.assertEqual(mem_info, mock_memory_info)
        self.assertEqual(mem_info.total_mb, 8192.0)
        self.assertEqual(mem_info.free_mb, 6144.0)
        mock_gpu_instance.get_gpu_memory.assert_called_once_with(device_id=0)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_get_all_gpu_memory(self, mock_gpu_manager, mock_resource_monitor):
        """Test get_all_gpu_memory() returns dict of GPUMemoryInfo."""
        mock_gpu_instance = Mock()
        mock_all_memory = {
            0: GPUMemoryInfo(total_mb=8192.0, used_mb=2048.0, free_mb=6144.0),
            1: GPUMemoryInfo(total_mb=8192.0, used_mb=4096.0, free_mb=4096.0),
        }
        mock_gpu_instance.get_all_gpu_memory.return_value = mock_all_memory
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        all_mem = engine.get_all_gpu_memory()

        self.assertEqual(all_mem, mock_all_memory)
        self.assertEqual(len(all_mem), 2)
        self.assertEqual(all_mem[0].free_mb, 6144.0)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_enforce_gpu_memory_limit(self, mock_gpu_manager, mock_resource_monitor):
        """Test enforce_gpu_memory_limit() delegates to GPUManager."""
        mock_gpu_instance = Mock()
        mock_gpu_instance.enforce_memory_limit.return_value = True
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        result = engine.enforce_gpu_memory_limit("cuda:0")

        self.assertTrue(result)
        mock_gpu_instance.enforce_memory_limit.assert_called_once_with(device="cuda:0")

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_clear_gpu_cache(self, mock_gpu_manager, mock_resource_monitor):
        """Test clear_gpu_cache() delegates to GPUManager."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        engine.clear_gpu_cache("cuda:0")

        mock_gpu_instance.clear_cache.assert_called_once_with(device="cuda:0")

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_auto_select_device(self, mock_gpu_manager, mock_resource_monitor):
        """Test auto_select_device() returns recommended device."""
        mock_gpu_instance = Mock()
        mock_gpu_instance.auto_select_device.return_value = "cuda:0"
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        device = engine.auto_select_device()

        self.assertEqual(device, "cuda:0")
        mock_gpu_instance.auto_select_device.assert_called_once()

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_get_limits(self, mock_gpu_manager, mock_resource_monitor):
        """Test get_limits() returns ResourceLimits."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        limits = ResourceLimits(max_cpu_percent=80.0, min_memory_mb=2048.0)
        engine = LimitingEngine(limits=limits)

        retrieved_limits = engine.get_limits()

        self.assertEqual(retrieved_limits, limits)
        self.assertEqual(retrieved_limits.max_cpu_percent, 80.0)
        self.assertEqual(retrieved_limits.min_memory_mb, 2048.0)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_update_limits(self, mock_gpu_manager, mock_resource_monitor):
        """Test update_limits() modifies limits at runtime."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()

        # Update limits
        engine.update_limits(max_cpu_percent=90.0, min_memory_mb=4096.0)

        self.assertEqual(engine.limits.max_cpu_percent, 90.0)
        self.assertEqual(engine.limits.min_memory_mb, 4096.0)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_update_limits_invalid_key(self, mock_gpu_manager, mock_resource_monitor):
        """Test update_limits() ignores invalid keys."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        original_cpu = engine.limits.max_cpu_percent

        # Try to update invalid field
        engine.update_limits(invalid_field="value")

        # Limits should remain unchanged
        self.assertEqual(engine.limits.max_cpu_percent, original_cpu)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_get_gpu_manager(self, mock_gpu_manager, mock_resource_monitor):
        """Test get_gpu_manager() returns underlying GPUManager."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        manager = engine.get_gpu_manager()

        self.assertEqual(manager, mock_gpu_instance)

    @patch("src.shared_engines.limiting_engine.ResourceMonitor")
    @patch("src.shared_engines.limiting_engine.GPUManager")
    def test_get_resource_monitor(self, mock_gpu_manager, mock_resource_monitor):
        """Test get_resource_monitor() returns underlying ResourceMonitor."""
        mock_gpu_instance = Mock()
        mock_gpu_manager.return_value = mock_gpu_instance
        mock_monitor_instance = Mock()
        mock_resource_monitor.return_value = mock_monitor_instance

        engine = LimitingEngine()
        monitor = engine.get_resource_monitor()

        self.assertEqual(monitor, mock_monitor_instance)


if __name__ == "__main__":
    unittest.main()
