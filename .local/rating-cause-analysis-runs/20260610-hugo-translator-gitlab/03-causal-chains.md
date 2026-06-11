# Causal Chain Analysis

## Primary Causal Chain: The God-Class Trap

```
Rapid feature development
  → All logic added to TranslationEngine (path of least resistance)
    → engine.py grows to 5,613 lines, 57 methods
      → translate_file() alone is 1,417 lines
        → Can't test individual phases in isolation
          → Coverage gate disabled (too hard to cover)
            → Regressions hide in untested paths
              → Exception swallowing masks failures
                → Bugs found only via manual log inspection
                  → Low operational maturity
                    → Low adoption confidence
```

## Secondary Causal Chain: The Lint Suppression Spiral

```
Initial codebase has some lint violations
  → Developer adds ruff to pyproject.toml
    → Too many violations to fix at once
      → 26 rules suppressed as "tech debt"
        → C901 (complexity) suppressed!
          → Complex methods never flagged
            → translate_file grows unchecked
              → More lint issues accumulate
                → Suppression list grows
                  → Actual bugs hide in noise
```

## Tertiary Causal Chain: The CI Coverage Gap

```
CI runs only critical-path tests (~200 out of ~1,500)
  → Worker tests, TM tests, benchmarking tests never run in CI
    → Regressions in these subsystems go unnoticed
      → Manual testing burden increases
        → Workers run on single machine (Windows Task Scheduler)
          → No distributed coordination
            → Worker health check is manual-only
              → Operational maturity ceiling
```

## Quaternary Causal Chain: The Documentation Mirage

```
Docs generated in batch (123 files)
  → Claims are comprehensive and well-structured
    → No CI verification of claims
      → Code evolves, docs stay
        → Docs become aspirational
          → New contributor reads docs, hits reality gap
            → Trust erosion → adoption friction
```
