# Worker Deployment Guide

## Overview

All workers are managed by a single **orchestrator** process
(`src/workers/worker_orchestrator.py`). The orchestrator runs as a Windows Scheduled Task,
evaluates triggers every 15 minutes, and launches workers as oneshot subprocesses when their
conditions are met. Workers do not run as daemons — they start, do their work, and exit.

### Workers

| Worker | Module | Trigger | Cooldown |
|--------|--------|---------|----------|
| `content_worker` | `autonomous_content_translation_worker` | `retranslate_queue` non-empty OR `.md` file changes | 30 min |
| `tm_improvement_worker` | `tm_improvement_worker` | `improvement_queue` non-empty | 60 min |
| `verification_worker` | `autonomous_verification_worker` | config `.yaml` changed OR after content_worker runs | 2 hours |

Triggers and cooldowns are configured in [`config/workers.yaml`](../../config/workers.yaml).

---

## Quick Start

### 1. Set up `.env`

```
ASPOSE_NET_CONTENT=C:\path\to\aspose.net\content
ASPOSE_ORG_CONTENT=C:\path\to\aspose.org\content
```

These are loaded by the orchestrator at startup and inherited by all workers.

### 2. Register the orchestrator task (as Administrator, once)

```powershell
Start-Process powershell -Verb RunAs -ArgumentList `
    "-ExecutionPolicy Bypass -File scripts\register_startup_task.ps1"
```

### 3. Start immediately

```powershell
Start-ScheduledTask -TaskName "HugoTranslatorGitlab-Orchestrator"
```

For full setup details see [windows-native-deployment.md](../operations/windows-native-deployment.md).

---

## Orchestrator Commands

```powershell
# Check status of all workers + queue depths
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --status

# Run one check cycle and exit (useful for testing)
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --once --log-level INFO

# Dry run — evaluate triggers but don't launch anything
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --once --dry-run

# Continuous daemon (same as what the scheduled task runs)
.venv\Scripts\python.exe -m src.workers.worker_orchestrator --check-interval 900 --log-level INFO
```

---

## Running Workers Manually

Workers can be run directly without the orchestrator:

```bash
# Content translation worker (one shot)
.venv\Scripts\python.exe -m src.workers.autonomous_content_translation_worker --mode oneshot

# Limit to one site
.venv\Scripts\python.exe -m src.workers.autonomous_content_translation_worker --mode oneshot --site docs.aspose.net.words

# TM improvement worker (one shot)
.venv\Scripts\python.exe -m src.workers.tm_improvement_worker --mode oneshot

# Verification worker (one shot)
.venv\Scripts\python.exe -m src.workers.autonomous_verification_worker --mode oneshot
```

---

## Log Files

| File | Written by | Content |
|------|-----------|---------|
| `data/logs/orchestrator_daemon.log` | Orchestrator | All cycle events, launch decisions, errors |
| `data/logs/worker_events.jsonl` | Orchestrator | Structured JSON events per cycle |
| `data/logs/content_worker.log` | content_worker | Per-file translation log |
| `data/logs/tm_worker.log` | tm_improvement_worker | TM improvement log |
| `data/logs/orchestrator.state.json` | Orchestrator | Cycle state (last launches, circuit breaker) |

---

## Queue Files

| File | Purpose |
|------|---------|
| `data/retranslate_queue.jsonl` | Files to retranslate (purity failures, up to 3 retries) |
| `data/quarantine.jsonl` | Files that failed 3+ retranslation attempts |
| `data/tm/improvement_queue.jsonl` | TM entries queued for LLM quality improvement |

---

## Troubleshooting

See [windows-native-deployment.md — Troubleshooting](../operations/windows-native-deployment.md#troubleshooting)
for the full troubleshooting guide covering:
- Content worker 0-translation issue (missing env vars)
- Stale PID files
- Retranslate queue not draining
- Orchestrator crash recovery
