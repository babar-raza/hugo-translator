# Phase 1 - Rating Parameter Model

> Docs-only changes do NOT improve a rating unless the weakness was specifically documentation trustworthiness AND the docs are source-grounded, validated, and protected from drift.

## 1. Functional Clarity (weight: high)

- **10/10**: Every feature described in README/docs is implemented, tested, and provably works. CLI --help matches actual behavior. All modes (strict/normal/lenient, dry-run) are exercised by tests.
- **7/10**: Core features work and are tested. Some edge cases undocumented or untested.
- **5/10**: Main workflow works but secondary features (e.g., specific validation modes) are untested or broken.
- **3/10**: Core workflow has known failures. README claims features that don't work.
- **Evidence**: Test results for each claimed feature. CLI smoke test output. dry-run proof.
- **Common weaknesses**: README claims untested features; CLI flags that don't work; missing dry-run proof.
- **Real improvements**: Add tests for each CLI flag; fix broken features; add smoke tests.
- **Validators/gates**: CLI smoke test gate; feature-claim validator.
- **Not improvement**: Adding feature descriptions to docs without tests.

## 2. Architecture Quality (weight: medium)

- **10/10**: Clear module boundaries, dependency direction, no circular imports, separation of concerns.
- **7/10**: Good separation with minor coupling. No circular imports.
- **5/10**: Some circular dependencies or monolithic modules. Mixed responsibilities.
- **3/10**: Tightly coupled modules, unclear boundaries, import hacks.
- **Evidence**: Import dependency analysis. Module size distribution. Circular import check.
- **Common weaknesses**: Circular imports; god-modules; mixed CLI/engine logic.
- **Real improvements**: Break circular imports; extract shared logic; enforce boundaries.
- **Validators/gates**: Circular import detector; module size check.
- **Not improvement**: Drawing architecture diagrams without fixing structure.

## 3. Code Quality (weight: medium)

- **10/10**: Lint-clean (ruff/black), type-checked (mypy), no dead code, consistent style.
- **7/10**: Mostly lint-clean. Type hints on public APIs. Minor dead code.
- **5/10**: Lint passes with many ignores. Inconsistent style. Some dead code.
- **3/10**: Lint fails or is disabled. No type checking. Widespread dead code.
- **Evidence**: Ruff output. Mypy output. Dead code analysis.
- **Common weaknesses**: Too many ruff ignores; mypy disabled; dead code accumulation.
- **Real improvements**: Fix lint violations; reduce ruff ignores; enable mypy on critical paths.
- **Validators/gates**: Ruff check in CI; mypy check on critical modules.
- **Not improvement**: Adding more ignores to make lint pass.

## 4. Operational Maturity (weight: high)

- **10/10**: Health checks, graceful shutdown, log rotation, metrics, monitoring, backup/restore, rollback.
- **7/10**: Basic health checks and monitoring. Graceful shutdown works. Logs structured.
- **5/10**: Some operational scripts exist but are untested or manual-only.
- **3/10**: No health checks, no graceful shutdown, no operational scripts.
- **Evidence**: Health check test output. Graceful shutdown test. Log sample. Backup/restore proof.
- **Common weaknesses**: Untested operational scripts; no graceful shutdown test; stale health checks.
- **Real improvements**: Test health checks; test graceful shutdown; add backup verification.
- **Validators/gates**: Health check smoke test; shutdown integration test.
- **Not improvement**: Writing runbooks without testing the procedures.

## 5. Test Confidence (weight: critical)

- **10/10**: >80% coverage, all critical paths tested, failure-path tests, idempotency tests, contract tests, CI enforced.
- **7/10**: >60% coverage, critical paths tested, some failure-path tests. CI runs tests.
- **5/10**: Tests exist but coverage unknown. Many untested critical paths. CI may be broken.
- **3/10**: Few tests, many failing, no CI enforcement.
- **Evidence**: pytest output with coverage. CI run results. Test failure analysis.
- **Common weaknesses**: Unknown coverage; failing tests; no failure-path tests; flaky tests.
- **Real improvements**: Fix failing tests; add missing critical-path tests; enable coverage reporting.
- **Validators/gates**: CI test gate; minimum coverage gate; zero-failure gate.
- **Not improvement**: Adding path-only tests that check file existence.

## 6. Documentation Trustworthiness (weight: medium)

