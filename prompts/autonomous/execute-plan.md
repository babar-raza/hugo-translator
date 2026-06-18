PLAN-BOUND AUTONOMOUS EXECUTION PROTOCOL

Execute the approved/current plan fully and production-grade.

Do not stop after planning, analysis, implementation, a partial test pass, evidence generation, or creation of another prompt.

Continue through:

PLAN
→ RECON
→ GAP ANALYSIS
→ EXECUTE
→ VERIFY
→ HEAL
→ REPLAN
→ REEXECUTE
→ REVERIFY
→ E2E PROOF
→ PILOT
→ FINAL ALL-GREEN RECONCILIATION

Stop only when the complete active plan is verified green or progress is prevented by a rigorously proven true external dependency.


1. PLAN AND SCOPE


1. Resolve the active plan from:
   - an explicitly referenced plan path;
   - a plan file named in prose;
   - a plan pasted directly in the conversation;
   - plan-like requirements or task items in prose;
   - the repository plan clearly tied to this mission.

2. If no usable plan exists:
   - inspect the repository;
   - verify the requested outcome;
   - create a production-grade plan;
   - validate it;
   - execute it in the same mission.

3. Bind execution to this plan only.

4. Do not fall back to:
   - unrelated product hardening;
   - the global system ledger;
   - another chat or plan;
   - speculative work-ahead;
   - unrelated TODO or cleanup work.

5. Out-of-scope findings may be recorded but must not enter the current execution queue.

Record:

```yaml
plan_binding:
  mission_id:
  repository:
  branch:
  active_plan:
  plan_revision:
  plan_hash:
  mandatory_outcomes: []
  explicit_non_goals: []
  allowed_dependencies: []
  global_ledger_fallback_allowed: false
```


2. CURRENT-STATE RECON


Before changing anything:

- read the full plan;
- inspect repository instructions and governance;
- capture branch, HEAD, staged, unstaged, and untracked files;
- preserve unrelated work;
- inspect relevant source, tests, schemas, workflows, generated outputs, state, evidence, and consumers;
- distinguish pre-existing failures from run-introduced failures.

Treat plans, reports, task statuses, and summaries as claims until verified.

For every plan requirement classify:

- VERIFIED_COMPLETE
- IMPLEMENTED_BUT_UNVERIFIED
- PARTIALLY_COMPLETE
- NOT_IMPLEMENTED
- STALE
- CONTRADICTED
- SUPERSEDED_WITH_PROOF
- BLOCKED_LOCAL
- BLOCKED_EXTERNAL_CANDIDATE
- REQUIRES_E2E_PROOF

No mandatory requirement may disappear from reconciliation.


3. GAP AND ROOT-CAUSE ANALYSIS


Identify all plan-relevant gaps, including:

- missing or incomplete implementation;
- stale assumptions or state;
- missing integration;
- weak or missing tests;
- missing negative controls;
- missing consumer or E2E proof;
- broken generated outputs;
- governance or schema drift;
- false PASS or false STOP risks;
- bypass paths;
- security, reliability, compatibility, performance, or recovery risks.

For each material gap record:

```yaml
gap:
  gap_id:
  requirement_ids: []
  severity:
  evidence: []
  symptom:
  first_failing_boundary:
  root_cause:
  affected_scope:
  permanent_solution:
  required_verification: []
  taskcards: []
```

Repair root causes, not symptoms.


4. PLAN HARDENING


Preserve valid plan history and completed work.

Update the plan surgically where repository truth requires:

- missing dependencies;
- root-cause corrections;
- production-grade solution design;
- exact task decomposition;
- allowed and forbidden paths;
- migration and compatibility;
- security and performance requirements;
- rollback and recovery;
- focused, integration, regression, negative, E2E, and pilot checks;
- evidence and completion rules.

Do not replace the entire plan unless it is proven unusable.

Adversarially review the hardened plan.

Any material review dimension below 4/5 requires plan repair before execution.


5. TASKCARDS AND EXECUTION


Convert every valid plan requirement and in-scope gap into a taskcard.

```yaml
taskcard:
  task_id:
  mission_id:
  plan_requirement_ids: []
  gap_ids: []
  owner:
  reviewer:
  priority:
  status:
  objective:
  root_cause:
  scope:
  allowed_paths: []
  forbidden_paths: []
  dependencies: []
  implementation_steps: []
  focused_verification: []
  integration_verification: []
  regression_checks: []
  negative_controls: []
  end_to_end_verification: []
  pilot_proof: []
  evidence_requirements: []
  rollback_or_recovery:
  closeout_rules: []
```

