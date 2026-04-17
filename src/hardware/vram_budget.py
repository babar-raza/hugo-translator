"""
VRAM Budget Management - Centralized VRAM allocation and budget computation.

Provides dataclasses and utilities for computing VRAM budgets from percent/MB limits.
"""

import logging
from dataclasses import dataclass

import torch

logger = logging.getLogger(__name__)


@dataclass
class VRAMBudget:
    """
    VRAM budget computed from configuration.

    Attributes:
        fraction: Memory fraction (0.0-1.0) for torch.cuda.set_per_process_memory_fraction
        percent: Budget as percentage (0-100) for human-readable display
        computed_mb: Computed budget in MB based on actual GPU memory
        source: How budget was determined ("percent", "mb", "default")
    """

    fraction: float
    percent: float
    computed_mb: float
    source: str = "default"

    def __post_init__(self):
        """Validate budget values."""
        if not (0.0 <= self.fraction <= 1.0):
            raise ValueError(f"fraction must be 0.0-1.0, got {self.fraction}")
        if not (0 <= self.percent <= 100):
            raise ValueError(f"percent must be 0-100, got {self.percent}")
        if self.computed_mb < 0:
            raise ValueError(f"computed_mb must be >= 0, got {self.computed_mb}")

    def to_dict(self):
        """Convert to dictionary for logging/telemetry."""
        return {
            "fraction": self.fraction,
            "percent": self.percent,
            "computed_mb": self.computed_mb,
            "source": self.source,
        }


def resolve_vram_budget_mb(
    total_mb: float,
    max_gpu_memory_percent: int | None = None,
    max_gpu_memory_mb: int | None = None,
) -> tuple[int, VRAMBudget]:
    """
    Resolve VRAM budget from configuration with precedence:
    1. max_gpu_memory_mb (explicit MB limit - highest priority)
    2. max_gpu_memory_percent (percentage of total VRAM)
    3. Default: 60% of total VRAM (safety default)

    Args:
        total_mb: Total GPU memory in MB (from torch.cuda.get_device_properties)
        max_gpu_memory_percent: Optional percentage limit (0-100)
        max_gpu_memory_mb: Optional explicit MB limit

    Returns:
        Tuple of (budget_mb, VRAMBudget)
        - budget_mb: Integer MB budget to apply
        - VRAMBudget: Dataclass with computed fraction, percent, and source

    Example:
        # GPU with 8192 MB total VRAM
        total = 8192

        # Case 1: Explicit MB limit (highest priority)
        budget_mb, budget = resolve_vram_budget_mb(total, max_gpu_memory_mb=4096)
        # Returns: (4096, VRAMBudget(fraction=0.5, percent=50.0, computed_mb=4096, source="mb"))

        # Case 2: Percentage limit
        budget_mb, budget = resolve_vram_budget_mb(total, max_gpu_memory_percent=60)
        # Returns: (4915, VRAMBudget(fraction=0.6, percent=60.0, computed_mb=4915, source="percent"))

        # Case 3: Default 60%
        budget_mb, budget = resolve_vram_budget_mb(total)
        # Returns: (4915, VRAMBudget(fraction=0.6, percent=60.0, computed_mb=4915, source="default"))
    """
    # Validate total_mb
    if total_mb <= 0:
        raise ValueError(f"total_mb must be > 0, got {total_mb}")

    # Precedence 1: Explicit MB limit (highest priority)
    if max_gpu_memory_mb is not None:
        if max_gpu_memory_mb <= 0:
            raise ValueError(f"max_gpu_memory_mb must be > 0, got {max_gpu_memory_mb}")

        # Clamp to total VRAM (can't allocate more than available)
        budget_mb = min(max_gpu_memory_mb, int(total_mb))
        fraction = budget_mb / total_mb
        percent = fraction * 100.0

        budget = VRAMBudget(
            fraction=fraction,
            percent=percent,
            computed_mb=float(budget_mb),
            source="mb",
        )

        logger.debug(
            f"VRAM budget from max_gpu_memory_mb: {budget_mb}MB "
            f"({percent:.1f}% of {total_mb:.0f}MB total)"
        )

        return budget_mb, budget

    # Precedence 2: Percentage limit
    if max_gpu_memory_percent is not None:
        if not (0 < max_gpu_memory_percent <= 100):
            raise ValueError(
                f"max_gpu_memory_percent must be 0-100, got {max_gpu_memory_percent}"
            )

        fraction = max_gpu_memory_percent / 100.0
        budget_mb = int(total_mb * fraction)
        percent = float(max_gpu_memory_percent)

        budget = VRAMBudget(
            fraction=fraction,
            percent=percent,
            computed_mb=float(budget_mb),
            source="percent",
        )

        logger.debug(
            f"VRAM budget from max_gpu_memory_percent: {budget_mb}MB "
            f"({percent}% of {total_mb:.0f}MB total)"
        )

        return budget_mb, budget

    # Precedence 3: Default 60% (safety default to prevent OOM)
    default_percent = 60
    fraction = default_percent / 100.0
    budget_mb = int(total_mb * fraction)

    budget = VRAMBudget(
        fraction=fraction,
        percent=float(default_percent),
        computed_mb=float(budget_mb),
        source="default",
    )

    logger.debug(
        f"VRAM budget from default: {budget_mb}MB "
        f"({default_percent}% of {total_mb:.0f}MB total)"
    )

    return budget_mb, budget


def get_gpu_total_memory_mb(device_id: int = 0) -> float:
    """
    Get total GPU memory in MB for a specific device.

    Args:
        device_id: CUDA device ID (default: 0)

    Returns:
        Total memory in MB

    Raises:
        RuntimeError: If CUDA not available or device invalid
    """
    if not torch.cuda.is_available():
        raise RuntimeError("CUDA not available")

    try:
        props = torch.cuda.get_device_properties(device_id)
        total_mb = props.total_memory / (1024**2)
        return total_mb
    except Exception as e:
        raise RuntimeError(f"Failed to get GPU memory for device {device_id}: {e}")
