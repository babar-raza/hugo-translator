# Autonomous Content Translation Worker

## Overview

The Autonomous Content Translation Worker is a scheduled background service that automatically translates Hugo content directories and commits the results. It runs independently of manual CLI operations, providing continuous translation coverage for content repositories.

## Key Features

- **Two Execution Modes**: Oneshot (run once) and Daemon (self-schedules)
- **Timezone-Aware Scheduling**: Runs within configured time windows using `zoneinfo` (not local machine time)
- **VRAM Enforcement**: Respects GPU memory limits (default: 60%) via `VRAMEnforcer`
- **Selective Git Commits**: Only commits files actually modified in the current run
- **Telemetry Integration**: All runs tagged with `trigger_type="scheduled"` for analytics
- **Multi-Site Support**: Can process all sites or a specific site per run

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Autonomous Content Translation Worker                      │
│                                                              │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ WindowScheduler│→ │Translation   │→ │ Git Commit   │     │
│  │  (daemon mode) │  │   Engine     │  │   Helper     │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
│          ↓                  ↓                  ↓            │
│  ┌──────────────┐  ┌──────────────┐  ┌──────────────┐     │
│  │ ScheduleConfig│  │ ConfigService│  │ VRAMEnforcer │     │
│  └──────────────┘  └──────────────┘  └──────────────┘     │
└─────────────────────────────────────────────────────────────┘
```

## Execution Modes

### Oneshot Mode

Runs a single translation pass and exits. Ideal for:
- Windows Task Scheduler (schedule multiple oneshot runs per day)
- CI/CD pipelines
- Manual testing

```bash
python -m src.workers.autonomous_content_translation_worker \
  --mode oneshot \
  --site docs.aspose.net
```

### Daemon Mode

Self-schedules runs within a daily time window. Ideal for:
- Docker containers (single container runs continuously)
- Linux systemd services
- Long-running background processes

```bash
python -m src.workers.autonomous_content_translation_worker \
  --mode daemon \
  --runs-per-day 5 \
  --window-start 10:00 \
  --window-end 22:00 \
  --timezone America/Los_Angeles
```

## Command-Line Interface

### Required Arguments

- `--mode`: Execution mode (`oneshot` or `daemon`)

### Optional Arguments

| Argument | Default | Description |
|----------|---------|-------------|
| `--config-root` | `config/` | Root directory for configuration files |
| `--site` | None | Site ID to process (if omitted, process all sites) |
| `--runs-per-day` | 5 | Number of runs per day (daemon mode only) |
| `--window-start` | `10:00` | Start of daily window (HH:MM) |
| `--window-end` | `22:00` | End of daily window (HH:MM) |
| `--timezone` | `America/Los_Angeles` | Timezone name (IANA format) |
| `--jitter-minutes` | 10 | Random jitter to add/subtract (minutes) |
| `--max-sites-per-run` | None | Maximum sites to process per run |
| `--max-gpu-memory-percent` | 60 | GPU memory limit (percentage) |
| `--device` | `auto` | Device for inference (`cpu`, `cuda`, `mps`, `auto`) |
| `--log-level` | `INFO` | Logging level |

## Scheduling Logic

### Window-Based Scheduling

The scheduler divides the daily window into equal intervals:

```
Window: 10:00 - 22:00 (12 hours)
Runs per day: 5

Base run times:
- 10:00 (start)
- 13:00 (+3 hours)
- 16:00 (+3 hours)
- 19:00 (+3 hours)
- 22:00 (end)

With jitter (±10 minutes):
- 10:00 → 10:07
- 13:00 → 12:55
- 16:00 → 16:03
- 19:00 → 19:09
- 22:00 → 21:54
```

### Timezone Handling

**CRITICAL**: The worker uses `zoneinfo` for timezone-aware scheduling. This ensures:
- Correct scheduling across daylight saving time transitions
- Independence from system/container local time
- Consistent behavior in Docker and Windows environments

Example:
```python
from zoneinfo import ZoneInfo
now = datetime.now(ZoneInfo("America/Los_Angeles"))
# Always returns correct LA time, regardless of machine timezone
```

## Site Processing

For each site profile:
1. Load site configuration (`ConfigService.get_site_profile(site_id)`)
2. For each `content_root` in profile:
   - Call `TranslationEngine.translate_directory()` with `trigger_type="scheduled"`
   - Collect translation results
3. Commit only modified files via `auto_commit_translations()`

### Content Roots

Site profiles specify one or more content directories to translate:

```yaml
# config/site_profiles/docs.aspose.net.yaml
site_id: docs.aspose.net
content_roots:
  - /path/to/docs/content/en
  - /path/to/docs/content/tutorials
