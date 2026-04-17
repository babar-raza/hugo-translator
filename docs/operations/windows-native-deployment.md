# Windows-Native Deployment

This is the primary production deployment path. Two autonomous workers run as Windows Task Scheduler jobs, translating content and improving the Translation Memory on a recurring schedule. No Docker or Redis required.

---

## Prerequisites

- Python 3.10+ installed system-wide (not just in a venv)
- Git available on PATH
- CUDA 12.1+ drivers (optional — workers fall back to CPU if GPU not available)
- Administrator access for Task Scheduler registration
- Content repository cloned locally (the Hugo site you want to translate)

---

## Step 1: Install the Package

```powershell
cd hugo-translator

# Create virtual environment
python -m venv .venv
.venv\Scripts\activate

# Install dependencies
pip install -r requirements/cpu.txt   # CPU-only
# OR for GPU:
pip install -r requirements/gpu.txt

# Install the package
pip install -e .
```

Verify:
```powershell
translate-hugo --help
```

---

## Step 2: Configure Content Roots

Edit `config/global.yaml` and set the content roots for your sites. Each site profile in `config/site_profiles/` has a `content_roots` field pointing to the cloned Hugo repository:

```yaml
# config/site_profiles/mysite.yaml
content_roots:
  - ${MYSITE_CONTENT}   # Expanded from environment variable
target_languages: [fr, de, es, ja]
source_lang: en
```

Then in `.env`:
```bash
MYSITE_CONTENT=C:\Users\you\content-repos\mysite
```

Environment variables in `content_roots` are expanded at profile load time.

---

## Step 3: Download Language Detection Model

The FastText language detection model is required for validation:

```powershell
# One-time download
python -c "
import urllib.request, os
os.makedirs('data/models/fasttext', exist_ok=True)
urllib.request.urlretrieve(
    'https://dl.fbaipublicfiles.com/fasttext/supervised-models/lid.176.bin',
    'data/models/fasttext/lid.176.bin'
)
print('Downloaded lid.176.bin')
"
```

---

## Step 4: Configure LLM (Optional — for TM Improvement Worker)

The TM improvement worker uses an LLM to improve translation quality. Configure in `config/global.yaml`:

```yaml
tm_improvement:
  llm:
    provider: openai_compatible
    base_url: https://your-llm-endpoint/v1
    model: recommended
    api_key_env: YOUR_LLM_API_KEY
```

Set the API key in `.env`:
```bash
YOUR_LLM_API_KEY=sk-...
```

If no LLM is configured, the TM improvement worker can be disabled (just don't start it).

---

## Step 5: Start Workers (Manual / Ad-Hoc)

To start workers immediately without Task Scheduler:

```powershell
# Content worker only (daemon mode, scheduled)
powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1

# Content worker + TM improvement worker
powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1 -TmWorker

# Skip the initial "run immediately" and wait for first scheduled slot
powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1 -NoImmediate
```

The script kills any existing worker processes before starting fresh ones.

---

## Step 6: Register with Task Scheduler (Production)

For permanent, automatic startup on login and on a schedule:

```powershell
# Run PowerShell as Administrator
Start-Process powershell -Verb RunAs -ArgumentList `
    "-ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1"
```

This registers four Task Scheduler tasks:
- `HugoTranslator-ContentWorker` — runs content translation on schedule
- `HugoTranslator-TMWorker` — runs TM improvement on schedule
- `HugoTranslator-Watchdog` — monitors workers, restarts on crash (max 5 restarts/hour)
- `HugoTranslator-AutonomousVerification` — periodic quality checks

Verify registration:
```powershell
Get-ScheduledTask | Where-Object TaskName -like "HugoTranslator-*" | Select-Object TaskName, State
```

---

## Monitoring

### Heartbeat Files

Both workers write JSON heartbeat files every minute while running:

```powershell
# Content worker heartbeat
Get-Content data\logs\content_worker.heartbeat | ConvertFrom-Json

# TM worker heartbeat
Get-Content data\logs\tm_worker.heartbeat | ConvertFrom-Json
```

Heartbeat fields: `timestamp`, `pid`, `status`, `last_success_ts`, `last_error_ts`, `current_site`

### Health Check Script

```powershell
scripts\check_worker_health.ps1
```

Returns OK, WARN, or CRIT per worker. Rules:
- Heartbeat file missing or > 15 min old → **CRIT**
- `last_error_ts` newer than `last_success_ts` → **WARN**
- Worker stuck in `starting` state > 6h with fresh heartbeat → **WARN**

### Log Files

```powershell
# Tail content worker log
Get-Content data\logs\content_worker.log -Wait -Tail 30

# Tail TM worker log
Get-Content data\logs\tm_worker.log -Wait -Tail 30
```

---

## Known Issues and Workarounds

### `index.lock` stale lock in content repo

If a git operation is interrupted, the content repository's `index.lock` file may be left behind, blocking all future git operations:

```powershell
Remove-Item "C:\path\to\content-repo\.git\index.lock" -Force
```

### Task Scheduler tasks re-enable themselves

Windows Task Scheduler sometimes re-enables tasks after `Disable-ScheduledTask`. To permanently disable all HugoTranslator tasks:

```powershell
# Run as Administrator
powershell -ExecutionPolicy Bypass -File scripts\_disable_tasks.ps1
```

### `taskkill` fails in Git Bash

Use Python as an alternative:

```python
import os
os.kill(PID, 9)
```

Or use `Stop-Process` in PowerShell:

```powershell
Stop-Process -Id PID -Force
```

### Administrator elevation required

Task Scheduler setup (`setup_task_scheduler.ps1`) requires an Administrator PowerShell session. Running without elevation will exit with an error immediately.

### `[TimeSpan]::MaxValue` overflows Task Scheduler XML

The setup script uses `New-TimeSpan -Days 9999` instead of `[TimeSpan]::MaxValue` for execution time limits. This is intentional — MaxValue overflows the Task Scheduler XML schema.

---

## Disabling Workers

To stop all workers without unregistering them from Task Scheduler:

```powershell
# Kill running processes (finds by PID file)
scripts\start_workers.ps1  # Starting fresh workers kills the old ones first

# Or directly:
$pid = [int](Get-Content data\logs\content_worker_daemon.pid)
Stop-Process -Id $pid -Force
```

To permanently disable scheduled tasks (admin required):

```powershell
powershell -ExecutionPolicy Bypass -File scripts\_disable_tasks.ps1
```

---

## Next Steps

- [AGENTS.md](../../AGENTS.md) — Full worker reference (flags, modes, VRAM management)
- [DAILY_OPERATIONS.md](DAILY_OPERATIONS.md) — Day-to-day operational tasks
- [docs/user-guide/setup.md](../user-guide/setup.md) — Full installation reference
