EVIDENCE-BASED LAST-SPRINT ACHIEVEMENT REVIEW, PROOF-LEVEL CLASSIFICATION, OUTCOME IMPACT ASSESSMENT, AND DECISION-READY STATUS SUMMARY

Act as an independent sprint evidence reviewer.

Your task is to determine what was actually achieved during the last sprint and produce a sober, evidence-backed status assessment.

Do not repeat the sprint’s intended goals as though they were completed.

Do not trust summaries, task statuses, declarations, closeout reports, test counts, acceptance messages, or agent claims without verifying them against the underlying evidence.

The final assessment must clearly distinguish:

- what was planned;
- what was attempted;
- what changed;
- what was verified;
- what was consumed or exercised end to end;
- what remains partial;
- what failed;
- what remains unproven;
- what materially changed the likely final outcome.

----------------------------------------------------------------------
PRIMARY OBJECTIVE
----------------------------------------------------------------------

Provide an evidence-based answer to three questions:

1. What did the sprint actually achieve?
2. What do those results genuinely prove?
3. How do those results affect the final project outcome?

The answer must support decision-making.

It must not read like:

- a celebration note;
- a marketing update;
- a repetition of the sprint plan;
- an agent-generated closeout summary;
- a list of files without interpretation;
- a test-count report without behavioral meaning.

----------------------------------------------------------------------
CORE EVIDENCE RULE
----------------------------------------------------------------------

Treat current repository state and directly inspectable sprint evidence as the source of truth.

Evidence may include:

- changed source files;
- changed test files;
- Git diffs;
- commits;
- taskcards;
- taskcard transitions;
- commands;
- stdout and stderr;
- test logs;
- validator output;
- static-analysis output;
- build output;
- package artifacts;
- runtime results;
- generated artifacts;
- before-and-after comparisons;
- evidence declarations;
- evidence manifests;
- review reports;
- consumer traces;
- pilot outputs;
- state transitions;
- queue transitions;
- rollback results;
- current repository behavior.

Do not treat the following as sufficient proof on their own:

- a plan item marked complete;
- a TODO marked done;
- a taskcard marked CLOSED;
- an agent saying “implemented”;
- a reviewer saying “accepted”;
- an evidence path that was not inspected;
- a reported test count without logs;
- test files existing;
- source files existing;
- a zero exit code without understanding the command;
- a generated next-sprint file;
- a continuation flag;
- a declaration claiming success;
- a summary copied from another summary.

A claim is supported only when the evidence directly demonstrates it.

----------------------------------------------------------------------
REQUIRED INPUT DISCOVERY
----------------------------------------------------------------------

Determine the boundaries of the last sprint.

Identify, where available:

- sprint name or run ID;
- sprint plan;
- sprint start state;
- sprint end state;
- branch;
- baseline commit;
- final commit or current HEAD;
- taskcards included;
- declared scope;
- evidence root;
- changed files;
- test and validation commands;
- review package;
- closeout package;
- relevant queue or state changes.

Do not assume the latest file is the authoritative sprint record merely because of its timestamp.

Reconcile:

- plan;
- taskcards;
- Git history;
- repository state;
- evidence;
- runtime results.

If the sprint boundary is ambiguous:

- use the strongest evidence-supported boundary;
- state the ambiguity;
- avoid attributing unrelated work to the sprint.

----------------------------------------------------------------------
REQUIRED EVIDENCE REVIEW
----------------------------------------------------------------------

Inspect the available evidence in sufficient depth to determine what actually happened.

At minimum review, where present:

1. Sprint plan and intended scope
2. Baseline state
3. Changed source files
4. Changed tests
5. Generated artifacts
6. Taskcard states
7. Commands executed
8. Raw logs
9. Test results
10. Validator results
11. Static-analysis results
12. Build results
13. Package results
14. Runtime or consumer results
15. Pilot evidence
16. Review and rework evidence
17. Final repository state
18. Unresolved failures and warnings
19. Claims made in the sprint summary
20. Contradictions between claims and evidence

Do not stop after reading the final sprint report.

Verify important claims against primary artifacts.

----------------------------------------------------------------------
EVIDENCE HIERARCHY
----------------------------------------------------------------------

Prefer evidence in this order:

