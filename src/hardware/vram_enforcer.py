"""
VRAM Enforcer - Centralized enforcement of VRAM budget limits.

Provides VRAMEnforcer class for applying per-process memory fractions
and context manager for "enforce once per process" semantics.
"""

import logging
import threading
from contextlib import contextmanager
from typing import Dict, Optional, Tuple

import torch

from .vram_budget import VRAMBudget, get_gpu_total_memory_mb, resolve_vram_budget_mb

logger = logging.getLogger(__name__)


# Global state to track enforcement (per-process singleton)
_enforcement_lock = threading.Lock()
_enforcement_state: Dict[int, bool] = {}  # device_id -> enforced


class VRAMEnforcer:
    """
    VRAM budget enforcer with idempotent "enforce once per process" semantics.

    Applies torch.cuda.set_per_process_memory_fraction() based on hardware config
    and ensures enforcement happens exactly once per device per process.

    Example:
        # Initialize from hardware config
        hardware_config = {
            "max_gpu_memory_percent": 60,  # Use 60% of VRAM
            "enable_gpu": True
        }

        enforcer = VRAMEnforcer()
        max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, device="cuda:0")

        # Logs: "Applied VRAM budget: 4915MB (60.0% of 8192MB) on device cuda:0"
        # Returns: (4915, VRAMBudget(...))

        # Second call is idempotent (no-op)
        max_memory_mb2, budget2 = enforcer.enforce_from_config(hardware_config, device="cuda:0")
        # Logs: "VRAM budget already applied to device 0 (4915MB, 60.0%)"
    """

    def __init__(self):
        """Initialize VRAM enforcer."""
        pass

    def enforce_from_config(
        self,
        hardware_config: Dict,
        device: str = "cuda:0",
    ) -> Tuple[int, Optional[VRAMBudget]]:
        """
        Enforce VRAM budget from hardware configuration.

        Idempotent: If already enforced for this device, returns cached values.

        Args:
            hardware_config: Hardware configuration dict with keys:
                - max_gpu_memory_percent: Optional percentage limit (0-100)
                - max_gpu_memory_mb: Optional explicit MB limit
                - enable_gpu: Whether GPU is enabled (default: True)
            device: Device string (e.g., "cuda:0", "cuda")

        Returns:
            Tuple of (max_memory_mb, VRAMBudget or None)
            - max_memory_mb: Computed budget in MB to pass to ModelLoader
            - VRAMBudget: Budget details, or None if GPU disabled/unavailable

        Raises:
            RuntimeError: If CUDA not available but GPU enforcement requested

        Example:
            config = {"max_gpu_memory_percent": 60}
            max_mb, budget = enforcer.enforce_from_config(config, "cuda:0")
        """
        # Check if GPU is enabled
        enable_gpu = hardware_config.get("enable_gpu", True)
        if not enable_gpu:
            logger.info("GPU disabled in config, skipping VRAM enforcement")
            return 0, None

        # Check if device is CUDA
        if not device.startswith("cuda"):
            logger.debug(f"Device {device} is not CUDA, skipping VRAM enforcement")
            return 0, None

        # Check if CUDA is available
        if not torch.cuda.is_available():
            logger.warning("CUDA not available, skipping VRAM enforcement")
            return 0, None

        # Extract device ID
        device_id = self._parse_device_id(device)

        # Check if already enforced for this device (idempotent)
        with _enforcement_lock:
            if _enforcement_state.get(device_id, False):
                # Already enforced, return cached budget
                # Recompute budget for return value (enforcement already applied)
                try:
                    total_mb = get_gpu_total_memory_mb(device_id)
                    max_gpu_memory_percent = hardware_config.get("max_gpu_memory_percent")
                    max_gpu_memory_mb = hardware_config.get("max_gpu_memory_mb")

                    budget_mb, budget = resolve_vram_budget_mb(
                        total_mb=total_mb,
                        max_gpu_memory_percent=max_gpu_memory_percent,
                        max_gpu_memory_mb=max_gpu_memory_mb,
                    )

                    logger.info(
                        f"VRAM budget already applied to device {device_id} "
                        f"({budget_mb}MB, {budget.percent:.1f}%)"
                    )

                    return budget_mb, budget

                except Exception as e:
                    logger.warning(
                        f"Failed to recompute cached budget for device {device_id}: {e}"
                    )
                    return 0, None

        # Enforce budget (first time for this device)
        try:
            # Get total GPU memory
            total_mb = get_gpu_total_memory_mb(device_id)

            # Resolve budget from config
            max_gpu_memory_percent = hardware_config.get("max_gpu_memory_percent")
            max_gpu_memory_mb = hardware_config.get("max_gpu_memory_mb")

            budget_mb, budget = resolve_vram_budget_mb(
                total_mb=total_mb,
                max_gpu_memory_percent=max_gpu_memory_percent,
                max_gpu_memory_mb=max_gpu_memory_mb,
            )

            # Apply enforcement via torch.cuda.set_per_process_memory_fraction
            applied_mb = self.enforce_fraction(device_id, budget.fraction)

            # Mark as enforced
            with _enforcement_lock:
                _enforcement_state[device_id] = True

            logger.info(
                f"Applied VRAM budget: {applied_mb}MB ({budget.percent:.1f}% of {total_mb:.0f}MB) "
                f"on device cuda:{device_id} [source: {budget.source}]"
            )

            return applied_mb, budget

        except Exception as e:
            logger.error(f"Failed to enforce VRAM budget on device {device}: {e}")
            return 0, None

    def enforce_fraction(self, device_id: int, target_fraction: float) -> int:
        """
        Apply memory fraction to specific device via torch.cuda API.

        Args:
            device_id: CUDA device ID
            target_fraction: Memory fraction (0.0-1.0)

        Returns:
            Applied memory budget in MB

        Raises:
            RuntimeError: If enforcement fails
        """
        if not (0.0 <= target_fraction <= 1.0):
            raise ValueError(f"target_fraction must be 0.0-1.0, got {target_fraction}")

        try:
            # Apply fraction
            torch.cuda.set_per_process_memory_fraction(target_fraction, device_id)

            # Calculate applied MB
            total_mb = get_gpu_total_memory_mb(device_id)
            applied_mb = int(total_mb * target_fraction)

            logger.debug(
                f"Set per-process memory fraction: {target_fraction:.3f} "
                f"({applied_mb}MB) on device {device_id}"
            )

            return applied_mb

        except Exception as e:
            raise RuntimeError(
                f"Failed to set memory fraction on device {device_id}: {e}"
            ) from e

    def _parse_device_id(self, device: str) -> int:
        """
        Parse device ID from device string.

        Args:
            device: Device string (e.g., "cuda", "cuda:0", "cuda:1")

        Returns:
            Device ID (int)

        Example:
            _parse_device_id("cuda") -> 0
            _parse_device_id("cuda:0") -> 0
            _parse_device_id("cuda:1") -> 1
        """
        if ":" in device:
            try:
                return int(device.split(":")[1])
            except (ValueError, IndexError):
                logger.warning(f"Failed to parse device ID from '{device}', using 0")
                return 0
        return 0

    def is_enforced(self, device_id: int) -> bool:
        """
        Check if VRAM budget has been enforced for a device.

        Args:
            device_id: CUDA device ID

        Returns:
            True if enforced, False otherwise
        """
        with _enforcement_lock:
            return _enforcement_state.get(device_id, False)


@contextmanager
def ensure_vram_budget(
    hardware_config: Dict,
    device: str = "cuda:0",
):
    """
    Context manager to ensure VRAM budget is enforced before execution.

    Provides "enforce once per process" semantics with idempotent behavior.

    Args:
        hardware_config: Hardware configuration dict
        device: Device string (e.g., "cuda:0")

    Yields:
        Tuple of (max_memory_mb, VRAMBudget or None)

    Example:
        config = {"max_gpu_memory_percent": 60}

        with ensure_vram_budget(config, "cuda:0") as (max_mb, budget):
            # VRAM budget enforced here
            model_loader = ModelLoader(max_memory_mb=max_mb)
            # ... use model loader
    """
    enforcer = VRAMEnforcer()
    max_memory_mb, budget = enforcer.enforce_from_config(hardware_config, device)

    try:
        yield (max_memory_mb, budget)
    finally:
        # Cleanup if needed (currently no cleanup required)
        pass


def reset_enforcement_state():
    """
    Reset enforcement state (for testing only).

    This allows tests to re-enforce budgets on the same device.
    Should NOT be used in production code.
    """
    global _enforcement_state
    with _enforcement_lock:
        _enforcement_state.clear()
        logger.debug("VRAM enforcement state reset (testing only)")
