# Hugo Translation System - Specification Index

**Last Updated:** 2026-01-15
**Status:** Initial spec mining complete, verification pending

---

## Overview

The Hugo Translation System is a production-ready automated translation system for Hugo static sites. It provides:

- **Multi-site support** with per-site configuration profiles
- **3-layer Translation Memory** (L1 in-memory, L2 persistent, L3 semantic)
- **10-validator quality pipeline** with intelligent retry
- **Distributed architecture** (orchestrator + workers via MCP or Redis)
- **CLI and API interfaces** for various usage patterns
- **Crash recovery** with progress tracking and atomic writes

---

## System Architecture

```
┌─────────────────────────────────────────────────────┐
│                   User Interfaces                    │
├──────────────┬──────────────┬───────────────────────┤
│  CLI         │  MCP Tools   │  Docker Services      │
│  (primary)   │  (worker)    │  (production)         │
└──────┬───────┴──────┬───────┴──────┬────────────────┘
       │              │              │
       ▼              ▼              ▼
┌─────────────────────────────────────────────────────┐
│            Translation Engine Core                   │
│  ┌──────────┬──────────┬──────────┬──────────┐      │
│  │  Parser  │Extractor │Validator │Translator│      │
│  └────┬─────┴────┬─────┴────┬─────┴────┬─────┘      │
└───────┼──────────┼──────────┼──────────┼────────────┘
        │          │          │          │
        ▼          ▼          ▼          ▼
┌──────────┬──────────┬──────────┬──────────────────┐
│   TM     │ Config   │ Model    │  Observability   │
│  L1/L2/L3│ Service  │ Loader   │  (Metrics/Logs)  │
└──────────┴──────────┴──────────┴──────────────────┘
```

---

## Core Invariants

### Must (Critical - Never Violate)

1. **Multi-language subprocess isolation:** When translating multiple target languages, MUST use separate subprocesses to prevent model state contamination
   - Evidence: `src/cli.py` lines 1090-1178
   - Rationale: M2M100 model retains internal state causing language bleed

2. **Atomic file writes:** Output files MUST be written atomically (temp file + rename) to prevent corruption
   - Evidence: `src/utils/atomic_write.py`
   - Rationale: Prevent partial writes on crash/interrupt

3. **TM 3-layer lookup order:** Translation Memory lookups MUST follow L1 → L2 → L3 order
   - Evidence: `src/tm/translation_memory.py`
   - Rationale: Performance optimization (fast→slow), preserve cache hierarchy

4. **Critical validator rejection:** Placeholder, CodeBlock, and Link validator failures MUST always result in REJECT decision
   - Evidence: `src/translation_engine/validation/decision_engine.py`
   - Rationale: Protect syntactic integrity (shortcodes, code, links cannot be corrupted)

5. **Site-level file locking:** Only one translation process MUST be active per site at a time
   - Evidence: `src/utils/file_lock.py`, used in `translate_directory()`
   - Rationale: Prevent concurrent TM corruption and output conflicts

6. **Graceful L3 index persistence:** L3 FAISS index MUST be saved on shutdown (SIGINT/SIGTERM)
   - Evidence: `src/cli.py:setup_unified_signal_handler()` lines 867-932
   - Rationale: Prevent loss of semantic TM data

### Should (Important - Avoid Violating)

7. **Validation retry limit:** SHOULD limit retry attempts to configured max (default: 2)
   - Evidence: `src/translation_engine/engine.py` validation loop
   - Rationale: Prevent infinite retry loops

8. **Progress file validation:** SHOULD validate and attempt recovery of corrupted progress files
   - Evidence: `src/cli.py` lines 1035-1063
   - Rationale: Maximize recovery success rate

9. **TM hit rate monitoring:** SHOULD track and log TM hit rates for observability
   - Evidence: `TranslationStats.tm_hit_rate` property
   - Rationale: Performance visibility

10. **Disk space pre-check:** SHOULD check free disk space before translation (>2x content size)
    - Evidence: `src/translation_engine/engine.py:_write_output()`
    - Rationale: Prevent mid-translation disk full errors

