# Graceful Shutdown & Telemetry Cleanup

## Overview

This document describes the graceful shutdown system implemented to handle process interruptions (Ctrl+C, kill signals) and ensure telemetry data is properly recorded even when hugo-translator is terminated mid-execution.

## Problem

When hugo-translator is killed with SIGINT (Ctrl+C) or SIGTERM, the process terminates immediately without running finally blocks. This leaves telemetry records in a "running" state with:
- `end_time: None`
- `status: "running"` (never updated to "success" or "failed")
- `metrics_json: None` (no token counts, TM hits, etc.)
- `items_discovered/succeeded/failed: 0`

## Solution

The solution consists of three components:

### 1. Signal Handlers (`graceful_shutdown.py`)

Signal handlers catch SIGINT and SIGTERM and gracefully close all active telemetry contexts before exiting.

**Key Features:**
- Global registry of active telemetry contexts
- Automatic context cleanup on signals
- Updates telemetry with cancellation status before closing
- Thread-safe context registration/unregistration
- Support for custom shutdown handlers

**Files:**
- `src/observability/graceful_shutdown.py` - Core implementation
- Integrated into `src/cli.py` (setup at startup)
- Integrated into `src/translation_engine/engine.py` (context registration)

### 2. Startup Cleanup (`telemetry_cleanup.py`)

Cleans up stale "running" records from previous interrupted sessions on application startup via the telemetry HTTP API.

