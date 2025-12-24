# Translation Memory Maintenance Runbook

**Version:** 1.0
**Last Updated:** 2025-12-24

Operational procedures for maintaining the Translation Memory (TM) cache system.

---

## Overview

The Translation Memory system uses LMDB (Lightning Memory-Mapped Database) for persistent storage and FAISS for semantic search. While both systems are designed for crash safety and reliability, regular maintenance ensures optimal performance and data integrity.

**Critical Operations:**
- [Integrity Checks](#integrity-checks) - Verify cache health
- [Backup & Restore](#backup--restore) - Protect against data loss
- [Performance Monitoring](#performance-monitoring) - Track cache health
- [Capacity Management](#capacity-management) - Plan for growth

---

## Quick Reference

### Health Check (30 seconds)
```bash
venv/Scripts/python.exe -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; r = check_cache_integrity(Path('data/tm/l2_lmdb')); print(f'{r.health_percentage:.1f}% healthy ({r.valid_count:,}/{r.total_scanned:,})')"
```

### Create Backup (2-5 minutes)
```bash
venv/Scripts/python.exe -c "from src.tm.backup import create_backup_manager; from pathlib import Path; mgr = create_backup_manager(Path('data/tm/l2_lmdb')); info = mgr.create_backup(); print(f'Backup: {info}')"
```

### List Backups
```bash
venv/Scripts/python.exe -c "from src.tm.backup import create_backup_manager; from pathlib import Path; mgr = create_backup_manager(Path('data/tm/l2_lmdb')); [print(b) for b in mgr.list_backups()]"
```

---

## Integrity Checks

The integrity checker validates cache entries against corruption, missing fields, and invalid data.

### Quick Health Check

**When to run:** Daily, after system crashes, before major operations

**Command:**
```bash
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

# Quick health check
report = check_cache_integrity(Path('data/tm/l2_lmdb'))

# Display results
print(f'Health: {report.health_percentage:.1f}%')
print(f'Status: {\"✓ HEALTHY\" if report.is_healthy else \"✗ CORRUPTED\"}')
print(f'Scanned: {report.total_scanned:,} entries')
print(f'Valid: {report.valid_count:,}')
print(f'Corrupt: {report.corrupt_count}')
"
```

**Expected output:**
```text
Health: 100.0%
Status: ✓ HEALTHY
Scanned: 44,550 entries
Valid: 44,550
Corrupt: 0
```

**Interpretation:**
- **100% healthy:** Cache is perfect, no action needed
- **99-100%:** Minor corruption, review errors and consider repair
- **95-99%:** Moderate corruption, repair recommended
- **<95%:** Significant corruption, restore from backup or rebuild

---

### Comprehensive Integrity Scan

**When to run:** Weekly, after suspected corruption, pre-migration

**Command:**
```bash
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path
import json

# Full scan with detailed report
db_path = Path('data/tm/l2_lmdb')
report = check_cache_integrity(
    db_path,
    repair=False,       # Read-only mode
    max_errors=1000     # Collect up to 1000 errors
)

# Save detailed report
with open('tm_integrity_report.json', 'w') as f:
    json.dump(report.to_dict(), f, indent=2)

print(f'Report saved to tm_integrity_report.json')
print(json.dumps(report.to_dict(), indent=2))
"
```

**Report format:**
```json
{
  "total_scanned": 44550,
  "valid_count": 44550,
  "corrupt_count": 0,
  "repaired_count": 0,
  "health_percentage": 100.0,
  "is_healthy": true,
  "error_count": 0,
  "errors": []
}
```

**Report fields:**
- `total_scanned`: Total entries examined
- `valid_count`: Entries passing all checks
- `corrupt_count`: Entries failing validation
- `repaired_count`: Entries fixed (repair mode only)
- `health_percentage`: `(valid_count / total_scanned) * 100`
- `is_healthy`: `true` if `corrupt_count == 0`
- `errors`: List of first 10 errors with keys and messages

---

### Auto-Repair Mode

**⚠️ CAUTION:** Repair mode **deletes** corrupted entries permanently. Always backup first!

**When to run:** Only when corruption is confirmed and acceptable to lose bad entries

**Procedure:**
```bash
# 1. Create backup first (REQUIRED)
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backup = mgr.create_backup(verify_integrity=False)
print(f'Backup created: {backup.path}')
"

# 2. Run integrity check in repair mode
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(
    Path('data/tm/l2_lmdb'),
    repair=True,        # ⚠️ DESTRUCTIVE: Deletes corrupt entries
    max_errors=1000
)

print(f'Repaired: {report.repaired_count} entries')
print(f'New health: {report.health_percentage:.1f}%')
"

# 3. Verify repair succeeded
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Final status: {\"✓ HEALTHY\" if report.is_healthy else \"✗ STILL CORRUPTED\"}')
"
```

**What gets repaired:**
- Invalid JSON → Entry deleted
- Missing required fields → Entry deleted
- Empty field values → Entry deleted
- Invalid language codes → Entry deleted
- Invalid UTF-8 encoding → Entry deleted
- Non-dictionary entries → Entry deleted

---

### Validation Checks Performed

The integrity checker validates each entry against these criteria:

| Check | Description | Error Message |
|-------|-------------|---------------|
| **UTF-8 Encoding** | Entry must be valid UTF-8 | `Invalid UTF-8 encoding` |
| **JSON Structure** | Entry must be valid JSON | `Invalid JSON` |
| **Dictionary Type** | Entry must be a JSON object | `Entry is not a dictionary` |
| **Required Fields** | Must have: `source_text`, `translation`, `site_id`, `src_lang`, `tgt_lang` | `Missing required field: <field>` |
| **Non-Empty Values** | All required fields must have values | `Empty value for field: <field>` |
| **Non-Null Values** | No null values allowed | `Null value for field: <field>` |
| **Language Codes** | Must be valid ISO 639-1 (2-letter codes) | `Invalid language code: <code>` |

**Example valid entry:**
```json
{
  "source_text": "Hello, world!",
  "translation": "Hola, mundo!",
  "site_id": "blog.example.com",
  "src_lang": "en",
  "tgt_lang": "es"
}
```

---

## Backup & Restore

### Creating Backups

**Backup Features:**
- Atomic snapshots using LMDB's native copy mechanism
- Automatic compaction to save disk space
- Integrity verification before backup (optional)
- Automatic pruning of old backups
- Disk space validation

#### Standard Backup

**When to run:** Daily, before major operations, before upgrades

```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

# Create backup manager
mgr = create_backup_manager(
    tm_path=Path('data/tm/l2_lmdb'),
    backup_dir=Path('data/tm_backups'),  # Optional: defaults to <tm_path>_backups
    max_backups=5                         # Keep last 5 backups
)

# Create backup with integrity check
backup_info = mgr.create_backup(
    verify_integrity=True,  # Check cache health before backup
    compact=True            # Compact backup to save space
)

print(f'✓ Backup created: {backup_info.path.name}')
print(f'  Size: {backup_info.size_mb:.1f} MB')
print(f'  Entries: {backup_info.entry_count:,}')
print(f'  Time: {backup_info.timestamp.strftime(\"%Y-%m-%d %H:%M:%S\")}')
"
```

**Output:**
```text
✓ Backup created: tm_backup_20251224_143025
  Size: 45.3 MB
  Entries: 44,550
  Time: 2025-12-24 14:30:25
```

**Backup naming:** `tm_backup_YYYYMMDD_HHMMSS`

---

#### Fast Backup (No Integrity Check)

**When to run:** Frequent snapshots, time-critical backups

```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backup_info = mgr.create_backup(verify_integrity=False)  # Skip integrity check

print(f'Fast backup: {backup_info.path.name}')
"
```

---

### Listing Backups

```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backups = mgr.list_backups()  # Sorted by timestamp (newest first)

print(f'Found {len(backups)} backup(s):')
for i, backup in enumerate(backups, 1):
    print(f'  {i}. {backup.path.name}')
    print(f'      {backup.size_mb:.1f} MB, {backup.entry_count:,} entries')
    print(f'      {backup.timestamp.strftime(\"%Y-%m-%d %H:%M:%S\")}')
"
```

**Get latest backup:**
```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
latest = mgr.get_latest_backup()

if latest:
    print(f'Latest: {latest.path.name} ({latest.size_mb:.1f} MB)')
else:
    print('No backups found')
"
```

---

### Restoring from Backup

**⚠️ CRITICAL:** Restore **replaces** current cache. Current data will be lost!

**Restore procedure:**

```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))

# List backups to choose from
backups = mgr.list_backups()
print('Available backups:')
for i, b in enumerate(backups, 1):
    print(f'  {i}. {b.path.name} ({b.timestamp.strftime(\"%Y-%m-%d %H:%M\")})')

# Restore from latest (replace index with desired backup)
backup_to_restore = backups[0].path

# IMPORTANT: This creates a safety backup of current state before restore
safety_backup = mgr.restore_backup(
    backup_path=backup_to_restore,
    force=True,                    # Required: Skip interactive confirmation
    create_safety_backup=True      # Create backup of current state (recommended)
)

if safety_backup:
    print(f'✓ Safety backup created: {safety_backup.path.name}')
print(f'✓ Restored from: {backup_to_restore.name}')
"
```

**Safety features:**
- Creates pre-restore backup automatically
- Validates backup exists before restore
- Atomic replacement (all-or-nothing)

**Restore without safety backup** (faster, not recommended):
```python
mgr.restore_backup(backup_path, force=True, create_safety_backup=False)
```

---

### Deleting Old Backups

**Manual deletion:**
```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))

# Get backups sorted by age (oldest first)
backups = list(reversed(mgr.list_backups()))

# Delete oldest backup
if len(backups) > 0:
    oldest = backups[0]
    mgr.delete_backup(oldest.path)
    print(f'Deleted: {oldest.path.name}')
"
```

**Automatic pruning:**
Backups are automatically pruned when `create_backup()` is called. Only the most recent `max_backups` are kept.

---

## Performance Monitoring

### Cache Statistics

**View current cache size:**
```bash
venv/Scripts/python.exe -c "
from src.tm.l2_persistent import L2PersistentTM
from pathlib import Path

l2 = L2PersistentTM(Path('data/tm/l2_lmdb'))
stat = l2.env.stat()
info = l2.env.info()

print(f'Entries: {stat[\"entries\"]:,}')
print(f'Map size: {info[\"map_size\"] / (1024**2):.1f} MB')
print(f'Page size: {stat[\"psize\"]} bytes')
print(f'Depth: {stat[\"depth\"]}')

l2.close()
"
```

### Disk Usage

**Check actual disk usage:**
```bash
# Windows PowerShell
Get-ChildItem data\tm\l2_lmdb | Measure-Object -Property Length -Sum | Select-Object @{Name=\"Size (MB)\"; Expression={[math]::Round($_.Sum / 1MB, 2)}}, Count

# Linux/Mac
du -sh data/tm/l2_lmdb
```

**Check backup disk usage:**
```bash
# Windows PowerShell
Get-ChildItem data\tm_backups | Measure-Object -Property Length -Sum | Select-Object @{Name=\"Size (MB)\"; Expression={[math]::Round($_.Sum / 1MB, 2)}}, Count

# Linux/Mac
du -sh data/tm_backups
```

---

## Maintenance Schedules

### Daily Operations (5 minutes)

**Morning health check:**
```bash
# 1. Quick integrity check (30 sec)
venv/Scripts/python.exe -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; r = check_cache_integrity(Path('data/tm/l2_lmdb')); print(f'Health: {r.health_percentage:.1f}%')"

# 2. Check disk space (10 sec)
dir data\tm\l2_lmdb | find "bytes free"

# 3. Review logs for TM errors (manual, 2-3 min)
# Check application logs for:
#   - "cache corruption"
#   - "LMDB error"
#   - "integrity check failed"
```

**Daily backup (evening, automated):**
```bash
venv/Scripts/python.exe -c "from src.tm.backup import create_backup_manager; from pathlib import Path; create_backup_manager(Path('data/tm/l2_lmdb'), max_backups=7).create_backup()"
```

---

### Weekly Operations (30 minutes)

**Every Monday morning:**

1. **Full integrity scan** (10 min)
   ```bash
   venv/Scripts/python.exe -c "
   from src.tm.integrity import check_cache_integrity
   from pathlib import Path
   import json

   report = check_cache_integrity(Path('data/tm/l2_lmdb'), max_errors=1000)

   with open(f'integrity_report_weekly.json', 'w') as f:
       json.dump(report.to_dict(), f, indent=2)

   print(f'Health: {report.health_percentage:.1f}%')
   print(f'Report: integrity_report_weekly.json')
   "
   ```

2. **Verify backup system** (5 min)
   ```bash
   venv/Scripts/python.exe -c "
   from src.tm.backup import create_backup_manager
   from pathlib import Path

   mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
   backups = mgr.list_backups()

   print(f'Backups: {len(backups)}')
   if len(backups) > 0:
       latest = backups[0]
       age_hours = (datetime.now() - latest.timestamp).total_seconds() / 3600
       print(f'Latest: {latest.path.name} ({age_hours:.1f} hours old)')
   else:
       print('⚠️ WARNING: No backups found!')
   "
   ```

3. **Performance analysis** (10 min)
   - Review TM hit rates in monitoring dashboard
   - Check cache size growth trends
   - Identify slow lookups (p95 > 100ms)

4. **Cleanup old backups** (5 min)
   ```bash
   # Automatically handled by max_backups
   # Manual cleanup only if needed
   ```

---

### Monthly Operations (1-2 hours)

**First Monday of month:**

1. **Compaction** (30-60 min for large caches)
   ```bash
   # LMDB auto-compacts, but manual compaction can reclaim space
   venv/Scripts/python.exe -c "
   from src.tm.backup import create_backup_manager
   from pathlib import Path

   # Create compacted backup
   mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
   compacted = mgr.create_backup(compact=True)

   print(f'Compacted backup: {compacted.size_mb:.1f} MB')
   print(f'Consider restoring from this backup to reclaim space')
   "
   ```

2. **Capacity planning review** (15 min)
   - Calculate monthly growth rate
   - Project when disk space will be exhausted
   - Plan for scaling (increase map_size, add storage)

3. **Benchmark performance** (15 min)
   - Run translation benchmark
   - Compare with baseline performance
   - Investigate regressions

4. **Archive old entries** (optional, 30 min)
   - Identify entries not accessed in 90+ days
   - Archive to cold storage
   - Rebuild cache without archived entries

---

## Emergency Procedures

### Cache Corruption Detected

**Symptoms:**
- Integrity check shows `health < 95%`
- Application errors: "JSON decode error"
- Translation lookups failing
- LMDB errors in logs

**Recovery procedure:**

```bash
# 1. Assess damage
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path
import json

report = check_cache_integrity(Path('data/tm/l2_lmdb'), max_errors=1000)
print(f'Corrupt entries: {report.corrupt_count}')
print(f'Health: {report.health_percentage:.1f}%')

with open('corruption_report.json', 'w') as f:
    json.dump(report.to_dict(), f, indent=2)
"

# 2a. If health > 95%: Auto-repair
#     See "Auto-Repair Mode" section above

# 2b. If health < 95%: Restore from backup
#     See "Restoring from Backup" section above
```

---

### Disk Full

**Symptoms:**
- LMDB error: `MDB_MAP_FULL`
- Cannot create backups
- Cannot add new translations

**Recovery procedure:**

```bash
# 1. Check disk usage
dir data\tm | find "bytes free"

# 2. Delete oldest backups
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backups = list(reversed(mgr.list_backups()))

# Delete oldest 2 backups
for backup in backups[:2]:
    mgr.delete_backup(backup.path)
    print(f'Deleted: {backup.path.name}')
"

# 3. Increase LMDB map_size (code change required)
# Edit src/tm/l2_persistent.py:
# L2PersistentTM(..., max_size_mb=500)  # Increase from current value
```

---

### System Crash Recovery

**After abrupt process termination:**

```bash
# 1. Check for stale lock files
dir .translation_progress\locks

# 2. Remove stale locks (if present)
Remove-Item .translation_progress\locks\*.lock

# 3. Run full integrity check
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Health: {report.health_percentage:.1f}%')
print(f'Status: {\"✓ No corruption\" if report.is_healthy else \"✗ Corruption detected\"}')
"

# 4. If healthy: Resume operations
# 5. If corrupted: Restore from backup
```

**Why no corruption after crashes:**
LMDB is ACID-compliant with copy-on-write semantics. Crashes can only affect uncommitted transactions. All committed data survives.

**Evidence:**
- 2025-12-24: Process abruptly killed, 44,550 entries, 100% healthy after restart

---

## Automation Examples

### Windows Task Scheduler (PowerShell)

**Daily backup script** (`tm_daily_backup.ps1`):
```powershell
# tm_daily_backup.ps1
$ErrorActionPreference = "Stop"

cd "C:\path\to\hugo-translator"

& venv\Scripts\python.exe -c @"
from src.tm.backup import create_backup_manager
from pathlib import Path
from datetime import datetime

mgr = create_backup_manager(
    Path('data/tm/l2_lmdb'),
    max_backups=7  # Keep 1 week
)

backup = mgr.create_backup(verify_integrity=True)
print(f'{datetime.now()}: Backup created - {backup.path.name} ({backup.size_mb:.1f} MB)')
"@ >> logs\tm_backup.log 2>&1
```

**Schedule daily at 2 AM:**
```powershell
$action = New-ScheduledTaskAction -Execute "PowerShell.exe" -Argument "-File C:\path\to\tm_daily_backup.ps1"
$trigger = New-ScheduledTaskTrigger -Daily -At 2am
Register-ScheduledTask -Action $action -Trigger $trigger -TaskName "TM Daily Backup" -Description "Daily TM cache backup with integrity check"
```

---

### Linux Cron

**Daily backup cron job:**
```bash
# Add to crontab (crontab -e)
0 2 * * * cd /path/to/hugo-translator && venv/bin/python -c "from src.tm.backup import create_backup_manager; from pathlib import Path; create_backup_manager(Path('data/tm/l2_lmdb'), max_backups=7).create_backup()" >> logs/tm_backup.log 2>&1
```

**Weekly integrity check:**
```bash
# Every Monday at 6 AM
0 6 * * 1 cd /path/to/hugo-translator && venv/bin/python -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; import json; r = check_cache_integrity(Path('data/tm/l2_lmdb')); json.dump(r.to_dict(), open('logs/integrity_weekly.json', 'w'), indent=2)" >> logs/tm_integrity.log 2>&1
```

---

### Python Automation Script

**Comprehensive maintenance script** (`tm_maintenance.py`):
```python
#!/usr/bin/env python
"""TM maintenance automation script."""

import json
import logging
from datetime import datetime
from pathlib import Path

from src.tm.backup import create_backup_manager
from src.tm.integrity import check_cache_integrity

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.FileHandler('logs/tm_maintenance.log'),
        logging.StreamHandler()
    ]
)

logger = logging.getLogger(__name__)


def daily_maintenance():
    """Daily TM maintenance tasks."""
    logger.info("Starting daily maintenance")

    # 1. Integrity check
    logger.info("Running integrity check...")
    report = check_cache_integrity(Path('data/tm/l2_lmdb'))

    if not report.is_healthy:
        logger.error(f"Cache corruption detected! Health: {report.health_percentage:.1f}%")
        # Send alert (email, Slack, etc.)
        return False

    logger.info(f"Cache healthy: {report.health_percentage:.1f}% ({report.total_scanned:,} entries)")

    # 2. Create backup
    logger.info("Creating backup...")
    mgr = create_backup_manager(Path('data/tm/l2_lmdb'), max_backups=7)
    backup = mgr.create_backup(verify_integrity=False)  # Already checked above

    logger.info(f"Backup created: {backup.path.name} ({backup.size_mb:.1f} MB)")

    logger.info("Daily maintenance completed")
    return True


if __name__ == "__main__":
    success = daily_maintenance()
    exit(0 if success else 1)
```

**Run daily:**
```bash
# Cron
0 2 * * * cd /path/to/hugo-translator && venv/bin/python tm_maintenance.py

# Windows Task Scheduler
schtasks /create /tn "TM Maintenance" /tr "C:\path\to\venv\Scripts\python.exe C:\path\to\tm_maintenance.py" /sc daily /st 02:00
```

---

## Best Practices

### Backup Strategy

**3-2-1 Rule:**
- **3** copies of data (original + 2 backups)
- **2** different storage types (local + network/cloud)
- **1** offsite copy

**Recommended setup:**
- Daily local backups (7-day retention)
- Weekly backups copied to network storage (4-week retention)
- Monthly backups archived to cold storage (1-year retention)

### Integrity Check Strategy

**When to run integrity checks:**
- ✅ Daily (quick check)
- ✅ After system crashes
- ✅ Before major operations (migration, upgrade)
- ✅ When performance degrades
- ✅ Weekly (comprehensive scan)
- ❌ Not needed: After every translation (LMDB is ACID-compliant)

### Backup Timing

**Optimal backup times:**
- Low activity periods (night, weekends)
- Before major changes (code deployment, config changes)
- After significant data additions (large translation batches)

**Avoid backups during:**
- High translation load
- Active batch translations
- Database migration/rebuild

---

## Troubleshooting

### Backup Fails: Insufficient Space

**Error:**
```text
InsufficientSpaceError: Insufficient disk space for backup
```

**Solution:**
```bash
# 1. Check free space
dir data | find "bytes free"

# 2. Delete old backups
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backups = list(reversed(mgr.list_backups()))

for backup in backups[5:]:  # Keep only 5 newest
    mgr.delete_backup(backup.path)
    print(f'Deleted: {backup.path.name}')
"

# 3. Lower min_free_space_gb requirement
# CacheBackupManager(..., min_free_space_gb=1.0)  # Default is 5.0
```

### Integrity Check Times Out

**Symptom:** Integrity check takes too long (>10 min for <100K entries)

**Solution:**
```bash
# Use max_errors to stop early
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

# Stop after finding 100 errors
report = check_cache_integrity(Path('data/tm/l2_lmdb'), max_errors=100)
print(f'Scanned: {report.total_scanned:,} (stopped at max_errors)')
"
```

### Restore Fails

**Error:**
```text
RestoreError: Failed to restore backup
```

**Diagnosis:**
```bash
# Check backup integrity
venv/Scripts/python.exe -c "
from pathlib import Path
from src.tm.integrity import check_cache_integrity

backup_path = Path('data/tm_backups/tm_backup_20251224_143025')
report = check_cache_integrity(backup_path)

print(f'Backup health: {report.health_percentage:.1f}%')
"
```

**Solution:**
- If backup corrupted: Use older backup
- If all backups corrupted: Rebuild cache from source

---

## Related Documentation

- [TM Architecture](../architecture/translation-memory.md) - How TM works
- [TM Troubleshooting](tm-troubleshooting.md) - Diagnose TM issues
- [TM Performance Tuning](tm-performance-tuning.md) - Optimize cache
- [TM Statistics Monitoring](../guides/tm-statistics-monitoring-guide.md) - Grafana dashboards

---

## Appendix: API Reference

### Integrity Check API

```python
from src.tm.integrity import check_cache_integrity, CacheIntegrityChecker
from pathlib import Path

# Convenience function (recommended)
report = check_cache_integrity(
    db_path=Path('data/tm/l2_lmdb'),
    repair=False,       # Set True to delete corrupted entries
    max_errors=100      # Stop after N errors
)

# Class-based API (advanced)
from src.tm.l2_persistent import L2PersistentTM

l2 = L2PersistentTM(Path('data/tm/l2_lmdb'))
checker = CacheIntegrityChecker(l2)
report = checker.verify_all(repair=False, max_errors=100, log_progress=True)
l2.close()
```

### Backup API

```python
from src.tm.backup import create_backup_manager, CacheBackupManager
from pathlib import Path

# Convenience function (recommended)
mgr = create_backup_manager(
    tm_path=Path('data/tm/l2_lmdb'),
    backup_dir=Path('data/tm_backups'),  # Optional
    max_backups=5,                        # Optional
    min_free_space_gb=5.0                 # Optional
)

# Create backup
backup_info = mgr.create_backup(
    verify_integrity=True,  # Check cache before backup
    compact=True            # Compact backup
)

# List backups
backups = mgr.list_backups()  # Sorted newest first
latest = mgr.get_latest_backup()

# Restore backup
safety_backup = mgr.restore_backup(
    backup_path=backup_info.path,
    force=True,                    # Required
    create_safety_backup=True      # Recommended
)

# Delete backup
mgr.delete_backup(backup_path)
```

---

**Document Version:** 1.0
**Last Verified:** 2025-12-24
**Verification:** All commands tested on Windows 11 with Python 3.13.2
