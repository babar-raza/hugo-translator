# Autonomous Green Loop — Orchestration Prompt
Version: 1.0 | System: autonomous-green-loop

---

## INVOCATION

To run the autonomous green loop on any plan:

```
Read this file (prompts/autonomous/autonomous-green-loop.md).
Then read the plan at <ABSOLUTE_PATH_TO_PLAN>.
Execute the autonomous green loop.
```

The loop runs until GREEN_STOP, a genuine external blocker, or 5 iterations.
It does not require human input between stages.

---

## MISSION

Run any plan file from its current state to GREEN_STOP by chaining the four
stage prompts (harden-plan.md, execute-plan.md, sprint-audit.md, expand-plan.md)
autonomously. Produce machine-readable state files after each stage so that
any future agent session can resume from the correct point without re-running
completed work.

The loop improves itself when weaknesses are found. If a gap in the loop
machinery is discovered, invoke the MACHINERY_HEALING lane before continuing.

---

## PREREQUISITES

Before starting, read:
1. `prompts/autonomous/loop-state-machine.md` — states, transitions, file schemas
2. `prompts/autonomous/loop-audit-contract.md` — GREEN_STOP definition, finding
   classifications
3. `prompts/autonomous/loop-idempotency-contract.md` — rerun safety rules

Do not proceed without understanding these three contracts.

---

## STEP 0: RUN SETUP

**[COORDINATOR lane]**

1. Verify the plan file exists at the path provided. If not: BLOCKED_EXTERNAL
   (plan file missing).

2. Generate RUN_ID: `autonomous-green-loop-YYYYMMDD`
   If a run directory with this name already exists, append `-b`, `-c`, etc.
   Exception: if `loop-signal.yaml` exists in that directory, this is a RESUME
   situation — go to STEP 1 (RESUME CHECK).

3. Create run directory: `.local/autonomous-loop/runs/<RUN_ID>/`

4. Write initial `loop-state.yaml`:
   ```yaml
   run_id: <RUN_ID>
   plan_path: <ABSOLUTE_PATH_TO_PLAN>
   current_state: INITIATED
   iteration: 1
   iterations_remaining: 5
   max_iterations: 5
   started_at: <ISO-8601 now>
   updated_at: <ISO-8601 now>
   transitions: []
   ```

5. Initialize `taskcard-registry.yaml`:
   ```yaml
   run_id: <RUN_ID>
   plan_path: <ABSOLUTE_PATH_TO_PLAN>
   created_at: <ISO-8601 now>
   updated_at: <ISO-8601 now>
   taskcards: []
   ```

6. Record transition: INITIATED (reason: "Loop started").

---

## STEP 1: RESUME CHECK

**[COORDINATOR lane]**

If `.local/autonomous-loop/runs/<RUN_ID>/loop-signal.yaml` exists:

- Read `next_action`:
  - `GREEN_STOP`: The loop already reached green. Print status and STOP.
    Do NOT re-execute. This invocation is a no-op.
  - `BLOCKED_EXTERNAL`: Print `blocker_description` and STOP. Human must resolve.
  - `MAX_ITER_REACHED`: Print incomplete-loop-report.md path and STOP.
  - `EXPAND`: Resume from STEP 5 (EXPAND stage) with current iteration.
  - `AUDIT_COMPLETE` (state): Resume from STEP 5 (EXPAND stage).
  - Any other: Read `loop-state.yaml.current_state` and resume from
    the appropriate step.

If `loop-state.yaml` exists but `loop-signal.yaml` does not:
- Read `current_state` and resume from the appropriate step.

If neither file exists: this is a fresh run. Continue to STEP 2.

---

## STEP 2: HARDEN STAGE (iteration 1 only)

**[PLAN_HARDENING lane]**

1. Update `loop-state.yaml`: `current_state: HARDENING`

2. **Context assembly — do this before applying harden-plan.md logic:**
   Read the plan file at `<PLAN_PATH>` completely. Hold its contents in working
   memory as the "active plan." This satisfies harden-plan.md's PLAN DISCOVERY
   requirement.

