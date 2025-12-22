"""
Unit tests for CPU optimizer.

Tests cover:
1. Low-RAM scenario (<8GB) - conservative batch size
2. High-RAM scenario (>=8GB) - normal batch size
3. Batch size bounds enforcement [1, 64]
4. Thread count computation (<=physical cores)
"""
import os
from unittest.mock import MagicMock, patch

import pytest

from src.model_runtime.cpu_optimizer import CPUOptimizer, RuntimeConfig


class TestCPUOptimizer:
    """Test suite for CPUOptimizer."""

    def test_low_ram_scenario(self):
        """Test conservative settings for low-RAM systems (<8GB)."""
        optimizer = CPUOptimizer()

        # Mock low-RAM system: 6GB total, 4GB available, 4 cores
        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 4 if not logical else 8
            mock_vm.return_value = MagicMock(
                total=6 * 1024**3, available=4 * 1024**3
            )

            config = optimizer.optimize()

            # Verify conservative batch size
            # Usable: 4GB - 2GB (MIN_FREE) = 2GB
            # Conservative: 2GB / (0.25GB * 2) = 4 batches
            assert config.batch_size == 4
            assert config.device == "cpu"
            assert config.num_threads == 4
            assert config.intra_threads == 4
            assert config.inter_threads == 1

            # Verify environment variables set
            assert os.environ.get("OMP_NUM_THREADS") == "4"
            assert os.environ.get("MKL_NUM_THREADS") == "4"

    def test_high_ram_scenario(self):
        """Test normal settings for high-RAM systems (>=8GB)."""
        optimizer = CPUOptimizer(memory_target_percent=0.7)

        # Mock high-RAM system: 16GB total, 12GB available, 8 cores
        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 8 if not logical else 16
            mock_vm.return_value = MagicMock(
                total=16 * 1024**3, available=12 * 1024**3
            )

            config = optimizer.optimize()

            # Verify normal batch size
            # Usable: 12GB * 0.7 - 2GB (MIN_FREE) = 6.4GB
            # Batch: 6.4GB / 0.25GB = 25.6 → 25
            assert config.batch_size == 25
            assert config.device == "cpu"
            # With 8 cores, reserve 1 → 7 threads
            assert config.num_threads == 7
            assert config.intra_threads == 7
            assert config.inter_threads == 1

            # Verify environment variables
            assert os.environ.get("OMP_NUM_THREADS") == "7"

    def test_batch_size_bounds(self):
        """Test batch size is bounded to [1, 64] for safety."""
        optimizer = CPUOptimizer()

        # Test lower bound: very low RAM
        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 2 if not logical else 4
            # 2GB total, 1GB available → too low for normal operation
            mock_vm.return_value = MagicMock(
                total=2 * 1024**3, available=1 * 1024**3
            )

            config = optimizer.optimize()
            assert config.batch_size >= CPUOptimizer.MIN_BATCH_SIZE
            assert config.batch_size == 1  # Should clamp to minimum

        # Test upper bound: override with huge value
        optimizer_override = CPUOptimizer(batch_size_override=1000)

        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 8 if not logical else 16
            mock_vm.return_value = MagicMock(
                total=64 * 1024**3, available=32 * 1024**3
            )

            config = optimizer_override.optimize()
            assert config.batch_size <= CPUOptimizer.MAX_BATCH_SIZE
            assert config.batch_size == 64  # Should clamp to maximum

    def test_thread_count_computation(self):
        """Test thread count is computed correctly based on physical cores."""
        optimizer = CPUOptimizer()

        # Test with 4 cores: should use all 4
        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 4 if not logical else 8
            mock_vm.return_value = MagicMock(
                total=8 * 1024**3, available=6 * 1024**3
            )

            config = optimizer.optimize()
            assert config.num_threads == 4

        # Test with 16 cores: should reserve 1 → 15
        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 16 if not logical else 32
            mock_vm.return_value = MagicMock(
                total=32 * 1024**3, available=24 * 1024**3
            )

            config = optimizer.optimize()
            assert config.num_threads == 15

        # Test thread override
        optimizer_override = CPUOptimizer(num_threads_override=6)

        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 8 if not logical else 16
            mock_vm.return_value = MagicMock(
                total=16 * 1024**3, available=12 * 1024**3
            )

            config = optimizer_override.optimize()
            assert config.num_threads == 6

        # Test override clamped to physical cores
        optimizer_high = CPUOptimizer(num_threads_override=100)

        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 4 if not logical else 8
            mock_vm.return_value = MagicMock(
                total=8 * 1024**3, available=6 * 1024**3
            )

            config = optimizer_high.optimize()
            assert config.num_threads == 4  # Clamped to physical cores

    def test_environment_variables_set(self):
        """Test that environment variables are set correctly."""
        optimizer = CPUOptimizer()

        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 6 if not logical else 12
            mock_vm.return_value = MagicMock(
                total=12 * 1024**3, available=8 * 1024**3
            )

            config = optimizer.optimize()

            # Verify all required env vars are set
            assert "OMP_NUM_THREADS" in os.environ
            assert "MKL_NUM_THREADS" in os.environ
            assert "NUMEXPR_MAX_THREADS" in os.environ

            thread_str = str(config.num_threads)
            assert os.environ["OMP_NUM_THREADS"] == thread_str
            assert os.environ["MKL_NUM_THREADS"] == thread_str
            assert os.environ["NUMEXPR_MAX_THREADS"] == thread_str

    def test_fallback_to_logical_cores(self):
        """Test fallback when physical core count unavailable."""
        optimizer = CPUOptimizer()

        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            # Simulate physical=None, logical=8
            mock_cpu.side_effect = lambda logical: 8 if logical else None
            mock_vm.return_value = MagicMock(
                total=8 * 1024**3, available=6 * 1024**3
            )

            config = optimizer.optimize()

            # Should fall back to logical cores and reserve 1 → 7
            assert config.num_threads == 7

    def test_runtime_config_dataclass(self):
        """Test RuntimeConfig dataclass behavior."""
        # Test with explicit intra_threads
        config1 = RuntimeConfig(batch_size=16, num_threads=4, intra_threads=4)
        assert config1.batch_size == 16
        assert config1.num_threads == 4
        assert config1.intra_threads == 4
        assert config1.inter_threads == 1
        assert config1.device == "cpu"

        # Test auto-setting of intra_threads
        config2 = RuntimeConfig(batch_size=8, num_threads=6)
        assert config2.intra_threads == 6  # Should auto-set to num_threads

    def test_memory_target_percent_clamping(self):
        """Test that memory_target_percent is clamped to [0.1, 0.9]."""
        # Test too low
        optimizer_low = CPUOptimizer(memory_target_percent=0.0)
        assert optimizer_low.memory_target_percent == 0.1

        # Test too high
        optimizer_high = CPUOptimizer(memory_target_percent=1.5)
        assert optimizer_high.memory_target_percent == 0.9

        # Test in range
        optimizer_normal = CPUOptimizer(memory_target_percent=0.7)
        assert optimizer_normal.memory_target_percent == 0.7

    def test_batch_size_override(self):
        """Test batch size override behavior."""
        optimizer = CPUOptimizer(batch_size_override=24)

        with patch("psutil.cpu_count") as mock_cpu, patch(
            "psutil.virtual_memory"
        ) as mock_vm:
            mock_cpu.side_effect = lambda logical: 8 if not logical else 16
            mock_vm.return_value = MagicMock(
                total=16 * 1024**3, available=12 * 1024**3
            )

            config = optimizer.optimize()
            assert config.batch_size == 24  # Override should be used
