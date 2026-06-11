"""
Tests for GPU Manager.

Tests GPU detection, configuration, memory management, and fallback logic.
"""

import json
import platform
from unittest.mock import patch

import pytest
import torch

from src.hardware.gpu_manager import (
    GPUCapabilities,
    GPUInfo,
    GPUManager,
    GPUMemoryInfo,
)


class TestGPUMemoryInfo:
    """Tests for GPUMemoryInfo dataclass."""

    def test_create_memory_info(self):
        """Test creating GPUMemoryInfo."""
        mem = GPUMemoryInfo(
            total_mb=8192.0,
            used_mb=2048.0,
            free_mb=6144.0,
            reserved_mb=512.0,
        )

        assert mem.total_mb == 8192.0
        assert mem.used_mb == 2048.0
        assert mem.free_mb == 6144.0
        assert mem.reserved_mb == 512.0

    def test_to_dict(self):
        """Test converting to dictionary."""
        mem = GPUMemoryInfo(
            total_mb=8192.0,
            used_mb=2048.0,
            free_mb=6144.0,
        )

        data = mem.to_dict()
        assert data["total_mb"] == 8192.0
        assert data["used_mb"] == 2048.0
        assert data["free_mb"] == 6144.0


class TestGPUInfo:
    """Tests for GPUInfo dataclass."""

    def test_create_gpu_info(self):
        """Test creating GPUInfo."""
        mem = GPUMemoryInfo(total_mb=8192.0, used_mb=2048.0, free_mb=6144.0)
        gpu = GPUInfo(
            id=0,
            name="NVIDIA GeForce RTX 3080",
            compute_capability="8.6",
            total_memory_mb=10240.0,
            current_memory=mem,
        )

        assert gpu.id == 0
        assert gpu.name == "NVIDIA GeForce RTX 3080"
        assert gpu.compute_capability == "8.6"
        assert gpu.total_memory_mb == 10240.0
        assert gpu.current_memory == mem

    def test_to_dict(self):
        """Test converting to dictionary."""
        mem = GPUMemoryInfo(total_mb=8192.0, used_mb=2048.0, free_mb=6144.0)
        gpu = GPUInfo(
            id=0,
            name="NVIDIA GeForce RTX 3080",
            compute_capability="8.6",
            total_memory_mb=10240.0,
            current_memory=mem,
        )

        data = gpu.to_dict()
        assert data["id"] == 0
        assert data["name"] == "NVIDIA GeForce RTX 3080"
        assert "current_memory" in data