**Key Features:**
- Marks old "running" records as "cancelled"
- Configurable max age (default: 1 hour)
- Uses HTTP API (respects single-writer pattern)
- Non-blocking (doesn't fail if API unavailable)
- Gracefully handles missing API endpoints (404)

**Files:**
- `src/observability/telemetry_cleanup.py` - API-based cleanup utility
- Called from `src/cli.py` at startup

**Architecture:**
- Uses GET /api/v1/runs to query stale runs
- Uses PATCH /api/v1/runs/{event_id} to mark as cancelled
- Requires telemetry API v2.1+ with these endpoints
- Falls back gracefully if endpoints not available

### 3. Context Registration

Telemetry contexts are automatically registered for shutdown tracking.

**Integration Points:**
- `translate_file()` - Registers file translation telemetry context
- `translate_directory()` - Registers directory translation telemetry context
- Both properly unregister on normal completion

## Usage

No changes needed for normal usage. The system is automatically activated.

### How It Works

1. **On Startup:**
   ```
   hugo-translator starts
   ↓
   setup_graceful_shutdown() registers signal handlers
   ↓
   cleanup_stale_runs() queries API for stale runs and marks as "cancelled"
   ```

2. **During Translation:**
   ```
   telemetry.track_translation_session() creates context
   ↓
   register_active_context(context) adds to global registry
   ↓
   Translation work happens
   ↓
   On normal completion: unregister_active_context(context)
   ```

3. **On Interruption (Ctrl+C):**
   ```
   User presses Ctrl+C
   ↓
   Signal handler catches SIGINT
   ↓
   For each active context:
     - set_metrics(error_summary="Process killed with SIGINT")
     - __exit__(None, None, None)
   ↓
   sys.exit(0)
   ```

## Testing

### Test 1: Normal Completion
```bash
# Run translation
python -m src.cli --site blog.aspose.net --input content/blog/example.md

# Check telemetry - should show "success" status with full metrics
docker exec local-telemetry-api python3 -c "
import sqlite3
conn = sqlite3.connect('/data/telemetry.sqlite')
cursor = conn.execute('SELECT status, end_time, output_summary FROM agent_runs ORDER BY created_at DESC LIMIT 1')
print(cursor.fetchone())
"
```

**Expected:** `('success', '2025-12-24T...', '37 translations, 0 errors')`

### Test 2: Graceful Interruption
```bash
# Start translation
python -m src.cli --site blog.aspose.net --input content/blog/ &
PID=$!

# Wait a few seconds, then interrupt
sleep 5
kill -SIGINT $PID

# Check telemetry - should show "cancelled" status with error summary
docker exec local-telemetry-api python3 -c "
import sqlite3
conn = sqlite3.connect('/data/telemetry.sqlite')
cursor = conn.execute('SELECT status, error_summary FROM agent_runs ORDER BY created_at DESC LIMIT 1')
print(cursor.fetchone())
"
```

**Expected:** `('cancelled', 'Process killed with SIGINT')`

**Note (GS-01/02/03):** As of the latest implementation, the following fields are now captured:
- `status`: Set to 'cancelled' (not 'running')
- `duration_ms`: Elapsed time from start to interrupt in milliseconds
- `end_time`: UTC timestamp when interrupt occurred (ISO 8601 format)

### Test 3: Startup Cleanup

**Note:** This test currently requires telemetry API v2.1+ with GET/PATCH endpoints. Until these endpoints are available, the cleanup function will gracefully degrade and log a warning.

```bash
# Manually insert a stale run (via direct database access for testing)
docker exec local-telemetry-api python3 -c "
import sqlite3
from datetime import datetime, timedelta, timezone

conn = sqlite3.connect('/data/telemetry.sqlite')
old_time = (datetime.now(timezone.utc) - timedelta(hours=2)).isoformat()
conn.execute('''
    INSERT INTO agent_runs (event_id, run_id, created_at, start_time, agent_name, job_type, status)
    VALUES ('test-stale-run', 'test-123', ?, ?, 'hugo-translator', 'translate_file', 'running')
''', (old_time, old_time))
conn.commit()
print('Inserted stale run')
"

# Run hugo-translator (triggers API-based cleanup)
# Set TELEMETRY_API_URL if needed
export TELEMETRY_API_URL=http://localhost:8765
python -m src.cli --site blog.aspose.net --input content/blog/example.md

# Check if stale run was cleaned up (via direct database access for verification)
docker exec local-telemetry-api python3 -c "
import sqlite3
conn = sqlite3.connect('/data/telemetry.sqlite')
cursor = conn.execute('SELECT status, error_summary FROM agent_runs WHERE run_id = \"test-123\"')
print(cursor.fetchone())
"
```

**Expected (when API v2.1+ available):** `('cancelled', 'Stale run cleaned up on startup ...')`

**Expected (current, API v2.0):** Warning logged: "Telemetry API cleanup endpoints not yet available (GET /api/v1/runs returned 404)"

## Implementation Details

### Signal Handler Flow

```python
_perform_graceful_shutdown(signum, frame):
    1. Set shutdown_in_progress flag
    2. Log signal received
    3. Lock contexts registry
    4. For each active context:
        a. Calculate duration_ms from context._start_time (GS-02)
        b. Generate end_time as UTC ISO 8601 timestamp (GS-03)
        c. Update metrics with:
           - run_status="cancelled" (GS-01)
           - duration_ms (GS-02)
           - end_time (GS-03)
           - output_summary, error_summary
        d. Call context.__exit__(None, None, None)
        e. Log success/failure
    5. Clear registry
    6. Call custom shutdown handlers
    7. Exit with code 0
```

### Context Registration Pattern

```python
# In translate_file() and translate_directory()
telemetry_run = telemetry_cm.__enter__()

# Register for shutdown tracking
try:
    from ..observability.graceful_shutdown import register_active_context
    register_active_context(telemetry_run)
except ImportError:
    pass  # Graceful degradation

# ... translation work ...

# Unregister on normal completion (in finally block)
try:
    from ..observability.graceful_shutdown import unregister_active_context
    unregister_active_context(telemetry_run)
except ImportError:
    pass
```

## Files Modified

### New Files
- `src/observability/graceful_shutdown.py` - Signal handler and context registry
- `src/observability/telemetry_cleanup.py` - Startup cleanup utility
- `docs/graceful_shutdown_telemetry.md` - This documentation

### Modified Files
- `src/cli.py` - Added setup_graceful_shutdown() and cleanup_stale_runs() calls
- `src/translation_engine/engine.py` - Added context registration/unregistration in translate_file() and translate_directory()

### Test Files
- `tests/unit/observability/test_telemetry_cleanup.py` - Unit tests for API-based cleanup (100% coverage)

## Benefits

1. **No Lost Data:** All telemetry data is recorded even when process is killed
2. **Clean Database:** Old stale runs are automatically cleaned up on startup (when API supports it)
3. **No User Changes:** Completely transparent to end users
4. **Graceful Degradation:** Works even if signal handlers fail or API unavailable
5. **Thread-Safe:** Safe for parallel translation operations
6. **Respects Architecture:** Uses HTTP API instead of direct database access (single-writer pattern)

## Limitations

1. **API Endpoints Required:** Cleanup requires telemetry API v2.1+ with GET/PATCH endpoints (currently not available)
2. **SIGKILL Handling:** Cannot catch `kill -9` (SIGKILL) - these records will remain stale
3. **Windows Support:** Signal handling may behave differently on Windows (uses different signal mechanisms)
4. **Temporary Degradation:** Until API endpoints are available, stale runs will not be cleaned automatically

## Future Improvements

1. **API Endpoints (IN PROGRESS):**
   - ✅ Hugo-translator now uses API-based cleanup (respects single-writer pattern)
   - ⏳ Telemetry API needs GET /api/v1/runs and PATCH /api/v1/runs/{event_id} endpoints
   - Once API is upgraded to v2.1+, cleanup will work automatically
2. **Periodic Updates:** Update telemetry progress every N files during long-running operations
3. **Health Checks:** Add telemetry health monitoring to detect stale runs automatically
4. **Retry Mechanism:** Retry telemetry updates on network failures
5. **Windows Signal Support:** Add proper signal handling for Windows (SIGBREAK, etc.)

## Troubleshooting

### Cleanup Not Running
**Symptom:** Old "running" records not being cleaned up on startup

**Solutions:**
- Check if telemetry API v2.1+ is available (with GET/PATCH endpoints)
- Check API URL is correct: `TELEMETRY_API_URL=http://localhost:8765`
- Check telemetry API is reachable: `curl http://localhost:8765/health`
- Check logs for cleanup errors: `grep "Telemetry cleanup" logs/hugo-translator.log`

### Signal Handler Not Firing
**Symptom:** Ctrl+C doesn't gracefully close telemetry

**Solutions:**
- Check signal handlers are registered: `grep "Graceful shutdown handlers" logs/hugo-translator.log`
- Verify Python signal module is available
- Check if another signal handler is overriding (e.g., debugger)

### Contexts Not Unregistering
**Symptom:** get_active_context_count() keeps growing

**Solutions:**
- Ensure unregister_active_context() is called in finally blocks
- Check for exceptions in finally blocks that prevent unregistration
- Verify import paths are correct (relative vs absolute imports)
