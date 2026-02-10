# Machine Restart Recovery — Fully Configured ✅

**Date**: 2026-02-08
**Status**: System will **fully auto-recover** on machine restart

---

## What Happens When You Restart the Machine

### Boot Sequence (Automatic, No Manual Intervention Required)

1. **Ollama Starts** (via Startup folder shortcut) ✅
   - Location: `C:\Users\prora\AppData\Roaming\Microsoft\Windows\Start Menu\Programs\Startup\`
   - Process: `ollama.exe serve`
   - Listens on: `http://localhost:11434`
   - Available models: 33 (including `qwen3:14b`)

2. **Task Scheduler Triggers** (2 tasks with `AtStartup` triggers, 1 task with 5-minute repetition) ✅
   - `HugoTranslator-ContentWorker` starts in daemon mode (AtStartup trigger)
   - `HugoTranslator-TMWorker` starts in daemon mode (AtStartup trigger)
   - `HugoTranslator-Watchdog` starts with 5-minute repetition (Once trigger with repetition)

3. **Worker Initialization** ✅
   - **Content Worker**:
     - Preflight checks (CUDA, disk space, config)
     - Loads Translation Memory (L1/L2/L3)
     - Writes PID file and heartbeat
     - Starts background heartbeat thread (60s interval)
     - Enters daemon loop (4 runs/day, 08:00-23:00 window)

   - **TM Worker**:
     - Preflight checks (CUDA, disk space, Ollama connectivity)
     - Attempts LLM connection to Ollama (with retry + auto-discovery)
     - Loads Translation Memory
     - Writes PID file and heartbeat
     - Starts background heartbeat thread (60s interval)
     - Enters daemon loop (4 runs/day, 08:00-23:00 window)

4. **Watchdog Monitoring Begins** ✅
   - Checks worker heartbeats every 5 minutes
   - Restarts dead workers (with circuit breaker: max 5 restarts/hour)
   - Respects "shutting_down" status (5-minute grace period)

---

## Failure Recovery Scenarios

### Scenario 1: Ollama Slow to Start
**Problem**: TM Worker starts before Ollama is ready
**Recovery**:
1. TM Worker setup fails (connection refused on port 11434)
2. Exponential backoff retry kicks in (attempt 1/5, wait 30s)
3. Retries up to 5 times over ~10 minutes
4. Ollama finishes starting during retry window
5. TM Worker setup succeeds on retry attempt 2-5
6. Worker continues normally

**Timeline**: 30s - 10min recovery (automatic)

---

### Scenario 2: Ollama Fails to Start
**Problem**: Ollama shortcut broken or executable missing
**Recovery**:
1. TM Worker exhausts 5 retry attempts (~10 min)
2. TM Worker exits with error
3. Watchdog detects dead worker (within 5 min)
4. Watchdog restarts TM Worker
5. TM Worker retries setup again (5 attempts)
6. Cycle repeats up to 5 times/hour
7. Circuit breaker trips after 5 restarts
8. Alert logged: "CIRCUIT BREAKER OPEN... Will auto-reset at HH:mm:ss"

**Timeline**: ~1 hour until circuit breaker trips
**Manual Fix Required**: Start Ollama manually → Circuit breaker auto-resets → Workers resume

---

### Scenario 3: Worker Crashes During Run
**Problem**: Worker crashes mid-translation (OOM, exception, etc.)
**Recovery**:
1. Worker process dies (heartbeat stops updating)
2. Watchdog detects stale heartbeat (within 5 min)
3. Watchdog restarts worker via Task Scheduler
4. Worker restarts fresh (setup retry if transient failure)
5. Consecutive failure counter resets on successful run

**Timeline**: 5-10 min recovery (automatic)
**Edge Case**: If crash is persistent (bug, bad config), circuit breaker trips after 5 restarts/hour

---

### Scenario 4: Graceful Shutdown
**Problem**: User/system sends SIGTERM/SIGINT to worker
**Recovery**:
1. Worker catches signal (SIGINT/SIGTERM/SIGBREAK)
2. Worker writes heartbeat: `status=shutting_down`
3. Worker stops background heartbeat thread
4. Worker cleans up telemetry contexts
5. Worker exits cleanly (exit code 0)
6. Watchdog sees `status=shutting_down`, waits 5 minutes before restarting
7. After 5 minutes, watchdog restarts worker
8. Worker starts fresh

