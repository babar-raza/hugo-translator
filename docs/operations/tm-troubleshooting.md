# Translation Memory Troubleshooting Guide

**Version:** 1.0
**Last Updated:** 2025-12-24

Diagnose and resolve common Translation Memory (TM) cache issues.

---

## Overview

This guide covers common TM issues, their symptoms, diagnostic procedures, and solutions. For routine maintenance, see [TM Maintenance Runbook](tm-maintenance.md).

**Common Issues:**
- [Cache Corruption](#cache-corruption)
- [Low Hit Rates](#low-hit-rates)
- [Slow Lookups](#slow-lookups)
- [Disk Space Issues](#disk-space-issues)
- [LMDB Errors](#lmdb-errors)
- [FAISS Errors](#faiss-errors)

---

## Diagnostic Workflow

When encountering TM issues, follow this systematic diagnostic workflow:

```text
1. Initial Health Check
   ├─→ Healthy? → Monitor performance
   └─→ Unhealthy? ↓

2. Identify Issue Category
   ├─→ Corruption? → Cache Corruption section
   ├─→ Performance? → Slow Lookups / Low Hit Rates
   ├─→ Disk/Space? → Disk Space Issues
   └─→ Errors? → LMDB / FAISS Errors

3. Run Diagnostic Commands
   ├─→ Integrity check
   ├─→ Log analysis
   └─→ Metrics review

4. Apply Solution
   ├─→ Auto-repair
   ├─→ Restore from backup
   ├─→ Configuration tuning
   └─→ Rebuild cache

5. Verify Resolution
   └─→ Re-run health check
```

---

### Initial Health Check

**Quick health assessment:**

```bash
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(Path('data/tm/l2_lmdb'))

print(f'Health: {report.health_percentage:.1f}%')
print(f'Status: {\"✓ HEALTHY\" if report.is_healthy else \"✗ UNHEALTHY\"}')
print(f'Entries: {report.total_scanned:,}')
print(f'Corrupted: {report.corrupt_count}')

# Health assessment
if report.health_percentage == 100.0:
    print('\nAssessment: Excellent - No issues detected')
elif report.health_percentage >= 99.0:
    print('\nAssessment: Minor issues - Monitor closely')
elif report.health_percentage >= 95.0:
    print('\nAssessment: Moderate issues - Repair recommended')
else:
    print('\nAssessment: Critical issues - Restore from backup')
"
```

---

### Log Analysis

**Check application logs for TM errors:**

```bash
# Windows PowerShell
Select-String -Path "logs\*.log" -Pattern "cache|LMDB|integrity|TM error" | Select-Object -Last 20

# Linux/Mac
grep -i "cache\|LMDB\|integrity\|TM error" logs/*.log | tail -20
```

**Common error patterns:**
- `LMDB error: MDB_MAP_FULL` → Disk space issue
- `LMDB error: MDB_CORRUPTED` → Cache corruption
- `JSON decode error` → Entry corruption
- `Low TM hit rate` → Performance issue
- `FAISS index error` → L3 index corruption

---

### Metrics Review

**Check TM performance metrics:**

```bash
venv/Scripts/python.exe -c "
from src.tm.l2_persistent import L2PersistentTM
from pathlib import Path

l2 = L2PersistentTM(Path('data/tm/l2_lmdb'))
stat = l2.env.stat()
info = l2.env.info()

print(f'Entries: {stat[\"entries\"]:,}')
print(f'Map size: {info[\"map_size\"] / (1024**3):.2f} GB')
print(f'Map used: {(stat[\"psize\"] * info[\"last_pgno\"]) / (1024**3):.2f} GB')
print(f'Depth: {stat[\"depth\"]} (normal: 3-5)')

l2.close()
"
```

**Grafana dashboards** (if monitoring is enabled):
- TM Hit Rate by Layer
- TM Lookup Duration
- Cache Size Utilization

---

## Common Issues

### Cache Corruption

**Symptoms:**
- Integrity check shows `health < 100%`
- Application errors: `JSON decode error`, `Invalid UTF-8`
- Translation lookups returning incorrect results
- LMDB errors in logs: `MDB_CORRUPTED`

**Diagnosis:**

```bash
# 1. Run full integrity scan
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path
import json

report = check_cache_integrity(Path('data/tm/l2_lmdb'), max_errors=1000)

print(f'Corrupt entries: {report.corrupt_count}')
print(f'Health: {report.health_percentage:.1f}%')

# Save detailed report
with open('corruption_diagnosis.json', 'w') as f:
    json.dump(report.to_dict(), f, indent=2)

# Show first 5 errors
for key, error in report.errors[:5]:
    print(f'\n{key.hex()[:20]}...: {error}')
"

# 2. Check error patterns
# Look for common error types:
#   - Invalid JSON → Data corruption
#   - Missing fields → Schema violation
#   - Invalid language codes → Data quality issue
```

**Root Causes:**
- Abrupt process termination (rare - LMDB is ACID-compliant)
- Disk hardware failure
- File system corruption
- Manual file editing (never do this!)
- Software bugs in TM write code

**Solution:**

**Minor corruption (health > 95%):**
```bash
# Auto-repair (deletes corrupt entries)
# IMPORTANT: Backup first!

# 1. Create backup
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backup = mgr.create_backup(verify_integrity=False)
print(f'Backup: {backup.path.name}')
"

# 2. Run repair
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(Path('data/tm/l2_lmdb'), repair=True)
print(f'Repaired: {report.repaired_count} entries')
print(f'New health: {report.health_percentage:.1f}%')
"

# 3. Verify repair
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Status: {\"✓ REPAIRED\" if report.is_healthy else \"✗ STILL CORRUPT\"}')
"
```

**Major corruption (health < 95%):**
```bash
# Restore from backup (safer than repair)

# 1. List available backups
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backups = mgr.list_backups()

print('Available backups:')
for i, b in enumerate(backups, 1):
    print(f'  {i}. {b.path.name} ({b.timestamp.strftime(\"%Y-%m-%d %H:%M\")} - {b.size_mb:.1f} MB)')
"

# 2. Restore from latest good backup
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backups = mgr.list_backups()

# Restore from latest (creates safety backup automatically)
safety = mgr.restore_backup(backups[0].path, force=True)
print(f'Restored from: {backups[0].path.name}')
print(f'Safety backup: {safety.path.name}')
"
```

**Prevention:**
- Regular integrity checks (daily quick check)
- Regular backups (daily automated backup)
- Never manually edit LMDB files
- Monitor disk health (SMART status)

---

### Low Hit Rates

**Symptoms:**
- Overall hit rate < 50%
- Excessive model translation calls
- Slow translation performance
- High API costs

**Diagnosis:**

```bash
# Check TM statistics in Grafana
# Expected hit rates:
#   - L1 (in-memory): 60-80% of total hits
#   - L2 (persistent): 15-30% of total hits
#   - L3 (semantic): 5-15% of total hits
#   - L4 (miss): <10% ideally

# If Grafana unavailable, check logs:
grep -i "hit rate\|cache miss\|TM stats" logs/*.log | tail -50
```

**Root Causes:**

1. **New content domain** - Translating content in new topic areas
   - **Expected:** Hit rate starts low, improves over time
   - **Solution:** Continue translating, cache will populate

2. **Cache cleared accidentally** - Cache was deleted or reset
   - **Symptom:** Sudden drop from high to low hit rate
   - **Solution:** Restore from backup if recent

3. **Different source texts** - Similar but not identical content
   - **Symptom:** Low L2 hit rate, but L3 may help
   - **Solution:** Normal behavior, L3 semantic search should find similar

4. **TM not loading** - Cache file corrupted or inaccessible
   - **Symptom:** 0% hit rate across all layers
   - **Solution:** Check cache integrity, restore from backup

**Solutions:**

**Verify TM is loading:**
```bash
venv/Scripts/python.exe -c "
from src.tm.l2_persistent import L2PersistentTM
from pathlib import Path

l2 = L2PersistentTM(Path('data/tm/l2_lmdb'))
stat = l2.env.stat()

if stat['entries'] == 0:
    print('✗ PROBLEM: Cache is empty!')
else:
    print(f'✓ Cache loaded: {stat[\"entries\"]:,} entries')

l2.close()
"
```

**Build up cache with batch translation:**
```bash
# For new content domains, populate cache by translating representative content
# Hit rate will improve as cache grows
```

**Check for cache key collisions:**
```bash
# If using custom normalization, verify keys are unique
# Check for duplicate entries with different values
```

**Performance Targets:**
- **New content:** 20-40% hit rate initially
- **Repeated content:** 80-95% hit rate after first translation
- **Mixed content:** 60-80% hit rate in steady state

---

### Slow Lookups

**Symptoms:**
- TM lookup latency > 100ms (p95)
- Translation throughput reduced
- High worker CPU usage
- Timeouts in application logs

**Diagnosis:**

```bash
# 1. Check LMDB statistics
venv/Scripts/python.exe -c "
from src.tm.l2_persistent import L2PersistentTM
from pathlib import Path

l2 = L2PersistentTM(Path('data/tm/l2_lmdb'))
stat = l2.env.stat()

print(f'Tree depth: {stat[\"depth\"]} (slow if > 6)')
print(f'Entries: {stat[\"entries\"]:,}')
print(f'Branch pages: {stat[\"branch_pages\"]:,}')
print(f'Leaf pages: {stat[\"leaf_pages\"]:,}')

l2.close()
"

# 2. Monitor system resources
# Windows Task Manager: Check CPU, Disk I/O
# Windows Performance Monitor: Add LMDB process counters

# 3. Profile TM operations (if profiling enabled)
# Check for hot spots in TM lookup code
```

**Root Causes:**

1. **Disk I/O contention** - Slow disk, heavy I/O load
   - **Symptom:** Disk queue length > 2, high disk latency
   - **Solution:** Move TM to faster storage (SSD/NVMe)

2. **Memory pressure** - Insufficient RAM for TM operations
   - **Symptom:** High page faults, swap usage
   - **Solution:** Increase worker memory allocation

3. **Large cache size** - Tree depth too deep, many pages
   - **Symptom:** Tree depth > 6, many branch pages
   - **Solution:** Consider partitioning cache by site/language

4. **L3 FAISS index fragmentation**
   - **Symptom:** L3 lookups slow (>500ms)
   - **Solution:** Rebuild L3 index

**Solutions:**

**Move to faster storage:**
```bash
# 1. Create backup
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backup = mgr.create_backup()
print(f'Backup: {backup.path.name}')
"

# 2. Move backup to SSD/NVMe
# Example: D:\fast_storage\tm_backups\

# 3. Restore to new location
venv/Scripts/python.exe -c "
from src.tm.backup import CacheBackupManager
from pathlib import Path

old_backup = Path('data/tm_backups/tm_backup_20251224_143025')
new_location = Path('D:/fast_storage/tm_cache')

# Copy LMDB files to new location
import shutil
shutil.copytree(old_backup, new_location)

print(f'Moved to: {new_location}')
"

# 4. Update config to point to new location
# Edit src/tm/l2_persistent.py or config file
```

**Rebuild L3 FAISS index:**
```bash
venv/Scripts/python.exe -c "
from src.tm.l3_rebuild import rebuild_l3_index
from pathlib import Path

# Rebuild L3 semantic index from L2 cache
rebuild_l3_index(
    l2_path=Path('data/tm/l2_lmdb'),
    l3_path=Path('data/tm/l3_faiss'),
    batch_size=1000
)

print('L3 index rebuilt')
"
```

**Performance targets:**
- **L1 lookup:** <1ms (p95)
- **L2 lookup:** <10ms (p95)
- **L3 lookup:** <100ms (p95)

---

### Disk Space Issues

**Symptoms:**
- LMDB error: `MDB_MAP_FULL`
- Cannot create backups: `InsufficientSpaceError`
- Cannot add new translations
- Disk usage warning in logs

**Diagnosis:**

```bash
# 1. Check free disk space
dir data | find "bytes free"

# 2. Check TM cache size
venv/Scripts/python.exe -c "
from pathlib import Path

db_path = Path('data/tm/l2_lmdb')
data_file = db_path / 'data.mdb'

if data_file.exists():
    size_mb = data_file.stat().st_size / (1024**2)
    print(f'TM cache: {size_mb:.1f} MB')
"

# 3. Check backup size
dir data\tm_backups | find "File(s)"
```

**Root Causes:**

1. **LMDB map_size limit reached**
   - **Symptom:** `MDB_MAP_FULL` error
   - **Current cache:** approaching `max_size_mb` limit
   - **Solution:** Increase `max_size_mb` parameter

2. **Disk full**
   - **Symptom:** `InsufficientSpaceError` during backup
   - **Solution:** Delete old backups, clean up disk

3. **Backup accumulation**
   - **Symptom:** Backup directory consuming too much space
   - **Solution:** Lower `max_backups`, delete old backups

**Solutions:**

**Increase LMDB map_size:**
```python
# Edit src/tm/l2_persistent.py or create custom L2PersistentTM:

from src.tm.l2_persistent import L2PersistentTM
from pathlib import Path

# Increase max_size_mb from default (usually 100-500MB)
l2 = L2PersistentTM(
    db_path=Path('data/tm/l2_lmdb'),
    max_size_mb=2000  # Increase to 2GB
)
```

**Delete old backups:**
```bash
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))
backups = list(reversed(mgr.list_backups()))  # Oldest first

# Delete all but newest 3 backups
for backup in backups[3:]:
    mgr.delete_backup(backup.path)
    print(f'Deleted: {backup.path.name}')
"
```

**Compact cache:**
```bash
# Create compacted backup, then restore from it
venv/Scripts/python.exe -c "
from src.tm.backup import create_backup_manager
from pathlib import Path

mgr = create_backup_manager(Path('data/tm/l2_lmdb'))

# Create compacted backup
compacted = mgr.create_backup(compact=True)
print(f'Compacted size: {compacted.size_mb:.1f} MB')

# Restore from compacted backup to reclaim space
safety = mgr.restore_backup(compacted.path, force=True)
print(f'Restored, old cache backed up to: {safety.path.name}')
"
```

**Disk space requirements:**
- **TM cache:** 50-500 MB (varies by translation volume)
- **Backups:** 250-2500 MB (5 backups × cache size)
- **Minimum free:** 5 GB recommended

---

### LMDB Errors

Common LMDB errors and solutions:

#### MDB_MAP_FULL

**Error:**
```text
lmdb.MapFullError: mdb_put: MDB_MAP_FULL: Environment mapsize limit reached
```

**Cause:** LMDB map_size limit exceeded

**Solution:**
```python
# Increase max_size_mb in L2PersistentTM initialization
# See "Disk Space Issues" section above
```

---

#### MDB_CORRUPTED

**Error:**
```text
lmdb.CorruptedError: mdb_cursor_open: MDB_CORRUPTED: Located page was wrong type
```

**Cause:** Database file corruption (very rare)

**Solution:**
```bash
# Restore from backup
# See "Cache Corruption" section above
```

---

#### MDB_NOTFOUND

**Error:**
```text
lmdb.NotFoundError: mdb_get: MDB_NOTFOUND: No matching key/data pair found
```

**Cause:** Normal - entry not in cache (cache miss)

**Solution:** This is expected behavior, not an error. Entry will be translated and cached.

---

#### Permission denied

**Error:**
```text
PermissionError: [Errno 13] Permission denied: 'data/tm/l2_lmdb/lock.mdb'
```

**Cause:** Another process has the database open, or stale lock file

**Solution:**
```bash
# 1. Check for running processes using TM
# Windows: tasklist | find /i "python"
# Linux: ps aux | grep python

# 2. If no processes running, remove stale lock file
# ONLY IF NO PROCESSES RUNNING!
Remove-Item data\tm\l2_lmdb\lock.mdb -Force
```

---

### FAISS Errors

Common FAISS (L3 semantic cache) errors:

#### Index dimension mismatch

**Error:**
```text
RuntimeError: Error in faiss::IndexFlatL2::add_same_thread:  Dimension of vectors does not match index dimension
```

**Cause:** Embedding model changed, dimension mismatch

**Solution:**
```bash
# Rebuild L3 index with correct dimensions
venv/Scripts/python.exe -c "
from src.tm.l3_rebuild import rebuild_l3_index
from pathlib import Path

rebuild_l3_index(
    l2_path=Path('data/tm/l2_lmdb'),
    l3_path=Path('data/tm/l3_faiss')
)
"
```

---

#### Index file corrupted

**Error:**
```text
RuntimeError: Error reading index file: Invalid format
```

**Cause:** FAISS index file corrupted

**Solution:**
```bash
# Delete corrupted index and rebuild
Remove-Item data\tm\l3_faiss\* -Recurse -Force

venv/Scripts/python.exe -c "
from src.tm.l3_rebuild import rebuild_l3_index
from pathlib import Path

rebuild_l3_index(
    l2_path=Path('data/tm/l2_lmdb'),
    l3_path=Path('data/tm/l3_faiss')
)
"
```

---

#### Metadata mismatch

**Error:**
```text
AssertionError: Metadata count (4500) does not match index vectors (4452)
```

**Cause:** Index and metadata out of sync

**Solution:**
```bash
# Rebuild L3 index to resynchronize
# See above "Index file corrupted" solution
```

---

## Case Studies

### Case Study 1: Abrupt Process Termination Recovery

**Date:** 2025-12-24
**Incident:** Translation process abruptly killed (SIGKILL)
**Impact:** Process terminated mid-translation

**Initial Assessment:**
- Process terminated without graceful shutdown
- Lock file remained: `.translation_progress/locks/blog.aspose.net.lock`
- User concern: Is TM cache corrupted?

**Diagnosis:**
```bash
# 1. Quick health check
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Health: {report.health_percentage:.1f}%')
print(f'Scanned: {report.total_scanned:,} entries')
print(f'Corrupted: {report.corrupt_count}')
"

# Output:
# Health: 100.0%
# Scanned: 44,550 entries
# Corrupted: 0
```

**Result:** ✅ **NO CORRUPTION DETECTED**

**Root Cause Analysis:**
- LMDB uses ACID transactions (Atomic, Consistent, Isolated, Durable)
- Copy-on-write semantics prevent in-place modifications
- Only uncommitted transactions lost (none in this case)
- All 44,550 committed entries survived perfectly

**Recovery Actions:**
1. ✅ Verified cache integrity (100% healthy)
2. ✅ Removed stale lock file
3. ✅ Resumed operations normally
4. ✅ No data loss

**Lessons Learned:**
1. **LMDB crash safety works as designed** - ACID guarantees protected all data
2. **Stale locks are expected** - Lock files must be cleaned after crashes
3. **Integrity checks validate recovery** - Always verify health after crashes
4. **No panic needed** - LMDB is designed for crash resilience

**Prevention:**
- Regular backups (daily automated)
- Integrity monitoring (daily quick checks)
- Graceful shutdown when possible (SIGTERM vs SIGKILL)

**Evidence:**
- Integrity report: `cache_integrity_analysis_2025-12-24.md`
- 44,550 entries scanned, 0 corrupted
- Health: 100.0%

**Conclusion:**
LMDB's ACID properties and copy-on-write design provide excellent crash resilience. This incident validates the architecture's robustness.

---

## Related Documentation

- [TM Maintenance Runbook](tm-maintenance.md) - Routine maintenance procedures
- [TM Architecture](../architecture/translation-memory.md) - How TM works
- [TM Performance Tuning](tm-performance-tuning.md) - Optimization guide
- [TM Statistics Monitoring](../guides/tm-statistics-monitoring-guide.md) - Grafana dashboards

---

## Quick Reference

### Diagnostic Commands

```bash
# Health check
venv/Scripts/python.exe -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; r = check_cache_integrity(Path('data/tm/l2_lmdb')); print(f'{r.health_percentage:.1f}% ({r.corrupt_count} errors)')"

# Cache size
venv/Scripts/python.exe -c "from src.tm.l2_persistent import L2PersistentTM; from pathlib import Path; l2 = L2PersistentTM(Path('data/tm/l2_lmdb')); print(f'{l2.env.stat()[\"entries\"]:,} entries'); l2.close()"

# Disk space
dir data\tm | find "bytes free"

# Backup status
venv/Scripts/python.exe -c "from src.tm.backup import create_backup_manager; from pathlib import Path; print(f'{len(create_backup_manager(Path(\"data/tm/l2_lmdb\")).list_backups())} backups')"
```

### Recovery Commands

```bash
# Create emergency backup
venv/Scripts/python.exe -c "from src.tm.backup import create_backup_manager; from pathlib import Path; b = create_backup_manager(Path('data/tm/l2_lmdb')).create_backup(); print(f'Backup: {b.path.name}')"

# Auto-repair cache
venv/Scripts/python.exe -c "from src.tm.integrity import check_cache_integrity; from pathlib import Path; r = check_cache_integrity(Path('data/tm/l2_lmdb'), repair=True); print(f'Repaired: {r.repaired_count}')"

# Restore from latest backup
venv/Scripts/python.exe -c "from src.tm.backup import create_backup_manager; from pathlib import Path; mgr = create_backup_manager(Path('data/tm/l2_lmdb')); mgr.restore_backup(mgr.get_latest_backup().path, force=True)"
```

---

**Document Version:** 1.0
**Last Verified:** 2025-12-24
**Case Studies:** 1 real incident documented (2025-12-24 crash recovery)
