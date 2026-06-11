"""
Unit tests for WorkerRunner VRAM policy enforcement.

Tests that VRAM budgets are correctly applied in different execution modes.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.hardware.vram_enforcer import reset_enforcement_state
from src.workers.runner import (
    ExecutionMode,
    WorkerConfig,
    WorkerRunner,
)


@pytest.fixture(autouse=True)
def reset_vram_state():
    """Reset VRAM enforcement state before each test."""
    reset_enforcement_state()
    yield
    reset_enforcement_state()


@pytest.fixture
def mock_cuda():
    """Mock torch.cuda to simulate GPU presence."""
    with patch("src.workers.runner.torch") as mock_torch:
        # Simulate CUDA available
        mock_torch.cuda.is_available.return_value = True

        # Mock get_device_properties to return 8192 MB (8 GB) GPU
        mock_props = MagicMock()
        mock_props.total_memory = 8192 * 1024 * 1024  # 8 GB in bytes
        mock_torch.cuda.get_device_properties.return_value = mock_props

        # Mock set_per_process_memory_fraction
        mock_torch.cuda.set_per_process_memory_fraction = MagicMock()

        yield mock_torch


@pytest.fixture
def mock_vram_enforcer():
    """Mock VRAMEnforcer to track enforcement calls."""
    with patch("src.workers.runner.VRAMEnforcer") as MockVRAMEnforcer:
        mock_enforcer = MagicMock()
        MockVRAMEnforcer.return_value = mock_enforcer

        # Default return values
        mock_enforcer.enforce_from_config.return_value = (
            4915,
            MagicMock(percent=60.0, source="percent"),
        )

        yield mock_enforcer


class TestWorkerRunnerVRAMPolicy:
    """Test WorkerRunner VRAM enforcement policy."""

    def test_windows_cuda_applies_vram_enforcement(self, mock_cuda, mock_vram_enforcer):
        """Test that windows_cuda mode applies VRAM enforcement."""
        # Create config for windows_cuda mode
        config = WorkerConfig(
            execution_mode=ExecutionMode.WINDOWS_CUDA,
            worker_id="test-worker",
            device="cuda:0",
            mode_config={
                "max_gpu_memory_percent": 60,
                "max_gpu_memory_mb": None,
            },
        )

        # Create runner (this should apply VRAM enforcement in __init__)
        # We'll use a concrete subclass for testing
        class TestRunner(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        runner = TestRunner(config)

        # Check that VRAMEnforcer was called
        mock_vram_enforcer.enforce_from_config.assert_called_once()

        # Check the call arguments (device is passed as keyword arg)
        call_args = mock_vram_enforcer.enforce_from_config.call_args
        hardware_config = call_args[0][0]  # First positional arg
        device = call_args[1]["device"]  # Keyword arg

        assert hardware_config["enable_gpu"] is True
        assert hardware_config["max_gpu_memory_percent"] == 60
        assert hardware_config["max_gpu_memory_mb"] is None
        assert device == "cuda:0"

    def test_docker_gpu_applies_vram_enforcement(self, mock_cuda, mock_vram_enforcer):
        """Test that docker_gpu mode applies VRAM enforcement."""
        # Create config for docker_gpu mode
        config = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_GPU,
            worker_id="test-worker",
            device="cuda",
            mode_config={
                "max_gpu_memory_percent": 60,
                "max_gpu_memory_mb": None,
            },
        )

        # Create runner
        class TestRunner(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        runner = TestRunner(config)

        # Check that VRAMEnforcer was called
        mock_vram_enforcer.enforce_from_config.assert_called_once()

    def test_docker_cpu_skips_vram_enforcement(self, mock_cuda, mock_vram_enforcer):
        """Test that docker_cpu mode does NOT apply VRAM enforcement."""
        # Create config for docker_cpu mode
        config = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_CPU,
            worker_id="test-worker",
            device="cuda",  # Will be overridden to "cpu" by device policy
            mode_config={
                "max_gpu_memory_percent": 60,
                "max_gpu_memory_mb": None,
            },
        )

        # Create runner
        class TestRunner(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        runner = TestRunner(config)

        # Check that device was forced to CPU
        assert runner.config.device == "cpu"

        # Check that VRAMEnforcer was NOT called (device is CPU)
        mock_vram_enforcer.enforce_from_config.assert_not_called()

    def test_vram_enforcement_with_explicit_mb(self, mock_cuda, mock_vram_enforcer):
        """Test VRAM enforcement with explicit MB limit."""
        # Create config with explicit MB limit
        config = WorkerConfig(
            execution_mode=ExecutionMode.WINDOWS_CUDA,
            worker_id="test-worker",
            device="cuda:0",
            mode_config={
                "max_gpu_memory_percent": None,
                "max_gpu_memory_mb": 4096,
            },
        )

        # Create runner
        class TestRunner(WorkerRunner):
            def setup(self):
                pass

            def run(self):
                pass

            def shutdown(self):
                pass

        runner = TestRunner(config)

        # Check the call arguments
        call_args = mock_vram_enforcer.enforce_from_config.call_args
        hardware_config = call_args[0][0]

        assert hardware_config["max_gpu_memory_percent"] is None
        assert hardware_config["max_gpu_memory_mb"] == 4096

    def test_vram_enforcement_error_handling(self, mock_cuda):
        """Test that VRAM enforcement errors are handled gracefully."""
        # Mock VRAMEnforcer to raise an exception
        with patch("src.workers.runner.VRAMEnforcer") as MockVRAMEnforcer:
            mock_enforcer = MagicMock()
            MockVRAMEnforcer.return_value = mock_enforcer
            mock_enforcer.enforce_from_config.side_effect = RuntimeError("GPU error")

            # Create config
            config = WorkerConfig(
                execution_mode=ExecutionMode.WINDOWS_CUDA,
                worker_id="test-worker",
                device="cuda:0",
                mode_config={
                    "max_gpu_memory_percent": 60,
                    "max_gpu_memory_mb": None,
                },
            )

            # Create runner (should not raise, should log error)
            class TestRunner(WorkerRunner):
                def setup(self):
                    pass

                def run(self):
                    pass

                def shutdown(self):
                    pass

            # Should not raise exception
            runner = TestRunner(config)

            # Runner should still be created (error was handled)
            assert runner is not None
            assert runner.config.device == "cuda:0"


class TestVRAMEnforcementIntegration:
    """Integration tests for VRAM enforcement with device policy."""

    def test_device_policy_and_vram_enforcement_order(self, mock_cuda, mock_vram_enforcer):
        """Test that device policy is applied before VRAM enforcement."""
        # Create config for windows_cuda mode with "auto" device
        config = WorkerConfig(
            execution_mode=ExecutionMode.WINDOWS_CUDA,
            worker_id="test-worker",
            device="auto",  # Should be resolved by device policy
            mode_config={
                "max_gpu_memory_percent": 60,
                "max_gpu_memory_mb": None,
            },
        )

        # Mock device policy to return "cuda:0"
        with patch("src.workers.runner.DevicePolicy") as MockDevicePolicy:
            mock_policy = MagicMock()
            MockDevicePolicy.return_value = mock_policy
            mock_policy.get_device.return_value = "cuda:0"
            mock_policy.is_gpu_allowed.return_value = True

            # Create runner
            class TestRunner(WorkerRunner):
                def setup(self):
                    pass

                def run(self):
                    pass

                def shutdown(self):
                    pass

            runner = TestRunner(config)

            # Check that device policy was applied first
            mock_policy.enforce.assert_called_once()
            mock_policy.get_device.assert_called_once()

            # Check that VRAM enforcement used the resolved device
            call_args = mock_vram_enforcer.enforce_from_config.call_args
            device = call_args[1]["device"]  # Keyword arg
            assert device == "cuda:0"
