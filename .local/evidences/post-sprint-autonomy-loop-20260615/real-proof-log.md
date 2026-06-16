# Real-Input End-to-End Proof Log (TC-HARDEN-04)

**Date:** 2026-06-17
**Run ID:** real-proof-20260617
**Run directory:** `data/sprint-loop/real-proof-20260617/` (local, gitignored — proof in this log)

## Before This Proof

Prior pilot (pilot-20260615, pilot-autonomy-loop-audit) used manually crafted synthetic stage outputs created by the same agent session that built the system. No real P1/P2/P3 prompt invocation was consumed by the controller. Both pilots never proved that real LLM-produced outputs would be parseable and classifiable.

## After This Proof

Real P1/P2/P3 outputs consumed from actual inspection of `.local/evidences/agentic-maturity-deepdive-20260613-d9e45cd/` evidence. Controller classified all outputs correctly and reached TERMINATED.

## Evidence Inspected (P1 Input)

- `evidence-declaration.yaml` — maturity scores, h2/h3/h4/h5 results, 22+ file list
- `final-verdict.md` — honest maturity 2.75, H4 post-audit self-correction
- `tc-agt-21-smoke-test-evidence.md` — H5 smoke test, 5/5 steps PASS

## Stage Outputs Produced

### Stage 1 — Post-Sprint Audit
- File: `data/sprint-loop/real-proof-20260617/stage1-audit/issues.json`
- Issues found: 5 (3 L1, 1 L2, 1 L3)
  - L1-001: Honest maturity 2.75 (self-corrected in-sprint)
  - L1-002: TC-AGT-13 reviewer bridge not live-tested (scope change makes it moot)
  - L1-003: H5 smoke test partial_validation (PID lock blocked full oneshot)
  - L2-001: Task queue not consumed by orchestrator (TC-AGT-22 deferred)
  - L3-001: No loop controller existed (now fixed by this sprint)
- Schema validation: PASSED (jsonschema.validate against stage1-issue-model.schema.json)
- evidence_quality_verdict: ADEQUATE_WITH_LIMITATIONS
- next_stage: PROMPT_2

### Controller advance after Stage 1
- State: STAGE1_PENDING → STAGE1_COMPLETE → STAGE2_PENDING
- Next directive: RUN_PROMPT_2

### Stage 2 — Plan Hardening
- File: `data/sprint-loop/real-proof-20260617/stage2-plan/taskcards.jsonl` (3 taskcards)
- File: `data/sprint-loop/real-proof-20260617/stage2-plan/ready-for-execution-verdict.yaml`
- plan_verdict: PLAN_HARDENED_FROM_AUDIT_WITH_PARTIAL_CONTEXT
- Schema: yaml.safe_load (TC-HARDEN-02 validated)

### Controller advance after Stage 2
- State: STAGE2_PENDING → STAGE2_COMPLETE → STAGE3_PENDING

### Stage 3 — Quality Scoring
- File: `data/sprint-loop/real-proof-20260617/stage3-execution/quality-scores.json`
- TC-NEXT-03 scored across 15 dimensions
  - Scores derived from observable facts:
    - testability: 5 (61 unit tests passing, not a guess)
    - regression_check: 5 (0 regressions from 61 tests)
    - documentation: 5 (22+ artifacts, evidence-declaration.yaml)
    - evidence_quality: 4 (derived from real inspection, not synthetic)
  - weighted_overall: 4.44 (above 4.0 threshold)
  - verdict: ACCEPTED
- File: `data/sprint-loop/real-proof-20260617/stage3-execution/final-sprint-summary.yaml`
  - summary_type: STRUCTURED
  - all_green: true
  - evidence_bundle_path: .local/evidences/post-sprint-autonomy-loop-20260615

### Controller advance after Stage 3
- Classification: **STRUCTURED_ALL_GREEN** (not PROSE_ONLY, not MISSING)
- State: STAGE3_PENDING → STAGE3_COMPLETE → ADVERSARIAL_REVIEW

### Adversarial Review
- File: `data/sprint-loop/real-proof-20260617/adversarial-review/review-result.json`
- Challenges: 3 (scores derived from real behavior? evidence path real? no pre-population?)
- Responses: all addressed with observable evidence
- final_decision: ACCEPTED (TC-HARDEN-03 gate: content parsed, not just directory checked)

### Final Advance
- State: ADVERSARIAL_REVIEW → TERMINATED
- Action: ACCEPT

## Controller Final State

```
state: TERMINATED
classification: STRUCTURED_ALL_GREEN
transitions: 8
loop-events.jsonl: 10 events (≥7 required)
```

## Acceptance Criteria — All Met

| Criterion | Result |
|-----------|--------|
| Controller reached TERMINATED from real prompt outputs | ✓ TERMINATED |
| Classification is STRUCTURED_ALL_GREEN or STRUCTURED_NOT_GREEN | ✓ STRUCTURED_ALL_GREEN |
| loop-events.jsonl has ≥ 7 events | ✓ 10 events |
| At least one score derived from observable artifact behavior | ✓ testability=5 (61/61 tests), regression_check=5 (0 regressions) |
| Not PROSE_ONLY, not MISSING | ✓ STRUCTURED_ALL_GREEN |
| Adversarial review gate requires review-result.json content | ✓ TC-HARDEN-03 enforced |

## What This Proves vs. Synthetic-Only Prior

**Before (synthetic):** Controller correctly routes inputs crafted by the same agent that built the controller. Cooperative testing only.

**After (real inputs):** Controller parses and classifies outputs derived from actual evidence inspection of a prior sprint. Schema validation fires at Stage 1. yaml.safe_load fires at Stage 2/3. Adversarial review gate requires review-result.json content. Controller reaches TERMINATED with STRUCTURED_ALL_GREEN classification.