### May (Configurable - User Choice)

11. **Validation strictness:** MAY use strict/normal/lenient validation modes per use case
    - Evidence: `--validation-mode` CLI flag
    - Config: Site profile or CLI override

12. **Cache write mode:** MAY use auto/always/never cache write modes
    - Evidence: `--cache-write-mode` CLI flag
    - Use cases: Read-only mode for testing, always for corpus building

13. **Parallel execution:** MAY process languages in parallel or round-robin
    - Evidence: `--parallel-languages`, `--global-lang-rounds` flags
    - Constraint: Mutually exclusive

### Never (Prohibited)

14. **NEVER modify TM without successful translation:** Do not store failed/rejected translations in TM
    - Evidence: TM update only on ACCEPT decision
    - Rationale: Preserve TM quality

15. **NEVER mix cache modes and parallel flags:** Do not use both `--parallel-languages` and `--global-lang-rounds`
    - Evidence: `src/cli.py` lines 198-202 (raises ValueError)
    - Rationale: Undefined behavior, mutual exclusion required

16. **NEVER skip validation for critical validators:** Even in lenient mode, critical validators must run
    - Evidence: `decision_engine.py` critical validator list
    - Rationale: Syntactic integrity non-negotiable

---

## Feature Specifications

### CLI Features

- [CLI-001: Main Translation Command](features/cli-001-main-translate.md)
- [CLI-002: Validation Control](features/cli-002-validation-control.md)
- [CLI-005: Resume Control](features/cli-005-resume-control.md)

### MCP Tools

- [MCP-001: translate_hugo_file Tool](features/mcp-001-translate-file.md)

<!-- NOTE: MCP-003 (tm_exact_lookup) and MCP-005 (health_check) removed 2026-01-15
     These were planned specs that were never implemented. References removed to
     eliminate broken links. See reports/agents/agent_d/wi002_wi003_docs/run_20260115_231500/
     for documentation of this change. -->

### Translation Engine

- [API-001: translate_file Method](features/api-001-translate-file.md)
- [API-002: translate_directory Method](features/api-002-translate-directory.md)

### Translation Memory

- [TM-001: L1 In-Memory Cache](features/tm-001-l1-cache.md)
- [TM-002: L2 Persistent Store](features/tm-002-l2-persistent.md)
- [TM-003: L3 Semantic Search](features/tm-003-l3-semantic.md)

### Validation Pipeline

- [VAL-001: Decision Engine (ACCEPT/RETRY/REJECT)](features/val-001-decision-engine.md)
- [VAL-002: Critical Validators](features/val-002-critical-validators.md)

### Infrastructure

- [SVC-001: Orchestrator Service](features/svc-001-orchestrator.md)
- [SVC-002: Worker Service](features/svc-002-worker-service.md)

---

## Verification Status Legend

- ✅ **VERIFIED:** Spec tested against actual implementation, contract test exists
- 🔍 **EVIDENCE_ONLY:** Spec extracted from code, no contract test yet
- 🤔 **INFERRED:** Spec inferred from architecture, needs verification
- ⚠️ **NEEDS_UPDATE:** Spec may be outdated, requires review

**Current Status:** All specs are 🔍 **EVIDENCE_ONLY** pending contract test creation.

---

## Configuration Schema Contracts

### Site Profile Schema (config/site_profiles/{site_id}.yaml)

```yaml
site_id: string                  # REQUIRED
content_roots: list[string]      # REQUIRED - source content paths
target_langs: list[string]       # REQUIRED - target language codes
output_dir: string               # REQUIRED - output directory
default_source_lang: string      # OPTIONAL - default: "en"
default_model: string            # OPTIONAL - default: "m2m100_418m"
tm_prefs:                        # OPTIONAL
  use_semantic_tm: bool          # default: true
frontmatter_config:              # OPTIONAL
  translatable_fields: list[string]
  protected_fields: list[string]
body:                            # OPTIONAL
  sort_segments_by_length: bool  # default: false
```

