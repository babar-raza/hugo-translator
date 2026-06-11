"""
Unit tests for Hardware Detection.
"""

import pytest
import torch

from src.model_runtime import HardwareDetector, HardwareInfo


class TestHardwareInfo:
    """Test HardwareInfo dataclass."""

    def test_hardware_info_creation(self):
        """Test creating HardwareInfo."""
        info = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16.0,
            has_cuda=True,
            cuda_devices=[{"id": 0, "name": "Tesla T4", "total_memory_gb": 16.0}],
            has_mps=False,
            recommended_device="cuda",
        )

        assert info.cpu_count == 8
        assert info.total_ram_gb == 16.0
        assert info.has_cuda is True
        assert len(info.cuda_devices) == 1
        assert info.recommended_device == "cuda"

    def test_hardware_info_to_dict(self):
        """Test HardwareInfo serialization."""
        info = HardwareInfo(
            cpu_count=4,
            total_ram_gb=8.0,
            has_cuda=False,
            has_mps=True,
            recommended_device="mps",
        )

        info_dict = info.to_dict()
        assert isinstance(info_dict, dict)
        assert info_dict["cpu_count"] == 4
        assert info_dict["total_ram_gb"] == 8.0
        assert info_dict["has_cuda"] is False
        assert info_dict["has_mps"] is True
        assert info_dict["recommended_device"] == "mps"


class TestHardwareDetector:
    """Test HardwareDetector functionality."""

    def test_detector_initialization(self):
        """Test creating HardwareDetector."""
        detector = HardwareDetector()
        assert detector is not None

    def test_detect_returns_hardware_info(self):
        """Test that detect() returns HardwareInfo."""
        detector = HardwareDetector()
        info = detector.detect()

        assert isinstance(info, HardwareInfo)
        assert info.cpu_count > 0
        assert info.total_ram_gb > 0
        assert isinstance(info.has_cuda, bool)
        assert isinstance(info.has_mps, bool)
        assert info.recommended_device in ["cuda", "mps", "cpu"]

    def test_detect_cpu_info(self):
        """Test CPU detection."""
        detector = HardwareDetector()
        info = detector.detect()

        # CPU count should be positive
        assert info.cpu_count > 0
        # RAM should be reasonable (at least 1GB for test environment)
        assert info.total_ram_gb >= 1.0

    def test_detect_cuda_consistency(self):
        """Test CUDA detection consistency with torch."""
        detector = HardwareDetector()
        info = detector.detect()

        # Our detection should match torch's detection
        assert info.has_cuda == torch.cuda.is_available()

        # If CUDA available, should have device info
        if info.has_cuda:
            assert len(info.cuda_devices) > 0
            assert info.cuda_devices[0]["total_memory_gb"] > 0

    def test_detect_mps_consistency(self):
        """Test MPS detection consistency."""
        detector = HardwareDetector()
        info = detector.detect()

        # MPS should be consistent with torch
        expected_mps = (
            torch.backends.mps.is_available() if hasattr(torch.backends, "mps") else False
        )
        assert info.has_mps == expected_mps

    def test_detect_platform_info(self):
        """Test platform information is populated."""
        detector = HardwareDetector()
        info = detector.detect()

        assert info.platform != ""
        assert info.python_version != ""

    def test_recommend_device_cuda_preferred(self):
        """Test device recommendation prefers CUDA."""
        detector = HardwareDetector()

        # Simulate CUDA with good VRAM
        device = detector._recommend_device(
            has_cuda=True,
            has_mps=False,
            cuda_devices=[{"total_memory_gb": 8.0}],
        )
        assert device == "cuda"

    def test_recommend_device_cuda_insufficient_vram(self):
        """Test device recommendation with insufficient CUDA VRAM."""
        detector = HardwareDetector()

        # Simulate CUDA with low VRAM
        device = detector._recommend_device(
            has_cuda=True,
            has_mps=False,
            cuda_devices=[{"total_memory_gb": 1.0}],  # Less than 2GB
        )
        # Should fall back to CPU
        assert device == "cpu"

    def test_recommend_device_mps_fallback(self):
        """Test device recommendation falls back to MPS."""
        detector = HardwareDetector()

        # Simulate no CUDA but MPS available
        device = detector._recommend_device(
            has_cuda=False,
            has_mps=True,
            cuda_devices=[],
        )
        assert device == "mps"

    def test_recommend_device_cpu_fallback(self):
        """Test device recommendation falls back to CPU."""
        detector = HardwareDetector()

        # Simulate no CUDA, no MPS
        device = detector._recommend_device(
            has_cuda=False,
            has_mps=False,
            cuda_devices=[],
        )
        assert device == "cpu"

    def test_get_recommendations(self):
        """Test getting hardware recommendations."""
        detector = HardwareDetector()
        info = detector.detect()

        recommendations = detector.get_recommendations(info)

        assert "device" in recommendations
        assert "warnings" in recommendations
        assert "suggestions" in recommendations
        assert isinstance(recommendations["warnings"], list)
        assert isinstance(recommendations["suggestions"], list)

    def test_get_recommendations_low_ram(self):
        """Test recommendations with low RAM."""
        detector = HardwareDetector()

        # Create info with low RAM
        info = HardwareInfo(
            cpu_count=2,
            total_ram_gb=2.0,  # Low RAM
            has_cuda=False,
            has_mps=False,
            recommended_device="cpu",
        )

        recommendations = detector.get_recommendations(info)

        # Should have warning about low RAM
        assert any("RAM" in w or "ram" in w.lower() for w in recommendations["warnings"])

    def test_get_recommendations_good_gpu(self):
        """Test recommendations with good GPU."""
        detector = HardwareDetector()

        # Create info with good GPU
        info = HardwareInfo(
            cpu_count=8,
            total_ram_gb=16.0,
            has_cuda=True,
            cuda_devices=[{"total_memory_gb": 12.0}],
            has_mps=False,
            recommended_device="cuda",
        )

        recommendations = detector.get_recommendations(info)

        # Should have suggestion about using GPU
        assert any("large model" in s.lower() or "GPU" in s for s in recommendations["suggestions"])

    def test_get_recommendations_no_gpu(self):
        """Test recommendations without GPU."""
        detector = HardwareDetector()

        # Create info without GPU
        info = HardwareInfo(
            cpu_count=4,
            total_ram_gb=8.0,
            has_cuda=False,
            has_mps=False,
            recommended_device="cpu",
        )

        recommendations = detector.get_recommendations(info)

        # Should have suggestion about CPU optimization
        assert any("CTranslate2" in s or "CPU" in s for s in recommendations["suggestions"])