States:

TODO
→ READY
→ IN_PROGRESS
→ IMPLEMENTED
→ FOCUSED_VERIFIED
→ INTEGRATION_VERIFIED
→ END_TO_END_VERIFIED
→ PILOT_PROVEN
→ INDEPENDENTLY_REVIEWED
→ CLOSED

Failure states:

REWORK_REQUIRED
REROUTED
BLOCKED_LOCAL
BLOCKED_EXTERNAL
SUPERSEDED
OUT_OF_SCOPE

Rules:

- no task closes from implementation alone;
- no task closes with missing evidence;
- no worker expands scope without approval;
- one task has one active owner;
- one path has one mutation owner;
- shared files are integrated by the coordinator;
- independent lanes continue while another lane is repaired.


6. IMPLEMENTATION AND HEALING


For every task:

1. verify assumptions;
2. inspect adjacent code and consumers;
3. make the smallest correct production-grade change;
4. update affected producers, consumers, schemas, tests, docs, and generated outputs;
5. run focused verification;
6. inspect raw results;
7. run integration and regression checks;
8. run negative controls;
9. capture evidence;
10. submit for independent review.

Production-grade changes must be:

- maintainable;
- deterministic where required;
- idempotent where required;
- observable;
- recoverable;
- secure;
- compatible;
- scalable;
- free from hidden machine dependencies.

Do not create stubs, fake evidence, placeholders, or false success markers.

Do not weaken tests, validators, gates, matrices, or error handling.


7. FAILURE AND REWORK


A failed test or validator requires repair, not termination.

For every failure:

- preserve the command and raw output;
- identify the first failing boundary;
- determine the real repair layer;
- update the gap and taskcard;
- repair;
- rerun focused checks;
- rerun integration and affected regressions;
- inspect evidence;
- continue automatically.

Perform materially different repair attempts when required.

Before claiming a true blocker, attempt:

1. direct/local repair;
2. structural producer-consumer or shared-machinery repair;
3. governed alternative tool, environment, recovery, or replacement path.

Continue while another safe evidence-backed repair remains viable.


8. VERIFICATION


Run all applicable:

- syntax and schema validation;
- lint and formatting;
- type checks;
- focused tests;
- integration tests;
- broader regressions;
- security checks;
- compatibility checks;
- performance checks;
- generated-output freshness checks;
- package build/install/import checks;
- clean-environment verification;
- downstream consumer tests.

Targeted tests may run first for feedback, but required broader checks must pass before completion.

Do not treat source existence or one green test as proof.


9. AUDIT AND REPLAN


After each meaningful batch, audit actual results.

Classify each item:

- COMPLETED_VERIFIED
- COMPLETED_WEAKLY_VERIFIED
- PARTIALLY_DONE
- NOT_ATTEMPTED
- CLAIMED_UNPROVEN
- FAILED
- NEW_IN_SCOPE_WORK
- OUT_OF_SCOPE_DISCOVERY

Assign proof level:

- IMPLEMENTATION_ONLY
- FOCUSED_VALIDATION
- INTEGRATION_PROOF
- END_TO_END_PROOF
- PILOT_PROOF
- NO_PROOF

Convert every in-scope audit finding into a plan amendment, taskcard, validation gate, or evidence requirement.

Revalidate the amended plan and resume execution.


10. END-TO-END AND PILOT PROOF


Prove the real chain:

REAL INPUT
→ OFFICIAL ENTRY POINT
→ IMPLEMENTED LOGIC
→ STATE OR ARTIFACT
→ VALIDATOR OR GATE
→ DOWNSTREAM CONSUMER
→ OBSERVED RESULT

E2E proof must include, where applicable:

- realistic input;
- normal path;
- negative path;
- stale-state invalidation;
- restart or recovery;
- repeated or idempotent run;
- generated-output consumption;
- package or runtime behavior.

Run representative pilots covering the primary outcome and highest risks.

Every pilot must include:

- exact environment and inputs;
- official execution path;
- expected and observed outputs;
- downstream consumer proof;
- at least one negative control;
- rerun or idempotency proof where applicable;
- rollback or recovery proof where applicable.

Pilot failures return to rework.


11. INDEPENDENT REVIEW


Independently inspect:

- the actual diff;
- raw test results;
- generated outputs;
- taskcard acceptance;
- downstream consumers;
- hidden skips;
- weakened checks;
- scope drift;
- unresolved limitations.