Level 1 — Direct behavioral proof

Examples:

- real end-to-end run;
- clean consumer workflow;
- verified source mutation;
- runtime behavior;
- successful load-edit-save-reload;
- downstream consumer acting on output;
- package installation and use;
- adversarial or negative control behaving correctly.

Level 2 — Direct implementation and validation proof

Examples:

- inspected code changes;
- focused tests passing;
- integration tests passing;
- validators passing;
- build succeeding;
- static analysis succeeding;
- generated artifacts inspected.

Level 3 — Structural or state evidence

Examples:

- taskcards created;
- schemas added;
- plans updated;
- queues generated;
- state transitioned;
- evidence packaged;
- prompts or skills created.

This proves infrastructure or preparation, not necessarily behavior.

Level 4 — Claims and intent

Examples:

- summaries;
- plans;
- status labels;
- declarations;
- projections;
- expected outcomes.

This is not achievement proof unless corroborated.

When sources conflict, prefer direct behavioral evidence over summaries and status labels.

----------------------------------------------------------------------
ACHIEVEMENT CLASSIFICATION
----------------------------------------------------------------------

Classify every material sprint item into exactly one primary category.

COMPLETED_AND_VERIFIED

Use only when:

- the required implementation or artifact exists;
- acceptance criteria were exercised;
- required verification passed;
- evidence was inspected;
- downstream or integration behavior was checked where required;
- no critical contradiction remains.

COMPLETED_IMPLEMENTATION_ONLY

Use when:

- the implementation exists;
- source changes are real;
- required broader verification is absent or incomplete.

PARTIALLY_COMPLETED

Use when:

- some required work exists;
- important sub-items, integrations, tests, or evidence remain incomplete;
- the intended outcome was not fully reached.

ATTEMPTED_BUT_NOT_ACCEPTABLE

Use when:

- work was attempted;
- artifacts or changes exist;
- the result failed validation, remained structurally weak, or did not reach production-ready quality.

VERIFIED_NEGATIVE_FINDING

Use when:

- the sprint conclusively disproved an assumption;
- revealed a real defect;
- found a missing consumer;
- exposed a false readiness claim;
- located a failing boundary.

A verified negative finding is legitimate progress, but it is not implementation completion.

UNVERIFIED_CLAIM

Use when:

- completion was claimed;
- direct evidence is missing, weak, stale, or contradictory.

NOT_STARTED_OR_NO_EVIDENCE

Use when:

- the item was planned;
- no meaningful implementation or evidence was found.

OUT_OF_SCOPE_OR_DEFERRED

Use when:

- the sprint explicitly and legitimately deferred the item;
- the reason and future handling are recorded.

BLOCKED

Use when:

- a real blocker prevented completion;
- attempts and evidence are documented.

Do not classify ordinary incomplete work as blocked merely because the sprint ended.

----------------------------------------------------------------------
PROOF-LEVEL CLASSIFICATION
----------------------------------------------------------------------

For each important result, assign exactly one proof level.

PROOF_LEVEL_0 — NO_PROOF

- intent, claim, plan, or status only;
- no direct supporting evidence.

PROOF_LEVEL_1 — ARTIFACT_OR_IMPLEMENTATION_EXISTS

- code, configuration, taskcard, schema, prompt, or generated artifact exists;
- behavior has not been adequately verified.

PROOF_LEVEL_2 — FOCUSED_VALIDATION

- focused unit tests, validators, or static checks passed;
- broader integration remains unproven.

PROOF_LEVEL_3 — INTEGRATION_VALIDATION

- relevant components worked together;
- integration behavior was demonstrated;
- complete consumer or mission path remains unproven.

PROOF_LEVEL_4 — END_TO_END_PROOF

- the full intended path was exercised successfully;
- required consumers acted;
- evidence supports the result from input through final output.

PROOF_LEVEL_5 — PRODUCTION_SHAPED_OR_PRODUCTION_PROOF

- clean installation or deployment-shaped use;
- real consumer behavior;
- negative controls;
- regression checks;
- rerun or idempotency where applicable;
- no critical unresolved readiness gaps for the proven scope.

Do not label fixture-only validation as production proof.

Do not label a passing unit test as end-to-end proof.

