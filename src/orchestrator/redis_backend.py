"""
Redis backend for distributed job queue.

Provides persistent, distributed queue using Redis as the backend.
"""

import json
import logging
import uuid

from .models import JobStats, JobStatus, TranslationJob

logger = logging.getLogger(__name__)


class RedisQueueBackend:
    """
    Redis-backed job queue for distributed systems.

    Uses Redis sorted sets for priority queue and hashes for job storage.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        key_prefix: str = "hugo_translation",
    ):
        """
        Initialize Redis backend.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Optional Redis password
            key_prefix: Prefix for all Redis keys
        """
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.key_prefix = key_prefix

        # Redis client (lazy initialization)
        self._redis: any | None = None

        # Redis keys
        self.queue_key = f"{key_prefix}:queue"  # Sorted set for priority queue
        self.jobs_key = f"{key_prefix}:jobs"  # Hash for job data
        self.stats_key = f"{key_prefix}:stats"  # Hash for statistics

    def _get_redis(self) -> any:
        """Get or create Redis connection."""
        if self._redis is None:
            try:
                import redis

                self._redis = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=True,
                )
                # Test connection
                self._redis.ping()
                logger.info(f"Connected to Redis at {self.host}:{self.port}")

            except ImportError:
                raise RuntimeError(
                    "redis-py not installed. Install with: pip install redis"
                )
            except Exception as e:
                raise RuntimeError(f"Failed to connect to Redis: {e}")

        return self._redis

    def enqueue(self, job: TranslationJob) -> str:
        """
        Add job to Redis queue.

        Args:
            job: TranslationJob to enqueue

        Returns:
            Job ID
        """
        redis = self._get_redis()

        # Generate ID if not set
        if not job.job_id:
            job.job_id = str(uuid.uuid4())

        # Check for duplicate
        if redis.hexists(self.jobs_key, job.job_id):
            raise ValueError(f"Job {job.job_id} already exists")

        # Set status to pending
        job.status = JobStatus.PENDING

        # Serialize job
        job_data = self._serialize_job(job)

        # Add to queue (sorted set) with score = (priority, timestamp)
        # Lower priority numbers = higher priority
        # Score format: priority * 1e10 + timestamp (for FIFO within same priority)
        import time

        score = job.priority * 1e10 + time.time()

        # Use pipeline for atomic operation
        pipe = redis.pipeline()
        pipe.zadd(self.queue_key, {job.job_id: score})
        pipe.hset(self.jobs_key, job.job_id, job_data)
        pipe.hincrby(self.stats_key, "total_enqueued", 1)
        pipe.hincrby(self.stats_key, "pending", 1)
        pipe.execute()

        logger.info(
            f"Enqueued job {job.job_id} to Redis "
            f"(type={job.job_type.value}, priority={job.priority})"
        )

        return job.job_id

    def dequeue(self) -> TranslationJob | None:
        """
        Get highest priority pending job from Redis.

        Returns:
            TranslationJob or None if queue is empty
        """
        redis = self._get_redis()

        # Get job with lowest score (highest priority)
        results = redis.zrange(self.queue_key, 0, 0, withscores=False)

        if not results:
            return None

        job_id = results[0]

        # Get job data
        job_data = redis.hget(self.jobs_key, job_id)
        if not job_data:
            # Job exists in queue but not in storage - remove from queue
            redis.zrem(self.queue_key, job_id)
            return None

        # Deserialize job
        job = self._deserialize_job(job_data)

        # Check status
        if job.status != JobStatus.PENDING:
            # Job was already processed - remove from queue
            redis.zrem(self.queue_key, job_id)
            return self.dequeue()  # Try next job

        # Update status to running
        job.status = JobStatus.RUNNING

        # Atomic update: remove from queue and update status
        pipe = redis.pipeline()
        pipe.zrem(self.queue_key, job_id)
        pipe.hset(self.jobs_key, job_id, self._serialize_job(job))
        pipe.hincrby(self.stats_key, "pending", -1)
        pipe.hincrby(self.stats_key, "running", 1)
        pipe.execute()

        logger.info(f"Dequeued job {job_id} from Redis")

        return job

    def get_job(self, job_id: str) -> TranslationJob | None:
        """
        Get job by ID.

        Args:
            job_id: Job identifier

        Returns:
            TranslationJob or None if not found
        """
        redis = self._get_redis()
        job_data = redis.hget(self.jobs_key, job_id)

        if not job_data:
            return None

        return self._deserialize_job(job_data)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
        result_summary: dict | None = None,
    ) -> bool:
        """
        Update job status in Redis.

        Args:
            job_id: Job identifier
            status: New status
            error_message: Optional error message
            result_summary: Optional result summary

        Returns:
            True if updated, False if job not found
        """
        redis = self._get_redis()

        # Get current job
        job_data = redis.hget(self.jobs_key, job_id)
        if not job_data:
            return False

        job = self._deserialize_job(job_data)
        old_status = job.status

        # Update status
        job.status = status
        if error_message:
            job.error_message = error_message
        if result_summary:
            job.result_summary = result_summary

        # Save updated job
        pipe = redis.pipeline()
        pipe.hset(self.jobs_key, job_id, self._serialize_job(job))

        # Update statistics
        if old_status != status:
            if old_status == JobStatus.PENDING:
                pipe.hincrby(self.stats_key, "pending", -1)
            elif old_status == JobStatus.RUNNING:
                pipe.hincrby(self.stats_key, "running", -1)

            if status == JobStatus.COMPLETED:
                pipe.hincrby(self.stats_key, "completed", 1)
            elif status == JobStatus.FAILED:
                pipe.hincrby(self.stats_key, "failed", 1)

        pipe.execute()

        logger.info(f"Updated job {job_id} status: {old_status.value} -> {status.value}")

        return True

    def peek(self, n: int = 10) -> list[TranslationJob]:
        """
        Look at next N pending jobs without removing.

        Args:
            n: Number of jobs to peek at

        Returns:
            List of up to N pending jobs
        """
        redis = self._get_redis()

        # Get job IDs with lowest scores
        job_ids = redis.zrange(self.queue_key, 0, n - 1)

        jobs = []
        for job_id in job_ids:
            job = self.get_job(job_id)
            if job and job.status == JobStatus.PENDING:
                jobs.append(job)

        return jobs

    def get_stats(self) -> JobStats:
        """
        Get queue statistics.

        Returns:
            JobStats with queue metrics
        """
        redis = self._get_redis()

        stats_data = redis.hgetall(self.stats_key)

        return JobStats(
            total_enqueued=int(stats_data.get("total_enqueued", 0)),
            pending=int(stats_data.get("pending", 0)),
            running=int(stats_data.get("running", 0)),
            completed=int(stats_data.get("completed", 0)),
            failed=int(stats_data.get("failed", 0)),
        )

    def size(self) -> int:
        """
        Get number of jobs in queue.

        Returns:
            Queue size
        """
        redis = self._get_redis()
        return redis.zcard(self.queue_key)

    def clear(self) -> None:
        """Clear all jobs from queue."""
        redis = self._get_redis()

        pipe = redis.pipeline()
        pipe.delete(self.queue_key)
        pipe.delete(self.jobs_key)
        pipe.delete(self.stats_key)
        pipe.execute()

        logger.info("Cleared Redis queue")

    def close(self) -> None:
        """Close Redis connection."""
        if self._redis:
            self._redis.close()
            self._redis = None
            logger.info("Closed Redis connection")

    @staticmethod
    def _serialize_job(job: TranslationJob) -> str:
        """Serialize job to JSON string."""
        return json.dumps(job.to_dict())

    @staticmethod
    def _deserialize_job(job_data: str) -> TranslationJob:
        """Deserialize job from JSON string."""
        data = json.loads(job_data)
        return TranslationJob.from_dict(data)


class RedisJobQueue:
    """
    Job queue with Redis backend.

    Wrapper around RedisQueueBackend with the same interface as JobQueue.
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
    ):
        """
        Initialize Redis job queue.

        Args:
            host: Redis host
            port: Redis port
            db: Redis database number
            password: Optional Redis password
        """
        self.backend = RedisQueueBackend(
            host=host,
            port=port,
            db=db,
            password=password,
        )

    def enqueue(self, job: TranslationJob) -> str:
        """Add job to queue."""
        return self.backend.enqueue(job)

    def dequeue(self) -> TranslationJob | None:
        """Get next job from queue."""
        return self.backend.dequeue()

    def peek(self, n: int = 10) -> list[TranslationJob]:
        """Look at next N jobs without removing."""
        return self.backend.peek(n)

    def get_job(self, job_id: str) -> TranslationJob | None:
        """Get job by ID."""
        return self.backend.get_job(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: str | None = None,
        result_summary: dict | None = None,
    ) -> bool:
        """Update job status."""
        return self.backend.update_job_status(
            job_id, status, error_message, result_summary
        )

    def get_stats(self) -> JobStats:
        """Get queue statistics."""
        return self.backend.get_stats()

    def size(self) -> int:
        """Get queue size."""
        return self.backend.size()

    def is_empty(self) -> bool:
        """Check if queue is empty."""
        return self.size() == 0

    def clear(self) -> None:
        """Clear all jobs."""
        self.backend.clear()

    def close(self) -> None:
        """Close connection."""
        self.backend.close()

    def __len__(self) -> int:
        """Return queue size."""
        return self.size()
