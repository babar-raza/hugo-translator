"""
End-to-End Integration Tests for Redis Queue + Worker Processing.

Tests the complete flow:
- Orchestrator creates jobs in Redis queue
- Workers dequeue and process jobs
- Job status updates propagate through Redis
- System handles failures gracefully
"""

import os
import tempfile
import time
from pathlib import Path
from typing import Generator

import pytest

from src.orchestrator.models import JobStatus, JobType, TranslationJob
from src.orchestrator.redis_backend import RedisJobQueue


@pytest.fixture
def redis_queue() -> Generator[RedisJobQueue, None, None]:
    """
    Create Redis queue for testing.

    Uses DB 15 for test isolation.
    """
    queue = RedisJobQueue(
        host=os.getenv("REDIS_HOST", "localhost"),
        port=int(os.getenv("REDIS_PORT", 6379)),
        db=15,  # Test database
    )

    # Clear test database before test
    queue._get_redis().flushdb()

    yield queue

    # Cleanup after test
    queue._get_redis().flushdb()
    queue.close()


@pytest.fixture
def sample_job() -> TranslationJob:
    """Create a minimal translation job for testing."""
    return TranslationJob(
        job_id="test-job-001",
        job_type=JobType.FILE,
        site_id="example",
        target_langs=["es", "fr"],
        input_paths=[Path("/content/example/test.md")],
        priority=5,
    )


class TestRedisQueueBasics:
    """Test basic Redis queue operations."""

    def test_enqueue_dequeue_cycle(self, redis_queue: RedisJobQueue, sample_job: TranslationJob):
        """Test enqueuing and dequeuing a single job."""
        # Enqueue job
        job_id = redis_queue.enqueue(sample_job)
        assert job_id == sample_job.job_id

        # Verify queue size
        stats = redis_queue.get_stats()
        assert stats.pending == 1
        assert stats.running == 0
        assert stats.completed == 0

        # Dequeue job
        dequeued_job = redis_queue.dequeue()
        assert dequeued_job is not None
        assert dequeued_job.job_id == sample_job.job_id
        assert dequeued_job.status == JobStatus.RUNNING

        # Verify queue stats updated
        stats = redis_queue.get_stats()
        assert stats.pending == 0
        assert stats.running == 1

    def test_multiple_jobs_fifo_order(self, redis_queue: RedisJobQueue):
        """Test multiple jobs processed in priority order."""
        jobs = [
            TranslationJob(
                job_id=f"job-{i}",
                job_type=JobType.FILE,
                site_id="example",
                target_langs=["es"],
                input_paths=[Path(f"/content/test{i}.md")],
                priority=priority,
            )
            for i, priority in enumerate([5, 3, 7, 1, 9])  # Different priorities
        ]

        # Enqueue all jobs
        for job in jobs:
            redis_queue.enqueue(job)

        # Dequeue and verify priority order (1 is highest)
        dequeued_ids = []
        while True:
            job = redis_queue.dequeue()
            if not job:
                break
            dequeued_ids.append(job.job_id)

        # Jobs should be dequeued in priority order: 1, 3, 5, 7, 9
        assert dequeued_ids == ["job-3", "job-1", "job-0", "job-2", "job-4"]

    def test_job_status_updates(self, redis_queue: RedisJobQueue, sample_job: TranslationJob):
        """Test updating job status through lifecycle."""
        # Enqueue job
        redis_queue.enqueue(sample_job)

        # Dequeue job (status → RUNNING)
        job = redis_queue.dequeue()
        assert job.status == JobStatus.RUNNING

        # Update to COMPLETED
        redis_queue.update_job_status(
            job_id=job.job_id,
            status=JobStatus.COMPLETED,
            result_summary={"files_processed": 1},
        )

        # Verify status persisted
        updated_job = redis_queue.get_job(job.job_id)
        assert updated_job.status == JobStatus.COMPLETED
        assert updated_job.result_summary["files_processed"] == 1

        # Verify stats
        stats = redis_queue.get_stats()
        assert stats.completed == 1
        assert stats.running == 0

    def test_job_persistence_across_connections(self, sample_job: TranslationJob):
        """Test jobs persist in Redis across queue reconnections."""
        # Create queue and enqueue job
        queue1 = RedisJobQueue(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=15,
        )
        queue1._get_redis().flushdb()
        queue1.enqueue(sample_job)
        queue1.close()

        # Create new queue instance and verify job exists
        queue2 = RedisJobQueue(
            host=os.getenv("REDIS_HOST", "localhost"),
            port=int(os.getenv("REDIS_PORT", 6379)),
            db=15,
        )

        job = queue2.dequeue()
        assert job is not None
        assert job.job_id == sample_job.job_id

        # Cleanup
        queue2._get_redis().flushdb()
        queue2.close()

    def test_concurrent_dequeue_no_duplicates(self, redis_queue: RedisJobQueue):
        """Test multiple workers don't dequeue same job."""
        # Enqueue 10 jobs
        jobs = [
            TranslationJob(
                job_id=f"job-{i:03d}",
                job_type=JobType.FILE,
                site_id="example",
                target_langs=["es"],
                input_paths=[Path(f"/content/test{i}.md")],
                priority=5,
            )
            for i in range(10)
        ]

        for job in jobs:
            redis_queue.enqueue(job)

        # Simulate concurrent workers by dequeuing rapidly
        dequeued_jobs = set()
        for _ in range(10):
            job = redis_queue.dequeue()
            if job:
                # Verify no duplicate
                assert job.job_id not in dequeued_jobs
                dequeued_jobs.add(job.job_id)

        # All jobs should be dequeued exactly once
        assert len(dequeued_jobs) == 10

    def test_failed_job_handling(self, redis_queue: RedisJobQueue, sample_job: TranslationJob):
        """Test marking job as failed."""
        # Enqueue and dequeue job
        redis_queue.enqueue(sample_job)
        job = redis_queue.dequeue()

        # Mark job as failed with error message
        error_msg = "Translation engine failed: Model not loaded"
        redis_queue.update_job_status(
            job_id=job.job_id,
            status=JobStatus.FAILED,
            error_message=error_msg,
        )

        # Verify failure recorded
        failed_job = redis_queue.get_job(job.job_id)
        assert failed_job.status == JobStatus.FAILED
        assert failed_job.error_message == error_msg

        # Verify stats
        stats = redis_queue.get_stats()
        assert stats.failed == 1
        assert stats.running == 0

    def test_empty_queue_dequeue_returns_none(self, redis_queue: RedisJobQueue):
        """Test dequeuing from empty queue returns None."""
        job = redis_queue.dequeue()
        assert job is None

    def test_queue_size_reporting(self, redis_queue: RedisJobQueue):
        """Test queue size returns correct count."""
        # Empty queue
        assert redis_queue.size() == 0

        # Add jobs
        for i in range(5):
            job = TranslationJob(
                job_id=f"job-{i}",
                job_type=JobType.FILE,
                site_id="example",
                target_langs=["es"],
                input_paths=[Path(f"/content/test{i}.md")],
                priority=5,
            )
            redis_queue.enqueue(job)

        assert redis_queue.size() == 5

        # Dequeue one
        redis_queue.dequeue()
        assert redis_queue.size() == 4