----------------------------------------------------------------------
DISTINGUISH CODE, BEHAVIOR, AND ASSUMPTION
----------------------------------------------------------------------

Every material conclusion must distinguish among:

CODE_OR_ARTIFACT_CHANGE

What changed in:

- source;
- tests;
- configuration;
- schemas;
- prompts;
- taskcards;
- plans;
- generated artifacts;
- packaging.

VERIFIED_BEHAVIOR

What was directly shown to work through:

- tests;
- runtime;
- consumer flow;
- integration;
- negative controls;
- state transitions;
- downstream consumption.

ASSUMPTION_OR_INFERENCE

What appears likely but was not directly proven.

Clearly label inference.

Do not use implementation existence as shorthand for verified behavior.

----------------------------------------------------------------------
CONTRADICTION HANDLING
----------------------------------------------------------------------

Identify contradictions such as:

- summary says complete but taskcard remains open;
- taskcard says CLOSED but tests failed;
- tests reported as passing but logs are missing;
- evidence manifest lists artifacts that do not exist;
- source changed outside declared scope;
- package claimed but no package artifact exists;
- end-to-end proof claimed from unit tests;
- consumer readiness claimed without clean consumer execution;
- capability marked closed but required gap remains;
- automation marked successful but output had no consumer;
- evidence package says accepted while repository state remains broken.

For each material contradiction:

- state the conflicting claims;
- identify the stronger evidence;
- explain the resulting classification;
- do not average contradictory evidence into a vague conclusion.

----------------------------------------------------------------------
QUANTITATIVE RECONCILIATION
----------------------------------------------------------------------

When the sprint reports counts, reconcile them where possible.

Examples:

- files changed;
- source files added;
- test files added;
- tests added;
- tests passed;
- validators passed;
- taskcards closed;
- products affected;
- capabilities added;
- facts processed;
- packages built;
- consumer scenarios completed;
- failures remaining.

For each important count, distinguish:

- reported;
- independently confirmed;
- partially confirmed;
- contradicted;
- not verifiable.

Do not repeat large counts merely because they appear impressive.

Explain what the count actually proves.

Examples:

- “2,000 tests passed” may prove regression safety for covered behavior, but not that the new feature is complete.
- “20 files added” proves source growth, not architectural quality.
- “10 taskcards closed” proves state updates only if closure evidence is valid.
- “40 capability records generated” does not prove downstream consumption.

----------------------------------------------------------------------
AREA 1 — WHAT WE ACHIEVED
----------------------------------------------------------------------

List concrete, evidence-supported sprint outputs.

Organize them into:

A. Fully completed and verified

Include only items meeting COMPLETED_AND_VERIFIED.

For each item state:

- what changed;
- what evidence proves it;
- proof level;
- affected scope;
- important limitations.

B. Implemented but not fully verified

Include items where:

- code or artifacts exist;
- broader validation remains incomplete.

State exactly what is still missing.

C. Partially completed

Include items where:

- only part of the intended result exists;
- dependencies, consumers, tests, integration, or evidence remain missing.

D. Attempted but not production-ready

Include:

- failed approaches;
- structurally weak implementation;
- incomplete pilots;
- non-idempotent generation;
- fixture-only success;
- code that passes limited tests but remains unusable;
- evidence that does not support readiness.

E. Verified negative findings

Include important defects, false assumptions, missing consumers, architecture problems, or unsafe behavior conclusively identified.

F. Unresolved or unverified work

Include:

- planned items without evidence;
- claims not independently proven;
- open taskcards;
- failed checks;
- missing evidence;
- unresolved contradictions.

Avoid vague statements such as:

- “made good progress”;
- “substantially completed”;
- “mostly done”;
- “improved significantly”;

unless immediately quantified and evidenced.

----------------------------------------------------------------------
AREA 2 — WHAT THIS PROVES
----------------------------------------------------------------------

Explain what the sprint results genuinely demonstrate.

Separate conclusions by proof level.

A. Proven end to end

State only conclusions supported by a complete input-to-consumer path.

B. Proven at integration level

State conclusions supported by component interaction but not full final use.

C. Proven at focused validation level

State what unit tests, validators, source inspection, or static analysis demonstrate.