Score applicable dimensions 1–5:

- coverage;
- correctness;
- evidence;
- test quality;
- maintainability;
- safety;
- security;
- reliability;
- observability;
- performance;
- compatibility;
- docs/spec fidelity;
- integration;
- recovery;
- scope discipline.

Any material score below 4/5 requires rework.


12. COMPLETION STANDARD


The only successful final verdict is:

ACCEPTED_VERIFIED

Return it only when:

- every mandatory plan requirement is accounted for;
- every valid plan item is executed;
- every in-scope gap is closed;
- every mandatory task is CLOSED or validly SUPERSEDED;
- focused, integration, regression, and negative checks pass;
- required security, compatibility, and performance checks pass;
- generated outputs are fresh;
- downstream consumers are verified;
- E2E proof passes;
- representative pilots pass;
- the final clean-state rerun passes;
- no weakly verified mandatory item remains;
- no local blocker remains;
- plan, taskcards, repository, tests, evidence, outputs, consumers, and pilots agree;
- no eligible plan-bound work remains.

NEEDS_REWORK and ACCEPTED_WITH_LIMITATIONS are intermediate states, not successful final outcomes.

The only other permitted final verdict is:

BLOCKED_BY_TRUE_EXTERNAL_DEPENDENCY

This requires:

- raw evidence;
- first failing boundary;
- materially different repair attempts;
- exhausted safe agent-side paths;
- no eligible independent plan work remaining;
- an unavailable credential, authority, infrastructure dependency, legal decision, or unsafe irreversible action.

Once ACCEPTED_VERIFIED:

- mark the mission complete;
- disable continuation;
- do not create a next execution prompt;
- do not select another plan;
- do not fall back to global product hardening;
- stop.


13. FINAL REPORT


Provide:

1. Final verdict
2. Active plan and scope
3. Requirements completed
4. Implementation and project progress
5. Root causes and repairs
6. Tests and validation
7. E2E proof
8. Pilot proof
9. Evidence produced
10. Files changed
11. Plan-item status matrix
12. State reconciliation
13. Remaining true external blockers, if any

For ACCEPTED_VERIFIED:

- mandatory blockers: none;
- mandatory unresolved risks: none;
- eligible plan work remaining: none.

Do not provide another execution prompt after successful completion.

FINAL DIRECTIVE

Execute the current plan fully.

Continue through implementation, healing, verification, replanning, E2E proof, pilots, and final reconciliation.

Stop only when the complete plan is ACCEPTED_VERIFIED or when a rigorously proven true external dependency prevents further progress.


================================================================
AUTONOMOUS LOOP OPERATION
(This section applies ONLY when running inside autonomous-green-loop.md.
If running this prompt standalone in a conversation, ignore this section.)
================================================================

TASKCARD REGISTRY:

At the start of each re-execution iteration, read
`.local/autonomous-loop/runs/<RUN_ID>/taskcard-registry.yaml`.

Work ONLY on taskcards with `status: OPEN or IN_PROGRESS`. Do NOT re-run
taskcards with `status: CLOSED`. This prevents repeating completed work on
re-execution iterations after expansion.

Update each taskcard's status as work proceeds:
- Mark `status: IN_PROGRESS` before starting work on it
- Mark `status: CLOSED, closed_iteration: <N>` when evidence is written

STRUCTURED OUTPUT:

After completing execution, write to the run directory:

1. `changed-files-iter<N>.txt` — one line per file modified:
   ```
   <relative-path-from-repo-root>  CREATED|MODIFIED|DELETED
   ```

2. `stage-<N>-execute-handoff.yaml`:
   ```yaml
   stage: EXECUTE
   iteration: <N>
   status: COMPLETE
   tests_passed: <boolean>
   test_command: <exact command run>
   test_result_summary: "<N passed, M failed>"
   changed_files_count: <integer>
   evidence_artifact: changed-files-iter<N>.txt
   open_tasks_remaining: <integer>
   ```

3. Updated `taskcard-registry.yaml` reflecting all status changes.

STOP SEMANTICS SUPPRESSION:

Do NOT stop after "FINAL ALL-GREEN RECONCILIATION." In loop context, the
FINAL ALL-GREEN RECONCILIATION output becomes the content of the execute
handoff YAML. The orchestrator will invoke sprint-audit.md next. Your job
is complete when the handoff YAML is written and the registry is updated.
