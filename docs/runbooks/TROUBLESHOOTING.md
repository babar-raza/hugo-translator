# Troubleshooting Runbook

Quick reference guide for diagnosing and resolving common issues.

## Quick Diagnostics

Run automated troubleshooting:
```bash
python scripts/troubleshoot.py --symptom <symptom>
```

Available symptoms: `slow_translations`, `oom_errors`, `cache_misses`

---

## High Translation Failure Rate

**Symptom**: Translation error rate >5%

**Diagnosis**:
```bash
python scripts/generate_metrics_report.py | grep "Failed"
grep ERROR data/logs/translation.log | tail -50
```

**Resolution**:
1. Check model availability: `python scripts/health_check.py`
2. Review error logs for patterns
3. Restart workers: `pkill -TERM -f translation_worker`
4. Verify configuration: `cat config/global.yaml`

---

## Low TM Hit Rate

**Symptom**: TM hit rate <30%

**Diagnosis**:
```bash
python scripts/generate_metrics_report.py | grep "Hit Rate"
python scripts/inspect_cache.py --stats
```

**Resolution**:
1. Rebuild L3 index: `python scripts/build_l3_index.py --force`
2. Sync L3 with L2: `python scripts/sync_l3_index.py`
3. Check TM size: `du -sh data/tm/`
4. Verify TM not corrupted: `python scripts/restore_tm.py --test`

---

## Worker Down

**Symptom**: Worker process not running

**Diagnosis**:
```bash
ps aux | grep translation_worker
tail -100 data/logs/translation.log
```

**Resolution**:
1. Check for crash: Review logs
2. Restart worker: `python -m src.workers.translation_worker --worker-id worker-1`
3. Check resources: `free -h` and `df -h`
4. Verify configuration loaded correctly

---

## High Queue Depth

**Symptom**: Queue depth >1000 jobs

**Diagnosis**:
```bash
python scripts/generate_metrics_report.py | grep "Queue"
```

**Resolution**:
1. Add more workers
2. Check for slow translations: `grep "duration.*[5-9][0-9]" data/logs/translation.log`
3. Optimize batch sizes in config
4. Check if workers are responding: `ps aux | grep translation_worker`

---

## TM Errors

**Symptom**: TM database errors

**Diagnosis**:
```bash
python scripts/health_check.py --verbose
ls -lh data/tm/l2_lmdb/ data/tm/l3_faiss/
```

**Resolution**:
1. Check disk space: `df -h`
2. Verify TM accessibility: `python scripts/health_check.py`
3. Restore from backup if corrupted:
   ```bash
   python scripts/restore_tm.py \
       --backup backups/tm_latest.tar.gz \
       --verify
   ```

---

## Model Errors

**Symptom**: Model loading/translation errors

**Diagnosis**:
```bash
grep "model" data/logs/translation.log | grep ERROR
python scripts/health_check.py --verbose
```

**Resolution**:
1. Check model registry: `ls -lh data/models/`
2. Clear model cache: Restart workers
3. Re-download models if needed
4. Check GPU availability: `nvidia-smi` (if using GPU)

---

## High Memory Usage

**Symptom**: Memory usage >80%

**Diagnosis**:
```bash
free -h  # Linux
# or Windows Task Manager
python scripts/health_check.py | grep "Memory"
```

**Resolution**:
1. Reduce number of workers
2. Reduce model cache size in `config/global.yaml`
3. Restart workers to clear memory: `pkill -TERM -f translation_worker`
4. Use smaller models

---

## Low Disk Space

**Symptom**: Disk usage >85%

**Diagnosis**:
```bash
df -h
du -sh data/tm/ data/logs/ data/models/
```

**Resolution**:
1. Clean old logs: `find data/logs/ -name "*.log.*" -mtime +30 -delete`
2. Remove old backups: `find backups/ -name "*.tar.gz" -mtime +30 -delete`
3. Clean model cache: `rm -rf data/models/.cache/*`
4. Add more disk space

---

## Slow Translations

**Symptom**: 95th percentile translation time >10s

**Diagnosis**:
```bash
python scripts/troubleshoot.py --symptom slow_translations
```

**Resolution**:
1. Check TM hit rate (see above)
2. Use GPU if available: Set `device: cuda` in config
3. Optimize batch sizes
4. Use faster models (e.g., smaller M2M100 variant)
5. Add more workers for parallel processing

---

## Validation Failures

**Symptom**: High validation failure rate

**Diagnosis**:
```bash
grep "validation" data/logs/translation.log | grep FAIL
```

**Resolution**:
1. Review validation rules in config
2. Check for placeholder issues
3. Verify YAML syntax in translated files
4. Adjust validation strictness if needed

---

## Backup Failures

**Symptom**: Backup script fails

**Diagnosis**:
```bash
tail -100 data/logs/backup.log
df -h
```

**Resolution**:
1. Check disk space
2. Verify backup directory writable: `ls -ld backups/`
3. Try uncompressed backup: `--compression none`
4. Manual backup to different location

---

## Restore Failures

**Symptom**: Restore verification fails

**Diagnosis**:
```bash
python scripts/restore_tm.py --backup <file> --test
```

**Resolution**:
1. Check backup integrity: Verify checksum
2. Try older backup
3. Extract manually: `tar -xzf backup.tar.gz`
4. Contact support if data loss suspected

---

## Health Check Degraded

**Symptom**: Health check returns DEGRADED or UNHEALTHY

**Diagnosis**:
```bash
python scripts/health_check.py --verbose
```

**Resolution**:
Review each failed component and address per component-specific guidance above.

---

## Performance Degradation

**Symptom**: System slower than baseline

**Diagnosis**:
```bash
python scripts/generate_metrics_report.py --since 24h
python scripts/health_check.py --verbose
```

**Resolution**:
1. Compare metrics with baseline
2. Check resource utilization
3. Review recent changes
4. Restart workers
5. Rebuild indexes if needed

---

## Emergency Escalation

If unable to resolve:
1. Collect diagnostics:
   ```bash
   python scripts/health_check.py --verbose > diagnostics.txt
   python scripts/generate_metrics_report.py --format json >> diagnostics.txt
   tail -500 data/logs/translation.log >> diagnostics.txt
   ```
2. Create backup: `python scripts/backup_tm.py --output backups/emergency.tar.gz`
3. Contact support with diagnostics

---

## See Also

- [Daily Operations](./DAILY_OPERATIONS.md)
- [Disaster Recovery](./DISASTER_RECOVERY.md)
- [Health Monitoring](../HEALTH_MONITORING.md)
