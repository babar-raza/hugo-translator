# POST-SPRINT STRICT EVIDENCE AUDIT
# Three-Level Issue Discovery, Root-Cause Review, and Next-Stage Recommendation
# Output contract: .supervisor/schemas/stage1-issue-model.schema.json

---

## Mode

Audit mode.
- Do not execute new implementation work.
- Do not modify source files unless the project's audit system requires writing evidence artifacts.
- Do not exaggerate progress.
- Do not describe intent as achievement.
- Do not treat claims as facts.
- Do not accept summaries without evidence.
- Do not skip integration and system-connect-point review.

## Mission

Provide an evidence-based summary of what was actually achieved in the last sprint, then perform a strict manual and evidence-backed review of:
- what was completed
- what was partial
- what was unresolved
- what was not verified
- what was not proven
- what was integrated
- what was supposed to be integrated but was not
- what system weaknesses allowed gaps to happen

## Required Input Discovery

Locate and inspect the latest sprint evidence from available sources:
- final assistant response
- sprint summary
- evidence bundle
- declaration review package
- evidence-declaration.yaml
- evidence-manifest.yaml
- changed-file manifest
- taskcards and taskcard index
- ledgers and queue/state files
- continuation signals
- raw logs and command logs
- test outputs and validator outputs
- generated outputs and sample outputs
- closeout report and pilot proof
- current repository state
- relevant consumers and integration points

If evidence bundle is missing:
- classify all dependent claims as UNVERIFIED
- produce an EVIDENCE_DEFECT issue
- recommend Prompt 2 if a plan update is required
- recommend Prompt 3 only if evidence repair can be executed safely from taskcards

---

## Section A: What We Achieved

List concrete outputs, changes, validations, and decisions completed during the sprint.

For each achievement, state:
- what changed
- where it changed
- whether fully done or partially done
- what evidence supports it
- whether behavior was verified
- whether it is integrated
- whether it is production-ready
- whether any caveats remain

Do not mix: code existence, behavior proof, integration proof, production readiness.

## Section B: What This Proves

Classify the level of proof for each conclusion:
- `implementation_only`
- `partial_validation`
- `focused_validation`
- `integration_validation`
- `end_to_end_proof`
- `pilot_proof`
- `no_proof_yet`

Identify: evidence-supported conclusions, unproven conclusions, carried assumptions, narrow proof, synthetic-only proof, missing raw logs, missing consumer/integration validation.

## Section C: Effect on Final Outcome

State whether the sprint:
- reduced risk
- improved confidence
- uncovered deeper issues
- changed the execution path
- moved materially closer to the final goal
- exposed blockers
- revealed weak system machinery
- requires plan hardening
- requires re-execution

State: what still blocks the final outcome, what remains unproven, what must happen next.

---

## Structured Issue Level L1: Sprint Execution Issues

Issues in the sprint's own execution:
- missed task, partially completed task, incorrectly completed task
- unverified work, unproven claim, missing raw log
- missing validator output, weak test, synthetic-only test
- stale artifact, missing evidence bundle, missing declaration
- misleading final summary, taskcard not closed
- taskcard closed without evidence, changed file not listed
- generated output not inspected, commit/staging state unclear
- pilot claimed but not proven, end-to-end claim without evidence
- production-ready claim without production proof

## Structured Issue Level L2: Integration and Connect-Point Issues

Where sprint work was supposed to connect into the system:
- implementation not consumed, output not wired to downstream
- registry not updated, state file stale, queue not updated
- ledgers not updated, docs not synchronized
- skill not synchronized, prompt not synchronized
- schema not synchronized, validator not synchronized
- CI/local gate not updated, generated artifact not regenerated
- downstream workflow still uses old path
- evidence exists but no consumer reads it
- taskcard exists but no executor consumes it
- new script exists but is not registered
- new rule exists but is advisory only

## Structured Issue Level L3: System Weakness Issues

Deeper weaknesses that allowed the sprint to fall short:
- autonomous supervisor did not continue
- no loop controller, no summary parser, no quality scorer
- no reroute controller, no fail-closed state
- validator too shallow, evidence contract too weak
- taskcard schema too weak, plan allowed prose-only work
- governance allowed early stop
- prompt allowed handoff instead of execution
- system did not require pilot proof
- system did not force downstream consumption check
- system accepted artifact existence as proof
- system accepted synthetic tests as production proof
- system did not block below-threshold quality
- system required human to choose next prompt
- system allowed "next prompt needed" as a final state

---

## Issue Record Format

Every issue record must contain:
- `issue_id`, `issue_level` (L1_EXECUTION, L2_INTEGRATION, L3_SYSTEM_WEAKNESS)
- `title`, `description`
- `evidence`, `missing_evidence`
- `root_cause`, `why_not_only_symptom`
- `affected_files`, `affected_components`, `affected_connection_points`
- `severity` (CRITICAL, HIGH, MEDIUM, LOW)
- `blocker` (boolean)
- `recurrence_risk` (HIGH, MEDIUM, LOW)
- `required_fix_type`
- `requires_plan_update`, `requires_taskcard`, `requires_system_healing`
- `requires_reexecution`, `requires_governance_change`, `requires_evidence_repair`
- `recommended_next_stage`
- `acceptance_impact`

---

## Claim Classification Matrix

For every major sprint claim, classify as:
- `ACCEPTED_VERIFIED`
- `ACCEPTED_WITH_LIMITATIONS`
- `PARTIAL`
- `UNVERIFIED`
- `FAILED`
- `STALE`
- `MISLEADING`
- `DAMAGED_OR_REGRESSED`
- `EXTERNAL_BLOCKED`

---

## Evidence Quality Verdicts

- `STRONG`
- `ADEQUATE_WITH_LIMITATIONS`
- `WEAK`
- `INSUFFICIENT`
- `MISLEADING`

## Final Verdicts

- `SPRINT_ALL_GREEN_VERIFIED`
- `SPRINT_ACCEPTED_WITH_LIMITATIONS`
- `SPRINT_REQUIRES_PLAN_HARDENING`
- `SPRINT_REQUIRES_REEXECUTION`
- `SPRINT_REQUIRES_EVIDENCE_REPAIR`
- `SPRINT_BLOCKED_EXTERNAL`
- `SPRINT_SUMMARY_INSUFFICIENT`

## Next-Stage Recommendation Rules

- All green + strong evidence: recommend adversarial review then acceptance
- Issues require plan changes: recommend Prompt 2
- Only evidence packaging missing, no plan changes needed: recommend Prompt 3 evidence repair lane
- Execution defects remain: recommend Prompt 2 then Prompt 3
- Sprint summary missing/insufficient: recommend Prompt 1 rerun or evidence reconstruction
- True external blocker: recommend blocker packaging and stop

---

## Required Outputs

All outputs must conform to `.supervisor/schemas/stage1-issue-model.schema.json`.

Files to produce:
- `stage1-sprint-audit-summary.md`
- `stage1-achievement-proof-summary.md`
- `stage1-final-outcome-impact.md`
- `stage1-l1-execution-issues.yaml`
- `stage1-l2-integration-issues.yaml`
- `stage1-l3-system-weaknesses.yaml`
- `stage1-root-cause-map.md`
- `stage1-claim-classification-matrix.csv`
- `stage1-evidence-quality-verdict.md`
- `stage1-next-stage-recommendation.yaml`
- `stage1-issue-model.json` (machine-readable, schema-conformant)
