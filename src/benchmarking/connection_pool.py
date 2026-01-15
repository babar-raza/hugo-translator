"""Database connection pooling for concurrent access.

Implements connection pooling to reduce connection overhead and improve
performance for concurrent database operations.

Features:
- Connection reuse with pooling
- Health checks and connection validation
- Thread-safe connection checkout/checkin
- Automatic connection lifecycle management
- Configurable pool size and timeout

Example:
    pool = ConnectionPool("data/benchmarks.db", pool_size=5)

    # Get connection from pool
    with pool.get_connection() as conn:
        cursor = conn.execute("SELECT * FROM benchmark_runs")
        results = cursor.fetchall()

    # Connection automatically returned to pool
"""

import logging
import sqlite3
import threading
import time
from contextlib import contextmanager
from pathlib import Path
from queue import Empty, Queue
from typing import Generator, Optional

logger = logging.getLogger(__name__)


class PooledConnection:
    """Wrapper for pooled database connection.

    Tracks connection health and usage statistics.
    """

    def __init__(self, conn: sqlite3.Connection, pool_id: int):
        """Initialize pooled connection.

        Args:
            conn: SQLite connection
            pool_id: Connection pool identifier
        """
        self.conn = conn
        self.pool_id = pool_id
        self.created_at = time.time()
        self.last_used = time.time()
        self.use_count = 0
        self.is_healthy = True

    def mark_used(self) -> None:
        """Mark connection as recently used."""
        self.last_used = time.time()
        self.use_count += 1

    def check_health(self) -> bool:
        """Verify connection is healthy.

        Returns:
            True if connection is functional
        """
        try:
            cursor = self.conn.execute("SELECT 1")
            cursor.fetchone()
            self.is_healthy = True
            return True
        except Exception as e:
            logger.warning(f"Connection {self.pool_id} health check failed: {e}")
            self.is_healthy = False
            return False

    def close(self) -> None:
        """Close the database connection."""
        try:
            self.conn.close()
            logger.debug(f"Connection {self.pool_id} closed")
        except Exception as e:
            logger.error(f"Error closing connection {self.pool_id}: {e}")


