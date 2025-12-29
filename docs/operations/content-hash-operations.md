# Content Hash Tracking - Operations Guide

## Overview

This guide covers day-to-day operations, monitoring, troubleshooting, and maintenance of the production content hash tracking system.

**Audience**: Site Reliability Engineers, DevOps, Production Support

**Related Documents**:
- [Architecture](../architecture/content-hash-production.md) - System design
- [Metrics Guide](../observability/content-hash-metrics.md) - Monitoring details
- [User Guide](../guides/content-hash-tracking.md) - End-user documentation

## Daily Operations

### Health Checks

**Morning Checklist** (5 minutes):

```bash
# 1. Check Grafana dashboard
open http://localhost:3100/d/content-hash-tracking

# 2. Verify no lock timeouts (should be 0)
curl -s localhost:9091/metrics | grep metadata_lock_timeouts

# 3. Check metadata file sizes
docker exec hugo-translator-orchestrator \
  find /data/metadata -name "*.json" -exec du -h {} \; | sort -rh

# 4. Verify Redis connectivity
docker exec hugo-translator-redis redis-cli PING
# Expected: PONG

# 5. Check recent errors
docker logs hugo-translator-orchestrator --since 24h | grep -i "metadata.*error"
```

**Expected Results**:
- ✅ Lock timeouts: 0
- ✅ Metadata files: < 10 MB each
- ✅ Redis: PONG
- ✅ No metadata errors in logs

### Monitoring Dashboards

**Primary Dashboard**: "Content Hash Tracking" (Grafana)

**Key Panels to Watch**:

1. **Lock Timeouts** (red = alert)
   - Normal: 0
   - Warning: > 0 (investigate immediately)

2. **Cache Hit Rate**
   - Normal: > 90%
   - Warning: < 80% (frequent file changes)

3. **Hash Computation Duration p95**
   - Normal: < 50ms
   - Warning: > 100ms (slow disk I/O)

4. **Metadata File Size**
   - Normal: < 10 MB
   - Warning: > 10 MB (enable cleanup)

### Log Monitoring

**Log Levels**:
- `INFO`: Normal operations (cleanup, hash updates)
- `WARNING`: Recoverable errors (corruption, lock failures)
- `ERROR`: Critical errors (I/O failures, Redis down)

**Key Log Patterns**:

```bash
# Monitor cleanup activity
docker logs hugo-translator-orchestrator | grep "Cleaned up.*stale metadata"
# Example: "Cleaned up 15 stale metadata entries (older than 30 days)"

# Monitor lock acquisition issues
docker logs hugo-translator-orchestrator | grep "Redis lock failed"
# Should be 0 in healthy system

# Monitor corruption recovery
docker logs hugo-translator-orchestrator | grep "Metadata corrupted, rebuilding"
# Occasional is OK, frequent indicates disk issues
```

## Routine Maintenance

### Weekly Tasks

**1. Metadata Cleanup Verification** (5 minutes)

```bash
# Check cleanup is running
docker logs hugo-translator-orchestrator --since 7d | \
  grep "Running automatic cleanup"

# Verify stale entries removed
docker logs hugo-translator-orchestrator --since 7d | \
  grep "Cleaned up.*stale metadata"

# If no cleanup logs, verify config
docker exec hugo-translator-orchestrator \
  python -c "
from src.utils.config_loader import get_global_config
config = get_global_config()
cleanup = config['content_hash_tracking']['auto_cleanup']
print(f'Cleanup enabled: {cleanup[\"enabled\"]}')
print(f'Max age days: {cleanup[\"max_age_days\"]}')
"
```

**2. Performance Review** (10 minutes)

```bash
# Hash computation trends (PromQL)
# Run in Grafana Explore:
histogram_quantile(0.95,
  rate(content_hash_compute_duration_seconds_bucket[7d])
)

# Lock acquisition trends
histogram_quantile(0.95,
  rate(metadata_lock_acquire_duration_seconds_bucket[7d])
)

# Identify performance regressions
# If p95 increased >50%, investigate disk I/O or file sizes
```

