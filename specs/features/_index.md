# Features Index

## Overview

This document provides an index of all features in the Hugo Translation System. Each feature is documented in a separate Markdown file in this directory.

## Feature Categories

### Core Translation Features

- **[api-001-translate-file](api-001-translate-file.md)**: Translate a single file
- **[api-002-translate-directory](api-002-translate-directory.md)**: Translate a directory of files
- **[cli-001-main-translate](cli-001-main-translate.md)**: Main CLI translation command
- **[cli-002-validation-control](cli-002-validation-control.md)**: Validation control flags
- **[cli-005-resume-control](cli-005-resume-control.md)**: Resume and restart control

### Translation Memory Features

- **[tm-001-l1-cache](tm-001-l1-cache.md)**: L1 in-memory cache
- **[tm-002-l2-persistent-store](tm-002-l2-persistent-store.md)**: L2 persistent storage
- **[tm-003-l3-semantic-search](tm-003-l3-semantic-search.md)**: L3 semantic search

### Validation Features

- **[val-001-decision-engine](val-001-decision-engine.md)**: Validation decision engine
- **[val-002-critical-validators](val-002-critical-validators.md)**: Critical validation rules

### Benchmarking Features

- **[bm-001-model-benchmarking](bm-001-model-benchmarking.md)**: Model benchmarking and performance testing

### Model Features

- **[mcp-001-translate-file](mcp-001-translate-file.md)**: MCP-based file translation

## Feature Status

| Feature ID | Status | Last Reviewed | Contract Test |
|------------|--------|---------------|---------------|
| api-001-translate-file | EVIDENCE_ONLY | 2026-01-13 | - |
| api-002-translate-directory | EVIDENCE_ONLY | 2026-01-13 | - |
| cli-001-main-translate | EVIDENCE_ONLY | 2026-01-13 | - |
| cli-002-validation-control | VERIFIED | 2026-01-16 | test_inv005_validation_mode.py (11 tests) |
| cli-005-resume-control | VERIFIED | 2026-01-16 | test_inv007_resume_skip.py (13 tests) |
| tm-001-l1-cache | VERIFIED | 2026-01-16 | test_inv003_tm_lookup.py (9 tests) |
| tm-002-l2-persistent-store | VERIFIED | 2026-01-16 | test_inv003_tm_lookup.py (9 tests) |
| tm-003-l3-semantic-search | VERIFIED | 2026-01-16 | test_inv003_tm_lookup.py, test_inv009_l3_periodic_saves.py (20 tests) |
| val-001-decision-engine | VERIFIED | 2026-01-16 | test_inv005_validation_mode.py (11 tests) |
| val-002-critical-validators | VERIFIED | 2026-01-16 | test_validation_critical.py (11 tests) |
| bm-001-model-benchmarking | EVIDENCE_ONLY | 2026-01-13 | - |
| mcp-001-translate-file | EVIDENCE_ONLY | 2026-01-13 | - |

## Feature Coverage

- **Total Features**: 12
- **Verified Features**: 7
- **Evidence-Only Features**: 5
- **Inferred Features**: 0

## Contract Test Coverage (Infrastructure)

The following contract tests verify core invariants that underpin multiple features:

| Contract Test | Invariant | Tests | Coverage |
|---------------|-----------|-------|----------|
| test_inv001_subprocess.py | Subprocess Isolation | 12 | Core infrastructure |
| test_inv002_atomic_writes.py | Atomic File Writes | 16 | File I/O safety |
| test_inv006_file_locking.py | File Locking | 15 | Concurrency safety |
| test_inv008_git_commit.py | Git Commit | 14 | Observability |

**Total Contract Tests**: 112 tests across 9 test files

## Next Steps

1. ~~Verify all features by running them and updating their status~~
2. Add missing evidence for features with incomplete documentation
3. Update feature specifications with detailed information
4. Add new features as they are discovered or implemented
5. Create contract tests for remaining EVIDENCE_ONLY features:
   - api-001-translate-file
   - api-002-translate-directory
   - cli-001-main-translate
   - bm-001-model-benchmarking
   - mcp-001-translate-file

---

## Update Log

### Update - 2026-01-16 19:00 PKT

**Agent D (Docs & Specs)** - Updated feature status based on existing contract tests.

**Changes:**
- Added "Contract Test" column to Feature Status table
- Updated 7 features from EVIDENCE_ONLY to VERIFIED status:
  - cli-002-validation-control (test_inv005_validation_mode.py)
  - cli-005-resume-control (test_inv007_resume_skip.py)
  - tm-001-l1-cache (test_inv003_tm_lookup.py)
  - tm-002-l2-persistent-store (test_inv003_tm_lookup.py)
  - tm-003-l3-semantic-search (test_inv003_tm_lookup.py + test_inv009_l3_periodic_saves.py)
  - val-001-decision-engine (test_inv005_validation_mode.py)
  - val-002-critical-validators (test_validation_critical.py)
- Added "Contract Test Coverage (Infrastructure)" section for cross-cutting concerns
- Updated Feature Coverage statistics (7 verified, 5 evidence-only)
- Updated Next Steps to reflect verified features and list remaining work