class TestGPUManager:
    """Tests for GPUManager."""

    def test_init_default_config(self):
        """Test initialization with default config."""
        manager = GPUManager()

        assert manager.enable_gpu is True
        assert manager.max_gpu_memory_mb is None
        assert manager.gpu_device_id == -1
        assert manager.allow_cpu_fallback is True

    def test_init_custom_config(self):
        """Test initialization with custom config."""
        config = {
            "enable_gpu": False,
            "max_gpu_memory_mb": 4096,
            "gpu_device_id": 0,
            "allow_cpu_fallback": False,
        }
        manager = GPUManager(config)

        assert manager.enable_gpu is False
        assert manager.max_gpu_memory_mb == 4096
        assert manager.gpu_device_id == 0
        assert manager.allow_cpu_fallback is False

    def test_detect_capabilities(self):
        """Test detecting GPU capabilities."""
        manager = GPUManager()
        caps = manager.detect()

        # Basic assertions that work on both GPU and CPU systems
        assert isinstance(caps, GPUCapabilities)
        assert caps.cpu_count > 0
        assert caps.total_ram_gb > 0
        assert caps.platform == platform.platform()
        assert caps.python_version == platform.python_version()
        assert caps.recommended_device in ["cpu", "cuda", "cuda:0", "cuda:1"]

        # GPU-specific checks if CUDA available
        if torch.cuda.is_available():
            assert caps.has_cuda is True
            assert caps.device_count > 0
            assert caps.cuda_version is not None
            assert len(caps.devices) > 0
            assert caps.recommended_device.startswith("cuda")
        else:
            assert caps.has_cuda is False
            assert caps.device_count == 0
            assert caps.recommended_device == "cpu"

    def test_detect_caching(self):
        """Test that capabilities are cached."""
        manager = GPUManager()

        caps1 = manager.detect()
        caps2 = manager.get_capabilities()

        assert caps1 is caps2

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_get_device_info_cuda(self):
        """Test getting device info with CUDA."""
        manager = GPUManager()
        device_info = manager._get_device_info(0)

        assert isinstance(device_info, GPUInfo)
        assert device_info.id == 0
        assert device_info.name != ""
        assert device_info.total_memory_mb > 0
        assert device_info.compute_capability is not None
        assert device_info.current_memory is not None

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_get_gpu_memory_cuda(self):
        """Test getting GPU memory with CUDA."""
        manager = GPUManager()
        mem = manager.get_gpu_memory(0)

        assert mem is not None
        assert mem.total_mb > 0
        assert mem.free_mb >= 0
        assert mem.used_mb >= 0
        assert mem.reserved_mb >= 0

    def test_get_gpu_memory_no_cuda(self):
        """Test getting GPU memory without CUDA."""
        manager = GPUManager()

        with patch("torch.cuda.is_available", return_value=False):
            mem = manager.get_gpu_memory(0)
            assert mem is None

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_get_all_gpu_memory_cuda(self):
        """Test getting all GPU memory with CUDA."""
        manager = GPUManager()
        all_mem = manager.get_all_gpu_memory()

        assert isinstance(all_mem, dict)
        assert len(all_mem) == torch.cuda.device_count()
        assert 0 in all_mem
        assert all_mem[0].total_mb > 0

    def test_recommend_device_no_gpu(self):
        """Test device recommendation without GPU."""
        manager = GPUManager()

        with patch("torch.cuda.is_available", return_value=False):
            caps = manager.detect()
            assert caps.recommended_device == "cpu"

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_recommend_device_with_gpu(self):
        """Test device recommendation with GPU."""
        manager = GPUManager()
        caps = manager.detect()

        assert caps.recommended_device.startswith("cuda")

    def test_recommend_device_gpu_disabled(self):
        """Test device recommendation when GPU disabled in config."""
        config = {"enable_gpu": False}
        manager = GPUManager(config)

        caps = manager.detect()
        assert caps.recommended_device == "cpu"

    def test_recommend_device_specific_gpu(self):
        """Test recommending specific GPU device."""
        if not torch.cuda.is_available() or torch.cuda.device_count() < 1:
            pytest.skip("Need CUDA GPU for this test")

        config = {"gpu_device_id": 0}
        manager = GPUManager(config)

        caps = manager.detect()
        assert caps.recommended_device == "cuda:0"

    def test_validate_device_cpu(self):
        """Test validating CPU device."""
        manager = GPUManager()

        assert manager.validate_device("cpu") is True

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_validate_device_cuda(self):
        """Test validating CUDA device."""
        manager = GPUManager()

        assert manager.validate_device("cuda") is True
        assert manager.validate_device("cuda:0") is True

        # Invalid device ID
        invalid_id = torch.cuda.device_count() + 10
        assert manager.validate_device(f"cuda:{invalid_id}") is False

    def test_validate_device_no_cuda(self):
        """Test validating CUDA device without CUDA."""
        manager = GPUManager()

        with patch("torch.cuda.is_available", return_value=False):
            assert manager.validate_device("cuda") is False

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_enforce_memory_limit_cuda(self):
        """Test enforcing memory limit with CUDA."""
        config = {"max_gpu_memory_mb": 4096}
        manager = GPUManager(config)

        result = manager.enforce_memory_limit("cuda:0")
        assert result is True

        # Cleanup
        torch.cuda.set_per_process_memory_fraction(1.0, 0)

    def test_enforce_memory_limit_cpu(self):
        """Test enforcing memory limit on CPU (should do nothing)."""
        config = {"max_gpu_memory_mb": 4096}
        manager = GPUManager(config)

        result = manager.enforce_memory_limit("cpu")
        assert result is False

    def test_enforce_memory_limit_no_config(self):
        """Test enforcing memory limit without config."""
        manager = GPUManager()

        result = manager.enforce_memory_limit("cuda")
        assert result is False

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_clear_cache_cuda(self):
        """Test clearing GPU cache."""
        manager = GPUManager()

        # Allocate some memory
        x = torch.randn(1000, 1000, device="cuda")
        del x

        # Clear cache
        manager.clear_cache("cuda:0")

        # Should not raise error
        manager.clear_cache()

    def test_clear_cache_no_cuda(self):
        """Test clearing cache without CUDA."""
        manager = GPUManager()

        with patch("torch.cuda.is_available", return_value=False):
            # Should not raise error
            manager.clear_cache()

    def test_auto_select_device(self):
        """Test auto-selecting device."""
        manager = GPUManager()
        device = manager.auto_select_device()

        assert device in ["cpu", "cuda", "cuda:0", "cuda:1"]
        assert manager.validate_device(device)

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_auto_select_device_with_memory_limit(self):
        """Test auto-select with memory limit."""
        config = {"max_gpu_memory_mb": 2048}
        manager = GPUManager(config)

        device = manager.auto_select_device()
        assert device.startswith("cuda")

        # Cleanup
        if ":" in device:
            device_id = int(device.split(":")[1])
        else:
            device_id = 0
        torch.cuda.set_per_process_memory_fraction(1.0, device_id)

    def test_generate_report(self):
        """Test generating capabilities report."""
        manager = GPUManager()
        report = manager.generate_report()

        assert "# GPU Capabilities Report" in report
        assert "## System Information" in report
        assert "## GPU Detection" in report
        assert "## Configuration" in report
        assert "## Recommendations" in report

        # Check system info included
        assert "CPU Cores:" in report
        assert "Total RAM:" in report
        assert "Recommended Device:" in report

    def test_generate_report_with_file(self, tmp_path):
        """Test generating report to file."""
        manager = GPUManager()
        report_path = tmp_path / "gpu_report.md"

        report = manager.generate_report(report_path)

        assert report_path.exists()
        content = report_path.read_text(encoding="utf-8")
        assert "# GPU Capabilities Report" in content
        # Report should be the same (allow encoding differences)
        assert len(content) == len(report)

    def test_capabilities_to_dict(self):
        """Test converting capabilities to dict."""
        manager = GPUManager()
        caps = manager.detect()

        data = caps.to_dict()

        assert isinstance(data, dict)
        assert "has_cuda" in data
        assert "cpu_count" in data
        assert "devices" in data
        assert isinstance(data["devices"], list)

    def test_get_recommended_device(self):
        """Test getting recommended device."""
        manager = GPUManager()

        device1 = manager.get_recommended_device()
        assert device1 in ["cpu", "cuda", "cuda:0", "cuda:1"]

        # Should use cached
        device2 = manager.get_recommended_device()
        assert device1 == device2

        # Force re-detect
        device3 = manager.get_recommended_device(force_detect=True)
        assert device3 in ["cpu", "cuda", "cuda:0", "cuda:1"]

    def test_multi_gpu_selection(self):
        """Test multi-GPU selection logic."""
        if not torch.cuda.is_available() or torch.cuda.device_count() < 2:
            pytest.skip("Need multi-GPU system for this test")

        manager = GPUManager()
        caps = manager.detect()

        # Should have multiple devices
        assert len(caps.devices) >= 2

        # Should recommend device with most free memory
        recommended = caps.recommended_device
        assert recommended.startswith("cuda")