target_langs:
  - es
  - fr
  - de
```

The worker processes each content_root independently, allowing for:
- Multiple content directories per site
- Separate git commits per content_root (for traceability)
- Parallel processing of different content types

## VRAM Enforcement

The worker enforces GPU memory limits via `VRAMEnforcer` before loading models:

```python
hardware_config = {
    "enable_gpu": True,
    "max_gpu_memory_percent": 60,  # Use max 60% of VRAM
}

enforcer = VRAMEnforcer()
max_memory_mb, budget = enforcer.enforce_from_config(
    hardware_config, device="cuda:0"
)
# Applies torch.cuda.set_per_process_memory_fraction(0.6, 0)
```

This prevents:
- OOM errors from concurrent workers
- System-wide GPU starvation
- Unpredictable memory allocation

## Git Commit Integration

### Commit Strategy

The worker uses `auto_commit_translations()` from `git_commit_helper.py`:

1. **Collect Modified Files**: Only files written in this run (via `collect_output_files()`)
2. **Create Commit**: Stage and commit with auto-generated message
3. **Associate with Telemetry**: Link commit hash to telemetry run (TC-GIT-01)
4. **Optional Push**: Push to remote if configured

### Commit Message Format

```
chore: translate 15 docs.aspose.net files to es,fr,de

- Translated: 15 files
- Model: m2m100_1.2b
- TM hits: 67.3% (152/226 segments)
- Site: docs.aspose.net
- Content: /path/to/docs/content/en
- Run ID: 8f7e3c2a:docs.aspose.net:en

Co-Authored-By: Claude Sonnet 4.5 <noreply@anthropic.com>
```

### Run ID Format

Run IDs are structured for traceability:
```
{invocation_id}:{site_id}:{content_root_name}

Example:
8f7e3c2a-9b1c-4d2e-8f3a-1c5e7f9b2d4a:docs.aspose.net:en
```

Components:
- `invocation_id`: UUID generated at worker startup (shared across all sites in this invocation)
- `site_id`: Site identifier from profile
- `content_root_name`: Name of the content directory (e.g., "en", "tutorials")

## Telemetry Integration

### Trigger Type

All telemetry events are tagged with `trigger_type="scheduled"`:

```python
result = translation_engine.translate_directory(
    site_id=site_id,
    directory=content_dir,
    target_langs=target_langs,
    trigger_type="scheduled",  # CRITICAL
)
```

This enables analytics queries like:
```sql
-- Compare scheduled vs manual translation performance
SELECT trigger_type, AVG(duration_ms), COUNT(*)
FROM translation_runs
GROUP BY trigger_type;
```

### Commit Association (TC-GIT-01)

After git commit, the worker associates the commit hash with the telemetry run:

```python
telemetry.associate_commit(
    run_context,
    commit_hash="a1b2c3d4...",
    commit_source="llm",
    commit_author="Worker <worker@example.com>",
    commit_timestamp="2025-01-16T14:30:00Z"
)
```

This creates a bidirectional link:
- Telemetry run → Git commit (via commit_hash field)
- Git commit → Telemetry run (via run_id in commit message)

## Deployment Scenarios

### Scenario 1: Windows Task Scheduler (Oneshot Mode)

Schedule 5 runs per day at fixed times:

**Task 1: 10:00 AM**
```powershell
Program: python
Arguments: -m src.workers.autonomous_content_translation_worker --mode oneshot
Start in: C:\repos\hugo-translator
Trigger: Daily at 10:00 AM Pacific Time
```

**Task 2: 1:00 PM** (repeat with `1:00 PM`)
**Task 3: 4:00 PM** (repeat with `4:00 PM`)
**Task 4: 7:00 PM** (repeat with `7:00 PM`)
**Task 5: 10:00 PM** (repeat with `10:00 PM`)

**Pros**:
- Simple Windows integration
- Each run is independent (no daemon management)
- Easy to monitor via Task Scheduler logs

**Cons**:
- Requires 5 separate scheduled tasks
- No automatic jitter (runs at exact times)

### Scenario 2: Docker Container (Daemon Mode)

Single container that self-schedules:

**Dockerfile**:
```dockerfile
FROM python:3.11-slim