- **10/10**: Docs generated from or validated against source. No stale claims. Setup instructions tested.
- **7/10**: Docs mostly accurate. Setup instructions work. Minor staleness.
- **5/10**: Some docs stale. Setup instructions may not work. Claims not validated.
- **3/10**: Docs significantly stale. README claims unimplemented features. Setup broken.
- **Evidence**: Docs-vs-source consistency check. Setup instruction test. Stale claim audit.
- **Common weaknesses**: Stale feature claims; untested setup instructions; historical reports as current truth.
- **Real improvements**: Audit and fix stale claims; test setup instructions; add doc validation.
- **Validators/gates**: Stale-claim detector; setup instruction test.
- **Not improvement**: Adding more docs without fixing stale ones.

## 7. Security and Safety Confidence (weight: high)

- **10/10**: No secrets in code, input validation, safe defaults, dry-run mode, no command injection.
- **7/10**: No secrets in code. Basic input validation. Dry-run exists.
- **5/10**: Some input validation missing. No secret scanning. Dry-run untested.
- **3/10**: Secrets in code or config. No input validation. Unsafe defaults.
- **Evidence**: Secret scan output. Input validation audit. Dry-run test.
- **Common weaknesses**: Hardcoded paths/tokens; missing input validation; no secret scanning.
- **Real improvements**: Add secret scanning; fix input validation gaps; test dry-run.
- **Validators/gates**: Secret scan gate; input validation test.
- **Not improvement**: Adding security policy document without fixing code.

## 8. Integration Fitness (weight: medium)

- **10/10**: All external integrations tested (Git, Hugo, models, LMDB). Integration tests in CI.
- **7/10**: Key integrations tested. Some integration tests. Hugo build check in CI.
- **5/10**: Few integration tests. External dependencies assumed to work.
- **3/10**: No integration tests. External dependencies untested.
- **Evidence**: Integration test results. Hugo build output. Model loading test.
- **Common weaknesses**: Missing integration tests; untested external dependencies.
- **Real improvements**: Add integration tests for critical external dependencies.
- **Validators/gates**: Hugo build check; model loading smoke test.
- **Not improvement**: Documenting integrations without testing them.

## 9. Maintainability (weight: medium)

- **10/10**: Clear naming, small functions, no tech debt accumulation, easy onboarding.
- **7/10**: Mostly maintainable. Some large files. Tech debt tracked.
- **5/10**: Large monolithic files. Tech debt not tracked. Onboarding unclear.
- **3/10**: Unmaintainable code. No documentation for contributors. Massive tech debt.
- **Evidence**: File size distribution. Tech debt tracking. CONTRIBUTING.md quality.
- **Common weaknesses**: Large files; untracked tech debt; stale CONTRIBUTING.md.
- **Real improvements**: Break large files; track tech debt; update CONTRIBUTING.md.
- **Validators/gates**: File size check; tech debt audit.
- **Not improvement**: Creating tech debt documents without fixing anything.

## 10. Agentic Workflow Maturity (weight: low-medium for this project)

- **10/10**: Autonomous workers have health checks, state machines, evidence contracts, recovery.
- **7/10**: Workers run autonomously. Basic health monitoring. Some recovery logic.
- **5/10**: Workers exist but lack monitoring or recovery. Manual intervention needed.
- **3/10**: Workers are unreliable. No monitoring. No recovery.
- **Evidence**: Worker health check output. Recovery test. Autonomous operation proof.
- **Common weaknesses**: No worker health monitoring; no recovery; stale queue handling.
- **Real improvements**: Add worker health tests; test recovery; fix stale queue handling.
- **Validators/gates**: Worker health check gate; queue integrity test.
- **Not improvement**: Adding agent guardrails docs without testing worker behavior.

## 11. Overall Adoption Confidence (weight: composite)

- **10/10**: New user can install, configure, and run first translation in <30 minutes with docs alone.
- **7/10**: Installation works. First run possible with some guidance. Clear docs.
- **5/10**: Installation may fail. First run requires expert knowledge.
- **3/10**: Cannot install without debugging. No clear path to first use.
- **Evidence**: Fresh install test. First-run test. Setup documentation test.
- **Common weaknesses**: Broken install; missing dependencies; unclear first-run path.
- **Real improvements**: Fix install path; test setup docs; add getting-started test.
- **Validators/gates**: Install smoke test; first-run gate.
- **Not improvement**: Adding marketing-style adoption docs without fixing install.
