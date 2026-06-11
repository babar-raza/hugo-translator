# Healing Priorities (Ordered by Impact/Effort Ratio)

## Priority 1: Enable Coverage Gate + Expand CI Tests
**Effort**: LOW | **Impact**: Test Confidence +1.0, Operational Maturity +0.5
- Set `test_coverage.enabled: true` in quality_gates.yaml with threshold 50%
- Add integration tests to release_gate.yml
- Add worker unit tests to CI
- Estimated time: 2-4 hours

## Priority 2: Reduce Ruff Suppress List (Critical Rules)
**Effort**: MEDIUM | **Impact**: Code Quality +1.0, Maintainability +0.5
- Fix B904 (raise-without-from) — adds exception context, helps debugging
- Fix B023 (closure-over-loop-variable) — prevents real bugs
- Fix F841 (unused variables) — removes dead code
- Keep C901 suppressed until god-class decomposition
- Estimated time: 4-8 hours

## Priority 3: Run Mypy + Fix Critical Errors
**Effort**: MEDIUM | **Impact**: Code Quality +0.5, Maintainability +0.5, Adoption +0.5
- Run `mypy src/` and triage results
- Fix critical errors (wrong types, missing returns)
- Add mypy to pre-commit hooks
- Estimated time: 8-16 hours (depending on error count)

## Priority 4: Decompose TranslationEngine
**Effort**: HIGH | **Impact**: Architecture +2.0, Maintainability +2.0, Test Confidence +1.0
- Extract: TranslationPipeline, FileWriter, TelemetryManager, OOMRecovery, LanguageRouter
- Keep TranslationEngine as thin orchestrator
- Add integration tests before refactoring
- Estimated time: 40-80 hours

## Priority 5: Add Automated Doc Verification
**Effort**: LOW | **Impact**: Documentation +1.0, Adoption +0.5
- CI step to verify claims.yaml against code
- Doc freshness check (warn if docs untouched for 30+ days when src changed)
- README claim verification
- Estimated time: 4-8 hours

## Priority 6: Pin Dependencies
**Effort**: LOW | **Impact**: Integration Fitness +1.0
- Generate pip-compile locked requirements
- Or add upper bounds to pyproject.toml
- Estimated time: 1-2 hours

## Priority 7: Automate Worker Health Check
**Effort**: LOW | **Impact**: Agentic Workflow +1.0, Operational Maturity +0.5
- Enable scheduled cron trigger in worker_health_check.yml
- Add alerting on stale heartbeat
- Estimated time: 1-2 hours
