# Content Hash Tracking Metrics

## Overview

Content hash tracking provides Prometheus metrics to monitor file change detection performance, cache efficiency, and multi-worker coordination health.

## Metrics Reference

### Histograms

#### `content_hash_compute_duration_seconds`
**Type**: Histogram
**Unit**: Seconds
**Description**: Time to compute file content hash (MD5/SHA256)
**Labels**: `worker_id`
**Buckets**: `[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0]`

**Interpretation**:
- **p50 < 10ms**: Good (typical for small markdown files with MD5)
- **p95 < 50ms**: Acceptable
- **p95 > 100ms**: Investigate (large files or slow disk I/O)

**Optimization**:
- If p95 is high, check:
  - File sizes (consider sampling for very large files)
  - Disk I/O performance
  - Hash algorithm (MD5 vs SHA256 - MD5 is ~3x faster)

---

#### `metadata_save_duration_seconds`
**Type**: Histogram
**Unit**: Seconds
**Description**: Duration to save metadata file (including lock acquisition)
**Labels**: `worker_id`
**Buckets**: `[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0]`

**Interpretation**:
- **p50 < 100ms**: Good
- **p95 < 500ms**: Acceptable
- **p95 > 1s**: Investigate (Redis lock contention or slow disk)

**Optimization**:
- High p95 may indicate:
  - Multi-worker lock contention (check `metadata_lock_acquire_duration_seconds`)
  - Large metadata file (check `metadata_file_size_bytes`)
  - Slow disk writes (check I/O metrics)

---

#### `metadata_lock_acquire_duration_seconds`
**Type**: Histogram
**Unit**: Seconds
**Description**: Duration to acquire Redis distributed lock for metadata
**Labels**: `worker_id`
**Buckets**: `[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0]`

**Interpretation**:
- **p50 < 10ms**: Good (low contention)
- **p95 < 100ms**: Acceptable (moderate contention)
- **p95 > 1s**: High contention (many workers competing)

**Optimization**:
- High lock acquisition time indicates:
  - Too many workers writing simultaneously
  - Slow metadata saves (holding lock too long)
  - Consider reducing worker count or batching writes

---

### Counters

#### `content_hash_cache_hits`
**Type**: Counter
**Unit**: Count
**Description**: Number of content hash cache hits (mtime unchanged, fast path)
**Labels**: `worker_id`

**Interpretation**:
- High cache hit rate (>90%) is desirable
- Indicates effective mtime-based fast path

---

#### `content_hash_cache_misses`
**Type**: Counter
**Unit**: Count
**Description**: Number of content hash cache misses (mtime changed, recompute hash)
**Labels**: `worker_id`

**Interpretation**:
- Cache misses require expensive hash computation
- Expected when files are actually modified
- Unexpected high misses may indicate:
  - Filesystem updates mtime without content changes
  - Clock synchronization issues
  - Build tools touching files

---

#### `content_hash_changes_detected`
**Type**: Counter
**Unit**: Count
**Description**: Number of file changes detected via content hash
**Labels**: `worker_id`

**Interpretation**:
- Tracks actual content changes (true positives)
- Compare with `content_hash_no_change` to understand change rate

---

#### `content_hash_no_change`
**Type**: Counter
**Unit**: Count
**Description**: Number of files with no content change detected
**Labels**: `worker_id`

**Interpretation**:
- Tracks files checked but unchanged
- High ratio (no_change / total) indicates efficient change detection

---

#### `metadata_lock_timeouts`
**Type**: Counter
**Unit**: Count
**Description**: Number of Redis lock timeouts (fell back to direct write)
**Labels**: `worker_id`

**Interpretation**:
- **0 timeouts**: Healthy multi-worker coordination
- **>0 timeouts**: Warning - lock contention or Redis issues
- Timeouts cause fallback to uncoordinated writes (risk of data loss)

**Action**:
- If timeouts occur:
  - Increase `redis_lock_timeout` in config (default: 30s)
  - Reduce number of concurrent workers
  - Investigate Redis performance