class TestBenchmark:
    """Test benchmarking functionality."""

    @pytest.mark.slow
    def test_benchmark_device_cpu(self):
        """Test benchmarking on CPU."""
        detector = HardwareDetector()

        # Benchmark CPU (should always be available)
        result = detector.benchmark_device(
            device="cpu",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            num_iterations=3,  # Reduced for speed
        )

        # Should return valid results
        assert "samples_per_sec" in result
        assert "avg_time_ms" in result
        assert result["samples_per_sec"] > 0
        assert result["avg_time_ms"] > 0

    @pytest.mark.slow
    @pytest.mark.skipif(not torch.cuda.is_available(), reason="CUDA not available")
    def test_benchmark_device_cuda(self):
        """Test benchmarking on CUDA."""
        detector = HardwareDetector()

        result = detector.benchmark_device(
            device="cuda",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            num_iterations=3,
        )

        # Should return valid results
        assert "samples_per_sec" in result
        assert "avg_time_ms" in result
        assert result["samples_per_sec"] > 0

    def test_benchmark_device_invalid(self):
        """Test benchmarking with invalid device."""
        detector = HardwareDetector()

        result = detector.benchmark_device(
            device="invalid_device",
            model_name="sentence-transformers/all-MiniLM-L6-v2",
            num_iterations=2,
        )

        # Should return error
        assert "error" in result
        assert result["samples_per_sec"] == 0.0
