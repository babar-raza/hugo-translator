# Repository Structure

**Last Updated:** 2026-01-15
**Author:** Agent D (Docs & Specs)
**Phase:** 6.4 - Documentation Update

---

## Overview

This document provides comprehensive documentation of the hugo-translator repository structure. The organization follows the file organization plan established in Phase 6.2 (WI-P6-002).

## Top-Level Directory Layout

```
hugo-translator/
├── archive/          # Historical artifacts (legacy code, old reports)
├── config/           # Configuration files (YAML)
├── data/             # Runtime data (TM, benchmarks, corpus)
├── docker/           # Docker configuration files
├── docs/             # Documentation
├── models/           # Translation model storage
├── plans/            # Active implementation plans
├── reports/          # Active analysis reports
├── requirements/     # Python dependency specifications
├── scripts/          # Utility scripts
├── specs/            # Technical specifications
├── src/              # Production source code
└── tests/            # Test suite
```

---

## Directory Details

### archive/

**Purpose:** Historical artifacts preserved for reference but not actively maintained.

| Subdirectory | Contents |
|--------------|----------|
| `legacy/` | Old translation system (ast-translator, ast-converter, etc.) |
| `plans/` | Completed implementation plans from previous phases |
| `reports/` | Historical phase reports, research artifacts, task cards |
| `samples/` | Development samples and examples from early development |

**Note:** Files in `archive/` are kept for historical context. They are not part of the active codebase and should not be imported or referenced in production code.

---

### config/

**Purpose:** All configuration files for the translation system.

| File/Directory | Description |
|----------------|-------------|
| `global.yaml` | Global system configuration |
| `site_profiles/` | Site-specific configuration (e.g., `docs.aspose.net.yaml`) |
| `terminology/` | Protected terminology rules |
| `validation.yaml` | Validation rules and thresholds |
| `metrics.yaml` | Metrics storage and bounds configuration |
| `model_registry.yaml` | Available translation models metadata |

**Configuration Priority:**
1. CLI arguments (highest)
2. Environment variables
3. Site profile configuration
4. Global configuration
5. Code defaults (lowest)

---

### data/

**Purpose:** Runtime data storage (not committed to git).

| Subdirectory | Contents |
|--------------|----------|
| `benchmark_corpus/` | Test data for benchmarking |
| `benchmarks/` | Benchmark results and SQLite database |
| `tm/` | Translation Memory storage (L1/L2/L3) |
| `logs/` | Runtime logs (NDJSON format) |
| `telemetry/` | Telemetry integration data |

**Note:** Most contents of `data/` are gitignored. Only empty directories and sample files are committed.

---

### docs/

**Purpose:** User and developer documentation.

| Subdirectory | Contents |
|--------------|----------|
| `api/` | API reference documentation |
| `architecture/` | System architecture documents |
| `configuration/` | Configuration reference |
| `deployment/` | Deployment guides (Docker, Windows) |
| `development/` | Developer guides (including this file) |
| `features/` | Feature documentation |
| `getting-started/` | Quickstart guides by persona |
| `guides/` | How-to guides |
| `operations/` | Runbooks and troubleshooting |
| `reference/` | CLI and config reference |
| `user-guide/` | End-user documentation |

---

### plans/

**Purpose:** Active implementation plans (only non-archived plans).

| Subdirectory | Contents |
|--------------|----------|
| `autonomous_workers/` | Master plan and worker implementation details |
| `from_chat/` | Plans generated from chat conversations |
| `templates/` | Plan templates for new work items |

**Note:** Completed plans are moved to `archive/plans/` after implementation.

---

### reports/

**Purpose:** Active analysis and execution reports.

| Subdirectory | Contents |
|--------------|----------|
| `agents/` | Agent execution reports (agent_a through agent_f) |
| `autonomous_workers/` | Worker analysis (FILE_MANIFEST.json, FILE_ORGANIZATION.md) |

**Note:** Historical reports are moved to `archive/reports/` after completion.

---

### requirements/

**Purpose:** Python dependency specifications.

| File | Description |
|------|-------------|
| `base.txt` | Core dependencies |
| `cpu.txt` | CPU-only dependencies |
| `gpu.txt` | GPU/CUDA dependencies |
| `dev.txt` | Development tools (pytest, black, ruff) |
| `quality.txt` | Quality checking dependencies (langdetect) |
| `docs.txt` | Documentation build dependencies |

---

### scripts/

**Purpose:** Utility scripts organized by function.

| Subdirectory | Contents |
|--------------|----------|
| `archived/` | Historical scripts (one-time use) |
| `archived/migrations/` | Database migration scripts |
| `diagnostics/` | Diagnostic utilities |
| `observability/` | Telemetry and logging scripts |

**Key Scripts:**
- `backup_tm.py` - Translation Memory backup
- `restore_tm.py` - Translation Memory restore
- `verify_telemetry.py` - Telemetry health check
- `generate_file_manifest.py` - File inventory generation

---

### specs/

**Purpose:** Technical specifications and contracts.

| File/Directory | Contents |
|----------------|----------|
| `_index.md` | Specification index |
| `configuration.md` | Configuration specification |
| `core_invariants.md` | Core system invariants (INV-001 through INV-009) |
| `features/` | Feature specifications (MCP, validation, etc.) |