**3. Disk Usage Audit** (5 minutes)

```bash
# Check metadata volume usage
docker exec hugo-translator-orchestrator df -h /data/metadata

# Expected: < 100 MB for typical deployments
# If > 1 GB, consider more aggressive cleanup

# List largest metadata files
docker exec hugo-translator-orchestrator \
  find /data/metadata -name "*.json" -exec du -h {} \; | \
  sort -rh | head -10
```

### Monthly Tasks

**1. Metadata Backup** (10 minutes)

```bash
# Create backup directory
mkdir -p backups/metadata/$(date +%Y-%m)

# Backup all metadata files
docker cp hugo-translator-orchestrator:/data/metadata/. \
  backups/metadata/$(date +%Y-%m)/

# Verify backup
ls -lh backups/metadata/$(date +%Y-%m)/
```

**2. Configuration Review** (15 minutes)

```bash
# Review current config
docker exec hugo-translator-orchestrator cat /app/config/global.yaml | \
  grep -A 20 "content_hash_tracking"

# Compare with recommended settings (see table below)
```

**Recommended Settings by Deployment Size**:

| Deployment | Workers | Files | Recommended Config |
|-----------|---------|-------|-------------------|
| **Small** | 1-2 | < 1,000 | Default |
| **Medium** | 3-4 | 1,000-10,000 | `max_age_days: 30`, `cleanup_on_load: true` |
| **Large** | 5-8 | 10,000-50,000 | `max_age_days: 14`, `cleanup_on_load: true`, `redis_lock_timeout: 60` |
| **X-Large** | 9+ | > 50,000 | `max_age_days: 7`, `cleanup_on_save: true`, `redis_lock_timeout: 120` |

**3. Metrics Review** (20 minutes)

```bash
# Generate monthly report
cat <<'EOF' > monthly_report.sh
#!/bin/bash
echo "Content Hash Tracking - Monthly Report"
echo "======================================"
echo ""
echo "Date: $(date +%Y-%m-%d)"
echo ""

# Total operations
echo "Total Operations:"
curl -s localhost:9091/metrics | \
  grep 'content_hash_changes_detected\|content_hash_no_change' | \
  awk '{sum+=$2} END {print "  Total checks: " sum}'

# Cache hit rate
echo ""
echo "Cache Performance:"
hits=$(curl -s localhost:9091/metrics | grep content_hash_cache_hits | awk '{print $2}')
misses=$(curl -s localhost:9091/metrics | grep content_hash_cache_misses | awk '{print $2}')
echo "  Hits: $hits"
echo "  Misses: $misses"
echo "  Hit Rate: $(echo "scale=2; $hits / ($hits + $misses) * 100" | bc)%"

# Lock timeouts
echo ""
echo "Lock Health:"
timeouts=$(curl -s localhost:9091/metrics | grep metadata_lock_timeouts | awk '{print $2}')
echo "  Timeouts: $timeouts (should be 0)"

# Metadata size
echo ""
echo "Metadata Files:"
docker exec hugo-translator-orchestrator \
  find /data/metadata -name "*.json" -exec du -sh {} \;
EOF

chmod +x monthly_report.sh
./monthly_report.sh
```

## Incident Response

### Lock Timeout Incident

**Symptom**: `metadata_lock_timeouts` metric > 0

**Severity**: HIGH (data loss risk)

**Response Procedure**:

1. **Immediate** (5 minutes):
   ```bash
   # Check Redis health
   docker exec hugo-translator-redis redis-cli INFO stats

   # Check worker count
   docker ps | grep hugo-translator-worker | wc -l

   # Check lock acquisition times
   curl -s localhost:9091/metrics | \
     grep metadata_lock_acquire_duration_seconds
   ```