class TestJobDataSerialization:
    """Test job serialization and deserialization."""

    def test_complex_job_roundtrip(self, redis_queue: RedisJobQueue):
        """Test complex job with all fields serializes correctly."""
        from datetime import datetime
        from src.orchestrator.models import JobMode

        job = TranslationJob(
            job_id="complex-job-001",
            job_type=JobType.SWEEP_BATCH,
            site_id="docs.example.com",
            target_langs=["es", "fr", "de", "ja"],
            input_paths=[
                Path("/content/docs/guide.md"),
                Path("/content/docs/api.md"),
            ],
            priority=3,
            created_at=datetime.now(),
            mode=JobMode.AUTO,
            metadata={
                "sweep_id": "sweep-123",
                "batch_number": 42,
                "extra_data": {"key": "value"},
            },
        )

        # Enqueue and dequeue
        redis_queue.enqueue(job)
        dequeued = redis_queue.dequeue()

        # Verify all fields preserved
        assert dequeued.job_id == job.job_id
        assert dequeued.job_type == job.job_type
        assert dequeued.site_id == job.site_id
        assert dequeued.target_langs == job.target_langs
        assert dequeued.input_paths == job.input_paths
        assert dequeued.priority == job.priority
        assert dequeued.mode == job.mode
        assert dequeued.metadata == job.metadata

    def test_path_serialization(self, redis_queue: RedisJobQueue):
        """Test Path objects serialize to strings and back."""
        job = TranslationJob(
            job_id="path-test",
            job_type=JobType.FILE,
            site_id="example",
            target_langs=["es"],
            input_paths=[
                Path("/absolute/path/file.md"),
                Path("relative/path/file.md"),
            ],
            priority=5,
        )

        redis_queue.enqueue(job)
        dequeued = redis_queue.dequeue()

        # Paths should be Path objects
        assert all(isinstance(p, Path) for p in dequeued.input_paths)
        assert dequeued.input_paths[0] == Path("/absolute/path/file.md")
        assert dequeued.input_paths[1] == Path("relative/path/file.md")


class TestEdgeCases:
    """Test edge cases and error conditions."""

    def test_update_nonexistent_job(self, redis_queue: RedisJobQueue):
        """Test updating job that doesn't exist."""
        # This should not raise an error
        redis_queue.update_job_status(
            job_id="nonexistent-job",
            status=JobStatus.COMPLETED,
        )

        # Job should not exist
        job = redis_queue.get_job("nonexistent-job")
        assert job is None

    def test_get_nonexistent_job(self, redis_queue: RedisJobQueue):
        """Test getting job that doesn't exist."""
        job = redis_queue.get_job("nonexistent-job")
        assert job is None

    def test_large_batch_processing(self, redis_queue: RedisJobQueue):
        """Test handling large number of jobs."""
        # Create 100 jobs
        for i in range(100):
            job = TranslationJob(
                job_id=f"batch-job-{i:04d}",
                job_type=JobType.FILE,
                site_id="example",
                target_langs=["es"],
                input_paths=[Path(f"/content/file{i}.md")],
                priority=5,
            )
            redis_queue.enqueue(job)

        # Verify all enqueued
        assert redis_queue.size() == 100
        stats = redis_queue.get_stats()
        assert stats.pending == 100

        # Process all
        processed = 0
        while redis_queue.size() > 0:
            job = redis_queue.dequeue()
            if job:
                processed += 1
                redis_queue.update_job_status(
                    job_id=job.job_id,
                    status=JobStatus.COMPLETED,
                )

        assert processed == 100
        stats = redis_queue.get_stats()
        assert stats.completed == 100


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
