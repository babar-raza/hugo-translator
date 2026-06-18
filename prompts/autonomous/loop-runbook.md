# Autonomous Green Loop — Operator Runbook
Version: 1.0 | System: autonomous-green-loop

---

## Overview

The autonomous green loop runs any Claude plan file through the stages:
HARDEN → EXECUTE → AUDIT → [EXPAND → EXECUTE]* → GREEN

It runs within a single agent session but produces persistent state files that
enable session recovery if context is exhausted. The loop stops at GREEN_STOP,
a genuine external blocker, or after 5 iterations.

---

## Starting a New Loop Run

### Step 1 — Identify the plan file

The plan file is a `.md` file in `C:\Users\prora\.claude\plans\` created by
Claude in plan mode. It must contain:
- A problem or scope description
- At least one taskcard or actionable item

Example: `C:\Users\prora\.claude\plans\golden-yawning-crown.md`

### Step 2 — Invoke the loop

In a new Claude session, provide this exact instruction:

```
Read prompts/autonomous/autonomous-green-loop.md.
Then read the plan at <ABSOLUTE_PATH_TO_PLAN>.
Execute the autonomous green loop.
```

The agent will:
1. Generate a RUN_ID: `autonomous-green-loop-YYYYMMDD`
2. Create the run directory: `.local/autonomous-loop/runs/<RUN_ID>/`
3. Initialize `loop-state.yaml` and `taskcard-registry.yaml`
4. Execute the full loop

### Step 3 — Monitor progress

During execution, the agent writes state files continuously. Check status:

```bash
python scripts/ops/autonomous_loop_status.py \
  --run-dir .local/autonomous-loop/runs/<RUN_ID>
```

Exit 0 = GREEN_STOP reached. Exit 1 = in progress or needs attention.

---

## Run ID Convention

Format: `autonomous-green-loop-YYYYMMDD`

If multiple runs happen on the same date, append a suffix:
- `autonomous-green-loop-20260618`
- `autonomous-green-loop-20260618-b`

Never reuse a run ID. Each run gets its own directory. Previous runs are never
overwritten.

---

## Run Directory Layout

```
.local/autonomous-loop/runs/<RUN_ID>/
  loop-state.yaml              Current state + iteration + transition log
  loop-signal.yaml             Machine-readable next action (written by AUDIT)
  taskcard-registry.yaml       All taskcards + statuses across all iterations
  gap-register.md              Output of HARDEN stage (iteration 1 only)
  stage-1-harden-handoff.yaml  Compact HARDEN stage completion signal
  changed-files-iter1.txt      Files modified in execution iteration 1
  stage-1-execute-handoff.yaml Compact EXECUTE iteration 1 completion signal
  audit-report-iter1.md        Full audit output for iteration 1
  stage-1-audit-handoff.yaml   Compact AUDIT iteration 1 completion signal
  expansion-delta-iter1.md     Plan expansion from iteration 1 audit (if needed)
  stage-1-expand-handoff.yaml  Compact EXPAND iteration 1 completion signal
  changed-files-iter2.txt      Files modified in execution iteration 2
  ...
  incomplete-loop-report.md    Written only if MAX_ITER_REACHED
```

---

## Resuming After Context Exhaustion

If the agent's context fills up mid-run:

1. Check current state:
```bash
python scripts/ops/autonomous_loop_status.py \
  --run-dir .local/autonomous-loop/runs/<RUN_ID>
```

2. Read the printed "To resume" instruction. It will say something like:
```
State: AUDIT_COMPLETE (iteration 2/5) — next_action: EXPAND
To resume: Read prompts/autonomous/autonomous-green-loop.md.
  Then read the plan at <PATH>.
  The run directory .local/autonomous-loop/runs/<RUN_ID>/ already has
  loop-signal.yaml with next_action: EXPAND. The loop will resume from EXPANDING.
```

3. Start a new agent session with that instruction.

The new session reads `loop-signal.yaml` and `taskcard-registry.yaml` from the
existing run dir and continues from where the previous session left off.
Completed taskcards (status: CLOSED) are not re-run.

---

## Handling BLOCKED_EXTERNAL

If the loop writes `loop-signal.yaml` with `next_action: BLOCKED_EXTERNAL`:

1. Read `loop-signal.yaml.blocker_description` for the specific blocker
2. Resolve the blocker (provide credential, make decision, etc.)
3. Edit `loop-signal.yaml`: change `next_action` to `EXPAND` or `GREEN_STOP`
   as appropriate after resolving the blocker
4. Resume the loop using the resume procedure above

---

## Forcing a Specific Iteration

To force the loop to start at a specific iteration (e.g., iteration 3) without
re-running iterations 1 and 2, the run directory must already contain:
- All taskcards for iterations 1 and 2 in `taskcard-registry.yaml` with correct statuses
- `loop-state.yaml` with `iteration: 3` and `current_state: HARDENED`

Then resume normally.

---

## Resetting a Failed Run

To start fresh from a failed or corrupt run:
1. Rename the old run dir: `mv <RUN_DIR> <RUN_DIR>-corrupted`
2. Start a new run with a new RUN_ID

Do not delete old run dirs. They are evidence of what was attempted.

---

## Default Configuration

| Setting | Default | Override |
|---------|---------|--------|
| Max iterations | 5 | Edit `loop-state.yaml.max_iterations` before starting |
| Run dir base | `.local/autonomous-loop/runs/` | None — fixed |
| Evidence dir | `.local/autonomous-loop/evidence/<RUN_ID>/` | None — fixed |
| Stop condition | GREEN_STOP | Loop contract defines all stop conditions |

---

## Structural Health Check

Run after implementing any changes to loop prompt files:

```bash
python scripts/quality/validate_autonomous_loop.py
# Exit 0: all references valid, all AUTONOMOUS LOOP OPERATION sections present
# Exit 1: specific failure message printed
```

---

## Known Limits

1. **Context window:** Large plans (15+ taskcards) over 4+ iterations may exhaust
   context. Use session recovery if this occurs.

2. **Self-audit:** The same agent that executes the plan runs the audit. This is
   acknowledged in `loop-audit-contract.md`. Human review before final acceptance
   is recommended for high-stakes plans.

3. **Maximum iterations:** Default 5. If GREEN is not reached in 5 iterations,
   `incomplete-loop-report.md` is written and the loop stops. A human must
   decide whether to continue, change the plan, or accept the result.

4. **Pilot validation:** The rework path (EXPAND → re-EXECUTE) was validated
   via a controlled 2-taskcard pilot (`pilot-20260618`). First production use on
   plans larger than 10 taskcards should be monitored.