3. Apply all logic from `prompts/autonomous/harden-plan.md`:
   - Perform PLAN DISCOVERY AND SCOPE LOCK
   - Perform REPOSITORY RECON
   - Perform GAP ANALYSIS
   - Perform ROOT-CAUSE ANALYSIS
   - Perform TECHNICAL DESIGN HARDENING
   - Perform TASKCARD NORMALIZATION
   - Perform VERIFICATION DESIGN
   - Do NOT stop at EXECUTION-READY HANDOFF — continue to step 4

4. Write `gap-register.md` to the run directory:
   - List every gap identified with severity and root cause
   - List every taskcard the plan should contain after hardening

5. Populate `taskcard-registry.yaml` with all taskcards:
   - Each with `status: OPEN, opened_iteration: 1, source: HARDEN`
   - Sharpen vague acceptance criteria to testable conditions

6. Write `stage-1-harden-handoff.yaml` to the run directory:
   ```yaml
   stage: HARDEN
   iteration: 1
   status: COMPLETE
   gap_count: <integer>
   taskcard_count: <integer>
   evidence_artifact: gap-register.md
   ```

7. Update `loop-state.yaml`: `current_state: HARDENED`, append transition.

---

## STEP 3: EXECUTE STAGE (every iteration)

**[EXECUTION lane + VERIFICATION lane]**

Let N = current iteration number (from `loop-state.yaml.iteration`).

1. Update `loop-state.yaml`: `current_state: EXECUTING`

2. Read `taskcard-registry.yaml`. Build the working list: all tasks with
   `status: OPEN or IN_PROGRESS`. If the list is empty and N == 1: error.
   If empty and N > 1: this means all tasks closed — skip to STEP 4.

3. **Context assembly — do this before applying execute-plan.md logic:**
   Read the plan file at `<PLAN_PATH>` completely. This is the current active
   plan (potentially updated by prior EXPAND stages). Read `gap-register.md`
   if iteration 1, or `expansion-delta-iter<N-1>.md` if N > 1, for context.
   Hold contents in working memory.

4. Apply all logic from `prompts/autonomous/execute-plan.md` for each OPEN task:
   - PLAN AND SCOPE (bound to current plan, not full prompt 12-phase cycle
     for already-hardened plans)
   - CURRENT-STATE RECON
   - EXECUTE (implement changes)
   - VERIFY (run tests, validators)
   - HEAL (repair failing tests inline)
   - Do NOT stop after FINAL ALL-GREEN RECONCILIATION — continue to step 5

   For each taskcard:
   - Mark `status: IN_PROGRESS` in registry before starting
   - Mark `status: CLOSED, closed_iteration: N` when evidence exists

5. Run `python scripts/quality/validate_autonomous_loop.py` if this sprint's
   deliverable includes loop files. Record the exit code and output.

6. Write `changed-files-iter<N>.txt`:
   ```
   <relative-path>  CREATED|MODIFIED|DELETED
   ```

7. Write `stage-<N>-execute-handoff.yaml`:
   ```yaml
   stage: EXECUTE
   iteration: <N>
   status: COMPLETE
   tests_passed: <boolean>
   test_command: <exact command>
   test_result_summary: "<N passed, M failed>"
   changed_files_count: <integer>
   evidence_artifact: changed-files-iter<N>.txt
   open_tasks_remaining: <integer>
   ```

8. Update `taskcard-registry.yaml` with all status changes.

9. Update `loop-state.yaml`: `current_state: EXECUTED`, append transition.

---

## STEP 4: AUDIT STAGE (every iteration)

**[AUDIT lane]**

1. Update `loop-state.yaml`: `current_state: AUDITING`

2. **Context assembly:**
   Read `changed-files-iter<N>.txt`. Read `stage-<N>-execute-handoff.yaml`.
   Read the actual files listed in the changed-files manifest. Read
   `taskcard-registry.yaml`. Hold all contents in working memory.

3. Apply all logic from `prompts/autonomous/sprint-audit.md`:
   - REQUIRED INPUT DISCOVERY
   - EVIDENCE HIERARCHY
   - ACHIEVEMENT CLASSIFICATION
   - PROOF-LEVEL CLASSIFICATION
   - The AUTONOMOUS LOOP OPERATION section at end of sprint-audit.md applies here
   - Do NOT stop after producing the audit output — continue to step 4