2. **Mitigation** (10 minutes):
   ```bash
   # Option A: Increase timeout (temporary)
   # Edit config/global.yaml:
   #   redis_lock_timeout: 60  # Increase from 30

   # Option B: Reduce workers (immediate)
   docker-compose up -d --scale worker=2

   # Option C: Restart Redis (if unhealthy)
   docker-compose restart redis
   ```

3. **Root Cause Analysis** (30 minutes):
   - Check Redis slow log: `docker exec hugo-translator-redis redis-cli SLOWLOG GET 10`
   - Review metadata save duration: p95 should be < 500ms
   - Check disk I/O: `docker exec hugo-translator-orchestrator iostat -x 1 10`

4. **Long-term Fix**:
   - Enable `cleanup_on_save` to reduce metadata size
   - Optimize worker count vs. throughput
   - Consider Redis tuning or upgrade

### Metadata Corruption Incident

**Symptom**: Logs show "Metadata corrupted, rebuilding"

**Severity**: MEDIUM (recoverable, one-time rehash)

**Response Procedure**:

1. **Verify Corruption** (5 minutes):
   ```bash
   # Check metadata file validity
   docker exec hugo-translator-orchestrator \
     python -c "
import json
from pathlib import Path
metadata_file = Path('/data/metadata/.translation_metadata.json')
try:
    with open(metadata_file) as f:
        data = json.load(f)
    print(f'Valid JSON: {len(data[\"files\"])} files')
except Exception as e:
    print(f'Corrupted: {e}')
"
   ```

2. **Restore from Backup** (if available):
   ```bash
   # Stop services
   docker-compose stop

   # Restore backup
   docker cp backups/metadata/2025-01/.translation_metadata.json \
     hugo-translator-orchestrator:/data/metadata/

   # Restart services
   docker-compose start
   ```

3. **Or Allow Rebuild** (if backup unavailable):
   ```bash
   # Corruption auto-recovery will:
   # 1. Reset to empty metadata
   # 2. Rehash all files on next translation
   # No action needed, monitor progress
   ```

4. **Root Cause Analysis**:
   - Check for disk errors: `docker exec hugo-translator-orchestrator dmesg | grep -i error`
   - Verify atomic writes: Check if temp files exist
   - Review shutdown logs: Was container killed during save?

### Slow Hash Computation Incident

**Symptom**: `content_hash_compute_duration_seconds` p95 > 100ms

**Severity**: LOW (performance degradation)

**Response Procedure**:

1. **Identify Slow Files** (10 minutes):
   ```bash
   # Find large files
   docker exec hugo-translator-orchestrator \
     find /content -name "*.md" -size +10M -exec du -h {} \;

   # Find recently modified large files
   docker exec hugo-translator-orchestrator \
     find /content -name "*.md" -mtime -1 -size +1M -exec du -h {} \;
   ```

2. **Check Disk I/O** (5 minutes):
   ```bash
   # Monitor I/O performance
   docker exec hugo-translator-orchestrator iostat -x 1 10

   # Look for:
   # - %util > 80%: Disk saturation
   # - await > 50ms: Slow response times
   ```

3. **Mitigation**:
   - If using SHA256, switch to MD5 (3x faster):
     ```yaml
     content_hash_tracking:
       hash_algorithm: "md5"
     ```
   - If disk is slow, upgrade to SSD
   - If files are huge (>100 MB), consider excluding them

## Configuration Management

### Updating Configuration

**Safe Update Procedure**:

1. **Edit config** (local):
   ```bash
   vim config/global.yaml
   # Modify content_hash_tracking section
   ```

2. **Validate YAML**:
   ```bash
   python -c "import yaml; yaml.safe_load(open('config/global.yaml'))"
   ```

3. **Apply changes** (rolling restart):
   ```bash
   # Restart orchestrator (main process)
   docker-compose restart orchestrator

   # Restart workers (one at a time)
   docker-compose restart worker
   ```

4. **Verify**:
   ```bash
   # Check logs for new config
   docker logs hugo-translator-orchestrator | tail -20

   # Verify feature is enabled
   docker exec hugo-translator-orchestrator \
     python -c "from src.utils.config_loader import get_global_config; \
                print(get_global_config()['features']['enable_content_hash_tracking'])"
   ```

