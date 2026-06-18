# Disaster Recovery Runbook

Procedures for recovering from catastrophic failures and data loss scenarios.

## Overview

This runbook covers:
- Complete system loss
- Data corruption
- Hardware failures
- Critical disk space
- Database corruption

**RTO (Recovery Time Objective)**: 1-2 hours
**RPO (Recovery Point Objective)**: 24 hours (last daily backup)

---

## Complete System Loss

### Scenario
Server crash, hardware failure, or catastrophic software failure resulting in complete system loss.

### Prerequisites
- Recent backup available
- New hardware/VM provisioned
- Network connectivity

### Recovery Steps

1. **Provision new system**:
   ```bash
   # Ubuntu/Debian
   sudo apt update && sudo apt install -y python3 python3-pip git

   # Install system dependencies
   sudo apt install -y build-essential libssl-dev libffi-dev
   ```

2. **Clone repository**:
   ```bash
   git clone https://github.com/yourorg/hugo-translator.git
   cd hugo-translator
   ```

3. **Install dependencies**:
   ```bash
   pip3 install -r requirements/base.txt
   pip3 install -r requirements/prod.txt
   ```

4. **Restore from backup**:
   ```bash
   # Copy backup from remote storage
   scp user@backup-server:/backups/tm_latest.tar.gz ./backups/

   # Verify backup integrity
   python scripts/tm/restore_tm.py \
       --backup backups/tm_latest.tar.gz \
       --test

   # Restore TM data and configs
   python scripts/tm/restore_tm.py \
       --backup backups/tm_latest.tar.gz \
       --verify
   ```

5. **Verify restoration**:
   ```bash
   # Check all components
   python scripts/health_check.py --verbose

   # Verify TM data
   ls -lh data/tm/l2_lmdb/ data/tm/l3_faiss/

   # Verify configs
   ls -lh config/
   ```

6. **Start system**:
   ```bash
   # Start workers
   python -m src.workers.translation_worker --worker-id worker-1

   # Verify operational
   python scripts/health_check.py
   ```

7. **Run test translation**:
   ```bash
   # Test single translation
   python -c "
   from src.translation_engine import TranslationEngine
   engine = TranslationEngine()
   result = engine.translate('Hello world', 'en', 'es')
   print(result)
   "
   ```

**Expected Recovery Time**: 1-2 hours

**Verification**:
- [ ] System health check passes
- [ ] TM data restored
- [ ] Configuration restored
- [ ] Test translation successful
- [ ] All workers running

---

## Data Corruption

### Scenario
TM database corrupted due to disk errors, improper shutdown, or software bug.

### Detection
```bash
python scripts/health_check.py --verbose
# Look for: "UNHEALTHY" status on TM components

# Or check logs
grep "corruption\|corrupt" data/logs/translation.log
```

### Recovery Steps

1. **Stop system immediately**:
   ```bash
   pkill -TERM -f translation_worker
   ```

2. **Assess corruption**:
   ```bash
   # Check L2 LMDB
   python -c "
   import lmdb
   try:
       env = lmdb.open('data/tm/l2_lmdb', readonly=True)
       print('L2 OK')
       env.close()
   except Exception as e:
       print(f'L2 CORRUPTED: {e}')
   "

   # Check L3 FAISS
   python -c "
   import faiss
   try:
       index = faiss.read_index('data/tm/l3_faiss/index.faiss')
       print(f'L3 OK: {index.ntotal} entries')
   except Exception as e:
       print(f'L3 CORRUPTED: {e}')
   "
   ```

3. **Backup corrupted data** (for forensics):
   ```bash
   mv data/tm data/tm.corrupted.$(date +%Y%m%d)
   ```

4. **Restore from last good backup**:
   ```bash
   # Find most recent good backup
   ls -lht backups/tm_*.tar.gz | head -5

   # Test backup
   python scripts/tm/restore_tm.py \
       --backup backups/tm_YYYYMMDD.tar.gz \
       --test

   # Restore
   python scripts/tm/restore_tm.py \
       --backup backups/tm_YYYYMMDD.tar.gz \
       --verify
   ```

5. **Verify integrity**:
   ```bash
   python scripts/health_check.py --verbose
   ```

6. **Restart system**:
   ```bash
   python -m src.workers.translation_worker --worker-id worker-1
   ```

**Expected Recovery Time**: 30-60 minutes

**Data Loss**: Up to 24 hours (since last backup)

---

## Disk Space Crisis

### Scenario
Disk usage >95%, system unable to write data.

### Immediate Actions

1. **Stop non-critical services**:
   ```bash
   pkill -TERM -f translation_worker
   ```