D. Implementation exists but behavioral proof is incomplete

State what code or machinery now exists without overstating functionality.

E. No proof yet

State important conclusions that remain assumptions.

For every conclusion answer:

- What evidence supports it?
- What proof level applies?
- What scope does the conclusion cover?
- What does it not prove?
- Can it be generalized beyond the pilot?
- Is the result fixture-only, isolated, production-shaped, or production-proven?

Explicitly identify:

- supported conclusions;
- unsupported conclusions;
- disproven assumptions;
- conclusions narrowed by evidence;
- conclusions that require another sprint.

----------------------------------------------------------------------
AREA 3 — EFFECT ON THE FINAL OUTCOME
----------------------------------------------------------------------

Explain how the sprint changes the likely final project outcome.

Assess the effect across:

1. Final-goal proximity

   Did the sprint produce real product or system capability that is part of the final outcome?

   Or did it mainly:

   - improve planning;
   - improve governance;
   - improve diagnostics;
   - expose defects;
   - prepare infrastructure;
   - produce evidence?

2. Risk reduction

   State which risks were reduced and why.

   Examples:

   - unknown architecture became explicit;
   - failing boundary was located;
   - package path was proven;
   - test coverage increased;
   - consumer flow was demonstrated;
   - stale claims were removed.

3. Risk discovery

   State new or deeper risks uncovered.

   A sprint may reduce uncertainty while revealing that the final outcome is farther away than previously believed.

4. Confidence change

   State whether confidence:

   - increased;
   - decreased;
   - became more precise;
   - remained unchanged.

   Explain which parts changed.

5. Execution-path change

   State whether the sprint changed:

   - implementation order;
   - architecture;
   - dependencies;
   - required gates;
   - product priorities;
   - required pilots;
   - plan assumptions;
   - scope.

6. Material progress toward the final goal

   State exactly how the sprint moved the project closer.

   Distinguish:

   - direct product progress;
   - machinery progress;
   - diagnostic progress;
   - governance progress;
   - evidence progress;
   - documentation progress.

   Do not describe governance-only or evidence-only work as direct product completion.

7. Remaining blockers

   State what still blocks the final outcome.

   Distinguish:

   - technical blockers;
   - architecture blockers;
   - missing authority;
   - missing implementation;
   - missing validation;
   - missing consumer proof;
   - missing packaging;
   - external blockers;
   - ordinary unfinished work.

----------------------------------------------------------------------
MATERIALITY ASSESSMENT
----------------------------------------------------------------------

Classify the sprint’s overall effect using exactly one primary assessment:

MATERIAL_FINAL_OUTCOME_PROGRESS

Use when the sprint delivered verified functionality or system capability directly required by the final goal.

MATERIAL_RISK_REDUCTION

Use when it did not complete final functionality but removed major uncertainty or proved critical machinery.

MATERIAL_PROBLEM_DISCOVERY

Use when it conclusively exposed deeper defects that change planning or readiness.

PREPARATORY_PROGRESS

Use when it mainly created plans, taskcards, schemas, infrastructure, prompts, or evidence foundations.

LIMITED_PROGRESS

Use when only a small portion of intended value was verified.

NO_MATERIAL_PROGRESS

Use when outputs were mostly claims, duplicated artifacts, governance churn, or unconsumed work.

REGRESSION_OR_INCREASED_RISK

Use when the sprint introduced breakage, misleading state, unsafe machinery, or reduced readiness.

More than one secondary effect may also be noted.

----------------------------------------------------------------------
FINAL OUTCOME CONFIDENCE
----------------------------------------------------------------------

Assess confidence in the final outcome using:

- HIGHER_WITH_DIRECT_PROOF
- HIGHER_BUT_LIMITED_TO_PILOT_SCOPE
- MORE_PRECISE_BUT_NOT_HIGHER
- UNCHANGED
- LOWER_DUE_TO_NEWLY_CONFIRMED_GAPS
- LOWER_DUE_TO_REGRESSION
- INSUFFICIENT_EVIDENCE_TO_ASSESS

Explain the reason.

Do not assign numerical percentages unless the project has a defensible measurement model.

----------------------------------------------------------------------
REQUIRED OUTPUT STRUCTURE
----------------------------------------------------------------------

