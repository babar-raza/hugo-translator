# Evidence Map: Finding → File → Metric

| Finding | Primary Evidence File(s) | Key Metric |
|---------|--------------------------|------------|
| RCA-001: God-class | src/translation_engine/engine.py | 5,613 lines, 57 methods |
| RCA-002: Exception swallowing | 125 src/ files | 689 `except Exception` blocks |
| RCA-003: Lint suppression | pyproject.toml:118-144 | 26 suppressed rules |
| RCA-004: Coverage disabled | config/quality_gates.yaml | `enabled: false` |
| RCA-005: CI subset | .github/workflows/release_gate.yml | ~200/1,500 tests run |
| RCA-006: CLI mega-module | src/cli.py | 3,137 lines |
| RCA-007: No mypy run | (absence of .mypy_cache) | 0 runs despite config |
| RCA-008: 1,417-line method | engine.py:1354-2770 | Single method |
| RCA-009: Aspirational docs | docs/ (123 files), config/claims.yaml | Batch-generated same day |
| RCA-010: Convention governance | AGENTS.md, AGENT_GUARDRAILS.md | Manual-only health check |
| RCA-011: Incomplete pre-commit | .pre-commit-config.yaml | No mypy, no tests |
| RCA-012: Subprocess safety | 17 files, 0 shell=True | Low risk |
| RCA-013: Unbounded deps | pyproject.toml:26-43 | All use >= only |
