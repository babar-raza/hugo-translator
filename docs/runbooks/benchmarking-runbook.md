# Benchmarking Runbook

**Last Updated**: 2025-12-24
**Audience**: Developers, Operators

## Quick Start

### Run Your First Benchmark

```bash
# 1. Initialize database
python -c "
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase
db = BenchmarkDatabase(Path('data/benchmarks/benchmarks.db'))
print('Database initialized')
"

# 2. Run benchmark
python -m src.benchmarking.cli run \
    --model facebook/m2m100_418M \
    --device cpu \
    --batch-size 8 \
    --corpus tiny \
    --output data/benchmarks/benchmarks.db

# 3. View results
python -c "
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase
db = BenchmarkDatabase(Path('data/benchmarks/benchmarks.db'))
runs = db.list_runs(limit=1)
if runs:
    run = db.get_run(runs[0][0])
    avg_throughput = sum(r.throughput_tokens_per_sec for r in run.results) / len(run.results)
    print(f'Average throughput: {avg_throughput:.1f} tokens/sec')
"
```

### Get a Model Recommendation

```python
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.recommender import ModelRecommender
from src.benchmarking.system_info import SystemInfoCollector

# Initialize
db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
recommender = ModelRecommender(db)
collector = SystemInfoCollector()

# Get recommendation
system_info = collector.collect()
rec = recommender.recommend(system_info)

print(f"Use: {rec.model_id} with batch_size={rec.batch_size}")
```

### Enable Production Metrics

```python
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.production_ingestor import ProductionMetricsIngestor

# Initialize with enabled=True (OPT-IN)
db = BenchmarkDatabase(Path("data/benchmarks/production.db"))
ingestor = ProductionMetricsIngestor(db, enabled=True)

# Use with TranslationEngine
# (pass ingestor to engine constructor)
```

## Common Tasks

### Compare Two Models

```python
# Run benchmarks for both models, then compare
comparison = db.compare_runs(
    run_ids=["run_001", "run_002"],
    metric="throughput_tokens_per_sec"
)
```

### Archive Old Runs

```python
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=90)).isoformat()
runs = db.list_runs(limit=1000)
for run_id, model_id, device, timestamp, count in runs:
    if timestamp < cutoff:
        run = db.get_run(run_id)
        # Export and delete
```

### Check Database Health

```python
conn = db._get_conn()
result = conn.execute("PRAGMA integrity_check").fetchone()[0]
print("Health:", result)  # Should be "ok"
```

## Troubleshooting

### Database Locked

```python
# Force WAL checkpoint
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
```

### Slow Queries

```python
# Analyze tables
conn.execute("ANALYZE")

# Check index usage
cursor = conn.execute("EXPLAIN QUERY PLAN SELECT ...")
```

### Memory Leak

```python
# Verify bounded metrics
from src.translation_engine.engine import TranslationEngine
engine = TranslationEngine(...)
assert isinstance(engine._timing_metrics["translation_duration_ms"], deque)
```

See full documentation:
- [Benchmarking Features](../features/benchmarking.md)
- [Benchmarking Operations](../operations/benchmarking-operations.md)
- [Benchmarking API](../api/benchmarking-api.md)
