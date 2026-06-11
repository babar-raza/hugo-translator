"""
Unit tests for VRAM enforcer.

Tests VRAMEnforcer class with mocked torch.cuda to avoid requiring actual GPU hardware.
"""

from unittest.mock import MagicMock, patch

import pytest

from src.hardware.vram_enforcer import (
    VRAMEnforcer,
    ensure_vram_budget,
    reset_enforcement_state,
)


@pytest.fixture(autouse=True)
def reset_state():
    """Reset enforcement state before each test."""
    reset_enforcement_state()
    yield
    reset_enforcement_state()


@pytest.fixture
def mock_cuda():
    """Mock torch.cuda to simulate GPU presence."""
    # Need to patch both modules since they import torch independently
    with (
        patch("src.hardware.vram_enforcer.torch") as mock_torch_enforcer,
        patch("src.hardware.vram_budget.torch") as mock_torch_budget,
    ):
        # Mock get_device_properties to return 8192 MB (8 GB) GPU
        mock_props = MagicMock()
        mock_props.total_memory = 8192 * 1024 * 1024  # 8 GB in bytes

        # Configure both mocks identically
        for mock_torch in [mock_torch_enforcer, mock_torch_budget]:
            mock_torch.cuda.is_available.return_value = True
            mock_torch.cuda.get_device_properties.return_value = mock_props
            mock_torch.cuda.set_per_process_memory_fraction = MagicMock()

        yield mock_torch_enforcer


@pytest.fixture
def mock_cuda_unavailable():
    """Mock torch.cuda to simulate no GPU."""
    with (
        patch("src.hardware.vram_enforcer.torch") as mock_torch_enforcer,
        patch("src.hardware.vram_budget.torch") as mock_torch_budget,
    ):
        for mock_torch in [mock_torch_enforcer, mock_torch_budget]:
            mock_torch.cuda.is_available.return_value = False

        yield mock_torch_enforcer


