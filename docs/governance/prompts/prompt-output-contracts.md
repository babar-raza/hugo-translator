# Prompt Output Contracts

This document specifies the required outputs for each stage of the post-sprint autonomy loop. All structured outputs must conform to their JSON schemas in `schemas/`.

## Stage 1 — Post-Sprint Audit

**Schema:** `schemas/stage1-issue-model.schema.json`

**Required files in `stage1-audit/`:**

| File | Format | Description |
|------|--------|-------------|
| `issues.json` | JSON (schema-compliant) | All L1/L2/L3 issues with root causes |
| `claim-classification.json` | JSON (embedded in issues.json) | Claim matrix |
| `audit-summary.md` | Markdown | Human-readable achievement/proof/impact summary |
| `next-stage-recommendation.yaml` | YAML | Machine-readable next-stage directive |

**Rejection criteria:**
- Any issue without `root_cause` field
- Any claim without `proof_level` classification
- Missing `evidence_quality_verdict`
- Missing `next_stage_recommendation`

## Stage 2 — Plan Hardening

**Schema:** `schemas/stage2-taskcard-contract.schema.json`

**Required files in `stage2-plan/`:**

| File | Format | Description |
|------|--------|-------------|
| `taskcards.jsonl` | JSONL | One taskcard per line (task_queue.py compatible) |
| `verification-matrix.json` | JSON | Cross-reference of taskcards to verification methods |
| `plan-delta.md` | Markdown | Human-readable plan amendments |
| `ready-for-execution-verdict.yaml` | YAML | Plan readiness verdict |

**Rejection criteria:**
- Any actionable issue from Stage 1 without a corresponding taskcard
- Taskcards with prose-only recommendations (no verification commands)
- Missing `plan_verdict`
- Taskcards without `acceptance_criteria`

## Stage 3 — Controlled Execution

**Schema:** `schemas/stage3-quality-score.schema.json`

**Required files in `stage3-execution/`:**

| File | Format | Description |
|------|--------|-------------|
| `quality-scores.json` | JSON (schema-compliant) | Per-taskcard quality evaluations |
| `taskcard-status.yaml` | YAML | Final status of all taskcards |
| `execution-log.md` | Markdown | Human-readable execution narrative |
| `final-sprint-summary.yaml` | YAML | Structured sprint summary |
| `self-review-issues.json` | JSON | Prompt 1-style self-review issues |

**Rejection criteria:**
- `summary_type` = "PROSE_ONLY" or "MISSING"
- Any taskcard executed but not scored
- Any rerouted item marked accepted without re-evaluation
- Missing `evidence_bundle_path`
- `all_green: true` with non-empty `open_issues` (CONTRADICTORY)

## Loop Controller

**Schema:** `schemas/loop-decision-state.schema.json`

**Required files in run root:**

| File | Format | Description |
|------|--------|-------------|
| `loop-state.json` | JSON (schema-compliant) | Current state machine state |
| `loop-events.jsonl` | JSONL | Decision event log |
| `next-directive.json` | JSON | What the agent should do next |

## Summary Classification Rules

The loop controller classifies Stage 3 output as:

| Classification | Condition | Next Action |
|---------------|-----------|-------------|
| STRUCTURED_ALL_GREEN | `all_green: true`, no blockers, no rerouted items | ADVERSARIAL_REVIEW |
| STRUCTURED_NOT_GREEN | Structured but open issues remain | Feed issues to PROMPT_2 |
| PROSE_ONLY | `summary_type: PROSE_ONLY` | PROMPT_2 then PROMPT_3 |
| MISSING | No `final-sprint-summary.yaml` found | PROMPT_1 then PROMPT_2 then PROMPT_3 |
| CONTRADICTORY | `all_green: true` but reroute_log non-empty | Acceptance blocked |
| EVIDENCE_MISSING | `evidence_bundle_path` is null | Evidence repair lane |
| SCORES_MISSING | Taskcards without quality scores | Quality scoring lane |
| TASKCARDS_INCOMPLETE | Taskcards in non-terminal status | PROMPT_2 |
| BLOCKED_EXTERNAL | True external blocker verified | Package blocker, stop |

## Quality Scoring Thresholds

- **Overall minimum:** 4.0 (weighted across all dimensions)
- **Dimension minimum:** 3.0 (no dimension may score below this)
- **Critical dimensions:** correctness >= 4.0, completeness >= 4.0
- **Reroute trigger:** Any required dimension < 4/5
- **Rubric:** `config/sprint_quality_rubric.yaml`

## System Accuracy Rules

This system is **advisory only**. The loop controller writes `next-directive.json`
but does NOT invoke prompts or execute stages. A Claude agent or human operator reads
the directive and manually runs the indicated prompt.

**Required terminology** (use only these terms when describing this system):
- advisory routing
- machine-emitted directive
- directive-driven routing
- decision-advisory loop
- routing recommendation

**Prohibited terminology** (these misrepresent what the system does):
- autonomous
- self-executing
- auto-invokes
- runs itself

Any output, plan, summary, commit message, or evidence file that uses prohibited
terminology must be corrected before the session closes.