---

### Gauges

#### `metadata_file_size_bytes`
**Type**: Gauge
**Unit**: Bytes
**Description**: Current metadata file size in bytes
**Labels**: `worker_id`

**Interpretation**:
- **<1 MB**: Small project (<1000 files)
- **1-10 MB**: Medium project (1000-10000 files)
- **>10 MB**: Large project (>10000 files)

**Optimization**:
- Large metadata files may slow down saves
- Consider CHH-05 (automatic cleanup) to remove stale entries

---

#### `metadata_tracked_files`
**Type**: Gauge
**Unit**: Count
**Description**: Number of source files tracked in metadata
**Labels**: `worker_id`

**Interpretation**:
- Tracks metadata growth over time
- Should stabilize once all source files processed

---

## Grafana Dashboard

### Installation

1. Copy dashboard JSON to Grafana provisioning:
   ```bash
   cp docker/grafana/dashboards/content-hash-tracking.json \
      docker/grafana/provisioning/dashboards/
   ```

2. Restart Grafana:
   ```bash
   docker-compose restart grafana
   ```

3. Access dashboard:
   - URL: http://localhost:3100/dashboards
   - Search: "Content Hash Tracking"

### Dashboard Panels

1. **Hash Computation Duration**: p50 and p95 hash computation times
2. **Cache Hit Rate**: Percentage of mtime fast-path hits
3. **Metadata Save Duration**: p50 and p95 save times (including locks)
4. **Lock Acquisition Duration**: Redis lock acquisition times
5. **Change Detection Rate**: Files with/without changes over time
6. **Metadata File Size**: Current metadata file size trend
7. **Tracked Files Count**: Total files in metadata
8. **Lock Timeouts**: Alert panel (red when >0)
9. **Total Operations**: Sum of all change detection operations

### Alert Rules

Create alerts in Prometheus for production monitoring:

```yaml
# docker/prometheus/alert_rules.yml

groups:
  - name: content_hash_tracking
    interval: 30s
    rules:
      - alert: HighLockTimeoutRate
        expr: rate(metadata_lock_timeouts[5m]) > 0.01
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High Redis lock timeout rate"
          description: "Worker {{$labels.worker_id}} experiencing lock timeouts ({{$value}} timeouts/sec)"

      - alert: SlowHashComputation
        expr: histogram_quantile(0.95, rate(content_hash_compute_duration_seconds_bucket[5m])) > 0.1
        for: 10m
        labels:
          severity: warning
        annotations:
          summary: "Slow content hash computation"
          description: "p95 hash computation time {{$value}}s (threshold: 0.1s)"

      - alert: HighLockContention
        expr: histogram_quantile(0.95, rate(metadata_lock_acquire_duration_seconds_bucket[5m])) > 1.0
        for: 5m
        labels:
          severity: warning
        annotations:
          summary: "High Redis lock contention"
          description: "p95 lock acquisition time {{$value}}s (threshold: 1s)"

      - alert: LargeMetadataFile
        expr: metadata_file_size_bytes > 10485760
        for: 15m
        labels:
          severity: info
        annotations:
          summary: "Large metadata file"
          description: "Metadata file size {{$value}} bytes (>10MB) - consider cleanup"
```

## PromQL Query Examples

### Cache Hit Rate
```promql
# Overall cache hit rate (last 5 minutes)
rate(content_hash_cache_hits[5m]) /
(rate(content_hash_cache_hits[5m]) + rate(content_hash_cache_misses[5m]))
```

### Average Hash Computation Time
```promql
# Average hash computation time per worker
rate(content_hash_compute_duration_seconds_sum[5m]) /
rate(content_hash_compute_duration_seconds_count[5m])
```

### Lock Contention Ratio
```promql
# Percentage of time spent waiting for locks
rate(metadata_lock_acquire_duration_seconds_sum[5m]) /
rate(metadata_save_duration_seconds_sum[5m])
```