Use the following structure.

# Last Sprint: Evidence-Based Achievement Assessment

## Executive assessment

Provide a compact paragraph stating:

- overall materiality classification;
- strongest verified achievement;
- most important limitation;
- effect on final-outcome confidence;
- whether the project is materially closer to the final goal.

## Evidence basis and sprint boundary

State:

- sprint/run reviewed;
- plan or taskcards reviewed;
- repository range or baseline;
- evidence root;
- primary evidence inspected;
- important evidence missing;
- boundary uncertainty.

## 1. What we achieved

### Fully completed and verified

For each item use:

**Achievement:**
**What changed:**
**Direct evidence:**
**Proof level:**
**Scope:**
**Limitations:**

### Implemented but not fully verified

Use the same fields and state missing proof.

### Partially completed

State completed portion and remaining portion.

### Attempted but not production-ready

State what was attempted, why it is insufficient, and current disposition.

### Verified negative findings

State what was disproved or uncovered and why it matters.

### Unresolved or unverified work

State missing implementation, evidence, validation, integration, or authority.

## 2. What this proves

### End-to-end conclusions

### Integration-level conclusions

### Focused-validation conclusions

### Implementation-only conclusions

### Conclusions that remain unproven

For each conclusion state:

- evidence;
- proof level;
- applicable scope;
- explicit non-claims.

## 3. Effect on the final outcome

### Material progress

State direct contribution to the final goal.

### Risk reduction

State risks reduced.

### New or deeper risks uncovered

State risks confirmed or newly discovered.

### Execution-path changes

State changes to order, architecture, gates, priorities, or scope.

### Remaining blockers and unfinished work

Separate:

- true blockers;
- unresolved technical work;
- missing proof;
- external dependencies.

### Final-outcome confidence

State the confidence classification and rationale.

## Proof and status matrix

Provide a compact matrix with:

| Sprint item | Planned outcome | Actual result | Achievement status | Proof level | Evidence | Remaining gap |
|-------------|-----------------|---------------|--------------------|-------------|----------|---------------|

## Claims that should not be repeated

List any prior sprint claims that are:

- exaggerated;
- unsupported;
- outdated;
- contradicted;
- too broad for the evidence.

Provide corrected wording for each important claim.

## Decision implications

State:

- what may safely proceed;
- what must remain gated;
- what requires rework;
- what requires further evidence;
- what should be deprioritized or removed;
- the most important next decision.

## Final verdict

Use exactly one:

- `SPRINT_VERIFIED — MATERIAL_FINAL_OUTCOME_PROGRESS`
- `SPRINT_VERIFIED — MATERIAL_RISK_REDUCTION`
- `SPRINT_VERIFIED — MATERIAL_PROBLEM_DISCOVERY`
- `SPRINT_PARTIALLY_VERIFIED — PREPARATORY_PROGRESS`
- `SPRINT_PARTIALLY_VERIFIED — LIMITED_PROGRESS`
- `SPRINT_UNVERIFIED — EVIDENCE_INSUFFICIENT`
- `SPRINT_NO_MATERIAL_PROGRESS`
- `SPRINT_REGRESSION_OR_INCREASED_RISK`

Then state:

- strongest proven result;
- highest proof level reached;
- most important unresolved gap;
- whether the sprint materially advanced the final outcome;
- exact reason for the verdict.

----------------------------------------------------------------------
WRITING STYLE
----------------------------------------------------------------------

Write in a direct, sober, review-ready tone.

Prefer:

- exact nouns and verbs;
- concrete results;
- explicit evidence;
- bounded conclusions;
- clear limitations;
- clear uncertainty;
- decision relevance.

Avoid:

- celebratory language;
- promotional framing;
- motivational wording;
- vague praise;
- inflated adjectives;
- unqualified statements such as complete, robust, production-ready, autonomous, comprehensive, or resolved;
- repeating the sprint plan as the result;
- presenting effort as achievement;
- presenting artifact creation as consumer proof;
- hiding failed or partial work in footnotes.

Use statements such as:

