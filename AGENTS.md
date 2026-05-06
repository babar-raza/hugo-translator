# Autonomous Agents

This project uses three autonomous worker processes for scheduled translation, TM improvement, and verification. All three run on Windows Task Scheduler in the production deployment. None require a running server — they sleep between scheduled runs and wake on their own.

---

## Content Translation Worker

**Module**: `src/workers/autonomous_content_translation_worker.py`

Translates Hugo markdown files on a recurring schedule. On each run it:
1. Reads all site profiles from `config/site_profiles/`
2. For each site, selects up to `files_per_commit` source files (alphabetically ordered)
3. Runs the full translation pipeline (parse → TM lookup → MT model → validate → write)
4. Commits translated files to git with TM hit rates and validation stats in the commit message

**Modes**:

| Mode | Command | Use case |
|------|---------|----------|
| `oneshot` | Runs once then exits | Manual trigger, CI, testing |
| `daemon` | Runs on schedule, sleeps between runs | Production |

**Start (immediate, one-shot):**
```powershell
python -m src.workers.autonomous_content_translation_worker --mode oneshot
```

**Start (scheduled daemon, via script):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1
```

**Key flags:**
```
--mode {oneshot,daemon}      Run mode (default: daemon)
--site SITE_ID               Translate a specific site only
--runs-per-day N             How many times to run per day (default: 4)
--window-start HH:MM         Start of allowed window (default: 07:00)
--window-end HH:MM           End of allowed window (default: 23:00)
--timezone TZ                Timezone for scheduling (default: UTC)
--device {cpu,cuda,auto}     Compute device (default: auto)
--max-gpu-memory-percent N   GPU VRAM budget % (default: 50)
--max-seconds-per-run N      Wall-clock timeout per run (default: 3600)
--run-immediately            Run once before waiting for first window slot
--log-level {DEBUG,INFO,...} Log verbosity
```

**Monitoring:**
- Heartbeat: `data/logs/content_worker.heartbeat` (JSON, updated every minute)
- PID: `data/logs/content_worker_daemon.pid`
- Log: `data/logs/content_worker.log`
- Health check: `scripts/check_worker_health.ps1`

---

## TM Improvement Worker

**Module**: `src/workers/tm_improvement_worker.py`

Improves existing translations in the Translation Memory using an LLM. On each run it:
1. Polls the improvement queue for candidate translations
2. Calls the configured LLM to produce a higher-quality version
3. Validates the improvement against quality gates
4. Writes the improved translation back to L2 (LMDB) and L3 (FAISS)

LLM configuration is read from `config/global.yaml` → `tm_improvement.llm`. Do not pass `--llm-provider` or `--llm-model` as CLI flags — they override the config and may connect to the wrong endpoint.

**Modes**: Same as content worker (`oneshot` / `daemon`)

**Start (with TM worker, via script):**
```powershell
powershell -ExecutionPolicy Bypass -File scripts\start_workers.ps1 -TmWorker
```

**Key flags:**
```
--mode {oneshot,daemon}         Run mode
--runs-per-day N                Runs per day (default: 4)
--candidates-per-run N          TM entries to process per run (default: 50)
--max-llm-calls-per-run N       LLM call budget per run (default: 200)
--max-seconds-per-run N         Wall-clock timeout (default: 900)
--device {cpu,cuda,auto}        Compute device for L3 FAISS
--max-gpu-memory-percent N      VRAM budget %
```

**Monitoring:**
- Heartbeat: `data/logs/tm_worker.heartbeat`
- PID: `data/logs/tm_worker_daemon.pid`
- Log: `data/logs/tm_worker.log`

---

## Autonomous Verification Worker

**Module**: `src/workers/autonomous_verification_worker.py`

Periodically verifies translation quality on already-translated output files. Reports quality metrics without modifying any files.

**Start:**
```powershell
python -m src.workers.autonomous_verification_worker --mode oneshot
```

---

## Task Scheduler Registration

All three workers are registered with Windows Task Scheduler via:

```powershell
# Run as Administrator
powershell -ExecutionPolicy Bypass -File scripts\setup_task_scheduler.ps1
```

This registers four tasks:
- `HugoTranslator-ContentWorker` — content translation, scheduled
- `HugoTranslator-TMWorker` — TM improvement, scheduled
- `HugoTranslator-Watchdog` — circuit breaker (max 5 restarts/hour)
- `HugoTranslator-AutonomousVerification` — periodic quality checks

To disable all tasks without unregistering:
```powershell
# Run as Administrator
powershell -ExecutionPolicy Bypass -File scripts\_disable_tasks.ps1
```

---

## Health Monitoring

```powershell
# Overall worker health
scripts\check_worker_health.ps1

# Check heartbeat directly
Get-Content data\logs\content_worker.heartbeat | ConvertFrom-Json
Get-Content data\logs\tm_worker.heartbeat | ConvertFrom-Json

# Tail logs
Get-Content data\logs\content_worker.log -Wait -Tail 30
Get-Content data\logs\tm_worker.log -Wait -Tail 30
```

**Health rules:**
- Missing or stale heartbeat (> 15 min old) → CRITICAL
- `last_error_ts` newer than `last_success_ts` → WARNING
- Worker in `starting` state and run age > 6h with fresh heartbeat → WARNING (stuck run)

---

## VRAM Management

Both workers offload models before sleeping:
- Content worker: calls `_offload_models()` before every daemon sleep — unloads M2M100 and calls `torch.cuda.empty_cache()`
- TM worker: calls `_offload_resources()` before every sleep — moves L3 FAISS index and LLM client to CPU

This ensures VRAM is free during the sleep window for other processes.

---

## Related Documentation

- [Agent Guardrails](docs/AGENT_GUARDRAILS.md) - Safety rules and constraints for autonomous agents
- [Worker Deployment](docs/workers/WORKER_DEPLOYMENT.md) - Detailed deployment procedures
- [Windows-Native Deployment](docs/operations/windows-native-deployment.md) - Production deployment on Windows
- [ONBOARDING.md](docs/getting-started/ONBOARDING.md) - New contributor onboarding
- [VRAM Policy Spec](specs/autonomous_workers/VRAM_POLICY.md) - GPU memory management specification

---

## Agent Metrics Reporting

Both the Content Translation Worker and TM Improvement Worker report per-run metrics via the Agent Metrics API integration. This is **disabled by default** (`enabled: false`, `dry_run: true` in `config/global.yaml`).

When enabled, each content_root translation produces a 17-field payload covering item counts, LLM token usage, and scope (product, platform, website). Payloads are posted to a shared Google Sheet. Evidence sidecars are written locally regardless of posting status.

**Worker hooks:**
- Content worker: `MetricsRunContext.start()` before each content_root, `.finish()` after
- TM worker: Same pattern, with `job_type="tm_improvement"`
- Errors are caught and logged — metrics never crash a worker run

**Configuration**: `config/global.yaml` → `agent_metrics` section

**Full reference**: [Agent Metrics API](docs/observability/agent-metrics-api.md)
