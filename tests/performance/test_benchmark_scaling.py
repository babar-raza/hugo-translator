"""Performance and scalability tests for benchmark database.

Tests query performance at scale (10,000+ benchmark runs) to validate
Phase 4.2 optimizations.

Run with: pytest tests/performance/test_benchmark_scaling.py -v --benchmark
"""

import json
import logging
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

from src.benchmarking.query_cache import QueryCache, make_cache_key
from src.benchmarking.connection_pool import ConnectionPool
from src.benchmarking.performance_monitor import PerformanceMonitor

logger = logging.getLogger(__name__)


def create_large_test_database(db_path: str, num_runs: int = 10000) -> None:
    """Create test database with large dataset for scalability testing.

    Args:
        db_path: Path to database file
        num_runs: Number of benchmark runs to create (default 10,000)
    """
    logger.info(f"Creating large test database with {num_runs} runs...")
    start_time = time.time()

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA synchronous = NORMAL")  # Faster inserts

    # Create schema with v9 indices
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS benchmark_runs (
            run_id TEXT PRIMARY KEY,
            model_id TEXT NOT NULL,
            device TEXT NOT NULL,
            batch_sizes TEXT NOT NULL,
            iterations INTEGER NOT NULL,
            corpus_category TEXT,
            purpose TEXT NOT NULL,
            tags TEXT NOT NULL,
            total_duration_seconds REAL NOT NULL,
            timestamp_utc TEXT NOT NULL,
            metadata TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS benchmark_results (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            run_id TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            model_id TEXT NOT NULL,
            device TEXT NOT NULL,
            batch_size INTEGER NOT NULL,
            duration_seconds REAL NOT NULL,
            tokens_input INTEGER NOT NULL,
            tokens_output INTEGER NOT NULL,
            throughput_tokens_per_sec REAL NOT NULL,
            peak_memory_mb REAL,
            bleu_score REAL,
            comet_score REAL,
            cache_status TEXT DEFAULT 'unknown',
            tm_level TEXT DEFAULT 'none',
            cache_hit_rate REAL DEFAULT 0.0,
            errors TEXT NOT NULL,
            FOREIGN KEY (run_id) REFERENCES benchmark_runs(run_id) ON DELETE CASCADE
        );

        CREATE TABLE IF NOT EXISTS benchmark_trends (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            device TEXT NOT NULL,
            time_window TEXT NOT NULL,
            window_start TEXT NOT NULL,
            window_end TEXT NOT NULL,
            sample_count INTEGER NOT NULL,
            avg_throughput REAL NOT NULL,
            p50_throughput REAL NOT NULL,
            p95_throughput REAL NOT NULL,
            p99_throughput REAL NOT NULL,
            avg_duration REAL NOT NULL,
            avg_memory_mb REAL,
            created_at TEXT NOT NULL,
            UNIQUE(model_id, device, time_window, window_start)
        );

        CREATE TABLE IF NOT EXISTS performance_baselines (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            model_id TEXT NOT NULL,
            device TEXT NOT NULL,
            baseline_type TEXT NOT NULL,
            baseline_date TEXT NOT NULL,
            avg_throughput REAL NOT NULL,
            p50_throughput REAL NOT NULL,
            p95_throughput REAL NOT NULL,
            sample_count INTEGER NOT NULL,
            metadata TEXT NOT NULL,
            created_at TEXT NOT NULL,
            UNIQUE(model_id, device, baseline_type, baseline_date)
        );

        -- v1-v8 indices
        CREATE INDEX IF NOT EXISTS idx_runs_model ON benchmark_runs(model_id);
        CREATE INDEX IF NOT EXISTS idx_runs_device ON benchmark_runs(device);
        CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON benchmark_runs(timestamp_utc);
        CREATE INDEX IF NOT EXISTS idx_results_run ON benchmark_results(run_id);
        CREATE INDEX IF NOT EXISTS idx_runs_model_device ON benchmark_runs(model_id, device);
        CREATE INDEX IF NOT EXISTS idx_runs_model_device_timestamp ON benchmark_runs(model_id, device, timestamp_utc);
        CREATE INDEX IF NOT EXISTS idx_trends_model_device ON benchmark_trends(model_id, device);
        CREATE INDEX IF NOT EXISTS idx_trends_window ON benchmark_trends(time_window, window_start);
        CREATE INDEX IF NOT EXISTS idx_trends_model_device_window ON benchmark_trends(model_id, device, time_window, window_start);
        CREATE INDEX IF NOT EXISTS idx_baselines_model_device ON performance_baselines(model_id, device);
        CREATE INDEX IF NOT EXISTS idx_baselines_type_date ON performance_baselines(baseline_type, baseline_date);

        -- v9 optimization indices (Phase 4.2)
        CREATE INDEX IF NOT EXISTS idx_trends_model_device_start ON benchmark_trends(model_id, device, window_start);
        CREATE INDEX IF NOT EXISTS idx_baselines_model_device_type ON performance_baselines(model_id, device, baseline_type);
        CREATE INDEX IF NOT EXISTS idx_results_throughput_perf ON benchmark_results(run_id, throughput_tokens_per_sec);
        CREATE INDEX IF NOT EXISTS idx_runs_created_at ON benchmark_runs(model_id, device, timestamp_utc);
    """)

    models = ["m2m100_418m", "nllb_200_distilled_600m", "opus_mt_en_fr", "mbart_large_50"]
    devices = ["cpu", "cuda"]
    base_time = datetime.now(UTC) - timedelta(days=90)

    # Batch insert for performance
    run_batch = []
    result_batch = []

    for i in range(num_runs):
        model_id = models[i % len(models)]
        device = devices[i % len(devices)]
        run_id = f"scale_test_run_{i:06d}"
        timestamp = (base_time + timedelta(hours=i * 0.5)).isoformat()

        run_batch.append((
            run_id, model_id, device, json.dumps([8]), 10, "general",
            "scalability_test", json.dumps(["test"]), 15.0, timestamp, json.dumps({})
        ))

        # 10 results per run
        for j in range(10):
            result_batch.append((
                run_id, f"{run_id}_sample_{j}", model_id, device, 8, 1.5 + (j * 0.1),
                512, 128, 85.0 + (j * 5), 2048.0 if device == "cpu" else 4096.0,
                0.65 + (j * 0.01), 0.75 + (j * 0.01), "miss", "none", 0.0, json.dumps([])
            ))

        # Commit in batches of 100
        if (i + 1) % 100 == 0:
            conn.executemany("""
                INSERT INTO benchmark_runs
                (run_id, model_id, device, batch_sizes, iterations, corpus_category,
                 purpose, tags, total_duration_seconds, timestamp_utc, metadata)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, run_batch)

            conn.executemany("""
                INSERT INTO benchmark_results
                (run_id, sample_id, model_id, device, batch_size, duration_seconds,
                 tokens_input, tokens_output, throughput_tokens_per_sec,
                 peak_memory_mb, bleu_score, comet_score, cache_status, tm_level,
                 cache_hit_rate, errors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, result_batch)

            conn.commit()
            run_batch = []
            result_batch = []

            if (i + 1) % 1000 == 0:
                elapsed = time.time() - start_time
                logger.info(f"  Created {i + 1}/{num_runs} runs ({elapsed:.1f}s)")

    # Insert remaining batches
    if run_batch:
        conn.executemany("""
            INSERT INTO benchmark_runs
            (run_id, model_id, device, batch_sizes, iterations, corpus_category,
             purpose, tags, total_duration_seconds, timestamp_utc, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, run_batch)

        conn.executemany("""
            INSERT INTO benchmark_results
            (run_id, sample_id, model_id, device, batch_size, duration_seconds,
             tokens_input, tokens_output, throughput_tokens_per_sec,
             peak_memory_mb, bleu_score, comet_score, cache_status, tm_level,
             cache_hit_rate, errors)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """, result_batch)

    # Create trend and baseline data
    for model in models:
        for device in devices:
            for day in range(90):
                window_start = (base_time + timedelta(days=day)).isoformat()
                window_end = (base_time + timedelta(days=day+1)).isoformat()
                conn.execute("""
                    INSERT INTO benchmark_trends
                    (model_id, device, time_window, window_start, window_end,
                     sample_count, avg_throughput, p50_throughput, p95_throughput, p99_throughput,
                     avg_duration, avg_memory_mb, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """, (
                    model, device, "daily", window_start, window_end,
                    100, 90.0, 88.0, 95.0, 98.0, 1.5, 3000.0, datetime.now(UTC).isoformat()
                ))

            # Baseline
            conn.execute("""
                INSERT INTO performance_baselines
                (model_id, device, baseline_type, baseline_date,
                 avg_throughput, p50_throughput, p95_throughput,
                 sample_count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """, (
                model, device, "monthly", "2024-01-01",
                85.0, 83.0, 92.0, 1000, json.dumps({}), datetime.now(UTC).isoformat()
            ))

    conn.commit()
    conn.close()

    elapsed = time.time() - start_time
    logger.info(f"Large test database created in {elapsed:.1f}s: {db_path}")
    logger.info(f"  {num_runs} runs, {num_runs * 10} results")


@pytest.fixture(scope="module")
def large_db(tmp_path_factory):
    """Create large test database (module-scoped for reuse)."""
    db_path = tmp_path_factory.mktemp("data") / "large_benchmark.db"
    create_large_test_database(str(db_path), num_runs=10000)
    return db_path


class TestQueryPerformanceAtScale:
    """Test query performance with large dataset (10,000 runs)."""

    def test_performance_trends_query_speed(self, large_db):
        """Test get_performance_trends query speed at scale."""
        conn = sqlite3.connect(str(large_db))
        conn.row_factory = sqlite3.Row

        query = """
            SELECT
                window_start,
                window_end,
                sample_count,
                avg_throughput,
                p50_throughput,
                p95_throughput,
                p99_throughput,
                avg_duration,
                avg_memory_mb
            FROM benchmark_trends
            WHERE model_id = ?
              AND device = ?
              AND time_window = ?
              AND window_start >= datetime('now', ?)
            ORDER BY window_start
        """

        start_time = time.perf_counter()
        cursor = conn.execute(query, ("m2m100_418m", "cpu", "daily", "-30 days"))
        results = cursor.fetchall()
        duration_ms = (time.perf_counter() - start_time) * 1000

        conn.close()

        # Should be fast even with 10k runs
        assert duration_ms < 50, f"Query took {duration_ms:.2f}ms (expected <50ms)"
        assert len(results) > 0

        logger.info(f"get_performance_trends: {duration_ms:.2f}ms ({len(results)} rows)")

    def test_throughput_distribution_query_speed(self, large_db):
        """Test get_throughput_distribution query speed at scale."""
        conn = sqlite3.connect(str(large_db))
        conn.row_factory = sqlite3.Row

        query = """
            SELECT
                r.timestamp_utc,
                br.batch_size,
                br.throughput_tokens_per_sec,
                br.duration_seconds,
                br.peak_memory_mb
            FROM benchmark_results br
            JOIN benchmark_runs r ON br.run_id = r.run_id
            WHERE r.model_id = ?
              AND r.device = ?
              AND r.timestamp_utc >= datetime('now', ?)
            ORDER BY r.timestamp_utc
        """

        start_time = time.perf_counter()
        cursor = conn.execute(query, ("m2m100_418m", "cpu", "-7 days"))
        results = cursor.fetchall()
        duration_ms = (time.perf_counter() - start_time) * 1000

        conn.close()

        # Should complete in reasonable time
        assert duration_ms < 100, f"Query took {duration_ms:.2f}ms (expected <100ms)"
        assert len(results) > 0

        logger.info(f"get_throughput_distribution: {duration_ms:.2f}ms ({len(results)} rows)")

    def test_model_comparison_query_speed(self, large_db):
        """Test get_model_comparison query speed at scale."""
        conn = sqlite3.connect(str(large_db))
        conn.row_factory = sqlite3.Row

        query = """
            SELECT
                r.model_id,
                COUNT(*) as sample_count,
                AVG(br.throughput_tokens_per_sec) as avg_throughput,
                AVG(br.duration_seconds) as avg_duration,
                AVG(br.peak_memory_mb) as avg_memory_mb,
                MIN(br.throughput_tokens_per_sec) as min_throughput,
                MAX(br.throughput_tokens_per_sec) as max_throughput
            FROM benchmark_results br
            JOIN benchmark_runs r ON br.run_id = r.run_id
            WHERE r.model_id IN (?, ?, ?)
              AND r.device = ?
              AND r.timestamp_utc >= datetime('now', ?)
            GROUP BY r.model_id
            ORDER BY avg_throughput DESC
        """

        start_time = time.perf_counter()
        cursor = conn.execute(query, ("m2m100_418m", "nllb_200_distilled_600m", "opus_mt_en_fr", "cpu", "-30 days"))
        results = cursor.fetchall()
        duration_ms = (time.perf_counter() - start_time) * 1000

        conn.close()

        # Should complete quickly
        assert duration_ms < 150, f"Query took {duration_ms:.2f}ms (expected <150ms)"
        assert len(results) > 0

        logger.info(f"get_model_comparison: {duration_ms:.2f}ms ({len(results)} rows)")


class TestQueryCacheEffectiveness:
    """Test query cache effectiveness at scale."""

    def test_cache_hit_rate(self, large_db):
        """Test cache achieves ≥60% hit rate for repeated queries."""
        cache = QueryCache(max_size=50, ttl_seconds=300)
        conn = sqlite3.connect(str(large_db))

        # Simulate dashboard loading same queries repeatedly
        queries = [
            ("m2m100_418m", "cpu", "daily"),
            ("m2m100_418m", "cuda", "daily"),
            ("nllb_200_distilled_600m", "cpu", "daily"),
        ]

        # Execute queries multiple times
        for _ in range(10):
            for model_id, device, time_window in queries:
                cache_key = make_cache_key("trends", model_id=model_id, device=device, window=time_window)

                # Check cache
                result = cache.get(cache_key)
                if result is None:
                    # Cache miss - execute query
                    cursor = conn.execute("""
                        SELECT * FROM benchmark_trends
                        WHERE model_id = ? AND device = ? AND time_window = ?
                    """, (model_id, device, time_window))
                    result = cursor.fetchall()
                    cache.set(cache_key, result)

        conn.close()

        # Check cache stats
        stats = cache.get_stats()
        hit_rate = stats["hit_rate"]

        logger.info(f"Cache stats: {stats}")
        logger.info(f"Hit rate: {hit_rate:.1%}")

        # Should achieve ≥60% hit rate
        assert hit_rate >= 0.60, f"Cache hit rate {hit_rate:.1%} < 60%"

    def test_cache_performance_benefit(self, large_db):
        """Test cache provides significant performance benefit."""
        cache = QueryCache(max_size=50, ttl_seconds=300)
        conn = sqlite3.connect(str(large_db))

        model_id = "m2m100_418m"
        device = "cpu"
        time_window = "daily"
        cache_key = make_cache_key("trends", model_id=model_id, device=device, window=time_window)

        # First query (cache miss)
        start_time = time.perf_counter()
        cursor = conn.execute("""
            SELECT * FROM benchmark_trends
            WHERE model_id = ? AND device = ? AND time_window = ?
        """, (model_id, device, time_window))
        result = cursor.fetchall()
        cache.set(cache_key, result)
        uncached_duration_ms = (time.perf_counter() - start_time) * 1000

        # Second query (cache hit)
        start_time = time.perf_counter()
        result = cache.get(cache_key)
        cached_duration_ms = (time.perf_counter() - start_time) * 1000

        conn.close()

        # Cache should be significantly faster (>10x)
        speedup = uncached_duration_ms / cached_duration_ms if cached_duration_ms > 0 else 0

        logger.info(f"Uncached: {uncached_duration_ms:.3f}ms")
        logger.info(f"Cached: {cached_duration_ms:.3f}ms")
        logger.info(f"Speedup: {speedup:.1f}x")

        assert speedup > 10, f"Cache speedup {speedup:.1f}x is not significant"


class TestConnectionPoolPerformance:
    """Test connection pool performance under load."""

    def test_pool_reduces_connection_overhead(self, large_db):
        """Test connection pooling reduces overhead vs creating connections."""
        num_queries = 50

        # Without pooling - create new connection each time
        start_time = time.perf_counter()
        for _ in range(num_queries):
            conn = sqlite3.connect(str(large_db))
            cursor = conn.execute("SELECT COUNT(*) FROM benchmark_runs")
            cursor.fetchone()
            conn.close()
        without_pool_ms = (time.perf_counter() - start_time) * 1000

        # With pooling
        pool = ConnectionPool(large_db, pool_size=5)
        start_time = time.perf_counter()
        for _ in range(num_queries):
            with pool.get_connection() as conn:
                cursor = conn.execute("SELECT COUNT(*) FROM benchmark_runs")
                cursor.fetchone()
        with_pool_ms = (time.perf_counter() - start_time) * 1000
        pool.close_all()

        improvement_pct = ((without_pool_ms - with_pool_ms) / without_pool_ms) * 100

        logger.info(f"Without pool: {without_pool_ms:.2f}ms")
        logger.info(f"With pool: {with_pool_ms:.2f}ms")
        logger.info(f"Improvement: {improvement_pct:.1f}%")

        # Pool should be faster
        assert with_pool_ms < without_pool_ms


class TestPerformanceMonitorIntegration:
    """Test performance monitor at scale."""

    def test_slow_query_detection(self, large_db):
        """Test slow query detection and logging."""
        monitor = PerformanceMonitor(slow_threshold_ms=50.0)
        conn = sqlite3.connect(str(large_db))

        # Execute some queries
        queries = [
            ("SELECT COUNT(*) FROM benchmark_runs", "count_runs"),
            ("SELECT * FROM benchmark_results LIMIT 1000", "get_results"),
            ("SELECT * FROM benchmark_trends WHERE model_id = 'm2m100_418m'", "get_trends"),
        ]

        for sql, name in queries:
            with monitor.track_query(name):
                cursor = conn.execute(sql)
                cursor.fetchall()

        conn.close()

        # Check for slow queries
        stats = monitor.get_stats()
        logger.info(f"Monitor stats: {stats}")

        if monitor.has_slow_queries():
            slow = monitor.get_slow_queries()
            logger.warning(f"Detected {len(slow)} slow queries")
            for query in slow:
                logger.warning(f"  {query['name']}: {query['duration_ms']:.2f}ms")

        # Test passes regardless of slow queries (this is informational)
        assert stats["total_queries"] == 3


if __name__ == "__main__":
    # Allow running directly for manual testing
    logging.basicConfig(level=logging.INFO)
    pytest.main([__file__, "-v", "-s"])
