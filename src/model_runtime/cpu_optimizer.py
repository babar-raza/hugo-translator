"""
CPU-specific runtime optimization for translation models.

Provides automatic tuning of batch size, thread counts, and environment variables
for optimal CPU performance.
"""
import logging
import os
from dataclasses import dataclass

import psutil

logger = logging.getLogger(__name__)


@dataclass
class RuntimeConfig:
    """Runtime configuration for CPU-optimized translation."""

    batch_size: int
    num_threads: int
    device: str = "cpu"
    intra_threads: int = 0  # 0 = auto (uses num_threads)
    inter_threads: int = 1

    def __post_init__(self):
        """Set intra_threads to num_threads if not specified."""
        if self.intra_threads == 0:
            self.intra_threads = self.num_threads


class CPUOptimizer:
    """
    CPU-specific runtime optimizer.

    Detects hardware capabilities and computes optimal settings for:
    - Batch size (based on available RAM)
    - Thread counts (intra-op and inter-op parallelism)
    - Environment variables (OMP_NUM_THREADS, MKL_NUM_THREADS, etc.)
    """

    # Constants for heuristics
    MIN_BATCH_SIZE = 1
    MAX_BATCH_SIZE = 64
    RAM_PER_BATCH_GB = 0.25  # Conservative estimate: 250MB per batch item
    LOW_RAM_THRESHOLD_GB = 8.0
    MIN_FREE_RAM_GB = 2.0  # Keep at least 2GB free

    def __init__(
        self,
        batch_size_override: int | None = None,
        num_threads_override: int | None = None,
        memory_target_percent: float = 0.7,
    ):
        """
        Initialize CPU optimizer.

        Args:
            batch_size_override: Manual override for batch size
            num_threads_override: Manual override for thread count
            memory_target_percent: Target memory utilization (0.0-1.0)
        """
        self.batch_size_override = batch_size_override
        self.num_threads_override = num_threads_override
        self.memory_target_percent = max(0.1, min(0.9, memory_target_percent))

    def optimize(self) -> RuntimeConfig:
        """
        Compute optimal runtime configuration for current hardware.

        Returns:
            RuntimeConfig with optimized settings
        """
        # Detect hardware
        cpu_cores = self._detect_cpu_cores()
        total_ram_gb = self._detect_ram_gb()
        available_ram_gb = self._detect_available_ram_gb()

        # Compute optimal settings
        batch_size = self._compute_batch_size(total_ram_gb, available_ram_gb)
        num_threads = self._compute_thread_count(cpu_cores)

        # Apply overrides
        if self.batch_size_override is not None:
            batch_size = self._clamp_batch_size(self.batch_size_override)
            logger.info(f"Using batch size override: {batch_size}")

        if self.num_threads_override is not None:
            num_threads = min(self.num_threads_override, cpu_cores)
            logger.info(f"Using thread count override: {num_threads}")

        # Set environment variables
        self._set_environment(num_threads)

        # Log configuration
        logger.info(
            f"CPU optimization: cores={cpu_cores}, RAM={total_ram_gb:.1f}GB, "
            f"available={available_ram_gb:.1f}GB, batch_size={batch_size}, "
            f"threads={num_threads}"
        )

        return RuntimeConfig(
            batch_size=batch_size,
            num_threads=num_threads,
            device="cpu",
            intra_threads=num_threads,
            inter_threads=1,
        )

    def _detect_cpu_cores(self) -> int:
        """
        Detect number of physical CPU cores.

        Returns:
            Number of physical cores (falls back to logical if unavailable)
        """
        # Prefer physical cores over logical (no hyperthreading)
        physical = psutil.cpu_count(logical=False)
        logical = psutil.cpu_count(logical=True)

        if physical is None:
            logger.warning("Could not detect physical CPU cores, using logical count")
            return logical or 1

        return physical

    def _detect_ram_gb(self) -> float:
        """
        Detect total system RAM in GB.

        Returns:
            Total RAM in gigabytes
        """
        total_bytes = psutil.virtual_memory().total
        return total_bytes / (1024**3)

    def _detect_available_ram_gb(self) -> float:
        """
        Detect available system RAM in GB.

        Returns:
            Available RAM in gigabytes
        """
        available_bytes = psutil.virtual_memory().available
        return available_bytes / (1024**3)

    def _compute_batch_size(self, total_ram_gb: float, available_ram_gb: float) -> int:
        """
        Compute optimal batch size based on RAM.

        Strategy:
        - Use conservative multiplier for low-RAM systems (<8GB)
        - Target memory_target_percent of available RAM
        - Enforce safety bounds [MIN_BATCH_SIZE, MAX_BATCH_SIZE]

        Args:
            total_ram_gb: Total system RAM
            available_ram_gb: Currently available RAM

        Returns:
            Recommended batch size
        """
        # Low-RAM path: conservative settings
        if total_ram_gb < self.LOW_RAM_THRESHOLD_GB:
            # Very conservative: only use a fraction of available memory
            usable_ram = max(0, available_ram_gb - self.MIN_FREE_RAM_GB)
            batch_size = int(usable_ram / (self.RAM_PER_BATCH_GB * 2))
            logger.info(
                f"Low RAM detected ({total_ram_gb:.1f}GB), using conservative batch size"
            )
        else:
            # Normal path: target a percentage of available RAM
            usable_ram = available_ram_gb * self.memory_target_percent
            usable_ram = max(0, usable_ram - self.MIN_FREE_RAM_GB)
            batch_size = int(usable_ram / self.RAM_PER_BATCH_GB)

        # Enforce bounds
        return self._clamp_batch_size(batch_size)

    def _clamp_batch_size(self, batch_size: int) -> int:
        """
        Clamp batch size to safety bounds.

        Args:
            batch_size: Proposed batch size

        Returns:
            Clamped batch size in [MIN_BATCH_SIZE, MAX_BATCH_SIZE]
        """
        clamped = max(self.MIN_BATCH_SIZE, min(self.MAX_BATCH_SIZE, batch_size))

        if clamped != batch_size:
            logger.warning(
                f"Batch size {batch_size} out of bounds, clamped to {clamped}"
            )

        return clamped

    def _compute_thread_count(self, cpu_cores: int) -> int:
        """
        Compute optimal thread count.

        Strategy:
        - Use physical cores (not logical/hyperthreaded)
        - Reserve 1 core for system if many cores available

        Args:
            cpu_cores: Number of physical CPU cores

        Returns:
            Recommended thread count
        """
        # Use all physical cores, but reserve 1 if we have many
        if cpu_cores >= 8:
            return max(1, cpu_cores - 1)
        else:
            return cpu_cores

    def _set_environment(self, num_threads: int):
        """
        Set environment variables for CPU optimization.

        Sets:
        - OMP_NUM_THREADS: OpenMP thread count
        - MKL_NUM_THREADS: Intel MKL thread count
        - NUMEXPR_MAX_THREADS: NumExpr thread count

        Args:
            num_threads: Number of threads to use
        """
        thread_str = str(num_threads)

        # Set environment variables
        os.environ["OMP_NUM_THREADS"] = thread_str
        os.environ["MKL_NUM_THREADS"] = thread_str
        os.environ["NUMEXPR_MAX_THREADS"] = thread_str

        logger.debug(
            f"Set CPU environment: OMP_NUM_THREADS={thread_str}, "
            f"MKL_NUM_THREADS={thread_str}, NUMEXPR_MAX_THREADS={thread_str}"
        )
