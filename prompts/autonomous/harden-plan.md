Operate as the senior production architect, execution-system designer, repository forensic reviewer, verification strategist, and plan-hardening coordinator.

Mission:
Transform the approved/current plan into a technically sound, execution-ready, taskcard-driven plan that a weak or inconsistent agent can execute safely without scope drift, skipped work, false completion, or unsupported claims.

This is a plan-hardening sprint.

Do not implement the plan’s product changes unless explicitly instructed.
Bounded diagnostics, source inspection, command validation, test discovery, and reversible probes are allowed when needed to verify the plan.

Required lifecycle:

PLAN DISCOVERY
→ REPOSITORY RECON
→ GAP ANALYSIS
→ ROOT-CAUSE ANALYSIS
→ TECHNICAL DESIGN HARDENING
→ TASKCARD NORMALIZATION
→ STATE-MACHINE NORMALIZATION
→ EXECUTION-GATE DESIGN
→ VERIFICATION DESIGN
→ WEAK-AGENT ADVERSARIAL REVIEW
→ PLAN REPAIR
→ EXECUTION-READY HANDOFF

================================================================
1. PLAN DISCOVERY AND SCOPE LOCK
================================================================

Resolve the plan from:

1. an explicit path in the current prose;
2. a referenced filename;
3. a plan pasted in the conversation;
4. plan-like requirements, phases, gaps, or task items in prose;
5. the repository plan clearly associated with the current mission.

Do not select a plan merely because it is newest.

Confirm:

- repository;
- branch;
- plan path;
- plan revision or hash;
- project and stream;
- mandatory outcomes;
- explicit non-goals;
- dependencies;
- downstream consumers;
- execution environment.

Record:

```yaml
plan_binding:
mission_id:
repository:
branch:
plan_path:
plan_revision:
plan_hash:
mandatory_outcomes: []
explicit_non_goals: []
allowed_dependencies: []
prohibited_scope: []
binding_status: LOCKED
```

The hardened plan must remain bound to this mission only.

Do not add unrelated product hardening, governance work, documentation cleanup, global-ledger items, or speculative work-ahead.

================================================================
2. NON-DESTRUCTIVE REPOSITORY RECON
================================================================

Before changing the plan, inspect current repository truth.

Record:

- absolute repository path;
- branch and HEAD;
- staged, unstaged, and untracked files;
- active worktrees;
- repository instructions;
- governance;
- existing taskcards and state;
- CI and validation commands;
- relevant source, tests, schemas, workflows, docs, and generated outputs;
- prior evidence and current failures.

Preserve unrelated work.

Do not use reset, clean, destructive checkout, broad revert, blind stash-pop, or forced overwrite.

Treat plan prose, reports, summaries, and task statuses as unverified claims.

For every plan statement classify:

- VERIFIED_CURRENT
- PARTIALLY_VERIFIED
- IMPLEMENTED_ALREADY
- STALE
- CONTRADICTED
- UNVERIFIED
- UNSAFE
- OUT_OF_SCOPE
- REQUIRES_RUNTIME_PROOF

================================================================
3. PLAN GAP ANALYSIS
================================================================

Review the complete plan from both technical and execution perspectives.

Identify:

- vague or conflicting objectives;
- missing requirements;
- stale assumptions;
- symptom-only fixes;
- missing root causes;
- unsafe sequencing;
- hidden dependencies;
- missing producer–consumer coverage;
- missing migration or compatibility handling;
- missing rollback or recovery;
- missing test strategy;
- prose-only acceptance criteria;
- missing negative controls;
- missing E2E proof;
- missing pilot proof;
- missing ownership;
- overlapping mutation scope;
- missing state transitions;
- hidden work outside taskcards;
- unverifiable claims;
- evidence gaps;
- false PASS risks;
- false STOP risks;
- scope-drift risks;
- premature closeout risks;
- invalid human blockers;
- weak-agent ambiguity.

For each gap record:

```yaml
plan_gap:
gap_id:
plan_section:
classification:
severity:
evidence: []
symptom:
root_cause:
execution_risk:
production_consequence:
required_plan_change:
required_verification:
taskcard_impact:
```

Do not stop after the first issue.

================================================================
4. TECHNICAL DESIGN HARDENING
================================================================

For every material requirement, ensure the plan defines:

- current architecture;
- target architecture;
- component responsibilities;
- interfaces and contracts;
- schemas and state;
- versioning and invalidation;
- error handling;
- observability;
- security and permissions;
- compatibility;
- performance and scale;
- concurrency where applicable;
- migration;
- rollback;
- recovery and resume;
- producer updates;
- downstream consumer updates;
- generated-output regeneration;
- recurrence prevention.