4. Write `audit-report-iter<N>.md` to the run directory.

5. Count `blocking_gaps`: number of findings classified as `BLOCKING_GAP`.

6. Determine `next_action`:
   - 0 blocking gaps AND all registry tasks CLOSED → `GREEN_STOP`
   - > 0 blocking gaps AND `iterations_remaining > 0` → `EXPAND`
   - > 0 blocking gaps AND `iterations_remaining <= 0` → `MAX_ITER_REACHED`
   - Genuine external blocker found → `BLOCKED_EXTERNAL`

7. Write `loop-signal.yaml`:
   ```yaml
   run_id: <RUN_ID>
   plan_path: <PLAN_PATH>
   iteration: <N>
   state: AUDIT_COMPLETE
   audit_verdict: <from sprint-audit.md final verdict>
   blocking_gaps: <count>
   next_action: <GREEN_STOP|EXPAND|BLOCKED_EXTERNAL|MAX_ITER_REACHED>
   blocker_description: ""  # populate only for BLOCKED_EXTERNAL
   max_iterations: 5
   iterations_remaining: <current value>
   updated_at: <ISO-8601 now>
   ```

8. Write `stage-<N>-audit-handoff.yaml`:
   ```yaml
   stage: AUDIT
   iteration: <N>
   status: COMPLETE
   audit_verdict: <verdict>
   blocking_gaps: <count>
   next_action: <next_action>
   evidence_artifact: audit-report-iter<N>.md
   ```

9. Update `loop-state.yaml`: `current_state: AUDIT_COMPLETE`, append transition.

---

## STEP 5: STOP EVALUATION

**[COORDINATOR lane]**

Read `loop-signal.yaml.next_action`:

- `GREEN_STOP` → go to STEP 8 (GREEN_STOP handler)
- `BLOCKED_EXTERNAL` → go to STEP 9 (BLOCKED_EXTERNAL handler)
- `MAX_ITER_REACHED` → go to STEP 10 (MAX_ITER_REACHED handler)
- `EXPAND` → go to STEP 6 (EXPAND stage)

---

## STEP 6: EXPAND STAGE

**[EXPANSION lane]**

1. Update `loop-state.yaml`: `current_state: EXPANDING`

2. **Context assembly — this is critical for expand-plan.md which requires
   "recent conversation context":**
   Read `audit-report-iter<N>.md` completely.
   Read the plan file at `<PLAN_PATH>` completely.
   Read `taskcard-registry.yaml` to understand which tasks are OPEN vs CLOSED.
   The contents of these files ARE the "recent conversation context/prose"
   that `expand-plan.md`'s INPUT DISCOVERY RULE requires. No conversation
   history is needed — the files provide the equivalent context.

3. Apply all logic from `prompts/autonomous/expand-plan.md`:
   - INPUT DISCOVERY: use the files read in step 2 as input
   - CORE MISSION: extract every BLOCKING_GAP finding from the audit report
   - GAP EXTRACTION CATEGORIES: convert to new taskcards
   - TASKCARD REQUIREMENTS: every actionable finding becomes a taskcard
   - PLAN FORMAT PRESERVATION: append to plan file, do not restructure it
   - Do NOT stop after writing the expanded plan — continue to step 4

4. Append new taskcards to `taskcard-registry.yaml`:
   ```yaml
   - id: TC-<SCOPE>-<NN>
     title: "<from audit finding>"
     status: OPEN
     opened_iteration: <N+1>
     closed_iteration: null
     source: EXPAND_iter<N>
     acceptance_criteria: "<testable condition>"
     evidence_artifact: null
   ```
   Apply duplicate prevention rules from `loop-idempotency-contract.md`.

5. Write `expansion-delta-iter<N>.md`:
   - What audit findings caused this expansion
   - What new taskcards were added
   - What plan amendments were made

6. Write `stage-<N>-expand-handoff.yaml`:
   ```yaml
   stage: EXPAND
   iteration: <N>
   status: COMPLETE
   new_tasks_added: <integer>
   evidence_artifact: expansion-delta-iter<N>.md
   ```

7. Update `loop-state.yaml`: `current_state: EXPANDED`, append transition.