### Common Configuration Changes

**1. Disable Content Hash (emergency)**:

```yaml
# config/global.yaml
features:
  enable_content_hash_tracking: false
```

```bash
# Or via CLI (per-run override)
docker exec hugo-translator-orchestrator \
  python -m src.cli example.com --disable-content-hash
```

**2. Adjust Cleanup Policy**:

```yaml
# More aggressive cleanup (large deployments)
content_hash_tracking:
  auto_cleanup:
    enabled: true
    max_age_days: 14  # Reduce from 30
    cleanup_on_save: true  # Enable continuous cleanup
```

**3. Increase Lock Timeout** (high contention):

```yaml
content_hash_tracking:
  redis_lock_timeout: 60  # Increase from 30
```

**4. Switch Hash Algorithm**:

```yaml
content_hash_tracking:
  hash_algorithm: "sha256"  # More secure (slower)
```

**After change**: Rebuild hashes with `--rebuild-content-hashes`

## Performance Tuning

### Optimizing for Throughput

**Goal**: Maximum files/hour with acceptable overhead

**Tuning Knobs**:

1. **Worker Count**:
   ```bash
   # Test different worker counts
   for workers in 2 4 6 8; do
     docker-compose up -d --scale worker=$workers
     # Run benchmark
     time docker exec hugo-translator-orchestrator \
       python -m src.cli example.com
     # Monitor lock timeouts
     curl -s localhost:9091/metrics | grep metadata_lock_timeouts
   done

   # Optimal: Maximum workers where lock_timeouts = 0
   ```

2. **Cleanup Frequency**:
   ```yaml
   # Option A: Cleanup on load (default)
   auto_cleanup:
     cleanup_on_load: true   # Once per startup
     cleanup_on_save: false

   # Option B: Continuous cleanup (large metadata)
   auto_cleanup:
     cleanup_on_load: true
     cleanup_on_save: true   # Every save (more overhead)
   ```

3. **Hash Algorithm**:
   ```yaml
   # MD5: 3x faster than SHA256
   hash_algorithm: "md5"  # Recommended for speed
   ```

### Optimizing for Latency

**Goal**: Minimize time to first translation

**Tuning Knobs**:

1. **Disable cleanup on load**:
   ```yaml
   auto_cleanup:
     cleanup_on_load: false  # Skip cleanup at startup
     cleanup_on_save: true   # Cleanup during operation
   ```

2. **Reduce lock timeout**:
   ```yaml
   redis_lock_timeout: 10  # Fail fast (dev/test only)
   ```

3. **Metadata warm-up** (large files):
   ```bash
   # Pre-load metadata before main run
   docker exec hugo-translator-orchestrator \
     python -c "
from pathlib import Path
from src.utils.metadata_tracker import MetadataTracker
tracker = MetadataTracker(Path('/data/metadata/.translation_metadata.json'))
tracker.load()
print(f'Loaded {len(tracker._data)} entries')
"
   ```

## Disaster Recovery

### Metadata Loss

**Scenario**: Metadata volume deleted or corrupted beyond recovery.

**Recovery Procedure**:

1. **Accept one-time rehash**:
   - All files will be treated as "changed"
   - Translation proceeds normally
   - New metadata created from scratch

2. **Monitor progress**:
   ```bash
   # Watch metadata file growth
   watch -n 5 'docker exec hugo-translator-orchestrator \
     du -h /data/metadata/.translation_metadata.json'
   ```

3. **Optimize recovery** (optional):
   - Temporarily increase workers for parallel hashing
   - Disable cleanup during recovery

**Prevention**:
- Regular backups (monthly)
- Volume snapshots (daily)
- Replication (cross-datacenter)

### Redis Failure

**Scenario**: Redis unavailable, multi-worker environment.

**Recovery Procedure**:

1. **Immediate**: System continues with degraded locking
   - Metadata writes proceed (fallback mode)
   - Risk of race conditions (last-write-wins)

