# JSON Schema Reference

This page documents the six JSON schemas in the `schemas/` directory. These schemas define output contracts for the post-sprint autonomy loop governance system (`scripts/ops/sprint_loop_controller.py`) and related infrastructure.

**Audience:** System Contributors, Governance Operators
**Last Updated:** 2026-06-17

---

## Overview

The schemas enforce structured outputs across the three-stage sprint governance loop:

```
Stage 1: Post-Sprint Audit  → stage1-issue-model.schema.json
Stage 2: Plan Hardening     → stage2-taskcard-contract.schema.json
Stage 3: Quality Scoring    → stage3-quality-score.schema.json
Loop State Machine          → loop-decision-state.schema.json
Adversarial Review Gate     → adversarial-review-result.schema.json
Evidence Sidecars           → evidence-declaration.schema.json
```

All schemas are consumed by `scripts/ops/sprint_loop_controller.py` and validated against agent outputs before stage transitions.

---

## Schema Catalog

### 1. `stage1-issue-model.schema.json`

**Purpose:** Output contract for Stage 1 (post-sprint audit). Captures issues found during a strict sprint audit.

**Used by:** Sprint loop controller at STAGE1_COMPLETE transition

**Required fields:**
| Field | Type | Description |
|-------|------|-------------|
| `issues` | array | All issues found during audit |
| `claim_classifications` | object | Classification of claims (verified/reported/projected) |
| `evidence_quality_verdict` | string | Overall evidence quality rating |
| `next_stage_recommendation` | string | Recommended next stage action |

**Issue structure (each item in `issues` array):**
| Field | Type | Description |
|-------|------|-------------|
| `issue_id` | string | Unique ID (e.g. `L1-001`, `L2-003`) |
| `issue_level` | string | `L1_EXECUTION`, `L2_INTEGRATION`, or `L3_SYSTEM` |
| `title` | string | Short issue title |
| `description` | string | Detailed description |
| `severity` | string | Impact severity |
| `blocker` | boolean | Whether this blocks stage progression |

**Optional top-level fields:** `run_id`, `sprint_id`, `date`, `structured_all_green`

---

### 2. `stage2-taskcard-contract.schema.json`

**Purpose:** Output contract for Stage 2 (plan hardening). Each taskcard represents one actionable unit of work generated from Stage 1 audit issues.

**Used by:** Sprint loop controller at STAGE2_COMPLETE transition

**Required fields:**
| Field | Type | Description |
|-------|------|-------------|
| `taskcards` | array | List of taskcard objects |
| `plan_verdict` | string | One of the plan verdict enumerations (see below) |

**Taskcard structure (each item in `taskcards` array):**
| Field | Type | Description |
|-------|------|-------------|
| `taskcard_id` | string | Unique ID (e.g. `TC-LOOP-01`) |
| `title` | string | Short taskcard title |
| `source_issue_id` | string | Stage 1 `issue_id` this taskcard addresses |
| `current_status` | string | Current state in taskcard lifecycle |
| `required_verification` | array | Verification commands or steps |
| `acceptance_criteria` | array | Criteria for closure |

**Taskcard status values:** `PROPOSED`, `READY`, `BLOCKED`, `IN_PROGRESS`, `IMPLEMENTED`, `VERIFIED`, `SCORED`, `REROUTED`, `REWORKING`, `REWORKED`, `ACCEPTED`, `ACCEPTED_WITH_LIMITATIONS`, `BLOCKED_EXTERNAL`, `DEFERRED_WITH_REASON`

**Priority values:** `P0`, `P1`, `P2`, `P3`

**Plan verdict values:**
- `PLAN_HARDENED_FROM_AUDIT_READY_FOR_EXECUTION`
- `PLAN_HARDENED_FROM_AUDIT_WITH_PARTIAL_CONTEXT`
- `PLAN_NOT_READY_AUDIT_PLAN_MISMATCH`
- `PLAN_NOT_READY_MISSING_ACTIVE_PLAN`
- `PLAN_NOT_READY_MISSING_AUDIT_SUMMARY`
- `BLOCKED_EXTERNAL`

**Optional fields:** `run_id`, `source_audit_run_id`, `verification_matrix`, `execution_dag`, `anti_overclaim_rules`

---

### 3. `stage3-quality-score.schema.json`

**Purpose:** Output contract for Stage 3 (controlled execution quality scoring). Captures per-taskcard quality evaluations across 15 dimensions.

**Used by:** Sprint loop controller at STAGE3_COMPLETE transition; `scripts/ops/sprint_quality_scorer.py`

**Required fields:**
| Field | Type | Description |
|-------|------|-------------|
| `evaluations` | array | Per-taskcard quality evaluations |

