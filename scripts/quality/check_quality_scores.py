#!/usr/bin/env python3
"""Quick check of quality scores in database."""

import sqlite3

db = sqlite3.connect("data/benchmarks/benchmarks.db")
cursor = db.cursor()

# Check schema
cursor.execute("PRAGMA table_info(benchmark_results)")
columns = [row[1] for row in cursor.fetchall()]
print(f"Columns: {columns}")

# Get quality scores
cursor.execute("""
    SELECT sample_id, bleu_score, comet_score, throughput_tokens_per_sec
    FROM benchmark_results
    WHERE bleu_score IS NOT NULL
    LIMIT 10
""")

print("\nSample quality scores:")
for row in cursor.fetchall():
    sample_id, bleu, comet, throughput = row
    print(f"  {sample_id}: BLEU={bleu:.2f}, COMET={comet}, throughput={throughput:.1f} tok/s")

# Get average scores
cursor.execute("""
    SELECT
        AVG(bleu_score) as avg_bleu,
        COUNT(*) as count
    FROM benchmark_results
    WHERE bleu_score IS NOT NULL
""")
row = cursor.fetchone()
print(f"\nQuality benchmarks: {row[1]} samples, avg BLEU={row[0]:.2f}")

db.close()
