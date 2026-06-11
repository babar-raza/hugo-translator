"""
Unit tests for JobEngine.

Tests job queue wrapper with both memory and Redis backends (mocked).
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from src.orchestrator.models import JobStats, JobStatus, JobType, TranslationJob
from src.shared_engines.job_engine import JobEngine


class TestJobEngineMemoryBackend(unittest.TestCase):
    """Test JobEngine with memory backend."""

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_memory_initialization(self, mock_job_queue):
        """Test JobEngine initializes with memory backend."""
        mock_queue_instance = Mock()
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")

        self.assertEqual(engine.backend_type, "memory")
        mock_job_queue.assert_called_once_with(backend="memory")
        self.assertEqual(engine.queue, mock_queue_instance)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_enqueue_memory(self, mock_job_queue):
        """Test enqueue() with memory backend."""
        mock_queue_instance = Mock()
        mock_queue_instance.enqueue.return_value = "job_123"
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")

        # Create test job
        job = TranslationJob(
            job_id="job_123",
            job_type=JobType.FILE,
            site_id="products.aspose.com",
            target_langs=["es", "fr"],
            input_paths=[Path("content/example.md")],
        )

        # Enqueue job
        job_id = engine.enqueue(job)

        self.assertEqual(job_id, "job_123")
        mock_queue_instance.enqueue.assert_called_once_with(job)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_dequeue_memory(self, mock_job_queue):
        """Test dequeue() with memory backend."""
        mock_queue_instance = Mock()
        mock_job = Mock(spec=TranslationJob)
        mock_job.job_id = "job_123"
        mock_job.job_type = JobType.FILE
        mock_job.priority = 5
        mock_queue_instance.dequeue.return_value = mock_job
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        job = engine.dequeue()

        self.assertEqual(job, mock_job)
        self.assertEqual(job.job_id, "job_123")
        mock_queue_instance.dequeue.assert_called_once()

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_dequeue_empty_queue(self, mock_job_queue):
        """Test dequeue() returns None when queue is empty."""
        mock_queue_instance = Mock()
        mock_queue_instance.dequeue.return_value = None
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        job = engine.dequeue()

        self.assertIsNone(job)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_get_status_memory(self, mock_job_queue):
        """Test get_status() retrieves job by ID."""
        mock_queue_instance = Mock()
        mock_job = Mock(spec=TranslationJob)
        mock_job.job_id = "job_123"
        mock_job.status = JobStatus.RUNNING
        mock_queue_instance.get_job.return_value = mock_job
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        job = engine.get_status("job_123")

        self.assertEqual(job, mock_job)
        self.assertEqual(job.status, JobStatus.RUNNING)
        mock_queue_instance.get_job.assert_called_once_with("job_123")

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_get_status_not_found(self, mock_job_queue):
        """Test get_status() returns None for non-existent job."""
        mock_queue_instance = Mock()
        mock_queue_instance.get_job.return_value = None
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        job = engine.get_status("nonexistent_job")

        self.assertIsNone(job)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_list_pending_memory(self, mock_job_queue):
        """Test list_pending() retrieves pending jobs."""
        mock_queue_instance = Mock()
        mock_jobs = [
            Mock(spec=TranslationJob, job_id="job_1", priority=1),
            Mock(spec=TranslationJob, job_id="job_2", priority=2),
        ]
        mock_queue_instance.peek.return_value = mock_jobs
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        pending = engine.list_pending(limit=10)

        self.assertEqual(len(pending), 2)
        self.assertEqual(pending[0].job_id, "job_1")
        mock_queue_instance.peek.assert_called_once_with(n=10)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_update_status_memory(self, mock_job_queue):
        """Test update_status() updates job status."""
        mock_queue_instance = Mock()
        mock_queue_instance.update_job_status.return_value = True
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        success = engine.update_status(
            job_id="job_123", status=JobStatus.COMPLETED, result_summary={"files_translated": 5}
        )

        self.assertTrue(success)
        mock_queue_instance.update_job_status.assert_called_once_with(
            job_id="job_123",
            status=JobStatus.COMPLETED,
            error_message=None,
            result_summary={"files_translated": 5},
        )

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_update_status_with_error(self, mock_job_queue):
        """Test update_status() with error message."""
        mock_queue_instance = Mock()
        mock_queue_instance.update_job_status.return_value = True
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        success = engine.update_status(
            job_id="job_456",
            status=JobStatus.FAILED,
            error_message="Translation service unavailable",
        )

        self.assertTrue(success)
        mock_queue_instance.update_job_status.assert_called_once_with(
            job_id="job_456",
            status=JobStatus.FAILED,
            error_message="Translation service unavailable",
            result_summary=None,
        )

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_get_stats_memory(self, mock_job_queue):
        """Test get_stats() returns queue statistics."""
        mock_queue_instance = Mock()
        mock_stats = JobStats(total_enqueued=10, pending=3, running=2, completed=4, failed=1)
        mock_queue_instance.get_stats.return_value = mock_stats
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        stats = engine.get_stats()

        self.assertEqual(stats.pending, 3)
        self.assertEqual(stats.running, 2)
        self.assertEqual(stats.completed, 4)
        self.assertEqual(stats.failed, 1)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_list_jobs_memory(self, mock_job_queue):
        """Test list_jobs() with status filter."""
        mock_queue_instance = Mock()
        mock_jobs = [
            Mock(spec=TranslationJob, job_id="job_1", status=JobStatus.COMPLETED),
            Mock(spec=TranslationJob, job_id="job_2", status=JobStatus.COMPLETED),
        ]
        mock_queue_instance.list_jobs.return_value = mock_jobs
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        jobs = engine.list_jobs(status=JobStatus.COMPLETED, limit=50)

        self.assertEqual(len(jobs), 2)
        mock_queue_instance.list_jobs.assert_called_once_with(status=JobStatus.COMPLETED, limit=50)

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_is_empty_memory_true(self, mock_job_queue):
        """Test is_empty() returns True when no pending jobs."""
        mock_queue_instance = Mock()
        mock_queue_instance.peek.return_value = []
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        self.assertTrue(engine.is_empty())

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_is_empty_memory_false(self, mock_job_queue):
        """Test is_empty() returns False when jobs pending."""
        mock_queue_instance = Mock()
        mock_queue_instance.peek.return_value = [Mock(spec=TranslationJob)]
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        self.assertFalse(engine.is_empty())

    @patch("src.shared_engines.job_engine.JobQueue")
    def test_shutdown_memory(self, mock_job_queue):
        """Test shutdown() with memory backend (no-op)."""
        mock_queue_instance = Mock()
        mock_job_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="memory")
        engine.shutdown()

        # Memory backend shutdown is a no-op (no close method)
        # Just verify it doesn't crash


class TestJobEngineRedisBackend(unittest.TestCase):
    """Test JobEngine with Redis backend."""

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_redis_initialization_default_config(self, mock_redis_queue):
        """Test JobEngine initializes with Redis backend (default config)."""
        mock_queue_instance = Mock()
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")

        self.assertEqual(engine.backend_type, "redis")
        mock_redis_queue.assert_called_once_with(host="localhost", port=6379, db=0, password=None)

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_redis_initialization_custom_config(self, mock_redis_queue):
        """Test JobEngine initializes with custom Redis config."""
        mock_queue_instance = Mock()
        mock_redis_queue.return_value = mock_queue_instance

        redis_config = {"host": "redis.example.com", "port": 6380, "db": 1, "password": "secret123"}

        engine = JobEngine(backend="redis", redis_config=redis_config)

        self.assertEqual(engine.backend_type, "redis")
        mock_redis_queue.assert_called_once_with(
            host="redis.example.com", port=6380, db=1, password="secret123"
        )

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_enqueue_redis(self, mock_redis_queue):
        """Test enqueue() with Redis backend."""
        mock_queue_instance = Mock()
        mock_queue_instance.enqueue.return_value = "job_redis_123"
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")

        job = TranslationJob(
            job_id="job_redis_123",
            job_type=JobType.DIRECTORY,
            site_id="docs.aspose.net",
            target_langs=["de"],
            input_paths=[Path("content/")],
        )

        job_id = engine.enqueue(job)

        self.assertEqual(job_id, "job_redis_123")
        mock_queue_instance.enqueue.assert_called_once_with(job)

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_dequeue_redis(self, mock_redis_queue):
        """Test dequeue() with Redis backend."""
        mock_queue_instance = Mock()
        mock_job = Mock(spec=TranslationJob)
        mock_job.job_id = "job_redis_456"
        mock_job.job_type = JobType.DIRECTORY
        mock_job.priority = 3
        mock_queue_instance.dequeue.return_value = mock_job
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")
        job = engine.dequeue()

        self.assertEqual(job, mock_job)
        self.assertEqual(job.job_id, "job_redis_456")

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_list_jobs_redis_not_supported(self, mock_redis_queue):
        """Test list_jobs() returns empty list for Redis backend."""
        mock_queue_instance = Mock()
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")
        jobs = engine.list_jobs(status=JobStatus.COMPLETED)

        # Redis backend doesn't support list_jobs, returns empty list
        self.assertEqual(len(jobs), 0)

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_is_empty_redis_true(self, mock_redis_queue):
        """Test is_empty() with Redis backend (empty)."""
        mock_queue_instance = Mock()
        mock_queue_instance.is_empty.return_value = True
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")
        self.assertTrue(engine.is_empty())

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_is_empty_redis_false(self, mock_redis_queue):
        """Test is_empty() with Redis backend (not empty)."""
        mock_queue_instance = Mock()
        mock_queue_instance.is_empty.return_value = False
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")
        self.assertFalse(engine.is_empty())

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_shutdown_redis(self, mock_redis_queue):
        """Test shutdown() closes Redis connection."""
        mock_queue_instance = Mock()
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")
        engine.shutdown()

        mock_queue_instance.close.assert_called_once()

    @patch("src.shared_engines.job_engine.RedisJobQueue")
    def test_get_backend_type(self, mock_redis_queue):
        """Test get_backend_type() returns correct backend."""
        mock_queue_instance = Mock()
        mock_redis_queue.return_value = mock_queue_instance

        engine = JobEngine(backend="redis")
        self.assertEqual(engine.get_backend_type(), "redis")


class TestJobEngineInvalidBackend(unittest.TestCase):
    """Test JobEngine with invalid backend."""

    def test_invalid_backend_raises_error(self):
        """Test initialization with invalid backend raises ValueError."""
        with self.assertRaises(ValueError) as ctx:
            JobEngine(backend="invalid_backend")

        self.assertIn("Unsupported backend", str(ctx.exception))
        self.assertIn("invalid_backend", str(ctx.exception))


if __name__ == "__main__":
    unittest.main()
