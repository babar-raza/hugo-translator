"""
Abstract base class for queue backends.

Defines the interface that all queue backends must implement for
job queue operations.
"""

from abc import ABC, abstractmethod
from typing import Optional, Dict, Any, List


class QueueBackend(ABC):
    """
    Abstract base class for queue backends.

    Defines the contract for queue operations including push, pop,
    health checking, and lifecycle management.

    All concrete implementations (MemoryQueueBackend, RedisQueueBackend)
    must implement these methods to ensure consistent behavior across
    different backend types.

    Example:
        class MyQueueBackend(QueueBackend):
            def push(self, queue_name: str, item: Dict[str, Any]) -> None:
                # Implementation...
                pass

            def pop(self, queue_name: str, timeout: float = 0) -> Optional[Dict[str, Any]]:
                # Implementation...
                pass

            def health_check(self) -> bool:
                # Implementation...
                pass

            def close(self) -> None:
                # Implementation...
                pass
    """

    @abstractmethod
    def push(self, queue_name: str, item: Dict[str, Any]) -> None:
        """
        Push item to queue.

        Args:
            queue_name: Name of the queue
            item: Item to push (must be serializable)

        Raises:
            QueueFullError: If queue is at capacity (backend-specific)
            ConnectionError: If backend is unavailable

        Example:
            backend.push("translation_jobs", {
                "job_id": "job_123",
                "priority": 1,
                "data": {...}
            })
        """
        pass

    @abstractmethod
    def pop(self, queue_name: str, timeout: float = 0) -> Optional[Dict[str, Any]]:
        """
        Pop item from queue.

        Args:
            queue_name: Name of the queue
            timeout: Maximum time to wait for item (seconds)
                    0 = non-blocking, None = block forever

        Returns:
            Item from queue or None if queue is empty (non-blocking)
            or timeout reached

        Raises:
            ConnectionError: If backend is unavailable

        Example:
            # Non-blocking pop
            item = backend.pop("translation_jobs", timeout=0)

            # Blocking pop with 5 second timeout
            item = backend.pop("translation_jobs", timeout=5.0)
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """
        Check if backend is healthy and responsive.

        Returns:
            True if backend is healthy and accessible, False otherwise

        Note:
            This should be a lightweight operation (ping/echo) that
            completes quickly. Avoid expensive operations.

        Example:
            if backend.health_check():
                print("Backend is healthy")
            else:
                print("Backend is down, switching to fallback")
        """
        pass

    @abstractmethod
    def close(self) -> None:
        """
        Close backend connection and release resources.

        Should be idempotent (safe to call multiple times).

        Example:
            backend = RedisQueueBackend()
            try:
                backend.push("queue", {"data": "..."})
            finally:
                backend.close()
        """
        pass

    def peek(self, queue_name: str, n: int = 10) -> List[Dict[str, Any]]:
        """
        Look at next N items without removing them (optional).

        Args:
            queue_name: Name of the queue
            n: Number of items to peek at

        Returns:
            List of up to N items from queue (in priority order)

        Note:
            This is an optional method. Backends that don't support
            peeking can return an empty list.

        Example:
            items = backend.peek("translation_jobs", n=5)
            print(f"Next {len(items)} jobs in queue")
        """
        return []

    def size(self, queue_name: str) -> int:
        """
        Get number of items in queue (optional).

        Args:
            queue_name: Name of the queue

        Returns:
            Number of items in queue, or -1 if not supported

        Note:
            This is an optional method. Backends that don't support
            size checking can return -1.

        Example:
            queue_size = backend.size("translation_jobs")
            if queue_size > 100:
                print("Queue is getting large")
        """
        return -1

    def clear(self, queue_name: str) -> None:
        """
        Clear all items from queue (optional).

        Args:
            queue_name: Name of the queue

        Warning:
            This is a destructive operation. Use with caution.

        Note:
            This is an optional method. Backends that don't support
            clearing can raise NotImplementedError.

        Example:
            backend.clear("translation_jobs")
        """
        raise NotImplementedError(f"{self.__class__.__name__} does not support clear()")


class QueueFullError(Exception):
    """Raised when queue is at capacity and cannot accept more items."""
    pass
