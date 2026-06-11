# Root-Cause Findings Catalog

## RCA-001: God-Class Anti-Pattern in TranslationEngine

**Severity**: HIGH
**Dimensions affected**: Architecture Quality, Maintainability, Test Confidence
**Evidence**: `src/translation_engine/engine.py` — 5,613 lines, 57 methods, single class

### Description
`TranslationEngine` is a monolithic god-class that handles:
- File translation orchestration
- Language detection integration
- TM cache management
- GPU OOM recovery
- Adaptive batch sizing
- Telemetry tracking
- Quality validation
- File writing
- Graceful shutdown coordination
- Git commit association
- Content hash tracking
- Disk space checking
- Model selection
- Review caching

### Causal Chain
God-class → can't test individual concerns in isolation → low mutation resilience → can't safely refactor → more code gets added to the same file → accelerating tech debt.

### Evidence
- `__init__` method spans lines 209-603 (395 lines)
- `translate_file` method spans lines 1354-2770 (1,417 lines — a single method)
- `_translate_directory_locked` is another ~400+ line method
- 84 `except Exception` blocks in engine.py alone (swallowing errors)

---

## RCA-002: Excessive Exception Swallowing

**Severity**: HIGH
**Dimensions affected**: Code Quality, Operational Maturity, Functional Clarity
**Evidence**: 689 `except Exception` blocks across 125 src/ files; 0 bare excepts (good)

### Description
Nearly every operation in the codebase wraps failures in `except Exception` with a `logger.warning()` or `logger.debug()` and continues. While this provides graceful degradation, it:
- Hides real bugs behind warning logs
- Makes failures non-deterministic (works sometimes, silently wrong other times)
- Makes debugging production issues extremely difficult

### Causal Chain
Exception swallowing → silent failures → bugs discovered only in production by humans reading logs → low confidence in automated monitoring → operational maturity ceiling.

### Key Offenders
- `engine.py`: 84 `except Exception` blocks
- `autonomous_content_translation_worker.py`: 48 blocks
- `cli.py`: 36 blocks
- `git_commit_helper.py`: 27 blocks
- `benchmarking/scheduler.py`: 15 blocks

---

## RCA-003: Ruff Rule Suppression as Tech Debt

**Severity**: MEDIUM
**Dimensions affected**: Code Quality, Maintainability
**Evidence**: `pyproject.toml` lines 118-144 — 26 suppressed ruff rules

### Description
The ruff config suppresses 26 lint rules marked "tracked as tech debt":
- B904: raise-without-from (loses exception context)
- B007: unused loop control variable
- F841: assigned-but-never-used variables
- E741: ambiguous variable names
- B023: function-uses-loop-variable (closure bugs)
- C901: too complex (explicitly ignoring complexity!)
- Plus 14 more

### Causal Chain
Rapid feature development → lint violations accumulate → easier to suppress than fix → suppression list grows → actual bugs hide among style issues → code quality ceiling.

---

## RCA-004: Test Coverage Gate Disabled

**Severity**: HIGH
**Dimensions affected**: Test Confidence, Operational Maturity
**Evidence**: `config/quality_gates.yaml` line `enabled: false` for test_coverage gate

### Description
The quality gates config explicitly disables the test coverage gate. Despite pyproject.toml configuring `--cov=src`, coverage is never enforced. No .mypy_cache exists, indicating mypy has never been run either.

### Causal Chain
No coverage enforcement → untested code paths accumulate → false confidence from passing tests → regression risk on any change → low adoption confidence.

### Additional Evidence
- 472 test files but test_engine.py (the main engine) is only 1,586 lines for a 5,613-line class
- `translate_file` (1,417 lines) has no dedicated unit test file — only tested indirectly via integration/contract tests
- Only 3 e2e test files exist
- Only 2 security-related test files (test_pii_sanitization.py, test_log_sanitizer.py)

---

## RCA-005: CI Runs Only Subset of Tests

**Severity**: MEDIUM
**Dimensions affected**: Operational Maturity, Test Confidence
**Evidence**: `.github/workflows/release_gate.yml`

### Description
The release gate CI workflow:
1. Runs translation_engine unit tests ✓
2. Runs validation unit tests ✓
3. Runs only 4 specific contract tests (out of ~298)
4. Runs only phase-0, phase-1, and 3 specific phase-3/4 tests
5. Does NOT run: 69 integration tests, 3 e2e tests, benchmarking tests, observability tests, worker tests, TM tests

### Causal Chain
Selective CI → regressions in untested subsystems go unnoticed → bugs reach production → manual verification burden → operational maturity ceiling.

### Additional Issue
Worker health check workflow requires self-hosted runner and is manual-trigger only. Telemetry health check and content structure scan are also limited.

---

## RCA-006: CLI Mega-Module (3,137 lines)

**Severity**: MEDIUM
**Dimensions affected**: Maintainability, Architecture Quality
**Evidence**: `src/cli.py` — 3,137 lines, 30+ functions

### Description
The CLI module contains:
- Argument parsing (381-870: ~490 lines of argparse setup)
- Heavy dependency lazy loading
- Benchmarking config loading/validation
- Signal handling
- Verification report generation
- Logging setup (110+ lines)
- Full site translation orchestration (translate_site: 1517-2990: ~1,470 lines)
- Lock management (cmd_unlock, cmd_diagnose_lock)
- Subprocess management for parallel language processing

