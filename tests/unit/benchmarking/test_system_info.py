"""
Unit tests for system_info.py.

Tests cover:
1. Basic collection with HardwareDetector integration
2. CPU-only scenario (no CUDA)
3. CUDA-present scenario with GPU details
4. Missing torch module (ImportError handling)
5. Path sanitization (no username leakage)
"""

import json
from unittest.mock import Mock, patch

import pytest

from src.benchmarking.system_info import SystemInfo, SystemInfoCollector
from src.model_runtime.hardware import HardwareInfo


@pytest.fixture
def mock_hardware_info_cpu_only():
    """Mock HardwareInfo for CPU-only system."""
    return HardwareInfo(
        cpu_count=8,
        total_ram_gb=16.0,
        has_cuda=False,
        cuda_devices=[],
        has_mps=False,
        recommended_device="cpu",
        platform="Windows-10-10.0.19041",
        python_version="3.10.11",
    )


@pytest.fixture
def mock_hardware_info_with_cuda():
    """Mock HardwareInfo for system with CUDA GPU."""
    return HardwareInfo(
        cpu_count=12,
        total_ram_gb=32.0,
        has_cuda=True,
        cuda_devices=[
            {
                "id": 0,
                "name": "NVIDIA GeForce RTX 3080",
                "total_memory_gb": 10.0,
                "compute_capability": "8.6",
            }
        ],
        has_mps=False,
        recommended_device="cuda",
        platform="Linux-5.15.0-58-generic",
        python_version="3.10.11",
    )


class TestSystemInfo:
    """Test SystemInfo dataclass."""

    def test_to_dict(self):
        """Test conversion to dictionary."""
        system_info = SystemInfo(
            cpu_model="Intel Core i7-9700K",
            cpu_cores=8,
            total_ram_gb=16.0,
            gpu_model="NVIDIA RTX 3080",
            gpu_memory_gb=10.0,
            has_cuda=True,
            os_name="Windows",
            os_version="10",
            platform_system="Windows",
            platform_release="10",
            python_version="3.10.11",
            python_implementation="CPython",
            torch_version="2.0.1",
            torch_cuda_available=True,
            collected_at_utc="2025-01-15T12:00:00+00:00",
        )

        result = system_info.to_dict()

        assert isinstance(result, dict)
        assert result["cpu_model"] == "Intel Core i7-9700K"
        assert result["cpu_cores"] == 8
        assert result["total_ram_gb"] == 16.0
        assert result["gpu_model"] == "NVIDIA RTX 3080"
        assert result["has_cuda"] is True

    def test_from_dict(self):
        """Test creation from dictionary."""
        data = {
            "cpu_model": "AMD Ryzen 9 5900X",
            "cpu_cores": 12,
            "total_ram_gb": 32.0,
            "gpu_model": None,
            "gpu_memory_gb": None,
            "gpu_compute_capability": None,
            "has_cuda": False,
            "cuda_version": None,
            "os_name": "Linux",
            "os_version": "5.15.0",
            "platform_system": "Linux",
            "platform_release": "5.15.0",
            "python_version": "3.11.3",
            "python_implementation": "CPython",
            "torch_version": "2.1.0",
            "torch_cuda_available": False,
            "collected_at_utc": "2025-01-15T12:00:00+00:00",
            "collector_version": "1.0.0",
        }

        system_info = SystemInfo.from_dict(data)

        assert system_info.cpu_model == "AMD Ryzen 9 5900X"
        assert system_info.cpu_cores == 12
        assert system_info.has_cuda is False
        assert system_info.gpu_model is None


