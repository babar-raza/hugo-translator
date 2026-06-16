# CONTROLLED TASKCARD EXECUTION

## Title
Execution Mode — Controlled Taskcard Execution, Plan Readiness Gating, System Healing, Verification, Evidence, Quality Scoring, Reroute, and Final Self-Review

## Mode
**Execution mode.** Execute the approved plan only if it is genuinely ready for safe execution. If the plan is not ready, heal it first, then stop with an execution-ready handoff.

## Core Rule
Do not blindly execute prose. First convert the plan into a controlled, taskcard-driven, gate-managed execution system.

## Output Contract
**Schema:** `schemas/stage3-quality-score.schema.json`

**Required output files** (write to `stage3-execution/` under the run directory):
- `quality-scores.json` — Per-taskcard quality evaluations (schema-compliant)
- `taskcard-status.yaml` — Final status of all taskcards
- `execution-log.md` — Human-readable execution narrative
- `final-sprint-summary.yaml` — Structured sprint summary (MUST be structured, not prose)
- `self-review-issues.json` — Prompt 1-style self-review issues

## Operating Principles
- Act on the human's behalf where repository governance allows it
- Do not bypass tests, scanners, hooks, policy gates, or evidence requirements
- Do not use destructive operations (reset, clean, broad revert)
- Do not mutate unrelated files
- Do not trust prior summaries — verify directly
- Prefer durable system fixes over one-off patches
- Do not accept below-4 quality scores
- Do not accept prose-only final summaries
- Do not accept missing evidence bundles

## Phase 0 — Preflight
1. Record: repo path, branch, HEAD commit, git status, staged/untracked files, relevant plan/taskcard/governance/evidence files
2. Classify every dirty/untracked file as: owned_by_this_sprint, unrelated_work, stale_generated, unsafe_unknown
3. If unrelated/unsafe changes exist, isolate this sprint's work
4. Create run record directory

## Phase 1 — Readiness Gate
A plan is NOT ready if: goals are vague, tasks are not taskcard-driven, gates are missing, verification is prose, evidence requirements missing, state management missing, rollback rules missing, dependencies unclear, quality scoring missing, reroute rules missing.

**If not ready:** Heal the plan (add taskcards, gates, verification commands, evidence requirements, scoring, reroute rules). Stop after producing execution-ready handoff. Set `summary_type: STRUCTURED`, verdict: `PLAN_NOT_READY_HEALED_ONLY`.

**If ready:** Proceed to execution.

## Phase 2 — Plan Healing (if needed)
Produce a normalized, execution-ready plan with:
1. Normalized objective (problem, importance, non-regression, out-of-scope)
2. Root-cause model
3. Taskcard-driven state (one taskcard per actionable unit)
4. Internal execution management (preflight, implementation, midflight, pre-commit, evidence, closeout, quality, reroute gates)
5. Sync requirements (skills, docs, governance, registry)
6. Verification (exact commands, expected results, failure handling)
7. Evidence (bundle with run record, git status, changed files, test logs, scores, verdict)

## Phase 3 — Controlled Execution
Execute in controlled slices. For each taskcard:
1. Re-read source files before editing
2. Confirm allowed/forbidden paths
3. Implement the smallest durable fix
4. Add/update tests before claiming success
5. Run focused tests
6. Run broader regression tests
7. Update docs/skills if behavior changed
8. Update taskcard state
9. Record evidence
10. Score the item (see Phase 5)
11. Reroute if any required score < 4/5

Do not continue past a failed gate unless the failure is understood, the fix is within scope, the fix is recorded, and tests are rerun.

## Phase 4 — Verification
Before closeout, run: lint/format checks, unit tests for touched modules, integration tests for changed workflows, governance/policy checks, taskcard consistency checks, evidence contract validation, git status verification.

## Phase 5 — Quality Scoring
**Rubric:** `config/sprint_quality_rubric.yaml`

Score every executed item 1-5 across 15 dimensions:
- **Base (60%):** correctness, completeness, production_ready, documentation, testability
- **Sprint (40%):** evidence_quality, claim_verification, root_cause_depth, taskcard_precision, dependency_mapping, rollback_safety, pilot_proof, regression_check, contract_compliance, governance_adherence

**Acceptance:** Overall >= 4.0, no dimension < 3.0, critical dimensions >= 4.0.

**Reroute:** Any required dimension < 4/5 → mark REROUTED, create rework reason, repair, rerun, rescore. Accept only after all dimensions pass. If impossible due to external blocker, classify BLOCKED_EXTERNAL.

## Phase 6 — Commit Rules
Commit only if: repo policy allows, all gates pass, unrelated files excluded, evidence exists, taskcards/docs updated, git status understood.

Commit message format: `<type>(<scope>): <short durable summary>`

## Phase 7 — Final Self-Review
Produce a structured self-review in the Prompt 1 pattern:
- What was achieved
- What this proves
- Effect on final outcome
- L1 execution issues (write to `self-review-issues.json`)
- L2 integration issues
- L3 system weakness issues
- Evidence quality verdict

The final sprint summary MUST be structured (not prose-only). Write to `final-sprint-summary.yaml` with all fields from the schema.

## Execution Verdicts
- EXECUTION_COMPLETE_VERIFIED
- EXECUTION_COMPLETE_WITH_LIMITATIONS
- EXECUTION_REROUTED_REWORK_REQUIRED
- PLAN_NOT_READY_HEALED_ONLY
- BLOCKED_BY_FAILED_GATE
- BLOCKED_BY_REPO_SAFETY
- BLOCKED_EXTERNAL
- NEEDS_HUMAN_DECISION
