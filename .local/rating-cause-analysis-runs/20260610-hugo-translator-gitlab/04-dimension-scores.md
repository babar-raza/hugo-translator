# Current Dimension Scores (Post-Healing Sprint)

| # | Dimension | Score | Key Depressors |
|---|-----------|-------|----------------|
| 1 | Functional Clarity | 8.0 | Shortcode validator was silently broken (fixed in sprint) |
| 2 | Architecture Quality | 6.5 | God-class engine.py, CLI mega-module, no clear layer boundaries |
| 3 | Code Quality | 7.0 | 689 except-Exception blocks, 26 suppressed ruff rules, C901 ignored |
| 4 | Operational Maturity | 7.0 | CI runs <15% of tests, coverage gate disabled, worker health manual-only |
| 5 | Test Confidence | 7.0 | 472 test files but no coverage enforcement, main method untestable, 3 e2e tests |
| 6 | Documentation Trustworthiness | 7.0 | 123 docs but batch-generated, claims unverified, no freshness enforcement |
| 7 | Security/Safety | 8.0 | No shell=True, detect-private-key hook, PII sanitization tests. Minor: unsanitized subprocess args |
| 8 | Integration Fitness | 7.0 | Unbounded dep versions, sentence-transformers already hit deprecation |
| 9 | Maintainability | 6.0 | 5,613-line file, 1,417-line method, mypy never run, no onboarding test suite |
| 10 | Agentic Workflow Maturity | 7.0 | Good docs (AGENTS.md, guardrails), but enforcement is convention-only |
| 11 | Adoption Confidence | 6.5 | Would a new team trust this? Docs look great, but engine.py is daunting |
| | **Composite** | **6.91** | |

## Composite Calculation
Weighted average: (8.0 + 6.5 + 7.0 + 7.0 + 7.0 + 7.0 + 8.0 + 7.0 + 6.0 + 7.0 + 6.5) / 11 = 6.91
