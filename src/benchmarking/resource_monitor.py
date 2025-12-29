"""Resource monitoring for safe benchmark execution.

Monitors system resources to prevent benchmarks from choking the system.
Provides real-time resource snapshots and safety checks.
"""

import time
from dataclasses import dataclass
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ResourceSnapshot:
    """Snapshot of system resource usage at a point in time."""

    cpu_percent: float  # Overall CPU usage (0-100)
    memory_percent: float  # Overall memory usage (0-100)
    memory_available_mb: float  # Available memory in MB
    gpu_memory_used_mb: Optional[float]  # GPU memory used (None if no GPU)
    gpu_memory_available_mb: Optional[float]  # GPU memory available (None if no GPU)
    timestamp: datetime


class ResourceMonitor:
    """Monitors system resources for safe benchmark execution.

    Uses psutil when available, gracefully degrades without it.
    """

    def __init__(self):
        """Initialize resource monitor."""
        self.psutil_available = False

        try:
            import psutil

            self.psutil = psutil
            self.psutil_available = True
            logger.info("psutil available for resource monitoring")
        except ImportError:
            logger.warning("psutil not available - resource monitoring will use fallbacks")

    def get_current(self) -> ResourceSnapshot:
        """Get current resource snapshot.

        Returns:
            ResourceSnapshot with current resource usage

        Note:
            Gracefully degrades if psutil is not available.
        """
        if self.psutil_available:
            return self._get_current_with_psutil()
        else:
            return self._get_current_fallback()

    def _get_current_with_psutil(self) -> ResourceSnapshot:
        """Get resource snapshot using psutil."""
        try:
            # CPU and memory
            cpu_percent = self.psutil.cpu_percent(interval=0.1)
            mem = self.psutil.virtual_memory()
            memory_percent = mem.percent
            memory_available_mb = mem.available / (1024 * 1024)

            # GPU (try to detect via torch if available)
            gpu_memory_used_mb = None
            gpu_memory_available_mb = None

            try:
                import torch

                if torch.cuda.is_available():
                    device = torch.cuda.current_device()
                    gpu_mem_allocated = torch.cuda.memory_allocated(device) / (1024 * 1024)
                    gpu_mem_reserved = torch.cuda.memory_reserved(device) / (1024 * 1024)
                    gpu_mem_total = torch.cuda.get_device_properties(device).total_memory / (
                        1024 * 1024
                    )

                    gpu_memory_used_mb = gpu_mem_reserved
                    gpu_memory_available_mb = gpu_mem_total - gpu_mem_reserved
            except Exception as e:
                logger.debug(f"GPU monitoring not available: {e}")

            return ResourceSnapshot(
                cpu_percent=cpu_percent,
                memory_percent=memory_percent,
                memory_available_mb=memory_available_mb,
                gpu_memory_used_mb=gpu_memory_used_mb,
                gpu_memory_available_mb=gpu_memory_available_mb,
                timestamp=datetime.utcnow(),
            )

        except Exception as e:
            logger.error(f"Failed to get resource snapshot with psutil: {e}")
            return self._get_current_fallback()

    def _get_current_fallback(self) -> ResourceSnapshot:
        """Get resource snapshot using fallback (conservative estimates)."""
        # Return conservative values that won't block benchmarks
        return ResourceSnapshot(
            cpu_percent=50.0,  # Assume moderate load
            memory_percent=50.0,  # Assume moderate load
            memory_available_mb=2048.0,  # Assume 2GB available
            gpu_memory_used_mb=None,
            gpu_memory_available_mb=None,
            timestamp=datetime.utcnow(),
        )

    def is_safe_to_run(
        self, estimate: "ResourceEstimate", safety_margin: float = 0.2
    ) -> bool:
        """Check if it's safe to run a benchmark with given resource estimate.

        Args:
            estimate: Resource estimate for the benchmark
            safety_margin: Safety margin (0-1), e.g., 0.2 = keep 20% buffer

        Returns:
            True if safe to run, False otherwise

        Note:
            Conservative check - prefers false negatives to avoid system choking.
        """
        try:
            snapshot = self.get_current()

            # Check CPU headroom
            cpu_headroom = 100.0 - snapshot.cpu_percent
            if cpu_headroom < (safety_margin * 100):
                logger.warning(f"Insufficient CPU headroom: {cpu_headroom:.1f}%")
                return False

            # Check memory availability
            required_memory_mb = estimate.estimated_memory_mb * (1.0 + safety_margin)
            if snapshot.memory_available_mb < required_memory_mb:
                logger.warning(
                    f"Insufficient memory: need {required_memory_mb:.0f}MB, "
                    f"available {snapshot.memory_available_mb:.0f}MB"
                )
                return False

            # Check GPU memory if needed
            if estimate.device_required in ["cuda", "gpu"]:
                if estimate.estimated_gpu_memory_mb is not None:
                    if snapshot.gpu_memory_available_mb is None:
                        logger.warning("GPU required but not available")
                        return False

                    required_gpu_mb = estimate.estimated_gpu_memory_mb * (
                        1.0 + safety_margin
                    )
                    if snapshot.gpu_memory_available_mb < required_gpu_mb:
                        logger.warning(
                            f"Insufficient GPU memory: need {required_gpu_mb:.0f}MB, "
                            f"available {snapshot.gpu_memory_available_mb:.0f}MB"
                        )
                        return False

            return True

        except Exception as e:
            logger.error(f"Failed to check resource safety: {e}")
            # Conservative: return False on error
            return False

    def wait_for_resources(
        self, estimate: "ResourceEstimate", timeout_seconds: float = 300
    ) -> bool:
        """Wait for sufficient resources to become available.

        Args:
            estimate: Resource estimate for the benchmark
            timeout_seconds: Maximum time to wait in seconds

        Returns:
            True if resources became available, False if timed out

        Note:
            Polls every 5 seconds until resources are available or timeout.
        """
        start_time = time.time()
        poll_interval = 5.0

        while True:
            if self.is_safe_to_run(estimate):
                logger.info("Resources available for benchmark")
                return True

            elapsed = time.time() - start_time
            if elapsed >= timeout_seconds:
                logger.warning(f"Timed out waiting for resources after {elapsed:.0f}s")
                return False

            # Wait before next poll
            time.sleep(min(poll_interval, timeout_seconds - elapsed))


# Import here to avoid circular dependency
from dataclasses import dataclass as _dataclass
from typing import Optional as _Optional


@_dataclass
class ResourceEstimate:
    """Estimated resource requirements for a benchmark."""

    estimated_memory_mb: float
    estimated_gpu_memory_mb: _Optional[float]
    estimated_duration_seconds: float
    device_required: str  # "cpu", "cuda", "auto"
    confidence: float  # 0-1, how confident is the estimate
