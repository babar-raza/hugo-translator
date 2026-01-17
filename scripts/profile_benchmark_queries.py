"""Profile benchmark database queries with EXPLAIN QUERY PLAN.

This script analyzes query performance for Phase 4.2 optimization by:
1. Creating a test database with realistic data
2. Running EXPLAIN QUERY PLAN on all analytics queries
3. Measuring actual query execution time
4. Identifying missing indices and optimization opportunities
"""

import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path
import sys

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkRun, BenchmarkResult
from src.benchmarking.system_info import SystemInfo


def create_test_database(db_path: str, num_runs: int = 100) -> None:
    """Create test database with realistic data.

    Args:
        db_path: Path to database file
        num_runs: Number of benchmark runs to create
    """
    print(f"Creating test database with {num_runs} runs...")
    db = BenchmarkDatabase(db_path)

    models = ["m2m100_418m", "nllb_200_distilled_600m", "opus_mt_en_fr"]
    devices = ["cpu", "cuda"]

    base_time = datetime.now(UTC) - timedelta(days=30)

    for i in range(num_runs):
        model_id = models[i % len(models)]
        device = devices[i % len(devices)]

        run_id = f"test_run_{i:05d}"
        timestamp = base_time + timedelta(hours=i)

        # Create system info
        system_info = SystemInfo(
            cpu_model="Intel Core i7-9700K",
            cpu_cores=8,
            total_ram_gb=32.0,
            gpu_model="NVIDIA RTX 3080" if device == "cuda" else None,
            gpu_memory_gb=10.0 if device == "cuda" else None,
            os_name="Linux",
            os_version="5.15.0",
            python_version="3.10.0",
            torch_version="2.0.0",
            collected_at_utc=timestamp.isoformat()
        )

        # Create results (10 samples per run)
        results = []
        for j in range(10):
            results.append(BenchmarkResult(
                sample_id=f"{run_id}_sample_{j}",
                model_id=model_id,
                device=device,
                batch_size=8,
                duration_seconds=1.5 + (j * 0.1),
                tokens_input=512,
                tokens_output=128,
                throughput_tokens_per_sec=85.0 + (j * 5),
                peak_memory_mb=2048.0 if device == "cpu" else 4096.0,
                bleu_score=0.65 + (j * 0.01),
                comet_score=0.75 + (j * 0.01),
                cache_status="miss",
                tm_level="none",
                cache_hit_rate=0.0
            ))

        # Save run
        run = BenchmarkRun(
            run_id=run_id,
            model_id=model_id,
            device=device,
            batch_sizes=[8],
            iterations=10,
            corpus_category="general",
            purpose="testing",
            tags=["test"],
            system_info=system_info,
            results=results,
            total_duration_seconds=sum(r.duration_seconds for r in results),
            timestamp_utc=timestamp.isoformat()
        )

        db.save_run(run)

        if (i + 1) % 10 == 0:
            print(f"  Created {i + 1}/{num_runs} runs")

    print(f"Test database created: {db_path}")


def profile_query(conn: sqlite3.Connection, query: str, params: tuple, name: str) -> dict:
    """Profile a single query with EXPLAIN QUERY PLAN and timing.

    Args:
        conn: Database connection
        query: SQL query to profile
        params: Query parameters
        name: Query name for reporting

    Returns:
        Dictionary with profiling results
    """
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
        "query_plan": query_plan
    }


