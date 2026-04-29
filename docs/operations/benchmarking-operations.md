# Benchmarking Operations Guide

**Last Updated**: 2025-12-24
**Status**: Production-Ready
**Audience**: Site Operators, SREs

## Table of Contents

- [Overview](#overview)
- [Enabling Production Metrics](#enabling-production-metrics)
- [Database Maintenance](#database-maintenance)
- [Performance Tuning](#performance-tuning)
- [Monitoring and Metrics](#monitoring-and-metrics)
- [Troubleshooting](#troubleshooting)
- [Capacity Planning](#capacity-planning)
- [Backup and Recovery](#backup-and-recovery)

## Overview

This guide covers operational aspects of the benchmarking system including database maintenance, performance tuning, monitoring, and troubleshooting. Follow these procedures to ensure reliable benchmarking in production environments.

### Operational Modes

The benchmarking system supports three operational modes:

1. **Development Mode**: Interactive benchmarking for model evaluation
2. **Production Monitoring Mode**: OPT-IN metrics collection from live translations
3. **Offline Analysis Mode**: Query historical data for recommendations

## Enabling Production Metrics

### Prerequisites

- Benchmark database initialized
- Sufficient disk space (see [Capacity Planning](#capacity-planning))
- Write permissions to database directory

### Enable via Code

```python
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase
from src.benchmarking.production_ingestor import ProductionMetricsIngestor

# Initialize database
db_path = Path("data/benchmarks/production.db")
db = BenchmarkDatabase(db_path)

# Enable production metrics (OPT-IN)
ingestor = ProductionMetricsIngestor(db, enabled=True)

# Integrate with TranslationEngine
from src.translation_engine.engine import TranslationEngine

engine = TranslationEngine(
    model=model,
    tm=tm,
    production_metrics_ingestor=ingestor,  # Pass enabled ingestor
)
```

### Enable via Configuration

```yaml
# config/benchmarking.yaml
production_metrics:
  enabled: true  # Default: false (OPT-IN)
  database_path: "data/benchmarks/production.db"
  flush_interval_seconds: 60  # Flush to disk every 60s
```

### Verify Production Metrics

```bash
# Check if metrics are being recorded
python -c "
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase

db = BenchmarkDatabase(Path('data/benchmarks/production.db'))
runs = db.list_runs(purpose='production', limit=10)
print(f'Production runs recorded: {len(runs)}')
"
```

### Disable Production Metrics

```python
# Set enabled=False (default)
ingestor = ProductionMetricsIngestor(db, enabled=False)

# Or simply don't pass ingestor to TranslationEngine
engine = TranslationEngine(model=model, tm=tm)  # No production metrics
```

## Database Maintenance

### Daily Maintenance

#### Check Database Size

```bash
# Check database file size
ls -lh data/benchmarks/benchmarks.db

# Check WAL file size (should be <1MB typically)
ls -lh data/benchmarks/benchmarks.db-wal
```

#### WAL Checkpoint

WAL files should be checkpointed regularly to merge changes back to main database:

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
conn = db._get_conn()

# Force checkpoint
conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
print("WAL checkpoint completed")
```

**Schedule**: Run daily or when WAL file > 10MB.

#### Vacuum Database

Reclaim unused space after deleting old runs:

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
conn = db._get_conn()

# Vacuum to reclaim space
conn.execute("VACUUM")
print("Database vacuumed")
```

**Schedule**: Run weekly or after bulk deletions.

#### Verify Integrity

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
conn = db._get_conn()

# Run integrity check
result = conn.execute("PRAGMA integrity_check").fetchone()[0]
if result == "ok":
    print("✓ Database integrity verified")
else:
    print(f"✗ Integrity check failed: {result}")
    # See Troubleshooting section
```

**Schedule**: Run daily as part of health check.

### Weekly Maintenance

#### Analyze Query Performance

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
conn = db._get_conn()

# Analyze tables
conn.execute("ANALYZE")
print("Database statistics updated")
```

**Schedule**: Run weekly to update query optimizer statistics.

#### Archive Old Runs

```python
from datetime import datetime, timedelta
from pathlib import Path
from src.benchmarking.storage import BenchmarkDatabase

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))

# Archive runs older than 90 days
cutoff_date = (datetime.now() - timedelta(days=90)).isoformat()

runs = db.list_runs(limit=10000)
archived_count = 0

for run_id, model_id, device, timestamp, count in runs:
    if timestamp < cutoff_date:
        # Export to archive
        run = db.get_run(run_id)
        archive_path = Path(f"archives/benchmarks/{run_id}.json")
        archive_path.parent.mkdir(parents=True, exist_ok=True)
        archive_path.write_text(json.dumps(run.to_dict(), indent=2))

        # Delete from database
        db._get_conn().execute("DELETE FROM benchmark_runs WHERE run_id = ?", (run_id,))
        archived_count += 1

print(f"Archived {archived_count} runs")
```

**Schedule**: Run weekly or when database > 1GB.

### Monthly Maintenance

#### Full Backup

See [Backup and Recovery](#backup-and-recovery) section.

#### Review Disk Usage Trends

```bash
# Track database growth over time
du -sh data/benchmarks/benchmarks.db >> logs/db_size_history.log

# Plot growth (if gnuplot available)
gnuplot -e "plot 'logs/db_size_history.log' using 1:2 with lines"
```

## Performance Tuning

### Database Configuration

#### Optimize WAL Settings

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
conn = db._get_conn()

# Tune WAL parameters
conn.execute("PRAGMA wal_autocheckpoint=1000")  # Checkpoint every 1000 pages
conn.execute("PRAGMA journal_size_limit=10485760")  # Max WAL size: 10MB
conn.execute("PRAGMA synchronous=NORMAL")  # Balance safety/performance
```

**Impact**:
- `wal_autocheckpoint`: Lower = more frequent checkpoints (slower writes, smaller WAL)
- `journal_size_limit`: Caps WAL file size
- `synchronous=NORMAL`: Faster writes, slight risk if power loss

#### Optimize Memory Usage

```python
conn.execute("PRAGMA cache_size=-64000")  # 64MB cache (negative = KB)
conn.execute("PRAGMA temp_store=MEMORY")  # Use RAM for temp tables
conn.execute("PRAGMA mmap_size=268435456")  # 256MB memory-mapped I/O
```

**Impact**:
- Larger cache = faster queries, more memory usage
- `temp_store=MEMORY` = faster temp operations
- `mmap_size` = faster reads via memory mapping

### Query Optimization

#### Add Indexes for Common Queries

```sql
-- Index for similarity queries (by hardware)
CREATE INDEX IF NOT EXISTS idx_system_info_cpu_ram
    ON system_info(cpu_cores, total_ram_gb);

-- Index for time-range queries
CREATE INDEX IF NOT EXISTS idx_runs_timestamp_purpose
    ON benchmark_runs(timestamp_utc, purpose);

-- Index for model comparisons
CREATE INDEX IF NOT EXISTS idx_results_model_batch
    ON benchmark_results(model_id, batch_size);
```

#### Explain Query Plans

```python
# Check if query uses indexes
cursor = conn.execute("EXPLAIN QUERY PLAN SELECT * FROM benchmark_runs WHERE model_id = ?", ("facebook/m2m100_418M",))
for row in cursor:
    print(row)

# Should show "USING INDEX idx_runs_model"
```

### Metrics Configuration Tuning

Adjust timing metrics storage limits based on workload using `config/metrics.yaml` or environment variables.

See [Metrics Configuration](../configuration/metrics.md) for complete documentation.

#### Using Configuration File

Edit `config/metrics.yaml`:

```yaml
metrics:
  storage:
    translation_engine:
      retry_metrics_maxlen: 2000  # Increase for better p99 accuracy

    l3_semantic:
      timing_metrics_maxlen: 20000  # Increase for high-traffic production

    batch_optimizer:
      timing_metrics_maxlen: 10000  # Increase for large batch jobs
```

#### Using Environment Variables

Override at runtime without editing files:

```bash
# Low-memory environment
export METRICS_ENGINE_MAXLEN=500
export METRICS_L3_MAXLEN=5000
export METRICS_BATCH_MAXLEN=2500

# High-traffic production
export METRICS_ENGINE_MAXLEN=2000
export METRICS_L3_MAXLEN=20000
export METRICS_BATCH_MAXLEN=10000

python -m src.benchmarking.cli run --corpus production ...
```

**Trade-offs**:
- **Higher limits**: Better statistical accuracy (especially p95/p99), more memory usage
- **Lower limits**: Lower memory footprint, less historical data
- **Defaults (1000/10000/5000)**: Balanced for typical workloads

**Memory Impact**:
- Each 1000 samples ≈ 8KB memory per metric
- TranslationEngine (2 metrics): 2000 samples = 16KB
- L3SemanticTM (3 metrics): 10000 samples = 240KB
- BatchOptimizer (4 metrics): 5000 samples = 160KB

**Recommendations**:
- **Development/Testing**: Use lower limits (100-1000) for minimal overhead
- **Production (typical)**: Use defaults (1000/10000/5000)
- **Production (high-traffic)**: Increase L3 to 20000+ for better p99
- **Production (low-memory)**: Decrease all to 500/5000/2500

## Monitoring and Metrics

### Key Metrics to Monitor

#### Database Health

```python
from src.benchmarking.storage import BenchmarkDatabase
from pathlib import Path

db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))
conn = db._get_conn()

# Database size
db_size_mb = Path("data/benchmarks/benchmarks.db").stat().st_size / (1024 * 1024)

# WAL size
wal_path = Path("data/benchmarks/benchmarks.db-wal")
wal_size_mb = wal_path.stat().st_size / (1024 * 1024) if wal_path.exists() else 0

# Total runs
total_runs = conn.execute("SELECT COUNT(*) FROM benchmark_runs").fetchone()[0]

# Recent runs (last 24h)
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(hours=24)).isoformat()
recent_runs = conn.execute(
    "SELECT COUNT(*) FROM benchmark_runs WHERE timestamp_utc > ?",
    (cutoff,)
).fetchone()[0]

print(f"Database size: {db_size_mb:.1f} MB")
print(f"WAL size: {wal_size_mb:.1f} MB")
print(f"Total runs: {total_runs}")
print(f"Recent runs (24h): {recent_runs}")
```

#### Production Metrics Ingestion

```python
# Monitor production metrics recording
production_runs = db.list_runs(purpose="production", limit=1000)
print(f"Production runs: {len(production_runs)}")

# Check for recent activity
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(hours=1)).isoformat()
recent_production = [
    r for r in production_runs
    if r[3] > cutoff  # r[3] is timestamp
]
print(f"Production runs (last hour): {len(recent_production)}")
```

#### Performance Metrics

```python
# Average query latency (sample)
import time

start = time.perf_counter()
runs = db.list_runs(limit=100)
query_latency_ms = (time.perf_counter() - start) * 1000
print(f"list_runs(100) latency: {query_latency_ms:.1f} ms")

# Get run latency
start = time.perf_counter()
run = db.get_run(runs[0][0])
get_latency_ms = (time.perf_counter() - start) * 1000
print(f"get_run() latency: {get_latency_ms:.1f} ms")
```

### Alerting Thresholds

Set up alerts for these conditions:

| Metric | Warning | Critical | Action |
|--------|---------|----------|--------|
| Database size | > 1GB | > 5GB | Archive old runs |
| WAL size | > 10MB | > 50MB | Force checkpoint |
| Query latency | > 100ms | > 500ms | Analyze queries, add indexes |
| Recent runs | 0 in 24h | 0 in 72h | Check production metrics enabled |
| Integrity check | Not "ok" | N/A | Restore from backup |

### Prometheus Metrics Export

```python
# Export metrics for Prometheus
from prometheus_client import Gauge, Counter, Histogram
import time

# Define metrics
benchmark_runs_total = Counter('benchmark_runs_total', 'Total benchmark runs')
benchmark_db_size_bytes = Gauge('benchmark_db_size_bytes', 'Database size in bytes')
benchmark_query_latency_seconds = Histogram('benchmark_query_latency_seconds', 'Query latency')

# Update metrics
def update_metrics():
    db = BenchmarkDatabase(Path("data/benchmarks/benchmarks.db"))

    # Total runs
    total = db._get_conn().execute("SELECT COUNT(*) FROM benchmark_runs").fetchone()[0]
    benchmark_runs_total.inc(total)

    # Database size
    db_size = Path("data/benchmarks/benchmarks.db").stat().st_size
    benchmark_db_size_bytes.set(db_size)

    # Query latency
    start = time.perf_counter()
    db.list_runs(limit=100)
    latency = time.perf_counter() - start
    benchmark_query_latency_seconds.observe(latency)

# Call periodically (e.g., every 60s)
while True:
    update_metrics()
    time.sleep(60)
```

## Troubleshooting

### Issue: Database Locked Errors

**Symptom**:
```
sqlite3.OperationalError: database is locked
```

**Diagnosis**:
```python
# Check for long-running transactions
conn.execute("PRAGMA wal_checkpoint(PASSIVE)")

# Check if WAL mode is enabled
result = conn.execute("PRAGMA journal_mode").fetchone()[0]
print(f"Journal mode: {result}")  # Should be "wal"
```

**Solutions**:

1. **Ensure WAL mode is enabled**:
```python
conn.execute("PRAGMA journal_mode=WAL")
```

2. **Increase busy timeout**:
```python
conn.execute("PRAGMA busy_timeout=60000")  # 60 seconds
```

3. **Check for hung processes**:
```bash
# Linux: Check for processes with open file handles
lsof | grep benchmarks.db

# Windows: Use Process Explorer to find processes with open handles
```

### Issue: Slow Queries

**Symptom**: Queries taking >100ms.

**Diagnosis**:
```python
# Enable query logging
conn.execute("PRAGMA query_only=1")

# Explain query plan
cursor = conn.execute("EXPLAIN QUERY PLAN SELECT * FROM benchmark_runs WHERE model_id = ?", ("facebook/m2m100_418M",))
for row in cursor:
    print(row)
```

**Solutions**:

1. **Add missing indexes** (see [Query Optimization](#query-optimization))

2. **Analyze tables**:
```python
conn.execute("ANALYZE")
```

3. **Reduce query scope**:
```python
# Instead of querying all runs
runs = db.list_runs(limit=10000)  # Returns 10K runs

# Limit to recent runs
from datetime import datetime, timedelta
cutoff = (datetime.now() - timedelta(days=30)).isoformat()
runs = db.list_runs(limit=1000)  # Smaller limit
runs = [r for r in runs if r[3] > cutoff]  # Filter by timestamp
```

### Issue: Memory Leak in Production

**Symptom**: Memory usage grows unbounded over time.

**Diagnosis**:
```python
import sys

# Check if using bounded deque
from src.translation_engine.engine import TranslationEngine

engine = TranslationEngine(...)
metrics = engine._timing_metrics

for key, value in metrics.items():
    print(f"{key}: type={type(value)}, len={len(value)}")
    if isinstance(value, deque):
        print(f"  maxlen={value.maxlen}")
    elif isinstance(value, list):
        print(f"  ⚠️ Unbounded list detected!")
        print(f"  Memory: {sys.getsizeof(value) / 1024:.1f} KB")
```

**Solutions**:

1. **Verify bounded deque usage** (BM-07 fix):
```python
# Should be deque with maxlen
from collections import deque
assert isinstance(engine._timing_metrics["translation_duration_ms"], deque)
assert engine._timing_metrics["translation_duration_ms"].maxlen is not None
```

2. **Update to latest code** with bounded metrics fix.

### Issue: Corrupted Database

**Symptom**: `PRAGMA integrity_check` returns errors.

**Diagnosis**:
```python
result = conn.execute("PRAGMA integrity_check").fetchone()[0]
if result != "ok":
    print(f"Corruption detected: {result}")

    # Try quick check
    quick_result = conn.execute("PRAGMA quick_check").fetchone()[0]
    print(f"Quick check: {quick_result}")
```

**Solutions**:

1. **Attempt recovery via dump/restore**:
```bash
# Dump to SQL
sqlite3 benchmarks.db .dump > backup.sql

# Create new database
mv benchmarks.db benchmarks.db.corrupted
sqlite3 benchmarks_new.db < backup.sql

# Verify new database
sqlite3 benchmarks_new.db "PRAGMA integrity_check"

# If OK, replace
mv benchmarks_new.db benchmarks.db
```

2. **Restore from backup** (see [Backup and Recovery](#backup-and-recovery))

### Issue: PII Leakage in System Info

**Symptom**: Usernames visible in stored paths.

**Diagnosis**:
```python
from src.benchmarking.system_info import SystemInfoCollector

collector = SystemInfoCollector()
info = collector.collect()

# Check for PII patterns
info_dict = info.to_dict()
info_json = json.dumps(info_dict)

# Should contain [HOME] or [USER], not actual usernames
if "/home/" in info_json and "[HOME]" not in info_json:
    print("⚠️ PII leakage detected: home directory not sanitized")

if "C:\\Users\\" in info_json and "[USER]" not in info_json:
    print("⚠️ PII leakage detected: Windows user directory not sanitized")
```

**Solutions**:

1. **Verify sanitization is working**:
```python
# Test sanitization
test_paths = [
    "/home/john.doe/projects/test",
    "C:\\Users\\Jane\\Documents\\test",
    "/Users/alice/work/test",
]

for path in test_paths:
    sanitized = collector.sanitize_path(path)
    print(f"{path} → {sanitized}")
    assert "[HOME]" in sanitized or "[USER]" in sanitized
```

2. **Update to latest SystemInfoCollector** with sanitization fix.

## Capacity Planning

### Storage Requirements

#### Database Size Growth

Typical storage per benchmark run:

| Component | Size per Run |
|-----------|-------------|
| benchmark_runs row | ~500 bytes |
| system_info row | ~1 KB |
| benchmark_results (100 samples) | ~10 KB |
| Indexes | ~20% overhead |
| **Total** | ~12 KB per run |

**Projected growth**:
- 100 runs: ~1.2 MB
- 1,000 runs: ~12 MB
- 10,000 runs: ~120 MB
- 100,000 runs: ~1.2 GB

#### WAL File Size

WAL files grow until checkpointed:
- Default checkpoint: Every 1000 pages (~4MB)
- Max WAL size: 10MB (configurable)

**Action**: Set up daily WAL checkpoints if running production metrics.

### Memory Requirements

| Component | Memory Usage |
|-----------|-------------|
| BenchmarkDatabase | ~10 MB baseline |
| SQLite cache (64MB) | ~64 MB |
| SystemInfoCollector | ~1 MB |
| ProductionMetricsIngestor | ~2 MB |
| ModelRecommender (100 cached runs) | ~15 MB |
| **Total** | ~100 MB typical |

### Disk I/O

| Operation | IOPS | Throughput |
|-----------|------|------------|
| save_run() | 10-20 IOPS | ~1 KB/op |
| list_runs(100) | 100-200 IOPS | ~1 MB/op |
| Checkpoint | 1000+ IOPS | ~10 MB/op |

**Recommendation**: Use SSD for database storage (10x faster than HDD).

### Scaling Recommendations

| Workload | Database Size | WAL Checkpoint | Archive Policy |
|----------|---------------|----------------|----------------|
| Dev/Test | < 100 MB | Weekly | Keep all runs |
| Light Production | 100 MB - 1 GB | Daily | Archive > 90 days |
| Heavy Production | 1 GB - 5 GB | Hourly | Archive > 30 days |
| Enterprise | > 5 GB | Continuous | Archive > 7 days |

## Backup and Recovery

### Backup Strategy

#### Daily Backup (Hot Backup)

```bash
#!/bin/bash
# Daily hot backup (database can remain open)

DATE=$(date +%Y%m%d)
SOURCE="data/benchmarks/benchmarks.db"
BACKUP_DIR="backups/benchmarks"

mkdir -p "$BACKUP_DIR"

# Checkpoint WAL before backup
sqlite3 "$SOURCE" "PRAGMA wal_checkpoint(TRUNCATE)"

# Backup using SQLite .backup command (safe for open databases)
sqlite3 "$SOURCE" ".backup '$BACKUP_DIR/benchmarks_$DATE.db'"

# Compress
gzip "$BACKUP_DIR/benchmarks_$DATE.db"

# Verify
gunzip -c "$BACKUP_DIR/benchmarks_$DATE.db.gz" | sqlite3 :memory: "PRAGMA integrity_check"

echo "Backup completed: $BACKUP_DIR/benchmarks_$DATE.db.gz"
```

**Schedule**: Run daily via cron:
```cron
0 2 * * * /path/to/backup_benchmarks.sh
```

#### Weekly Full Backup (Cold Backup)

```bash
#!/bin/bash
# Weekly cold backup (stop all writers)

DATE=$(date +%Y%m%d)
SOURCE="data/benchmarks/benchmarks.db"
BACKUP_DIR="backups/benchmarks/weekly"

mkdir -p "$BACKUP_DIR"

# Stop any writers (e.g., stop application)
# systemctl stop translation-engine

# Copy all database files
cp "$SOURCE" "$BACKUP_DIR/benchmarks_$DATE.db"
cp "$SOURCE-wal" "$BACKUP_DIR/benchmarks_$DATE.db-wal" 2>/dev/null || true
cp "$SOURCE-shm" "$BACKUP_DIR/benchmarks_$DATE.db-shm" 2>/dev/null || true

# Restart application
# systemctl start translation-engine

# Compress
tar -czf "$BACKUP_DIR/benchmarks_$DATE.tar.gz" "$BACKUP_DIR/benchmarks_$DATE.db"*

# Verify
tar -xzf "$BACKUP_DIR/benchmarks_$DATE.tar.gz" -C /tmp
sqlite3 "/tmp/benchmarks_$DATE.db" "PRAGMA integrity_check"

echo "Weekly backup completed: $BACKUP_DIR/benchmarks_$DATE.tar.gz"
```

**Schedule**: Run weekly via cron:
```cron
0 3 * * 0 /path/to/backup_benchmarks_weekly.sh
```

### Retention Policy

| Backup Type | Retention | Storage |
|-------------|-----------|---------|
| Daily | 30 days | ~500 MB |
| Weekly | 12 weeks | ~2 GB |
| Monthly | 12 months | ~5 GB |

**Total storage**: ~8 GB for full retention.

### Recovery Procedures

#### Recover from Daily Backup

```bash
# Stop application
# systemctl stop translation-engine

# Restore from backup
DATE=20251224  # Replace with backup date
gunzip -c "backups/benchmarks/benchmarks_$DATE.db.gz" > data/benchmarks/benchmarks.db

# Verify integrity
sqlite3 data/benchmarks/benchmarks.db "PRAGMA integrity_check"

# Restart application
# systemctl start translation-engine

echo "Recovery completed from $DATE backup"
```

#### Point-in-Time Recovery

SQLite with WAL mode supports point-in-time recovery:

```bash
# 1. Restore latest backup
cp backups/benchmarks/benchmarks_latest.db data/benchmarks/benchmarks.db

# 2. Replay WAL transactions up to specific point
# (requires WAL archive - see SQLite WAL documentation)

# 3. Verify
sqlite3 data/benchmarks/benchmarks.db "PRAGMA integrity_check"
```

### Disaster Recovery

In case of catastrophic failure:

1. **Restore from latest backup** (see above)
2. **Re-run recent benchmarks** to recreate missing data
3. **Production metrics**: Lost data cannot be recovered (OPT-IN, no source)

**Prevention**:
- Store backups off-site (cloud storage, NAS)
- Test recovery procedures monthly
- Monitor backup success/failure

## See Also

- [Benchmarking Features](../features/benchmarking.md) - Feature overview
- [Benchmarking Architecture](../architecture/benchmarking-system.md) - Technical details
- [Benchmarking API Reference](../api/benchmarking-api.md) - API documentation
- [Benchmarking Runbook](../runbooks/benchmarking-runbook.md) - Quick reference

## Changelog

### 2025-12-24 - v1.0
- Initial operations guide
- Daily/weekly/monthly maintenance procedures
- Performance tuning recommendations
- Monitoring and alerting guidance
- Troubleshooting runbook
- Backup and recovery procedures
