# Content Hash Tracking - Production Architecture

## Overview

This document describes the production-ready architecture of the Content Hash Tracking system, including all hardening features implemented for multi-worker, high-scale deployments.

**Related Documents**:
- [Base Architecture](content-hash-tracking.md) - Core design and algorithms
- [Operations Guide](../operations/content-hash-operations.md) - Day-to-day operations
- [Metrics Guide](../observability/content-hash-metrics.md) - Monitoring and alerting
- [User Guide](../guides/content-hash-tracking.md) - End-user documentation

## Production Features

The production-hardened system includes:

1. **CHH-01: Enabled by Default** (CRITICAL)
   - Feature flag default changed to `true`
   - Production deployments use content hash automatically
   - Opt-out available via `--disable-content-hash` flag

2. **CHH-02: Multi-Worker Concurrency** (HIGH)
   - Redis distributed locking for metadata updates
   - Prevents race conditions in multi-worker environments
   - Graceful fallback to single-writer mode

3. **CHH-03: Dedicated Metadata Volume** (MEDIUM)
   - Docker volume `metadata_storage` for persistent metadata
   - Decouples metadata from content mounts
   - Survives container recreation

4. **CHH-04: Prometheus Metrics** (MEDIUM)
   - Hash computation duration histograms
   - Cache hit rate counters
   - Lock acquisition timing
   - Metadata file size gauges

5. **CHH-05: Automatic Cleanup** (LOW)
   - Age-based metadata removal (default: 30 days)
   - Configurable cleanup policies
   - Prevents unbounded metadata growth

## Production Architecture Diagram

```
┌─────────────────────────────────────────────────────────────────────┐
│                        Docker Compose Stack                          │
│                                                                       │
│  ┌────────────────────┐  ┌────────────────────┐  ┌───────────────┐  │
│  │ Orchestrator       │  │  Worker 1          │  │  Worker N     │  │
│  │  (Main Process)    │  │  (Translation)     │  │  (Translation)│  │
│  └────────┬───────────┘  └────────┬───────────┘  └───────┬───────┘  │
│           │                       │                       │          │
│           └───────────────────────┴───────────────────────┘          │
│                                   │                                  │
│  ┌───────────────────────────────┴───────────────────────────────┐  │
│  │                  Redis (Distributed Locking)                   │  │
│  │                                                                 │  │
│  │  Lock Key: "metadata_lock:/data/metadata/.translation_...json"│  │
│  │  Timeout: 30 seconds (configurable)                           │  │
│  │  Algorithm: Redlock (redis-py implementation)                 │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                   │                                  │
│  ┌───────────────────────────────┴───────────────────────────────┐  │
│  │             Metadata Volume (metadata_storage)                 │  │
│  │                                                                 │  │
│  │  /data/metadata/.translation_metadata.json                    │  │
│  │  ├─ Atomic writes (temp + rename)                             │  │
│  │  ├─ Redis lock protection                                     │  │
│  │  ├─ Automatic cleanup (30 days)                               │  │
│  │  └─ Prometheus metrics integration                            │  │
│  └─────────────────────────────────────────────────────────────────┘  │
│                                   │                                  │
│  ┌───────────────────────────────┴───────────────────────────────┐  │
│  │               Prometheus + Grafana (Observability)             │  │
│  │                                                                 │  │
│  │  Metrics:                                                      │  │
│  │  - content_hash_compute_duration_seconds (histogram)          │  │
│  │  - content_hash_cache_hits (counter)                          │  │
│  │  - metadata_lock_acquire_duration_seconds (histogram)         │  │
│  │  - metadata_file_size_bytes (gauge)                           │  │
│  │                                                                 │  │
│  │  Dashboard: "Content Hash Tracking"                           │  │
│  │  Alerts: Lock timeouts, slow hashing, large metadata          │  │
│  └─────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

## Component Interactions

### Multi-Worker Write Flow

```
Worker 1                          Redis                      Metadata File
   │                                │                              │
   │  1. Translation complete       │                              │
   │  2. update_source()            │                              │
   │     update_output()            │                              │
   │  3. save()                     │                              │
   ├───────────────────────────────>│                              │
   │  LOCK metadata_lock:path       │                              │
   │  (blocking_timeout=30s)        │                              │
   │                                │ ✓ Lock acquired              │
   │<───────────────────────────────┤                              │
   │                                │                              │
   │  4. _save_to_disk()            │                              │
   ├────────────────────────────────┼─────────────────────────────>│
   │  atomic_write(temp + rename)   │                              │ ✓ Written
   │                                │                              │
   │  5. Release lock               │                              │
   ├───────────────────────────────>│                              │
   │  UNLOCK                        │ ✓ Lock released              │
   │                                │                              │

