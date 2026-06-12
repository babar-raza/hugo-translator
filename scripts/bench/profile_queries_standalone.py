"""Standalone query profiling script for Phase 4.2.

Profiles benchmark database queries without requiring full project imports.
"""

import json
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path


def create_test_database(db_path: str, num_runs: int = 500) -> None:
    """Create test database with realistic data."""
    print(f"Creating test database with {num_runs} runs...")

    conn = sqlite3.connect(db_path)
    conn.execute("PRAGMA foreign_keys = ON")
    conn.execute("PRAGMA journal_mode = WAL")

    # Create schema (v8)
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

        -- Existing v1 indices
        CREATE INDEX IF NOT EXISTS idx_runs_model ON benchmark_runs(model_id);
        CREATE INDEX IF NOT EXISTS idx_runs_device ON benchmark_runs(device);
        CREATE INDEX IF NOT EXISTS idx_runs_timestamp ON benchmark_runs(timestamp_utc);
        CREATE INDEX IF NOT EXISTS idx_results_run ON benchmark_results(run_id);

        -- v2 composite indices
        CREATE INDEX IF NOT EXISTS idx_runs_model_device ON benchmark_runs(model_id, device);
        CREATE INDEX IF NOT EXISTS idx_runs_model_device_timestamp ON benchmark_runs(model_id, device, timestamp_utc);

        -- v8 trend indices
        CREATE INDEX IF NOT EXISTS idx_trends_model_device ON benchmark_trends(model_id, device);
        CREATE INDEX IF NOT EXISTS idx_trends_window ON benchmark_trends(time_window, window_start);
        CREATE INDEX IF NOT EXISTS idx_trends_model_device_window ON benchmark_trends(model_id, device, time_window, window_start);

        -- v8 baseline indices
        CREATE INDEX IF NOT EXISTS idx_baselines_model_device ON performance_baselines(model_id, device);
        CREATE INDEX IF NOT EXISTS idx_baselines_type_date ON performance_baselines(baseline_type, baseline_date);
    """)

    models = ["m2m100_418m", "nllb_200_distilled_600m", "opus_mt_en_fr"]
    devices = ["cpu", "cuda"]
    base_time = datetime.now(UTC) - timedelta(days=30)

    # Insert benchmark runs and results
    for i in range(num_runs):
        model_id = models[i % len(models)]
        device = devices[i % len(devices)]
        run_id = f"test_run_{i:05d}"
        timestamp = (base_time + timedelta(hours=i * 1.5)).isoformat()

        conn.execute(
            """
            INSERT INTO benchmark_runs
            (run_id, model_id, device, batch_sizes, iterations, corpus_category,
             purpose, tags, total_duration_seconds, timestamp_utc, metadata)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
            (
                run_id,
                model_id,
                device,
                json.dumps([8]),
                10,
                "general",
                "testing",
                json.dumps(["test"]),
                15.0,
                timestamp,
                json.dumps({}),
            ),
        )

        # Insert 10 results per run
        for j in range(10):
            conn.execute(
                """
                INSERT INTO benchmark_results
                (run_id, sample_id, model_id, device, batch_size, duration_seconds,
                 tokens_input, tokens_output, throughput_tokens_per_sec,
                 peak_memory_mb, bleu_score, comet_score, cache_status, tm_level,
                 cache_hit_rate, errors)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    run_id,
                    f"{run_id}_sample_{j}",
                    model_id,
                    device,
                    8,
                    1.5 + (j * 0.1),
                    512,
                    128,
                    85.0 + (j * 5),
                    2048.0 if device == "cpu" else 4096.0,
                    0.65 + (j * 0.01),
                    0.75 + (j * 0.01),
                    "miss",
                    "none",
                    0.0,
                    json.dumps([]),
                ),
            )

        if (i + 1) % 50 == 0:
            conn.commit()
            print(f"  Created {i + 1}/{num_runs} runs")

    # Insert some trend data
    for model in models:
        for device in devices:
            for day in range(30):
                window_start = (base_time + timedelta(days=day)).isoformat()
                window_end = (base_time + timedelta(days=day + 1)).isoformat()
                conn.execute(
                    """
                    INSERT INTO benchmark_trends
                    (model_id, device, time_window, window_start, window_end,
                     sample_count, avg_throughput, p50_throughput, p95_throughput, p99_throughput,
                     avg_duration, avg_memory_mb, created_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                    (
                        model,
                        device,
                        "daily",
                        window_start,
                        window_end,
                        100,
                        90.0,
                        88.0,
                        95.0,
                        98.0,
                        1.5,
                        3000.0,
                        datetime.now(UTC).isoformat(),
                    ),
                )

    # Insert baseline data
    for model in models:
        for device in devices:
            conn.execute(
                """
                INSERT INTO performance_baselines
                (model_id, device, baseline_type, baseline_date,
                 avg_throughput, p50_throughput, p95_throughput,
                 sample_count, metadata, created_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
                (
                    model,
                    device,
                    "daily",
                    "2024-01-01",
                    85.0,
                    83.0,
                    92.0,
                    1000,
                    json.dumps({}),
                    datetime.now(UTC).isoformat(),
                ),
            )

    conn.commit()
    conn.close()
    print(f"Test database created: {db_path}")


def profile_query(conn: sqlite3.Connection, query: str, params: tuple, name: str) -> dict:
    """Profile a single query with EXPLAIN QUERY PLAN and timing."""
    # Get query plan
    explain_query = f"EXPLAIN QUERY PLAN {query}"
    cursor = conn.execute(explain_query, params)
    query_plan = cursor.fetchall()

    # Measure execution time (run 10 times and average)
    times = []
    for _ in range(10):
        start = time.perf_counter()
        cursor = conn.execute(query, params)
        rows = cursor.fetchall()
        end = time.perf_counter()
        times.append((end - start) * 1000)  # Convert to ms

    avg_time = sum(times) / len(times)
    min_time = min(times)
    max_time = max(times)

    return {
        "name": name,
        "avg_time_ms": avg_time,
        "min_time_ms": min_time,
        "max_time_ms": max_time,
        "row_count": len(rows),
        "query_plan": query_plan,
    }


def main():
    """Main profiling routine."""
    test_db_path = "test_benchmark_profile.db"

    # Create fresh database
    if Path(test_db_path).exists():
        Path(test_db_path).unlink()
        print("Removed existing database")

    create_test_database(test_db_path, num_runs=500)

    # Connect to database
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row

    print("\n" + "=" * 80)
    print("QUERY PROFILING RESULTS (BEFORE OPTIMIZATION)")
    print("=" * 80)

    results = []

    # 1. get_performance_trends
    print("\n### Query 1: get_performance_trends")
    query1 = """
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
    result1 = profile_query(
        conn, query1, ("m2m100_418m", "cpu", "daily", "-30 days"), "get_performance_trends"
    )
    print(
        f"  Avg time: {result1['avg_time_ms']:.2f}ms (min: {result1['min_time_ms']:.2f}ms, max: {result1['max_time_ms']:.2f}ms)"
    )
    print(f"  Rows returned: {result1['row_count']}")
    print("  Query plan:")
    for row in result1["query_plan"]:
        print(f"    {row}")
    results.append(result1)

    # 2. get_throughput_distribution
    print("\n### Query 2: get_throughput_distribution")
    query2 = """
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
    result2 = profile_query(
        conn, query2, ("m2m100_418m", "cpu", "-7 days"), "get_throughput_distribution"
    )
    print(
        f"  Avg time: {result2['avg_time_ms']:.2f}ms (min: {result2['min_time_ms']:.2f}ms, max: {result2['max_time_ms']:.2f}ms)"
    )
    print(f"  Rows returned: {result2['row_count']}")
    print("  Query plan:")
    for row in result2["query_plan"]:
        print(f"    {row}")
    results.append(result2)

    # 3. compare_performance - baseline lookup
    print("\n### Query 3: compare_performance (baseline lookup)")
    query3 = """
        SELECT avg_throughput, p95_throughput
        FROM performance_baselines
        WHERE model_id = ? AND device = ? AND baseline_date = ?
    """
    result3 = profile_query(
        conn, query3, ("m2m100_418m", "cpu", "2024-01-01"), "compare_performance_baseline"
    )
    print(
        f"  Avg time: {result3['avg_time_ms']:.2f}ms (min: {result3['min_time_ms']:.2f}ms, max: {result3['max_time_ms']:.2f}ms)"
    )
    print(f"  Rows returned: {result3['row_count']}")
    print("  Query plan:")
    for row in result3["query_plan"]:
        print(f"    {row}")
    results.append(result3)

    # 4. compare_performance - current data
    print("\n### Query 4: compare_performance (current data)")
    query4 = """
        SELECT
            AVG(throughput_tokens_per_sec) as avg_throughput
        FROM benchmark_results br
        JOIN benchmark_runs r ON br.run_id = r.run_id
        WHERE r.model_id = ?
          AND r.device = ?
          AND DATE(r.timestamp_utc) <= ?
          AND DATE(r.timestamp_utc) > DATE(?, '-7 days')
    """
    result4 = profile_query(
        conn,
        query4,
        ("m2m100_418m", "cpu", "2024-02-01", "2024-02-01"),
        "compare_performance_current",
    )
    print(
        f"  Avg time: {result4['avg_time_ms']:.2f}ms (min: {result4['min_time_ms']:.2f}ms, max: {result4['max_time_ms']:.2f}ms)"
    )
    print(f"  Rows returned: {result4['row_count']}")
    print("  Query plan:")
    for row in result4["query_plan"]:
        print(f"    {row}")
    results.append(result4)

    # 5. get_model_comparison
    print("\n### Query 5: get_model_comparison")
    query5 = """
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
    result5 = profile_query(
        conn,
        query5,
        ("m2m100_418m", "nllb_200_distilled_600m", "opus_mt_en_fr", "cpu", "-30 days"),
        "get_model_comparison",
    )
    print(
        f"  Avg time: {result5['avg_time_ms']:.2f}ms (min: {result5['min_time_ms']:.2f}ms, max: {result5['max_time_ms']:.2f}ms)"
    )
    print(f"  Rows returned: {result5['row_count']}")
    print("  Query plan:")
    for row in result5["query_plan"]:
        print(f"    {row}")
    results.append(result5)

    # 6. TimeSeriesAggregator query
    print("\n### Query 6: TimeSeriesAggregator._aggregate_window")
    query6 = """
        SELECT
            br.throughput_tokens_per_sec,
            br.duration_seconds,
            br.peak_memory_mb
        FROM benchmark_results br
        JOIN benchmark_runs r ON br.run_id = r.run_id
        WHERE r.model_id = ?
          AND r.device = ?
          AND r.timestamp_utc >= ?
          AND r.timestamp_utc < ?
        ORDER BY br.throughput_tokens_per_sec
    """
    start_time = (datetime.now(UTC) - timedelta(days=1)).isoformat()
    end_time = datetime.now(UTC).isoformat()
    result6 = profile_query(
        conn, query6, ("m2m100_418m", "cpu", start_time, end_time), "aggregate_window"
    )
    print(
        f"  Avg time: {result6['avg_time_ms']:.2f}ms (min: {result6['min_time_ms']:.2f}ms, max: {result6['max_time_ms']:.2f}ms)"
    )
    print(f"  Rows returned: {result6['row_count']}")
    print("  Query plan:")
    for row in result6["query_plan"]:
        print(f"    {row}")
    results.append(result6)

    # Summary
    print("\n" + "=" * 80)
    print("BASELINE PERFORMANCE SUMMARY")
    print("=" * 80)

    print("\nQuery Performance (sorted by avg time):")
    results_sorted = sorted(results, key=lambda x: x["avg_time_ms"], reverse=True)
    for r in results_sorted:
        status = "SLOW" if r["avg_time_ms"] > 10 else "OK"
        print(
            f"  [{status:>4}] {r['name']:<35} {r['avg_time_ms']:>7.2f}ms ({r['row_count']:>5} rows)"
        )

    print("\nIndex Analysis:")
    cursor = conn.execute(
        "SELECT name, sql FROM sqlite_master WHERE type='index' AND name LIKE 'idx_%'"
    )
    indices = cursor.fetchall()
    print(f"  Current indices: {len(indices)}")
    for idx in indices:
        print(f"    - {idx[0]}")

    print("\nOptimization Recommendations (Phase 4.2):")
    print("  1. Add composite index: benchmark_trends(model_id, device, window_start)")
    print("  2. Add composite index: benchmark_results(run_id, throughput_tokens_per_sec)")
    print("  3. Add composite index: performance_baselines(model_id, device, baseline_type)")
    print("  4. Implement query result caching with LRU + TTL")
    print("  5. Implement database connection pooling")
    print("  6. Add slow query logging (>500ms threshold)")

    conn.close()

    print(f"\nTest database retained: {test_db_path}")
    print("Profiling complete. Baseline measurements recorded.")


if __name__ == "__main__":
    main()
