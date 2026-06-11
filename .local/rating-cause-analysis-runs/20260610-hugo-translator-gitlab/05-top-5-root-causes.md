# Top 5 Root Causes of Low Project Rating

## 1. God-Class TranslationEngine (RCA-001, RCA-008)
**Impact**: Architecture -2.5, Maintainability -3.0, Test Confidence -1.5
**Summary**: engine.py is 5,613 lines with a 1,417-line method. This single file concentrates 15+ responsibilities that should be separate modules. It is the primary structural bottleneck preventing testability, maintainability, and onboarding.
**Fix effort**: HIGH (requires careful decomposition into ~6 focused modules with integration tests protecting the refactor)

## 2. Exception Swallowing at Scale (RCA-002)
**Impact**: Code Quality -2.0, Operational Maturity -1.5, Functional Clarity -1.0
**Summary**: 689 `except Exception` blocks across the codebase convert errors into log warnings. This provides false stability — the system appears to work but silently produces wrong results. Production debugging requires reading thousands of log lines.
**Fix effort**: MEDIUM (audit each block; categorize as: legitimate graceful degradation vs. bug-hiding; fix the latter)

## 3. Test Coverage Gate Disabled + CI Subset (RCA-004, RCA-005)
**Impact**: Test Confidence -2.0, Operational Maturity -1.5
**Summary**: Coverage enforcement is explicitly disabled. CI runs ~200 out of ~1,500 tests. Workers, TM, benchmarking, and observability tests never run in CI. Full regression requires 9-minute local gate script that developers may skip.
**Fix effort**: LOW-MEDIUM (enable coverage gate at 60%, expand CI test scope incrementally)

## 4. 26 Suppressed Lint Rules Including C901 (RCA-003)
**Impact**: Code Quality -1.5, Maintainability -1.0
**Summary**: Suppressing C901 (complexity) means the linter can never flag methods like the 1,417-line translate_file(). Other suppressions hide real bugs (B023: closure bugs, B904: lost exception context). The suppression list is self-reinforcing — each new suppression reduces the value of linting.
**Fix effort**: MEDIUM (address rules in priority order: B904, B023, F841, then C901)

## 5. Documentation Is Aspirational, Not Verified (RCA-009, RCA-007)
**Impact**: Documentation Trustworthiness -1.5, Adoption Confidence -1.0
**Summary**: 123 doc files and detailed mypy/claims configs create an impression of maturity. But mypy has never been run, claims are not CI-verified, and docs were batch-generated on the same day as the last src commit. A new developer will encounter the gap between what docs promise and what the code delivers.
**Fix effort**: LOW-MEDIUM (add claims-verification CI step, run mypy and fix critical errors, add doc freshness check)