### Model Registry Schema (config/model_registry.yaml)

```yaml
models:
  - model_id: string             # REQUIRED - unique identifier
    hf_repo: string              # REQUIRED - HuggingFace repo
    family: string               # REQUIRED - m2m100/nllb/opus
    size_mb: int                 # REQUIRED
    supported_devices: list[string]  # cpu/cuda
    capabilities:                # REQUIRED
      max_input_length: int
      max_output_length: int
      supported_languages: list[string]
```

---

## Decision Logs

No behavior change decisions yet. All specs reflect current implementation as-is.

---

## Next Steps: Contract Test Creation

To transition specs from EVIDENCE_ONLY to VERIFIED status:

1. Create `tests/contract/` directory
2. Add pytest marker: `@pytest.mark.contract`
3. Write contract tests for:
   - CLI command invariants (multi-lang isolation, atomic writes)
   - TM layer lookup order
   - Validation decision engine (ACCEPT/RETRY/REJECT)
   - Critical validator behavior
   - File locking behavior
   - Signal handler shutdown sequence
4. Link tests to spec sections (docstring references)
5. Add CI gate to prevent contract test modifications without spec updates

---

## Spec Authoring Guidelines

When writing feature specs in `specs/features/`, follow this template:

```markdown
# Feature ID: {AREA}-{NUMBER}

## Summary
One-line feature description

## Entry Points
- CLI: command/flag
- API: method signature
- MCP: tool name
- Event: trigger type

## Inputs/Outputs
- Input schema
- Output schema
- Error codes

## Invariants
### Must
- Critical constraints

### Should
- Important guidelines

### Never
- Prohibited behaviors

## Errors and Edge Cases
- Error conditions
- Exception types
- Recovery strategies

## Config and Environment
- Configuration keys
- Environment variables
- Defaults

## Side Effects
- File system changes
- Cache updates
- Metrics emission
- Network calls

## Evidence
- File: path
- Lines: X-Y
- Symbol: function/class name
- Verification: code/test/config

## Verification Status
🔍 EVIDENCE_ONLY | ✅ VERIFIED | 🤔 INFERRED | ⚠️ NEEDS_UPDATE
```

---

## Repository Structure

The repository follows a structured organization defined in Phase 6 (Repo File Organization). See:

- [REPO_STRUCTURE.md](../docs/development/REPO_STRUCTURE.md) - Detailed directory documentation
- [FILE_ORGANIZATION.md](../reports/autonomous_workers/FILE_ORGANIZATION.md) - Organization plan with KEEP/MOVE/ARCHIVE/DELETE decisions

### Key Directories

| Directory | Purpose |
|-----------|---------|
| `src/` | Production source code |
| `tests/` | Unit, integration, contract, regression tests |
| `config/` | Site profiles, terminology, validation rules |
| `specs/` | Technical specifications (this directory) |
| `docs/` | User and development documentation |
| `scripts/` | Utility and maintenance scripts |
| `archive/` | Historical artifacts (legacy, old reports) |

---

## Maintenance

This index and all feature specs are living documents. Update when:

- Behavior changes are approved and merged (Mode: BEHAVIOR_CHANGE)
- New features are added
- Bugs reveal misunderstood invariants
- Contract tests uncover spec gaps

Always update specs BEFORE modifying contract tests (spec is source of truth).

---

## Phase 6 Completion Note

**Date:** 2026-01-15

Phase 6 (Repo File Organization) of the Autonomous Workers Unification project is COMPLETE. This phase produced:

1. **FILE_MANIFEST.json** - Complete inventory of 151,642 files (51.29 GB)
2. **FILE_ORGANIZATION.md** - Organization plan categorizing files into KEEP/MOVE/ARCHIVE/DELETE
3. **reorganize_repo.py** - Automated migration script with dry-run mode
4. **REPO_STRUCTURE.md** - Comprehensive repository structure documentation

All deliverables passed self-review gate (≥4/5 on all 12 dimensions).