2. **Free disk space urgently**:
   ```bash
   # Remove old logs
   find data/logs/ -name "*.log.*" -delete
   rm -f data/logs/*.log.1 data/logs/*.log.2

   # Remove old backups (keep last 3)
   cd backups/
   ls -t tm_*.tar.gz | tail -n +4 | xargs rm -f
   ls -t tm_*.tar.gz.sha256 | tail -n +4 | xargs rm -f

   # Clear temp files
   rm -rf /tmp/translation_* /tmp/tm_*

   # Check space
   df -h
   ```

3. **Identify space hogs**:
   ```bash
   du -sh data/* | sort -h
   du -sh data/tm/* | sort -h
   ```

4. **Emergency cleanup if still critical**:
   ```bash
   # Archive and compress old artifacts
   tar -czf data/artifacts.$(date +%Y%m%d).tar.gz data/artifacts/
   rm -rf data/artifacts/*

   # Clean model cache
   rm -rf data/models/.cache/*
   ```

5. **Restart with reduced footprint**:
   ```bash
   # Reduce workers
   python -m src.workers.translation_worker --worker-id worker-1
   ```

**Recovery Time**: 15-30 minutes

---

## Database Rebuild

### Scenario
TM database needs complete rebuild from scratch.

### Prerequisites
- Source translation files available
- Or restore from backup first

### Steps

1. **Backup existing TM**:
   ```bash
   python scripts/tm/backup_tm.py \
       --output backups/tm_before_rebuild.tar.gz
   ```

2. **Clear existing TM**:
   ```bash
   rm -rf data/tm/l2_lmdb/*
   rm -rf data/tm/l3_faiss/*
   ```

3. **Rebuild from source translations** (if available):
   ```bash
   # This would use your specific ingestion script
   # Example:
   python scripts/ingest_translations.py \
       --source translated_content/ \
       --rebuild
   ```

4. **Or restore and rebuild indexes**:
   ```bash
   # Restore L2
   python scripts/tm/restore_tm.py \
       --backup backups/tm_latest.tar.gz

   # Rebuild L3 from L2
   python scripts/tm/build_l3_index.py --force
   ```

5. **Verify rebuild**:
   ```bash
   python scripts/health_check.py --verbose
   python scripts/inspect_cache.py --stats
   ```

**Recovery Time**: 1-4 hours (depending on TM size)

---

## Hardware Failure

### Scenario
Physical hardware failure (disk, memory, CPU).

### Immediate Actions

1. **Assess failure scope**:
   - Check system logs: `dmesg | tail -100`
   - Check disk health: `smartctl -a /dev/sda`
   - Check memory: `free -h`

2. **Stop system gracefully if possible**:
   ```bash
   python scripts/tm/backup_tm.py \
       --output backups/emergency_$(date +%Y%m%d_%H%M%S).tar.gz

   pkill -TERM -f translation_worker
   ```

3. **If disk failing**:
   - Copy critical data immediately
   - Restore on new hardware (see Complete System Loss)

4. **If memory failing**:
   - Reduce workers
   - Reduce cache sizes
   - Replace memory

---

## Network Partition

### Scenario
Network connectivity lost to remote services or workers.

### Detection
```bash
# Check network connectivity
ping -c 3 google.com

# Check worker connectivity
curl http://worker-1:9090/metrics
```

### Recovery

1. **Switch to local-only mode**:
   - Disable remote job queue (Redis)
   - Use in-memory queue
   - Operate with local workers only

2. **Re-establish connectivity**:
   - Check network configuration
   - Verify firewall rules
   - Test connectivity

3. **Resync after recovery**:
   - Sync TM changes
   - Process queued jobs
   - Verify data consistency

---

## Testing Disaster Recovery

### Regular Testing

**Monthly**: Test backup restore
```bash
python scripts/tm/restore_tm.py \
    --backup backups/tm_latest.tar.gz \
    --target /tmp/dr_test \
    --verify
```

**Quarterly**: Full DR simulation
1. Provision test environment
2. Restore from backup
3. Verify functionality
4. Document time to recover
5. Update procedures

**Annually**: Complete system rebuild
- Rebuild from scratch
- Document all dependencies
- Update documentation
- Train team

---

## Prevention

### Automated Backups
- Daily backups via cron/Task Scheduler
- Verify backups weekly
- Test restore monthly
- Off-site backup copies

### Monitoring
- Disk space alerts at 80%
- TM health checks every 5 minutes
- Error rate alerts
- Performance monitoring

### Documentation
- Keep runbooks updated
- Document all procedures
- Train team on DR procedures
- Regular DR drills

---

## Contact Information

**Emergency Contacts**:
- System Administrator: [Contact]
- DevOps On-Call: [Contact]
- Database Admin: [Contact]

**Escalation**:
- Level 1: Operations team
- Level 2: Engineering team
- Level 3: Architecture team

---

## See Also

- [Daily Operations](./DAILY_OPERATIONS.md)
- [Troubleshooting](./TROUBLESHOOTING.md)
- [Backup and Restore](./backup-restore.md)
- Health Monitoring (archived)
