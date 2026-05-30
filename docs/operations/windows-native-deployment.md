# Windows-Native Deployment

The primary production deployment path for `hugo-translator-gitlab`. A single **orchestrator**
process manages all workers via trigger-based oneshot launching. No Docker, no Redis, no
daemon-per-worker required.

---

## Architecture

```
HugoTranslatorGitlab-Orchestrator (Windows Scheduled Task)
  └─ worker_orchestrator.py  [daemon, every 15 min check cycle]
       ├─ content_worker      [oneshot, when retranslate_queue non-empty OR .md files changed]
       ├─ tm_improvement_worker [oneshot, when improvement_queue non-empty]
       └─ verification_worker  [oneshot, after content_worker runs OR config changes]
```

The scheduled task fires at logon **and** repeats every 5 minutes. With
`MultipleInstances = IgnoreNew`, only one orchestrator runs at a time. If it crashes,
it restarts within 5 minutes automatically.

---

## Prerequisites

- Python 3.10+ in `.venv` (repo includes `.venv` setup)
- Git available on PATH
- CUDA 12.1+ drivers (optional — workers fall back to CPU automatically)
- Administrator access once for Task Scheduler registration
- Content repositories cloned locally:
  - `aspose.net` content → local path set in `.env` as `ASPOSE_NET_CONTENT`
  - `aspose.org` content → local path set in `.env` as `ASPOSE_ORG_CONTENT`

---

## Step 1: Configure `.env`

The orchestrator loads `.env` at startup and passes all variables to subprocess workers.
Edit `.env` in the project root:

```
AGENT_METRICS_ENDPOINT=<your-endpoint>
AGENT_METRICS_TOKEN=<your-token>
ASPOSE_NET_CONTENT=C:\Users\you\path\to\aspose.net\content
ASPOSE_ORG_CONTENT=C:\Users\you\path\to\aspose.org\content
```

`ASPOSE_NET_CONTENT` and `ASPOSE_ORG_CONTENT` are required for the content worker to
resolve site profiles. If they are absent, the orchestrator logs a WARNING at startup and
the content worker exits with 0 translations every cycle.

---

## Step 2: Register the Startup Task (once, as Administrator)

```powershell
# Open PowerShell as Administrator
Start-Process powershell -Verb RunAs -ArgumentList `
    "-ExecutionPolicy Bypass -File scripts\register_startup_task.ps1"
```

This registers `HugoTranslatorGitlab-Orchestrator` with:
- Trigger 1: at logon
- Trigger 2: repeat every 5 minutes (auto-restart watchdog)
- `MultipleInstances = IgnoreNew` — silent skip if already running
- `ExecutionTimeLimit = 0` — no time limit (daemon)
- Logs directly to `data\logs\orchestrator_daemon.log`

Verify:
```powershell
Get-ScheduledTask -TaskName "HugoTranslatorGitlab-Orchestrator" | Select-Object TaskName, State
```

Expected: `State = Ready`

---

## Step 3: Start the Orchestrator Now (Without Rebooting)

```powershell
Start-ScheduledTask -TaskName "HugoTranslatorGitlab-Orchestrator"
```

Or start manually (useful for debugging):
```powershell
cd "C:\path\to\hugo-translator-gitlab"
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --check-interval 900 --log-level INFO
```

---

## Monitoring

### Orchestrator Status

```powershell
cd "C:\path\to\hugo-translator-gitlab"
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --status
```

Sample output:
```
=== Orchestrator Status (2026-05-30T10:00:00+00:00) ===

  content_worker: DEAD (no PID file) enabled trigger=ACTIVE state=stopped
  tm_improvement_worker: ALIVE (PID 12345) enabled trigger=inactive state=running
  verification_worker: DEAD (no PID file) enabled trigger=inactive state=stopped

  Queue data/retranslate_queue.jsonl: 820 entries
  Queue data/tm/improvement_queue.jsonl: 7277 entries
  Queue data/quarantine.jsonl: 0 entries

  Circuit breaker: 2/5 launches/hour (closed)
```

For JSON output (useful for scripting):
```powershell
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --status --json
```

### Log Files

```powershell
# Orchestrator log (all cycle events)
Get-Content data\logs\orchestrator_daemon.log -Wait -Tail 30

# Content worker log
Get-Content data\logs\content_worker.log -Wait -Tail 30

# TM improvement worker log
Get-Content data\logs\tm_worker.log -Wait -Tail 30
```

### Event Log

The orchestrator appends structured events to `data/logs/worker_events.jsonl`:

```powershell
# Last 5 events
Get-Content data\logs\worker_events.jsonl | Select-Object -Last 5 | ForEach-Object { $_ | ConvertFrom-Json }
```

Event types: `worker_launched`, `dry_run_launch`, `launch_failed`, `no_work_available`, `cycle_error`

### Heartbeat Files

Workers write JSON heartbeat files while running:

```powershell
# Content worker heartbeat
Get-Content data\logs\content_worker.heartbeat | ConvertFrom-Json

# TM worker heartbeat
Get-Content data\logs\tm_worker.heartbeat | ConvertFrom-Json
```

---

## Stopping the Orchestrator

```powershell
# Via Task Scheduler (stops and does not restart until next trigger)
Stop-ScheduledTask -TaskName "HugoTranslatorGitlab-Orchestrator"

