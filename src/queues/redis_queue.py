"""
Redis queue backend implementation.

Provides persistent, distributed queue using Redis as the backend.
Uses Redis sorted sets for priority queue operations.
"""

import json
import logging
import time
from typing import Any

from .base import QueueBackend

logger = logging.getLogger(__name__)


class RedisQueueBackend(QueueBackend):
    """
    Redis-backed queue for distributed systems.

    Uses Redis sorted sets for priority queue and hashes for job data.
    Provides persistence and distributed access across multiple workers.

    Args:
        host: Redis host (default: "localhost")
        port: Redis port (default: 6379)
        db: Redis database number (default: 0)
        password: Optional Redis password
        key_prefix: Prefix for all Redis keys (default: "hugo_translation")
        max_retries: Maximum connection retry attempts (default: 3)
        retry_delay: Delay between retries in seconds (default: 1.0)

    Example:
        backend = RedisQueueBackend(
            host="localhost",
            port=6379,
            max_retries=3
        )

        # Push item
        backend.push("jobs", {
            "job_id": "job_123",
            "priority": 1,
            "data": {...}
        })

        # Pop item
        item = backend.pop("jobs", timeout=5.0)

        # Health check
        if backend.health_check():
            print("Redis is healthy")

        # Cleanup
        backend.close()
    """

    def __init__(
        self,
        host: str = "localhost",
        port: int = 6379,
        db: int = 0,
        password: str | None = None,
        key_prefix: str = "hugo_translation",
        max_retries: int = 3,
        retry_delay: float = 1.0
    ):
        """Initialize Redis queue backend."""
        self.host = host
        self.port = port
        self.db = db
        self.password = password
        self.key_prefix = key_prefix
        self.max_retries = max_retries
        self.retry_delay = retry_delay

        # Redis client (lazy initialization)
        self._redis: Any | None = None
        self._closed = False

        logger.info(
            f"RedisQueueBackend initialized: host={host}:{port}, "
            f"db={db}, max_retries={max_retries}"
        )

    def _get_redis(self) -> Any:
        """Get or create Redis connection with retry logic."""
        if self._closed:
            raise RuntimeError("Queue backend is closed")

        if self._redis is not None:
            return self._redis

        # Try to connect with retries
        last_error = None
        for attempt in range(self.max_retries):
            try:
                import redis

                self._redis = redis.Redis(
                    host=self.host,
                    port=self.port,
                    db=self.db,
                    password=self.password,
                    decode_responses=True,
                    socket_connect_timeout=5,
                    socket_timeout=5
                )

                # Test connection
                self._redis.ping()

                logger.info(
                    f"Connected to Redis at {self.host}:{self.port} "
                    f"(attempt {attempt + 1}/{self.max_retries})"
                )

                return self._redis

            except ImportError:
                raise RuntimeError(
                    "redis-py not installed. Install with: pip install redis"
                )
            except Exception as e:
                last_error = e
                logger.warning(
                    f"Redis connection attempt {attempt + 1}/{self.max_retries} failed: {e}"
                )

                if attempt < self.max_retries - 1:
                    time.sleep(self.retry_delay * (attempt + 1))  # Exponential backoff

        # All retries failed
        raise ConnectionError(
            f"Failed to connect to Redis after {self.max_retries} attempts: {last_error}"
        )

    def _get_queue_key(self, queue_name: str) -> str:
        """Get Redis key for queue sorted set."""
        return f"{self.key_prefix}:{queue_name}:queue"

    def _get_data_key(self, queue_name: str) -> str:
        """Get Redis key for job data hash."""
        return f"{self.key_prefix}:{queue_name}:data"

    def push(self, queue_name: str, item: dict[str, Any]) -> None:
        """
        Push item to Redis queue.

        Args:
            queue_name: Name of the queue
            item: Item to push (must contain 'job_id' and 'priority' keys)

        Raises:
            ValueError: If item is missing required keys
            ConnectionError: If Redis is unavailable

        Example:
            backend.push("jobs", {
                "job_id": "job_123",
                "priority": 1,
                "data": {...}
            })
        """
        if "job_id" not in item:
            raise ValueError("Item must contain 'job_id' key")
        if "priority" not in item:
            raise ValueError("Item must contain 'priority' key")

        redis = self._get_redis()

        job_id = item["job_id"]
        priority = item["priority"]

        # Check for duplicate
        queue_key = self._get_queue_key(queue_name)
        data_key = self._get_data_key(queue_name)

        if redis.hexists(data_key, job_id):
            raise ValueError(f"Job {job_id} already exists in queue '{queue_name}'")

        # Serialize item
        item_json = json.dumps(item)

        # Score format: priority * 1e10 + timestamp (for FIFO within same priority)
        score = priority * 1e10 + time.time()

        # Use pipeline for atomic operation
        pipe = redis.pipeline()
        pipe.zadd(queue_key, {job_id: score})
        pipe.hset(data_key, job_id, item_json)
        pipe.execute()

        logger.debug(
            f"Pushed item to Redis queue '{queue_name}': "
            f"job_id={job_id}, priority={priority}"
        )

    def pop(self, queue_name: str, timeout: float = 0) -> dict[str, Any] | None:
        """
        Pop item from Redis queue.

        Args:
            queue_name: Name of the queue
            timeout: Maximum time to wait for item (seconds)
                    0 = non-blocking, >0 = blocking with timeout

        Returns:
            Item from queue or None if queue is empty (non-blocking)
            or timeout reached

        Raises:
            ConnectionError: If Redis is unavailable

        Note:
            Redis blocking pop is not supported in this implementation.
            Use polling with small timeout for blocking behavior.

        Example:
            # Non-blocking pop
            item = backend.pop("jobs", timeout=0)

            # Polling with timeout
            start = time.time()
            while time.time() - start < 5.0:
                item = backend.pop("jobs", timeout=0)
                if item:
                    break
                time.sleep(0.1)
        """
        redis = self._get_redis()

        queue_key = self._get_queue_key(queue_name)
        data_key = self._get_data_key(queue_name)

        # Get job with lowest score (highest priority)
        results = redis.zrange(queue_key, 0, 0)

        if not results:
            return None

        job_id = results[0]

        # Get job data
        item_json = redis.hget(data_key, job_id)
        if not item_json:
            # Job exists in queue but not in storage - remove from queue
            redis.zrem(queue_key, job_id)
            logger.warning(
                f"Job {job_id} found in queue but not in storage, removed"
            )
            return None

        # Deserialize item
        item = json.loads(item_json)

        # Atomic remove from queue and data
        pipe = redis.pipeline()
        pipe.zrem(queue_key, job_id)
        pipe.hdel(data_key, job_id)
        pipe.execute()

        logger.debug(
            f"Popped item from Redis queue '{queue_name}': "
            f"job_id={job_id}, priority={item.get('priority', 'N/A')}"
        )

        return item

    def health_check(self) -> bool:
        """
        Check if Redis is healthy and responsive.

        Returns:
            True if Redis PING succeeds, False otherwise

        Example:
            if backend.health_check():
                print("Redis is healthy")
            else:
                print("Redis is down")
        """
        if self._closed:
            return False

        try:
            redis = self._get_redis()
            response = redis.ping()
            return response is True
        except Exception as e:
            logger.warning(f"Redis health check failed: {e}")
            return False

    def close(self) -> None:
        """
        Close Redis connection and release resources.

        Example:
            backend.close()
        """
        if not self._closed:
            if self._redis:
                try:
                    self._redis.close()
                    logger.info("Closed Redis connection")
                except Exception as e:
                    logger.warning(f"Error closing Redis connection: {e}")
                finally:
                    self._redis = None

            self._closed = True

    def peek(self, queue_name: str, n: int = 10) -> list[dict[str, Any]]:
        """
        Look at next N items without removing them.

        Args:
            queue_name: Name of the queue
            n: Number of items to peek at

        Returns:
            List of up to N items from queue (in priority order)

        Example:
            items = backend.peek("jobs", n=5)
            print(f"Next {len(items)} jobs in queue")
        """
        if self._closed:
            return []

        try:
            redis = self._get_redis()
            queue_key = self._get_queue_key(queue_name)
            data_key = self._get_data_key(queue_name)

            # Get job IDs with lowest scores
            job_ids = redis.zrange(queue_key, 0, n - 1)

            items = []
            for job_id in job_ids:
                item_json = redis.hget(data_key, job_id)
                if item_json:
                    items.append(json.loads(item_json))

            return items

        except Exception as e:
            logger.warning(f"Failed to peek queue '{queue_name}': {e}")
            return []

    def size(self, queue_name: str) -> int:
        """
        Get number of items in queue.

        Args:
            queue_name: Name of the queue

        Returns:
            Number of items in queue

        Example:
            queue_size = backend.size("jobs")
            print(f"Queue has {queue_size} items")
        """
        if self._closed:
            return 0

        try:
            redis = self._get_redis()
            queue_key = self._get_queue_key(queue_name)
            return redis.zcard(queue_key)
        except Exception as e:
            logger.warning(f"Failed to get queue size for '{queue_name}': {e}")
            return 0

    def clear(self, queue_name: str) -> None:
        """
        Clear all items from queue.

        Args:
            queue_name: Name of the queue

        Warning:
            This is a destructive operation. Use with caution.

        Example:
            backend.clear("jobs")
        """
        if self._closed:
            return

        try:
            redis = self._get_redis()
            queue_key = self._get_queue_key(queue_name)
            data_key = self._get_data_key(queue_name)

            # Get count before clearing
            count = redis.zcard(queue_key)

            # Delete keys
            pipe = redis.pipeline()
            pipe.delete(queue_key)
            pipe.delete(data_key)
            pipe.execute()

            logger.info(f"Cleared {count} items from Redis queue '{queue_name}'")

        except Exception as e:
            logger.warning(f"Failed to clear queue '{queue_name}': {e}")
