# Scripts Directory

Utility scripts for the Hugo Translation System.

## Quick Reference — Operational Scripts

These are the scripts most colleagues will use day-to-day. See sections below for full detail on specific scripts.

### Worker Management

| Script | Purpose |
|--------|---------|
| `start_workers.ps1` | Start content worker (+ optionally TM worker) as detached processes |
| `start_content_worker.bat` | Start content worker via Task Scheduler bat wrapper |
| `start_tm_worker.bat` | Start TM improvement worker via Task Scheduler bat wrapper |
| `start_content_worker_now.bat` | Immediately start content worker (bypass schedule) |
| `start_tm_worker_now.bat` | Immediately start TM worker (bypass schedule) |
| `setup_task_scheduler.ps1` | Register all workers with Windows Task Scheduler (run as Admin) |
| `_disable_tasks.ps1` | Permanently disable all HugoTranslator Task Scheduler tasks (run as Admin) |
| `worker_watchdog.ps1` | Circuit breaker: restarts crashed workers (max 5/hour) |
| `check_worker_health.ps1` | Health check: OK / WARN / CRIT per worker |

### Setup

| Script | Purpose |
|--------|---------|
| `setup_dev_env.py` | Bootstrap: creates venv, installs deps, copies .env template |
| `setup/setup.ps1` | Windows full setup script |
| `setup/setup.sh` | Linux/macOS full setup script |

### Translation Memory

| Script | Purpose |
|--------|---------|
| `backup_tm.py` | Back up L2 LMDB + L3 FAISS index to `backups/` |
| `restore_tm.py` | Restore TM from a backup |
| `clear_tm.py` | Clear all TM entries (use with caution) |
| `build_l3_index.py` | Rebuild the L3 FAISS semantic index from L2 |
| `inspect_l3_metadata.py` | Inspect L3 index metadata and entry counts |
| `query_tm_cache.py` | Query TM for specific source text |
| `scan_language_contamination.py` | Scan translated output for wrong-language content. Use `--fast` to skip langdetect (recommended for large repos). Use `--repair` to delete bad files. |

### Diagnostics and Quality

| Script | Purpose |
|--------|---------|
| `comprehensive_diagnostic.py` | Full system diagnostic (GPU, models, TM, config) |
| `production_readiness_check.py` | Pre-publication readiness checklist |
| `check_worker_health.ps1` | Worker heartbeat health check |
| `health_check.py` | Lightweight system health check |
| `quality_gates.py` | Run quality gate checks on translated output |
| `check_tm_contamination.py` | Check TM for cross-language contamination |
| `check_share_safe.sh` | Verify no personal paths before sharing the repo |

### Benchmarking

| Script | Purpose |
|--------|---------|
| `benchmark_gpu_translation.py` | GPU translation performance benchmark |
| `benchmark_cpu_comprehensive.py` | CPU-only benchmark across models |
| `benchmark_all_models.py` | Full model comparison matrix |
| `analyze_benchmark_results.py` | Parse and summarize benchmark output |

### Model Management

| Script | Purpose |
|--------|---------|
| `download_models.py` | Pre-download translation models |
| `cleanup_models.py` | Remove unused cached models |
| `discover_models.py` | List all discovered local models |

---

## validate-evidence.py

Validates evidence citations in specifications to detect stale references.

### Usage

```bash
# Validate all specs
python scripts/validate-evidence.py --all

# Validate specific file
python scripts/validate-evidence.py specs/features/cli-001-main-translate.md

# Generate report
python scripts/validate-evidence.py --all --report reports/driftless/evidence_validation_report.md
```

### Checks Performed

- File exists at cited path
- Line numbers are within file bounds
- Line ranges are valid (end >= start)

### Exit Codes

- `0` - All citations valid
- `1` - Invalid citations found
- `2` - Error (file not found, invalid arguments)

## lint-specs.py

Automated spec-lint checker for specification quality.

### Usage

```bash
# Check all specs
python scripts/lint-specs.py --all

# Check specific file
python scripts/lint-specs.py specs/features/cli-001-main-translate.md

# Auto-fix violations (when supported)
python scripts/lint-specs.py --fix --all
```

### Checks Implemented

- **RULE-S1:** File naming (must match {category}-{number}-{slug}.md)
- **RULE-S2:** Required frontmatter fields
- **RULE-T1:** spec_id exists in inventory
- **RULE-ST1:** Valid status values

### Exit Codes

- `0` - All checks passed
- `1` - Violations found
- `2` - Error (file not found, invalid YAML)
