# Autonomous Workers - Setup Summary

**Date:** 2026-01-17
**Status:** ✅ READY FOR DEPLOYMENT

---

## What Was Done

### 1. ✅ Worker Validation

Both autonomous workers were tested and validated:

```bash
.venv\Scripts\python scripts\test_workers.py --dry-run
```

**Results:**
- ✅ Content Translation Worker: PASS
- ✅ TM Improvement Worker: PASS

### 2. ✅ Configuration for 4+ Runs Per Day with CUDA

Updated [config/global.yaml](config/global.yaml):

**Content Translation Worker:**
- Runs per day: **4**
- Time window: **08:00 - 23:00 Pacific Time**
- Device: **CUDA (GPU acceleration)**
- VRAM limit: **50%**
- Jitter: **±15 minutes**

**TM Improvement Worker:**
- Runs per day: **4**
- Time window: **08:00 - 23:00 Pacific Time**
- Device: **CUDA (GPU acceleration)**
- VRAM limit: **50%**
- LLM: **Ollama/llama2**
- Jitter: **±15 minutes**

### 3. ✅ Startup Scripts Created

**Batch Scripts (Windows):**
- [scripts/start_content_worker.bat](scripts/start_content_worker.bat) - Starts content translation worker in daemon mode
- [scripts/start_tm_worker.bat](scripts/start_tm_worker.bat) - Starts TM improvement worker in daemon mode

**PowerShell Setup Script:**
- [scripts/setup_task_scheduler.ps1](scripts/setup_task_scheduler.ps1) - Automated Task Scheduler configuration

**Test Script:**
- [scripts/test_workers.py](scripts/test_workers.py) - Comprehensive worker testing and validation

### 4. ✅ Documentation

Created comprehensive deployment guide:
- [docs/workers/WORKER_DEPLOYMENT.md](docs/workers/WORKER_DEPLOYMENT.md)

---

## Next Steps - Deploy Workers

### Step 1: Set Up Automatic Startup (REQUIRED)

**Run as Administrator:**

```powershell
powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
```

This will:
- Create two Windows scheduled tasks
- Configure automatic startup on system boot
- Enable auto-restart on failure
- Set workers to run with SYSTEM privileges

### Step 2: Start Workers Immediately (Optional)

To start workers now without waiting for system reboot:

```powershell
# Open PowerShell as Administrator
Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"
```

### Step 3: Verify Workers Are Running

Check worker status:

```powershell
Get-ScheduledTask -TaskName "HugoTranslator-*" | Select-Object TaskName, State, LastRunTime, NextRunTime
```

**Expected Output:**
```
TaskName                        State   LastRunTime        NextRunTime
--------                        -----   -----------        -----------
HugoTranslator-ContentWorker    Running 1/17/2026 3:57 PM  1/17/2026 8:00 PM
HugoTranslator-TMWorker         Running 1/17/2026 3:57 PM  1/17/2026 8:00 PM
```

---

## Worker Schedule

Both workers will run **4 times per day** at approximately:

| Run # | Time (Pacific) | Notes |
|-------|----------------|-------|
| 1 | ~08:00 AM | ±15 min jitter |
| 2 | ~01:00 PM | ±15 min jitter |
| 3 | ~06:00 PM | ±15 min jitter |
| 4 | ~11:00 PM | ±15 min jitter |

**Total: 8 automated runs per day** (4 content + 4 TM improvement)

---

## Features

### System Restart Persistence ✅

Workers will automatically:
- Start when the system boots
- Resume scheduling after restart
- Continue running even if no user is logged in

### GPU Acceleration ✅

Both workers use CUDA GPU acceleration:
- Device: `cuda`
- VRAM Limit: 50% of total GPU memory
- Preflight check: Skips run if GPU already busy (>50%)
- Safe for concurrent workloads

### Autonomous Operation ✅

Workers operate fully autonomously:
- Self-scheduling within daily time window
- Random jitter to avoid predictable timing
- Auto-commit and push translation results
- Continue on failure (resilient)
- Telemetry tracking for monitoring

### Resource Management ✅

Smart resource management:
- VRAM budgeting prevents GPU OOM
- Preflight checks avoid conflicts
- Post-run cleanup frees resources
- Configurable batch sizes per worker

---

## Quick Reference Commands

### Start Workers Now
```powershell
Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"
```

### Stop Workers
```powershell
Stop-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Stop-ScheduledTask -TaskName "HugoTranslator-TMWorker"
```

### Check Status
```powershell
Get-ScheduledTask -TaskName "HugoTranslator-*" | Format-Table TaskName, State, LastRunTime, NextRunTime
```

### View Logs
```powershell
# Open Task Scheduler GUI
taskschd.msc

# Navigate to: Task Scheduler Library
# Right-click task → Properties → History tab
```

### Test Workers Manually
```bash
# Dry run (validation only)
.venv\Scripts\python scripts\test_workers.py --dry-run

# Live test (actual execution)
.venv\Scripts\python scripts\test_workers.py --live
```

---

## Files Modified/Created

### Modified
- ✏️ [config/global.yaml](config/global.yaml) - Added worker configuration sections

### Created
- 📄 [scripts/test_workers.py](scripts/test_workers.py) - Comprehensive testing script
- 📄 [scripts/start_content_worker.bat](scripts/start_content_worker.bat) - Content worker startup
- 📄 [scripts/start_tm_worker.bat](scripts/start_tm_worker.bat) - TM worker startup
- 📄 [scripts/setup_task_scheduler.ps1](scripts/setup_task_scheduler.ps1) - Automated setup
- 📄 [docs/workers/WORKER_DEPLOYMENT.md](docs/workers/WORKER_DEPLOYMENT.md) - Deployment guide
- 📄 [WORKERS_SETUP_SUMMARY.md](WORKERS_SETUP_SUMMARY.md) - This file

---

## Important Notes

### Prerequisites

1. **Ollama Must Be Running** (for TM improvement worker)
   ```bash
   # Verify Ollama is accessible
   curl http://localhost:11434/api/tags
   ```

2. **llama2 Model Required** (for TM improvement worker)
   ```bash
   # Check if model is available
   ollama list | grep llama2

   # If not available, download it
   ollama pull llama2
   ```

3. **CUDA/GPU Available**
   ```bash
   # Verify CUDA is working
   .venv\Scripts\python -c "import torch; print('CUDA Available:', torch.cuda.is_available())"
   ```

### Known Limitations

- Workers require Windows Task Scheduler (Windows 7+)
- SYSTEM account needs GPU access (usually available by default)
- Ollama must be running as a service for TM worker
- Git auto-push requires SSH keys or credential manager configured

---

## Rollback

To disable or remove workers:

```powershell
# Disable workers (keeps tasks but prevents execution)
Disable-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Disable-ScheduledTask -TaskName "HugoTranslator-TMWorker"

# Remove workers completely
Unregister-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -Confirm:$false
Unregister-ScheduledTask -TaskName "HugoTranslator-TMWorker" -Confirm:$false
```

To revert configuration changes:
```bash
git checkout config/global.yaml
```

---

## Support

For detailed deployment instructions and troubleshooting:
- See [docs/workers/WORKER_DEPLOYMENT.md](docs/workers/WORKER_DEPLOYMENT.md)
- See [docs/observability/autonomous_workers_runbook.md](docs/observability/autonomous_workers_runbook.md)

For issues:
1. Run diagnostic test: `.venv\Scripts\python scripts\test_workers.py --dry-run`
2. Check Task Scheduler History in `taskschd.msc`
3. Verify CUDA availability and Ollama status