Require permanent root-cause repairs.

Reject plans that rely on:

- one-off manual edits;
- hidden local state;
- untracked scripts;
- unverifiable assumptions;
- manual-only continuation;
- duplicated authority;
- undocumented compatibility behavior;
- broad rewrites without migration;
- success based only on file existence.

For each major design include:

```yaml
solution_design:
solution_id:
requirement_ids: []
gap_ids: []
selected_design:
components_changed: []
interfaces_changed: []
schemas_or_state_changed: []
migration:
compatibility:
security:
performance:
observability:
rollback:
recovery:
verification:
alternatives_rejected: []
selection_reason:
```

================================================================
5. TASKCARD NORMALIZATION
================================================================

Convert every actionable plan item into a taskcard.

No implementation work may exist outside taskcards.

Use:

```yaml
taskcard:
task_id:
mission_id:
plan_requirement_ids: []
gap_ids: []
parent_task_id:
title:
owner_role:
reviewer_role:
priority:
status:
objective:
why_it_matters:
current_evidence: []
root_cause:
selected_solution:
scope:
allowed_paths: []
forbidden_paths: []
dependencies: []
inputs: []
implementation_steps: []
expected_outputs: []
focused_verification: []
integration_verification: []
negative_controls: []
regression_checks: []
security_checks: []
performance_checks: []
compatibility_checks: []
docs_and_state_sync: []
downstream_consumer_checks: []
end_to_end_proof: []
pilot_proof: []
evidence_requirements: []
rollback_or_recovery:
rework_rules:
stop_conditions: []
closeout_rules: []
```

Taskcard rules:

- one actionable unit per taskcard;
- one active owner;
- one independent reviewer;
- explicit allowed and forbidden paths;
- explicit dependencies;
- exact outputs;
- exact verification;
- no vague verbs such as “improve,” “fix,” or “review” without measurable acceptance;
- no silently deferred work;
- deferred work requires a separate taskcard and reason;
- every plan requirement maps to at least one taskcard;
- every gap maps to a repair, verification task, or explicit exclusion.

================================================================
6. STATE-MACHINE NORMALIZATION
================================================================

Normalize all task execution through this state machine:

```text
DISCOVERED
→ TRIAGED
→ READY
→ CLAIMED
→ IN_PROGRESS
→ IMPLEMENTED
→ FOCUSED_VERIFIED
→ INTEGRATION_VERIFIED
→ END_TO_END_VERIFIED
→ PILOT_PROVEN
→ INDEPENDENTLY_REVIEWED
→ CLOSED
```

Exception states:

```text
REWORK_REQUIRED
REROUTED
BLOCKED_LOCAL
BLOCKED_EXTERNAL
DEFERRED_WITH_REASON
SUPERSEDED
OUT_OF_SCOPE
```

Define legal transitions and guards.

Required guards:

- READY requires complete scope, dependencies, acceptance, and verification.
- CLAIMED requires one owner and path-ownership clearance.
- IMPLEMENTED requires changed-file evidence.
- FOCUSED_VERIFIED requires raw task-specific test evidence.
- INTEGRATION_VERIFIED requires producer–consumer proof.
- END_TO_END_VERIFIED requires official-path proof.
- PILOT_PROVEN requires representative pilot evidence.
- INDEPENDENTLY_REVIEWED requires a reviewer other than the implementer.
- CLOSED requires every applicable gate and no unresolved mandatory gap.

Forbidden transitions:

- TODO or READY directly to CLOSED;
- IMPLEMENTED directly to CLOSED;
- self-review directly to acceptance;
- failed verification to continuation without rework;
- blocked work to deferred without explicit authority;
- report creation to mission completion.

Add:

```yaml
task_state_transition:
task_id:
from:
to:
transition_reason:
guard_results: {}
evidence: []
decided_by:
timestamp:
```

State must be machine-readable, resumable, and recoverable after interruption.

================================================================
7. EXECUTION GATES
================================================================

Add these gates where applicable:

1. Preflight gate
    - plan binding;
    - repository safety;
    - dirty-file ownership;
    - dependencies;
    - task readiness.

2. Implementation-entry gate
    - root cause understood;
    - design selected;
    - paths authorized;
    - rollback defined.

3. Focused-verification gate
    - changed behavior tested;
    - negative controls run;
    - evidence captured.

4. Integration gate
    - producers and consumers aligned;
    - schemas and generated state synchronized;
    - related regressions pass.