- “The code exists, but end-to-end behavior was not demonstrated.”
- “Focused tests passed; package-level consumer proof remains absent.”
- “The sprint disproved the prior assumption that the queue was consumed.”
- “This reduced uncertainty but did not complete the product capability.”
- “The change is verified for the pilot only and should not be generalized.”
- “The evidence does not support the production-readiness claim.”
- “This was preparatory machinery work rather than direct product progress.”

----------------------------------------------------------------------
FINAL SELF-CHECK
----------------------------------------------------------------------

Before returning the assessment, verify:

- sprint intent was not reported as achievement;
- every important achievement has direct evidence;
- code changes are distinguished from verified behavior;
- assumptions are labelled;
- completed, partial, attempted, failed, and unverified work are separated;
- test counts are interpreted rather than merely repeated;
- fixture proof is distinguished from production proof;
- negative findings are recognized without being misrepresented as completed implementation;
- limitations and uncertainty are explicit;
- remaining gaps are not hidden;
- effect on the final outcome is clearly explained;
- the final verdict matches the evidence;
- the summary is suitable for technical and management decision-making.

Final instruction:

Report only what the evidence proves.

Do not turn intent, effort, generated artifacts, status labels, or reported counts into achievements without verification.

State clearly what changed, what worked, what did not work, what remains unproven, and how the sprint materially affects the final outcome.


================================================================
AUTONOMOUS LOOP OPERATION
(This section applies ONLY when running inside autonomous-green-loop.md.
If running this prompt standalone in a conversation, ignore this section.)
================================================================

SELF-AUDIT LIMITATION:

You are auditing the work of the same agent session that executed the plan.
This is a structural authority conflict that cannot be fully eliminated in a
single-agent system. The "Act as an independent sprint evidence reviewer"
instruction above is the primary mitigation.

Apply it with maximum strictness:
- Read the actual files, not your memory of what you wrote
- Do not accept any finding as ACCEPTED without a concrete file/test artifact
- Do not classify a BLOCKING_GAP as NON_BLOCKING_WARN to avoid another iteration
- Err toward UNVERIFIED when evidence is ambiguous

CONTEXT ASSEMBLY:

Before auditing, the orchestrator will have provided:
- Contents of `changed-files-iter<N>.txt`
- Contents of `stage-<N>-execute-handoff.yaml`
Read these and the actual changed files directly. Use them as your evidence input.

STRUCTURED OUTPUT:

After completing the audit, write to the run directory:

1. `audit-report-iter<N>.md` — full audit findings with:
   - Taskcards reviewed (list with status)
   - Evidence reviewed (specific files/outputs read)
   - Findings (each with classification from loop-audit-contract.md)
   - Blocking gaps count (explicit integer)
   - Audit verdict
   - Self-audit caveat statement

2. `stage-<N>-audit-handoff.yaml`:
   ```yaml
   stage: AUDIT
   iteration: <N>
   status: COMPLETE
   audit_verdict: <verdict>
   blocking_gaps: <integer>
   next_action: <GREEN_STOP|EXPAND|BLOCKED_EXTERNAL>
   evidence_artifact: audit-report-iter<N>.md
   ```

3. `loop-signal.yaml` — the machine-readable stop signal:
   ```yaml
   run_id: <RUN_ID>
   plan_path: <PLAN_PATH>
   iteration: <N>
   state: AUDIT_COMPLETE
   audit_verdict: <verdict>
   blocking_gaps: <integer>
   next_action: <GREEN_STOP|EXPAND|BLOCKED_EXTERNAL>
   blocker_description: ""
   max_iterations: 5
   iterations_remaining: <from loop-state.yaml>
   updated_at: <ISO-8601 now>
   ```

   Determination rules for next_action:
   - 0 blocking gaps AND all taskcard-registry.yaml entries are CLOSED → GREEN_STOP
   - > 0 blocking gaps AND iterations_remaining > 0 → EXPAND
   - > 0 blocking gaps AND iterations_remaining <= 0 → MAX_ITER_REACHED (write to
     next_action field; orchestrator handles the stop)
   - Genuine external blocker → BLOCKED_EXTERNAL

STOP SEMANTICS SUPPRESSION:

Do NOT stop after writing the audit report. The orchestrator reads
`loop-signal.yaml.next_action` to determine the next stage. Your job is
complete when the audit report, handoff YAML, and loop-signal.yaml are written.