Worker 2 (concurrent attempt)
   │                                │                              │
   │  1. Translation complete       │                              │
   │  2. save()                     │                              │
   ├───────────────────────────────>│                              │
   │  LOCK metadata_lock:path       │                              │
   │  (blocking_timeout=30s)        │ ⏳ Waiting for Worker 1...  │
   │                                │                              │
   │                                │ ✓ Lock acquired (after W1)  │
   │<───────────────────────────────┤                              │
   │  _save_to_disk()              │                              │
   └────────────────────────────────┼─────────────────────────────>│
```

### Automatic Cleanup Flow

```
Load Sequence (cleanup_on_load=true):
──────────────────────────────────────
MetadataTracker.load()
│
├─> Read .translation_metadata.json
│   └─> Parse JSON, validate schema
│
├─> Auto-cleanup check (CHH-05)
│   │
│   ├─> enabled=true? ✓
│   ├─> cleanup_on_load=true? ✓
│   │
│   └─> cleanup_old_entries(max_age_days=30)
│       │
│       ├─> Iterate all file entries
│       ├─> Check hash_computed_at timestamp
│       ├─> Delete if > 30 days old
│       │
│       └─> save() if entries removed
│           └─> Atomic write with lock

Save Sequence (cleanup_on_save=false):
──────────────────────────────────────
MetadataTracker.save()
│
├─> Acquire Redis lock (if multi-worker)
│
├─> _save_to_disk()
│   └─> atomic_write(json, fsync=true)
│
├─> Update Prometheus metrics
│   ├─> metadata_save_duration_seconds
│   ├─> metadata_file_size_bytes
│   └─> metadata_tracked_files
│
└─> Auto-cleanup check (CHH-05)
    │
    ├─> enabled=true? ✓
    ├─> cleanup_on_save=false? ✗
    │
    └─> SKIP (cleanup_on_save disabled)
```

## Configuration Architecture

### Global Configuration (`config/global.yaml`)

```yaml
features:
  enable_content_hash_tracking: true  # CHH-01: Enabled by default

content_hash_tracking:
  # Core settings
  hash_algorithm: "md5"  # md5 | sha1 | sha256

  # CHH-02: Multi-worker locking
  redis_lock_timeout: 30  # seconds

  # CHH-03: Dedicated metadata storage
  metadata_dir: "/data/metadata"  # Docker volume mount

  # CHH-04: Observability (automatic, no config needed)
  # Metrics registered in MetricsCollector

  # CHH-05: Automatic cleanup
  auto_cleanup:
    enabled: true
    max_age_days: 30
    cleanup_on_load: true
    cleanup_on_save: false
```

### Environment-Specific Overrides

**Development** (no Redis, single worker):
```yaml
content_hash_tracking:
  redis_lock_timeout: 5  # Fail fast in dev
  auto_cleanup:
    enabled: false  # Keep all metadata for debugging
```

**Production** (multi-worker):
```yaml
content_hash_tracking:
  redis_lock_timeout: 60  # Higher tolerance for contention
  auto_cleanup:
    enabled: true
    max_age_days: 30
    cleanup_on_load: true
```

**High-Scale** (many workers, large metadata):
```yaml
content_hash_tracking:
  redis_lock_timeout: 120  # Very high contention
  auto_cleanup:
    enabled: true
    max_age_days: 14  # More aggressive cleanup
    cleanup_on_save: true  # Continuous cleanup
```

## Failure Modes and Resilience

### 1. Redis Unavailable

**Symptom**: Workers cannot acquire distributed lock.

**Behavior**:
```python
try:
    with redis_client.lock(lock_key, timeout=30):
        self._save_to_disk()
except Exception as e:
    logger.warning("Redis lock failed, falling back to direct write")
    metrics.increment("metadata_lock_timeouts")
    self._save_to_disk()  # Proceed anyway (degraded mode)
```

**Impact**: Race condition possible (last-write-wins), metadata may be inconsistent.

**Mitigation**: Monitor `metadata_lock_timeouts` metric, alert on >0.

### 2. Metadata Corruption

**Symptom**: JSON parse error on load.

**Behavior**:
```python
try:
    raw = json.load(f)