WORKDIR /app
COPY . /app

RUN pip install -r requirements.txt

# Set timezone for logging (worker uses zoneinfo internally)
ENV TZ=America/Los_Angeles

CMD ["python", "-m", "src.workers.autonomous_content_translation_worker", \
     "--mode", "daemon", \
     "--runs-per-day", "5", \
     "--window-start", "10:00", \
     "--window-end", "22:00", \
     "--timezone", "America/Los_Angeles", \
     "--device", "cuda"]
```

**Docker Compose**:
```yaml
services:
  translation-worker:
    build: .
    restart: unless-stopped
    environment:
      - TZ=America/Los_Angeles
    volumes:
      - ./config:/app/config:ro
      - ./data:/app/data
      - ./content:/app/content
    deploy:
      resources:
        reservations:
          devices:
            - driver: nvidia
              count: 1
              capabilities: [gpu]
```

**Pros**:
- Single container, simple deployment
- Automatic jitter built-in
- Survives across host reboots (restart policy)

**Cons**:
- Container must stay running 24/7
- Requires proper signal handling for graceful shutdown

### Scenario 3: Kubernetes CronJob (Oneshot Mode)

Schedule runs via Kubernetes:

```yaml
apiVersion: batch/v1
kind: CronJob
metadata:
  name: translation-worker
spec:
  schedule: "0 10,13,16,19,22 * * *"  # 10AM, 1PM, 4PM, 7PM, 10PM UTC
  timeZone: "America/Los_Angeles"
  jobTemplate:
    spec:
      template:
        spec:
          containers:
          - name: worker
            image: hugo-translator:latest
            command:
              - python
              - -m
              - src.workers.autonomous_content_translation_worker
              - --mode
              - oneshot
            volumeMounts:
              - name: config
                mountPath: /app/config
              - name: content
                mountPath: /app/content
          restartPolicy: OnFailure
          volumes:
            - name: config
              configMap:
                name: translation-config
            - name: content
              persistentVolumeClaim:
                claimName: content-pvc
```

**Pros**:
- Native Kubernetes integration
- Built-in retry logic
- Resource limits and monitoring

**Cons**:
- Requires Kubernetes cluster
- More complex setup

## Environment Variables

The worker respects standard environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `EXECUTION_MODE` | Execution mode (windows_cuda, docker_cpu, docker_gpu) | `windows_cuda` |
| `CUDA_VISIBLE_DEVICES` | GPU devices to use | All GPUs |
| `TZ` | Timezone for logging | System timezone |
| `LOG_LEVEL` | Logging level | `INFO` |

**Note**: The `--timezone` argument controls scheduling logic (via `zoneinfo`), while `TZ` only affects log timestamps.

## Safety and Error Handling

### Site Lock Management

The worker uses `TranslationEngine.translate_directory()` which implements site-level locking:
- Prevents concurrent translations of the same site
- Auto-cleans stale locks (>24 hours old)
- Graceful handling of lock timeouts

### Error Recovery

The worker continues processing on errors:
1. **Site-level errors**: Skip failed site, continue with next site
2. **Content-root errors**: Skip failed content_root, continue with next content_root
3. **Commit errors**: Log failure, continue with next translation

Example log output:
```
ERROR - Failed to process site docs.aspose.net: ConnectionError
INFO - Processing next site: kb.aspose.net
```

### VRAM Enforcement Errors

If VRAM enforcement fails:
1. Log error with full traceback
2. Continue with translation (no enforcement)
3. May result in OOM if model is too large

## Monitoring and Observability

### Telemetry Events

The worker emits telemetry events for:
- Translation sessions (start, end, stats)
- Git commits (commit hash, files modified)
- Validation results (if enabled)
- Model loading (device, VRAM usage)

Query examples:
```sql
-- Find all scheduled translation runs
SELECT * FROM translation_runs WHERE trigger_type = 'scheduled';

-- Find runs with associated git commits
SELECT r.*, c.commit_hash
FROM translation_runs r
JOIN git_commits c ON r.run_id = c.run_id
WHERE r.trigger_type = 'scheduled';