# Kill any running worker subprocesses separately if needed
$pid = [int](Get-Content data\logs\content_worker.pid -ErrorAction SilentlyContinue)
if ($pid) { Stop-Process -Id $pid -Force -ErrorAction SilentlyContinue }
```

---

## Troubleshooting

### Content worker runs but translates 0 files

**Cause:** `ASPOSE_NET_CONTENT` / `ASPOSE_ORG_CONTENT` not set.

Check orchestrator log for:
```
Required env var ASPOSE_NET_CONTENT is not set — content_worker will skip all sites
```

**Fix:** Add the vars to `.env`, then restart the orchestrator.

---

### Orchestrator shows "No workers launched" every cycle

Check trigger state:
```powershell
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --status
```

- `trigger=inactive` for content_worker → retranslate queue is empty and no `.md` file changes
  detected. This is normal when all content is up to date.
- `trigger=ACTIVE` but worker `ALIVE` → worker is still running from a previous cycle (normal).
- Unresolved env var warning in log → fix `.env` (see above).

---

### Orchestrator died and didn't restart

The 5-minute repeat trigger should restart within 5 minutes. If it doesn't:

```powershell
# Check task state
Get-ScheduledTask -TaskName "HugoTranslatorGitlab-Orchestrator" | Select-Object State

# Check last run result (0 = success, non-zero = error)
(Get-ScheduledTaskInfo -TaskName "HugoTranslatorGitlab-Orchestrator").LastTaskResult

# Start manually
Start-ScheduledTask -TaskName "HugoTranslatorGitlab-Orchestrator"
```

Unhandled exceptions in the check cycle are now logged in `orchestrator_daemon.log` with
full traceback and the cycle recovers — check the log for `cycle_error` events.

---

### Stale PID file blocks a worker

If a worker died and its PID file was not cleaned up, the orchestrator auto-detects the
dead PID and removes it on the next cycle:
```
Worker content_worker: removed stale PID file data/logs/content_worker.pid (dead PID 12345)
```

No manual intervention needed.

---

### Retranslate queue not draining

Check `data/logs/content_worker.log` for purity failures:
```
Expected hr, detected fr (confidence: 97%)
output reached N tokens (limit: ...)
```

If purity failures are systemic, verify `max_new_tokens` in
`src/model_runtime/registry.py` is at least 512 (default as of commit `a8ce748`).
The 256-token limit caused truncation → wrong-language detection for many language pairs.

To reset retry counts for stuck entries (only run after fixing the root cause):
```bash
python -c "
import json, pathlib
q = pathlib.Path('data/retranslate_queue.jsonl')
lines = [json.loads(l) for l in q.read_text().splitlines() if l.strip()]
for e in lines: e['retry_count'] = 0
q.write_text('\n'.join(json.dumps(e) for e in lines) + '\n')
print(f'Reset {len(lines)} entries')
"
```

---

### Migrating from the old `hugo-translator` (non-gitlab) tasks

If you previously ran `HugoTranslator-ContentWorker`, `HugoTranslator-TMWorker`,
`HugoTranslator-Watchdog`, etc., these are from the retired `hugo-translator` repository
and conflict with the new orchestrator.

Run `scripts/register_startup_task.ps1` as Administrator — it deletes the old tasks before
registering `HugoTranslatorGitlab-Orchestrator`.

If the old watchdog script (`hugo-translator/scripts/worker_watchdog.ps1`) keeps recreating
the old tasks, neuter it:
```powershell
Set-Content "C:\path\to\hugo-translator\scripts\worker_watchdog.ps1" `
    "# RETIRED: hugo-translator replaced by hugo-translator-gitlab.`nexit 0"
```

---

## Key Files

| File | Purpose |
|------|---------|
| `.env` | Environment variables (content repo paths, API keys). Gitignored. |
| `config/workers.yaml` | Worker registry: triggers, cooldowns, commands |
| `config/global.yaml` | Global settings: device, batch sizes, LLM config |
| `scripts/register_startup_task.ps1` | Register `HugoTranslatorGitlab-Orchestrator` (run as Administrator) |
| `scripts/start_orchestrator.bat` | Manual start script (sets env vars, useful for dev) |
| `src/workers/worker_orchestrator.py` | Orchestrator implementation |
| `data/logs/orchestrator_daemon.log` | Orchestrator log (appended by `--log-file`) |
| `data/logs/orchestrator.state.json` | Orchestrator cycle state (last launch times, circuit breaker) |
| `data/logs/worker_events.jsonl` | Structured event log for all launch/skip events |
| `data/retranslate_queue.jsonl` | Files queued for retranslation (purity failures) |
| `data/quarantine.jsonl` | Files that failed 3+ retranslation attempts |
| `data/tm/improvement_queue.jsonl` | TM entries queued for LLM improvement |

---

## Next Steps

- [AGENTS.md](../../AGENTS.md) — Full worker reference (flags, modes, VRAM management)
- [docs/operations/DAILY_OPERATIONS.md](DAILY_OPERATIONS.md) — Day-to-day operational tasks
- [config/workers.yaml](../../config/workers.yaml) — Worker triggers and scheduling config
