"""
Unit tests for job queue system.
"""

from datetime import datetime, timedelta
from pathlib import Path

import pytest

from src.orchestrator.models import JobMode, JobStatus, JobType, TranslationJob
from src.orchestrator.queue import JobQueue


@pytest.fixture
def queue():
    """Create empty job queue."""
    return JobQueue(backend="memory")


@pytest.fixture
def sample_job():
    """Create sample translation job."""
    return TranslationJob(
        job_id="test_job_1",
        job_type=JobType.FILE,
        site_id="test_site",
        target_langs=["fr", "es"],
        input_paths=[Path("content/test.md")],
        priority=5,
    )


class TestJobQueueBasics:
    """Test basic queue operations."""

    def test_queue_initialization(self, queue):
        """Test queue initialization."""
        assert queue.backend == "memory"
        stats = queue.get_stats()
        assert stats.total_jobs == 0
        assert stats.pending_jobs == 0

    def test_enqueue_job(self, queue, sample_job):
        """Test enqueueing a job."""
        job_id = queue.enqueue(sample_job)

        assert job_id == "test_job_1"
        assert sample_job.status == JobStatus.PENDING

        stats = queue.get_stats()
        assert stats.total_jobs == 1
        assert stats.pending_jobs == 1

    def test_enqueue_generates_id(self, queue):
        """Test that queue generates ID if not provided."""
        job = TranslationJob(
            job_id="",  # Empty ID
            job_type=JobType.FILE,
            site_id="test_site",
            target_langs=["fr"],
            input_paths=[Path("test.md")],
        )

        job_id = queue.enqueue(job)

        assert job_id
        assert job_id.startswith("job_")
        assert len(job_id) > 4

    def test_enqueue_duplicate_fails(self, queue, sample_job):
        """Test that duplicate job IDs are rejected."""
        queue.enqueue(sample_job)

        with pytest.raises(ValueError, match="already exists"):
            queue.enqueue(sample_job)

    def test_dequeue_job(self, queue, sample_job):
        """Test dequeueing a job."""
        queue.enqueue(sample_job)

        job = queue.dequeue()

        assert job is not None
        assert job.job_id == "test_job_1"
        assert job.status == JobStatus.RUNNING

        stats = queue.get_stats()
        assert stats.running_jobs == 1
        assert stats.pending_jobs == 0

    def test_dequeue_empty_queue(self, queue):
        """Test dequeueing from empty queue."""
        job = queue.dequeue()
        assert job is None

    def test_get_job(self, queue, sample_job):
        """Test getting job by ID."""
        queue.enqueue(sample_job)

        job = queue.get_job("test_job_1")

        assert job is not None
        assert job.job_id == "test_job_1"

        # Non-existent job
        job = queue.get_job("nonexistent")
        assert job is None


class TestJobPriority:
    """Test priority queue behavior."""

    def test_priority_order(self, queue):
        """Test that jobs are dequeued by priority."""
        # Create jobs with different priorities
        job1 = TranslationJob(
            job_id="low_priority",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test1.md")],
            priority=8,  # Low priority (high number)
        )

        job2 = TranslationJob(
            job_id="high_priority",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test2.md")],
            priority=2,  # High priority (low number)
        )

        job3 = TranslationJob(
            job_id="medium_priority",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test3.md")],
            priority=5,  # Medium priority
        )

        # Enqueue in random order
        queue.enqueue(job1)
        queue.enqueue(job2)
        queue.enqueue(job3)

        # Dequeue should be in priority order
        assert queue.dequeue().job_id == "high_priority"
        assert queue.dequeue().job_id == "medium_priority"
        assert queue.dequeue().job_id == "low_priority"

    def test_fifo_for_same_priority(self, queue):
        """Test FIFO order for jobs with same priority."""
        import time

        job1 = TranslationJob(
            job_id="first",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test1.md")],
            priority=5,
        )

        time.sleep(0.01)  # Ensure different timestamps

        job2 = TranslationJob(
            job_id="second",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test2.md")],
            priority=5,
        )

        queue.enqueue(job1)
        queue.enqueue(job2)

        # Should dequeue in FIFO order
        assert queue.dequeue().job_id == "first"
        assert queue.dequeue().job_id == "second"

    def test_peek(self, queue):
        """Test peeking at pending jobs."""
        for i in range(5):
            job = TranslationJob(
                job_id=f"job_{i}",
                job_type=JobType.FILE,
                site_id="test",
                target_langs=["fr"],
                input_paths=[Path(f"test{i}.md")],
                priority=i,
            )
            queue.enqueue(job)

        # Peek at top 3
        jobs = queue.peek(n=3)

        assert len(jobs) == 3
        assert jobs[0].job_id == "job_0"  # Highest priority
        assert jobs[1].job_id == "job_1"
        assert jobs[2].job_id == "job_2"

        # Queue should still have all jobs
        stats = queue.get_stats()
        assert stats.pending_jobs == 5


