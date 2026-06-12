# Scripts Directory

Utility scripts for the Hugo Translation System.

---

## Governance Rules

> **Root = CI-critical only.**
> Scripts placed directly in `scripts/` must be referenced by path in a CI workflow
> (`scripts/*.yml`) or in `CONTRIBUTING.md`. Everything else belongs in a subdirectory.

### Adding a new script

1. Determine the correct subdirectory (see [Directory Structure](#directory-structure) below).
2. Place the script in that subdirectory, not the root.
3. If — and only if — the script must be referenced directly from CI or `CONTRIBUTING.md`,
   add it to the root AND add a `[[script]]` entry in `scripts/MANIFEST.toml`.
4. Run `python scripts/ci/check_manifest.py --strict` locally to verify.

The CI release gate runs `check_manifest.py --strict` on every PR and will reject any
unregistered script added to the root.

### Retirement policy

| Script type | Retire when | Destination |
|-------------|------------|-------------|
| Pilot / proof scripts (`pilot_*.py`, `*_proof.py`) | Sprint marked `STATUS: COMPLETE` in MEMORY.md | `scripts/archived/pilots/` |
| Content repair scripts (one-off RCA fixes) | Blocking issue resolved | `scripts/archived/content-repair/` |
| Micro-wrappers (<50 lines, wraps one subprocess call) | Identified | `scripts/archived/micro-wrappers/` |
| Any script | `status = "deprecated"` in MANIFEST for 30 days | Delete in next monthly maintenance pass |

When archiving, add at the top of the file:
```python
# ARCHIVED: YYYY-MM-DD. Sprint: <sprint-name>. Replacement: <command or path>.
```

---

## Directory Structure

After Phase 2 migration, scripts live in these subdirectories:

| Subdirectory | Contents |
|---|---|
| `ci/` | CI helper scripts (run_local_gate.py, scan_changed_content.py, check_manifest.py) |
| `ops/` | Worker management, deployment, monitoring, campaign automation |
| `tm/` | Translation memory backup/restore, L2/L3 index management |
| `bench/` | Benchmarking and performance analysis |
| `e2e/` | End-to-end test scripts |
| `quality/` | Quality gates, invariant checks, release readiness |
| `content/` | Content scanning, repair, retranslation |
| `models/` | Model download, discovery, cache management |
| `diag/` | Diagnostics, health checks, telemetry verification |
| `analysis/` | Analysis, reporting, corpus building, inventory |
| `setup/` | Environment setup scripts |
| `smoke/` | Smoke test scripts |
| `archived/` | Retired scripts (migrations, pilots, micro-wrappers) |

The **root** contains only the 7 CI-critical scripts listed in `MANIFEST.toml`.

---

## Quick Reference — Operational Scripts

These are the scripts most colleagues will use day-to-day. See sections below for full detail on specific scripts.

### Worker Management (`ops/`)

| Script | Purpose |
|--------|---------|
| `ops/start_workers.ps1` | Start content worker (+ optionally TM worker) as detached processes |
| `ops/start_content_worker.bat` | Start content worker via Task Scheduler bat wrapper |
| `ops/start_tm_worker.bat` | Start TM improvement worker via Task Scheduler bat wrapper |
| `ops/start_content_worker_now.bat` | Immediately start content worker (bypass schedule) |
| `ops/start_tm_worker_now.bat` | Immediately start TM worker (bypass schedule) |
| `ops/setup_task_scheduler.ps1` | Register all workers with Windows Task Scheduler (run as Admin) |
| `ops/_disable_tasks.ps1` | Permanently disable all HugoTranslator Task Scheduler tasks (run as Admin) |
| `ops/worker_watchdog.ps1` | Circuit breaker: restarts crashed workers (max 5/hour) |
| `ops/check_worker_health.ps1` | Health check: OK / WARN / CRIT per worker |
| `ops/rollback.py` | Rollback translation changes (git-based) |

### Setup

| Script | Purpose |
|--------|---------|
| `setup_dev_env.py` | Bootstrap: creates venv, installs deps, copies .env template (**root** — referenced in CONTRIBUTING.md) |
| `setup/setup.ps1` | Windows full setup script |
| `setup/setup.sh` | Linux/macOS full setup script |

### Translation Memory (`tm/`)

| Script | Purpose |
|--------|---------|
| `tm/backup_tm.py` | Back up L2 LMDB + L3 FAISS index to `backups/` |
| `tm/restore_tm.py` | Restore TM from a backup |
| `tm/clear_tm.py` | Clear all TM entries (use with caution) |
| `tm/build_l3_index.py` | Rebuild the L3 FAISS semantic index from L2 |
| `tm/inspect_l3_metadata.py` | Inspect L3 index metadata and entry counts |
| `tm/query_tm_cache.py` | Query TM for specific source text |
| `content/scan_language_contamination.py` | Scan translated output for wrong-language content. Use `--fast` to skip langdetect (recommended for large repos). Use `--repair` to delete bad files. |

### Diagnostics and Quality

| Script | Purpose |
|--------|---------|
| `diag/comprehensive_diagnostic.py` | Full system diagnostic (GPU, models, TM, config) |
| `quality/production_readiness_check.py` | Pre-publication readiness checklist |
| `ops/check_worker_health.ps1` | Worker heartbeat health check |
| `health_check.py` | Lightweight system health check (**root** — referenced in CI) |
| `quality/quality_gates.py` | Run quality gate checks on translated output |
| `tm/check_tm_contamination.py` | Check TM for cross-language contamination |
| `check_share_safe.sh` | Verify no personal paths before sharing the repo (**root** — referenced in CONTRIBUTING.md) |

### Benchmarking (`bench/`)

| Script | Purpose |
|--------|---------|
| `bench/benchmark_gpu_translation.py` | GPU translation performance benchmark |
| `bench/benchmark_cpu_comprehensive.py` | CPU-only benchmark across models |
| `bench/benchmark_all_models.py` | Full model comparison matrix |
| `bench/analyze_benchmark_results.py` | Parse and summarize benchmark output |

### Model Management (`models/`)

| Script | Purpose |
|--------|---------|
| `models/download_models.py` | Pre-download translation models |
| `models/cleanup_models.py` | Remove unused cached models |
| `models/discover_models.py` | List all discovered local models |

---

## quality/validate-evidence.py

Validates evidence citations in specifications to detect stale references.

### Usage

```bash
# Validate all specs
python scripts/quality/validate-evidence.py --all

# Validate specific file
python scripts/quality/validate-evidence.py specs/features/cli-001-main-translate.md

# Generate report
python scripts/quality/validate-evidence.py --all --report reports/driftless/evidence_validation_report.md
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
python scripts/quality/lint-specs.py --all

# Check specific file
python scripts/quality/lint-specs.py specs/features/cli-001-main-translate.md

# Auto-fix violations (when supported)
python scripts/quality/lint-specs.py --fix --all
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

---

## CI Helper Scripts (`ci/`)

| Script | Purpose |
|--------|---------|
| `ci/run_local_gate.py` | Local quality gate: lint + critical tests before commit |
| `ci/scan_changed_content.py` | Scan for changed content files in a PR |
| `ci/check_lmdb_test_map_size.py` | Verify test LMDB has sufficient map size |
| `ci/check_manifest.py` | Validate MANIFEST.toml against scripts/ root — run before committing new scripts |

Usage:
```bash
# Check manifest (warn mode — during migration)
python scripts/ci/check_manifest.py

# Check manifest (strict mode — post-migration)
python scripts/ci/check_manifest.py --strict

# Local gate before committing
python scripts/ci/run_local_gate.py
python scripts/ci/run_local_gate.py --full  # run all unit tests
```
