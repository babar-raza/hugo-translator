# Autonomous Green Loop — Taskcard Contract
Version: 1.0 | System: autonomous-green-loop

---

## Purpose

Defines the required shape of every taskcard in the autonomous green loop,
the schema of `taskcard-registry.yaml`, and the rules governing taskcard
lifecycle across iterations.

---

## taskcard-registry.yaml Schema

This file is the single source of truth for all taskcards in a loop run.
It lives at: `.local/autonomous-loop/runs/<RUN_ID>/taskcard-registry.yaml`

```yaml
run_id: string                     # matches loop-state.yaml.run_id
plan_path: string                  # absolute path to bound plan file
created_at: ISO-8601 datetime      # when registry was initialized
updated_at: ISO-8601 datetime      # last modification time
taskcards:
  - id: string                     # required; format: TC-XX-NN
    title: string                  # required; human-readable
    status: string                 # required; see Status Values below
    opened_iteration: integer      # required; iteration in which task was created
    closed_iteration: integer      # null until closed
    source: string                 # HARDEN | EXPAND_iter<N>
    acceptance_criteria: string    # required; brief, testable
    evidence_artifact: string      # relative path to evidence, or null
    lane: string                   # optional; which swarm lane owns this
    regression_of: string          # optional; ID of prior taskcard this re-opens
```

All fields marked "required" must be present. Optional fields may be omitted.

---

## Status Values

| Status | Meaning |
|--------|---------|
| `OPEN` | Not yet started; eligible for execution in the current iteration |
| `IN_PROGRESS` | Execution agent has claimed this task in the current iteration |
| `CLOSED` | Completed with evidence; never re-opened (see idempotency contract) |
| `BLOCKED` | Cannot proceed due to an external blocker; classify finding as EXTERNAL_BLOCKER |

---

## Taskcard ID Convention

Format: `TC-<SCOPE>-<NN>` where:
- `SCOPE` is a 2-4 character abbreviation of the plan's domain (e.g., `LOOP`, `PILOT`, `ENG`)
- `NN` is a zero-padded 2-digit sequence number within the scope

IDs must be unique within a run. When expansion adds new tasks in iteration N,
use the next available sequential number in the scope:
- Original: TC-LOOP-01, TC-LOOP-02, TC-LOOP-03
- Added in expansion: TC-LOOP-04, TC-LOOP-05

Do not reuse IDs. If a closed task must be redone (regression), create a new
ID with a `regression_of` field.

---

## Required Fields Per Taskcard (Full Shape)

Every taskcard that becomes executable (status: OPEN) must have:

```yaml
- id: TC-LOOP-01
  title: "Concise action description"
  status: OPEN
  opened_iteration: 1
  closed_iteration: null
  source: HARDEN                          # or EXPAND_iter1, EXPAND_iter2, etc.
  acceptance_criteria: >
    Specific, testable condition. Example: "validate_autonomous_loop.py exits 0"
    or "tests/unit/test_x.py::test_foo passes"
  evidence_artifact: null                 # filled in when closed
  lane: EXECUTION                         # or VERIFICATION, PLAN_HARDENING, etc.
```

When the task is closed:
```yaml
  status: CLOSED
  closed_iteration: 1
  evidence_artifact: changed-files-iter1.txt  # relative to run directory
```

---

## Lifecycle Rules

1. **HARDEN stage** initializes the registry with all taskcards extracted from
   the plan. All start at `status: OPEN, source: HARDEN`.

2. **EXECUTE stage** reads the registry at startup. Works only `OPEN` and
   `IN_PROGRESS` tasks. Marks tasks `IN_PROGRESS` when starting, `CLOSED`
   when evidence is written.

3. **AUDIT stage** does not modify the registry. It reads it to check for
   unclosed tasks.

4. **EXPAND stage** appends new taskcards to the registry. New tasks get
   `status: OPEN, source: EXPAND_iter<N>`. Existing tasks are not modified.

5. A task may only move `OPEN → IN_PROGRESS → CLOSED` or `OPEN → BLOCKED`.
   Backward transitions are not valid.

6. `CLOSED` is terminal. See idempotency contract for what happens when
   a regression requires redoing a closed task.

---

## Execute Stage: Task Selection Rule

At the start of each EXECUTE iteration, the agent must:

1. Read `taskcard-registry.yaml`
2. Build a working list of tasks: all entries with `status: OPEN or IN_PROGRESS`
3. If the working list is empty AND this is iteration 1: halt with an error
   (the HARDEN stage failed to extract taskcards)
4. If the working list is empty AND this is iteration 2+: check `loop-signal.yaml`
   — if `blocking_gaps == 0`, this state is correct (all tasks were already closed
   and the audit confirmed green). Otherwise, there is a registry inconsistency.
5. Execute only tasks from the working list.

---

## Acceptance Criteria Quality Standard

Acceptance criteria must be testable without additional judgment:

GOOD:
- "`python scripts/quality/validate_autonomous_loop.py` exits 0"
- "`tests/unit/test_loop.py::test_state_machine_transitions` passes"
- "File `prompts/autonomous/loop-audit-contract.md` exists and contains 'BLOCKING_GAP'"

NOT ACCEPTABLE:
- "The task is done well"
- "Code quality is high"
- "Feature works as expected"

If the plan's original taskcard has vague acceptance criteria, the HARDEN stage
must sharpen them before initializing the registry.
