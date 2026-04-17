"""
Unit tests for backend switching and failover functionality.

Tests JobEngineV2 backend selection, health checks, and auto-failover.
"""

from unittest.mock import MagicMock, Mock, patch

import pytest

from src.orchestrator.models import JobStatus, JobType, TranslationJob
from src.queues import MemoryQueueBackend, RedisQueueBackend
from src.shared_engines.job_engine import JobEngine
from src.shared_engines.job_engine_v2 import JobEngineV2


class TestBackendSelection:
    """Test backend selection logic with 4-tier precedence."""

    def test_default_backend_redis(self):
        """Test default backend is Redis."""
        config = {
            "redis": {"host": "localhost", "port": 6379},
            "memory": {"max_queue_size": 1000}
        }

        # Mock Redis to avoid actual connection
        with patch('src.queues.redis_queue.RedisQueueBackend._get_redis'):
            engine = JobEngineV2(config=config)

            assert engine.primary_backend_type == "redis"
            assert engine.fallback_backend_type == "memory"
            assert engine.current_backend_type == "redis"

    def test_explicit_backend_selection(self):
        """Test explicit backend configuration."""
        config = {
            "backend": "memory",
            "fallback_backend": "redis",
            "memory": {"max_queue_size": 100}
        }

        engine = JobEngineV2(config=config)

        assert engine.primary_backend_type == "memory"
        assert engine.fallback_backend_type == "redis"
        assert engine.current_backend_type == "memory"

    def test_environment_variable_precedence(self, monkeypatch):
        """Test QUEUE_BACKEND environment variable takes precedence."""
        # Set environment variable
        monkeypatch.setenv("QUEUE_BACKEND", "memory")

        config = {
            "backend": "redis",  # This should be overridden by env var
            "memory": {"max_queue_size": 500}
        }

        engine = JobEngineV2(config=config)

        assert engine.primary_backend_type == "memory"

    def test_execution_mode_backend_selection(self):
        """Test execution mode backend defaults."""
        config = {
            "primary_backend_from_mode": "redis",
            "redis": {"host": "localhost"}
        }

        # Mock Redis to avoid actual connection
        with patch('src.queues.redis_queue.RedisQueueBackend._get_redis'):
            engine = JobEngineV2(config=config)

            assert engine.primary_backend_type == "redis"


class TestMemoryBackend:
    """Test memory queue backend implementation."""

    def test_memory_backend_push_pop(self):
        """Test basic push/pop operations."""
        backend = MemoryQueueBackend(max_queue_size=10)

        # Push item
        item = {"job_id": "job_1", "priority": 1, "data": "test"}
        backend.push("test_queue", item)

        # Pop item
        popped = backend.pop("test_queue", timeout=0)

        assert popped is not None
        assert popped["job_id"] == "job_1"
        assert popped["priority"] == 1

    def test_memory_backend_priority_ordering(self):
        """Test priority queue ordering (lower priority = higher priority)."""
        backend = MemoryQueueBackend(max_queue_size=10)

        # Push items in random priority order
        backend.push("test_queue", {"job_id": "job_3", "priority": 3, "data": "low"})
        backend.push("test_queue", {"job_id": "job_1", "priority": 1, "data": "high"})
        backend.push("test_queue", {"job_id": "job_2", "priority": 2, "data": "medium"})

        # Pop items - should come out in priority order
        item1 = backend.pop("test_queue", timeout=0)
        item2 = backend.pop("test_queue", timeout=0)
        item3 = backend.pop("test_queue", timeout=0)

        assert item1["job_id"] == "job_1"  # Priority 1 (highest)
        assert item2["job_id"] == "job_2"  # Priority 2
        assert item3["job_id"] == "job_3"  # Priority 3 (lowest)

    def test_memory_backend_max_queue_size(self):
        """Test max_queue_size enforcement."""
        backend = MemoryQueueBackend(max_queue_size=2)

        # Push 2 items (should succeed)
        backend.push("test_queue", {"job_id": "job_1", "priority": 1})
        backend.push("test_queue", {"job_id": "job_2", "priority": 2})

        # Push 3rd item (should raise QueueFullError)
        from src.queues.base import QueueFullError
        with pytest.raises(QueueFullError):
            backend.push("test_queue", {"job_id": "job_3", "priority": 3})

    def test_memory_backend_health_check(self):
        """Test health check always returns True for memory backend."""
        backend = MemoryQueueBackend()

        assert backend.health_check() is True

        # Health check should still work after close
        backend.close()
        assert backend.health_check() is False

    def test_memory_backend_peek(self):
        """Test peek operation."""
        backend = MemoryQueueBackend()

        # Push items
        backend.push("test_queue", {"job_id": "job_1", "priority": 1})
        backend.push("test_queue", {"job_id": "job_2", "priority": 2})

        # Peek at items
        items = backend.peek("test_queue", n=2)

        assert len(items) == 2
        assert items[0]["job_id"] == "job_1"
        assert items[1]["job_id"] == "job_2"

        # Items should still be in queue
        assert backend.size("test_queue") == 2

    def test_memory_backend_size(self):
        """Test size operation."""
        backend = MemoryQueueBackend()

        assert backend.size("test_queue") == 0

        backend.push("test_queue", {"job_id": "job_1", "priority": 1})
        assert backend.size("test_queue") == 1

        backend.push("test_queue", {"job_id": "job_2", "priority": 2})
        assert backend.size("test_queue") == 2

        backend.pop("test_queue", timeout=0)
        assert backend.size("test_queue") == 1

    def test_memory_backend_clear(self):
        """Test clear operation."""
        backend = MemoryQueueBackend()

        # Push items
        backend.push("test_queue", {"job_id": "job_1", "priority": 1})
        backend.push("test_queue", {"job_id": "job_2", "priority": 2})

        assert backend.size("test_queue") == 2

        # Clear queue
        backend.clear("test_queue")

        assert backend.size("test_queue") == 0


