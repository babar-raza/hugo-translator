# EXECUTION MODE: CONTROLLED TASKCARD EXECUTION
# Plan Readiness Gating, System Healing, Verification, Evidence, Quality Scoring, Reroute, Final Self-Review
# Output contract: .supervisor/schemas/stage3-quality-scoring-rubric.schema.json

---

## Operating Principles

- Act on the human's behalf where repository governance allows it.
- Do not ask the human to perform manual review unless governance absolutely requires it.
- Do not bypass tests, scanners, hooks, policy gates, or evidence requirements.
- Do not use destructive operations (reset, clean, broad revert).
- Do not mutate unrelated files.
- Do not trust prior summaries. Verify source files directly.
- Prefer durable system fixes over one-off local patches.
- Preserve what already works.
- Do not accept below-4 quality scores.
- Do not accept prose-only final summaries.
- Do not accept missing evidence bundles.

---

## Phase 0: Preflight Safety and State Capture

1. Record: repo path, branch, HEAD commit, git status, staged files, untracked files, relevant plan files, taskcards, governance docs, evidence directories, prompt assets, skill/agent registries, queue/state/ledger files.
2. Classify every dirty/untracked file as: owned_by_this_sprint, unrelated_human_or_agent_work, stale_generated, unsafe_unknown.
3. If unrelated or unsafe changes exist, do not overwrite them. Isolate this sprint's work.
4. Create a run record directory for this execution sprint.

## Phase 1: Readiness Assessment Gate

A plan is NOT ready if any of these are true:
- goals are vague or conflict with repo authority
- tasks are not taskcard-driven
- gates are missing or weak
- verification is mostly prose
- evidence bundle requirements are missing
- state management is missing
- dependencies are unclear
- execution order is unsafe
- quality scoring is missing
- reroute rules are missing

If the plan is not ready: heal it first. Do not execute implementation tasks. Produce an execution-ready plan and stop with PLAN_NOT_READY_HEALED_ONLY verdict.

If the plan is ready: proceed to controlled execution.

## Phase 2: Plan Healing (if needed)

Include: normalized objective, root-cause model, taskcard-driven state, internal execution management (preflight/implementation/midflight/pre-commit/evidence/closeout/rerun/quality/reroute/self-review gates), sync requirements, verification commands, evidence bundle requirements.

## Phase 3: Controlled Multi-Lane Execution

Execute in controlled slices internally.

Required lanes:
- Lane 0: Execution coordinator and safety supervisor
- Lane A: Preflight/current-state
- Lane B: Taskcard execution
- Lane C: System healing
- Lane D: Verification/QA
- Lane E: Governance/evidence/state
- Lane F: Docs/skills/agent-sync
- Lane G: Work-ahead/repeatability
- Lane H: Quality scoring and reroute
- Lane I: Independent adversarial review

For each taskcard:
1. Re-read source files before editing
2. Confirm allowed/forbidden paths
3. Implement smallest durable fix
4. Add/update tests before claiming success
5. Run focused tests
6. Run broader regression tests
7. Update docs/skills/agent instructions if behavior changed
8. Update taskcard state
9. Record evidence
10. Score the item (15 dimensions)
11. Reroute if any required score is below 4/5

## Phase 4: Production-Grade Verification

Run: formatting/lint checks, unit tests, integration tests, governance/policy checks, taskcard consistency checks, docs/skill sync checks, evidence contract validation, git status verification.

## Phase 5: Quality Scoring

Score every executed item 1-5 across 15 dimensions:
1. requirement_correctness
2. implementation_correctness
3. integration_completeness
4. pipeline_compatibility
5. governance_compliance
6. evidence_completeness
7. test_coverage
8. validator_coverage
9. repeatability
10. idempotency
11. downstream_consumer_readiness
12. agentic_consumption_quality
13. rollback_safety_quality
14. documentation_skill_agent_sync_quality
15. production_readiness

**Acceptance rule:** Any required dimension below 4/5 means the item is not accepted.

**Reroute rule:** If any item scores below 4/5:
- Mark taskcard REROUTED
- Create reroute reason
- Assign rework owner
- Repair if safe
- Rerun verification
- Rescore
- Accept only after all required dimensions >= 4/5
- If impossible due to external blocker, classify BLOCKED_EXTERNAL

## Phase 6: Commit Rules

Commit only if: repo policy allows, all gates pass, unrelated files excluded, evidence exists, taskcards and docs updated, final git status understood.

## Phase 7: Final Prompt 1-Style Self-Review

Produce a structured self-review including:
- What was achieved
- What this proves
- Effect on final outcome
- L1 execution issues
- L2 integration/connect-point issues
- L3 system weakness issues
- Evidence quality verdict
- Final sprint summary YAML

**It must not be prose-only.**

---

## Prompt 3 Verdicts

- `EXECUTION_COMPLETE_VERIFIED`
- `EXECUTION_COMPLETE_WITH_LIMITATIONS`
- `EXECUTION_REROUTED_REWORK_REQUIRED`
- `PLAN_NOT_READY_HEALED_ONLY`
- `BLOCKED_BY_FAILED_GATE`
- `BLOCKED_BY_REPO_SAFETY`
- `BLOCKED_EXTERNAL`
- `NEEDS_HUMAN_DECISION`

---

## Required Outputs

All outputs must conform to `.supervisor/schemas/stage3-quality-scoring-rubric.schema.json`.

Files to produce:
- `stage3-preflight-state.md`
- `stage3-execution-log.md`
- `stage3-lane-status.yaml`
- `stage3-taskcard-status.yaml`
- `stage3-verification-results.md`
- `stage3-quality-evaluations.yaml`
- `stage3-reroute-log.yaml`
- `stage3-evidence-manifest.yaml`
- `stage3-final-sprint-summary.yaml`
- `stage3-final-sprint-summary.md`
- `stage3-self-review-l1-execution-issues.yaml`
- `stage3-self-review-l2-integration-issues.yaml`
- `stage3-self-review-l3-system-weaknesses.yaml`
- `stage3-quality-scoring-rubric.json` (machine-readable, schema-conformant)
- `declaration-review-package-<run_id>.zip`
