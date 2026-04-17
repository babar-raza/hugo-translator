"""
LimitingEngine - Unified resource constraint enforcement.

Wraps existing GPUManager and ResourceMonitor to provide consistent interface
for CPU, RAM, and GPU/VRAM resource limiting.
"""

import logging
from dataclasses import dataclass
from typing import Any

import torch

from src.benchmarking.resource_monitor import ResourceEstimate, ResourceMonitor, ResourceSnapshot
from src.hardware.gpu_manager import GPUManager, GPUMemoryInfo
from src.hardware.vram_budget import resolve_vram_budget_mb

logger = logging.getLogger(__name__)


@dataclass
class ResourceLimits:
    """Resource limits configuration."""

    # CPU limits
    max_cpu_percent: float | None = None  # Maximum CPU usage (0-100)

    # RAM limits
    min_memory_mb: float | None = None  # Minimum available memory in MB
    max_memory_percent: float | None = None  # Maximum memory usage (0-100)

    # GPU/VRAM limits
    max_gpu_memory_percent: int | None = None  # Maximum GPU memory as % of total (0-100)
    max_gpu_memory_mb: int | None = None  # Maximum GPU memory in MB (overrides percent)
    gpu_device_id: int = -1  # GPU device ID (-1 = auto-select)
    enable_gpu: bool = True  # Whether to use GPU

    # Timeouts
    wait_timeout_seconds: float = 300.0  # Max wait time for resources
    safety_margin: float = 0.2  # Safety margin (0-1), e.g., 0.2 = 20% buffer


