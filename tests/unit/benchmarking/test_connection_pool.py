"""Unit tests for database connection pooling.

Tests connection pooling, health checks, and concurrent access.
"""

import sqlite3
import threading
import time

import pytest

from src.benchmarking.connection_pool import ConnectionPool, PooledConnection


class TestPooledConnection:
    """Test PooledConnection wrapper."""

    def test_initialization(self):
        """Test pooled connection initialization."""
        conn = sqlite3.connect(":memory:")
        pooled = PooledConnection(conn, pool_id=1)

        assert pooled.conn == conn
        assert pooled.pool_id == 1
        assert pooled.use_count == 0
        assert pooled.is_healthy is True

    def test_mark_used(self):
        """Test marking connection as used."""
        conn = sqlite3.connect(":memory:")
        pooled = PooledConnection(conn, pool_id=1)

        initial_time = pooled.last_used
        time.sleep(0.01)

        pooled.mark_used()
        assert pooled.use_count == 1
        assert pooled.last_used > initial_time

    def test_health_check(self):
        """Test connection health check."""
        conn = sqlite3.connect(":memory:")
        pooled = PooledConnection(conn, pool_id=1)

        # Healthy connection
        assert pooled.check_health() is True
        assert pooled.is_healthy is True

        # Close connection (makes it unhealthy)
        conn.close()
        assert pooled.check_health() is False
        assert pooled.is_healthy is False


class TestConnectionPool:
    """Test ConnectionPool functionality."""

    @pytest.fixture
    def db_path(self, tmp_path):
        """Provide temporary database path."""
        return tmp_path / "test_pool.db"

    def test_initialization(self, db_path):
        """Test connection pool initialization."""
        pool = ConnectionPool(db_path, pool_size=3, timeout=10.0)

        try:
            stats = pool.get_stats()
            assert stats["pool_size"] == 3
            assert stats["available"] == 3
            assert stats["active"] == 0
            assert stats["total_created"] == 3
        finally:
            pool.close_all()

    def test_get_connection(self, db_path):
        """Test getting connection from pool."""
        pool = ConnectionPool(db_path, pool_size=2)

        try:
            with pool.get_connection() as conn:
                # Should get a valid connection
                assert conn is not None
                cursor = conn.execute("SELECT 1")
                result = cursor.fetchone()
                assert result[0] == 1

                # Check stats during usage
                stats = pool.get_stats()
                assert stats["active"] == 1
                assert stats["available"] == 1

            # Connection returned to pool
            stats = pool.get_stats()
            assert stats["active"] == 0
            assert stats["available"] == 2
        finally:
            pool.close_all()

    def test_multiple_connections(self, db_path):
        """Test checking out multiple connections."""
        pool = ConnectionPool(db_path, pool_size=3)

        try:
            # Get two connections
            with pool.get_connection() as conn1:
                with pool.get_connection() as conn2:
                    assert conn1 is not None
                    assert conn2 is not None
                    assert conn1 is not conn2

                    stats = pool.get_stats()
                    assert stats["active"] == 2
                    assert stats["available"] == 1

            # All returned
            stats = pool.get_stats()
            assert stats["active"] == 0
            assert stats["available"] == 3
        finally:
            pool.close_all()

    def test_pool_exhaustion_timeout(self, db_path):
        """Test timeout when pool is exhausted."""
        pool = ConnectionPool(db_path, pool_size=1, timeout=0.1)

        try:
            # Get the only connection
            with pool.get_connection() as conn1:
                # Try to get another (should timeout)
                with pytest.raises(TimeoutError):
                    with pool.get_connection() as conn2:
                        pass
        finally:
            pool.close_all()

    def test_connection_reuse(self, db_path):
        """Test that connections are reused from pool."""
        pool = ConnectionPool(db_path, pool_size=1)

        try:
            # Track connection identity
            conn_ids = []

            for _ in range(3):
                with pool.get_connection() as conn:
                    conn_ids.append(id(conn))

            # All should be the same connection (reused)
            assert len(set(conn_ids)) == 1

            stats = pool.get_stats()
            assert stats["total_checkouts"] == 3
            assert stats["total_checkins"] == 3
        finally:
            pool.close_all()

    def test_concurrent_access(self, db_path):
        """Test concurrent access from multiple threads."""
        pool = ConnectionPool(db_path, pool_size=5, timeout=5.0)
        results = []
        errors = []

        def worker(thread_id):
            try:
                for i in range(5):
                    with pool.get_connection() as conn:
                        # Execute a query
                        cursor = conn.execute("SELECT ?", (thread_id * 100 + i,))
                        result = cursor.fetchone()[0]
                        results.append(result)
                        time.sleep(0.001)  # Small delay
            except Exception as e:
                errors.append(e)

        try:
            # Create threads
            threads = [threading.Thread(target=worker, args=(i,)) for i in range(10)]

            # Start all threads
            for t in threads:
                t.start()

            # Wait for completion
            for t in threads:
                t.join()

            # Check results
            assert len(errors) == 0, f"Errors occurred: {errors}"
            assert len(results) == 50  # 10 threads * 5 queries each

            stats = pool.get_stats()
            assert stats["total_checkouts"] == 50
            assert stats["total_checkins"] == 50
            assert stats["active"] == 0
        finally:
            pool.close_all()

    def test_connection_health_validation(self, db_path):
        """Test connection health validation on checkout."""
        pool = ConnectionPool(db_path, pool_size=1, max_connection_age=0.1)

        try:
            # Get initial connection
            with pool.get_connection() as conn:
                conn_id1 = id(conn)

            # Wait for connection to age
            time.sleep(0.15)

            # Get connection again (should be replaced due to age)
            with pool.get_connection() as conn:
                conn_id2 = id(conn)

            # Should be different connection
            assert conn_id1 != conn_id2

            stats = pool.get_stats()
            assert stats["total_created"] == 2  # Original + replacement
        finally:
            pool.close_all()

    def test_close_all(self, db_path):
        """Test closing all connections."""
        pool = ConnectionPool(db_path, pool_size=3)

        stats = pool.get_stats()
        assert stats["available"] == 3

        pool.close_all()

        stats = pool.get_stats()
        assert stats["available"] == 0

    def test_context_manager(self, db_path):
        """Test using pool as context manager."""
        with ConnectionPool(db_path, pool_size=2) as pool:
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT 1")
                assert cursor.fetchone()[0] == 1

        # Pool should be closed after context
        stats = pool.get_stats()
        assert stats["available"] == 0

    def test_statistics_tracking(self, db_path):
        """Test comprehensive statistics tracking."""
        pool = ConnectionPool(db_path, pool_size=2, timeout=0.1)

        try:
            # Normal operations
            with pool.get_connection() as conn:
                pass

            with pool.get_connection() as conn:
                pass

            # Timeout attempt
            with pool.get_connection() as conn1:
                with pool.get_connection() as conn2:
                    try:
                        with pool.get_connection() as conn3:
                            pass
                    except TimeoutError:
                        pass

            stats = pool.get_stats()
            assert stats["total_checkouts"] == 5
            assert stats["total_checkins"] == 4
            assert stats["total_timeouts"] == 1
        finally:
            pool.close_all()


