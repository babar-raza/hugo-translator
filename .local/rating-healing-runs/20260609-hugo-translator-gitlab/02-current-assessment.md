# Phase 2 - Current State Assessment

## A. Project Identity and Workflow Truth

- **Purpose**: Automated translation system for Hugo static sites (multi-site, multi-language)
- **Entrypoints**: `translate-hugo` CLI, `python -m src`, orchestrator, autonomous workers
- **Workflows**: CLI-driven translation, orchestrator-managed batch processing, autonomous content workers
- **Generated outputs**: Translated Hugo markdown files, TM databases, metrics, benchmark reports
- **Deployment model**: Docker containers, Windows native workers, orchestrator-based
- **Tests**: pytest with phased unit tests, contract tests, integration tests, regression tests
- **CI**: GitHub Actions (cli_tests, release_gate, telemetry_health_check, worker_health_check, content_structure_scan)
- **Governance**: AGENTS.md, CONTRIBUTING.md

## B. Source and Behavior Assessment

### Strengths
- Well-structured modular codebase (238 source files)
- Strong validation engine with 11 configurable validators
- 3-layer Translation Memory (L1/L2/L3) with contract tests
- Comprehensive CLI with lazy-loaded heavy dependencies
- Feature flags system
- Structured logging (structlog)
- Quality gates script with configurable thresholds

### Weaknesses Found
1. **ShortcodePreservationValidator regex bug**: The regex `_SHORTCODE_RE` uses `[<%]` which only matches `<` and `%` delimiters. Hugo comment shortcodes `{{/* */}}` use `/` as the first char after `{{`, so they are NOT matched. This is a functional bug.
2. **ShortcodePreservationValidator API mismatch**: The validator was rewritten to use `_extract_structured()` returning `ParsedShortcode` objects, but the old `_extract_shortcodes()` method was removed. Tests still reference the old method.
3. **Extra shortcodes treated as ERROR**: The validator marks unexpected extra shortcodes as ERROR. Tests expect WARNING (which is more appropriate - extra shortcodes are suspicious but not critical). This means valid translations with minor shortcode additions are rejected unnecessarily.
4. **29 ruff lint violations in src/**: All auto-fixable (import sorting, unused imports, style). Ruff is not installed in venv.
5. **36 ruff lint violations in tests/**: All auto-fixable.
6. **FutureWarning in TM L3**: `get_sentence_embedding_dimension` deprecated, should use `get_embedding_dimension`.
7. **Dev dependencies not in venv**: ruff, pytest, black, mypy not installed in .venv (had to install manually)

## C. Tests and Validation Assessment

### Test Results (verified)
- **Phase-0 unit tests**: 6/6 passed
- **Phase-1 + TM unit tests**: 63/63 passed
- **Translation engine unit tests**: 645/645 passed (4 skipped)
- **Validation unit tests**: 436/461 passed, **25 FAILED** (all in test_shortcode_preservation_validator.py)
- **Contract tests**: 298/298 passed
- **Total tested**: 1448 passed, 25 failed, 4 skipped

### Test Confidence Issues
1. **25 failing tests**: All in shortcode preservation validator. Tests test real behavior but call a removed API method and have expectation mismatches vs current implementation.
2. **No coverage reporting configured in CI**: pyproject.toml has --cov flags but coverage gate is disabled in quality_gates.yaml.
3. **Dev tools not in venv**: CI installs from requirements/dev.txt but local venv doesn't have dev deps.

## D. Docs and Claim Trust

### Strengths
- README accurately describes core features (validation, TM, CLI)
- Extensive docs/ directory with architecture, deployment, guides
- CONTRIBUTING.md exists
- CHANGELOG.md exists

### Weaknesses
- README claims all 10 validators work - the shortcode preservation validator has a regex bug that misses comment shortcodes
- quality_gates.yaml references docs/VERIFICATION_WORKFLOW.md - not verified if it exists
- Many scripts in scripts/ (200+) - unclear which are current vs stale

## E. Production/Release Safety

- Docker-based deployment with Dockerfiles
- No PyPI publish workflow (good - avoids accidental releases)
- Worker deployment scripts exist but not tested in CI
- Orchestrator has health monitoring and restart logic

## F. Agentic Workflow Maturity

- AGENTS.md provides guardrails
- Autonomous workers exist (content, verification, TM)
- Orchestrator manages worker lifecycle
- No explicit taskcard state machine
- Worker health checks exist as CI workflows

## Summary of Rating-Critical Issues

| # | Issue | Impact | Fixable |
|---|-------|--------|---------|
| 1 | 25 shortcode validator tests failing | Test Confidence -2 | Yes - source + test fix |
| 2 | Shortcode regex misses comment shortcodes | Functional Clarity -1 | Yes - regex fix |
| 3 | Extra shortcodes as ERROR not WARNING | Functional Clarity -0.5 | Yes - source fix |
| 4 | 65 auto-fixable ruff violations | Code Quality -0.5 | Yes - ruff --fix |
| 5 | FutureWarning in L3 TM | Code Quality -0.5 | Yes - rename method |
| 6 | No local quality gate script runner | Operational Maturity -0.5 | Yes - add script |
| 7 | Dev deps missing from venv setup docs | Documentation Trust -0.5 | Yes - clarify |
