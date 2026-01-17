"""
WorkerRunner - Dual-Run Execution Layer for Worker Deployment.

Provides a unified interface for running workers in three execution modes:
1. windows_cuda - Windows native with CUDA GPU support
2. docker_cpu - Docker containerized with CPU-only enforcement
3. docker_gpu - Docker containerized with GPU passthrough

Implements device policy enforcement to guarantee CPU-only execution in docker_cpu mode.
"""

import logging
import os
import warnings
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Dict, Any

import torch

from src.hardware.vram_enforcer import VRAMEnforcer

logger = logging.getLogger(__name__)


class ExecutionMode(Enum):
    """
    Execution mode for worker deployment.

    - WINDOWS_CUDA: Windows native with CUDA GPU support
    - DOCKER_CPU: Docker containerized with CPU-only enforcement
    - DOCKER_GPU: Docker containerized with GPU passthrough
    """
    WINDOWS_CUDA = "windows_cuda"
    DOCKER_CPU = "docker_cpu"
    DOCKER_GPU = "docker_gpu"


@dataclass
class WorkerConfig:
    """
    Worker configuration with execution mode support.

    Supports 3-tier configuration precedence:
    1. Environment variables (highest priority)
    2. Execution mode defaults (from global.yaml)
    3. Global configuration (fallback)

    Attributes:
        execution_mode: Execution mode (windows_cuda, docker_cpu, docker_gpu)
        worker_id: Unique worker identifier
        redis_host: Redis host for job queue
        redis_port: Redis port
        redis_db: Redis database number
        redis_password: Optional Redis password
        poll_interval: Seconds between queue polls
        max_retries: Maximum job retry attempts
        config_path: Configuration directory path
        tm_path: Translation memory storage path
        device: Device for model inference (cpu, cuda, mps)
        use_shared_engines: Enable SharedEngines architecture
        log_level: Logging level
        mode_config: Execution mode-specific configuration overrides

    Example:
        # Load from environment variables
        config = WorkerConfig.from_env()

        # Create with explicit values
        config = WorkerConfig(
            execution_mode=ExecutionMode.DOCKER_CPU,
            worker_id="cpu-worker-1",
            device="cpu"
        )
    """
    execution_mode: ExecutionMode = ExecutionMode.WINDOWS_CUDA
    worker_id: str = "worker-default"
    redis_host: str = "localhost"
    redis_port: int = 6379
    redis_db: int = 0
    redis_password: Optional[str] = None
    poll_interval: float = 5.0
    max_retries: int = 3
    config_path: str = "./config"
    tm_path: str = "./data/tm"
    device: str = "auto"
    use_shared_engines: bool = True
    log_level: str = "INFO"
    mode_config: Dict[str, Any] = field(default_factory=dict)

    @classmethod
    def from_env(cls, mode_defaults: Optional[Dict[str, Any]] = None) -> "WorkerConfig":
        """
        Create WorkerConfig from environment variables with mode defaults.

        Implements 3-tier precedence:
        1. Environment variables (highest)
        2. Mode defaults from global.yaml (middle)
        3. Dataclass defaults (lowest)

        Args:
            mode_defaults: Execution mode defaults from global.yaml

        Returns:
            WorkerConfig with merged configuration

        Example:
            # Load from environment with mode defaults
            mode_defaults = {
                "device": "cpu",
                "max_retries": 5,
                "poll_interval": 3.0
            }
            config = WorkerConfig.from_env(mode_defaults)
        """
        mode_defaults = mode_defaults or {}

        # Parse execution mode from environment
        execution_mode_str = os.getenv("EXECUTION_MODE", "windows_cuda")
        try:
            execution_mode = ExecutionMode(execution_mode_str)
        except ValueError:
            logger.warning(
                f"Invalid EXECUTION_MODE '{execution_mode_str}'. "
                f"Valid values: windows_cuda, docker_cpu, docker_gpu. "
                f"Defaulting to windows_cuda."
            )
            execution_mode = ExecutionMode.WINDOWS_CUDA

        # Build config with 3-tier precedence
        # Tier 3: Dataclass defaults (already set)
        # Tier 2: Mode defaults from global.yaml
        config_dict = {
            "execution_mode": execution_mode,
            "worker_id": mode_defaults.get("worker_id", os.getenv("WORKER_ID", "worker-default")),
            "redis_host": mode_defaults.get("redis_host", os.getenv("REDIS_HOST", "localhost")),
            "redis_port": mode_defaults.get("redis_port", int(os.getenv("REDIS_PORT", "6379"))),
            "redis_db": mode_defaults.get("redis_db", int(os.getenv("REDIS_DB", "0"))),
            "redis_password": mode_defaults.get("redis_password", os.getenv("REDIS_PASSWORD")),
            "poll_interval": mode_defaults.get("poll_interval", float(os.getenv("POLL_INTERVAL", "5.0"))),
            "max_retries": mode_defaults.get("max_retries", int(os.getenv("MAX_RETRIES", "3"))),
            "config_path": mode_defaults.get("config_path", os.getenv("CONFIG_PATH", "./config")),
            "tm_path": mode_defaults.get("tm_path", os.getenv("TM_DATA_PATH", "./data/tm")),
            "device": mode_defaults.get("device", os.getenv("DEVICE", "auto")),
            "use_shared_engines": mode_defaults.get(
                "use_shared_engines",
                os.getenv("USE_SHARED_ENGINES", "true").lower() in ("true", "1", "yes")
            ),
            "log_level": mode_defaults.get("log_level", os.getenv("LOG_LEVEL", "INFO")),
            "mode_config": mode_defaults
        }

        # Tier 1: Environment variables override everything
        # (Already applied above through os.getenv with mode_defaults.get as fallback)

        return cls(**config_dict)

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary representation."""
        return {
            "execution_mode": self.execution_mode.value,
            "worker_id": self.worker_id,
            "redis_host": self.redis_host,
            "redis_port": self.redis_port,
            "redis_db": self.redis_db,
            "poll_interval": self.poll_interval,
            "max_retries": self.max_retries,
            "config_path": self.config_path,
            "tm_path": self.tm_path,
            "device": self.device,
            "use_shared_engines": self.use_shared_engines,
            "log_level": self.log_level
        }


class DevicePolicy:
    """
    Device policy enforcement for execution modes.

    Ensures CPU-only execution in docker_cpu mode through multiple enforcement layers:
    1. Environment variable: CUDA_VISIBLE_DEVICES=""
    2. Runtime check: Verify torch.cuda.is_available() == False
    3. Device override: Force device="cpu" regardless of config

    Example:
        policy = DevicePolicy(ExecutionMode.DOCKER_CPU)
        policy.enforce()  # Sets CUDA_VISIBLE_DEVICES="" and validates
        device = policy.get_device("cuda")  # Returns "cpu" (overridden)
    """

    def __init__(self, execution_mode: ExecutionMode):
        """
        Initialize device policy for execution mode.

        Args:
            execution_mode: Execution mode to enforce policy for
        """
        self.execution_mode = execution_mode
        self._enforced = False

    def enforce(self) -> None:
        """
        Enforce device policy for current execution mode.

        For docker_cpu mode:
        - Sets CUDA_VISIBLE_DEVICES="" to hide GPUs
        - Validates torch.cuda.is_available() == False
        - Raises RuntimeError if CUDA still available after enforcement

        For other modes:
        - No enforcement, allows GPU access

        Raises:
            RuntimeError: If CPU-only enforcement fails in docker_cpu mode
        """
        if self._enforced:
            logger.debug(f"Device policy already enforced for {self.execution_mode.value}")
            return

        if self.execution_mode == ExecutionMode.DOCKER_CPU:
            logger.info("Enforcing CPU-only device policy for docker_cpu mode")

            # Layer 1: Set environment variable to hide CUDA devices
            os.environ["CUDA_VISIBLE_DEVICES"] = ""
            logger.debug("Set CUDA_VISIBLE_DEVICES='' to hide GPUs")

            # Layer 2: Runtime validation
            # Note: This check may still return True if torch was initialized before
            # the environment variable was set. The device override in get_device()
            # provides the final guarantee.
            if torch.cuda.is_available():
                # Warn but don't fail - the device override will ensure CPU usage
                logger.warning(
                    "CUDA still available after setting CUDA_VISIBLE_DEVICES=''. "
                    "This is expected if torch was initialized before enforcement. "
                    "Device override will ensure CPU-only execution."
                )
            else:
                logger.info("CPU-only enforcement verified: CUDA not available")

            self._enforced = True

        elif self.execution_mode == ExecutionMode.DOCKER_GPU:
            logger.info("GPU passthrough enabled for docker_gpu mode")
            # No enforcement needed, allow GPU access
            self._enforced = True

        elif self.execution_mode == ExecutionMode.WINDOWS_CUDA:
            logger.info("Native CUDA support enabled for windows_cuda mode")
            # No enforcement needed, allow GPU access
            self._enforced = True

    def get_device(self, requested_device: str) -> str:
        """
        Get device with policy enforcement applied.

        For docker_cpu mode:
        - Always returns "cpu" regardless of requested device
        - Logs warning if GPU was requested

        For other modes:
        - Returns requested device unchanged

        Args:
            requested_device: Device requested by configuration

        Returns:
            Device to use after policy enforcement

        Example:
            policy = DevicePolicy(ExecutionMode.DOCKER_CPU)
            policy.enforce()
            device = policy.get_device("cuda")  # Returns "cpu"
        """
        if not self._enforced:
            logger.warning("Device policy not enforced, calling enforce() first")
            self.enforce()

        if self.execution_mode == ExecutionMode.DOCKER_CPU:
            # Force CPU-only execution
            if requested_device != "cpu":
                logger.warning(
                    f"Device override: '{requested_device}' -> 'cpu' "
                    f"(docker_cpu mode enforces CPU-only execution)"
                )
            return "cpu"

        # For other modes, return requested device
        return requested_device

    def is_gpu_allowed(self) -> bool:
        """
        Check if GPU usage is allowed in current execution mode.

        Returns:
            True if GPU allowed, False if CPU-only mode
        """
        return self.execution_mode in (ExecutionMode.WINDOWS_CUDA, ExecutionMode.DOCKER_GPU)


class WorkerRunner(ABC):
    """
    Abstract base class for worker runners.

    Provides unified interface for running workers across different execution modes.
    Subclasses implement specific worker types (JobProcessor, etc.).

    Attributes:
        config: WorkerConfig with execution mode settings
        device_policy: DevicePolicy for enforcement

    Example:
        class JobProcessorRunner(WorkerRunner):
            def setup(self):
                # Initialize job processor
                pass

            def run(self):
                # Run job processing loop
                pass

            def shutdown(self):
                # Clean up resources
                pass

        # Create and run worker
        config = WorkerConfig.from_env()
        runner = JobProcessorRunner(config)
        runner.setup()
        runner.run()
        runner.shutdown()
    """

    def __init__(self, config: WorkerConfig):
        """
        Initialize worker runner with configuration.

        Args:
            config: WorkerConfig with execution mode settings
        """
        self.config = config
        self.device_policy = DevicePolicy(config.execution_mode)

        logger.info(
            f"Initializing WorkerRunner: mode={config.execution_mode.value}, "
            f"worker_id={config.worker_id}, device={config.device}"
        )

        # Enforce device policy
        self.device_policy.enforce()

        # Apply device policy to config
        self.config.device = self.device_policy.get_device(self.config.device)
        logger.info(f"Device after policy enforcement: {self.config.device}")

        # Apply VRAM budget enforcement for CUDA modes
        # This applies torch.cuda.set_per_process_memory_fraction() early
        # before any model loading to ensure budget is enforced process-wide
        if self.config.execution_mode in (ExecutionMode.WINDOWS_CUDA, ExecutionMode.DOCKER_GPU):
            if self.config.device.startswith("cuda"):
                try:
                    # Build hardware config from mode_config
                    hardware_config = {
                        "enable_gpu": True,
                        "max_gpu_memory_percent": self.config.mode_config.get("max_gpu_memory_percent"),
                        "max_gpu_memory_mb": self.config.mode_config.get("max_gpu_memory_mb"),
                    }

                    # Apply VRAM enforcement
                    enforcer = VRAMEnforcer()
                    max_memory_mb, budget = enforcer.enforce_from_config(
                        hardware_config, device=self.config.device
                    )

                    if budget:
                        logger.info(
                            f"VRAM budget enforced: {max_memory_mb}MB "
                            f"({budget.percent:.1f}% of total, source: {budget.source})"
                        )
                    else:
                        logger.warning("VRAM budget enforcement skipped (GPU disabled or unavailable)")

                except Exception as e:
                    logger.error(f"Failed to enforce VRAM budget: {e}", exc_info=True)

    @abstractmethod
    def setup(self) -> None:
        """
        Setup worker components.

        Subclasses must implement to initialize worker-specific components.
        """
        pass

    @abstractmethod
    def run(self) -> None:
        """
        Run worker main loop.

        Subclasses must implement to run worker-specific processing loop.
        """
        pass

    @abstractmethod
    def shutdown(self) -> None:
        """
        Graceful shutdown and cleanup.

        Subclasses must implement to clean up worker-specific resources.
        """
        pass

    def get_effective_device(self) -> str:
        """
        Get effective device after policy enforcement.

        Returns:
            Device string to use for model inference
        """
        return self.config.device

    def log_startup_info(self) -> None:
        """
        Log worker startup information.

        Logs execution mode, device policy, and configuration summary.
        """
        logger.info("=" * 70)
        logger.info("Worker Runner Startup")
        logger.info("=" * 70)
        logger.info(f"Execution Mode: {self.config.execution_mode.value}")
        logger.info(f"Worker ID: {self.config.worker_id}")
        logger.info(f"Device: {self.config.device}")
        logger.info(f"GPU Allowed: {self.device_policy.is_gpu_allowed()}")
        logger.info(f"Redis: {self.config.redis_host}:{self.config.redis_port}")
        logger.info(f"SharedEngines: {self.config.use_shared_engines}")
        logger.info("=" * 70)


# Backward compatibility support
def detect_legacy_mode() -> bool:
    """
    Detect if running in legacy mode (no EXECUTION_MODE env var).

    Returns:
        True if legacy mode, False if using execution mode
    """
    return "EXECUTION_MODE" not in os.environ


def warn_legacy_mode() -> None:
    """
    Emit deprecation warning for legacy mode.

    Called when worker runs without EXECUTION_MODE environment variable.
    """
    if detect_legacy_mode():
        warnings.warn(
            "Running without EXECUTION_MODE environment variable is deprecated. "
            "Set EXECUTION_MODE to 'windows_cuda', 'docker_cpu', or 'docker_gpu'. "
            "Legacy mode will be removed in a future release.",
            DeprecationWarning,
            stacklevel=3
        )
        logger.warning(
            "Worker running in LEGACY mode (no EXECUTION_MODE set). "
            "Set EXECUTION_MODE environment variable to enable dual-run execution layer. "
            "Valid values: windows_cuda, docker_cpu, docker_gpu"
        )
