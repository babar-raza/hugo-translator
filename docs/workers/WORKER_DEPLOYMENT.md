# Autonomous Workers Deployment Guide

## Overview

This system includes two autonomous workers that run scheduled translation tasks:

1. **Autonomous Content Translation Worker** - Translates Hugo content directories on a schedule
2. **TM Improvement Worker** - Uses LLM to improve Translation Memory entries

Both workers are configured to run **4 times per day** using **CUDA GPU acceleration**.

---

## Quick Start

### Step 1: Test Workers (Validation)

Run the comprehensive test script to validate both workers:

```bash
# Dry run (validation only - recommended first)
.venv\Scripts\python scripts\test_workers.py --dry-run

# Live test (actual execution with limited scope)
.venv\Scripts\python scripts\test_workers.py --live --site kb.aspose.net
```

**Expected Output:**
```
[PASS] - content_worker
[PASS] - tm_worker
[SUCCESS] All tests passed! Workers are ready for deployment.
```

### Step 2: Set Up Automatic Startup (Windows Task Scheduler)

**Run as Administrator:**

```powershell
# Open PowerShell as Administrator
powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
```

This creates two scheduled tasks that:
- Start automatically on system boot
- Run continuously in daemon mode
- Self-schedule 4 runs per day (08:00-23:00 Pacific Time)
- Use CUDA GPU acceleration
- Auto-restart on failure

### Step 3: Start Workers Now (Optional)

To start workers immediately without rebooting:

```powershell
# Start content translation worker
Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"

# Start TM improvement worker
Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"
```

---

## Configuration

### Schedule Configuration

Both workers use the same schedule (configured in [config/global.yaml](../../config/global.yaml)):

```yaml
schedule:
  runs_per_day: 4              # Run 4 times per day
  window_start: "08:00"        # Start at 8 AM Pacific Time
  window_end: "23:00"          # End at 11 PM Pacific Time
  timezone: "America/Los_Angeles"
  jitter_minutes: 15           # ±15 minutes random variation
```

**Calculated Run Times (approximate with jitter):**
- Run 1: ~08:00 AM (±15 min)
- Run 2: ~01:00 PM (±15 min)
- Run 3: ~06:00 PM (±15 min)
- Run 4: ~11:00 PM (±15 min)

### GPU/CUDA Configuration

Both workers use CUDA GPU acceleration:

```yaml
device: "cuda"                    # Force CUDA usage
max_gpu_memory_percent: 50        # Use 50% of VRAM (safe default)
preflight_check: true             # Check GPU before starting
abort_on_high_usage: true         # Skip run if GPU already busy
```

---

## Manual Worker Control

### Run Workers Manually (One-Time)

#### Content Translation Worker

```bash
# Oneshot mode (run once and exit)
.venv\Scripts\python -m src.workers.autonomous_content_translation_worker --mode oneshot

# With specific site
.venv\Scripts\python -m src.workers.autonomous_content_translation_worker --mode oneshot --site docs.aspose.net

# With CUDA and custom GPU limit
.venv\Scripts\python -m src.workers.autonomous_content_translation_worker --mode oneshot --device cuda --max-gpu-memory-percent 60
```

#### TM Improvement Worker

```bash
# Oneshot mode (run once and exit)
.venv\Scripts\python -m src.workers.tm_improvement_worker --mode oneshot

# With custom batch size
.venv\Scripts\python -m src.workers.tm_improvement_worker --mode oneshot --candidates-per-run 100

# With CUDA and custom settings
.venv\Scripts\python -m src.workers.tm_improvement_worker --mode oneshot --device cuda --max-gpu-memory-percent 60 --llm-provider ollama --llm-model llama2
```

### Run Workers in Daemon Mode (Background Service)

```bash
# Content worker daemon (self-scheduling)
.venv\Scripts\python -m src.workers.autonomous_content_translation_worker --mode daemon --runs-per-day 4

# TM worker daemon (self-scheduling)
.venv\Scripts\python -m src.workers.tm_improvement_worker --mode daemon --runs-per-day 4
```

---

## Task Scheduler Management

### View Scheduled Tasks

```powershell
# Open Task Scheduler GUI
taskschd.msc

# View task details (PowerShell)
Get-ScheduledTask -TaskName "HugoTranslator-*"
```

### Start/Stop Tasks

```powershell
# Start workers
Start-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Start-ScheduledTask -TaskName "HugoTranslator-TMWorker"

# Stop workers
Stop-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Stop-ScheduledTask -TaskName "HugoTranslator-TMWorker"
```

### Enable/Disable Tasks

```powershell
# Disable (prevent from running)
Disable-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Disable-ScheduledTask -TaskName "HugoTranslator-TMWorker"

# Enable (allow to run)
Enable-ScheduledTask -TaskName "HugoTranslator-ContentWorker"
Enable-ScheduledTask -TaskName "HugoTranslator-TMWorker"
```

### Remove Tasks

