# Autonomous Green Loop — Audit Contract
Version: 1.0 | System: autonomous-green-loop

---

## Definition of GREEN_STOP

The loop may emit `next_action: GREEN_STOP` in `loop-signal.yaml` ONLY when ALL
of the following are simultaneously true:

1. `loop-signal.yaml.next_action` is being set to `GREEN_STOP` (this is the
   determination being made — not circular: the prior iteration's signal must
   show no blocking gaps)
2. All entries in `taskcard-registry.yaml` have `status: CLOSED`
   (no OPEN, IN_PROGRESS, or BLOCKED taskcards remain)
3. At least one complete EXECUTE → AUDIT cycle has been run
   (`loop-state.yaml.iteration >= 1`)
4. `python scripts/quality/validate_autonomous_loop.py` exits 0
5. The audit report for the current iteration has zero BLOCKING_GAP findings

If ANY condition is false, `next_action` must be `EXPAND` (or `BLOCKED_EXTERNAL`
if a genuine external blocker exists).

---

## Finding Classifications

Every finding from the audit stage must be classified as exactly one of:

| Classification | Meaning |
|----------------|---------|
| `ACCEPTED` | Complete, verified, no further action needed |
| `PARTIAL` | Implemented but not fully verified or integrated |
| `FAILED` | Attempted but did not achieve the goal |
| `UNVERIFIED` | Claimed complete but no verifiable evidence |
| `STALE` | Previously accepted but now out of date or invalidated |
| `MISLEADING` | Summary or claim overstates what was actually done |
| `DUPLICATE` | Same finding already captured in a prior audit iteration |
| `OUT_OF_SCOPE` | Outside the bound plan's scope (must be noted, not taskcarded) |
| `EXTERNAL_BLOCKER` | Cannot proceed without external authority or resource |
| `NON_BLOCKING_WARN` | Issue worth noting but does not block GREEN |
| `BLOCKING_GAP` | Must be resolved before GREEN_STOP is permitted |

---

## BLOCKING_GAP Handling

Every `BLOCKING_GAP` finding:
- Must be recorded in `audit-report-iter<N>.md` with: finding description, affected
  file or component, root cause, evidence that it is not resolved
- Must cause `loop-signal.yaml.blocking_gaps` to increment by 1
- Must result in `loop-signal.yaml.next_action: EXPAND` (not GREEN_STOP)
- Must become a new taskcard in `taskcard-registry.yaml` during EXPAND stage

BLOCKING_GAP findings from a prior iteration that are re-found in a subsequent
audit: duplicate fingerprinting applies. Verify the taskcard intended to fix it
is actually CLOSED before treating it as re-opened.

---

## Proof Required for ACCEPTED Classification

A finding may only be classified as ACCEPTED if at least one of the following
is true:
- A file was created or modified AND tests pass that cover the change
- A command was run AND its output is recorded in a handoff YAML
- A validator script exits 0 AND that exit code is recorded
- A manual check was performed AND the exact check and result are written

"The task was done" without evidence = `UNVERIFIED`, not `ACCEPTED`.

---

## Self-Audit Limitation

**This is a structural limitation that cannot be fully eliminated in this version.**

The agent that executes the plan also runs the audit. This creates a conflict of
interest: the agent may be more lenient toward its own work, may miss
consequences it did not consider, or may classify `UNVERIFIED` as `ACCEPTED`
due to familiarity with what it intended.

**Current mitigation:**
- `sprint-audit.md` explicitly instructs the agent to "Act as an independent
  sprint evidence reviewer"
- The agent is required to read the actual files and test outputs, not rely on
  its memory of what it did
- Any claim without a concrete file/test artifact must be classified `UNVERIFIED`

**Recommended human review gate:**
Before accepting GREEN_STOP on any plan with production consequences, a human
should review `audit-report-iter<N>.md` and confirm the ACCEPTED classifications
are supported by the cited evidence.

**Future improvement:**
A second agent session (with no memory of the execution session) running the
audit stage would eliminate the authority conflict. This is not implemented in
this version.

---

## Audit Report Required Structure

`audit-report-iter<N>.md` must contain:
1. **What was executed** — list of taskcards attempted, with status
2. **Evidence reviewed** — specific files, test outputs, validator results read
3. **Findings** — each classified using the table above
4. **Blocking gaps count** — explicit integer
5. **Audit verdict** — one of sprint-audit.md's final verdicts
6. **Self-audit caveat** — acknowledgment of the authority limitation

---

## What the Audit Stage Must NOT Do

- Accept a claim as ACCEPTED based on the agent's memory alone
- Classify a gap as DUPLICATE without checking the prior iteration's registry
- Classify an external-facing behavior as ACCEPTED without runtime evidence
- Classify BLOCKING_GAP as NON_BLOCKING_WARN to avoid another iteration
- Write GREEN_STOP when any taskcard in the registry is not CLOSED
