# Autonomous Green Loop — State Machine
Version: 1.0 | System: autonomous-green-loop

---

## States

| State | Description |
|-------|-------------|
| `INITIATED` | Loop started, plan bound, run directory created |
| `HARDENING` | harden-plan.md logic executing |
| `HARDENED` | Plan hardened, gap-register.md written |
| `EXECUTING` | execute-plan.md logic executing (iteration N) |
| `EXECUTED` | Execution complete, changed-files written, registry updated |
| `AUDITING` | sprint-audit.md logic executing |
| `AUDIT_COMPLETE` | Audit done, loop-signal.yaml written |
| `EXPANDING` | expand-plan.md logic executing (only if blocking_gaps > 0) |
| `EXPANDED` | Plan updated, new taskcards in registry with status OPEN |
| `GREEN` | loop-signal.yaml.next_action == GREEN_STOP and all registry tasks CLOSED |
| `BLOCKED_EXTERNAL` | Genuine external blocker; requires human decision |
| `MAX_ITER_REACHED` | 5-iteration limit hit; loop stops, state preserved for human |

HARDENING runs on iteration 1 only. Iterations 2+ re-enter at EXECUTING.

---

## Valid Transitions

| From | To | Guard Condition |
|------|----|-----------------|
| `INITIATED` | `HARDENING` | plan file exists and is readable |
| `HARDENING` | `HARDENED` | gap-register.md written to run dir |
| `HARDENED` | `EXECUTING` | taskcard-registry.yaml initialized |
| `EXECUTING` | `EXECUTED` | changed-files-iter<N>.txt written; registry updated |
| `EXECUTED` | `AUDITING` | stage handoff yaml written |
| `AUDITING` | `AUDIT_COMPLETE` | loop-signal.yaml written with next_action field set |
| `AUDIT_COMPLETE` | `GREEN` | next_action == GREEN_STOP AND all registry tasks CLOSED |
| `AUDIT_COMPLETE` | `EXPANDING` | next_action == EXPAND AND iterations_remaining > 0 |
| `AUDIT_COMPLETE` | `MAX_ITER_REACHED` | next_action == EXPAND AND iterations_remaining <= 0 |
| `AUDIT_COMPLETE` | `BLOCKED_EXTERNAL` | next_action == BLOCKED_EXTERNAL |
| `EXPANDING` | `EXPANDED` | expansion-delta-iter<N>.md written; registry updated |
| `EXPANDED` | `EXECUTING` | iterations_remaining decremented; iteration counter incremented |

No other transitions are valid. Skipping states is not permitted.

---

## Stop Conditions

### GREEN_STOP
All of the following must be true:
1. `loop-signal.yaml.next_action == "GREEN_STOP"`
2. All entries in `taskcard-registry.yaml` have `status: CLOSED`
3. `python scripts/quality/validate_autonomous_loop.py` exits 0
4. `iteration >= 1` (at least one full EXECUTE → AUDIT cycle completed)

### BLOCKED_EXTERNAL
`loop-signal.yaml.next_action == "BLOCKED_EXTERNAL"` with `blocker_description`
field populated. The agent writes an escalation note and stops. The loop state
is preserved for human review and manual restart.

Required conditions for BLOCKED_EXTERNAL classification:
- Required credential unavailable
- Required external service unavailable
- Destructive production action requires human authorization
- File or dependency cannot be created due to OS permissions
- Plan file does not exist and cannot be inferred

BLOCKED_EXTERNAL must not be used for:
- Low test scores (reroute instead)
- Compile errors (fix inline)
- Missing documentation (add inline)
- Failed audit findings (expand instead)

### MAX_ITER_REACHED
`iterations_remaining <= 0` when loop would otherwise continue expanding.
The agent writes `incomplete-loop-report.md` listing:
- All OPEN taskcards in the registry
- All unresolved blocking_gaps from the latest audit
- Recommended next step for a human or future session

---

## File Schemas

### loop-state.yaml
```yaml
run_id: string                  # autonomous-green-loop-YYYYMMDD
plan_path: string               # absolute path to bound plan file
current_state: string           # one of the 12 valid states above
iteration: integer              # current iteration number (starts at 1)
iterations_remaining: integer   # default 5, decremented on each EXPANDED→EXECUTING
max_iterations: integer         # default 5
started_at: ISO-8601 datetime
updated_at: ISO-8601 datetime
transitions:                    # append-only log
  - from_state: string
    to_state: string
    reason: string
    timestamp: ISO-8601 datetime
```

### loop-signal.yaml
Written by the AUDITING stage. Read by the orchestrator to determine next action.
```yaml
run_id: string
plan_path: string
iteration: integer
state: string                   # AUDIT_COMPLETE | GREEN | BLOCKED_EXTERNAL
audit_verdict: string           # from sprint-audit.md final verdict vocabulary
blocking_gaps: integer          # count of BLOCKING_GAP findings
next_action: string             # GREEN_STOP | EXPAND | BLOCKED_EXTERNAL
blocker_description: string     # populated only when next_action == BLOCKED_EXTERNAL
max_iterations: integer
iterations_remaining: integer
updated_at: ISO-8601 datetime
```

### taskcard-registry.yaml
Single source of truth for taskcard status across all iterations.
```yaml
run_id: string
taskcards:
  - id: string                  # TC-XX-NN format
    title: string
    status: string              # OPEN | IN_PROGRESS | CLOSED | BLOCKED
    opened_iteration: integer   # iteration in which this task was first created
    closed_iteration: integer   # null if not yet closed
    source: string              # HARDEN | EXPAND_iter<N>
    acceptance_criteria: string # brief, testable
    evidence_artifact: string   # relative path to evidence, or null
```

---

## Evidence Required Before State Advance

| Transition | Required Evidence |
|------------|-------------------|
| HARDENING → HARDENED | gap-register.md exists in run dir |
| HARDENED → EXECUTING | taskcard-registry.yaml initialized with at least 1 OPEN task |
| EXECUTING → EXECUTED | changed-files-iter<N>.txt exists; registry has no IN_PROGRESS tasks |
| EXECUTED → AUDITING | stage-<N>-execute-handoff.yaml exists |
| AUDITING → AUDIT_COMPLETE | loop-signal.yaml exists with next_action field |
| AUDIT_COMPLETE → EXPANDING | audit-report-iter<N>.md exists |
| EXPANDING → EXPANDED | expansion-delta-iter<N>.md exists; registry has new OPEN tasks OR no new gaps |
| EXPANDED → EXECUTING | loop-state.yaml updated with new iteration counter |

---

## Invalid Terminal States

These states must never appear in `loop-state.yaml.current_state` when the run
is considered complete. If found, the run is incomplete:
- `INITIATED`
- `HARDENING`
- `EXECUTING`
- `AUDITING`
- `EXPANDING`
- `AUDIT_COMPLETE` (intermediate; must advance to GREEN, EXPANDING, or a stop state)