```powershell
# Remove scheduled tasks
Unregister-ScheduledTask -TaskName "HugoTranslator-ContentWorker" -Confirm:$false
Unregister-ScheduledTask -TaskName "HugoTranslator-TMWorker" -Confirm:$false
```

---

## Monitoring

### Check Worker Status

```powershell
# Check if workers are running
Get-ScheduledTask -TaskName "HugoTranslator-*" | Select-Object TaskName, State, LastRunTime, NextRunTime
```

### View Logs

Workers log to console output. To view logs:

1. **Task Scheduler Logs:**
   - Open `taskschd.msc`
   - Navigate to Task Scheduler Library
   - Right-click task → Properties → History tab

2. **Worker Output Logs (if configured):**
   ```bash
   # Check for log files in data/logs/
   ls data/logs/*.log
   ```

### Check Telemetry Database

```bash
# Query recent scheduled runs
.venv\Scripts\python -c "import sqlite3; conn = sqlite3.connect('data/benchmarks/benchmarks.db'); cursor = conn.cursor(); cursor.execute(\"SELECT * FROM translation_commits WHERE created_at > datetime('now', '-7 days') ORDER BY created_at DESC LIMIT 10\"); print(cursor.fetchall()); conn.close()"
```

---

## Troubleshooting

### Workers Not Starting

1. **Check Task Scheduler Status:**
   ```powershell
   Get-ScheduledTask -TaskName "HugoTranslator-*"
   ```

2. **Verify Python Virtual Environment:**
   ```bash
   .venv\Scripts\python --version
   ```

3. **Check CUDA Availability:**
   ```bash
   .venv\Scripts\python -c "import torch; print('CUDA:', torch.cuda.is_available())"
   ```

### Workers Failing During Execution

1. **Check Last Run Results:**
   ```powershell
   Get-ScheduledTaskInfo -TaskName "HugoTranslator-ContentWorker" | Select-Object LastTaskResult
   Get-ScheduledTaskInfo -TaskName "HugoTranslator-TMWorker" | Select-Object LastTaskResult
   ```

2. **Run Manual Test:**
   ```bash
   .venv\Scripts\python scripts\test_workers.py --live
   ```

3. **Check GPU Memory:**
   - Workers may abort if GPU already exceeds 50% usage
   - Run `nvidia-smi` to check GPU status

### TM Worker Issues

1. **Verify Ollama is Running:**
   ```bash
   curl http://localhost:11434/api/tags
   ```

2. **Check LLM Model Availability:**
   ```bash
   ollama list | grep llama2
   ```

---

## Advanced Configuration

### Customize Schedule

Edit [config/global.yaml](../../config/global.yaml) and modify:

```yaml
autonomous_content_translation:
  schedule:
    runs_per_day: 6              # Increase to 6 runs per day
    window_start: "06:00"        # Start earlier
    window_end: "23:59"          # End later
```

Then restart workers:
```powershell
Stop-ScheduledTask -TaskName "HugoTranslator-*"
Start-ScheduledTask -TaskName "HugoTranslator-*"
```

### Change GPU Memory Limit

Edit [config/global.yaml](../../config/global.yaml):

```yaml
execution:
  device: "cuda"
  max_gpu_memory_percent: 60    # Increase from 50% to 60%
```

Or override via command line:
```bash
.venv\Scripts\python -m src.workers.autonomous_content_translation_worker --mode daemon --max-gpu-memory-percent 60
```

### CPU-Only Mode

To run workers without GPU:

```yaml
# In global.yaml
execution:
  device: "cpu"
```

Or via command line:
```bash
.venv\Scripts\python -m src.workers.autonomous_content_translation_worker --mode daemon --device cpu
```

---

## File Reference

| File | Purpose |
|------|---------|
| [config/global.yaml](../../config/global.yaml) | Worker configuration (schedule, CUDA, resources) |
| [scripts/test_workers.py](../../scripts/test_workers.py) | Comprehensive worker testing script |
| [scripts/start_content_worker.bat](../../scripts/start_content_worker.bat) | Content worker startup script |
| [scripts/start_tm_worker.bat](../../scripts/start_tm_worker.bat) | TM worker startup script |
| [scripts/setup_task_scheduler.ps1](../../scripts/setup_task_scheduler.ps1) | Automated Task Scheduler setup |
| [src/workers/autonomous_content_translation_worker.py](../../src/workers/autonomous_content_translation_worker.py) | Content worker implementation |
| [src/workers/tm_improvement_worker.py](../../src/workers/tm_improvement_worker.py) | TM worker implementation |

---

## Security Notes

- Workers run with **SYSTEM** privileges for unattended execution
- VRAM limits prevent GPU resource exhaustion
- Preflight checks prevent conflicts with other GPU workloads
- Git auto-push is enabled (can be disabled in global.yaml)

---

## Support

For issues or questions:
1. Check [docs/observability/autonomous_workers_runbook.md](../observability/autonomous_workers_runbook.md)
2. Run diagnostic test: `.venv\Scripts\python scripts\test_workers.py --dry-run`
3. Review logs in Task Scheduler History
