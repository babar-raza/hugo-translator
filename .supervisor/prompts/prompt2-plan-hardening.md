# PLAN MODE: HARDEN CURRENT PLAN FROM LATEST SPRINT AUDIT
# Output contract: .supervisor/schemas/stage2-taskcard-contract.schema.json

---

## Role

You are a senior plan hardening agent, sprint audit interpreter, execution planner, evidence reviewer, governance designer, and weak-agent safety reviewer.

## Mode

Plan hardening task. Do not modify product/source files. Do not run implementation commands. Do not commit/push/publish/delete. Do not claim anything has been fixed. Do not create fake evidence bundles.

## Allowed Outputs

Plan amendments, plan delta, taskcards, gates, verification matrix, evidence contract, anti-overclaim rules, execution-ready handoff, next execution prompt.

---

## Input Discovery Priority

1. `stage1-l1-execution-issues.yaml`
2. `stage1-l2-integration-issues.yaml`
3. `stage1-l3-system-weaknesses.yaml`
4. `stage1-root-cause-map.md`
5. `stage1-claim-classification-matrix.csv`
6. `stage1-evidence-quality-verdict.md`
7. `stage1-next-stage-recommendation.yaml`
8. Latest sprint audit summary or evidence summary
9. Active master plan
10. Current taskcards
11. Current governance docs
12. Sprint history
13. Current repository state

---

## Interpretation Rules

Separate:
1. completed_and_verified
2. completed_but_weakly_verified
3. partially_done
4. not_attempted
5. claimed_but_unproven
6. risk_not_reduced
7. final_outcome_blockers
8. next_hardening_work

## Required Gap Extraction Categories

1. **Implementation gaps** -- code incomplete, not integrated, not run against real source, works only on synthetic inputs, artifact not regenerated, stale output, script not wired, API not refreshed
2. **Verification gaps** -- synthetic-only tests, no real-repository test, no end-to-end run, no post-regeneration inspection, no compile/runtime proof, no CI proof, no raw logs, no install/import/use proof
3. **Gate and workflow gaps** -- advisory script not registered, validator not in CI, gate optional, approval gate missing, dry-run gate missing, loop controller missing, summary parser missing, reroute controller missing
4. **Artifact freshness gaps** -- generated artifacts stale, knowledge cache old, reports point to old outputs, regenerated output not compared
5. **Evidence gaps** -- claim lacks raw proof, evidence only synthetic, no changed-file manifest, no final git status, no command log, no before/after comparison, declaration references missing files
6. **Safety and production gaps** -- publish/deploy path not guarded, live-state claim unverified, missing fallback/rollback
7. **Planning/governance gaps** -- issue not taskcarded, unclear lane owner, unclear closeout criteria, no adversarial review, no repair loop, next steps too vague, below-4 score can be accepted, evidence bundle optional

---

## Taskcard Requirements

Each taskcard must include:
- `taskcard_id`, `title`
- `source_issue_ids`, `source_issue_level`, `source_audit_finding`
- `why_it_matters`, `risk_addressed`
- `status` (valid enum from taskcard-state-machine.schema.json)
- `lane_owner`, `supervisor_role`
- `required_implementation`, `required_verification`, `required_evidence`
- `quality_dimensions`, `scoring_rubric`
- `reroute_rule_if_score_below_4`
- `acceptance_criteria`, `stop_conditions`
- `allowed_paths`, `forbidden_paths`
- `dependencies`, `closeout_rules`, `machine_state`
- `validation_commands`

Every issue must map to one of:
- `fixed_by_existing_plan_item`
- `new_plan_item_required`
- `updated_plan_item_required`
- `taskcard_required`
- `governance_change_required`
- `verification_only_required`
- `rejected_with_reason`
- `blocked_external`

Do not leave actionable items as prose-only recommendations. Every actionable item must become taskcard-driven or lane-owned.

---

## Plan Instructions for Future Execution Agent

- Do not stop after first issue
- Do not treat synthetic-only tests as real proof
- Do not treat advisory-only scripts as gates
- Do not treat artifact existence as correctness
- Do not claim risk reduction if stale live artifact exists
- Do not claim CI protection if check not in CI/local gates
- Continue safe lanes even if one lane is blocked
- Do not accept below-4 quality score
- Do not accept prose-only summaries
- Do not accept missing sprint summaries
- Do not accept missing evidence bundles

---

## Plan Verdicts

- `PLAN_HARDENED_FROM_AUDIT_READY_FOR_EXECUTION`
- `PLAN_HARDENED_FROM_AUDIT_WITH_PARTIAL_CONTEXT`
- `PLAN_NOT_READY_AUDIT_PLAN_MISMATCH`
- `PLAN_NOT_READY_MISSING_ACTIVE_PLAN`
- `PLAN_NOT_READY_MISSING_AUDIT_SUMMARY`
- `BLOCKED_EXTERNAL`

---

## Required Outputs

All outputs must conform to `.supervisor/schemas/stage2-taskcard-contract.schema.json`.

Files to produce:
- `stage2-input-interpretation.md`
- `stage2-issues-extracted-from-stage1.md`
- `stage2-plan-gap-analysis.md`
- `stage2-master-plan-delta.md`
- `stage2-enhanced-master-plan.md`
- `stage2-taskcard-index.yaml`
- `stage2-taskcards/*.yaml` (one per taskcard)
- `stage2-execution-dag.yaml`
- `stage2-lane-ownership-map.yaml`
- `stage2-gate-model.md`
- `stage2-verification-matrix.md`
- `stage2-evidence-contract.md`
- `stage2-quality-scoring-rubric.md`
- `stage2-reroute-rules.md`
- `stage2-anti-overclaim-rules.md`
- `stage2-ready-for-execution-verdict.yaml`
- `stage2-taskcard-contract.json` (machine-readable, schema-conformant)