-- Average translation time by site
SELECT site_id, AVG(duration_ms) / 1000.0 AS avg_seconds
FROM translation_runs
WHERE trigger_type = 'scheduled'
GROUP BY site_id;
```

### Log Output

The worker logs structured information:
```
2025-01-16 10:07:23 - INFO - ================================================================================
2025-01-16 10:07:23 - INFO - SCHEDULED RUN #1 at 2025-01-16 10:07:23 PST
2025-01-16 10:07:23 - INFO - ================================================================================
2025-01-16 10:07:23 - INFO - Processing all sites: 8 total
2025-01-16 10:07:23 - INFO - Processing site: docs.aspose.net
2025-01-16 10:07:23 - INFO - Translating content_root: /path/to/docs/content/en
2025-01-16 10:07:23 - INFO - Target languages: es, fr, de
2025-01-16 10:08:45 - INFO - Translation completed: 15/15 files succeeded, 0 failed
2025-01-16 10:08:45 - INFO - Auto-committing translation outputs...
2025-01-16 10:08:46 - INFO - Committed 15 files: a1b2c3d (push: OK)
2025-01-16 10:08:46 - INFO - Git commit successful
```

## Testing

### Unit Tests

Test scheduling logic:
```bash
pytest tests/unit/workers/test_window_scheduler.py
```

### Integration Tests

Test worker execution with mocked TranslationEngine:
```bash
pytest tests/integration/test_autonomous_worker.py
```

### Manual Testing

Test oneshot mode on a small site:
```bash
python -m src.workers.autonomous_content_translation_worker \
  --mode oneshot \
  --site example \
  --config-root tests/fixtures/config \
  --device cpu \
  --log-level DEBUG
```

## Troubleshooting

### Issue: Worker not running at expected times

**Cause**: Timezone mismatch between scheduler and expectation

**Solution**: Verify timezone setting matches desired location:
```bash
python -c "from zoneinfo import ZoneInfo; from datetime import datetime; print(datetime.now(ZoneInfo('America/Los_Angeles')))"
```

### Issue: VRAM enforcement not working

**Cause**: CUDA not available or device not set correctly

**Solution**: Check CUDA availability:
```bash
python -c "import torch; print(torch.cuda.is_available())"
```

Verify device argument:
```bash
--device cuda  # or cuda:0, cuda:1, etc.
```

### Issue: Git commits not created

**Cause**: No files actually modified (all skipped due to content hash tracking)

**Solution**: Check translation logs for skip messages:
```
INFO - Skipped 10/10 files (content unchanged)
```

Force retranslation if needed:
```python
# Add force=True to translate_directory call (requires code change)
result = translation_engine.translate_directory(..., force=True)
```

### Issue: Daemon mode exits unexpectedly

**Cause**: Uncaught exception in translation or commit logic

**Solution**: Check logs for stack traces. The daemon continues on most errors, but some critical failures (e.g., config loading) will exit.

Enable debug logging:
```bash
--log-level DEBUG
```

## Future Enhancements

Potential improvements:
1. **Health Check Endpoint**: HTTP endpoint for monitoring worker status
2. **Prometheus Metrics**: Export scheduling and translation metrics
3. **Dynamic Scheduling**: Adjust run times based on system load
4. **Site Prioritization**: Process high-priority sites first
5. **Dry Run Mode**: Preview what would be translated without executing
6. **Resume Support**: Resume interrupted runs from last processed site

## References

- [WindowScheduler Implementation](../../src/workers/window_scheduler.py)
- [Git Commit Helper](../../src/observability/git_commit_helper.py)
- [VRAM Enforcer](../../src/hardware/vram_enforcer.py)
- [TranslationEngine](../../src/translation_engine/engine.py)
- [TC-GIT-01: Commit Association Spec](../features/)

## Update — 2026-02-16 22:36 PKT

### Worker Verification Delta (SR-03)

- `TranslationEngine` now resolves language detector via `_get_language_detector()` and initializes backward-compatible `self.detector` alias.
- This removes the prior runtime crash path (`'TranslationEngine' object has no attribute 'detector'`) in current oneshot worker output.
- New blocker observed during manual oneshot: repeated `FINAL PURITY CHECK FAILED` loops on `file1.md`, then timeout (`translate_directory(...) timed out after 60s`) and `[Errno 22] Invalid argument` for fixture files.

Evidence:
- `reports/agents/Agent_B/ORCH-AW-002/run_20260216_223609/artifacts/git_diff.txt`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/pytest_worker_slice.txt`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/content_worker_oneshot.txt`
- `reports/agents/Agent_C/ORCH-AW-003/run_20260216_223609/artifacts/content_worker_new_blockers.txt`

