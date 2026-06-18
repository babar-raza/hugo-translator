# Sprint Loop Governance

📋 Reported: Content verified against `scripts/ops/sprint_loop_controller.py` source. Runtime behavior should be independently verified before enabling in production.

**Audience:** System Contributors, Governance Operators  
**Last Updated:** 2026-06-17  
**Status:** 📋 Reported (code-verified, not runtime-verified)

---

## Overview

The post-sprint autonomy loop is a 10-state machine that governs structured sprint execution. It parses stage outputs, classifies summaries, and determines the next stage automatically — eliminating the need for manual prompt selection between stages.

**Default safety posture:**
- `enabled: false` in `config/global.yaml`
- `dry_run: true` — decisions are logged but not executed
- All state persisted in a run directory for auditability

---

## Controller

**Script:** `scripts/ops/sprint_loop_controller.py`

**Usage:**
```bash
# Inspect current state (dry-run)
python scripts/ops/sprint_loop_controller.py --run-dir <path> --dry-run

# Advance to next stage
python scripts/ops/sprint_loop_controller.py --run-dir <path> --advance

# Force a specific stage
python scripts/ops/sprint_loop_controller.py --run-dir <path> --force-stage 1
```

**State files:**
| File | Content |
|------|---------|
| `<run-dir>/loop-state.json` | Current state machine state |
| `<run-dir>/loop-events.jsonl` | Event log (one JSON per line) |
| `<run-dir>/next-directive.json` | Next action to execute |

---

## State Machine

```
IDLE
  → STAGE1_PENDING   (post-sprint audit triggered)
  → STAGE1_COMPLETE  (audit output validated)
  → STAGE2_PENDING   (plan hardening triggered)
  → STAGE2_COMPLETE  (hardened plan validated)
  → STAGE3_PENDING   (controlled execution triggered)
  → STAGE3_COMPLETE  (quality scoring done)
  → ADVERSARIAL_REVIEW  (adversarial gate required)
  → TERMINATED       (sprint accepted or blocked)
  → REWORK_PENDING   (repair required; loops back to S1/S2/S3)
```

**Valid transitions:**

| From | To (allowed) |
|------|-------------|
| IDLE | STAGE1_PENDING |
| STAGE1_PENDING | STAGE1_COMPLETE |
| STAGE1_COMPLETE | STAGE2_PENDING |
| STAGE2_PENDING | STAGE2_COMPLETE |
| STAGE2_COMPLETE | STAGE3_PENDING |
| STAGE3_PENDING | STAGE3_COMPLETE |
| STAGE3_COMPLETE | REWORK_PENDING, ADVERSARIAL_REVIEW, TERMINATED |
| REWORK_PENDING | STAGE1_PENDING, STAGE2_PENDING, STAGE3_PENDING |
| ADVERSARIAL_REVIEW | TERMINATED, REWORK_PENDING |

---

## Stage 3 Classifications

After Stage 3 execution, the controller classifies the quality score output into one of 9 values:

| Classification | Meaning | Next State |
|---------------|---------|-----------|
| `STRUCTURED_ALL_GREEN` | All taskcards ACCEPTED, no blockers | ADVERSARIAL_REVIEW |
| `STRUCTURED_NOT_GREEN` | Some taskcards REROUTED or BLOCKED | REWORK_PENDING |
| `MISSING` | No quality score output found | STAGE3_PENDING (retry) |
| `PROSE_ONLY` | Output exists but not machine-parseable | STAGE3_PENDING (retry) |
| `EVIDENCE_MISSING` | Score exists but evidence bundle absent | REWORK_PENDING |
| `SCORES_MISSING` | Score file exists but no evaluations | REWORK_PENDING |
| `TASKCARDS_INCOMPLETE` | Some taskcards not scored | REWORK_PENDING |
| `CONTRADICTORY` | Score and summary disagree | REWORK_PENDING |
| `BLOCKED_EXTERNAL` | True external blocker recorded | TERMINATED |

---

## Adversarial Review Gate

Before a sprint is accepted as complete, a structured adversarial review is required. The controller reads `adversarial-review/review-result.json` (validated against `schemas/adversarial-review-result.schema.json`).

**Decision semantics:**
- `ACCEPTED` → transitions to `TERMINATED` (sprint complete)
- `REROUTED` → returns to `REWORK_PENDING` (repair required)

---

## Output Schemas

Each stage requires machine-readable output validated against a JSON schema before state transition. See [JSON Schemas Reference](../reference/schemas.md) for all 6 schemas.

| Stage | Schema |
|-------|--------|
| Stage 1 output | `schemas/stage1-issue-model.schema.json` |
| Stage 2 output | `schemas/stage2-taskcard-contract.schema.json` |
| Stage 3 output | `schemas/stage3-quality-score.schema.json` |
| Loop state | `schemas/loop-decision-state.schema.json` |
| Adversarial gate | `schemas/adversarial-review-result.schema.json` |
| Evidence sidecar | `schemas/evidence-declaration.schema.json` |

---

## Quality Scorer

**Script:** `scripts/ops/sprint_quality_scorer.py`

Evaluates taskcard work across 15 dimensions (5 base + 10 sprint-specific):

*Base dimensions:* correctness, completeness, production_ready, documentation, test_coverage  
*Sprint-specific dimensions:* configurable in `config/sprint_quality_rubric.yaml`

**Reroute rule:** Any required dimension below 4/5 triggers automatic reroute to `REWORK_PENDING`.

---

## Related Documentation

- [JSON Schemas Reference](../reference/schemas.md) — Schema definitions for all stage outputs
- [Governance Prompts](prompts/prompt-loop-controller.md) — Prompt template for the controller
- [Evidence Declaration](../../src/observability/evidence_declaration.py) — Evidence sidecar source
- [Local Data Policy](local-data-policy.md) — Retention policy for evidence files in `.local/`