class TestVRAMEnforcer:
    """Test VRAMEnforcer class."""

    def test_enforce_from_config_with_percent(self, mock_cuda):
        """Test enforcement with max_gpu_memory_percent."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,  # 60% of 8192 MB = 4915 MB
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, "cuda:0")

        # Check return values
        assert max_memory_mb == 4915  # 60% of 8192 MB
        assert budget is not None
        assert budget.fraction == 0.6
        assert budget.percent == 60.0
        assert budget.computed_mb == 4915.0
        assert budget.source == "percent"

        # Check that torch.cuda.set_per_process_memory_fraction was called
        mock_cuda.cuda.set_per_process_memory_fraction.assert_called_once_with(0.6, 0)

    def test_enforce_from_config_with_mb(self, mock_cuda):
        """Test enforcement with explicit max_gpu_memory_mb."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": None,
            "max_gpu_memory_mb": 4096,  # Explicit 4096 MB
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, "cuda:0")

        # Check return values
        assert max_memory_mb == 4096
        assert budget is not None
        assert budget.fraction == 0.5  # 4096 / 8192
        assert budget.percent == 50.0
        assert budget.computed_mb == 4096.0
        assert budget.source == "mb"

        # Check that torch.cuda.set_per_process_memory_fraction was called
        mock_cuda.cuda.set_per_process_memory_fraction.assert_called_once_with(0.5, 0)

    def test_enforce_from_config_with_default(self, mock_cuda):
        """Test enforcement with default 60%."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": None,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, "cuda:0")

        # Check return values (should use 60% default)
        assert max_memory_mb == 4915  # 60% of 8192 MB
        assert budget is not None
        assert budget.fraction == 0.6
        assert budget.percent == 60.0
        assert budget.computed_mb == 4915.0
        assert budget.source == "default"

        # Check that torch.cuda.set_per_process_memory_fraction was called
        mock_cuda.cuda.set_per_process_memory_fraction.assert_called_once_with(0.6, 0)

    def test_enforce_from_config_idempotent(self, mock_cuda):
        """Test that enforcement is idempotent (only applies once per device)."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()

        # First call should enforce
        max_memory_mb1, budget1 = enforcer.enforce_from_config(hardware_config, "cuda:0")
        assert max_memory_mb1 == 4915
        assert budget1 is not None

        # Second call should be idempotent (no re-enforcement)
        max_memory_mb2, budget2 = enforcer.enforce_from_config(hardware_config, "cuda:0")
        assert max_memory_mb2 == 4915
        assert budget2 is not None

        # Should only have called set_per_process_memory_fraction once
        assert mock_cuda.cuda.set_per_process_memory_fraction.call_count == 1

    def test_enforce_from_config_gpu_disabled(self, mock_cuda):
        """Test that enforcement is skipped when GPU disabled."""
        hardware_config = {
            "enable_gpu": False,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, "cuda:0")

        # Should return 0 and None
        assert max_memory_mb == 0
        assert budget is None

        # Should not call torch API
        mock_cuda.cuda.set_per_process_memory_fraction.assert_not_called()

    def test_enforce_from_config_cpu_device(self, mock_cuda):
        """Test that enforcement is skipped for CPU device."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, "cpu")

        # Should return 0 and None
        assert max_memory_mb == 0
        assert budget is None

        # Should not call torch API
        mock_cuda.cuda.set_per_process_memory_fraction.assert_not_called()

    def test_enforce_from_config_cuda_unavailable(self, mock_cuda_unavailable):
        """Test that enforcement is skipped when CUDA unavailable."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, "cuda:0")

        # Should return 0 and None
        assert max_memory_mb == 0
        assert budget is None

        # Should not call torch API
        mock_cuda_unavailable.cuda.set_per_process_memory_fraction.assert_not_called()

    def test_enforce_fraction(self, mock_cuda):
        """Test enforce_fraction method."""
        enforcer = VRAMEnforcer()
        applied_mb = enforcer.enforce_fraction(device_id=0, target_fraction=0.7)

        # Should return 70% of 8192 MB = 5734 MB
        assert applied_mb == 5734

        # Should call torch API
        mock_cuda.cuda.set_per_process_memory_fraction.assert_called_once_with(0.7, 0)

    def test_enforce_fraction_invalid_fraction(self, mock_cuda):
        """Test enforce_fraction with invalid fraction."""
        enforcer = VRAMEnforcer()

        with pytest.raises(ValueError, match="target_fraction must be 0.0-1.0"):
            enforcer.enforce_fraction(device_id=0, target_fraction=1.5)

        with pytest.raises(ValueError, match="target_fraction must be 0.0-1.0"):
            enforcer.enforce_fraction(device_id=0, target_fraction=-0.1)

    def test_is_enforced(self, mock_cuda):
        """Test is_enforced method."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()

        # Before enforcement
        assert not enforcer.is_enforced(device_id=0)

        # After enforcement
        enforcer.enforce_from_config(hardware_config, "cuda:0")
        assert enforcer.is_enforced(device_id=0)

    def test_parse_device_id(self):
        """Test _parse_device_id method."""
        enforcer = VRAMEnforcer()

        assert enforcer._parse_device_id("cuda") == 0
        assert enforcer._parse_device_id("cuda:0") == 0
        assert enforcer._parse_device_id("cuda:1") == 1
        assert enforcer._parse_device_id("cuda:2") == 2
        assert enforcer._parse_device_id("cuda:invalid") == 0  # Falls back to 0


class TestEnsureVRAMBudget:
    """Test ensure_vram_budget context manager."""

    def test_context_manager(self, mock_cuda):
        """Test context manager usage."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        with ensure_vram_budget(hardware_config, "cuda:0") as (max_mb, budget):
            assert max_mb == 4915
            assert budget is not None
            assert budget.percent == 60.0

        # Check enforcement was applied
        mock_cuda.cuda.set_per_process_memory_fraction.assert_called_once()


class TestResetEnforcementState:
    """Test reset_enforcement_state utility."""

    def test_reset_enforcement_state(self, mock_cuda):
        """Test that reset_enforcement_state clears state."""
        hardware_config = {
            "enable_gpu": True,
            "max_gpu_memory_percent": 60,
            "max_gpu_memory_mb": None,
        }

        enforcer = VRAMEnforcer()

        # Enforce once
        enforcer.enforce_from_config(hardware_config, "cuda:0")
        assert enforcer.is_enforced(device_id=0)

        # Reset state
        reset_enforcement_state()

        # Should be able to enforce again
        enforcer2 = VRAMEnforcer()
        assert not enforcer2.is_enforced(device_id=0)

        # Second enforcement should work
        enforcer2.enforce_from_config(hardware_config, "cuda:0")
        assert enforcer2.is_enforced(device_id=0)

        # Should have called set_per_process_memory_fraction twice (once per enforcer)
        assert mock_cuda.cuda.set_per_process_memory_fraction.call_count == 2