---

## STEP 7: LOOP BACK

**[COORDINATOR lane]**

1. Decrement `loop-state.yaml.iterations_remaining` by 1.
2. Increment `loop-state.yaml.iteration` by 1.
3. Update `loop-signal.yaml.iterations_remaining` to match.
4. Update `loop-state.yaml`: `current_state: HARDENED` (re-entry point for EXECUTE).
5. Go to STEP 3 (EXECUTE STAGE) with the new iteration number.

---

## STEP 8: GREEN_STOP

**[COORDINATOR + MACHINERY_HEALING lane]**

Verify ALL conditions before writing final report:
1. `loop-signal.yaml.next_action == GREEN_STOP` — confirmed
2. All entries in `taskcard-registry.yaml` have `status: CLOSED` — verify
3. `python scripts/quality/validate_autonomous_loop.py` exits 0 — run it
4. `loop-state.yaml.iteration >= 1` — confirmed

If condition 2 or 3 fails:
- Write a new audit finding for the failed condition
- Set `loop-signal.yaml.next_action: EXPAND`
- Go to STEP 6 (this is a machinery-healing trigger)

If all conditions pass:

1. Update `loop-state.yaml`: `current_state: GREEN`, append transition.
2. Update `loop-signal.yaml.state: GREEN`.
3. Compile the evidence bundle in
   `.local/autonomous-loop/evidence/<RUN_ID>/`:
   - Copy or write all 11 required files from `loop-evidence-contract.md`
   - `final-green-report.md` must include: run summary, iterations taken,
     all taskcards and their final status, final audit verdict, evidence
     bundle location

4. Print the GREEN_STOP summary:
   ```
   AUTONOMOUS GREEN LOOP — GREEN_STOP
   Run ID: <RUN_ID>
   Iterations: <N>
   Plan: <PLAN_PATH>
   All taskcards: CLOSED
   Final audit verdict: <verdict>
   Evidence bundle: .local/autonomous-loop/evidence/<RUN_ID>/
   ```

---

## STEP 9: BLOCKED_EXTERNAL STOP

**[COORDINATOR lane]**

1. Update `loop-state.yaml`: `current_state: BLOCKED_EXTERNAL`
2. Ensure `loop-signal.yaml.blocker_description` is populated with:
   - What specific resource, credential, or authority is needed
   - What the agent tried that failed
   - What a human must do to unblock
3. Write escalation note (append to `gap-register.md` or create
   `blocked-external-iter<N>.md`)
4. Print the blocker and stop.

The run directory is preserved. A future session can resume after the blocker
is resolved (see `loop-runbook.md`).

---

## STEP 10: MAX_ITER_REACHED

**[COORDINATOR lane]**

1. Update `loop-state.yaml`: `current_state: MAX_ITER_REACHED`
2. Write `incomplete-loop-report.md` to the run directory:
   - All tasks in registry with `status: OPEN or BLOCKED`
   - All BLOCKING_GAP findings from the latest `audit-report-iter<N>.md`
   - Recommended next steps (increase iterations, simplify plan, manual resolution)
3. Print a summary of what remains open and stop.

The loop MUST NOT continue past this point without explicit human authorization
to increase `max_iterations`.

---

## ANTI-DRIFT RULES

The loop must NOT:
- Skip the AUDIT stage because execution "went well"
- Accept GREEN_STOP without confirming `taskcard-registry.yaml` (all CLOSED)
- Load all four stage prompts simultaneously (load each prompt at its stage only)
- Re-run closed taskcards
- Treat a previous session's summary as evidence (read the actual files)
- Advance state without writing the corresponding handoff YAML first
- Classify an external-API or credential failure as MAX_ITER — it is BLOCKED_EXTERNAL
- Create new taskcards in EXECUTION lane (only EXPANSION creates new tasks)

The loop MUST:
- Apply the AUTONOMOUS LOOP OPERATION section of each stage prompt when running
  in loop context
- Record every state transition in `loop-state.yaml.transitions`
- Write all per-iteration files with the iteration number in the filename
- Produce a non-empty `audit-report-iter<N>.md` at every audit stage
- Check `loop-idempotency-contract.md` before creating new taskcards in EXPAND