### File Change Rate
```promql
# Percentage of files that changed (last hour)
sum(increase(content_hash_changes_detected[1h])) /
(sum(increase(content_hash_changes_detected[1h])) + sum(increase(content_hash_no_change[1h])))
```

## Troubleshooting

### High Hash Computation Times

**Symptom**: `content_hash_compute_duration_seconds` p95 > 100ms

**Causes**:
- Large files (>10MB markdown files)
- Slow disk I/O
- SHA256 algorithm (slower than MD5)

**Solutions**:
1. Check file size distribution:
   ```bash
   find content/ -name "*.md" -exec du -h {} \; | sort -rh | head -20
   ```

2. Switch to MD5 if security isn't critical:
   ```yaml
   # config/global.yaml
   content_hash_tracking:
     hash_algorithm: "md5"  # ~3x faster than SHA256
   ```

3. Profile disk I/O:
   ```bash
   iostat -x 1 10
   ```

---

### Low Cache Hit Rate

**Symptom**: Cache hit rate < 80%

**Causes**:
- Frequent file modifications
- Build tools touching files without content changes
- Filesystem timestamp precision issues

**Solutions**:
1. Investigate which files are triggering misses:
   ```bash
   grep "content changed\|mtime changed" logs/translation.log | cut -d' ' -f5 | sort | uniq -c | sort -rn
   ```

2. Check for spurious mtime updates:
   ```bash
   # Git operations that touch files
   git log --since="1 hour ago" --stat
   ```

---

### Lock Timeouts

**Symptom**: `metadata_lock_timeouts` > 0

**Causes**:
- Too many concurrent workers
- Redis connection issues
- Slow metadata saves (holding lock too long)

**Solutions**:
1. Increase lock timeout:
   ```yaml
   # config/global.yaml
   content_hash_tracking:
     redis_lock_timeout: 60  # Increase from 30s to 60s
   ```

2. Reduce worker count:
   ```bash
   # docker-compose.yml
   # Comment out extra workers
   ```

3. Check Redis health:
   ```bash
   docker exec hugo-translator-redis redis-cli INFO stats
   docker exec hugo-translator-redis redis-cli SLOWLOG GET 10
   ```

---

### Large Metadata File

**Symptom**: `metadata_file_size_bytes` > 10MB

**Causes**:
- Many source files tracked
- Old entries not cleaned up

**Solutions**:
1. Implement CHH-05 (automatic cleanup):
   - Removes entries for deleted source files
   - Archives old translations

2. Manual cleanup:
   ```bash
   # Backup first
   docker exec hugo-translator-orchestrator \
     cp /data/metadata/.translation_metadata.json \
        /data/metadata/.translation_metadata.json.backup

   # Rebuild (will recreate from scratch)
   docker exec hugo-translator-orchestrator \
     rm /data/metadata/.translation_metadata.json
   ```

## Integration with Existing Metrics

Content hash metrics complement existing translation metrics:

| Metric Family | Purpose |
|---------------|---------|
| `translations_*` | Overall translation success/failure rates |
| `tm_*` | Translation Memory cache performance |
| `content_hash_*` | File change detection efficiency |
| `metadata_*` | Multi-worker coordination health |

### Combined Queries

**Effective Change Detection Rate**:
```promql
# True positives: changed files that triggered retranslation
(rate(content_hash_changes_detected[5m]) * rate(translations_total[5m])) /
rate(content_hash_changes_detected[5m])
```

**Wasted Hash Computations**:
```promql
# Files hashed but unchanged (cache misses with no change)
rate(content_hash_cache_misses[5m]) - rate(content_hash_changes_detected[5m])
```

## References

- [Prometheus Best Practices](https://prometheus.io/docs/practices/)
- [Grafana Dashboard Guide](https://grafana.com/docs/grafana/latest/dashboards/)
- [Content Hash Tracking Architecture](../architecture/content-hash-tracking.md)
- [Docker Volume Management](../deployment/docker.md)