class TestJobStatus:
    """Test job status management."""

    def test_update_job_status(self, queue, sample_job):
        """Test updating job status."""
        queue.enqueue(sample_job)

        success = queue.update_job_status("test_job_1", JobStatus.COMPLETED)

        assert success is True
        job = queue.get_job("test_job_1")
        assert job.status == JobStatus.COMPLETED
        assert job.completed_at is not None

    def test_update_with_error_message(self, queue, sample_job):
        """Test updating status with error message."""
        queue.enqueue(sample_job)

        success = queue.update_job_status(
            "test_job_1", JobStatus.FAILED, error_message="Translation failed"
        )

        assert success is True
        job = queue.get_job("test_job_1")
        assert job.status == JobStatus.FAILED
        assert job.error_message == "Translation failed"

    def test_update_with_result_summary(self, queue, sample_job):
        """Test updating status with result summary."""
        queue.enqueue(sample_job)

        result = {"files_translated": 1, "duration": 5.2}
        success = queue.update_job_status(
            "test_job_1", JobStatus.COMPLETED, result_summary=result
        )

        assert success is True
        job = queue.get_job("test_job_1")
        assert job.result_summary == result

    def test_update_nonexistent_job(self, queue):
        """Test updating nonexistent job."""
        success = queue.update_job_status("nonexistent", JobStatus.COMPLETED)
        assert success is False

    def test_cancel_job(self, queue, sample_job):
        """Test cancelling a job."""
        queue.enqueue(sample_job)

        success = queue.cancel_job("test_job_1")

        assert success is True
        job = queue.get_job("test_job_1")
        assert job.status == JobStatus.CANCELLED
        assert job.completed_at is not None

    def test_cannot_cancel_running_job(self, queue, sample_job):
        """Test that running jobs cannot be cancelled."""
        queue.enqueue(sample_job)
        queue.dequeue()  # Mark as running

        success = queue.cancel_job("test_job_1")

        assert success is False
        job = queue.get_job("test_job_1")
        assert job.status == JobStatus.RUNNING


class TestJobListing:
    """Test job listing and filtering."""

    def test_list_all_jobs(self, queue):
        """Test listing all jobs."""
        for i in range(5):
            job = TranslationJob(
                job_id=f"job_{i}",
                job_type=JobType.FILE,
                site_id="test",
                target_langs=["fr"],
                input_paths=[Path(f"test{i}.md")],
            )
            queue.enqueue(job)

        jobs = queue.list_jobs()

        assert len(jobs) == 5

    def test_list_by_status(self, queue):
        """Test filtering jobs by status."""
        # Create jobs with different statuses
        job1 = TranslationJob(
            job_id="pending_job",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test1.md")],
            priority=6,  # Lower priority
        )

        job2 = TranslationJob(
            job_id="running_job",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test2.md")],
            priority=4,  # Higher priority - will be dequeued first
        )

        queue.enqueue(job1)
        queue.enqueue(job2)
        queue.dequeue()  # job2 becomes running (higher priority)

        # List pending jobs
        pending = queue.list_jobs(status=JobStatus.PENDING)
        assert len(pending) == 1
        assert pending[0].job_id == "pending_job"

        # List running jobs
        running = queue.list_jobs(status=JobStatus.RUNNING)
        assert len(running) == 1
        assert running[0].job_id == "running_job"

    def test_list_respects_limit(self, queue):
        """Test that listing respects limit."""
        for i in range(20):
            job = TranslationJob(
                job_id=f"job_{i}",
                job_type=JobType.FILE,
                site_id="test",
                target_langs=["fr"],
                input_paths=[Path(f"test{i}.md")],
            )
            queue.enqueue(job)

        jobs = queue.list_jobs(limit=10)

        assert len(jobs) == 10


class TestStatistics:
    """Test queue statistics."""

    def test_get_stats(self, queue):
        """Test getting queue statistics."""
        # Create jobs with different statuses
        pending = TranslationJob(
            job_id="pending",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test1.md")],
        )

        running = TranslationJob(
            job_id="running",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test2.md")],
        )

        completed = TranslationJob(
            job_id="completed",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test3.md")],
        )

        queue.enqueue(pending)
        queue.enqueue(running)
        queue.enqueue(completed)

        queue.dequeue()  # running job
        queue.update_job_status("completed", JobStatus.COMPLETED)

        stats = queue.get_stats()

        assert stats.total_jobs == 3
        assert stats.pending_jobs == 1
        assert stats.running_jobs == 1
        assert stats.completed_jobs == 1
        assert stats.active_jobs == 2

    def test_clear_completed(self, queue):
        """Test clearing old completed jobs."""
        # Create old completed job
        old_job = TranslationJob(
            job_id="old_job",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test.md")],
        )
        old_job.completed_at = datetime.now() - timedelta(hours=48)
        old_job.status = JobStatus.COMPLETED

        # Create recent completed job
        recent_job = TranslationJob(
            job_id="recent_job",
            job_type=JobType.FILE,
            site_id="test",
            target_langs=["fr"],
            input_paths=[Path("test2.md")],
        )

        queue._jobs["old_job"] = old_job
        queue._jobs["recent_job"] = recent_job
        queue.update_job_status("recent_job", JobStatus.COMPLETED)

        # Clear jobs older than 24 hours
        cleared = queue.clear_completed(older_than_hours=24)

        assert cleared == 1
        assert queue.get_job("old_job") is None
        assert queue.get_job("recent_job") is not None
