# Autonomous Green Loop — Swarm Contract
Version: 1.0 | System: autonomous-green-loop

---

## Purpose

Defines the lane structure, file ownership, overlap prevention rules, and
single-agent operation protocol for the autonomous green loop. The system is
designed for a single agent running all lanes sequentially, but structured to
be swarm-compatible if multiple agents are ever used.

---

## Lanes

### Lane 1: COORDINATOR
**Role:** Owns the loop state machine. Assigns tasks. Controls stage transitions.
Prevents overlapping claims. Reconciles evidence.

**Exclusively owns:**
- `loop-state.yaml` — sole writer; all other lanes read-only
- Run directory creation and initialization
- Transition validation (no lane may advance state without COORDINATOR writing
  the transition to `loop-state.yaml`)
- Stopping decisions (GREEN_STOP, MAX_ITER_REACHED, BLOCKED_EXTERNAL)

**Reads:**
- `loop-signal.yaml` (written by AUDIT lane)
- `taskcard-registry.yaml` (read-only; delegates writes to individual lanes)

---

### Lane 2: PLAN_HARDENING
**Role:** Normalizes the plan. Creates the initial taskcard registry. Produces
the execution handoff.

**Exclusively owns (iteration 1 only):**
- `gap-register.md`
- `stage-1-harden-handoff.yaml`
- Initial `taskcard-registry.yaml` (creation only; subsequent updates by other lanes)

**Must NOT:**
- Modify source files
- Run tests or implementation commands
- Commit or push changes

---

### Lane 3: EXECUTION
**Role:** Implements taskcards. Modifies source files. Runs tests. Updates
taskcard status.

**Exclusively owns (per iteration):**
- `changed-files-iter<N>.txt`
- `stage-<N>-execute-handoff.yaml`
- Status updates in `taskcard-registry.yaml` (OPEN → IN_PROGRESS → CLOSED)

**Must NOT:**
- Write `loop-signal.yaml` (owned by AUDIT lane)
- Write `loop-state.yaml` transitions (owned by COORDINATOR)
- Delete or overwrite prior-iteration artifacts

---

### Lane 4: VERIFICATION
**Role:** Runs tests. Validates outputs. Checks gates. Reports results.

**Exclusively owns:**
- Test result summaries written into `stage-<N>-execute-handoff.yaml`
  (collaborates with EXECUTION lane)
- Output of `validate_autonomous_loop.py` written to
  `verification-commands.log`

In single-agent operation, VERIFICATION runs as part of the EXECUTION stage
immediately after implementation steps and before writing the handoff YAML.

---

### Lane 5: AUDIT
**Role:** Performs evidence-based audit. Challenges all claims. Creates findings.
Writes the machine-readable stop signal.

**Exclusively owns:**
- `audit-report-iter<N>.md`
- `stage-<N>-audit-handoff.yaml`
- `loop-signal.yaml` — sole writer; all other lanes read-only

**Must NOT:**
- Modify source files
- Re-run taskcards
- Classify findings as ACCEPTED without concrete evidence artifacts

---

### Lane 6: EXPANSION
**Role:** Converts audit findings into plan changes. Prepares re-execution.

**Exclusively owns:**
- `expansion-delta-iter<N>.md`
- `stage-<N>-expand-handoff.yaml`
- New taskcard entries appended to `taskcard-registry.yaml`
- Amendments appended to the plan file

**Must NOT:**
- Modify source files (only the plan file)
- Re-open closed taskcards
- Override the COORDINATOR's decision to stop

---

### Lane 7: MACHINERY_HEALING
**Role:** Improves loop infrastructure when a process weakness is discovered.
Updates prompts, validators, state rules, or contracts.

**Owns:**
- Modifications to loop prompt files (`prompts/autonomous/loop-*.md`,
  `prompts/autonomous/autonomous-green-loop.md`)
- Modifications to `scripts/quality/validate_autonomous_loop.py`
- Modifications to `scripts/ops/autonomous_loop_status.py`

**Activation condition:** Only invoked when an audit or execution reveals a
weakness in the loop machinery itself (e.g., a missing check in the validator,
an incorrect state transition, an ambiguous contract). Not invoked for normal
plan execution failures.

**Must NOT:**
- Modify the 4 existing stage prompts (harden-plan.md, execute-plan.md,
  sprint-audit.md, expand-plan.md) unless the weakness is specifically in their
  AUTONOMOUS LOOP OPERATION sections
- Modify source code outside `prompts/autonomous/` and `scripts/ops/`

---

## Single-Agent Operation Protocol

When a single agent runs all 7 lanes:

1. The agent explicitly declares its lane before acting in it:
   ```
   [COORDINATOR]: Initializing loop state for run autonomous-green-loop-20260618...
   [PLAN_HARDENING]: Applying harden-plan.md logic...
   [EXECUTION]: Executing TC-LOOP-01...
   [VERIFICATION]: Running validate_autonomous_loop.py...
   [AUDIT]: Reviewing evidence for iteration 1...
   [COORDINATOR]: Reading loop-signal.yaml: next_action=GREEN_STOP...
   ```

2. The agent never acts in two lanes simultaneously within the same operation.
   Sequential execution, one lane at a time.

3. The COORDINATOR makes all state transition decisions. Other lanes may propose
   but not directly advance state.

---

## File Ownership Matrix

| File | Created by | Updated by | Read by |
|------|------------|------------|---------|
| `loop-state.yaml` | COORDINATOR | COORDINATOR | All |
| `loop-signal.yaml` | AUDIT | AUDIT | COORDINATOR, EXPANSION |
| `taskcard-registry.yaml` | PLAN_HARDENING | EXECUTION, EXPANSION | All |
| `gap-register.md` | PLAN_HARDENING | — | EXECUTION |
| `stage-1-harden-handoff.yaml` | PLAN_HARDENING | — | COORDINATOR |
| `changed-files-iter<N>.txt` | EXECUTION | — | AUDIT |
| `stage-<N>-execute-handoff.yaml` | EXECUTION/VERIFICATION | — | COORDINATOR, AUDIT |
| `audit-report-iter<N>.md` | AUDIT | — | EXPANSION |
| `stage-<N>-audit-handoff.yaml` | AUDIT | — | COORDINATOR |
| `expansion-delta-iter<N>.md` | EXPANSION | — | COORDINATOR |
| `stage-<N>-expand-handoff.yaml` | EXPANSION | — | COORDINATOR |

---

## Overlap Prevention Rules

1. No two lanes write the same file in the same iteration.
2. Handoff YAML files are written exactly once (at stage completion). A second
   write indicates an error; investigate before proceeding.
3. If the AUDIT lane finds `loop-signal.yaml` already exists from the current
   iteration, it must read and compare before overwriting. If the previous
   signal was GREEN_STOP and the new audit disagrees, this is a
   MACHINERY_HEALING trigger — do not overwrite silently.
4. `taskcard-registry.yaml` updates from EXPANSION and EXECUTION must not
   conflict. In single-agent operation, they run sequentially. In multi-agent
   operation, a file lock or optimistic concurrency check is required.
