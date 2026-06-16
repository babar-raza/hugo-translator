# POST-SPRINT STRICT EVIDENCE AUDIT

## Title
Post-Sprint Strict Evidence Audit, Three-Level Issue Discovery, Root-Cause Review, and Next-Stage Recommendation

## Mode
**Audit mode.** Do not execute new implementation work. Do not modify source files unless writing evidence artifacts. Do not exaggerate progress. Do not describe intent as achievement. Do not treat claims as facts. Do not accept summaries without evidence. Do not skip integration and system-connect-point review.

## Mission
Provide an evidence-based summary of what was actually achieved in the last sprint, then perform a strict manual and evidence-backed review of: what was completed, what was partial, what was unresolved, what was not verified, what was not proven, what was integrated, what was supposed to be integrated but was not, and what system weaknesses allowed gaps to happen.

## Output Contract
**Schema:** `schemas/stage1-issue-model.schema.json`

**Required output files** (write to `stage1-audit/` under the run directory):
- `issues.json` — All L1/L2/L3 issues (schema-compliant)
- `audit-summary.md` — Human-readable summary (sections A, B, C below)
- `next-stage-recommendation.yaml` — Machine-readable routing directive

## Input Discovery
Locate and inspect the latest sprint evidence from all available sources:
- Final assistant response / sprint summary
- Evidence bundle / declaration-review-package
- `evidence-declaration.yaml` / `evidence-manifest.yaml`
- Changed-file manifest
- Taskcards / taskcard index / ledgers
- Queue/state files (`data/task_queue.jsonl`, `data/logs/continuation_state.json`)
- Continuation signals / run signals (`data/signals/`)
- Raw logs / command logs / test outputs / validator outputs
- Generated outputs / sample outputs
- Closeout report / pilot proof
- Current repository state (`git status`, `git log`)
- Relevant consumers and integration points

If the evidence bundle is missing: classify all dependent claims as UNVERIFIED, produce an EVIDENCE_DEFECT issue, and recommend Prompt 2 if a plan update is required.

## Section A — What We Achieved
List concrete outputs, changes, validations, and decisions completed during the sprint.

For each achievement, state:
- What changed and where
- Whether fully done or partially done
- What evidence supports it
- Whether behavior was verified
- Whether it is integrated
- Whether it is production-ready
- Whether caveats remain

Do not mix: code existence, behavior proof, integration proof, production readiness.

## Section B — What This Proves
Classify the level of proof for each conclusion:
- `implementation_only` | `partial_validation` | `focused_validation` | `integration_validation` | `end_to_end_proof` | `pilot_proof` | `no_proof_yet`

Identify: evidence-supported conclusions, unproven conclusions, carried assumptions, narrow proof, synthetic-only proof, proof lacking raw logs, proof lacking consumer/integration validation.

## Section C — Effect on Final Outcome
State whether the sprint: reduced risk, improved confidence, uncovered deeper issues, changed execution path, moved project closer to goal, exposed blockers, revealed weak machinery, requires plan hardening, requires re-execution.

Also state: what still blocks the final outcome, what remains unproven, what must happen next.

## Issue Levels

### L1 — Sprint Execution Issues
Issues in the sprint's own execution: missed tasks, partial completions, incorrect completions, unverified work, unproven claims, missing logs, weak tests, synthetic-only tests, stale artifacts, missing evidence bundles, misleading summaries, unclosed taskcards, changed files not listed, pilot claims without proof.

### L2 — Integration and Connect-Point Issues
Issues where sprint work was supposed to connect into the system: implementation not consumed, output not wired downstream, registry not updated, state file stale, docs/skills/prompts not synchronized, CI/local gate not updated, generated artifact not regenerated, downstream still uses old path, evidence exists but no consumer reads it.

### L3 — System Weakness Issues
Deeper weaknesses that allowed the sprint to fall short: no loop controller, no summary parser, no quality scorer, no reroute controller, validator too shallow, evidence contract too weak, plan allowed prose-only work, governance allowed early stop, system accepted artifact existence as proof, system required human to choose next prompt.

## Issue Record Schema
Every issue must contain all fields defined in `schemas/stage1-issue-model.schema.json`. Critical fields:
- `issue_id` (e.g., L1-001)
- `issue_level` (L1_EXECUTION, L2_INTEGRATION, L3_SYSTEM)
- `root_cause` (required — not just symptom)
- `why_not_only_symptom` (required)
- `blocker` (boolean)
- `required_fix_type`
- `recommended_next_stage`

## Claim Classification Matrix
For every major sprint claim, classify as:
- ACCEPTED_VERIFIED | ACCEPTED_WITH_LIMITATIONS | PARTIAL | UNVERIFIED | FAILED | STALE | MISLEADING | DAMAGED_OR_REGRESSED | EXTERNAL_BLOCKED

## Evidence Quality Verdicts
- STRONG | ADEQUATE_WITH_LIMITATIONS | WEAK | INSUFFICIENT | MISLEADING

## Final Verdicts
- SPRINT_ALL_GREEN_VERIFIED
- SPRINT_ACCEPTED_WITH_LIMITATIONS
- SPRINT_REQUIRES_PLAN_HARDENING
- SPRINT_REQUIRES_REEXECUTION
- SPRINT_REQUIRES_EVIDENCE_REPAIR
- SPRINT_BLOCKED_EXTERNAL
- SPRINT_SUMMARY_INSUFFICIENT

## Next-Stage Recommendation Rules
- All green + strong evidence → adversarial review then acceptance
- Issues require plan changes → Prompt 2
- Only evidence packaging missing → Prompt 3 evidence repair lane
- Execution defects remain → Prompt 2 then Prompt 3
- Sprint summary missing/insufficient → Prompt 1 rerun or evidence reconstruction
- True external blocker → blocker packaging and stop
