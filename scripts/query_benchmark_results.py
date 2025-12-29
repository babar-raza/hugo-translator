#!/usr/bin/env python3
"""Query and display all benchmark results from the database."""

import sqlite3
from pathlib import Path

def main():
    db_path = Path("data/benchmarks/benchmarks.db")

    if not db_path.exists():
        print(f"Database not found: {db_path}")
        return

    conn = sqlite3.connect(db_path)
    cursor = conn.cursor()

    # Get summary statistics per model
    query = """
    SELECT
        model_id,
        device,
        COUNT(*) as sample_count,
        AVG(throughput_tokens_per_sec) as avg_throughput,
        MIN(throughput_tokens_per_sec) as min_throughput,
        MAX(throughput_tokens_per_sec) as max_throughput
    FROM benchmark_results
    GROUP BY model_id, device
    ORDER BY avg_throughput DESC
    """

    cursor.execute(query)
    results = cursor.fetchall()

    print("Model Benchmark Results (CPU):")
    print("=" * 85)
    print(f"{'Model':<25} {'Samples':<10} {'Avg (tok/s)':<15} {'Min':<10} {'Max':<10}")
    print("-" * 85)

    for row in results:
        model_id, device, count, avg, min_val, max_val = row
        print(f"{model_id:<25} {count:<10} {avg:<15.1f} {min_val:<10.1f} {max_val:<10.1f}")

    print("=" * 85)
    print(f"Total models benchmarked: {len(results)}")

    # Check if quality_benchmarks table exists
    cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='quality_benchmarks'")
    table_exists = cursor.fetchone()

    if table_exists:
        # Get quality benchmark results
        quality_query = """
        SELECT
            model_id,
            metric_name,
            score
        FROM quality_benchmarks
        ORDER BY model_id, metric_name
        """

        cursor.execute(quality_query)
        quality_results = cursor.fetchall()

        if quality_results:
            print("\nQuality Benchmark Results:")
            print("=" * 60)
            print(f"{'Model':<25} {'Metric':<15} {'Score':<10}")
            print("-" * 60)

            for row in quality_results:
                model_id, metric_name, score = row
                print(f"{model_id:<25} {metric_name:<15} {score:<10.2f}")

            print("=" * 60)

    conn.close()

if __name__ == "__main__":
    main()