### Causal Chain
CLI as orchestration layer → business logic mixed with presentation → can't test translation orchestration without CLI → testing requires mocking argparse → lower test coverage of orchestration logic.

---

## RCA-007: No Mypy Ever Run

**Severity**: MEDIUM
**Dimensions affected**: Code Quality, Maintainability
**Evidence**: No `.mypy_cache` directory exists despite extensive mypy config in pyproject.toml

### Description
The project has a detailed mypy configuration (strict mode, disallow_untyped_defs, etc.) but has never actually run mypy. The config is aspirational — it claims strict typing discipline but has never been validated.

### Causal Chain
Config without enforcement → false sense of type safety → type errors accumulate → eventual mypy run would produce hundreds/thousands of errors → config becomes more aspirational over time.

---

## RCA-008: Translate-File Method is 1,417 Lines

**Severity**: HIGH
**Dimensions affected**: Architecture Quality, Maintainability, Code Quality
**Evidence**: `src/translation_engine/engine.py` lines 1354-2770

### Description
The `translate_file()` method is 1,417 lines long. It handles:
- Telemetry initialization and teardown
- Site profile loading
- Metadata tracker initialization
- Content hash checking
- File change detection
- Segment extraction
- Multi-language iteration (3 different modes)
- TM lookup
- Model translation
- Validation decision engine
- Retry logic with feedback
- OOM recovery
- File writing
- Progress tracking
- GPU cache clearing

A single method doing all this makes it impossible to test individual translation phases, understand failure modes, or reason about correctness.

---

## RCA-009: Documentation Exists But Claims Are Unverified

**Severity**: MEDIUM
**Dimensions affected**: Documentation Trustworthiness, Adoption Confidence
**Evidence**: 123 doc files, config/claims.yaml exists

### Description
The project has extensive documentation (123 files) covering architecture, deployment, quality, and operations. However:
- Docs and src last commits are same day (May 30), suggesting batch generation
- `config/claims.yaml` exists — a structured claims file — but no CI step verifies claims
- README claims "10 validators" but the actual count may differ
- No automated link checking or doc freshness enforcement

### Causal Chain
Docs generated in batches → drift from code → claims become aspirational → new contributors can't trust docs → adoption friction.

---

## RCA-010: Worker Governance Relies on Convention, Not Enforcement

**Severity**: MEDIUM
**Dimensions affected**: Agentic Workflow Maturity, Operational Maturity
**Evidence**: AGENTS.md, docs/AGENT_GUARDRAILS.md, config/workers.yaml

### Description
The project has thoughtful worker governance documentation:
- AGENTS.md describes 3 workers with modes, flags, and useful_work_criteria
- AGENT_GUARDRAILS.md defines 4 critical rules (never edit outputs, always run release gate, etc.)
- workers.yaml has cooldowns, max_runtime, max_concurrent settings

But enforcement is soft:
- Worker health check is manual-trigger only (workflow_dispatch)
- No scheduled heartbeat monitoring in CI
- No automated enforcement of guardrails (they're prose rules, not code constraints)
- Campaign sentinel files are filesystem-based (no distributed coordination)
- The content worker has only 1 dedicated unit test file

### Causal Chain
Convention-based governance → relies on developer discipline → violations go undetected → agentic workflow maturity ceiling.

---

## RCA-011: Pre-commit Hooks Present But Incomplete

**Severity**: LOW
**Dimensions affected**: Code Quality, Operational Maturity
**Evidence**: `.pre-commit-config.yaml`

### Description
Pre-commit hooks include:
- trailing-whitespace, end-of-file-fixer, check-yaml ✓
- detect-private-key ✓
- ruff check + format ✓
- no-hardcoded-paths (custom) ✓

Missing:
- No mypy hook (despite detailed config)
- No test runner hook
- No commit message linting
- ruff-format only checks (--check), doesn't auto-fix

---

## RCA-012: 17 Files Use subprocess Without Shell=True (Good) But Without Input Sanitization Review

**Severity**: LOW
**Dimensions affected**: Security/Safety
**Evidence**: 17 src/ files use subprocess, 0 use shell=True

### Description
Positive: No `shell=True` usage anywhere. All subprocess calls use list-form arguments.
However: The subprocess calls in git_commit.py (7 calls) and cli.py (2 calls) pass user-influenced data (file paths, commit messages) without explicit sanitization. This is mitigated by not using shell=True but could still be a concern if any path contains adversarial content.

---

## RCA-013: Dependency Version Ranges Too Broad

**Severity**: LOW
**Dimensions affected**: Integration Fitness, Operational Maturity
**Evidence**: `pyproject.toml` dependencies use `>=` with no upper bounds

### Description
All core dependencies use `>=` without upper bounds:
- `torch>=2.1.0` (could get torch 3.x)
- `transformers>=4.35.0` (API-breaking changes common)
- `sentence-transformers>=2.2.0` (already hit deprecation in this sprint)
- `faiss-cpu>=1.7.0`

The requirements/cpu.txt file does `pip install -r base.txt` which similarly lacks pins.

### Causal Chain
Unbounded versions → different team members get different versions → "works on my machine" → CI may pass on one version, fail on another → integration fragility.
