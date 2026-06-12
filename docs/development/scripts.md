# Operational Scripts

All helper scripts used by engineers, operators, and CI live in `scripts/`.
Centralizing these entry points means we can audit automation changes independently
from the core runtime.

> **Authoritative source:** `scripts/MANIFEST.toml` is the machine-readable registry
> for scripts at the `scripts/` root. `scripts/README.md` is the human-readable
> companion. This file documents the taxonomy and governance.

## Root = CI-Critical Only

Scripts placed directly in `scripts/` (the root) must be referenced by path in a CI
workflow or in `CONTRIBUTING.md`. There are currently 7 such scripts — see
`scripts/MANIFEST.toml` for the complete list with CI reference annotations.

Everything else lives in a subdirectory.

## Directory Structure

| Subdirectory | Purpose | Example scripts |
|---|---|---|
| `ci/` | CI helper scripts | `run_local_gate.py`, `check_manifest.py` |
| `ops/` | Worker management, deployment, monitoring | `start_workers.ps1`, `worker_watchdog.ps1` |
| `tm/` | Translation memory management | `backup_tm.py`, `build_l3_index.py` |
| `bench/` | Benchmarking and performance | `benchmark_gpu_translation.py`, `benchmark_all_models.py` |
| `e2e/` | End-to-end test orchestration | `e2e_verify_single_file.py`, `e2e_full_run.py` |
| `quality/` | Quality gates and release validation | `check_invariants.py`, `quality_gates.py` |
| `content/` | Content scanning and repair | `scan_language_contamination.py`, `repair_translated_content.py` |
| `models/` | Model download and cache management | `download_models.py`, `cleanup_models.py` |
| `diag/` | Diagnostics and health checks | `comprehensive_diagnostic.py`, `verify_telemetry.py` |
| `analysis/` | Analysis, reporting, corpus building | `generate_metrics_report.py`, `inventory_files.py` |
| `setup/` | Environment setup | `setup.ps1`, `setup.sh` |
| `smoke/` | Smoke tests | `smoke_test.ps1`, `smoke_test.sh` |
| `archived/` | Retired scripts | `migrations/`, `pilots/`, `micro-wrappers/` |

## Intake Process

When introducing a new automation entry point:

1. Identify the correct subdirectory from the table above.
2. Place the script there — never at the root unless it has a CI path reference.
3. Run `python scripts/ci/check_manifest.py --strict` locally to verify.
4. If the script must live at root (CI/CONTRIBUTING.md reference), add a `[[script]]`
   entry to `scripts/MANIFEST.toml` before opening the PR.
5. Update `scripts/README.md` quick reference table for operational scripts.

## Retirement Policy

See `scripts/README.md` for the full retirement policy table. In brief:

- **Sprint pilots**: archive to `scripts/archived/pilots/` when the sprint closes.
- **Content repair scripts**: archive to `scripts/archived/content-repair/` when the
  blocking issue is resolved.
- **Micro-wrappers** (<50 lines, single subprocess call): archive to
  `scripts/archived/micro-wrappers/` with the canonical replacement command noted.

## CI Enforcement

`scripts/ci/check_manifest.py` runs in the release gate:

- **Warn mode** (current, migration period): verifies all CI-critical scripts exist;
  warns about unregistered root scripts but does not fail.
- **Strict mode** (post Phase 2 migration): fails if any root script is unregistered.
  Switch CI to `--strict` after the subdirectory migration is complete.

## reports/ Policy

`reports/` stores sprint evidence artifacts (ZIP bundles, structured subdirectories).
Ephemeral outputs (dry-run JSON, per-run sidecars) are gitignored via `reports/.gitignore`.
Never commit raw dry-run JSON to `reports/` — only ZIP archives of completed sprints.
