# Telemetry Migration Guide: HTTP API + Buffer Architecture

**Status**: ✅ **MIGRATION COMPLETE** - hugo-translator already uses HTTP API architecture

**Audience**: Users upgrading hugo-translator or verifying telemetry configuration

**Last Updated**: 2025-12-20

---

## Executive Summary

**Good News**: If you're running the latest version of hugo-translator, **no migration is needed**. The codebase already uses the new HTTP API + buffer architecture.

This guide helps you:
1. Verify your installation uses the correct architecture
2. Configure environment variables properly
3. Troubleshoot telemetry issues
4. Understand the new architecture

---

## Table of Contents

1. [Architecture Overview](#architecture-overview)
2. [Prerequisites](#prerequisites)
3. [Verification Steps](#verification-steps)
4. [Environment Configuration](#environment-configuration)
5. [First-Time Setup](#first-time-setup)
6. [Validation](#validation)
7. [Troubleshooting](#troubleshooting)
8. [FAQ](#faq)

---

## Architecture Overview

### New Architecture (Current)

```
hugo-translator
    ↓
TelemetryClient (local-telemetry)
    ↓
[Primary] HTTP POST → API Service (localhost:8765)
    ↓                      ↓
[Failover] BufferFile   Single-Writer DB Access
    ↓
.jsonl.active → .jsonl.ready → .jsonl.synced
```

**Key Features**:
- ✅ **Zero corruption guarantee**: Single-writer pattern via HTTP API
- ✅ **Guaranteed delivery**: Local buffer when API unavailable
- ✅ **At-least-once semantics**: Idempotent event_id handling
- ✅ **Graceful degradation**: Works offline, syncs when API returns

###

 Old Architecture (Deprecated)

```
hugo-translator
    ↓
TelemetryClient (local-telemetry)
    ↓
[Direct] SQLite database writes (DANGEROUS)
    ↓
⚠️ Multi-process corruption risk
```

**Problems Fixed**:
- ❌ Database corruption from concurrent writes
- ❌ No guaranteed delivery when database locked
- ❌ Manual PRAGMA management required

---

## Prerequisites

### Required Versions

| Component | Minimum Version | How to Check |
|-----------|----------------|--------------|
| hugo-translator | Latest main branch | `git log -1 --oneline` (commit `7d7b108` or later) |
| local-telemetry | Latest main branch | `cd $TELEMETRY_SRC_PATH/.. && git log -1 --oneline` (commit `ec4b5d9` or later) |
| Python | 3.10+ | `python --version` |

### Required Dependencies

In local-telemetry environment:
```bash
cd C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry
pip install requests  # Required for HTTP API client
```

### API Service Deployment

The telemetry API service must be running on `localhost:8765`:

```bash
# Check if API is running
curl http://localhost:8765/health
# Expected: {"status": "ok", "version": "2.0.0"}
```

If not running, start it:
```bash
cd C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry
python telemetry_service.py
```

---

## Verification Steps

### Step 1: Verify Implementation Code

Check that `src/observability/telemetry_integration.py` uses the correct pattern:

```bash
cd c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator

# Should NOT find db_path parameter
grep -n "db_path" src/observability/telemetry_integration.py
# Expected: No matches (or only commented lines)

# Should find TelemetryConfig.from_env()
grep -n "TelemetryConfig.from_env()" src/observability/telemetry_integration.py
# Expected: Match on line 66 or similar
```

**Expected Code Pattern** (lines 63-72 in telemetry_integration.py):
```python
try:
    from telemetry.client import TelemetryClient
    from telemetry.config import TelemetryConfig

    # Correct pattern: Use TelemetryConfig.from_env()
    config = TelemetryConfig.from_env()
    client = TelemetryClient(config=config)

    telemetry_available = True
except Exception as e:
    telemetry_available = False
```

✅ **PASS**: If your code matches this pattern, you're already using the new architecture!

### Step 2: Verify Environment Variables

Check your `.env` file or environment:

```bash
# Required environment variables
echo $METRICS_API_URL          # Should be http://localhost:8765
echo $TELEMETRY_BUFFER_DIR     # Should be path like C:/telemetry/hugo-translator/buffer
echo $TELEMETRY_SRC_PATH       # Should be path to local-telemetry/src
```

**IMPORTANT**: The variable is `METRICS_API_URL`, **not** `TELEMETRY_API_URL`.
- Local-telemetry uses `METRICS_API_URL` for historical reasons
- This is documented in `.env.example`

### Step 3: Verify API Service Health

```bash
# Test API health endpoint
curl http://localhost:8765/health | jq .

# Expected output:
{
  "status": "ok",
  "version": "2.0.0",
  "db_path": "D:/agent-metrics/telemetry.sqlite",
  "journal_mode": "DELETE",
  "synchronous": "FULL"
}
```

✅ **PASS**: If you get `{"status": "ok"}`, the API is ready

---

## Environment Configuration

### Create/Update .env File

Create `.env` in hugo-translator root directory:

```bash
# Telemetry Configuration (HTTP API + Buffer Architecture)

# API endpoint for telemetry service
# NOTE: local-telemetry uses METRICS_API_URL (not TELEMETRY_API_URL)
METRICS_API_URL=http://localhost:8765

# Local buffer directory for guaranteed writes when API unavailable
# Events are buffered here and synced when API recovers
TELEMETRY_BUFFER_DIR=C:/telemetry/hugo-translator/buffer

# Path to local-telemetry source code
# Adjust this path to match your local setup
TELEMETRY_SRC_PATH=C:/Users/prora/OneDrive/Documents/GitHub/local-telemetry/src

# Optional: Agent owner name (for telemetry records)
AGENT_OWNER=Your Name

# Optional: Disable telemetry entirely
# TELEMETRY_ENABLED=false
```

### Add to .gitignore

Ensure `.env` and buffer files are not committed:

```bash
# Add to .gitignore if not already present
echo ".env" >> .gitignore
echo "telemetry_buffer/" >> .gitignore
```

### Load Environment Variables

Ensure your application loads `.env` on startup:

```python
# src/__main__.py or wherever app initializes
from dotenv import load_dotenv
load_dotenv()  # Load .env file
```

---

## First-Time Setup

If you're setting up telemetry for the first time:

### 1. Install Local-Telemetry

```bash
# Clone local-telemetry repository
cd C:\Users\prora\OneDrive\Documents\GitHub
git clone https://github.com/YOUR_ORG/local-telemetry.git
cd local-telemetry

# Install dependencies
pip install requests python-dotenv

# Verify version
git log -1 --oneline
# Should be ec4b5d9 or later
```

### 2. Start Telemetry API Service

```bash
cd C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry

# Start API service
python telemetry_service.py

# Expected output:
# INFO: Started server process [12345]
# INFO: Waiting for application startup.
# INFO: Application startup complete.
# INFO: Uvicorn running on http://0.0.0.0:8765 (Press CTRL+C to quit)
```

Keep this running in a separate terminal.

### 3. Configure Hugo-Translator

```bash
cd c:\Users\prora\OneDrive\Documents\GitHub\hugo-translator

# Copy example environment file
cp .env.example .env

# Edit .env and set:
# - METRICS_API_URL=http://localhost:8765
# - TELEMETRY_BUFFER_DIR=C:/telemetry/hugo-translator/buffer
# - TELEMETRY_SRC_PATH=C:/Users/prora/.../local-telemetry/src
```

### 4. Verify Configuration

```bash
# Run telemetry verification script
python scripts/verify_telemetry.py --check

# Expected output:
# ============================================================
# TELEMETRY FIELD VERIFICATION (TEL-07-A)
# ============================================================
# ...
# [PASS] All verifications passed!
```

---

## Validation

### Test 1: API Health Check

```bash
curl http://localhost:8765/health
# Expected: {"status": "ok"}
```

### Test 2: Buffer Directory Creation

```bash
# Check if buffer directory was created
ls -l C:/telemetry/hugo-translator/buffer/

# Expected: Directory exists (may be empty initially)
```

### Test 3: Single Translation Test

```bash
# Run a single file translation
python -m src.cli translate \
  --site-id example.com \
  --file path/to/test.md \
  --target-langs de

# Check for telemetry events
ls C:/telemetry/hugo-translator/buffer/*.jsonl.active

# Verify event was sent to API
curl "http://localhost:8765/api/v1/runs?agent_name=hugo-translator&limit=1" | jq .
```

### Test 4: Verify Telemetry Data

```bash
# Run verification script
python scripts/verify_telemetry.py --check

# Should show latest translation run details
```

### Test 5: API Unavailability Test

```bash
# Stop API service (CTRL+C in API terminal)

# Run a translation (should buffer locally)
python -m src.cli translate --site-id example.com --file test.md --target-langs de

# Check buffer file was created
ls C:/telemetry/hugo-translator/buffer/*.jsonl.active

# Start API service again
# Events should sync automatically
```

---

## Troubleshooting

### Issue: "ModuleNotFoundError: No module named 'requests'"

**Symptom**:
```
ModuleNotFoundError: No module named 'requests'
```

**Cause**: Missing `requests` dependency in local-telemetry environment

**Fix**:
```bash
cd C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry
pip install requests
```

---

### Issue: "Connection refused to localhost:8765"

**Symptom**:
```
APIUnavailableError: Cannot reach telemetry API at http://localhost:8765/api/v1/runs
```

**Cause**: Telemetry API service is not running

**Impact**: Events will be buffered locally (no data loss)

**Fix**:
```bash
# Start API service in separate terminal
cd C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry
python telemetry_service.py
```

**Workaround**: Events will sync automatically when API comes back online

---

### Issue: "Telemetry path not found"

**Symptom**:
```
WARNING: Telemetry path not found: C:\...\local-telemetry\src
```

**Cause**: `TELEMETRY_SRC_PATH` environment variable is incorrect

**Fix**:
```bash
# Verify path exists
ls C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src

# Update .env file with correct path
TELEMETRY_SRC_PATH=C:/Users/prora/OneDrive/Documents/GitHub/local-telemetry/src
```

---

### Issue: Buffer directory filling up

**Symptom**: Large number of `.jsonl.ready` files accumulating

**Cause**: API has been down for extended period, events are queued

**Impact**: Disk space usage increases

**Fix**:
```bash
# Start API service
python telemetry_service.py

# Sync worker will automatically process backlog
# Monitor buffer directory:
watch ls -lh C:/telemetry/hugo-translator/buffer/
```

**Prevention**: Monitor API uptime, set up health check alerts

---

### Issue: "Database locked" error (should NOT occur with new architecture)

**Symptom**:
```
sqlite3.OperationalError: database is locked
```

**Cause**: This error indicates you're **not** using the new HTTP API architecture

**Fix**:
```bash
# Verify implementation uses TelemetryConfig.from_env()
grep -n "TelemetryConfig.from_env()" src/observability/telemetry_integration.py

# If not found, you may be using an old version
git log -1 --oneline
# Update to latest version
git pull origin main
```

---

## FAQ

### Q: Do I need to migrate my existing telemetry data?

**A**: No. Existing telemetry data in the SQLite database remains readable. The new architecture writes new events via HTTP API but can still read historical data from the database.

### Q: What happens if the API is down?

**A**: Events are automatically buffered locally in `.jsonl.active` files. When the API recovers, buffered events are synced automatically. **No data loss occurs.**

### Q: Can I disable telemetry entirely?

**A**: Yes. Set `TELEMETRY_ENABLED=false` in your `.env` file, or simply don't start the API service. Hugo-translator will continue working normally.

### Q: How do I know if telemetry is working?

**A**: Run `python scripts/verify_telemetry.py --check`. If it shows recent runs with correct field values, telemetry is working.

### Q: What if I'm running multiple agents?

**A**: Each agent should have its own `TELEMETRY_BUFFER_DIR`:
```bash
# hugo-translator
TELEMETRY_BUFFER_DIR=C:/telemetry/hugo-translator/buffer

# other-agent
TELEMETRY_BUFFER_DIR=C:/telemetry/other-agent/buffer
```

All agents share the same API service (`http://localhost:8765`).

### Q: How often do buffer files sync?

**A**: Buffer sync worker runs continuously in the background. Files are synced within 60 seconds when the API is available.

### Q: Can I query telemetry data programmatically?

**A**: Yes. Use the HTTP API endpoints:
```bash
# Get metrics
curl http://localhost:8765/metrics

# Query runs (Note: Query endpoints may not be implemented yet)
# For now, query the database directly (read-only)
```

### Q: What's the difference between METRICS_API_URL and TELEMETRY_API_URL?

**A**: `METRICS_API_URL` is the correct environment variable name used by local-telemetry. `TELEMETRY_API_URL` was used in early documentation but is incorrect. Always use `METRICS_API_URL`.

### Q: How do I rollback to the old architecture?

**A**: See [TELEMETRY_ROLLBACK_GUIDE.md](TELEMETRY_ROLLBACK_GUIDE.md). However, **rollback is not recommended** as the old architecture has corruption risks.

---

## Summary

**Current Status**: ✅ Hugo-translator already uses HTTP API + buffer architecture

**What You Need to Do**:
1. ✅ Verify environment variables are set correctly (`.env` file)
2. ✅ Ensure telemetry API service is running (`python telemetry_service.py`)
3. ✅ Install `requests` module in local-telemetry environment
4. ✅ Run validation tests (`python scripts/verify_telemetry.py --check`)

**What You DON'T Need to Do**:
- ❌ No code changes required
- ❌ No data migration required
- ❌ No manual database updates required

---

## Related Documentation

- [Telemetry Operations Guide](telemetry.md) - Day-to-day telemetry usage
- [Telemetry Rollback Guide](TELEMETRY_ROLLBACK_GUIDE.md) - How to rollback if needed
- [Local-Telemetry Migration Plan](../../plans/APP_MIGRATION_hugo-translator.md) - Technical migration details

---

## Support

**Issues or Questions?**
- Check [Troubleshooting](#troubleshooting) section above
- Review [FAQ](#faq) section above
- Check telemetry API service logs
- Run verification script: `python scripts/verify_telemetry.py --check`

---

**Last Updated**: 2025-12-20
**Architecture Version**: HTTP API + Buffer (MIG-008)
**Document Version**: 1.0
