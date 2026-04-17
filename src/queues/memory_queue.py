"""
In-memory queue backend implementation.

Provides a simple, non-persistent queue for development and testing.
Uses Python's queue.PriorityQueue for thread-safe operations.
"""

import logging
import queue
import threading
import time
from typing import Any

from .base import QueueBackend, QueueFullError

logger = logging.getLogger(__name__)


class MemoryQueueBackend(QueueBackend):
    """
    In-memory queue backend for development and testing.

    Uses Python's queue.PriorityQueue for thread-safe, priority-based
    queue operations. Not persistent - all data is lost on restart.

    Limitations:
        - Single process only (not distributed)
        - Not persistent (data lost on restart)
        - Limited by available memory

    Args:
        max_queue_size: Maximum number of items in queue (default: 1000)
                       0 = unlimited

    Example:
        backend = MemoryQueueBackend(max_queue_size=100)

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
            print("Backend is healthy")

        # Cleanup
        backend.close()
    """

    def __init__(self, max_queue_size: int = 1000):
        """Initialize memory queue backend."""
        self.max_queue_size = max_queue_size
        self._queues: dict[str, queue.PriorityQueue] = {}
        self._lock = threading.RLock()
        self._closed = False

        logger.info(
            f"MemoryQueueBackend initialized: max_queue_size={max_queue_size}"
        )

    def _get_queue(self, queue_name: str) -> queue.PriorityQueue:
        """Get or create queue by name."""
        with self._lock:
            if queue_name not in self._queues:
                maxsize = self.max_queue_size if self.max_queue_size > 0 else 0
                self._queues[queue_name] = queue.PriorityQueue(maxsize=maxsize)
                logger.debug(f"Created queue: {queue_name} (maxsize={maxsize})")
            return self._queues[queue_name]

    def push(self, queue_name: str, item: dict[str, Any]) -> None:
        """
        Push item to queue.

        Args:
            queue_name: Name of the queue
            item: Item to push (must contain 'priority' key)

        Raises:
            QueueFullError: If queue is at capacity
            ValueError: If item is missing 'priority' key
            RuntimeError: If backend is closed

        Example:
            backend.push("jobs", {
                "job_id": "job_123",
                "priority": 1,
                "data": {...}
            })
        """
        if self._closed:
            raise RuntimeError("Queue backend is closed")

        if "priority" not in item:
            raise ValueError("Item must contain 'priority' key")

        q = self._get_queue(queue_name)

        try:
            # Priority queue uses (priority, item) tuples
            # Lower priority number = higher priority
            priority = item["priority"]
            timestamp = time.time()  # FIFO within same priority

            # Non-blocking put with timeout
            q.put((priority, timestamp, item), block=False)

            logger.debug(
                f"Pushed item to queue '{queue_name}': "
                f"priority={priority}, job_id={item.get('job_id', 'N/A')}"
            )

        except queue.Full:
            raise QueueFullError(
                f"Queue '{queue_name}' is full (max_queue_size={self.max_queue_size})"
            )

    def pop(self, queue_name: str, timeout: float = 0) -> dict[str, Any] | None:
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
            RuntimeError: If backend is closed

        Example:
            # Non-blocking pop
            item = backend.pop("jobs", timeout=0)

            # Blocking pop with 5 second timeout
            item = backend.pop("jobs", timeout=5.0)
        """
        if self._closed:
            raise RuntimeError("Queue backend is closed")

        q = self._get_queue(queue_name)

        try:
            if timeout == 0:
                # Non-blocking
                priority, timestamp, item = q.get(block=False)
            else:
                # Blocking with timeout
                block = True
                timeout_val = timeout if timeout is not None else None
                priority, timestamp, item = q.get(block=block, timeout=timeout_val)

            logger.debug(
                f"Popped item from queue '{queue_name}': "
                f"priority={priority}, job_id={item.get('job_id', 'N/A')}"
            )

            return item

        except queue.Empty:
            return None

    def health_check(self) -> bool:
        """
        Check if backend is healthy.

        Returns:
            True if backend is open and operational, False if closed

        Example:
            if backend.health_check():
                print("Backend is healthy")
        """
        return not self._closed

    def close(self) -> None:
        """
        Close backend and release resources.

        Clears all queues and marks backend as closed.

        Example:
            backend.close()
        """
        with self._lock:
            if not self._closed:
                # Clear all queues
                for queue_name in list(self._queues.keys()):
                    try:
                        while not self._queues[queue_name].empty():
                            self._queues[queue_name].get(block=False)
                    except queue.Empty:
                        pass

                self._queues.clear()
                self._closed = True

                logger.info("MemoryQueueBackend closed")

    def peek(self, queue_name: str, n: int = 10) -> list[dict[str, Any]]:
        """
        Look at next N items without removing them.

        Args:
            queue_name: Name of the queue
            n: Number of items to peek at

        Returns:
            List of up to N items from queue (in priority order)

        Note:
            This is a snapshot view. Items may be dequeued by other
            threads before they can be popped.

        Example:
            items = backend.peek("jobs", n=5)
            print(f"Next {len(items)} jobs in queue")
        """
        if self._closed:
            return []

        q = self._get_queue(queue_name)

        with self._lock:
            # Get all items
            items = []
            temp_items = []

            try:
                # Extract items
                while not q.empty() and len(items) < n:
                    priority, timestamp, item = q.get(block=False)
                    items.append(item)
                    temp_items.append((priority, timestamp, item))

                # Put them back
                for priority, timestamp, item in temp_items:
                    q.put((priority, timestamp, item), block=False)

            except queue.Empty:
                pass
            except queue.Full:
                # Should not happen since we're putting back what we took
                logger.warning(f"Failed to restore items to queue '{queue_name}'")

            return items

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

        q = self._get_queue(queue_name)
        return q.qsize()

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

        q = self._get_queue(queue_name)

        with self._lock:
            cleared_count = 0
            try:
                while not q.empty():
                    q.get(block=False)
                    cleared_count += 1
            except queue.Empty:
                pass

            logger.info(f"Cleared {cleared_count} items from queue '{queue_name}'")