class LimitingEngine:
    """
    Unified resource limiting engine.

    Wraps GPUManager and ResourceMonitor to provide consistent interface for:
    - CPU usage limits
    - RAM availability checks
    - GPU/VRAM memory limits
    - Resource waiting with timeout

    Args:
        limits: ResourceLimits configuration
        gpu_config: Optional GPU-specific configuration

    Example:
        # Initialize engine with limits
        limits = ResourceLimits(
            min_memory_mb=2048,  # Need 2GB RAM
            max_gpu_memory_mb=4096,  # Limit GPU to 4GB
            max_cpu_percent=80.0  # Keep CPU below 80%
        )
        limiting_engine = LimitingEngine(limits=limits)

        # Check if resources available
        if limiting_engine.check_resources_available():
            # Proceed with translation
            pass
        else:
            # Wait for resources
            if limiting_engine.wait_for_resources(timeout=60):
                # Resources available now
                pass
    """

    def __init__(
        self,
        limits: ResourceLimits | None = None,
        gpu_config: dict[str, Any] | None = None
    ):
        """Initialize limiting engine."""
        self.limits = limits or ResourceLimits()

        # Resolve max_gpu_memory_mb from percent if not explicitly set
        # This ensures ModelLoader receives a concrete MB value
        if (
            self.limits.max_gpu_memory_mb is None
            and self.limits.max_gpu_memory_percent is not None
            and self.limits.enable_gpu
            and torch.cuda.is_available()
        ):
            try:
                # Get GPU 0 total memory (default device)
                device_id = max(0, self.limits.gpu_device_id) if self.limits.gpu_device_id >= 0 else 0
                props = torch.cuda.get_device_properties(device_id)
                total_mb = props.total_memory / (1024**2)

                # Compute MB from percent
                budget_mb, budget = resolve_vram_budget_mb(
                    total_mb=total_mb,
                    max_gpu_memory_percent=self.limits.max_gpu_memory_percent,
                    max_gpu_memory_mb=None,
                )

                # Update limits with computed value
                self.limits.max_gpu_memory_mb = budget_mb
                logger.info(
                    f"Computed max_gpu_memory_mb from percent: {budget_mb}MB "
                    f"({self.limits.max_gpu_memory_percent}% of {total_mb:.0f}MB)"
                )

            except Exception as e:
                logger.warning(
                    f"Failed to compute max_gpu_memory_mb from percent: {e}. "
                    f"Using default 60% on-demand enforcement."
                )

        # Initialize GPU manager
        gpu_cfg = gpu_config or {}
        if self.limits.max_gpu_memory_mb:
            gpu_cfg["max_gpu_memory_mb"] = self.limits.max_gpu_memory_mb
        if self.limits.gpu_device_id >= 0:
            gpu_cfg["gpu_device_id"] = self.limits.gpu_device_id
        gpu_cfg["enable_gpu"] = self.limits.enable_gpu

        self.gpu_manager = GPUManager(config=gpu_cfg)

        # Initialize resource monitor
        self.resource_monitor = ResourceMonitor()

        logger.info(
            f"LimitingEngine initialized: "
            f"cpu_max={self.limits.max_cpu_percent}%, "
            f"mem_min={self.limits.min_memory_mb}MB, "
            f"gpu_mem_percent={self.limits.max_gpu_memory_percent}%, "
            f"gpu_mem_max={self.limits.max_gpu_memory_mb}MB"
        )

    def check_resources_available(
        self,
        required_memory_mb: float | None = None,
        required_gpu_memory_mb: float | None = None,
        device_required: str = "auto"
    ) -> bool:
        """
        Check if sufficient resources are currently available.

        Args:
            required_memory_mb: Required RAM in MB (uses limits if None)
            required_gpu_memory_mb: Required GPU memory in MB (uses limits if None)
            device_required: Device type: "cpu", "cuda", or "auto"

        Returns:
            True if resources available, False otherwise

        Example:
            if engine.check_resources_available(
                required_memory_mb=2048,
                required_gpu_memory_mb=4096,
                device_required="cuda"
            ):
                # Resources available
                pass
        """
        try:
            snapshot = self.resource_monitor.get_current()

            # Check CPU limits
            if self.limits.max_cpu_percent:
                if snapshot.cpu_percent > self.limits.max_cpu_percent:
                    logger.debug(
                        f"CPU usage too high: {snapshot.cpu_percent:.1f}% "
                        f"(limit: {self.limits.max_cpu_percent}%)"
                    )
                    return False

            # Check RAM limits
            min_memory = required_memory_mb or self.limits.min_memory_mb
            if min_memory:
                if snapshot.memory_available_mb < min_memory:
                    logger.debug(
                        f"Insufficient memory: {snapshot.memory_available_mb:.0f}MB "
                        f"(need: {min_memory}MB)"
                    )
                    return False

            if self.limits.max_memory_percent:
                if snapshot.memory_percent > self.limits.max_memory_percent:
                    logger.debug(
                        f"Memory usage too high: {snapshot.memory_percent:.1f}% "
                        f"(limit: {self.limits.max_memory_percent}%)"
                    )
                    return False

            # Check GPU limits
            if device_required in ["cuda", "gpu"] or (
                device_required == "auto" and self.limits.enable_gpu
            ):
                min_gpu_memory = (
                    required_gpu_memory_mb or self.limits.max_gpu_memory_mb
                )
                if min_gpu_memory:
                    if snapshot.gpu_memory_available_mb is None:
                        logger.debug("GPU required but not available")
                        return False

                    if snapshot.gpu_memory_available_mb < min_gpu_memory:
                        logger.debug(
                            f"Insufficient GPU memory: "
                            f"{snapshot.gpu_memory_available_mb:.0f}MB "
                            f"(need: {min_gpu_memory}MB)"
                        )
                        return False

            return True

        except Exception as e:
            logger.error(f"Failed to check resources: {e}")
            return False

    def wait_for_resources(
        self,
        required_memory_mb: float | None = None,
        required_gpu_memory_mb: float | None = None,
        device_required: str = "auto",
        timeout: float | None = None
    ) -> bool:
        """
        Wait for sufficient resources to become available.

        Polls every 5 seconds until resources are available or timeout.

        Args:
            required_memory_mb: Required RAM in MB (uses limits if None)
            required_gpu_memory_mb: Required GPU memory in MB (uses limits if None)
            device_required: Device type: "cpu", "cuda", or "auto"
            timeout: Max wait time in seconds (uses limits if None)

        Returns:
            True if resources became available, False if timed out

        Example:
            if engine.wait_for_resources(timeout=60):
                # Resources available, proceed
                pass
            else:
                # Timed out waiting
                raise RuntimeError("Resources unavailable")
        """
        timeout_seconds = timeout or self.limits.wait_timeout_seconds

        # Create resource estimate for the monitor
        estimate = ResourceEstimate(
            estimated_memory_mb=required_memory_mb or self.limits.min_memory_mb or 1024.0,
            estimated_gpu_memory_mb=required_gpu_memory_mb or self.limits.max_gpu_memory_mb,
            estimated_duration_seconds=timeout_seconds,
            device_required=device_required,
            confidence=0.8
        )

        logger.info(
            f"Waiting for resources (timeout: {timeout_seconds}s, "
            f"mem: {estimate.estimated_memory_mb:.0f}MB, "
            f"gpu_mem: {estimate.estimated_gpu_memory_mb}MB)"
        )

        result = self.resource_monitor.wait_for_resources(
            estimate=estimate,
            timeout_seconds=timeout_seconds
        )

        if result:
            logger.info("Resources became available")
        else:
            logger.warning(f"Timed out waiting for resources after {timeout_seconds}s")

        return result

    def get_current_resources(self) -> ResourceSnapshot:
        """
        Get current resource snapshot.

        Returns:
            ResourceSnapshot with current CPU, RAM, GPU usage

        Example:
            snapshot = engine.get_current_resources()
            print(f"CPU: {snapshot.cpu_percent}%")
            print(f"RAM available: {snapshot.memory_available_mb}MB")
            print(f"GPU available: {snapshot.gpu_memory_available_mb}MB")
        """
        return self.resource_monitor.get_current()

    def get_gpu_memory(self, device_id: int = 0) -> GPUMemoryInfo | None:
        """
        Get GPU memory info for specific device.

        Args:
            device_id: CUDA device ID

        Returns:
            GPUMemoryInfo or None if not available

        Example:
            mem_info = engine.get_gpu_memory(device_id=0)
            if mem_info:
                print(f"GPU free: {mem_info.free_mb}MB")
        """
        return self.gpu_manager.get_gpu_memory(device_id=device_id)

    def get_all_gpu_memory(self) -> dict[int, GPUMemoryInfo]:
        """
        Get memory info for all available GPUs.

        Returns:
            Dict mapping device_id to GPUMemoryInfo

        Example:
            all_gpus = engine.get_all_gpu_memory()
            for device_id, mem_info in all_gpus.items():
                print(f"GPU {device_id}: {mem_info.free_mb}MB free")
        """
        return self.gpu_manager.get_all_gpu_memory()

    def enforce_gpu_memory_limit(self, device: str) -> bool:
        """
        Enforce GPU memory limit if configured.

        Args:
            device: Device string (e.g., "cuda", "cuda:0")

        Returns:
            True if limit set successfully, False otherwise

        Example:
            if engine.enforce_gpu_memory_limit("cuda:0"):
                # Memory limit enforced
                pass
        """
        return self.gpu_manager.enforce_memory_limit(device=device)

    def clear_gpu_cache(self, device: str | None = None) -> None:
        """
        Clear GPU memory cache.

        Args:
            device: Optional device string, clears all if None

        Example:
            engine.clear_gpu_cache("cuda:0")  # Clear specific device
            engine.clear_gpu_cache()  # Clear all devices
        """
        self.gpu_manager.clear_cache(device=device)

    def auto_select_device(self) -> str:
        """
        Auto-select best available device respecting limits.

        Returns:
            Device string: "cuda", "cuda:N", or "cpu"

        Example:
            device = engine.auto_select_device()
            # Use device for model loading
        """
        device = self.gpu_manager.auto_select_device()
        logger.info(f"Auto-selected device: {device}")
        return device

    def get_limits(self) -> ResourceLimits:
        """
        Get current resource limits configuration.

        Returns:
            ResourceLimits instance

        Example:
            limits = engine.get_limits()
            print(f"Max CPU: {limits.max_cpu_percent}%")
        """
        return self.limits

    def update_limits(self, **kwargs: Any) -> None:
        """
        Update resource limits at runtime.

        Args:
            **kwargs: Limit fields to update

        Example:
            engine.update_limits(max_cpu_percent=90.0, min_memory_mb=4096)
        """
        for key, value in kwargs.items():
            if hasattr(self.limits, key):
                setattr(self.limits, key, value)
                logger.info(f"Updated limit: {key}={value}")
            else:
                logger.warning(f"Unknown limit key: {key}")

    def get_gpu_manager(self) -> GPUManager:
        """
        Get underlying GPUManager for advanced usage.

        Returns:
            GPUManager instance

        Note:
            Most code should use LimitingEngine methods instead of
            accessing the manager directly.
        """
        return self.gpu_manager

    def get_resource_monitor(self) -> ResourceMonitor:
        """
        Get underlying ResourceMonitor for advanced usage.

        Returns:
            ResourceMonitor instance

        Note:
            Most code should use LimitingEngine methods instead of
            accessing the monitor directly.
        """
        return self.resource_monitor