def main():
    """Main profiling routine."""
    # Create test database
    test_db_path = "test_benchmark_profile.db"
    if Path(test_db_path).exists():
        print(f"Using existing database: {test_db_path}")
    else:
        create_test_database(test_db_path, num_runs=500)

    # Connect to database
    conn = sqlite3.connect(test_db_path)
    conn.row_factory = sqlite3.Row

    print("\n" + "="*80)
    print("QUERY PROFILING RESULTS")
    print("="*80)

    # Profile queries from AnalyticsQueryAPI

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
    result1 = profile_query(conn, query1, ("m2m100_418m", "cpu", "daily", "-30 days"), "get_performance_trends")
    print(f"  Avg time: {result1['avg_time_ms']:.2f}ms (min: {result1['min_time_ms']:.2f}ms, max: {result1['max_time_ms']:.2f}ms)")
    print(f"  Rows returned: {result1['row_count']}")
    print("  Query plan:")
    for row in result1['query_plan']:
        print(f"    {row}")

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
    result2 = profile_query(conn, query2, ("m2m100_418m", "cpu", "-7 days"), "get_throughput_distribution")
    print(f"  Avg time: {result2['avg_time_ms']:.2f}ms (min: {result2['min_time_ms']:.2f}ms, max: {result2['max_time_ms']:.2f}ms)")
    print(f"  Rows returned: {result2['row_count']}")
    print("  Query plan:")
    for row in result2['query_plan']:
        print(f"    {row}")

    # 3. compare_performance - baseline lookup
    print("\n### Query 3: compare_performance (baseline lookup)")
    query3 = """
        SELECT avg_throughput, p95_throughput
        FROM performance_baselines
        WHERE model_id = ? AND device = ? AND baseline_date = ?
    """
    result3 = profile_query(conn, query3, ("m2m100_418m", "cpu", "2024-01-01"), "compare_performance_baseline")
    print(f"  Avg time: {result3['avg_time_ms']:.2f}ms (min: {result3['min_time_ms']:.2f}ms, max: {result3['max_time_ms']:.2f}ms)")
    print(f"  Rows returned: {result3['row_count']}")
    print("  Query plan:")
    for row in result3['query_plan']:
        print(f"    {row}")

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
    result4 = profile_query(conn, query4, ("m2m100_418m", "cpu", "2024-02-01", "2024-02-01"), "compare_performance_current")
    print(f"  Avg time: {result4['avg_time_ms']:.2f}ms (min: {result4['min_time_ms']:.2f}ms, max: {result4['max_time_ms']:.2f}ms)")
    print(f"  Rows returned: {result4['row_count']}")
    print("  Query plan:")
    for row in result4['query_plan']:
        print(f"    {row}")

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
    result5 = profile_query(conn, query5, ("m2m100_418m", "nllb_200_distilled_600m", "opus_mt_en_fr", "cpu", "-30 days"), "get_model_comparison")
    print(f"  Avg time: {result5['avg_time_ms']:.2f}ms (min: {result5['min_time_ms']:.2f}ms, max: {result5['max_time_ms']:.2f}ms)")
    print(f"  Rows returned: {result5['row_count']}")
    print("  Query plan:")
    for row in result5['query_plan']:
        print(f"    {row}")

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
    result6 = profile_query(conn, query6, ("m2m100_418m", "cpu", start_time, end_time), "aggregate_window")
    print(f"  Avg time: {result6['avg_time_ms']:.2f}ms (min: {result6['min_time_ms']:.2f}ms, max: {result6['max_time_ms']:.2f}ms)")
    print(f"  Rows returned: {result6['row_count']}")
    print("  Query plan:")
    for row in result6['query_plan']:
        print(f"    {row}")

    # Summary
    print("\n" + "="*80)
    print("SUMMARY")
    print("="*80)

    results = [result1, result2, result3, result4, result5, result6]

    print("\nQuery Performance (sorted by avg time):")
    results_sorted = sorted(results, key=lambda x: x['avg_time_ms'], reverse=True)
    for r in results_sorted:
        status = "SLOW" if r['avg_time_ms'] > 100 else "OK"
        print(f"  [{status}] {r['name']}: {r['avg_time_ms']:.2f}ms ({r['row_count']} rows)")

    print("\nOptimization Recommendations:")
    print("  1. Add composite index on benchmark_trends(model_id, device, window_start)")
    print("  2. Add composite index on benchmark_results(run_id, metric_name) - for future metrics")
    print("  3. Add composite index on benchmark_runs(model_id, device, timestamp_utc)")
    print("  4. Add composite index on performance_baselines(model_id, device, baseline_type)")
    print("  5. Consider query result caching for repeated queries")
    print("  6. Implement connection pooling to reduce connection overhead")

    conn.close()

    print(f"\nTest database retained: {test_db_path}")
    print("Run profiling complete.")


if __name__ == "__main__":
    main()
