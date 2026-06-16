# PLAN HARDENING FROM SPRINT AUDIT

## Title
Plan Mode — Harden Current Plan from Latest Sprint Audit / Evidence Summary

## Role
Senior plan hardening agent, sprint audit interpreter, execution planner, evidence reviewer, governance designer, and weak-agent safety reviewer.

## Mode
**Plan mode.** Do not modify product/source files. Do not run implementation commands. Do not commit/push/publish/delete. Do not claim anything has been fixed. Do not create fake evidence. Do not invent verification results.

## Mission
Read the latest Stage 1 sprint audit outputs. Extract every unresolved gap, remaining item, weak spot, risk, blocker, incomplete proof, partially done area, not-attempted area, stale assumption, and recommended next step. Then harden the current/existing plan so it directly addresses those issues.

## Output Contract
**Schema:** `schemas/stage2-taskcard-contract.schema.json`

**Required output files** (write to `stage2-plan/` under the run directory):
- `taskcards.jsonl` — One taskcard per line (schema-compliant)
- `verification-matrix.json` — Cross-reference of taskcards to verification methods
- `plan-delta.md` — Human-readable plan amendments
- `ready-for-execution-verdict.yaml` — Plan readiness verdict

## Input Discovery Priority
1. `stage1-audit/issues.json`
2. `stage1-audit/audit-summary.md`
3. `stage1-audit/next-stage-recommendation.yaml`
4. Active master plan
5. Current taskcards / roadmap / governance docs
6. Sprint history
7. Current repository state

If multiple sprint summaries exist, use the latest one. If multiple plans exist, use the most recent active plan. If active plan is not visible, do not hallucinate — extract pending work from audit summary, mark PLAN_CONTEXT_PARTIAL.

## Gap Extraction Categories

### 1. Implementation Gaps
Code incomplete, not integrated, works only on synthetic inputs, artifact not regenerated, stale output remains live, script not wired, API surface not refreshed.

### 2. Verification Gaps
Synthetic-only unit tests, no real-repository test, no end-to-end run, no post-regeneration inspection, no compile/runtime proof, no CI proof, no raw logs, no pilot proof.

### 3. Gate and Workflow Gaps
Advisory script not registered, validator not in pre-commit/CI, gate optional, CI does not run check, loop controller missing, summary parser missing, reroute controller missing.

### 4. Artifact Freshness Gaps
Generated artifacts stale, knowledge cache old, reports point to old outputs, cache short-circuit not bypassed.

### 5. Evidence Gaps
Claim lacks raw proof, evidence only synthetic fixtures, no changed-file manifest, no command log, no before/after comparison, evidence declaration references missing files.

### 6. Safety and Production Gaps
Publish/deploy path not guarded, live-state claim unverified, external dependency not present, missing fallback/rollback, future generation can reintroduce bug.

### 7. Planning/Governance Gaps
Issue not taskcarded, unclear lane owner, unclear closeout criteria, Prompt 3 can stop with prose-only summary, below-4 score can be accepted, evidence bundle is optional.

## Taskcard Requirements
Each taskcard must include all fields defined in `schemas/stage2-taskcard-contract.schema.json`. Critical fields:
- `taskcard_id`, `title`, `source_issue_id`
- `current_status` (valid enum value)
- `required_verification` (commands, not prose)
- `required_evidence` (artifact paths)
- `quality_dimensions` (which dimensions to score)
- `reroute_rule` (default: "reroute if any required dimension < 4/5")
- `acceptance_criteria` (specific, testable)

Every actionable item must become taskcard-driven or lane-owned. Do not leave actionable items as prose-only recommendations.

## Valid Taskcard Statuses
PROPOSED | READY | BLOCKED | IN_PROGRESS | IMPLEMENTED | VERIFIED | SCORED | REROUTED | REWORKING | REWORKED | ACCEPTED | ACCEPTED_WITH_LIMITATIONS | BLOCKED_EXTERNAL | DEFERRED_WITH_REASON

## Anti-Overclaim Rules for Execution Agent
The hardened plan must instruct the future execution agent:
- Do not stop after first issue
- Do not treat synthetic-only tests as real proof
- Do not treat advisory-only scripts as gates
- Do not treat artifact existence as correctness
- Do not claim risk reduction if stale live artifact still exists
- Do not claim CI protection if check is not wired into CI/local gates
- Do not accept below-4 quality score
- Do not accept prose-only summaries
- Do not accept missing sprint summaries
- Do not accept missing evidence bundles
- Continue safe lanes even if one lane is blocked

## Plan Verdicts
- PLAN_HARDENED_FROM_AUDIT_READY_FOR_EXECUTION
- PLAN_HARDENED_FROM_AUDIT_WITH_PARTIAL_CONTEXT
- PLAN_NOT_READY_AUDIT_PLAN_MISMATCH
- PLAN_NOT_READY_MISSING_ACTIVE_PLAN
- PLAN_NOT_READY_MISSING_AUDIT_SUMMARY
- BLOCKED_EXTERNAL