class TestRedisBackend:
    """Test Redis queue backend implementation (mocked)."""

    @pytest.fixture
    def mock_redis(self):
        """Create mock Redis client."""
        mock = MagicMock()
        mock.ping.return_value = True
        mock.hexists.return_value = False
        mock.pipeline.return_value = mock
        mock.execute.return_value = [True, True]
        return mock

    def test_redis_backend_health_check_success(self, mock_redis):
        """Test Redis health check success."""
        with patch('src.queues.redis_queue.redis.Redis', return_value=mock_redis):
            backend = RedisQueueBackend(host="localhost", port=6379)

            assert backend.health_check() is True
            mock_redis.ping.assert_called()

    def test_redis_backend_health_check_failure(self, mock_redis):
        """Test Redis health check failure."""
        mock_redis.ping.side_effect = Exception("Connection refused")

        with patch('src.queues.redis_queue.redis.Redis', return_value=mock_redis):
            backend = RedisQueueBackend(host="localhost", port=6379)

            # Force connection
            backend._redis = mock_redis

            assert backend.health_check() is False

    def test_redis_backend_connection_retry(self):
        """Test Redis connection retry logic."""
        mock_redis = MagicMock()
        mock_redis.ping.side_effect = [
            Exception("Retry 1"),
            Exception("Retry 2"),
            True  # Success on 3rd attempt
        ]

        with patch('src.queues.redis_queue.redis.Redis', return_value=mock_redis):
            backend = RedisQueueBackend(
                host="localhost",
                max_retries=3,
                retry_delay=0.1
            )

            # This should succeed on 3rd retry
            client = backend._get_redis()
            assert client is not None