2. **Restore Redis**:
   ```bash
   # Check Redis logs
   docker logs hugo-translator-redis

   # Restart Redis
   docker-compose restart redis

   # Verify connectivity
   docker exec hugo-translator-redis redis-cli PING
   ```

3. **Metadata reconciliation** (if corruption suspected):
   ```bash
   # Rebuild metadata from scratch
   docker exec hugo-translator-orchestrator \
     rm /data/metadata/.translation_metadata.json

   # Next run will recreate
   docker exec hugo-translator-orchestrator \
     python -m src.cli example.com --rebuild-content-hashes
   ```

**Prevention**:
- Redis persistence (RDB snapshots)
- Redis replication (master-replica)
- Monitor Redis health metrics

## Runbook Commands

### Quick Reference

**Check System Health**:
```bash
# One-liner health check
docker exec hugo-translator-orchestrator \
  python -c "
from src.utils.config_loader import get_global_config
from pathlib import Path
import json

config = get_global_config()
enabled = config['features']['enable_content_hash_tracking']
cleanup = config['content_hash_tracking']['auto_cleanup']

metadata_file = Path('/data/metadata/.translation_metadata.json')
if metadata_file.exists():
    with open(metadata_file) as f:
        data = json.load(f)
    tracked_files = len(data['files'])
    size_mb = metadata_file.stat().st_size / 1024 / 1024
else:
    tracked_files = 0
    size_mb = 0

print(f'Content Hash: {\"Enabled\" if enabled else \"Disabled\"}')
print(f'Tracked Files: {tracked_files}')
print(f'Metadata Size: {size_mb:.2f} MB')
print(f'Cleanup Enabled: {cleanup[\"enabled\"]}')
print(f'Max Age: {cleanup[\"max_age_days\"]} days')
"
```

**Force Cleanup**:
```bash
# Manually trigger cleanup (any age threshold)
docker exec hugo-translator-orchestrator \
  python -c "
from pathlib import Path
from src.utils.metadata_tracker import MetadataTracker

tracker = MetadataTracker(Path('/data/metadata/.translation_metadata.json'))
tracker.load()
removed = tracker.cleanup_old_entries(max_age_days=7)  # Aggressive
print(f'Removed {len(removed)} stale entries')
"
```

**Rebuild Metadata**:
```bash
# Delete and recreate (nuclear option)
docker exec hugo-translator-orchestrator \
  rm /data/metadata/.translation_metadata.json

docker exec hugo-translator-orchestrator \
  python -m src.cli example.com --rebuild-content-hashes
```

**Export Metadata for Analysis**:
```bash
# Export to local file for inspection
docker cp hugo-translator-orchestrator:/data/metadata/.translation_metadata.json \
  metadata_export_$(date +%Y%m%d).json

# Analyze with jq
cat metadata_export_*.json | jq '.statistics'
```

## Best Practices

1. **Monitor First**: Always check Grafana before making changes
2. **Backup Before**: Take metadata backup before major operations
3. **Test Locally**: Test config changes in dev environment first
4. **Rolling Updates**: Restart services one at a time (zero downtime)
5. **Document Changes**: Keep log of configuration changes
6. **Regular Cleanup**: Enable automatic cleanup (prevent metadata bloat)
7. **Alert Fatigue**: Set alert thresholds to avoid false positives
8. **Capacity Planning**: Monitor metadata growth trends monthly

## Support Contacts

**Escalation Path**:
1. Check this runbook
2. Review Grafana dashboard
3. Search GitHub issues
4. Contact platform team
5. File incident ticket

**Key Metrics for Support**:
- Lock timeout count
- Metadata file sizes
- Worker count
- Redis health status
- Recent configuration changes

## References

- [Architecture](../architecture/content-hash-production.md)
- [Metrics Guide](../observability/content-hash-metrics.md)
- [User Guide](../guides/content-hash-tracking.md)
- [Troubleshooting](troubleshooting.md)