class TestSystemInfoCollector:
    """Test SystemInfoCollector class."""

    @patch("src.benchmarking.system_info.platform.processor")
    @patch("src.benchmarking.system_info.HardwareDetector")
    def test_collect_cpu_only(
        self, mock_detector_class, mock_processor, mock_hardware_info_cpu_only
    ):
        """Test collection on CPU-only system."""
        # Setup mocks
        mock_processor.return_value = "Intel(R) Core(TM) i7-9700K CPU @ 3.60GHz"
        mock_detector = Mock()
        mock_detector.detect.return_value = mock_hardware_info_cpu_only
        mock_detector_class.return_value = mock_detector

        # Collect
        collector = SystemInfoCollector()
        system_info = collector.collect()

        # Verify
        assert system_info.cpu_cores == 8
        assert system_info.total_ram_gb == 16.0
        assert system_info.has_cuda is False
        assert system_info.gpu_model is None
        assert system_info.gpu_memory_gb is None
        assert system_info.cuda_version is None
        assert "i7-9700K" in system_info.cpu_model
        assert system_info.python_version is not None
        assert system_info.collected_at_utc is not None

    @patch("src.benchmarking.system_info.platform.processor")
    @patch("src.benchmarking.system_info.HardwareDetector")
    def test_collect_with_cuda(
        self,
        mock_detector_class,
        mock_processor,
        mock_hardware_info_with_cuda,
    ):
        """Test collection on system with CUDA GPU."""
        # Setup mocks
        mock_processor.return_value = "AMD Ryzen 9 5900X"

        # Mock torch module at import time
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.version.cuda = "11.8"

        mock_detector = Mock()
        mock_detector.detect.return_value = mock_hardware_info_with_cuda
        mock_detector_class.return_value = mock_detector

        # Patch torch import within the collector methods
        with patch.dict("sys.modules", {"torch": mock_torch}):
            # Collect
            collector = SystemInfoCollector()
            system_info = collector.collect()

        # Verify
        assert system_info.cpu_cores == 12
        assert system_info.total_ram_gb == 32.0
        assert system_info.has_cuda is True
        assert system_info.gpu_model == "NVIDIA GeForce RTX 3080"
        assert system_info.gpu_memory_gb == 10.0
        assert system_info.gpu_compute_capability == "8.6"
        assert system_info.cuda_version == "11.8"

    @patch("src.benchmarking.system_info.platform.processor")
    @patch("src.benchmarking.system_info.HardwareDetector")
    def test_collect_missing_torch(
        self, mock_detector_class, mock_processor, mock_hardware_info_cpu_only
    ):
        """Test collection when torch module is missing."""
        # Setup mocks
        mock_processor.return_value = "Intel Core i5"
        mock_detector = Mock()
        mock_detector.detect.return_value = mock_hardware_info_cpu_only
        mock_detector_class.return_value = mock_detector

        # Mock torch import failure in _collect_torch_info
        with patch.dict("sys.modules", {"torch": None}):
            collector = SystemInfoCollector()
            system_info = collector.collect()

        # Verify graceful handling
        assert system_info.torch_version is None
        assert system_info.torch_cuda_available is False
        # Other fields should still be populated
        assert system_info.cpu_cores == 8
        assert system_info.total_ram_gb == 16.0

    @patch("src.benchmarking.system_info.HardwareDetector")
    def test_path_sanitization(self, mock_detector_class, mock_hardware_info_cpu_only):
        """Test that paths are sanitized to prevent PII leakage."""
        mock_detector = Mock()
        mock_detector.detect.return_value = mock_hardware_info_cpu_only
        mock_detector_class.return_value = mock_detector

        collector = SystemInfoCollector()

        # Test various path patterns
        test_cases = [
            ("C:\\Users\\prora\\Documents", "C:/Users/<user>/Documents"),
            ("C:\\Users\\alice\\OneDrive\\Documents", "C:/Users/<user>/<user>/Documents"),
            ("/home/bob/.local/share", "/home/<user>/.local/share"),
            ("D:\\Users\\TestUser\\project", "D:/Users/<user>/project"),
            ("Regular string no paths", "Regular string no paths"),
        ]

        for input_str, expected in test_cases:
            result = collector._sanitize_string(input_str)
            assert result == expected, f"Failed for input: {input_str}"
            # Critical: no username should appear
            assert "prora" not in result.lower()
            assert "alice" not in result.lower()
            assert "bob" not in result.lower()
            assert "testuser" not in result.lower()

    @patch("src.benchmarking.system_info.platform.processor")
    @patch("src.benchmarking.system_info.HardwareDetector")
    def test_json_serializable(
        self, mock_detector_class, mock_processor, mock_hardware_info_cpu_only
    ):
        """Test that collected data is JSON-serializable."""
        mock_processor.return_value = "Intel Core i7"
        mock_detector = Mock()
        mock_detector.detect.return_value = mock_hardware_info_cpu_only
        mock_detector_class.return_value = mock_detector

        collector = SystemInfoCollector()
        system_info = collector.collect()

        # Should not raise
        json_data = json.dumps(system_info.to_dict())
        assert json_data is not None

        # Should be deserializable
        parsed = json.loads(json_data)
        assert parsed["cpu_cores"] == 8
        assert parsed["total_ram_gb"] == 16.0