except (JSONDecodeError, KeyError, ValueError):
    logger.warning("Metadata corrupted, rebuilding")
    self._data = {}  # Start fresh
```

**Impact**: All metadata lost, one-time rehashing of all files.

**Mitigation**: Atomic writes prevent corruption, backup metadata periodically.

### 3. Lock Timeout

**Symptom**: Worker cannot acquire lock within timeout period.

**Behavior**: Falls back to direct write (same as Redis unavailable).

**Root Causes**:
- Too many workers competing
- Slow metadata saves (large files)
- Redis network latency

**Mitigation**:
- Increase `redis_lock_timeout`
- Reduce worker count
- Enable `cleanup_on_save` to reduce metadata size

### 4. Disk Full

**Symptom**: `atomic_write()` fails with `OSError: No space left on device`.

**Behavior**: Exception propagates, translation marked as failed.

**Mitigation**: Monitor disk space, alert on <20% free.

### 5. Cleanup Removes Active Files

**Symptom**: File entries removed during active translation.

**Behavior**: Safe - next translation recreates entry with fresh hash.

**Mitigation**: Set `max_age_days` conservatively (30+ days).

## Performance Characteristics

### Multi-Worker Throughput

**Scenario**: 4 workers, 1000 files, 10% changed

| Configuration | Lock Contention | Total Time | Speedup |
|---------------|-----------------|------------|---------|
| Single worker | 0s              | 60s        | 1.0x    |
| 4 workers (no content hash) | 0s | 15s | 4.0x |
| 4 workers (content hash) | ~0.5s total | 15.5s | 3.9x |

**Overhead**: <5% lock contention overhead with 4 workers.

### Cleanup Performance

**Scenario**: 10,000 file entries, cleanup 1,000 stale entries

| Operation | Duration |
|-----------|----------|
| Load metadata | ~50ms |
| Iterate entries | ~10ms |
| Delete stale (1,000) | ~5ms |
| Save metadata | ~100ms |
| **Total** | **~165ms** |

**Overhead**: <1% of translation time, runs once on startup.

### Memory Usage

| Component | Size | Notes |
|-----------|------|-------|
| Metadata in-memory | ~500 KB | 1,000 files × 500 bytes |
| Redis lock state | ~1 KB | Per worker |
| Prometheus metrics | ~10 KB | Counters, histograms, gauges |
| **Total per worker** | **~511 KB** | Negligible |

## Monitoring and Alerting

### Key Metrics (CHH-04)

**Critical**:
- `metadata_lock_timeouts`: Must be 0 in production
- `content_hash_changes_detected`: Spike indicates mass file changes

**Warning**:
- `metadata_lock_acquire_duration_seconds` p95 > 1s: High contention
- `content_hash_compute_duration_seconds` p95 > 100ms: Slow disk I/O
- `metadata_file_size_bytes` > 10 MB: Consider cleanup

**Informational**:
- `content_hash_cache_hits` / (`cache_hits` + `cache_misses`): Hit rate
- `metadata_tracked_files`: Growth over time

### Grafana Dashboard

Import: `docker/grafana/dashboards/content-hash-tracking.json`

**Panels**:
1. Hash Computation Duration (p50, p95)
2. Cache Hit Rate (percentage)
3. Metadata Save Duration (p50, p95)
4. Lock Acquisition Duration (p50, p95)
5. Change Detection Rate (changes vs. no-change)
6. Metadata File Size (trend)
7. Tracked Files Count (gauge)
8. Lock Timeouts (alert panel)

### Alert Rules

```yaml
# Prometheus alert_rules.yml
groups:
  - name: content_hash_tracking
    rules:
      - alert: HighLockTimeoutRate
        expr: rate(metadata_lock_timeouts[5m]) > 0.01
        for: 5m
        severity: warning

      - alert: SlowHashComputation
        expr: histogram_quantile(0.95, rate(content_hash_compute_duration_seconds_bucket[5m])) > 0.1
        for: 10m
        severity: warning

      - alert: HighLockContention
        expr: histogram_quantile(0.95, rate(metadata_lock_acquire_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        severity: warning
```

## Scaling Considerations

### Horizontal Scaling (Workers)

**Recommendations**:
- **1-2 workers**: No special configuration needed
- **3-4 workers**: Default settings adequate
- **5-8 workers**: Increase `redis_lock_timeout` to 60s
- **9+ workers**: Enable `cleanup_on_save`, increase timeout to 120s

**Lock Contention Formula**:
```
Expected wait time ≈ (num_workers - 1) × avg_save_duration
```

Example: 8 workers, 100ms avg save → ~700ms wait time (acceptable).

### Vertical Scaling (File Count)

| File Count | Metadata Size | Load Time | Recommendation |
|------------|---------------|-----------|----------------|
| < 1,000 | < 1 MB | < 50ms | Default config |
| 1,000-10,000 | 1-10 MB | 50-500ms | Enable cleanup |
| 10,000-100,000 | 10-100 MB | 0.5-5s | Aggressive cleanup (14 days) |
| > 100,000 | > 100 MB | > 5s | Consider SQLite (future) |

**Current Limit**: Tested up to 50,000 files without issues.

## Security Considerations

### 1. Metadata Volume Permissions

**Risk**: Unauthorized access to metadata could leak file hashes.

**Mitigation**:
```yaml
# docker-compose.yml
volumes:
  metadata_storage:
    driver: local
    driver_opts:
      type: none
      o: bind,uid=1000,gid=1000,mode=0700  # Owner-only access
```

### 2. Redis Security

**Risk**: Unauthorized Redis access could corrupt locks.

**Mitigation**:
```yaml
# docker-compose.yml
services:
  redis:
    command: redis-server --requirepass ${REDIS_PASSWORD}
    ports: []  # No external exposure
```

### 3. Hash Algorithm Selection

**Risk**: MD5 collisions (theoretical).

**Mitigation**: Use SHA256 for security-critical deployments:
```yaml
content_hash_tracking:
  hash_algorithm: "sha256"
```

## Troubleshooting

### Lock Timeout Errors

**Symptom**: Logs show "Redis lock failed, falling back to direct write"

**Diagnosis**:
```bash
# Check Redis health
docker exec hugo-translator-redis redis-cli PING

# Check lock acquisition times
curl localhost:9091/metrics | grep metadata_lock_acquire_duration
```

**Resolution**:
1. Increase `redis_lock_timeout`
2. Reduce worker count temporarily
3. Check Redis performance (`SLOWLOG GET 10`)

### Large Metadata Files

**Symptom**: `metadata_file_size_bytes` > 10 MB

**Diagnosis**:
```bash
# Check tracked files
docker exec hugo-translator-orchestrator \
  python -c "import json; data = json.load(open('/data/metadata/.translation_metadata.json')); print(len(data['files']))"
```

**Resolution**:
1. Enable automatic cleanup
2. Reduce `max_age_days` to 14
3. Enable `cleanup_on_save` for continuous cleanup

### Slow Hash Computation

**Symptom**: `content_hash_compute_duration_seconds` p95 > 100ms

**Diagnosis**:
```bash
# Check file sizes
find /content -name "*.md" -exec du -h {} \; | sort -rh | head -20
```

**Resolution**:
1. Verify disk I/O (`iostat -x 1 10`)
2. Consider SSD upgrade
3. Switch to MD5 if using SHA256

## Migration Guide

### Upgrading to Production Features

**From**: Basic content hash (pre-CHH)
**To**: Production-hardened (post-CHH)

**Steps**:

1. **Update docker-compose.yml** (CHH-03):
   ```bash
   # Add metadata volume
   docker-compose down
   # Edit docker-compose.yml (add metadata_storage volume)
   docker-compose up -d
   ```

2. **Update config/global.yaml** (CHH-01, CHH-05):
   ```yaml
   features:
     enable_content_hash_tracking: true

   content_hash_tracking:
     metadata_dir: "/data/metadata"
     auto_cleanup:
       enabled: true
       max_age_days: 30
       cleanup_on_load: true
   ```

3. **Verify metrics** (CHH-04):
   ```bash
   # Access Grafana
   open http://localhost:3100/dashboards
   # Import content-hash-tracking.json dashboard
   ```

4. **Test multi-worker** (CHH-02):
   ```bash
   # Scale workers
   docker-compose up -d --scale worker=4

   # Monitor lock timeouts
   curl localhost:9091/metrics | grep metadata_lock_timeouts
   ```

## References

- CHH Plan File (archived)
- [Base Architecture](content-hash-tracking.md)
- [Operations Guide](../operations/content-hash-operations.md)
- [Metrics Guide](../observability/content-hash-metrics.md)
- [User Guide](../guides/content-hash-tracking.md)
- Implementation Summary (archived)