5. Pre-commit gate
    - required tests green;
    - unrelated files excluded;
    - docs and state synchronized;
    - final diff reviewed.

6. Evidence gate
    - raw logs;
    - commands;
    - changed files;
    - task transitions;
    - artifacts;
    - limitations.

7. E2E gate
    - real input;
    - official entry point;
    - official output;
    - downstream consumer;
    - observed result.

8. Pilot gate
    - representative scenario;
    - negative control;
    - rerun or recovery proof.

9. Closeout gate
    - all requirements reconciled;
    - all mandatory taskcards closed;
    - no weakly verified work;
    - state agreement;
    - no eligible plan work remains.

10. Rerun/non-regression gate
    - clean rerun;
    - idempotency where applicable;
    - no stale-state regression;
    - no false PASS or false STOP.

================================================================
8. WEAK-AGENT GUARDS
================================================================

Add explicit instructions that prevent weak-agent failure modes.

The hardened plan must prohibit:

- skipping repository recon;
- trusting prior summaries;
- changing scope silently;
- working outside taskcards;
- editing forbidden paths;
- overwriting existing plans or state;
- closing tasks from implementation alone;
- treating test existence as test execution;
- treating exit code alone as proof;
- treating generated files as fresh without regeneration;
- treating local state as remote truth;
- treating synthetic tests as E2E proof;
- treating advisory checks as mandatory gates or mandatory failures as advisory;
- hiding failed commands;
- weakening tests;
- creating stubs or placeholders;
- claiming human blockers before agent-side investigation;
- stopping at iteration limits;
- creating a terminal “next sprint” or generic closeout task;
- switching to unrelated product hardening;
- inventing evidence;
- declaring success with unresolved mandatory gaps.

Require every agent to produce:

```yaml
agent_handoff:
task_id:
owner:
files_read: []
files_changed: []
commands_run: []
results: []
generated_outputs: []
assumptions_verified: []
unresolved_findings: []
evidence_paths: []
self_review_scores: {}
recommended_next_state:
```

Require self-review across:

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
- integration readiness;
- rollback;
- scope discipline.

Any applicable score below 4/5 requires rework.

Self-review is not final approval.

================================================================
9. EXECUTION MANAGEMENT
================================================================

Define one coordinator and bounded specialist lanes.

Each lane must specify:

```yaml
execution_lane:
lane_id:
objective:
owner_role:
task_ids: []
owned_paths: []
shared_paths: []
forbidden_paths: []
dependencies: []
outputs: []
verification:
handoff:
integration_order:
stop_conditions: []
```

Execution guards:

- one task has one active owner;
- one path has one mutation owner;
- shared files are integrated by the coordinator;
- agents may read broadly but mutate only authorized paths;
- overlap checks occur before dispatch and integration;
- blocked lanes do not stop safe independent work;
- the coordinator controls task selection, rerouting, and closeout;
- no agent creates a competing plan or supervisor.

================================================================
10. VERIFICATION AND PILOT DESIGN
================================================================

Every task must define exact commands, expected results, failure handling, and evidence.

Require all applicable:

- syntax and schema checks;
- lint and formatting;
- type checks;
- unit tests;
- integration tests;
- targeted regressions;
- broader affected-scope regressions;
- security checks;
- compatibility checks;
- performance checks;
- generated-output freshness;
- package build/install/runtime;
- clean-environment verification;
- downstream consumer proof;
- rerun and idempotency;
- recovery and rollback.

Define E2E proof as:

```text
REAL INPUT
→ OFFICIAL ENTRY POINT
→ IMPLEMENTATION
→ STATE OR ARTIFACT
→ VALIDATOR OR GATE
→ DOWNSTREAM CONSUMER
→ OBSERVED RESULT
```

Define representative pilots based on:

- highest production risk;
- primary plan outcome;
- critical integration boundary;
- negative path;
- previously failing behavior;
- rerun or recovery behavior.

================================================================
11. EVIDENCE CONTRACT
================================================================

Require an evidence package containing:

- run record;
- baseline git status;
- final git status;
- plan binding;
- hardened plan diff;
- gap register;
- root-cause records;
- solution designs;
- taskcard register;
- state transitions;
- gate results;
- command ledger;
- test and validation logs;
- changed-file manifest;
- generated outputs;
- E2E design;
- pilot design;
- independent review;
- final plan-readiness verdict.

Evidence must be truthful, machine-readable where supported, and sufficient for another agent to resume without chat memory.

