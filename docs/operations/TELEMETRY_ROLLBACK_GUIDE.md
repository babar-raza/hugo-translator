# Telemetry Migration Rollback Guide

**Status**: ⚠️ **ROLLBACK NOT RECOMMENDED** - New architecture is production-ready and safer

**Audience**: System administrators needing emergency rollback procedures

**Last Updated**: 2025-12-20

---

## Executive Summary

**This guide is for emergency situations only.** Rolling back to the old direct SQLite architecture is **not recommended** because:
- ❌ Old architecture has database corruption risk from concurrent writes
- ❌ No guaranteed delivery when database is locked
- ❌ Requires manual PRAGMA management

**Better alternatives**:
1. Fix the issue with new architecture (see [Troubleshooting](TELEMETRY_MIGRATION_GUIDE.md#troubleshooting))
2. Disable telemetry temporarily (`TELEMETRY_ENABLED=false`)
3. Contact support for assistance

**Only proceed with rollback if**:
- Critical production blocker that cannot be fixed
- Temporary rollback while investigating root cause
- Explicit approval from system owner

---

## When to Rollback

### Failure Criteria

Consider rollback **only** if:

| Severity | Criteria | Example | Rollback? |
|----------|----------|---------|-----------|
| **CRITICAL** | Hugo-translator cannot start due to telemetry error | `ImportError: telemetry module` blocking startup | ⚠️ Consider |
| **CRITICAL** | Translation pipeline completely broken | All translations failing due to telemetry | ⚠️ Consider |
| **HIGH** | Telemetry data not being captured | Events not appearing in database/API | ❌ Fix instead |
| **MEDIUM** | API service not starting | Cannot start telemetry_service.py | ❌ Fix instead |
| **LOW** | Buffer files accumulating | API down for extended period | ❌ Fix instead |

###**DO NOT Rollback For**:

- ✅ "ModuleNotFoundError: requests" → Install `requests` module
- ✅ "Connection refused to localhost:8765" → Start API service
- ✅ "Buffer directory filling up" → Start API service (events will sync)
- ✅ Missing environment variables → Configure `.env` file
- ✅ Telemetry verification failures → Check configuration

### Decision Tree

```
Issue: Telemetry not working
    ↓
Q: Is hugo-translator still translating files successfully?
    ├─ YES → Don't rollback, fix telemetry config
    └─ NO → Does disabling telemetry fix it? (TELEMETRY_ENABLED=false)
        ├─ YES → Don't rollback, investigate telemetry integration
        └─ NO → Issue is not telemetry-related
```

---

## Rollback Impact Assessment

### What Happens During Rollback

| Component | Before Rollback (HTTP API) | After Rollback (Direct SQLite) |
|-----------|----------------------------|--------------------------------|
| TelemetryClient init | `TelemetryClient(config=TelemetryConfig.from_env())` | `TelemetryClient(db_path="...")` |
| Event writes | HTTP POST to API | Direct SQLite INSERT |
| Corruption risk | ❌ Zero (single-writer) | ⚠️ HIGH (multi-process) |
| Offline resilience | ✅ Buffer failover | ❌ Fails if DB locked |
| New events | Lost during rollback (buffered) | Written to DB |
| Historical data | ✅ Preserved (DB readable) | ✅ Preserved |

### Data Preservation

**What is preserved**:
- ✅ All historical telemetry data in SQLite database
- ✅ NDJSON backup files (audit trail)

**What may be lost**:
- ⚠️ Events buffered in `.jsonl.active` files (not yet synced to API)
- ⚠️ Events in `.jsonl.ready` files (waiting for sync)

**To preserve buffered data before rollback**:
```bash
# 1. Start API service
cd /path/to/local-telemetry
python telemetry_service.py

# 2. Wait for buffer sync (check for .jsonl.synced files)
ls C:/telemetry/hugo-translator/buffer/*.jsonl.synced

# 3. Once all files are .synced, proceed with rollback
```

---

## Rollback Procedure

### Prerequisites

Before starting rollback:
- [ ] Backup current `.env` file (`cp .env .env.backup.$(date +%Y%m%d)`)
- [ ] Backup telemetry database (`cp $DB_PATH $DB_PATH.backup.$(date +%Y%m%d)`)
- [ ] Stop hugo-translator (if running as service)
- [ ] Sync all buffered events (see Data Preservation above)
- [ ] Document reason for rollback in incident log

**Estimated Time**: 10-15 minutes

---

### Step 1: Stop Services

```bash
# Stop hugo-translator (if running as service)
# (adjust command for your deployment)
systemctl stop hugo-translator  # Linux
# or
# CTRL+C in terminal where hugo-translator is running

# Stop telemetry API service
# CTRL+C in terminal where telemetry_service.py is running
```

**Verification**:
```bash
# Verify no hugo-translator processes running
ps aux | grep hugo-translator
# Expected: No matches

# Verify API service stopped
curl http://localhost:8765/health
# Expected: Connection refused
```

---

### Step 2: Checkout Old Telemetry Integration Code

**IMPORTANT**: The current code already uses the new architecture. To rollback, you need to revert to old commit.

```bash
cd /path/to/hugo-translator

# Find commit before HTTP API migration
git log --oneline src/observability/telemetry_integration.py | head -10

# Identify the last commit that used db_path parameter
# (This is a hypothetical example - adjust to actual commit hash)
LAST_OLD_COMMIT="abc1234"  # Replace with actual commit hash

# Create rollback branch
git checkout -b rollback/telemetry-old-architecture

# Revert telemetry_integration.py to old version
git checkout $LAST_OLD_COMMIT -- src/observability/telemetry_integration.py

# Review changes
git diff HEAD src/observability/telemetry_integration.py
```

**Expected Changes**:
- ❌ Remove `TelemetryConfig.from_env()` usage
- ❌ Add back `db_path` parameter
- ❌ Remove HTTP API client code
- ❌ Remove buffer handling

**Example Old Code Pattern**:
```python
# OLD (rollback target)
from telemetry.client import TelemetryClient

telemetry_client = TelemetryClient(
    agent_name="hugo-translator",
    db_path="D:/agent-metrics/db/telemetry.sqlite"  # Direct DB access
)
```

---

### Step 3: Update Environment Variables

```bash
cd /path/to/hugo-translator

# Backup current .env
cp .env .env.new-architecture-backup

# Edit .env file
# Remove or comment out:
# - METRICS_API_URL
# - TELEMETRY_BUFFER_DIR

# Add (if using old architecture):
# TELEMETRY_DB_PATH=D:/agent-metrics/db/telemetry.sqlite
```

**Updated .env**:
```bash
# Telemetry Configuration (OLD ARCHITECTURE - Direct SQLite)

# Direct database path (OLD - has corruption risk!)
TELEMETRY_DB_PATH=D:/agent-metrics/db/telemetry.sqlite

# DEPRECATED: HTTP API settings (not used in old architecture)
# METRICS_API_URL=http://localhost:8765
# TELEMETRY_BUFFER_DIR=C:/telemetry/hugo-translator/buffer

# Path to local-telemetry source
TELEMETRY_SRC_PATH=/path/to/local-telemetry/src
```

---

### Step 4: Revert Local-Telemetry (Optional)

If local-telemetry also needs rollback:

```bash
cd /path/to/local-telemetry

# Create rollback branch
git checkout -b rollback/pre-http-api

# Find commit before HTTP API migration (MIG-008)
git log --oneline | grep -B 5 "MIG-008"

# Checkout old version (before MIG-001)
git checkout <commit-before-MIG-001>

# Verify old TelemetryClient accepts db_path parameter
grep -A 10 "def __init__" src/telemetry/client.py | grep "db_path"
# Expected: db_path parameter present
```

---

### Step 5: Restart Hugo-Translator

```bash
cd /path/to/hugo-translator

# Start hugo-translator
# (adjust command for your deployment)
systemctl start hugo-translator  # Linux
# or
python -m src.cli  # Manual startup
```

**Verification**:
```bash
# Test single translation
python -m src.cli translate \
  --site-id example.com \
  --file path/to/test.md \
  --target-langs de

# Check if telemetry written to database
python scripts/verify_telemetry.py --check

# Should show latest run (with old architecture)
```

---

### Step 6: Validation

Verify rollback was successful:

```bash
# 1. Check code pattern
grep -n "db_path" src/observability/telemetry_integration.py
# Expected: Match found (using old db_path parameter)

# 2. Check environment variables
echo $TELEMETRY_DB_PATH
# Expected: D:/agent-metrics/db/telemetry.sqlite

# 3. Check telemetry data
python scripts/verify_telemetry.py --check
# Expected: Latest run visible

# 4. Test translation
python -m src.cli translate --site-id test --file test.md --target-langs de
# Expected: Translation succeeds, telemetry written
```

---

## Monitoring After Rollback

### Watch for Corruption Warnings

The old architecture is prone to corruption. Monitor logs for:

```bash
# Check database integrity
sqlite3 D:/agent-metrics/db/telemetry.sqlite "PRAGMA integrity_check;"
# Expected: ok

# Watch for lock errors
tail -f /var/log/hugo-translator.log | grep "database is locked"
```

### Common Issues After Rollback

**Issue**: "database is locked" errors

**Cause**: Multiple hugo-translator processes writing concurrently

**Fix**: Run only one hugo-translator instance at a time

---

**Issue**: Lost events from buffer

**Cause**: Buffered events were not synced before rollback

**Recovery**: Events may be lost. Check NDJSON backup files:
```bash
ls D:/agent-metrics/raw/*.ndjson
# Look for events around rollback time
```

---

## Re-Migration (After Fixing Issues)

When you're ready to migrate back to HTTP API architecture:

1. Follow [TELEMETRY_MIGRATION_GUIDE.md](TELEMETRY_MIGRATION_GUIDE.md)
2. Ensure root cause of rollback is fixed
3. Test thoroughly in staging environment first
4. Monitor closely after re-migration

**Steps**:
```bash
# 1. Checkout main branch (new architecture)
git checkout main
git pull origin main

# 2. Restore new architecture .env
cp .env.new-architecture-backup .env

# 3. Start API service
cd /path/to/local-telemetry
python telemetry_service.py

# 4. Restart hugo-translator
# (adjust for your deployment)

# 5. Validate
python scripts/verify_telemetry.py --check
```

---

## Emergency Contacts

If you need to rollback:
1. Document the reason (what failed, error messages, impact)
2. Follow rollback procedure above
3. Report issue to development team
4. Schedule post-mortem to fix root cause

---

## Alternative: Disable Telemetry

**Instead of rolling back, consider temporarily disabling telemetry**:

```bash
# In .env file
TELEMETRY_ENABLED=false
```

**Advantages**:
- ✅ Hugo-translator continues working normally
- ✅ No code changes required
- ✅ No data loss risk
- ✅ Can re-enable when issue is fixed

**Disadvantages**:
- ❌ No telemetry data collected during disabled period

This is often **safer than rollback** for temporary issues.

---

## Rollback Checklist

Before rollback:
- [ ] Documented failure reason and impact
- [ ] Attempted all troubleshooting steps
- [ ] Disabled telemetry as alternative (didn't help)
- [ ] Got approval from system owner
- [ ] Backed up current .env and database
- [ ] Synced all buffered events

During rollback:
- [ ] Stopped all services
- [ ] Reverted code to old architecture
- [ ] Updated environment variables
- [ ] Restarted services
- [ ] Validated rollback successful

After rollback:
- [ ] Monitoring for database corruption
- [ ] Documented rollback in incident log
- [ ] Scheduled investigation of root cause
- [ ] Planned re-migration timeline

---

## Summary

**Recommendation**: ⚠️ **DO NOT ROLLBACK** unless absolutely necessary

**Safer alternatives**:
1. Fix the issue (see [Troubleshooting](TELEMETRY_MIGRATION_GUIDE.md#troubleshooting))
2. Disable telemetry temporarily (`TELEMETRY_ENABLED=false`)
3. Run hugo-translator without telemetry

**If you must rollback**:
- Follow procedure above carefully
- Monitor for database corruption
- Plan re-migration as soon as root cause is fixed

---

## Related Documentation

- [Telemetry Migration Guide](TELEMETRY_MIGRATION_GUIDE.md) - How to migrate to new architecture
- [Telemetry Operations Guide](telemetry.md) - Day-to-day telemetry usage
- [Troubleshooting](TELEMETRY_MIGRATION_GUIDE.md#troubleshooting) - Fix common issues without rollback

---

**Last Updated**: 2025-12-20
**Rollback Complexity**: High
**Risk Level**: ⚠️ Moderate (corruption risk with old architecture)
**Estimated Rollback Time**: 10-15 minutes