class TestGPUManagerCLI:
    """Tests for GPU Manager CLI."""

    def test_cli_detect(self, capsys):
        """Test CLI detection."""
        from src.hardware.gpu_manager import main

        with patch("sys.argv", ["gpu_manager.py", "--detect"]):
            main()

        captured = capsys.readouterr()
        assert "GPU CAPABILITIES DETECTION" in captured.out
        assert "CUDA Available:" in captured.out

    def test_cli_json(self, capsys):
        """Test CLI JSON output."""
        from src.hardware.gpu_manager import main

        with patch("sys.argv", ["gpu_manager.py", "--detect", "--json"]):
            main()

        captured = capsys.readouterr()
        data = json.loads(captured.out)

        assert "has_cuda" in data
        assert "cpu_count" in data
        assert "recommended_device" in data

    def test_cli_report(self, tmp_path):
        """Test CLI report generation."""
        from src.hardware.gpu_manager import main

        report_path = tmp_path / "gpu_report.md"

        with patch("sys.argv", ["gpu_manager.py", "--report", str(report_path)]):
            main()

        assert report_path.exists()
        content = report_path.read_text()
        assert "# GPU Capabilities Report" in content


class TestGPUManagerEdgeCases:
    """Test edge cases and error handling."""

    def test_invalid_device_string(self):
        """Test handling invalid device strings."""
        manager = GPUManager()

        assert manager.validate_device("invalid") is False
        assert manager.validate_device("cuda:abc") is False

    def test_memory_info_error_handling(self):
        """Test error handling when getting memory info fails."""
        manager = GPUManager()

        with patch("torch.cuda.get_device_properties", side_effect=Exception("Error")):
            mem = manager.get_gpu_memory(0)
            assert mem is None

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_device_info_without_nvidia_smi(self):
        """Test getting device info when nvidia-smi not available."""
        manager = GPUManager()

        with patch("subprocess.run", side_effect=FileNotFoundError):
            device_info = manager._get_device_info(0)

            # Should still work, just missing some info
            assert device_info.name != ""
            assert device_info.temperature is None
            assert device_info.driver_version is None

    def test_enforce_memory_limit_invalid_device(self):
        """Test enforcing memory limit on invalid device."""
        config = {"max_gpu_memory_mb": 4096}
        manager = GPUManager(config)

        result = manager.enforce_memory_limit("invalid:0")
        assert result is False

    def test_clear_cache_error_handling(self):
        """Test error handling when clearing cache fails."""
        manager = GPUManager()

        with patch("torch.cuda.empty_cache", side_effect=Exception("Error")):
            # Should not raise exception
            manager.clear_cache()

    def test_concurrent_detection(self):
        """Test thread-safe detection."""
        import threading

        manager = GPUManager()
        results = []

        def detect():
            caps = manager.detect()
            results.append(caps)

        threads = [threading.Thread(target=detect) for _ in range(5)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        # All should get same instance (cached)
        assert len(results) == 5
        assert all(r.cpu_count == results[0].cpu_count for r in results)


class TestGPUManagerIntegration:
    """Integration tests for GPU Manager."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_full_workflow_cuda(self):
        """Test complete workflow with CUDA."""
        config = {
            "enable_gpu": True,
            "max_gpu_memory_mb": 2048,
            "gpu_device_id": -1,
        }
        manager = GPUManager(config)

        # Detect
        caps = manager.detect()
        assert caps.has_cuda

        # Select device
        device = manager.auto_select_device()
        assert device.startswith("cuda")

        # Validate
        assert manager.validate_device(device)

        # Get memory
        mem = manager.get_gpu_memory(0)
        assert mem is not None

        # Clear cache
        manager.clear_cache(device)

        # Generate report
        report = manager.generate_report()
        assert len(report) > 0

        # Cleanup
        if ":" in device:
            device_id = int(device.split(":")[1])
        else:
            device_id = 0
        torch.cuda.set_per_process_memory_fraction(1.0, device_id)

    def test_full_workflow_cpu_only(self):
        """Test complete workflow without CUDA."""
        config = {"enable_gpu": False}
        manager = GPUManager(config)

        # Detect
        caps = manager.detect()
        assert caps.recommended_device == "cpu"

        # Select device
        device = manager.auto_select_device()
        assert device == "cpu"

        # Validate
        assert manager.validate_device(device)

        # Generate report
        report = manager.generate_report()
        assert len(report) > 0
        # When GPU is disabled via config, report should mention configuration
        assert "GPU Enabled: False" in report
