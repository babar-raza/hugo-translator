# Autonomous Green Loop — Idempotency Contract
Version: 1.0 | System: autonomous-green-loop

---

## Purpose

This contract defines how the loop behaves when re-run against a plan or
run directory that already has partial or complete state. Every re-invocation
must be safe: it must not duplicate completed work, corrupt existing state,
or produce different results from identical input.

---

## Rerun Detection

At startup, the loop checks for an existing run directory for the current plan:

```
.local/autonomous-loop/runs/<RUN_ID>/loop-signal.yaml
```

If this file exists:
- Read `next_action`
- If `next_action == GREEN_STOP`: **do not re-execute**. Print the status and stop.
  The plan has already reached green. Treat this as a no-op invocation.
- If `next_action == EXPAND` or state is `AUDIT_COMPLETE`: resume from the
  correct stage (see Session Recovery in `loop-runbook.md`)
- If `next_action == BLOCKED_EXTERNAL`: print the blocker and stop.
  Human must resolve before resuming.

If `loop-signal.yaml` does not exist, this is a new run. Proceed normally.

---

## Accepted-Work Preservation

Taskcards with `status: CLOSED` in `taskcard-registry.yaml` are NEVER re-opened,
regardless of:
- A new audit finding that touches the same file
- A new iteration
- A new session
- Manual edits to the plan file

The only exception: if a `STALE` or `MISLEADING` classification in the audit
explicitly revokes a prior ACCEPTED finding and creates a new BLOCKING_GAP
finding for the same task, that new finding becomes a NEW taskcard (with a new
ID and `opened_iteration` > original) rather than re-opening the closed one.

Rationale: Re-opening closed taskcards breaks the trust contract between the
execution agent and the loop. If prior work is wrong, say so explicitly with
a new task — do not silently undo previous iterations.

---

## Duplicate Finding Prevention

When the expansion stage adds new taskcards from audit findings:
1. Compute a fingerprint for each finding: `MD5(finding_title + "::" + affected_file)`
2. Check all existing entries in `taskcard-registry.yaml`
3. If a taskcard with the same fingerprint already exists:
   - If its status is OPEN or IN_PROGRESS: skip (it is already tracked)
   - If its status is CLOSED: this is a regression. Create a new taskcard with
     a `regression_of` field pointing to the original taskcard ID.
4. Only create new entries for findings with no matching fingerprint.

---

## Run ID Uniqueness

Run IDs are date-based: `autonomous-green-loop-YYYYMMDD`

If a run already exists for that date, append a letter suffix:
- `autonomous-green-loop-20260618`
- `autonomous-green-loop-20260618-b`
- `autonomous-green-loop-20260618-c`

Never reuse an existing run ID. Never overwrite an existing run directory.

---

## Evidence Append-Only Rule

Within a single run:
- Files in the run directory are NEVER deleted or overwritten
- Per-iteration files use the iteration number as suffix:
  `audit-report-iter1.md`, `audit-report-iter2.md`, etc.
- The registry (`taskcard-registry.yaml`) is updated in-place but only by
  appending new entries or updating status fields
- `loop-signal.yaml` is overwritten (it represents the CURRENT signal, not
  history) — the full history is in `loop-state.yaml.transitions`

---

## Maximum Iterations (prevents infinite loops)

Default: 5 iterations

If `iterations_remaining <= 0` when the loop would expand again:
1. Write `incomplete-loop-report.md` with all OPEN tasks and unresolved findings
2. Set `loop-signal.yaml.next_action: MAX_ITER_REACHED`
3. Stop

The loop MUST NOT expand beyond 5 iterations autonomously. If more iterations
are genuinely needed, a human must:
1. Read `incomplete-loop-report.md`
2. Decide whether to increase `max_iterations` in `loop-state.yaml`
3. Manually restart from the appropriate state

This limit prevents runaway loops from low-quality plans or stuck blockers.

---

## Plan File Mutation

The expand stage modifies the plan file to add new taskcards. This mutation is:
- **Additive only** — new sections or taskcards are appended
- **Non-destructive** — existing plan content is not removed or reordered
- **Reversible** — the plan file state at each iteration start is snapshotable
  from the taskcard-registry.yaml + expansion-delta files

The original plan file content must remain intact. Expansion adds to it.

---

## Idempotency of the Validator

`python scripts/quality/validate_autonomous_loop.py` is a read-only check.
Running it multiple times must produce identical results for identical input files.
It must not modify any file. It must not depend on external state (network, time).

---

## What NOT to Do on Rerun

- Do not re-run stages that already have completed handoff YAML files
- Do not re-initialize `taskcard-registry.yaml` if it already exists
- Do not write a new `loop-state.yaml` if one exists with a valid current_state
- Do not re-generate a RUN_ID that matches an existing run directory
- Do not interpret an empty loop-signal.yaml as "green" (verify the file contents)