class TestConnectionPoolIntegration:
    """Integration tests for connection pool."""

    @pytest.fixture
    def db_with_data(self, tmp_path):
        """Create database with test data."""
        db_path = tmp_path / "test_integration.db"
        conn = sqlite3.connect(str(db_path))

        # Create test table
        conn.execute("""
            CREATE TABLE test_data (
                id INTEGER PRIMARY KEY,
                value TEXT
            )
        """)

        # Insert test data
        for i in range(100):
            conn.execute("INSERT INTO test_data (id, value) VALUES (?, ?)", (i, f"value_{i}"))

        conn.commit()
        conn.close()

        return db_path

    def test_query_execution_with_pool(self, db_with_data):
        """Test executing queries through connection pool."""
        pool = ConnectionPool(db_with_data, pool_size=3)

        try:
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM test_data")
                count = cursor.fetchone()[0]
                assert count == 100

                cursor = conn.execute("SELECT * FROM test_data WHERE id < ?", (10,))
                results = cursor.fetchall()
                assert len(results) == 10
        finally:
            pool.close_all()

    def test_transaction_handling(self, db_with_data):
        """Test transaction handling with pooled connections."""
        pool = ConnectionPool(db_with_data, pool_size=2)

        try:
            # Execute transaction
            with pool.get_connection() as conn:
                conn.execute("BEGIN")
                conn.execute("UPDATE test_data SET value = ? WHERE id = ?", ("updated", 1))
                conn.commit()

            # Verify update in separate connection
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT value FROM test_data WHERE id = ?", (1,))
                result = cursor.fetchone()[0]
                assert result == "updated"
        finally:
            pool.close_all()

    def test_parallel_reads(self, db_with_data):
        """Test parallel read operations."""
        pool = ConnectionPool(db_with_data, pool_size=5)
        results = {}

        def read_worker(thread_id, start_id, end_id):
            with pool.get_connection() as conn:
                cursor = conn.execute(
                    "SELECT COUNT(*) FROM test_data WHERE id >= ? AND id < ?",
                    (start_id, end_id)
                )
                count = cursor.fetchone()[0]
                results[thread_id] = count

        try:
            threads = []
            for i in range(5):
                start = i * 20
                end = (i + 1) * 20
                t = threading.Thread(target=read_worker, args=(i, start, end))
                threads.append(t)
                t.start()

            for t in threads:
                t.join()

            # Each thread should have read 20 records
            assert all(count == 20 for count in results.values())
            assert sum(results.values()) == 100
        finally:
            pool.close_all()
