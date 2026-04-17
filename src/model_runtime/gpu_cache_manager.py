"""
GPU Cache Manager for Translation Models.

Provides intelligent GPU cache management to prevent memory fragmentation
during long-running translation sessions. Implements both periodic and
reactive cache clearing strategies.

Key Features:
- Periodic aggressive clearing (configurable interval)
- Fragmentation-aware reactive clearing (threshold-based)
- Memory usage logging and monitoring
- Graceful degradation if CUDA unavailable

Usage:
    manager = GPUCacheManager(clear_every_n_files=10)

    # After each file translation
    manager.clear_after_file(device)

    # Periodic check for aggressive clearing
    if manager.check_and_clear(device):
        logger.info("Performed aggressive GPU cache clear")
"""

import gc
import logging

logger = logging.getLogger(__name__)

# Try to import torch - graceful degradation if unavailable
try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False
    logger.warning(
        "PyTorch not available - GPU cache management disabled. "
        "Install with: pip install torch"
    )


class GPUCacheManager:
    """
    Intelligent GPU cache manager with fragmentation detection.

    Implements two-tier cache clearing strategy:
    1. Standard clearing after each file (light)
    2. Aggressive clearing on periodic/fragmentation triggers (heavy)

    Metrics tracked:
    - Files processed since last aggressive clear
    - Memory fragmentation ratio (reserved - allocated) / reserved
    - Total aggressive clears performed
    """

    def __init__(self, clear_every_n_files: int = 10):
        """
        Initialize GPU cache manager.

        Args:
            clear_every_n_files: Perform aggressive clear every N files (default: 10)
        """
        self.clear_every_n_files = clear_every_n_files
        self.files_processed = 0
        self.fragmentation_threshold = 0.50  # 50% fragmentation triggers aggressive clear
        self.total_aggressive_clears = 0

        if not TORCH_AVAILABLE:
            logger.debug("GPUCacheManager initialized but torch unavailable - operations will no-op")
        else:
            logger.debug(
                f"GPUCacheManager initialized: clear_every_n_files={clear_every_n_files}, "
                f"fragmentation_threshold={self.fragmentation_threshold:.0%}"
            )

    def clear_after_file(self, device: str) -> None:
        """
        Standard cache clear after file translation (light operation).

        Performs basic GPU cache clearing and increments file counter.
        This is called after every file translation to prevent basic accumulation.

        Args:
            device: Device string (e.g., "cuda", "cuda:0", "cpu")
        """
        if not TORCH_AVAILABLE:
            return

        # Only clear if device is CUDA
        if not device.startswith("cuda"):
            return

        # Check CUDA availability
        if not torch.cuda.is_available():
            return

        # Standard cache clear
        torch.cuda.empty_cache()
        self.files_processed += 1

        logger.debug(
            f"Standard GPU cache clear after file (files_processed: {self.files_processed})"
        )

    def aggressive_clear(self, device: str) -> None:
        """
        Aggressive cache clear for stubborn memory fragments (heavy operation).

        Performs comprehensive memory cleanup:
        1. Wait for all CUDA operations to complete (synchronize)
        2. Python garbage collection
        3. Double GPU cache clear (catches stubborn fragments)
        4. Log memory summary for monitoring

        Args:
            device: Device string (e.g., "cuda", "cuda:0", "cpu")
        """
        if not TORCH_AVAILABLE:
            return

        # Only clear if device is CUDA
        if not device.startswith("cuda"):
            return

        # Check CUDA availability
        if not torch.cuda.is_available():
            return

        # Extract device ID
        device_id = 0 if ":" not in device else int(device.split(":")[1])

        try:
            # Step 1: Wait for all CUDA operations to complete
            torch.cuda.synchronize(device_id)

            # Step 2: Python garbage collection
            gc.collect()

            # Step 3: Clear GPU cache twice (catches stubborn fragments)
            torch.cuda.empty_cache()
            torch.cuda.empty_cache()

            # Step 4: Log memory summary
            allocated_mb = torch.cuda.memory_allocated(device_id) / (1024**2)
            reserved_mb = torch.cuda.memory_reserved(device_id) / (1024**2)
            fragmentation = self._get_fragmentation_ratio(device_id)

            self.total_aggressive_clears += 1

            logger.info(
                f"Aggressive GPU cache clear #{self.total_aggressive_clears}: "
                f"allocated={allocated_mb:.0f}MB, reserved={reserved_mb:.0f}MB, "
                f"fragmentation={fragmentation:.1%}"
            )

        except Exception as e:
            logger.warning(f"Aggressive GPU cache clear failed: {e}")

    def check_and_clear(self, device: str) -> bool:
        """
        Check if aggressive clear needed and perform if necessary.

        Triggers aggressive clear if:
        1. Periodic threshold reached (files_processed >= clear_every_n_files), OR
        2. Fragmentation threshold exceeded (fragmentation > fragmentation_threshold)

        Args:
            device: Device string (e.g., "cuda", "cuda:0", "cpu")

        Returns:
            True if aggressive clear was performed, False otherwise
        """
        if not TORCH_AVAILABLE:
            return False

        # Only check if device is CUDA
        if not device.startswith("cuda"):
            return False

        # Check CUDA availability
        if not torch.cuda.is_available():
            return False

        # Extract device ID
        device_id = 0 if ":" not in device else int(device.split(":")[1])

        # Check 1: Periodic threshold
        periodic_trigger = self.files_processed >= self.clear_every_n_files

        # Check 2: Fragmentation threshold
        fragmentation_ratio = self._get_fragmentation_ratio(device_id)
        fragmentation_trigger = (
            fragmentation_ratio is not None and
            fragmentation_ratio > self.fragmentation_threshold
        )

        # Perform aggressive clear if either trigger fires
        if periodic_trigger or fragmentation_trigger:
            trigger_reason = []
            if periodic_trigger:
                trigger_reason.append(
                    f"periodic ({self.files_processed}/{self.clear_every_n_files} files)"
                )
            if fragmentation_trigger:
                trigger_reason.append(
                    f"fragmentation ({fragmentation_ratio:.1%} > {self.fragmentation_threshold:.1%})"
                )

            logger.debug(f"Aggressive clear triggered: {', '.join(trigger_reason)}")

            self.aggressive_clear(device)

            # Reset periodic counter
            self.files_processed = 0

            return True

        return False

    def _get_fragmentation_ratio(self, device_id: int = 0) -> float | None:
        """
        Calculate GPU memory fragmentation ratio.

        Fragmentation ratio = (reserved - allocated) / reserved
        - 0.0 = no fragmentation (all reserved memory is allocated)
        - 1.0 = complete fragmentation (all reserved memory is unused)

        Args:
            device_id: CUDA device ID (default: 0)

        Returns:
            Fragmentation ratio (0.0-1.0), or None if unable to calculate
        """
        if not TORCH_AVAILABLE:
            return None

        if not torch.cuda.is_available():
            return None

        try:
            allocated = torch.cuda.memory_allocated(device_id)
            reserved = torch.cuda.memory_reserved(device_id)

            # Avoid division by zero
            if reserved == 0:
                return 0.0

            fragmentation = (reserved - allocated) / reserved
            return fragmentation

        except Exception as e:
            logger.debug(f"Failed to calculate fragmentation ratio: {e}")
            return None