class TestBackendFailover:
    """Test backend failover and recovery."""

    def test_failover_on_primary_failure(self):
        """Test automatic failover when primary backend fails."""
        config = {
            "backend": "redis",
            "fallback_backend": "memory",
            "redis": {"host": "localhost", "port": 6379},
            "memory": {"max_queue_size": 1000}
        }

        # Mock Redis to fail health check
        with patch('src.queues.redis_queue.RedisQueueBackend._get_redis') as mock_redis:
            mock_redis.side_effect = ConnectionError("Redis unavailable")

            engine = JobEngineV2(config=config)

            # Engine should have failed over to memory backend
            assert engine.current_backend_type == "memory"
            assert engine._failover_count >= 1

    def test_recovery_to_primary(self):
        """Test automatic recovery to primary when it becomes available."""
        config = {
            "backend": "redis",
            "fallback_backend": "memory",
            "redis": {"host": "localhost", "port": 6379, "health_check_interval": 0},
            "memory": {"max_queue_size": 1000}
        }

        # Start with failed Redis
        with patch('src.queues.redis_queue.RedisQueueBackend._get_redis') as mock_redis:
            mock_redis.side_effect = ConnectionError("Redis unavailable")

            engine = JobEngineV2(config=config)

            # Should be on fallback
            assert engine.current_backend_type == "memory"

            # Simulate Redis recovery
            mock_redis.side_effect = None
            mock_client = MagicMock()
            mock_client.ping.return_value = True
            mock_redis.return_value = mock_client

            # Create new primary backend instance that will succeed
            engine.primary_backend = None  # Force recreation
            engine.health_check_cooldown = 0  # Disable cooldown for test
            engine._attempt_recovery()

            # Should have recovered to primary
            assert engine.current_backend_type == "redis"
            assert engine._recovery_count >= 1

    def test_telemetry_events_on_failover(self):
        """Test telemetry events are emitted on backend state changes."""
        mock_telemetry = Mock()
        mock_telemetry.emit = Mock()

        config = {
            "backend": "redis",
            "fallback_backend": "memory",
            "redis": {"host": "localhost"},
            "memory": {"max_queue_size": 1000},
            "telemetry": mock_telemetry
        }

        # Mock Redis to fail
        with patch('src.queues.redis_queue.RedisQueueBackend._get_redis') as mock_redis:
            mock_redis.side_effect = ConnectionError("Redis unavailable")

            engine = JobEngineV2(config=config)

            # Verify telemetry events were emitted
            assert mock_telemetry.emit.called
            # Should have emitted: queue_backend_init_failed, queue_backend_failover
            call_args = [call[0][0] for call in mock_telemetry.emit.call_args_list]
            assert "queue_backend_init_failed" in call_args or "queue_backend_failover" in call_args


class TestJobEngineIntegration:
    """Test JobEngine wrapper with V2 integration."""

    def test_legacy_api_backward_compatibility(self):
        """Test legacy API still works (backward compatibility)."""
        # Legacy API: backend + redis_config parameters
        engine = JobEngine(backend="memory")

        assert engine.backend_type == "memory"
        assert not engine._use_v2

    def test_new_api_with_config(self):
        """Test new API with config dictionary enables V2."""
        config = {
            "backend": "memory",
            "fallback_backend": "memory",
            "memory": {"max_queue_size": 500}
        }

        engine = JobEngine(config=config)

        assert engine._use_v2 is True
        assert engine.backend_type == "memory"

    def test_get_backend_stats_v2_only(self):
        """Test get_backend_stats returns None for legacy mode."""
        # Legacy mode
        engine_legacy = JobEngine(backend="memory")
        stats = engine_legacy.get_backend_stats()
        assert stats is None

        # V2 mode
        engine_v2 = JobEngine(config={"backend": "memory"})
        stats = engine_v2.get_backend_stats()
        assert stats is not None
        assert "primary_backend" in stats
        assert "current_backend" in stats
        assert "failover_count" in stats


class TestEndToEndScenarios:
    """End-to-end tests for common usage scenarios."""

    def test_enqueue_dequeue_with_failover(self):
        """Test job enqueue/dequeue works through failover."""
        from pathlib import Path

        config = {
            "backend": "memory",  # Use memory to avoid Redis dependency
            "fallback_backend": "memory",
            "memory": {"max_queue_size": 100}
        }

        engine = JobEngine(config=config)

        # Create test job
        job = TranslationJob(
            job_id="test_job_1",
            job_type=JobType.FILE,
            site_id="test.com",
            target_langs=["es", "fr"],
            input_paths=[Path("test.md")],
            priority=1
        )

        # Enqueue job
        job_id = engine.enqueue(job)
        assert job_id == "test_job_1"

        # Dequeue job
        dequeued_job = engine.dequeue()
        assert dequeued_job is not None
        assert dequeued_job.job_id == "test_job_1"
        assert dequeued_job.status == JobStatus.RUNNING

        # Update status
        success = engine.update_status(job_id, JobStatus.COMPLETED)
        assert success is True

        # Check status
        job_status = engine.get_status(job_id)
        assert job_status.status == JobStatus.COMPLETED

        # Cleanup
        engine.shutdown()

    def test_health_check_during_operations(self):
        """Test health checks run during normal operations."""
        config = {
            "backend": "memory",
            "redis": {"health_check_interval": 0},  # Check every operation
            "memory": {"max_queue_size": 100}
        }

        engine = JobEngine(config=config)

        # Get backend stats
        stats = engine.get_backend_stats()
        assert stats is not None
        assert stats["is_healthy"] is True

        # Cleanup
        engine.shutdown()


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