---

### src/

**Purpose:** Production source code.

| Module | Lines | Description |
|--------|-------|-------------|
| `benchmarking/` | 29 files | Performance benchmarking (dev-only) |
| `model_runtime/` | 12 files | Model loading and GPU optimization |
| `observability/` | 15+ files | Logging, telemetry, git commit |
| `orchestrator/` | 5 files | Job orchestration and queue |
| `shared_engines/` | 8 files | Unified shared engines (Phase 1) |
| `tm/` | 12 files | Translation Memory (L1/L2/L3) |
| `translation_engine/` | 35+ files | Core translation logic |
| `utils/` | 6 files | Shared utilities |
| `verification/` | 8 files | Output verification |
| `workers/` | 3 files | Worker processes |
| `cli.py` | 1 file | CLI entrypoint |

#### src/shared_engines/

The shared engines module (created in Phase 1) provides unified abstractions:

| Engine | Purpose |
|--------|---------|
| `composition_root.py` | Central factory for engine instances |
| `telemetry_engine.py` | Unified telemetry (internal + benchmark DB) |
| `job_engine.py` | Job queue abstraction (memory/Redis) |
| `profile_engine.py` | Site profile resolution |
| `logging_engine.py` | Structured NDJSON logging |
| `commit_engine.py` | Git commit automation |
| `limiting_engine.py` | Resource limits (CPU/RAM/VRAM) |
| `healing_engine.py` | Retry and recovery logic |
| `worker_runner.py` | Unified worker execution |

---

### tests/

**Purpose:** Comprehensive test suite.

| Directory | Count | Description |
|-----------|-------|-------------|
| `adhoc/` | Varies | Ad-hoc manual tests (moved from root) |
| `contract/` | 4+ files | Contract tests for core invariants |
| `fixtures/` | Varies | Consolidated test fixtures |
| `golden/` | 1 file | Golden tests for CLI backward compatibility |
| `integration/` | 15+ files | Integration tests |
| `performance/` | Varies | Performance benchmarks |
| `regression/` | 6 files | Regression tests |
| `smoke/` | 3 files | Smoke tests |
| `unit/` | 60+ files | Unit tests |

**Test Targets:**
- Unit: 70%+ coverage
- Integration: 50%+ coverage
- Contract: All 9 invariants tested
- Golden: All 4 golden commands passing

---

## Root-Level Files

| File | Purpose |
|------|---------|
| `README.md` | Project overview and quickstart |
| `CHANGELOG.md` | Version history |
| `LICENSE` | License information |
| `pyproject.toml` | Python project configuration |
| `pytest.ini` | Pytest configuration |
| `Dockerfile` | CPU Docker image |
| `Dockerfile.gpu` | GPU Docker image |
| `docker-compose.yml` | Docker orchestration |
| `.gitignore` | Git ignore patterns |
| `.pre-commit-config.yaml` | Pre-commit hooks |

---

## Files Excluded from Repository

The following are gitignored and should never be committed:

### Virtual Environments
- `venv/`, `.venv/`, `venv-*/` - Python virtual environments

### Cache Directories
- `.mypy_cache/` - Type checker cache
- `.pytest_cache/` - Test cache
- `.benchmarks/` - Benchmark cache
- `.cache/` - General cache
- `__pycache__/` - Python bytecode cache

### Build Artifacts
- `*.egg-info/` - Package metadata
- `htmlcov/` - Coverage reports
- `dist/`, `build/` - Distribution files

### Runtime Files
- `*.log` - Log files
- `.coverage` - Coverage data
- `*.db` (except committed schemas) - SQLite databases
- `telemetry_buffer/` - Telemetry buffer
- `.translation_progress/` - Progress tracking

---

## Migration Notes

### Files Moved (Phase 6)

| Original Location | New Location | Rationale |
|-------------------|--------------|-----------|
| Root `test_*.py` | `tests/unit/` or `tests/adhoc/` | Consolidate tests |
| `test_fixtures/` | `tests/fixtures/` | Standard location |
| `run_translation.py` | `scripts/` | Script organization |
| Migration scripts | `scripts/archived/migrations/` | One-time scripts |

### Files Archived (Phase 6)

| Original Location | Archive Location | Rationale |
|-------------------|-----------------|-----------|
| `legacy/` | `archive/legacy/` | Historical preservation |
| `reports/phase-*/` | `archive/reports/phases/` | Completed phases |
| `plans/_archive/` | `archive/plans/` | Completed plans |

### Files Deleted (Phase 6)

| Item | Reason |
|------|--------|
| Virtual environments | Should never be in git (~13.5 GB) |
| Empty directories | Cleanup |
| Malformed directories | Path errors |
| Cache directories | Build artifacts |

---

## See Also

- FILE_ORGANIZATION.md - Detailed organization plan (archived)
- FILE_MANIFEST.json - Complete file inventory (archived)
- MASTER_PLAN.md - Phase 6 implementation plan (archived)

---

*Document generated: 2026-01-15*
*Agent: Agent D (Docs & Specs)*
*Work Item: WI-P6-004*