**Timeline**: 5 min grace period before restart (intentional delay)

---

## Current Configuration Status

### Task Scheduler
| Task | State | Trigger | Action |
|------|-------|---------|--------|
| HugoTranslator-ContentWorker | Running | AtStartup | `python.exe -m src.workers.autonomous_content_translation_worker --mode daemon ...` |
| HugoTranslator-TMWorker | Running | AtStartup | `python.exe -m src.workers.tm_improvement_worker --mode daemon --llm-model qwen3:14b ...` |
| HugoTranslator-Watchdog | Ready | Every 5 min | `powershell.exe -ExecutionPolicy Bypass -File worker_watchdog.ps1` |

**All tasks**:
- Run as current user (Interactive)
- Auto-restart on failure (up to 3 times, 5-minute interval)
- Working directory: `C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator`

### Auto-Start Services
| Service | Method | Status |
|---------|--------|--------|
| Ollama | Startup folder shortcut | ✅ Configured |
| Content Worker | Task Scheduler (AtStartup) | ✅ Configured |
| TM Worker | Task Scheduler (AtStartup) | ✅ Configured |
| Watchdog | Task Scheduler (AtStartup + 5min repeat) | ✅ Configured |

---

## Robustness Features Active

### P0: Crash Prevention
- ✅ **Model Compatibility**: `qwen3:14b` installed and default
- ✅ **Setup Retry**: 5 attempts with exponential backoff (30s-300s)
- ✅ **LLM Auto-Discovery**: Fallback to any available Ollama model

### P1: False-Positive Prevention
- ✅ **Background Heartbeat**: 60s interval prevents watchdog killing healthy workers
- ✅ **Signal Handling**: Graceful shutdown writes "shutting_down" status
- ✅ **Watchdog Awareness**: 5-minute grace period for shutdown in progress

### P2: Self-Healing
- ✅ **Overlap Protection**: 300s minimum gap between daemon runs
- ✅ **Consecutive Failure Tracking**: Exit only after 10 consecutive failures
- ✅ **Circuit Breaker Logging**: Reset time displayed when tripped

---

## Post-Restart Verification Steps (Optional)

### Immediate Verification (T+2 minutes)
```powershell
# Check if all processes started
Get-Process -Name ollama, python -ErrorAction SilentlyContinue | Format-Table Name, Id, CPU, WorkingSet -AutoSize

# Check heartbeat freshness
$hb1 = Get-Content "data\logs\content_worker.heartbeat" | ConvertFrom-Json
$hb2 = Get-Content "data\logs\tm_worker.heartbeat" | ConvertFrom-Json
$age1 = (New-TimeSpan -Start $hb1.timestamp -End (Get-Date)).TotalSeconds
$age2 = (New-TimeSpan -Start $hb2.timestamp -End (Get-Date)).TotalSeconds
Write-Host "Content heartbeat: ${age1}s old (fresh if < 120s)"
Write-Host "TM heartbeat: ${age2}s old (fresh if < 120s)"
```

### Extended Verification (T+10 minutes)
```powershell
# Check circuit breaker state
if (Test-Path "data\watchdog_state.json") {
    Get-Content "data\watchdog_state.json" | ConvertFrom-Json
} else {
    Write-Host "Circuit breaker: CLEAR (no restarts)"
}

# Check worker logs for errors
Get-Content "data\logs\content_worker.log" -Tail 20
Get-Content "data\logs\tm_worker.log" -Tail 20
Get-Content "data\logs\watchdog.log" -Tail 20
```

---

## Summary

✅ **Fully configured for unattended operation**
✅ **Auto-recovery from all common failure modes**
✅ **Circuit breaker prevents infinite restart loops**
✅ **No manual intervention required on restart**

**Expected Downtime on Restart**: 0-2 minutes (normal boot time)
**Failure Recovery Time**: 5-10 minutes (automatic via watchdog)
**Circuit Breaker Trip Point**: 5 crashes within 60 minutes

---

**Last Updated**: 2026-02-08
**Related Documents**:
- [WORKER_ROBUSTNESS_IMPLEMENTATION_COMPLETE.md](WORKER_ROBUSTNESS_IMPLEMENTATION_COMPLETE.md) - Full implementation details
- [C:\Users\prora\.claude\plans\agile-weaving-book.md](C:\Users\prora\.claude\plans\agile-weaving-book.md) - Original robustness plan
