"""
Job queue system for managing translation jobs.

Supports both in-memory and Redis-backed queues for persistence.
"""

import heapq
import logging
import threading
import uuid
from typing import Dict, List, Optional

from .models import JobStats, JobStatus, TranslationJob

logger = logging.getLogger(__name__)


class JobQueue:
    """
    Priority queue for translation jobs.

    Jobs are ordered by priority (lower = higher priority), then by creation time (FIFO).
    Supports concurrent access with thread-safe operations.
    """

    def __init__(self, backend: str = "memory"):
        """
        Initialize job queue.

        Args:
            backend: Queue backend ('memory' or 'redis')
        """
        self.backend = backend
        self._lock = threading.RLock()
        self._heap: List[TranslationJob] = []
        self._jobs: Dict[str, TranslationJob] = {}  # job_id -> job

        if backend == "redis":
            logger.warning("Redis backend not yet implemented, falling back to memory")
            self.backend = "memory"

    def enqueue(self, job: TranslationJob) -> str:
        """
        Add job to queue.

        Args:
            job: TranslationJob to enqueue

        Returns:
            Job ID
        """
        with self._lock:
            # Generate ID if not set
            if not job.job_id:
                job.job_id = self._generate_job_id()

            # Check for duplicate
            if job.job_id in self._jobs:
                raise ValueError(f"Job {job.job_id} already exists")

            # Set to pending
            job.status = JobStatus.PENDING

            # Add to heap and dict
            heapq.heappush(self._heap, job)
            self._jobs[job.job_id] = job

            logger.info(
                f"Enqueued job {job.job_id} (type={job.job_type.value}, "
                f"priority={job.priority}, site={job.site_id})"
            )

            return job.job_id

    def dequeue(self) -> Optional[TranslationJob]:
        """
        Get highest priority pending job.

        Returns:
            TranslationJob or None if queue is empty
        """
        with self._lock:
            # Find next pending job (skip running/completed jobs)
            while self._heap:
                job = heapq.heappop(self._heap)

                # Check if job still pending (might have been cancelled)
                if job.status == JobStatus.PENDING:
                    job.status = JobStatus.RUNNING
                    logger.info(f"Dequeued job {job.job_id}")
                    return job

                # Job was cancelled/completed, remove from dict
                if job.job_id in self._jobs:
                    del self._jobs[job.job_id]

            return None

    def peek(self, n: int = 10) -> List[TranslationJob]:
        """
        Look at next N pending jobs without removing.

        Args:
            n: Number of jobs to peek at

        Returns:
            List of up to N pending jobs
        """
        with self._lock:
            pending = [
                job
                for job in sorted(self._heap)
                if job.status == JobStatus.PENDING
            ]
            return pending[:n]

    def get_job(self, job_id: str) -> Optional[TranslationJob]:
        """
        Get job by ID.

        Args:
            job_id: Job identifier

        Returns:
            TranslationJob or None if not found
        """
        with self._lock:
            return self._jobs.get(job_id)

    def update_job_status(
        self,
        job_id: str,
        status: JobStatus,
        error_message: Optional[str] = None,
        result_summary: Optional[Dict] = None,
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
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            job.status = status

            if error_message:
                job.error_message = error_message

            if result_summary:
                job.result_summary = result_summary

            if status in (JobStatus.COMPLETED, JobStatus.FAILED, JobStatus.CANCELLED):
                from datetime import datetime

                job.completed_at = datetime.now()

            logger.info(f"Updated job {job_id} status to {status.value}")
            return True

    def cancel_job(self, job_id: str) -> bool:
        """
        Cancel pending job.

        Args:
            job_id: Job identifier

        Returns:
            True if cancelled, False if job not found or already running
        """
        with self._lock:
            job = self._jobs.get(job_id)
            if not job:
                return False

            if job.status != JobStatus.PENDING:
                logger.warning(
                    f"Cannot cancel job {job_id} with status {job.status.value}"
                )
                return False

            job.status = JobStatus.CANCELLED
            from datetime import datetime

            job.completed_at = datetime.now()

            logger.info(f"Cancelled job {job_id}")
            return True

    def list_jobs(
        self, status: Optional[JobStatus] = None, limit: int = 100
    ) -> List[TranslationJob]:
        """
        List all jobs, optionally filtered by status.

        Args:
            status: Optional status filter
            limit: Maximum number of jobs to return

        Returns:
            List of TranslationJob instances
        """
        with self._lock:
            jobs = list(self._jobs.values())

            if status:
                jobs = [j for j in jobs if j.status == status]

            # Sort by creation time (newest first)
            jobs.sort(key=lambda j: j.created_at, reverse=True)

            return jobs[:limit]

    def get_stats(self) -> JobStats:
        """
        Get queue statistics.

        Returns:
            JobStats with counts by status
        """
        with self._lock:
            stats = JobStats(total_jobs=len(self._jobs))

            for job in self._jobs.values():
                if job.status == JobStatus.PENDING:
                    stats.pending_jobs += 1
                elif job.status == JobStatus.RUNNING:
                    stats.running_jobs += 1
                elif job.status == JobStatus.COMPLETED:
                    stats.completed_jobs += 1
                elif job.status == JobStatus.FAILED:
                    stats.failed_jobs += 1
                elif job.status == JobStatus.CANCELLED:
                    stats.cancelled_jobs += 1

            return stats

    def clear_completed(self, older_than_hours: int = 24) -> int:
        """
        Clear completed/failed/cancelled jobs older than specified hours.

        Args:
            older_than_hours: Age threshold in hours

        Returns:
            Number of jobs cleared
        """
        from datetime import datetime, timedelta

        with self._lock:
            threshold = datetime.now() - timedelta(hours=older_than_hours)
            to_remove = []

            for job_id, job in self._jobs.items():
                if job.status in (
                    JobStatus.COMPLETED,
                    JobStatus.FAILED,
                    JobStatus.CANCELLED,
                ):
                    if job.completed_at and job.completed_at < threshold:
                        to_remove.append(job_id)

            for job_id in to_remove:
                del self._jobs[job_id]

            # Rebuild heap (remove cleared jobs)
            self._heap = [j for j in self._heap if j.job_id in self._jobs]
            heapq.heapify(self._heap)

            if to_remove:
                logger.info(f"Cleared {len(to_remove)} old jobs")

            return len(to_remove)

    def _generate_job_id(self) -> str:
        """Generate unique job ID."""
        return f"job_{uuid.uuid4().hex[:12]}"
