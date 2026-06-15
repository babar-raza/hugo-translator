# Incident Response Runbook

Operational procedures for handling common failure scenarios in the Hugo Translation System.

## Severity Levels

| Level | Description | Response Time | Escalation |
|-------|-------------|---------------|------------|
| P1 | System down / data corruption | 1 hour | Immediate owner notification |
| P2 | Degraded quality / partial failure | 4 hours | Daily standup |
| P3 | Minor issue / cosmetic | 24 hours | Next sprint |

## Incident 1: Worker OOM (Out of Memory)

**Detection:** Worker logs show `torch.cuda.OutOfMemoryError` or process killed by OS OOM killer. Health check (`scripts/health_check.py`) reports `last_success_ts` stale.

**Severity:** P2

**Symptoms:**
- Worker process exits unexpectedly
- GPU memory utilization at 100%
- No new translations produced
- `data/logs/worker_state.json` shows `run_failed`

**Response:**
1. Check worker logs: `data/logs/worker.log`
2. Check GPU memory: `nvidia-smi` (if CUDA device)
3. Reduce batch size in `config/global.yaml`: `translation.max_batch_size`
4. Reduce `max_gpu_memory_percent` in worker config (default: 60%)
5. Restart worker: `python -m src.workers.autonomous_content_translation_worker --site <site> --mode oneshot`
6. Verify recovery: check `data/logs/worker_state.json` for `run_completed`

**Prevention:**
- The `VRAMEnforcer` module (`src/hardware/vram_enforcer.py`) monitors GPU memory and triggers model offload before OOM
- The `HealingEngine` automatically reduces batch size on OOM and retries
- Worker offloads models (`_offload_models()`) before sleep in daemon mode

## Incident 2: Worker Hung / Unresponsive

**Detection:** Health check shows heartbeat stale (no update in >2x expected interval). PID file exists but process is unresponsive.

**Severity:** P2

**Symptoms:**
- `data/worker/heartbeat.json` timestamp not updating
- Process consuming CPU but producing no output
- No new commits to content repository

**Response:**
1. Check PID file: `data/worker/content_worker.pid`
2. Check if process is alive: `ps -p <pid>` or Task Manager
3. If hung, terminate: `kill <pid>` / End Task
4. Check for lock files: `data/worker/*.lock`
5. Remove stale PID file if process is dead
6. Check continuation state: `data/logs/continuation_state.json` — if phase is `running`, it will be treated as `interrupted` on next start
7. Restart worker

**Prevention:**
- `TimeoutGuard` (`src/utils/timeout_guard.py`) enforces per-file translation timeouts (default: 600s)
- Worker heartbeat thread updates `heartbeat.json` every 30 seconds
- PID file locking prevents duplicate workers

## Incident 3: Bad Translation Batch

**Detection:** Quality audit score drops below threshold. Validator failures spike. Users report incorrect translations.

**Severity:** P1 (if published) / P2 (if caught pre-commit)

**Symptoms:**
- `scripts/audit_translation_quality.py --mode ci` reports score < 0.70
- Validation metrics in `data/logs/validation_metrics.jsonl` show high rejection rate
- Run history shows low acceptance rate

**Response:**
1. Stop the worker immediately if in daemon mode
2. Run quality audit: `python scripts/audit_translation_quality.py --mode ci --threshold 0.70 --verbose`
3. Identify affected files from validation metrics
4. Check if translations were committed: `git log --oneline -20` in content repo
5. If committed, revert the bad batch: `git revert <commit-hash>` in content repo
6. Investigate root cause:
   - Model degradation? Check `data/metrics/run_history.db` for acceptance rate trend
   - Config change? Check `config/global.yaml` diff
   - Source content issue? Check source files for unusual formatting
7. Re-run with `--dry-run` to verify fix before allowing commits

**Prevention:**
- 11 validators in the decision engine enforce quality (ACCEPT/RETRY/REJECT)
- `LanguageConsistencyValidator` checks target language purity via FastText
- `FrontmatterProtectionValidator` prevents YAML corruption
- Run history regression detection alerts on acceptance rate drops

## Incident 4: Metrics API Failure

**Detection:** Agent metrics posting returns non-200 response code. Evidence sidecar shows `posting.status: error`.

**Severity:** P3 (metrics are non-critical; translations continue)

**Symptoms:**
- `data/metrics/agent_evidence/` sidecar files show `response_code != 200`
- Worker logs show `agent_metrics_poster: POST failed`
- No data appearing in external metrics dashboard

**Response:**
1. Check if metrics are enabled: `config/global.yaml` → `agent_metrics.enabled` (default: false)
2. Check dry-run mode: `config/global.yaml` → `agent_metrics.dry_run` (default: true)
3. If enabled and not dry-run, check API endpoint connectivity
4. Check evidence sidecar for error details: `data/metrics/agent_evidence/<date>/*.json`
5. If persistent, set `agent_metrics.enabled: false` to prevent noise
6. File issue for API team if endpoint is unreachable

**Prevention:**
- Metrics posting is non-fatal — translation continues regardless
- Default config: `enabled: false`, `dry_run: true`
- Evidence sidecars always written (even on failure) for audit trail

## Incident 5: Translation Memory Corruption

**Detection:** L2 LMDB database reports `MDB_CORRUPTED` or `MDB_MAP_FULL`. Translation quality drops due to bad TM matches.

**Severity:** P2

**Symptoms:**
- Worker logs show LMDB errors
- TM hit rate drops to 0%
- Translation quality degrades (no fuzzy matches)

**Response:**
1. Stop all workers using the TM
2. Back up current TM: `cp -r data/tm/ data/tm-backup-$(date +%Y%m%d)/`
3. Check LMDB integrity: `python -c "import lmdb; env = lmdb.open('data/tm/l2'); print(env.stat())"`
4. If corrupted, rebuild from L1 cache or source translations
5. If `MDB_MAP_FULL`, increase map size in `config/global.yaml` → `tm.l2.map_size_mb`
6. Restart workers

**Prevention:**
- L2 uses atomic writes via LMDB transactions
- `_atomic_write()` pattern used for all JSON state files
- L1 (in-memory LRU) provides fallback if L2 is unavailable

## General Recovery Checklist

1. Identify the incident type and severity
2. Check worker state: `data/logs/worker_state.json`
3. Check continuation state: `data/logs/continuation_state.json`
4. Check recent run signals: `data/signals/run-signal-*.json`
5. Review worker logs: `data/logs/worker.log`
6. Check system resources: CPU, memory, disk, GPU
7. Verify config is correct: `python scripts/ci/check_governance.py --strict`
8. Run health check: `python scripts/health_check.py`
9. Restart worker in oneshot mode to verify recovery
10. Monitor first run after recovery for regressions