**Evaluation structure:**
| Field | Type | Description |
|-------|------|-------------|
| `taskcard_id` | string | Taskcard being scored |
| `dimension_scores` | object | Score (1-5) per dimension |
| `weighted_overall` | number | Weighted composite score (1-5) |
| `verdict` | string | `ACCEPT`, `REROUTE`, or `DEFER` |

**Scoring dimensions (from `config/sprint_quality_rubric.yaml`):**

*5 base dimensions:*
- `correctness` — implementation correctness
- `completeness` — all required work done
- `production_ready` — safe for production
- `documentation` — docs, examples, clarity
- `test_coverage` — tests validate behavior

*10 sprint-specific dimensions (configurable per sprint)*

**Reroute rule:** If any required dimension scores below 4/5, the taskcard is automatically rerouted to `REWORK_PENDING`.

**Optional fields:** `run_id`, `rubric_path`, `final_sprint_summary` (loaded separately from `final-sprint-summary.yaml`)

---

### 4. `loop-decision-state.schema.json`

**Purpose:** State machine schema for the sprint loop controller. Tracks which stage the loop is in and what decision was made at each transition.

**Used by:** `scripts/ops/sprint_loop_controller.py` at every state transition

**Required fields:**
| Field | Type | Description |
|-------|------|-------------|
| `run_id` | string | Unique loop run identifier |
| `current_state` | string | Current state machine state |

**State machine states:**
```
IDLE
  → STAGE1_PENDING
  → STAGE1_COMPLETE
  → STAGE2_PENDING
  → STAGE2_COMPLETE
  → STAGE3_PENDING
  → STAGE3_COMPLETE
  → REWORK_PENDING
  → ADVERSARIAL_REVIEW
  → TERMINATED
```

**Optional fields:** `sprint_id`, `cycle_count`, `transitions` (history log), `last_classification`, `last_directive`

---

### 5. `adversarial-review-result.schema.json`

**Purpose:** Gate file required before `ADVERSARIAL_REVIEW` transitions to `TERMINATED` (accept) or back to `REWORK_PENDING` (reroute). Ensures a structured adversarial challenge is recorded before sprint closure.

**Used by:** Sprint loop controller at `ADVERSARIAL_REVIEW` state; gate path: `adversarial-review/review-result.json`

**Required fields:**
| Field | Type | Description |
|-------|------|-------------|
| `review_date` | string | ISO-8601 date of the review |
| `challenges` | array | List of challenges raised by adversarial reviewer |
| `final_decision` | string | `ACCEPTED` or `REROUTED` |
| `reason` | string | Human-readable rationale for the decision |

**Decision semantics:**
- `ACCEPTED` → loop controller transitions to `TERMINATED` (sprint complete)
- `REROUTED` → loop controller returns to `REWORK_PENDING` (repair required)

---

### 6. `evidence-declaration.schema.json`

**Purpose:** Schema for evidence sidecar files (`evidence-declaration.yaml`). Captures run metadata, inspected artifacts, findings, and final verdict for any sprint or investigation run.

**Used by:** `src/observability/evidence_declaration.py` (Pydantic model); `.local/evidences/*/evidence-declaration.yaml`

**Required fields:**
| Field | Type | Description |
|-------|------|-------------|
| `run_id` | string | Unique run identifier |
| `repo_path` | string | Absolute path to repository root |

**Key optional fields:**
| Field | Type | Description |
|-------|------|-------------|
| `date` | string | Run date (YYYY-MM-DD) |
| `branch` | string | Git branch (default: "main") |
| `base_commit` | string | Git HEAD SHA at run start |
| `files_inspected` | object | Category → list of inspected file paths |
| `final_verdict` | string | Overall run verdict (default: "PENDING") |
| `autonomy_gaps_found` | integer | Count of autonomy gaps identified |
| `opportunities_identified` | integer | Count of improvement opportunities |
| `risks_identified` | integer | Count of risks identified |
| `taskcards_proposed` | integer | Count of taskcards proposed |
| `commands_inspected` | array | CLI commands that were inspected |
| `workflows_inspected` | array | Workflows that were inspected |

**Evidence sidecar location:** `.local/evidences/<sprint-name>/evidence-declaration.yaml`

---

## Related Documentation

- [Governance Prompts](../governance/prompts/prompt-loop-controller.md) — Sprint loop controller prompt and state machine logic
- [Quality Scoring Rubric](../../config/sprint_quality_rubric.yaml) — 15-dimension scoring weights
- [Evidence Declaration Source](../../src/observability/evidence_declaration.py) — Pydantic implementation
- [Loop Controller Source](../../scripts/ops/sprint_loop_controller.py) — State machine implementation
