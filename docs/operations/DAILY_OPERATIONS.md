# Daily Operations Runbook

This runbook provides step-by-step procedures for common daily operational tasks for the Hugo Translation System.

> **Comprehensive Guide**: For detailed explanations, troubleshooting, and operational guidance beyond daily tasks, see the [Operations Manual (README.md)](README.md).

## Table of Contents

- [System Startup](#system-startup)
- [System Shutdown](#system-shutdown)
- [Health Monitoring](#health-monitoring)
- [Backup Operations](#backup-operations)
- [Cache Management](#cache-management)
- [TM Maintenance](#tm-maintenance)
- [Log Review](#log-review)
- [Performance Monitoring](#performance-monitoring)

---

## System Startup

### Purpose
Start the translation system and verify all components are operational.

### Prerequisites
- Python 3.9+ installed
- Required dependencies installed
- Configuration files present
- Sufficient disk space (>10% free)

### Steps

1. **Navigate to project directory**:
   ```bash
   cd /path/to/hugo-translator
   ```

2. **Activate virtual environment** (if using):
   ```bash
   # Linux/Mac
   source venv/bin/activate

   # Windows
   venv\Scripts\activate
   ```

3. **Check system health BEFORE starting**:
   ```bash
   python scripts/health_check.py --verbose
   ```

   **Expected output**: Overall Status: ✓ HEALTHY

4. **Start translation workers**:
   ```bash
   # Start single worker
   python -m src.workers.translation_worker --worker-id worker-1

   # Or start multiple workers
   python -m src.workers.translation_worker --worker-id worker-1 &
   python -m src.workers.translation_worker --worker-id worker-2 &
   python -m src.workers.translation_worker --worker-id worker-3 &
   ```

5. **Verify workers started**:
   ```bash
   ps aux | grep translation_worker
   ```

   **Expected output**: Process listings for each worker

6. **Check metrics endpoint**:
   ```bash
   curl http://localhost:9090/metrics
   ```

   **Expected output**: Prometheus metrics in text format

7. **Monitor logs for startup issues**:
   ```bash
   tail -f data/logs/translation.log
   ```

   **Expected output**: INFO level logs, no ERROR messages

### What to do if...

**Workers fail to start**:
1. Check logs: `tail data/logs/translation.log`
2. Verify configuration: `python -c "from src.utils.config_loader import load_config; print(load_config())"`
3. Check port availability: `netstat -an | grep 9090`

**Health check shows DEGRADED**:
1. Review component status: `python scripts/health_check.py --verbose`
2. Address degraded components (see troubleshooting guide)
3. Re-run health check

**Out of memory**:
1. Check available memory: `free -h` (Linux) or Task Manager (Windows)
2. Reduce number of workers
3. Adjust model cache size in `config/global.yaml`

### Verification
- [ ] All workers running
- [ ] Health check returns HEALTHY
- [ ] Metrics endpoint accessible
- [ ] No ERROR logs in last 5 minutes

---

## System Shutdown

### Purpose
Gracefully shut down the translation system to prevent data loss.

### Prerequisites
- System is currently running
- No critical jobs in progress (or acceptable to interrupt)

### Steps

1. **Check for active jobs**:
   ```bash
   python scripts/analysis/generate_metrics_report.py --format json | \
       grep -A 5 "queue"
   ```

   **Expected output**: Queue depth and active jobs count

2. **Wait for jobs to complete** (if needed):
   ```bash
   # Monitor queue until empty
   watch -n 5 'python scripts/analysis/generate_metrics_report.py | grep "Queue Depth"'
   ```

3. **Stop workers gracefully** (send SIGTERM):
   ```bash
   # Linux/Mac
   pkill -TERM -f translation_worker

   # Windows
   taskkill /IM python.exe /FI "WINDOWTITLE eq translation_worker*"
   ```

4. **Wait for workers to finish** (30 seconds):
   ```bash
   sleep 30
   ```

5. **Verify workers stopped**:
   ```bash
   ps aux | grep translation_worker
   ```

   **Expected output**: No translation_worker processes

6. **Force kill if necessary** (last resort):
   ```bash
   # Linux/Mac
   pkill -KILL -f translation_worker

   # Windows
   taskkill /F /IM python.exe /FI "WINDOWTITLE eq translation_worker*"
   ```

7. **Create final backup**:
   ```bash
   python scripts/tm/backup_tm.py \
       --output backups/tm_shutdown_$(date +%Y%m%d).tar.gz
   ```

### What to do if...

**Workers won't stop**:
1. Check for hung processes: `ps aux | grep translation_worker`
2. Use force kill: `pkill -KILL -f translation_worker`
3. Check for orphaned resources: `lsof | grep python`

**Data loss concerns**:
1. Check if backup completed: `ls -lh backups/`
2. Verify TM data intact: `ls -lh data/tm/`
3. Run data integrity check (see TM Maintenance)

### Verification
- [ ] All workers stopped
- [ ] No zombie processes
- [ ] Backup completed successfully
- [ ] TM data directories intact

---

## Health Monitoring

### Purpose
Monitor system health and address issues proactively.

### Frequency
- **Real-time**: Prometheus/Grafana dashboards
- **Scheduled**: Every 5 minutes (cron)
- **Manual**: Before/after major operations

### Steps

1. **Run health check**:
   ```bash
   python scripts/health_check.py --verbose
   ```

2. **Review component status**:
   - ✓ HEALTHY: Component operational
   - ⚠ DEGRADED: Component has issues but functional
   - ✗ UNHEALTHY: Component failed

3. **Check metrics dashboard**:
   ```bash
   python scripts/analysis/generate_metrics_report.py --since 1h
   ```

4. **Review key metrics**:
   - TM hit rate: Should be >30%
   - Translation success rate: Should be >95%
   - Queue depth: Should be <1000
   - Memory usage: Should be <80%
   - Disk usage: Should be <85%

5. **Investigate anomalies**:
   ```bash
   # Check recent errors
   grep ERROR data/logs/translation.log | tail -20

   # Check slow translations
   grep "duration.*[5-9][0-9]\." data/logs/translation.log | tail -10
   ```

### What to do if...

**TM hit rate below 30%**:
1. Check TM size: `du -sh data/tm/`
2. Rebuild L3 index: `python scripts/tm/build_l3_index.py`
3. Verify TM not corrupted: `python scripts/health_check.py --test`

**High memory usage**:
1. Check model cache: Review `config/global.yaml`
2. Restart workers to clear cache
3. Reduce parallel jobs

**High queue depth**:
1. Add more workers
2. Check for slow translations
3. Review translation batch sizes

### Automation

Set up automated health checks:

**Linux (cron)**:
```bash
# Add to crontab
*/5 * * * * cd /path/to/hugo-translator && python scripts/health_check.py >> data/logs/health.log 2>&1
```

**Windows (Task Scheduler)**:
- Create task that runs every 5 minutes
- Program: `python scripts/health_check.py`
- Log output to: `data/logs/health.log`

### Verification
- [ ] Health check passing
- [ ] Key metrics within normal ranges
- [ ] No critical alerts
- [ ] Logs reviewed

---

## Backup Operations

### Purpose
Create regular backups of TM data and configurations for disaster recovery.

### Frequency
- **Daily**: Automated via scheduled script
- **Before changes**: Manual backup
- **After major operations**: Manual verification

### Steps

1. **Create manual backup**:
   ```bash
   python scripts/tm/backup_tm.py \
       --output backups/tm_$(date +%Y%m%d_%H%M%S).tar.gz \
       --rotate 7
   ```

   **Expected output**: "Backup created successfully"

2. **Verify backup**:
   ```bash
   python scripts/tm/restore_tm.py \
       --backup backups/tm_YYYYMMDD_HHMMSS.tar.gz \
       --test
   ```

   **Expected output**: "VALID: Backup appears valid"

3. **Check backup size**:
   ```bash
   ls -lh backups/tm_*.tar.gz | tail -5
   ```

   **Expected output**: Recent backups with reasonable sizes

4. **Test restore** (monthly):
   ```bash
   python scripts/tm/restore_tm.py \
       --backup backups/tm_latest.tar.gz \
       --target /tmp/test_restore \
       --verify
   ```

### What to do if...

**Backup fails**:
1. Check disk space: `df -h`
2. Check permissions: `ls -ld backups/`
3. Review error logs
4. Try uncompressed backup: `--compression none`

**Backup too large**:
1. Check TM size growth: `du -sh data/tm/`
2. Consider TM cleanup/pruning
3. Use better compression: `--compression xz`

**Restore test fails**:
1. Check backup integrity: `--test` flag
2. Verify checksum matches
3. Try older backup
4. Contact support if data loss suspected

### Automation

Scheduled backups are configured in:
- Linux: `scripts/scheduled_backup.sh` (via cron)
- Windows: `scripts/scheduled_backup.bat` (via Task Scheduler)

### Verification
- [ ] Backup completed successfully
- [ ] Backup size reasonable
- [ ] Checksum file created
- [ ] Old backups rotated

---

## Cache Management

### Purpose
Manage L1 cache to maintain optimal performance.

### When to perform
- L1 cache near capacity (>9000 entries)
- Memory usage high (>80%)
- After TM updates

### Steps

1. **Check L1 cache size**:
   ```bash
   python scripts/analysis/generate_metrics_report.py --format json | \
       grep -A 5 "tm_cache_size"
   ```

2. **Clear L1 cache** (restart workers):
   ```bash
   # Stop workers
   pkill -TERM -f translation_worker

   # Wait 30 seconds
   sleep 30

   # Restart workers
   python -m src.workers.translation_worker --worker-id worker-1
   ```

3. **Adjust cache size** (if needed):
   Edit `config/global.yaml`:
   ```yaml
   tm_defaults:
     l1_cache_size: 10000  # Adjust as needed
   ```

4. **Monitor cache hit rate**:
   ```bash
   python scripts/analysis/generate_metrics_report.py | grep "Hit Rate"
   ```

### Verification
- [ ] Cache size within limits
- [ ] Memory usage normal
- [ ] Hit rate maintained or improved

---

## TM Maintenance

### Purpose
Maintain Translation Memory health and performance.

### Frequency
- **Weekly**: Check TM statistics
- **Monthly**: Cleanup and optimization
- **Quarterly**: Full rebuild

### Steps

1. **Check TM statistics**:
   ```bash
   python scripts/inspect_cache.py --stats
   ```

2. **Check TM size**:
   ```bash
   du -sh data/tm/l2_lmdb data/tm/l3_faiss
   ```

3. **Rebuild L3 index** (if degraded):
   ```bash
   python scripts/tm/build_l3_index.py --force
   ```

4. **Sync L3 with L2** (ensure consistency):
   ```bash
   python scripts/tm/sync_l3_index.py
   ```

### Verification
- [ ] TM sizes reasonable
- [ ] Indexes accessible
- [ ] No corruption detected

---

## Log Review

### Purpose
Review logs for errors, warnings, and performance issues.

### Frequency
- **Real-time**: During operations
- **Daily**: End of day review
- **Weekly**: Trend analysis

### Steps

1. **Check for errors**:
   ```bash
   grep ERROR data/logs/translation.log | tail -50
   ```

2. **Check for warnings**:
   ```bash
   grep WARN data/logs/translation.log | tail -50
   ```

3. **Analyze error patterns**:
   ```bash
   grep ERROR data/logs/translation.log | \
       awk '{print $5}' | sort | uniq -c | sort -rn
   ```

4. **Check slow operations**:
   ```bash
   grep "duration" data/logs/translation.log | \
       awk '{if ($NF > 5) print}' | tail -20
   ```

5. **Log rotation** (if needed):
   ```bash
   mv data/logs/translation.log data/logs/translation.log.$(date +%Y%m%d)
   gzip data/logs/translation.log.*
   ```

### Verification
- [ ] No critical errors
- [ ] Warning levels acceptable
- [ ] Log files not excessively large

---

## Performance Monitoring

### Purpose
Monitor and optimize system performance.

### Key Metrics

1. **Translation throughput**: Translations per second
2. **TM hit rate**: Percentage of TM hits
3. **Translation latency**: Average translation time
4. **Queue depth**: Number of pending jobs
5. **Resource usage**: CPU, memory, disk

### Steps

1. **Generate performance report**:
   ```bash
   python scripts/analysis/generate_metrics_report.py --since 24h
   ```

2. **Check Prometheus metrics**:
   ```bash
   curl -s http://localhost:9090/api/v1/query \
       -d 'query=rate(translations_total[5m])'
   ```

3. **Review Grafana dashboards** (if configured)

4. **Compare with baselines**:
   - Normal TM hit rate: 30-70%
   - Normal translation time: 0.5-3 seconds
   - Normal queue depth: 0-100

### Optimization Tips

**Improve TM hit rate**:
- Rebuild L3 index regularly
- Ensure TM is properly populated
- Check normalization settings

**Reduce translation latency**:
- Use GPU if available
- Adjust batch sizes
- Use faster models

**Reduce queue depth**:
- Add more workers
- Optimize translation pipeline
- Use batch processing

### Verification
- [ ] Performance within acceptable range
- [ ] No degradation over time
- [ ] Optimization opportunities identified

---

## Emergency Contacts

- **System Administrator**: [Contact]
- **DevOps Team**: [Contact]
- **On-call Engineer**: [Contact]

## See Also

- [Troubleshooting Guide](./TROUBLESHOOTING.md)
- [Disaster Recovery](./DISASTER_RECOVERY.md)
- Health Monitoring (archived)
- [Backup and Restore](./backup-restore.md)