class TestSystemInfoCLI:
    """Test CLI functionality."""

    @patch("src.benchmarking.system_info.SystemInfoCollector")
    def test_cli_stdout(self, mock_collector_class, capsys):
        """Test CLI output to stdout."""
        from src.benchmarking.system_info import main

        # Setup mock
        mock_collector = Mock()
        mock_system_info = SystemInfo(
            cpu_model="Test CPU",
            cpu_cores=4,
            total_ram_gb=8.0,
            os_name="TestOS",
            os_version="1.0",
            platform_system="TestOS",
            platform_release="1.0",
            python_version="3.10.0",
            python_implementation="CPython",
            collected_at_utc="2025-01-15T12:00:00+00:00",
        )
        mock_collector.collect.return_value = mock_system_info
        mock_collector_class.return_value = mock_collector

        # Run CLI
        with patch("sys.argv", ["system_info.py"]):
            exit_code = main()

        # Verify
        assert exit_code == 0
        captured = capsys.readouterr()
        assert "Test CPU" in captured.out
        assert "cpu_cores" in captured.out

    @patch("src.benchmarking.system_info.SystemInfoCollector")
    def test_cli_file_output(self, mock_collector_class, tmp_path):
        """Test CLI output to file."""
        from src.benchmarking.system_info import main

        # Setup mock
        mock_collector = Mock()
        mock_system_info = SystemInfo(
            cpu_model="Test CPU",
            cpu_cores=4,
            total_ram_gb=8.0,
            os_name="TestOS",
            os_version="1.0",
            platform_system="TestOS",
            platform_release="1.0",
            python_version="3.10.0",
            python_implementation="CPython",
            collected_at_utc="2025-01-15T12:00:00+00:00",
        )
        mock_collector.collect.return_value = mock_system_info
        mock_collector_class.return_value = mock_collector

        # Run CLI with file output
        output_file = tmp_path / "system_info.json"
        with patch("sys.argv", ["system_info.py", "--out", str(output_file)]):
            exit_code = main()

        # Verify
        assert exit_code == 0
        assert output_file.exists()
        data = json.loads(output_file.read_text())
        assert data["cpu_model"] == "Test CPU"
        assert data["cpu_cores"] == 4