================================================================
12. PLAN HARDENING COMPLETION
================================================================

Return:

`PLAN_HARDENED_EXECUTION_READY`

only when:

- the plan is bound to the correct mission;
- every requirement is normalized;
- every actionable item is taskcarded;
- dependencies and sequencing are explicit;
- the state machine and transition guards are defined;
- weak-agent guards are embedded;
- technical designs address root causes;
- execution lanes and path ownership are defined;
- all gates are defined;
- verification commands and expected results are explicit;
- E2E and pilot designs are complete;
- rollback and recovery are defined;
- evidence requirements are complete;
- no unresolved critical ambiguity remains;
- an adversarial review finds the plan executable by a weak agent.

If the plan cannot be made execution-ready because of missing external information, return:

`PLAN_HARDENING_BLOCKED_TRUE_EXTERNAL_DEPENDENCY`

Include the exact missing dependency and resume condition.

================================================================
13. REQUIRED OUTPUT
================================================================

Provide:

1. Plan binding and scope
2. Repository recon summary
3. Plan gap register
4. Root-cause findings
5. Production-grade solution designs
6. Hardened plan sections
7. Taskcard register
8. State-machine definition
9. Transition guards
10. Execution lanes and ownership
11. Weak-agent guardrail matrix
12. Verification matrix
13. E2E design
14. Pilot design
15. Evidence contract
16. Remaining external dependencies
17. Final verdict

Do not execute implementation work during this sprint unless explicitly authorized.

Do not merely recommend that the plan be hardened.

Modify or produce the actual execution-ready plan, taskcards, state model, gates, and handoff artifacts.

FINAL DIRECTIVE

Harden the current plan technically and operationally.

Normalize it into a taskcard-driven, gate-managed, machine-readable execution system that weak agents can follow without skipping work, drifting scope, hiding failures, or closing prematurely.

Stop only when the plan is genuinely execution-ready.
force_mode: clipboard

- trigger: ":normalize-plan-taskcards"
replace: |-
Harden the approved/current plan for reliable execution.

Perform repository recon, plan gap analysis, root-cause analysis, technical design hardening, taskcard normalization, state-machine normalization, gate design, verification design, weak-agent adversarial review, and plan repair.

Requirements:

- Bind the plan to the current mission.
- Verify every plan claim against repository truth.
- Preserve valid plan history and completed work.
- Convert every actionable requirement into a taskcard.
- Define legal state transitions and guards.
- Prohibit hidden work, scope drift, self-approval, false evidence, skipped verification, and premature closeout.
- Define one owner per task and one mutation owner per path.
- Add preflight, implementation, verification, integration, evidence, E2E, pilot, rerun, and closeout gates.
- Add exact commands, expected results, failure handling, rollback, recovery, and evidence requirements.
- Require self-review and independent review.
- Require E2E and representative pilot proof.
- Ensure a weak agent can execute the plan without interpreting ambiguous prose.

Do not execute product implementation unless explicitly instructed.

Return only when the plan, taskcards, state machine, gates, verification matrix, and execution handoff are complete and execution-ready.


================================================================
AUTONOMOUS LOOP OPERATION
(This section applies ONLY when running inside autonomous-green-loop.md.
If running this prompt standalone in a conversation, ignore this section.)
================================================================

CONTEXT ASSEMBLY:

Before applying hardening logic, the orchestrator will have read the plan file
and provided its contents as working context. Use that content directly —
it satisfies the PLAN DISCOVERY AND SCOPE LOCK requirement.

STRUCTURED OUTPUT:

After completing hardening, write to the run directory:

1. `gap-register.md` — every gap identified, with severity and root cause.
   Include a list of all taskcards the plan should contain.

2. Initialize `taskcard-registry.yaml` — populate with all taskcards extracted
   from the hardened plan:
   - Each with `status: OPEN, opened_iteration: 1, source: HARDEN`
   - Sharpen any vague acceptance criteria to testable conditions
   - Apply `loop-taskcard-contract.md` field requirements

3. Write `stage-1-harden-handoff.yaml`:
   ```yaml
   stage: HARDEN
   iteration: 1
   status: COMPLETE
   gap_count: <integer>
   taskcard_count: <integer>
   evidence_artifact: gap-register.md
   ```

4. Update `loop-state.yaml`: set `current_state: HARDENED`.

STOP SEMANTICS SUPPRESSION:

Do NOT stop at "EXECUTION-READY HANDOFF." The autonomous-green-loop.md
orchestrator will invoke execute-plan.md next. Your job is complete when
the handoff YAML and registry are written.
