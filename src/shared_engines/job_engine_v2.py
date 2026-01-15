"""
JobEngine V2 - Production-grade job queue with backend switching and failover.

Extends JobEngine with:
- Dynamic backend selection (Redis, Memory, etc.)
- Health checks and auto-failover
- Auto-recovery to primary backend
- Configuration-driven backend selection
- Telemetry for backend state changes
"""

import logging
import os
import threading
import time
from typing import Optional, List, Dict, Any

from src.queues import QueueBackend, MemoryQueueBackend, RedisQueueBackend
from src.orchestrator.queue import JobQueue
from src.orchestrator.redis_backend import RedisJobQueue
from src.orchestrator.models import TranslationJob, JobStatus, JobStats

logger = logging.getLogger(__name__)


class JobEngineV2:
    """
    Production-grade job queue engine with backend switching and failover.

    Features:
    - Dynamic backend selection (redis, memory)
    - Automatic failover to fallback backend on health check failure
    - Automatic recovery to primary backend when available
    - Configuration-driven backend selection (4-tier precedence)
    - Health monitoring with configurable intervals
    - Telemetry events for backend state changes

    Backend Selection Precedence (highest to lowest):
    1. Environment variable QUEUE_BACKEND
    2. Execution mode default (from global.yaml execution.modes.<mode>.queue_backend)
    3. Global queue.backend (from global.yaml queue.backend)
    4. Fallback backend (queue.fallback_backend)
    5. Hardcoded default ("redis")

    Args:
        config: Configuration dictionary with keys:
            - backend: Primary backend type ("redis" or "memory")
            - fallback_backend: Fallback backend type (default: "memory")
            - redis: Redis configuration dict
                - host: Redis host (default: "localhost")
                - port: Redis port (default: 6379)
                - db: Redis database number (default: 0)
                - password: Optional Redis password
                - max_retries: Connection retry attempts (default: 3)
                - retry_delay: Delay between retries (default: 1.0)
                - health_check_interval: Health check interval in seconds (default: 60)
            - memory: Memory queue configuration dict
                - max_queue_size: Maximum queue size (default: 1000)
            - telemetry: Optional telemetry engine for event emission

    Example:
        config = {
            "backend": "redis",
            "fallback_backend": "memory",
            "redis": {
                "host": "localhost",
                "port": 6379,
                "health_check_interval": 60
            },
            "memory": {
                "max_queue_size": 1000
            }
        }

        engine = JobEngineV2(config=config)

        # Enqueue job
        job_id = engine.enqueue(job)

        # Dequeue job
        job = engine.dequeue()

        # Backend automatically fails over if Redis becomes unavailable
        # Backend automatically recovers when Redis becomes available again
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        """Initialize job engine with backend switching."""
        self.config = config or {}

        # Determine backends
        self.primary_backend_type = self._select_backend("primary")
        self.fallback_backend_type = self._select_backend("fallback")

        # Backend instances
        self.primary_backend: Optional[QueueBackend] = None
        self.fallback_backend: Optional[QueueBackend] = None
        self.current_backend: Optional[QueueBackend] = None
        self.current_backend_type: Optional[str] = None

        # Legacy queue wrappers (for backward compatibility)
        self.queue: Optional[Any] = None
        self.backend_type: Optional[str] = None

        # Health monitoring
        self.health_check_interval = self.config.get("redis", {}).get(
            "health_check_interval", 60
        )
        self.last_health_check = 0
        self.health_check_cooldown = 10  # Minimum seconds between recovery attempts
        self.last_recovery_attempt = 0

        # State tracking
        self._lock = threading.RLock()
        self._closed = False
        self._failover_count = 0
        self._recovery_count = 0

        # Telemetry (optional)
        self.telemetry = self.config.get("telemetry")

        # Initialize backends
        self._initialize_backends()

        logger.info(
            f"JobEngineV2 initialized: primary={self.primary_backend_type}, "
            f"fallback={self.fallback_backend_type}, "
            f"current={self.current_backend_type}"
        )

    def _select_backend(self, backend_role: str) -> str:
        """
        Select backend type based on 4-tier precedence.

        Args:
            backend_role: "primary" or "fallback"

        Returns:
            Backend type string ("redis" or "memory")
        """
        # Tier 1: Environment variable (highest priority)
        env_backend = os.getenv("QUEUE_BACKEND")
        if env_backend and backend_role == "primary":
            logger.info(
                f"Backend selected from QUEUE_BACKEND env var: {env_backend}"
            )
            return env_backend

        # Tier 2: Execution mode default (from caller's config)
        # This would be passed in config by CompositionRoot after loading global.yaml
        mode_backend = self.config.get(f"{backend_role}_backend_from_mode")
        if mode_backend:
            logger.info(
                f"Backend selected from execution mode: {mode_backend}"
            )
            return mode_backend

        # Tier 3: Explicit config (from global.yaml or caller)
        if backend_role == "primary":
            config_backend = self.config.get("backend")
            if config_backend:
                return config_backend

        # Tier 4: Fallback backend
        if backend_role == "fallback":
            fallback = self.config.get("fallback_backend", "memory")
            return fallback

        # Tier 5: Hardcoded default
        return "redis" if backend_role == "primary" else "memory"

    def _initialize_backends(self):
        """Initialize primary and fallback backends."""
        # Initialize primary backend
        try:
            self.primary_backend = self._create_backend(self.primary_backend_type)
            self.current_backend = self.primary_backend
            self.current_backend_type = self.primary_backend_type

            self._emit_telemetry("queue_backend_selected", {
                "backend_type": self.primary_backend_type,
                "role": "primary"
            })

        except Exception as e:
            logger.error(
                f"Failed to initialize primary backend ({self.primary_backend_type}): {e}"
            )
            self._emit_telemetry("queue_backend_init_failed", {
                "backend_type": self.primary_backend_type,
                "error": str(e)
            })

            # Fall back to fallback backend immediately
            self._initialize_fallback()

        # Initialize fallback backend (lazy)
        if self.current_backend_type != self.fallback_backend_type:
            # Don't initialize fallback yet, wait until needed
            pass

        # Initialize legacy wrapper for backward compatibility
        self._initialize_legacy_wrapper()

    def _initialize_fallback(self):
        """Initialize and switch to fallback backend."""
        try:
            if not self.fallback_backend:
                self.fallback_backend = self._create_backend(
                    self.fallback_backend_type
                )

            self.current_backend = self.fallback_backend
            self.current_backend_type = self.fallback_backend_type
            self._failover_count += 1

            logger.warning(
                f"Switched to fallback backend: {self.fallback_backend_type} "
                f"(failover count: {self._failover_count})"
            )

            self._emit_telemetry("queue_backend_failover", {
                "from_backend": self.primary_backend_type,
                "to_backend": self.fallback_backend_type,
                "failover_count": self._failover_count
            })

        except Exception as e:
            logger.critical(
                f"Failed to initialize fallback backend ({self.fallback_backend_type}): {e}"
            )
            raise RuntimeError(
                f"Both primary and fallback backends failed to initialize"
            )

    def _create_backend(self, backend_type: str) -> QueueBackend:
        """Create backend instance based on type."""
        if backend_type == "redis":
            redis_config = self.config.get("redis", {})
            return RedisQueueBackend(
                host=redis_config.get("host", "localhost"),
                port=redis_config.get("port", 6379),
                db=redis_config.get("db", 0),
                password=redis_config.get("password"),
                max_retries=redis_config.get("max_retries", 3),
                retry_delay=redis_config.get("retry_delay", 1.0)
            )

        elif backend_type == "memory":
            memory_config = self.config.get("memory", {})
            return MemoryQueueBackend(
                max_queue_size=memory_config.get("max_queue_size", 1000)
            )

        else:
            raise ValueError(
                f"Unsupported backend type: {backend_type}. Use 'redis' or 'memory'."
            )

    def _initialize_legacy_wrapper(self):
        """Initialize legacy queue wrapper for backward compatibility."""
        # Create legacy wrapper based on current backend type
        if self.current_backend_type == "redis":
            redis_config = self.config.get("redis", {})
            self.queue = RedisJobQueue(
                host=redis_config.get("host", "localhost"),
                port=redis_config.get("port", 6379),
                db=redis_config.get("db", 0),
                password=redis_config.get("password")
            )
        else:
            self.queue = JobQueue(backend="memory")

        self.backend_type = self.current_backend_type

    def _check_backend_health(self):
        """
        Check backend health and perform failover/recovery if needed.

        This method is called periodically to:
        1. Check if current backend is healthy
        2. Failover to fallback if primary is unhealthy
        3. Recover to primary if it becomes healthy again
        """
        current_time = time.time()

        # Rate limit health checks
        if current_time - self.last_health_check < self.health_check_interval:
            return

        self.last_health_check = current_time

        with self._lock:
            # Check current backend health
            is_healthy = self.current_backend.health_check()

            if not is_healthy:
                logger.warning(
                    f"Backend health check failed: {self.current_backend_type}"
                )

                self._emit_telemetry("queue_backend_health_check_failed", {
                    "backend_type": self.current_backend_type,
                    "failover_count": self._failover_count
                })

                # If we're on primary, failover to fallback
                if self.current_backend_type == self.primary_backend_type:
                    self._perform_failover()

            else:
                # Backend is healthy
                # If we're on fallback, try to recover to primary
                if self.current_backend_type == self.fallback_backend_type:
                    self._attempt_recovery()

    def _perform_failover(self):
        """Switch from primary to fallback backend."""
        logger.warning(
            f"Performing failover: {self.primary_backend_type} -> {self.fallback_backend_type}"
        )

        # Initialize fallback if not already done
        if not self.fallback_backend:
            self._initialize_fallback()
        else:
            self.current_backend = self.fallback_backend
            self.current_backend_type = self.fallback_backend_type
            self._failover_count += 1

            self._emit_telemetry("queue_backend_failover", {
                "from_backend": self.primary_backend_type,
                "to_backend": self.fallback_backend_type,
                "failover_count": self._failover_count
            })

        # Update legacy wrapper
        self._initialize_legacy_wrapper()

    def _attempt_recovery(self):
        """Attempt to recover from fallback to primary backend."""
        current_time = time.time()

        # Rate limit recovery attempts (cooldown period)
        if current_time - self.last_recovery_attempt < self.health_check_cooldown:
            return

        self.last_recovery_attempt = current_time

        # Check if primary backend is healthy
        if not self.primary_backend:
            try:
                self.primary_backend = self._create_backend(self.primary_backend_type)
            except Exception as e:
                logger.warning(
                    f"Failed to recreate primary backend for recovery: {e}"
                )
                return

        if self.primary_backend.health_check():
            logger.info(
                f"Primary backend is healthy, recovering: "
                f"{self.fallback_backend_type} -> {self.primary_backend_type}"
            )

            self.current_backend = self.primary_backend
            self.current_backend_type = self.primary_backend_type
            self._recovery_count += 1

            self._emit_telemetry("queue_backend_recovery", {
                "from_backend": self.fallback_backend_type,
                "to_backend": self.primary_backend_type,
                "recovery_count": self._recovery_count
            })

            # Update legacy wrapper
            self._initialize_legacy_wrapper()

        else:
            logger.debug(
                f"Primary backend still unhealthy, staying on fallback"
            )

    def _emit_telemetry(self, event_type: str, data: Dict[str, Any]):
        """Emit telemetry event (non-fatal)."""
        if not self.telemetry:
            return

        try:
            self.telemetry.emit(event_type, data)
        except Exception as e:
            logger.debug(f"Failed to emit telemetry event '{event_type}': {e}")

    # Public API methods (delegate to current backend + legacy wrapper)

    def enqueue(self, job: TranslationJob) -> str:
        """
        Add job to queue.

        Automatically checks backend health before operation.

        Args:
            job: TranslationJob to enqueue

        Returns:
            Job ID

        Example:
            job_id = engine.enqueue(job)
        """
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        # Check backend health periodically
        self._check_backend_health()

        try:
            # Use legacy wrapper for now (maintains backward compatibility)
            job_id = self.queue.enqueue(job)

            logger.debug(
                f"Enqueued job {job_id} to {self.current_backend_type} backend"
            )

            return job_id

        except Exception as e:
            logger.error(f"Failed to enqueue job: {e}")

            self._emit_telemetry("queue_operation_failed", {
                "operation": "enqueue",
                "backend_type": self.current_backend_type,
                "error": str(e)
            })

            raise

    def dequeue(self) -> Optional[TranslationJob]:
        """
        Get next highest-priority job from queue.

        Automatically checks backend health before operation.

        Returns:
            TranslationJob or None if queue is empty

        Example:
            job = engine.dequeue()
        """
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        # Check backend health periodically
        self._check_backend_health()

        try:
            job = self.queue.dequeue()

            if job:
                logger.debug(
                    f"Dequeued job {job.job_id} from {self.current_backend_type} backend"
                )

            return job

        except Exception as e:
            logger.error(f"Failed to dequeue job: {e}")

            self._emit_telemetry("queue_operation_failed", {
                "operation": "dequeue",
                "backend_type": self.current_backend_type,
                "error": str(e)
            })

            raise

    def get_status(self, job_id: str) -> Optional[TranslationJob]:
        """Get job by ID (check status)."""
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        return self.queue.get_job(job_id)

    def list_pending(self, limit: int = 10) -> List[TranslationJob]:
        """List pending jobs in priority order."""
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        return self.queue.peek(n=limit)

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        result_summary: Optional[Dict] = None
    ) -> bool:
        """Update job status."""
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        return self.queue.update_job_status(
            job_id=job_id,
            status=status,
            error_message=error_message,
            result_summary=result_summary
        )

    def get_stats(self) -> JobStats:
        """Get queue statistics."""
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        return self.queue.get_stats()

    def list_jobs(
        self,
        status: Optional[JobStatus] = None,
        limit: int = 100
    ) -> List[TranslationJob]:
        """List all jobs, optionally filtered by status."""
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        if self.backend_type == "memory":
            return self.queue.list_jobs(status=status, limit=limit)
        else:
            logger.warning(
                "list_jobs() not supported for Redis backend, returning empty list"
            )
            return []

    def shutdown(self) -> None:
        """Clean up queue resources."""
        with self._lock:
            if not self._closed:
                logger.info("Shutting down JobEngineV2")

                # Close legacy wrapper
                if self.queue and hasattr(self.queue, 'close'):
                    try:
                        self.queue.close()
                    except Exception as e:
                        logger.warning(f"Error closing legacy queue wrapper: {e}")

                # Close backends
                if self.primary_backend:
                    try:
                        self.primary_backend.close()
                    except Exception as e:
                        logger.warning(f"Error closing primary backend: {e}")

                if self.fallback_backend:
                    try:
                        self.fallback_backend.close()
                    except Exception as e:
                        logger.warning(f"Error closing fallback backend: {e}")

                self._closed = True

                logger.info(
                    f"JobEngineV2 shut down (failovers: {self._failover_count}, "
                    f"recoveries: {self._recovery_count})"
                )

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        if self._closed:
            raise RuntimeError("JobEngine is closed")

        if self.backend_type == "redis":
            return self.queue.is_empty()
        else:
            pending = self.queue.peek(n=1)
            return len(pending) == 0

    def get_backend_type(self) -> str:
        """Get current backend type."""
        return self.current_backend_type

    def get_backend_stats(self) -> Dict[str, Any]:
        """
        Get backend statistics and health information.

        Returns:
            Dictionary with backend stats:
                - primary_backend: Primary backend type
                - current_backend: Current active backend type
                - fallback_backend: Fallback backend type
                - failover_count: Number of failovers
                - recovery_count: Number of recoveries
                - is_healthy: Current backend health status
        """
        return {
            "primary_backend": self.primary_backend_type,
            "current_backend": self.current_backend_type,
            "fallback_backend": self.fallback_backend_type,
            "failover_count": self._failover_count,
            "recovery_count": self._recovery_count,
            "is_healthy": self.current_backend.health_check() if self.current_backend else False
        }