class TestGPUMemoryHelpers:
    """Test GPU memory helper static methods (BM04C-02)."""

    def test_get_available_gpu_memory_cuda_available(self):
        """Test get_available_gpu_memory_mb when CUDA is available."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.mem_get_info.return_value = (
            4096 * 1024**2,
            8192 * 1024**2,
        )  # 4GB free, 8GB total

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_available_gpu_memory_mb(device_id=0)

        assert result is not None
        assert result == pytest.approx(4096.0, rel=0.01)
        mock_torch.cuda.mem_get_info.assert_called_once_with(0)

    def test_get_available_gpu_memory_cuda_unavailable(self):
        """Test get_available_gpu_memory_mb when CUDA is unavailable."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_available_gpu_memory_mb(device_id=0)

        assert result is None

    def test_get_available_gpu_memory_invalid_device_id(self):
        """Test get_available_gpu_memory_mb with invalid device_id."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_available_gpu_memory_mb(device_id=5)

        assert result is None

    def test_get_available_gpu_memory_torch_not_installed(self):
        """Test get_available_gpu_memory_mb when torch is not installed."""
        with patch.dict("sys.modules", {"torch": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'torch'")):
                result = SystemInfoCollector.get_available_gpu_memory_mb(device_id=0)

        assert result is None

    def test_get_gpu_memory_stats_cuda_available(self):
        """Test get_gpu_memory_stats when CUDA is available."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 1
        mock_torch.cuda.mem_get_info.return_value = (
            4096 * 1024**2,
            8192 * 1024**2,
        )  # 4GB free, 8GB total
        mock_torch.cuda.memory_allocated.return_value = 2048 * 1024**2  # 2GB allocated
        mock_torch.cuda.memory_reserved.return_value = 3072 * 1024**2  # 3GB reserved

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_gpu_memory_stats(device_id=0)

        assert result is not None
        assert result["total_mb"] == pytest.approx(8192.0, rel=0.01)
        assert result["free_mb"] == pytest.approx(4096.0, rel=0.01)
        assert result["used_mb"] == pytest.approx(4096.0, rel=0.01)  # 8192 - 4096
        assert result["allocated_mb"] == pytest.approx(2048.0, rel=0.01)
        assert result["reserved_mb"] == pytest.approx(3072.0, rel=0.01)

        mock_torch.cuda.mem_get_info.assert_called_once_with(0)
        mock_torch.cuda.memory_allocated.assert_called_once_with(0)
        mock_torch.cuda.memory_reserved.assert_called_once_with(0)

    def test_get_gpu_memory_stats_cuda_unavailable(self):
        """Test get_gpu_memory_stats when CUDA is unavailable."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = False

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_gpu_memory_stats(device_id=0)

        assert result is None

    def test_get_gpu_memory_stats_invalid_device_id(self):
        """Test get_gpu_memory_stats with invalid device_id."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 2

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_gpu_memory_stats(device_id=5)

        assert result is None

    def test_get_gpu_memory_stats_torch_not_installed(self):
        """Test get_gpu_memory_stats when torch is not installed."""
        with patch.dict("sys.modules", {"torch": None}):
            with patch("builtins.__import__", side_effect=ImportError("No module named 'torch'")):
                result = SystemInfoCollector.get_gpu_memory_stats(device_id=0)

        assert result is None

    def test_get_gpu_memory_stats_multi_device(self):
        """Test get_gpu_memory_stats with multiple GPUs."""
        mock_torch = Mock()
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.device_count.return_value = 2

        # Device 0
        mock_torch.cuda.mem_get_info.return_value = (2048 * 1024**2, 8192 * 1024**2)
        mock_torch.cuda.memory_allocated.return_value = 1024 * 1024**2
        mock_torch.cuda.memory_reserved.return_value = 1536 * 1024**2

        with patch.dict("sys.modules", {"torch": mock_torch}):
            result = SystemInfoCollector.get_gpu_memory_stats(device_id=0)

        assert result is not None
        assert result["total_mb"] == pytest.approx(8192.0, rel=0.01)
        mock_torch.cuda.mem_get_info.assert_called_with(0)


@pytest.mark.benchmarking
class TestSystemInfoIntegration:
    """Integration tests (marked as benchmarking)."""

    def test_real_collection(self):
        """Test actual collection on real hardware (smoke test)."""
        collector = SystemInfoCollector()
        system_info = collector.collect()

        # Basic validation
        assert system_info.cpu_cores > 0
        assert system_info.total_ram_gb > 0
        assert system_info.cpu_model is not None
        assert system_info.os_name is not None
        assert system_info.python_version is not None

        # Check JSON serialization works
        json_data = json.dumps(system_info.to_dict())
        assert len(json_data) > 0

        # Critical: verify no username leakage
        json_lower = json_data.lower()
        # Note: This is a best-effort check. Specific usernames can be added.
        assert "prora" not in json_lower, "Username leaked in system info!"
