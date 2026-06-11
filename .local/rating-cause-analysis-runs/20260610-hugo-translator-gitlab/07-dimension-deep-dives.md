# Dimension Deep Dives

## Architecture Quality (6.5/10)

**Strengths**:
- Clear module boundaries for some subsystems (tm/, validation/, parser/)
- Plugin-like validator architecture (ValidationSuite with registered validators)
- Worker separation (content, TM improvement, verification)
- Config-driven behavior (YAML profiles, quality gates)

**Weaknesses**:
- TranslationEngine god-class (5,613 lines) violates SRP severely
- CLI module (3,137 lines) mixes orchestration with presentation
- No dependency injection framework — components wired via __init__ args + kwargs
- Circular import risk: engine.py has 30+ imports from sibling/parent modules
- No clear architectural layers (no ports/adapters, no service layer)

---

## Code Quality (7.0/10)

**Strengths**:
- Pre-commit hooks with ruff + private key detection
- Good naming conventions in general
- Type hints present throughout
- Zero bare except blocks
- Zero shell=True subprocess calls

**Weaknesses**:
- 689 `except Exception` blocks (swallowing)
- 26 suppressed ruff rules (including complexity C901)
- Mypy config present but never run
- Only 2 TODO/FIXME markers in 94K lines (either very clean or markers not used)

---

## Test Confidence (7.0/10)

**Strengths**:
- 472 test files, ~1,500 tests total
- Contract tests (298) verify behavioral invariants
- Regression tests for specific past bugs
- Phased test organization (phase-0 through phase-8)

**Weaknesses**:
- Coverage gate disabled
- CI runs ~13% of tests
- Main engine method (translate_file) is 1,417 lines with no dedicated test file
- Only 3 e2e tests
- Only 2 security tests
- 69 integration tests exist but don't run in CI

---

## Operational Maturity (7.0/10)

**Strengths**:
- 5 CI workflows covering different aspects
- Pre-commit hooks configured
- Health check script exists
- Heartbeat/PID file mechanism for workers
- Atomic file writes with error handling

**Weaknesses**:
- Worker health check is manual-trigger only
- CI runs subset of tests
- Coverage enforcement disabled
- No lock file for pip (just requirements/*.txt with >=)
- No automated rollback mechanism

---

## Maintainability (6.0/10)

**Strengths**:
- Contributing guide exists with quickstart
- Getting-started docs with onboarding, operator, contributor quickstarts
- Setup script exists (scripts/setup_dev_env.py)

**Weaknesses**:
- 5,613-line god-class is intimidating to new contributors
- 1,417-line method is impossible to understand
- 26 suppressed lint rules mean code smells are accepted
- No architectural decision records (ADRs)
- Mypy never run — type annotations may be wrong

---

## Agentic Workflow Maturity (7.0/10)

**Strengths**:
- AGENTS.md with clear worker documentation
- AGENT_GUARDRAILS.md with 4 critical rules
- workers.yaml with cooldowns, max_runtime, max_concurrent
- Campaign sentinel file mechanism
- Graceful shutdown coordination in engine

**Weaknesses**:
- All enforcement is convention-based (prose rules, not code)
- Health check is manual-only
- Workers run on Windows Task Scheduler — single-machine constraint
- No distributed coordination (filesystem-based locking only)
- No automated guardrail enforcement