class ConnectionPool:
    """Connection pool for SQLite database access.

    Manages a pool of database connections for efficient reuse across
    multiple threads/operations. Reduces connection overhead and improves
    concurrent access performance.

    Example:
        pool = ConnectionPool("data/benchmarks.db", pool_size=5)

        # Use context manager for automatic checkin
        with pool.get_connection() as conn:
            cursor = conn.execute("SELECT * FROM benchmark_runs LIMIT 10")
            results = cursor.fetchall()

        # Connection automatically returned to pool

        # Get pool statistics
        stats = pool.get_stats()
        print(f"Active: {stats['active']}, Available: {stats['available']}")
    """

    def __init__(
        self,
        db_path: Path | str,
        pool_size: int = 5,
        timeout: float = 30.0,
        max_connection_age: float = 3600.0
    ):
        """Initialize connection pool.

        Args:
            db_path: Path to SQLite database
            pool_size: Maximum number of connections in pool
            timeout: Timeout in seconds for getting connection from pool
            max_connection_age: Maximum age of connection before recreation (seconds)
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path
        self.pool_size = pool_size
        self.timeout = timeout
        self.max_connection_age = max_connection_age

        # Connection pool (FIFO queue)
        self._pool: Queue[PooledConnection] = Queue(maxsize=pool_size)
        self._active_connections: int = 0
        self._lock = threading.Lock()

        # Statistics
        self._total_created = 0
        self._total_checkouts = 0
        self._total_checkins = 0
        self._total_timeouts = 0
        self._total_health_failures = 0

        # Pre-populate pool
        self._initialize_pool()

        logger.info(
            f"ConnectionPool initialized: db={db_path}, "
            f"pool_size={pool_size}, timeout={timeout}s"
        )

    def _initialize_pool(self) -> None:
        """Pre-populate the connection pool."""
        for i in range(self.pool_size):
            try:
                conn = self._create_connection(i)
                self._pool.put(conn, block=False)
            except Exception as e:
                logger.error(f"Failed to create initial connection {i}: {e}")
                raise

    def _create_connection(self, pool_id: int) -> PooledConnection:
        """Create a new pooled connection.

        Args:
            pool_id: Connection identifier

        Returns:
            New PooledConnection instance
        """
        conn = sqlite3.connect(
            str(self.db_path),
            check_same_thread=False,
            timeout=self.timeout
        )
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.row_factory = sqlite3.Row

        pooled = PooledConnection(conn, pool_id)
        self._total_created += 1

        logger.debug(f"Created new connection {pool_id}")
        return pooled

    def _validate_connection(self, pooled_conn: PooledConnection) -> bool:
        """Validate connection is healthy and not too old.

        Args:
            pooled_conn: Pooled connection to validate

        Returns:
            True if connection is valid and healthy
        """
        # Check age
        age = time.time() - pooled_conn.created_at
        if age > self.max_connection_age:
            logger.debug(
                f"Connection {pooled_conn.pool_id} exceeded max age "
                f"({age:.1f}s > {self.max_connection_age}s)"
            )
            return False

        # Check health
        if not pooled_conn.check_health():
            self._total_health_failures += 1
            return False

        return True

    @contextmanager
    def get_connection(self) -> Generator[sqlite3.Connection, None, None]:
        """Get a connection from the pool (context manager).

        Yields:
            SQLite connection from pool

        Raises:
            TimeoutError: If no connection available within timeout

        Example:
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT * FROM benchmark_runs")
                results = cursor.fetchall()
        """
        pooled_conn = self._checkout()
        try:
            yield pooled_conn.conn
        finally:
            self._checkin(pooled_conn)

    def _checkout(self) -> PooledConnection:
        """Check out a connection from the pool.

        Returns:
            Pooled connection

        Raises:
            TimeoutError: If no connection available within timeout
        """
        self._total_checkouts += 1

        try:
            # Try to get connection from pool
            pooled_conn = self._pool.get(timeout=self.timeout)

            # Validate connection
            if not self._validate_connection(pooled_conn):
                # Connection is invalid, close it and create new one
                logger.debug(f"Replacing invalid connection {pooled_conn.pool_id}")
                pooled_conn.close()
                pooled_conn = self._create_connection(pooled_conn.pool_id)

            # Mark as used and track active connections
            pooled_conn.mark_used()
            with self._lock:
                self._active_connections += 1

            logger.debug(f"Checked out connection {pooled_conn.pool_id}")
            return pooled_conn

        except Empty:
            self._total_timeouts += 1
            logger.error(f"Connection pool timeout after {self.timeout}s")
            raise TimeoutError(
                f"Could not get connection from pool within {self.timeout}s. "
                f"Pool size: {self.pool_size}, Active: {self._active_connections}"
            )

    def _checkin(self, pooled_conn: PooledConnection) -> None:
        """Return a connection to the pool.

        Args:
            pooled_conn: Pooled connection to return
        """
        self._total_checkins += 1

        # Decrease active count
        with self._lock:
            self._active_connections -= 1

        # Return to pool
        try:
            self._pool.put(pooled_conn, block=False)
            logger.debug(f"Checked in connection {pooled_conn.pool_id}")
        except Exception as e:
            logger.error(f"Failed to return connection {pooled_conn.pool_id}: {e}")
            pooled_conn.close()

    def close_all(self) -> None:
        """Close all connections in the pool.

        Should be called during application shutdown.
        """
        logger.info("Closing connection pool...")

        closed_count = 0
        while not self._pool.empty():
            try:
                pooled_conn = self._pool.get(block=False)
                pooled_conn.close()
                closed_count += 1
            except Empty:
                break
            except Exception as e:
                logger.error(f"Error closing connection: {e}")

        logger.info(f"Connection pool closed: {closed_count} connections")

    def get_stats(self) -> dict:
        """Get connection pool statistics.

        Returns:
            Dictionary with pool metrics:
            - pool_size: Maximum pool size
            - active: Currently active connections
            - available: Connections available in pool
            - total_created: Total connections created
            - total_checkouts: Total checkout operations
            - total_checkins: Total checkin operations
            - total_timeouts: Number of timeout errors
            - total_health_failures: Number of health check failures
        """
        with self._lock:
            return {
                "pool_size": self.pool_size,
                "active": self._active_connections,
                "available": self._pool.qsize(),
                "total_created": self._total_created,
                "total_checkouts": self._total_checkouts,
                "total_checkins": self._total_checkins,
                "total_timeouts": self._total_timeouts,
                "total_health_failures": self._total_health_failures,
            }

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit - close all connections."""
        self.close_all()
