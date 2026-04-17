"""
JobEngine - Unified job queue abstraction for translation jobs.

Wraps existing JobQueue and RedisJobQueue to provide consistent interface
across execution modes (memory-based for CLI, Redis for distributed workers).

Version 2: Adds backend switching, health checks, and auto-failover support.
"""

import logging
from typing import Any

from src.orchestrator.models import JobStats, JobStatus, TranslationJob
from src.orchestrator.queue import JobQueue
from src.orchestrator.redis_backend import RedisJobQueue

logger = logging.getLogger(__name__)


class JobEngine:
    """
    Unified job queue engine for managing translation jobs.

    Version 2: Supports backend switching with health checks and auto-failover.

    Wraps JobQueue (memory) or RedisJobQueue (distributed) to provide
    consistent interface across execution modes.

    Supports two initialization patterns:
    1. Legacy: backend + redis_config parameters (backward compatible)
    2. New: config dictionary with backend switching support

    Args:
        backend: (Legacy) Queue backend type ("memory" or "redis")
        redis_config: (Legacy) Optional Redis configuration
        config: (New) Configuration dictionary with:
            - backend: Primary backend type ("redis" or "memory")
            - fallback_backend: Fallback backend type (default: "memory")
            - redis: Redis configuration dict
            - memory: Memory queue configuration dict
            - telemetry: Optional telemetry engine

    Example:
        # Legacy API (backward compatible)
        engine = JobEngine(backend="redis", redis_config={"host": "localhost"})

        # New API with backend switching
        engine = JobEngine(config={
            "backend": "redis",
            "fallback_backend": "memory",
            "redis": {"host": "localhost", "port": 6379},
            "memory": {"max_queue_size": 1000}
        })
    """

    def __init__(
        self,
        backend: str | None = None,
        redis_config: dict[str, Any] | None = None,
        config: dict[str, Any] | None = None
    ):
        """Initialize job queue engine."""
        # Determine initialization mode
        if config is not None:
            # New API: Use backend switching with V2 engine
            self._use_v2 = True
            self._init_v2(config)
        else:
            # Legacy API: Use simple backend selection
            self._use_v2 = False
            self._init_legacy(backend, redis_config)

    def _init_legacy(self, backend: str | None, redis_config: dict[str, Any] | None):
        """Initialize using legacy API (backward compatible)."""
        self.backend_type = backend or "memory"
        self.redis_config = redis_config or {}

        # Initialize underlying queue
        if self.backend_type == "memory":
            self.queue = JobQueue(backend="memory")
            logger.info("JobEngine initialized: backend=memory (legacy mode)")
        elif self.backend_type == "redis":
            host = self.redis_config.get("host", "localhost")
            port = self.redis_config.get("port", 6379)
            db = self.redis_config.get("db", 0)
            password = self.redis_config.get("password", None)

            self.queue = RedisJobQueue(
                host=host,
                port=port,
                db=db,
                password=password
            )
            logger.info(
                f"JobEngine initialized: backend=redis, host={host}:{port} (legacy mode)"
            )
        else:
            raise ValueError(
                f"Unsupported backend: {self.backend_type}. Use 'memory' or 'redis'."
            )

    def _init_v2(self, config: dict[str, Any]):
        """Initialize using V2 API with backend switching."""
        from src.shared_engines.job_engine_v2 import JobEngineV2

        self._engine_v2 = JobEngineV2(config=config)

        # Expose V2 attributes for compatibility
        self.backend_type = self._engine_v2.current_backend_type
        self.queue = self._engine_v2.queue
        self.redis_config = config.get("redis", {})

        logger.info(
            f"JobEngine initialized: backend={self.backend_type} (V2 mode with failover)"
        )

    def enqueue(self, job: TranslationJob) -> str:
        """
        Add job to queue.

        Args:
            job: TranslationJob to enqueue

        Returns:
            Job ID

        Raises:
            ValueError: If job already exists in queue

        Example:
            job = TranslationJob(
                job_id="job_123",
                job_type=JobType.FILE,
                site_id="products.aspose.com",
                target_langs=["es", "fr"],
                input_paths=[Path("content/example.md")]
            )
            job_id = engine.enqueue(job)
        """
        if self._use_v2:
            return self._engine_v2.enqueue(job)

        job_id = self.queue.enqueue(job)
        logger.debug(
            f"Enqueued job {job_id}: type={job.job_type.value}, "
            f"priority={job.priority}, site={job.site_id}"
        )
        return job_id

    def dequeue(self) -> TranslationJob | None:
        """
        Get next highest-priority job from queue.

        Returns:
            TranslationJob or None if queue is empty

        Note:
            Job status is automatically set to RUNNING when dequeued.

        Example:
            job = engine.dequeue()
            if job:
                # Process job...
                engine.update_status(job.job_id, JobStatus.COMPLETED)
        """
        if self._use_v2:
            return self._engine_v2.dequeue()

        job = self.queue.dequeue()
        if job:
            logger.debug(
                f"Dequeued job {job.job_id}: type={job.job_type.value}, "
                f"priority={job.priority}"
            )
        else:
            logger.debug("Queue is empty, no job dequeued")
        return job

    def get_status(self, job_id: str) -> TranslationJob | None:
        """
        Get job by ID (check status).

        Args:
            job_id: Job identifier

        Returns:
            TranslationJob or None if not found

        Example:
            job = engine.get_status("job_123")
            if job:
                print(f"Job status: {job.status.value}")
        """
        job = self.queue.get_job(job_id)
        if job:
            logger.debug(
                f"Retrieved job {job_id}: status={job.status.value}"
            )
        else:
            logger.debug(f"Job {job_id} not found")
        return job

    def list_pending(self, limit: int = 10) -> list[TranslationJob]:
        """
        List pending jobs in priority order.

        Args:
            limit: Maximum number of jobs to return (default: 10)

        Returns:
            List of pending TranslationJob instances

        Example:
            pending_jobs = engine.list_pending(limit=20)
            for job in pending_jobs:
                print(f"Job {job.job_id}: priority={job.priority}")
        """
        # JobQueue uses peek() method, RedisJobQueue also has peek()
        jobs = self.queue.peek(n=limit)
        logger.debug(f"Listed {len(jobs)} pending jobs (limit={limit})")
        return jobs

    def update_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
        result_summary: dict | None = None
    ) -> bool:
        """
        Update job status.

        Args:
            job_id: Job identifier
            status: New status
            error_message: Optional error message (for FAILED status)
            result_summary: Optional result summary (for COMPLETED status)

        Returns:
            True if updated, False if job not found

        Example:
            # Mark job as completed
            success = engine.update_status(
                job_id="job_123",
                status=JobStatus.COMPLETED,
                result_summary={"files_translated": 5, "total_tokens": 1500}
            )

            # Mark job as failed
            success = engine.update_status(
                job_id="job_456",
                status=JobStatus.FAILED,
                error_message="Translation service unavailable"
            )
        """
        success = self.queue.update_job_status(
            job_id=job_id,
            status=status,
            error_message=error_message,
            result_summary=result_summary
        )

        if success:
            logger.debug(f"Updated job {job_id} status to {status.value}")
        else:
            logger.warning(f"Failed to update job {job_id} (not found)")

        return success

    def get_stats(self) -> JobStats:
        """
        Get queue statistics.

        Returns:
            JobStats with counts by status

        Example:
            stats = engine.get_stats()
            print(f"Pending: {stats.pending}, Running: {stats.running}")
            print(f"Completed: {stats.completed}, Failed: {stats.failed}")
        """
        stats = self.queue.get_stats()
        logger.debug(
            f"Queue stats: pending={stats.pending}, running={stats.running}, "
            f"completed={stats.completed}, failed={stats.failed}"
        )
        return stats

    def list_jobs(
        self,
        status: JobStatus | None = None,
        limit: int = 100
    ) -> list[TranslationJob]:
        """
        List all jobs, optionally filtered by status.

        Args:
            status: Optional status filter
            limit: Maximum number of jobs to return (default: 100)

        Returns:
            List of TranslationJob instances

        Note:
            Only available for memory backend. Redis backend doesn't
            support this operation (use get_status() for individual jobs).

        Example:
            # List all completed jobs
            completed = engine.list_jobs(status=JobStatus.COMPLETED)

            # List all jobs (any status)
            all_jobs = engine.list_jobs(limit=1000)
        """
        if self.backend_type == "memory":
            jobs = self.queue.list_jobs(status=status, limit=limit)
            logger.debug(
                f"Listed {len(jobs)} jobs "
                f"(status={status.value if status else 'all'}, limit={limit})"
            )
            return jobs
        else:
            logger.warning(
                "list_jobs() not supported for Redis backend, returning empty list"
            )
            return []

    def shutdown(self) -> None:
        """
        Clean up queue resources.

        Closes connections and releases resources.

        Example:
            engine = JobEngine(backend="redis")
            try:
                # ... use engine ...
                pass
            finally:
                engine.shutdown()
        """
        if self._use_v2:
            self._engine_v2.shutdown()
            return

        if self.backend_type == "redis":
            logger.info("Shutting down JobEngine (Redis backend)")
            self.queue.close()
            logger.info("JobEngine shut down (Redis connection closed)")
        else:
            logger.info("Shutting down JobEngine (memory backend, no-op)")

    def is_empty(self) -> bool:
        """
        Check if queue is empty.

        Returns:
            True if no pending jobs, False otherwise

        Example:
            if engine.is_empty():
                print("No jobs to process")
        """
        if self.backend_type == "redis":
            return self.queue.is_empty()
        else:
            # Memory backend: check if peek returns empty list
            pending = self.queue.peek(n=1)
            return len(pending) == 0

    def get_backend_type(self) -> str:
        """
        Get queue backend type.

        Returns:
            Backend type ("memory" or "redis")

        Example:
            if engine.get_backend_type() == "redis":
                print("Using distributed queue")
        """
        if self._use_v2:
            return self._engine_v2.get_backend_type()
        return self.backend_type

    def get_backend_stats(self) -> dict[str, Any] | None:
        """
        Get backend statistics (V2 only).

        Returns:
            Dictionary with backend stats or None if not using V2

        Example:
            stats = engine.get_backend_stats()
            if stats:
                print(f"Failover count: {stats['failover_count']}")
        """
        if self._use_v2:
            return self._engine_v2.get_backend_stats()
        return None
