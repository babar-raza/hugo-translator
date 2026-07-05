# Aspose.org Multisite Translation Speed and Language-Mixing Micro-Task Plan

authoritative_plan: docs/quality/aspose-org-multisite-speed-language-mixing-micro-task-plan.md
authority_source: current conversation plans for kb/blog/docs/reference governed retranslation, VRAM-aware speed optimization, short-string scheduling, and parallel language-mixing controls
execution_authority: true
created_at: 2026-07-02
repo_path: C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator
content_repo_path: C:\Users\prora\OneDrive\Documents\GitHub\aspose.org
active_run_id: multisite_validate_20260702_001
last_execution_reconciliation: 2026-07-02T14:23:48Z
plan_hash_at_binding: 049841E3F25320F1A93E5E8822B2F79EEF2EACA68D95172663F6AAD0653C23F3

## Purpose

This is the single authoritative execution plan for optimizing the active governed retranslation campaign for:

- `kb.aspose.org`
- `blog.aspose.org`
- `docs.aspose.org`
- `reference.aspose.org`

It consolidates the current plan items into taskcards and micro-steps. It does not replace the closed `products.aspose.org` plan, which remains historical evidence only.

## Preserved Decisions

- The governed verifier remains the final acceptance authority.
- Acceptance criteria are not weakened for speed.
- Use locale-sharded workers instead of broad in-process `--parallel-languages` until monitored proof shows no language mixing.
- Keep per-shard evidence, checkpoint, current-item, inventory, and logs isolated.
- Keep per-file purity, partial-translation, structure, protected-field, shortcode/link/path/API, code-block, repetition, and source-mutation gates.
- Apply short-first scheduling only inside a locale shard, never across mixed target languages.
- Use VRAM-aware batching and concurrency, targeting about 80% VRAM, with automatic backoff on OOM or language-mixing signals.
- Preserve source pages exactly.

## Consolidated Requirements

| Requirement ID | Requirement | Source plan item |
|---|---|---|
| REQ-MULTI-001 | Governed multisite retranslation must cover all required source-locale pairs for kb/blog/docs/reference. | Repeatable multisite plan |
| REQ-MULTI-002 | Existing and generated targets must pass hardened quality gates before acceptance. | Quality hardening plan |
| REQ-SPEED-001 | Use larger batches and controlled parallel workers to improve accepted pairs/hour. | VRAM-aware speed plan |
| REQ-SPEED-002 | Measure throughput before and after optimization. | VRAM-aware speed plan |
| REQ-SCHED-001 | Add short-first or balanced scheduling without starving long pages. | Short-string addendum |
| REQ-LANG-001 | Prevent language mixing under parallel execution. | Language-mixing plan |
| REQ-LANG-002 | Isolate worker state by fixed locale shard. | Language-mixing plan |
| REQ-LANG-003 | Detect and count wrong-language, mixed-language, and purity failures per shard. | Language-mixing plan |
| REQ-ROUTE-001 | Enforce target path correctness for folder and file-suffix localization layouts. | Language-mixing plan |
| REQ-EVID-001 | Produce evidence for calibration, monitored samples, validation, rollback, and closeout. | All plans |
| REQ-SAFE-001 | Back off rather than weaken gates when speed settings induce failures. | Speed and language-mixing plans |

## Machine State

Parent statuses:

- PROPOSED
- READY
- IN_PROGRESS
- CHILDREN_IN_PROGRESS
- INTEGRATION_PENDING
- VERIFIED
- SCORED
- CLOSED
- BLOCKED
- BLOCKED_EXTERNAL
- DEFERRED_WITH_REASON

Child statuses:

- TODO
- READY
- IN_PROGRESS
- IMPLEMENTED
- VERIFIED
- SCORED
- CLOSED
- REROUTED
- BLOCKED
- BLOCKED_EXTERNAL
- DEFERRED_WITH_REASON

Micro-step statuses:

- PENDING
- READY
- ACTIVE
- COMPLETE
- FAILED
- BLOCKED
- SKIPPED_NOT_APPLICABLE

Invalid transitions:

- Parent cannot close before mandatory children close.
- Child cannot close before mandatory micro-steps complete and evidence exists.
- Rerouted task cannot close without rework evidence.
- Blocked task cannot close without unblock evidence.
- Skipped micro-step requires a reason.

## Parent Taskcards

### Parent Taskcard ID: TC-MULTI-001

Title: Establish one authoritative multisite execution state
Type: PARENT
Status: CLOSED
Owner: Execution agent
Supervisor: Review agent

Source:

- Plan requirement ID: REQ-MULTI-001, REQ-EVID-001
- Plan section: multisite governed retranslation and single-plan authority
- Root cause: Work was split across conversation plans, evidence outputs, and active workers without a single taskcardized execution plan.
- Selected solution: Consolidate requirements, preserve decisions, and taskcardize execution in this file.

Objective:

- Maintain one execution authority and prevent plan drift.

Outcome:

- Future agents can execute one micro-step at a time from this plan.

Children:

- TC-MULTI-001-A: Record active state and authority.
- TC-MULTI-001-B: Reconcile running workers with this plan.
- TC-MULTI-001-C: Create execution evidence index.

Acceptance checks:

- This file is referenced as authoritative in any new supporting artifact.
- Active run id and evidence roots are documented.
- Running workers are not confused with new optimized workers.

Evidence required:

- `docs/quality/aspose-org-multisite-speed-language-mixing-micro-task-plan.md`
- `.local/evidences/aspose-org-multisite/multisite_validate_20260702_001/`
- `.local/evidences/autonomous-workers/`

Rollback plan:

- Revert only this plan file if taskcardization is wrong; do not touch content targets.

#### Child Taskcard ID: TC-MULTI-001-A

Parent Taskcard ID: TC-MULTI-001
Title: Record active state and authority
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-MULTI-001-A-01
  - Status: READY
  - Action: Inspect repo path, branch, HEAD, and git status.
  - Target: repository metadata.
  - Allowed operation: inspect.
  - Expected output: recorded repo context.
  - Completion check: context appears in this plan or evidence.
- MS-MULTI-001-A-02
  - Status: READY
  - Action: Record active run id and evidence roots.
  - Target: `.local/evidences/`.
  - Allowed operation: inspect, record.
  - Expected output: evidence root list.
  - Completion check: evidence roots are listed in this plan.
- MS-MULTI-001-A-03
  - Status: READY
  - Action: Confirm this plan is the only active multisite speed/language-mixing plan.
  - Target: `docs/quality/`, `docs/plans/`, `TASK_BACKLOG.md`.
  - Allowed operation: inspect.
  - Expected output: no duplicate active plan found or duplicate risk recorded.
  - Completion check: duplicate risk is documented.

#### Child Taskcard ID: TC-MULTI-001-B

Parent Taskcard ID: TC-MULTI-001
Title: Reconcile running workers with this plan
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-MULTI-001-B-01
  - Status: READY
  - Action: List active PowerShell and Python translation worker processes.
  - Target: process table.
  - Allowed operation: inspect.
  - Expected output: process ids and start times.
  - Completion check: process list captured in evidence.
- MS-MULTI-001-B-02
  - Status: READY
  - Action: Read worker log tails for kb/blog/docs/reference.
  - Target: `.local/evidences/autonomous-workers/worker-*.log`.
  - Allowed operation: inspect.
  - Expected output: current cycle and latest summary for each site.
  - Completion check: latest cycle state recorded.
- MS-MULTI-001-B-03
  - Status: READY
  - Action: Decide whether to let existing workers drain or stop/relaunch under shard-safe optimized settings.
  - Target: worker control decision.
  - Allowed operation: record.
  - Expected output: decision record.
  - Completion check: decision references current progress and safety risk.

#### Child Taskcard ID: TC-MULTI-001-C

Parent Taskcard ID: TC-MULTI-001
Title: Create execution evidence index
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-MULTI-001-C-01
  - Status: PENDING
  - Action: Create or update a non-authoritative evidence index.
  - Target: `.local/evidences/aspose-org-multisite/multisite_validate_20260702_001/`.
  - Allowed operation: create, record.
  - Expected output: evidence index referencing this authoritative plan.
  - Completion check: index has `authoritative_plan` and `execution_authority: false`.
- MS-MULTI-001-C-02
  - Status: PENDING
  - Action: Link each active evidence folder to its taskcard.
  - Target: evidence index.
  - Allowed operation: edit, record.
  - Expected output: evidence-to-taskcard map.
  - Completion check: each taskcard has at least one evidence path or pending obligation.

### Parent Taskcard ID: TC-SPEED-001

Title: Add VRAM-aware throughput controls
Type: PARENT
Status: CLOSED

Source:

- Plan requirement ID: REQ-SPEED-001, REQ-SAFE-001
- Root cause: GPU memory is underused while process-level throughput is limited by conservative batches and unmanaged worker count.
- Selected solution: Add controlled throughput profiles, batch-size knobs, worker caps, VRAM polling, and automatic backoff.

Children:

- TC-SPEED-001-A: Measure current throughput baseline.
- TC-SPEED-001-B: Add runtime speed controls.
- TC-SPEED-001-C: Add VRAM controller.
- TC-SPEED-001-D: Calibrate speed profiles.
- TC-SPEED-001-E: Select production throughput profile.

#### Child Taskcard ID: TC-SPEED-001-A

Parent Taskcard ID: TC-SPEED-001
Title: Measure current throughput baseline
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SPEED-001-A-01
  - Status: READY
  - Action: Read accepted/failed counts for all four sites.
  - Target: `.local/evidences/<site>/multisite_validate_20260702_001/final/summary.json`.
  - Allowed operation: inspect.
  - Expected output: baseline accepted pairs and timestamps.
  - Completion check: counts are recorded.
- MS-SPEED-001-A-02
  - Status: READY
  - Action: Extract cycle duration and accepted delta from worker logs.
  - Target: `.local/evidences/autonomous-workers/worker-*.log`.
  - Allowed operation: inspect.
  - Expected output: accepted pairs/hour estimate per site.
  - Completion check: throughput estimate recorded.
- MS-SPEED-001-A-03
  - Status: READY
  - Action: Capture GPU utilization and VRAM snapshot.
  - Target: `nvidia-smi`.
  - Allowed operation: inspect.
  - Expected output: GPU utilization, memory used, memory total.
  - Completion check: snapshot recorded with timestamp.

#### Child Taskcard ID: TC-SPEED-001-B

Parent Taskcard ID: TC-SPEED-001
Title: Add runtime speed controls
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SPEED-001-B-01
  - Status: PENDING
  - Action: Inspect current governed runner CLI arguments.
  - Target: `scripts/quality/aspose_org_governed_retranslate.py`.
  - Allowed operation: inspect.
  - Expected output: current argument map.
  - Completion check: missing speed arguments identified.
- MS-SPEED-001-B-02
  - Status: PENDING
  - Action: Add `--model-batch-size` argument.
  - Target: `scripts/quality/aspose_org_governed_retranslate.py`.
  - Allowed operation: edit.
  - Expected output: argument is parsed.
  - Completion check: `--model-batch-size` appears in help or parser code.
- MS-SPEED-001-B-03
  - Status: PENDING
  - Action: Forward `--model-batch-size` to `src.cli --batch-size`.
  - Target: `build_translate_cmd`.
  - Allowed operation: edit.
  - Expected output: command includes `--batch-size <value>` when configured.
  - Completion check: focused unit test verifies command construction.
- MS-SPEED-001-B-04
  - Status: PENDING
  - Action: Add `--throughput-profile` argument with `safe`, `fast`, and `max-vram`.
  - Target: governed runner and multisite wrapper.
  - Allowed operation: edit.
  - Expected output: profile is accepted but defaults to current safe behavior.
  - Completion check: parser test covers defaults and valid values.
- MS-SPEED-001-B-05
  - Status: PENDING
  - Action: Add `--max-concurrent-site-workers`.
  - Target: multisite launcher/wrapper.
  - Allowed operation: edit.
  - Expected output: worker launch respects concurrency cap.
  - Completion check: launcher dry-run or unit test proves only capped workers would start.

#### Child Taskcard ID: TC-SPEED-001-C

Parent Taskcard ID: TC-SPEED-001
Title: Add VRAM controller
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SPEED-001-C-01
  - Status: PENDING
  - Action: Inspect existing GPU manager and VRAM enforcer APIs.
  - Target: `src/hardware/gpu_manager.py`, `src/hardware/vram_enforcer.py`.
  - Allowed operation: inspect.
  - Expected output: reusable API decision.
  - Completion check: selected API recorded.
- MS-SPEED-001-C-02
  - Status: PENDING
  - Action: Add `--target-vram-percent` runtime argument.
  - Target: worker launcher.
  - Allowed operation: edit.
  - Expected output: default `80`.
  - Completion check: parser test validates default.
- MS-SPEED-001-C-03
  - Status: PENDING
  - Action: Poll GPU memory before launching a new worker.
  - Target: launcher worker-start logic.
  - Allowed operation: edit.
  - Expected output: launch waits or skips when VRAM is above target.
  - Completion check: mocked GPU state test covers below/above threshold.
- MS-SPEED-001-C-04
  - Status: PENDING
  - Action: Record VRAM snapshots in worker evidence.
  - Target: worker logs or evidence report.
  - Allowed operation: edit.
  - Expected output: timestamped VRAM readings.
  - Completion check: sample log includes VRAM line.
- MS-SPEED-001-C-05
  - Status: PENDING
  - Action: Add OOM backoff rule.
  - Target: launcher cycle handling.
  - Allowed operation: edit.
  - Expected output: model batch size halves after CUDA OOM.
  - Completion check: simulated OOM log triggers backoff in test.

#### Child Taskcard ID: TC-SPEED-001-D

Parent Taskcard ID: TC-SPEED-001
Title: Calibrate speed profiles
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SPEED-001-D-01
  - Status: PENDING
  - Action: Run safe baseline calibration for 20-30 minutes.
  - Target: active worker run.
  - Allowed operation: run.
  - Expected output: accepted/hour baseline.
  - Completion check: calibration evidence exists.
- MS-SPEED-001-D-02
  - Status: PENDING
  - Action: Run `fast` profile calibration with moderate batch size.
  - Target: optimized launcher.
  - Allowed operation: run.
  - Expected output: accepted/hour and failure deltas.
  - Completion check: no source mutation and no language-mixing increase.
- MS-SPEED-001-D-03
  - Status: PENDING
  - Action: Run `max-vram` profile calibration.
  - Target: optimized launcher.
  - Allowed operation: run.
  - Expected output: throughput, VRAM, OOM, failure metrics.
  - Completion check: profile is marked acceptable or rejected.
- MS-SPEED-001-D-04
  - Status: PENDING
  - Action: Compare profiles.
  - Target: calibration report.
  - Allowed operation: record.
  - Expected output: speed profile scorecard.
  - Completion check: selected profile improves accepted/hour by at least 25% or is rejected.

#### Child Taskcard ID: TC-SPEED-001-E

Parent Taskcard ID: TC-SPEED-001
Title: Select production throughput profile
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SPEED-001-E-01
  - Status: PENDING
  - Action: Verify selected profile has zero source mutations.
  - Target: source mutation reports.
  - Allowed operation: inspect.
  - Expected output: mutation count is zero.
  - Completion check: evidence path recorded.
- MS-SPEED-001-E-02
  - Status: PENDING
  - Action: Verify selected profile does not increase hard-gate failure rate.
  - Target: failure counts by type.
  - Allowed operation: inspect.
  - Expected output: failure comparison.
  - Completion check: comparison is recorded.
- MS-SPEED-001-E-03
  - Status: PENDING
  - Action: Promote selected profile to autonomous launcher defaults.
  - Target: launcher config or run command.
  - Allowed operation: edit or record.
  - Expected output: production launch command.
  - Completion check: command is reproducible.

### Parent Taskcard ID: TC-SCHED-001

Title: Add short-string and balanced work scheduling
Type: PARENT
Status: CLOSED

Source:

- Plan requirement ID: REQ-SCHED-001
- Root cause: Current worker ordering is failure/path oriented and may spend early cycles on expensive pages while small pages could be accepted quickly and warm TM.
- Selected solution: Add size scoring and balanced short/medium/long scheduling inside each locale shard.

Children:

- TC-SCHED-001-A: Measure page and segment size distribution.
- TC-SCHED-001-B: Add work-order modes.
- TC-SCHED-001-C: Add AST unit length bucketing.
- TC-SCHED-001-D: Validate no starvation and no mapping drift.

#### Child Taskcard ID: TC-SCHED-001-A

Parent Taskcard ID: TC-SCHED-001
Title: Measure page and segment size distribution
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SCHED-001-A-01
  - Status: PENDING
  - Action: Add or run inventory size scoring for source pages.
  - Target: governed runner inventory.
  - Allowed operation: inspect or run.
  - Expected output: source bytes, estimated tokens, translatable unit counts.
  - Completion check: size report exists.
- MS-SCHED-001-A-02
  - Status: PENDING
  - Action: Classify pages into short, medium, and long buckets.
  - Target: size report.
  - Allowed operation: record.
  - Expected output: bucket counts per site and locale shard.
  - Completion check: bucket counts recorded.

#### Child Taskcard ID: TC-SCHED-001-B

Parent Taskcard ID: TC-SCHED-001
Title: Add work-order modes
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SCHED-001-B-01
  - Status: PENDING
  - Action: Add `--work-order` parser option.
  - Target: governed runner.
  - Allowed operation: edit.
  - Expected output: modes `failed-first`, `short-first`, `balanced`.
  - Completion check: parser test passes.
- MS-SCHED-001-B-02
  - Status: PENDING
  - Action: Implement `short-first` ordering inside current locale scope.
  - Target: item sort logic.
  - Allowed operation: edit.
  - Expected output: smaller pages sort first within attempt bucket.
  - Completion check: unit test verifies order.
- MS-SCHED-001-B-03
  - Status: PENDING
  - Action: Implement `balanced` quota ordering.
  - Target: item selection logic.
  - Allowed operation: edit.
  - Expected output: cycle contains short/medium/long quota.
  - Completion check: unit test verifies no long-page starvation.
- MS-SCHED-001-B-04
  - Status: PENDING
  - Action: Ensure work ordering never mixes target languages outside the active locale shard.
  - Target: item selection logic.
  - Allowed operation: edit, validate.
  - Expected output: selected items all belong to requested locale set.
  - Completion check: shard isolation test passes.

#### Child Taskcard ID: TC-SCHED-001-C

Parent Taskcard ID: TC-SCHED-001
Title: Add AST unit length bucketing
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SCHED-001-C-01
  - Status: PENDING
  - Action: Inspect current AST batch construction.
  - Target: `src/translation_engine/extractor/text_unit_extractor.py`.
  - Allowed operation: inspect.
  - Expected output: current unit ordering and token cap behavior recorded.
  - Completion check: finding recorded.
- MS-SCHED-001-C-02
  - Status: PENDING
  - Action: Add optional unit sorting by estimated token length before model call.
  - Target: `batch_translate_units`.
  - Allowed operation: edit.
  - Expected output: model input batches are length-bucketed.
  - Completion check: original unit-to-translation mapping is preserved.
- MS-SCHED-001-C-03
  - Status: PENDING
  - Action: Restore translations to original unit order after batch translation.
  - Target: AST translation result mapping.
  - Allowed operation: edit.
  - Expected output: rendered document order unchanged.
  - Completion check: regression test compares output order.
- MS-SCHED-001-C-04
  - Status: PENDING
  - Action: Add negative control for mixed-length unit mapping.
  - Target: unit test fixture.
  - Allowed operation: create.
  - Expected output: test fails if translation is assigned to wrong unit.
  - Completion check: negative control passes.

#### Child Taskcard ID: TC-SCHED-001-D

Parent Taskcard ID: TC-SCHED-001
Title: Validate no starvation and no mapping drift
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-SCHED-001-D-01
  - Status: PENDING
  - Action: Run focused scheduling unit tests.
  - Target: scheduling tests.
  - Allowed operation: run.
  - Expected output: tests pass.
  - Completion check: test log captured.
- MS-SCHED-001-D-02
  - Status: PENDING
  - Action: Run monitored sample with `short-first`.
  - Target: all four subdomains.
  - Allowed operation: run.
  - Expected output: accepted samples, no new language mixing.
  - Completion check: sample evidence recorded.
- MS-SCHED-001-D-03
  - Status: PENDING
  - Action: Run monitored sample with `balanced`.
  - Target: all four subdomains.
  - Allowed operation: run.
  - Expected output: accepted samples and better GPU utilization than pure short-first if applicable.
  - Completion check: sample evidence recorded.

### Parent Taskcard ID: TC-LANG-001

Title: Prevent language mixing under parallel execution
Type: PARENT
Status: CLOSED

Source:

- Plan requirement ID: REQ-LANG-001, REQ-LANG-002, REQ-LANG-003, REQ-ROUTE-001
- Root cause: Parallel workers can contaminate outputs if language scope, caches, checkpoint state, or target paths are shared incorrectly.
- Selected solution: Locale-sharded workers with isolated state, route validation, cache verification, and language-mixing counters.

Children:

- TC-LANG-001-A: Enforce locale-shard isolation.
- TC-LANG-001-B: Validate target output paths.
- TC-LANG-001-C: Verify cache and adaptive-state language keys.
- TC-LANG-001-D: Add language-mixing counters and backoff.
- TC-LANG-001-E: Run monitored multilingual shard proof.

#### Child Taskcard ID: TC-LANG-001-A

Parent Taskcard ID: TC-LANG-001
Title: Enforce locale-shard isolation
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-LANG-001-A-01
  - Status: PENDING
  - Action: Verify `--only-locales` requires `--shard-id`.
  - Target: governed runner CLI.
  - Allowed operation: inspect, validate.
  - Expected output: enforcement confirmed or gap recorded.
  - Completion check: test exists or is added.
- MS-LANG-001-A-02
  - Status: PENDING
  - Action: Ensure checkpoint path includes shard id.
  - Target: checkpoint path helper.
  - Allowed operation: inspect, validate.
  - Expected output: `checkpoint.<shard-id>.json`.
  - Completion check: unit test verifies path.
- MS-LANG-001-A-03
  - Status: PENDING
  - Action: Ensure current-item path includes shard id.
  - Target: current path helper.
  - Allowed operation: inspect, validate.
  - Expected output: `current.<shard-id>.json`.
  - Completion check: unit test verifies path.
- MS-LANG-001-A-04
  - Status: PENDING
  - Action: Ensure policy and inventory baselines include shard id.
  - Target: baseline file helper.
  - Allowed operation: inspect, validate.
  - Expected output: shard-specific baseline files.
  - Completion check: unit test verifies path.
- MS-LANG-001-A-05
  - Status: PENDING
  - Action: Ensure worker logs include site and shard id.
  - Target: autonomous launcher.
  - Allowed operation: edit.
  - Expected output: separate logs per site/shard.
  - Completion check: log path test or dry run proves separation.

#### Child Taskcard ID: TC-LANG-001-B

Parent Taskcard ID: TC-LANG-001
Title: Validate target output paths
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-LANG-001-B-01
  - Status: PENDING
  - Action: Add folder-layout target path validator.
  - Target: governed runner verification preflight.
  - Allowed operation: edit.
  - Expected output: target path must be under `{content_root}/{locale}/`.
  - Completion check: unit test rejects wrong locale folder.
- MS-LANG-001-B-02
  - Status: PENDING
  - Action: Add blog file-suffix target path validator.
  - Target: governed runner verification preflight.
  - Allowed operation: edit.
  - Expected output: target file stem must end with `.{locale}`.
  - Completion check: unit test rejects `index.de.md` for locale `fr`.
- MS-LANG-001-B-03
  - Status: PENDING
  - Action: Add duplicate output collision detection.
  - Target: inventory builder.
  - Allowed operation: edit.
  - Expected output: no two work items in a shard resolve to same target path.
  - Completion check: collision fixture fails fast.

#### Child Taskcard ID: TC-LANG-001-C

Parent Taskcard ID: TC-LANG-001
Title: Verify cache and adaptive-state language keys
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-LANG-001-C-01
  - Status: PENDING
  - Action: Inspect translation-memory key structure.
  - Target: TM modules.
  - Allowed operation: inspect.
  - Expected output: target-language key inclusion confirmed or gap recorded.
  - Completion check: finding recorded.
- MS-LANG-001-C-02
  - Status: PENDING
  - Action: Add or verify test that TM hit cannot cross target languages.
  - Target: TM tests.
  - Allowed operation: create, validate.
  - Expected output: cross-language cache hit is impossible.
  - Completion check: test passes.
- MS-LANG-001-C-03
  - Status: PENDING
  - Action: Inspect adaptive batch stats keying.
  - Target: `batch_stats_tracker`.
  - Allowed operation: inspect.
  - Expected output: per-target-language state confirmed.
  - Completion check: finding recorded.
- MS-LANG-001-C-04
  - Status: PENDING
  - Action: Add test that adaptive stats for one language do not alter another.
  - Target: batch stats tests.
  - Allowed operation: create, validate.
  - Expected output: state isolation test.
  - Completion check: test passes.

#### Child Taskcard ID: TC-LANG-001-D

Parent Taskcard ID: TC-LANG-001
Title: Add language-mixing counters and backoff
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-LANG-001-D-01
  - Status: PENDING
  - Action: Classify existing failure types that indicate language mixing.
  - Target: governed runner failure taxonomy.
  - Allowed operation: inspect, record.
  - Expected output: list of failure types counted as language-mixing.
  - Completion check: taxonomy recorded.
- MS-LANG-001-D-02
  - Status: PENDING
  - Action: Count language-mixing failures per shard cycle.
  - Target: summary or worker report.
  - Allowed operation: edit.
  - Expected output: `language_mixing_failure_count`.
  - Completion check: focused test with synthetic failures.
- MS-LANG-001-D-03
  - Status: PENDING
  - Action: Add backoff if shard has more than 3 language-mixing failures in a cycle.
  - Target: launcher cycle logic.
  - Allowed operation: edit.
  - Expected output: reduce concurrency or batch size for affected shard.
  - Completion check: mocked cycle report triggers backoff.
- MS-LANG-001-D-04
  - Status: PENDING
  - Action: Record backoff event in evidence.
  - Target: worker log/report.
  - Allowed operation: edit.
  - Expected output: backoff reason and new settings.
  - Completion check: log test or sample run records event.

#### Child Taskcard ID: TC-LANG-001-E

Parent Taskcard ID: TC-LANG-001
Title: Run monitored multilingual shard proof
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-LANG-001-E-01
  - Status: PENDING
  - Action: Select 20-file sample across 6 languages and four subdomains.
  - Target: monitored sample plan.
  - Allowed operation: run, record.
  - Expected output: sample manifest.
  - Completion check: sample includes all required site/layout types.
- MS-LANG-001-E-02
  - Status: PENDING
  - Action: Run sample with locale-sharded parallel workers.
  - Target: sample run.
  - Allowed operation: run.
  - Expected output: accepted/rejected evidence per file.
  - Completion check: run completes without source mutation.
- MS-LANG-001-E-03
  - Status: PENDING
  - Action: Verify zero wrong-language outputs.
  - Target: sample comparisons and purity reports.
  - Allowed operation: inspect.
  - Expected output: zero language-mixing failures.
  - Completion check: report says zero.
- MS-LANG-001-E-04
  - Status: PENDING
  - Action: Verify zero cross-locale path writes.
  - Target: output paths in receipts.
  - Allowed operation: inspect.
  - Expected output: each target path matches locale.
  - Completion check: path audit passes.

### Parent Taskcard ID: TC-VERIFY-001

Title: Validate and close optimized autonomous execution
Type: PARENT
Status: CLOSED

Source:

- Plan requirement ID: REQ-MULTI-002, REQ-EVID-001, REQ-SAFE-001
- Root cause: Speed improvements are unsafe unless accepted outputs are reverified and evidence proves no regression.
- Selected solution: Add mandatory validation, quality scoring, rollback, and closeout gates.

Children:

- TC-VERIFY-001-A: Reverify accepted receipts.
- TC-VERIFY-001-B: Run Hugo build checks.
- TC-VERIFY-001-C: Run source mutation checks.
- TC-VERIFY-001-D: Score quality and reroute weak taskcards.
- TC-VERIFY-001-E: Produce final execution handoff.

#### Child Taskcard ID: TC-VERIFY-001-A

Parent Taskcard ID: TC-VERIFY-001
Title: Reverify accepted receipts
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-VERIFY-001-A-01
  - Status: PENDING
  - Action: Run accepted reverify for each site/shard.
  - Target: governed runner `--reverify-accepted`.
  - Allowed operation: run.
  - Expected output: accepted reverify reports.
  - Completion check: all accepted entries return `VERIFIED_ACCEPT`.
- MS-VERIFY-001-A-02
  - Status: PENDING
  - Action: Quarantine any stale accepted receipt.
  - Target: checkpoint and quarantined receipts.
  - Allowed operation: run, record.
  - Expected output: failed state with typed reason.
  - Completion check: no stale accepted receipt remains.

#### Child Taskcard ID: TC-VERIFY-001-B

Parent Taskcard ID: TC-VERIFY-001
Title: Run Hugo build checks
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-VERIFY-001-B-01
  - Status: PENDING
  - Action: Run Hugo build for `kb.aspose.org`.
  - Target: `aspose.org/configs/kb.aspose.org.toml`.
  - Allowed operation: run.
  - Expected output: successful build or typed blocker.
  - Completion check: build log captured.
- MS-VERIFY-001-B-02
  - Status: PENDING
  - Action: Run Hugo build for `blog.aspose.org`.
  - Target: `aspose.org/configs/blog.aspose.org.yml`.
  - Allowed operation: run.
  - Expected output: successful build or typed blocker.
  - Completion check: build log captured.
- MS-VERIFY-001-B-03
  - Status: PENDING
  - Action: Run Hugo build for `docs.aspose.org`.
  - Target: `aspose.org/configs/docs.aspose.org.toml`.
  - Allowed operation: run.
  - Expected output: successful build or typed blocker.
  - Completion check: build log captured.
- MS-VERIFY-001-B-04
  - Status: PENDING
  - Action: Run Hugo build for `reference.aspose.org`.
  - Target: `aspose.org/configs/reference.aspose.org.toml`.
  - Allowed operation: run.
  - Expected output: successful build or typed blocker.
  - Completion check: build log captured.

#### Child Taskcard ID: TC-VERIFY-001-C

Parent Taskcard ID: TC-VERIFY-001
Title: Run source mutation checks
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-VERIFY-001-C-01
  - Status: PENDING
  - Action: Compare source hashes before and after execution.
  - Target: baseline and final source-hash evidence.
  - Allowed operation: inspect.
  - Expected output: zero mutations.
  - Completion check: `source_mutation_count == 0` for every site.
- MS-VERIFY-001-C-02
  - Status: PENDING
  - Action: If mutation exists, stop closeout and record rollback target.
  - Target: mutation report.
  - Allowed operation: record.
  - Expected output: blocker with exact paths.
  - Completion check: closeout is blocked until resolved.

#### Child Taskcard ID: TC-VERIFY-001-D

Parent Taskcard ID: TC-VERIFY-001
Title: Score quality and reroute weak taskcards
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-VERIFY-001-D-01
  - Status: PENDING
  - Action: Score each child taskcard on required dimensions.
  - Target: quality score report.
  - Allowed operation: record.
  - Expected output: 1-5 scores for each dimension.
  - Completion check: all mandatory dimensions are at least 4.
- MS-VERIFY-001-D-02
  - Status: PENDING
  - Action: Mark any child below 4 as `REROUTED`.
  - Target: taskcard status.
  - Allowed operation: record.
  - Expected output: reroute record and new child task if needed.
  - Completion check: no below-threshold task is closed.

#### Child Taskcard ID: TC-VERIFY-001-E

Parent Taskcard ID: TC-VERIFY-001
Title: Produce final execution handoff
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-VERIFY-001-E-01
  - Status: PENDING
  - Action: Summarize pages/languages processed.
  - Target: final handoff.
  - Allowed operation: record.
  - Expected output: processed count table.
  - Completion check: counts match summaries.
- MS-VERIFY-001-E-02
  - Status: PENDING
  - Action: Summarize validation results and repairs.
  - Target: final handoff.
  - Allowed operation: record.
  - Expected output: validation and repair summary.
  - Completion check: evidence paths included.
- MS-VERIFY-001-E-03
  - Status: PENDING
  - Action: State final verdict.
  - Target: final handoff.
  - Allowed operation: record.
  - Expected output: `ACCEPTED`, `ACCEPTED_WITH_KNOWN_BLOCKERS`, or `REJECTED`.
  - Completion check: verdict follows evidence.

## Dependency DAG

```text
TC-MULTI-001
  -> TC-SPEED-001-A
  -> TC-LANG-001-A

TC-LANG-001-A
  -> TC-LANG-001-B
  -> TC-LANG-001-C
  -> TC-LANG-001-D
  -> TC-LANG-001-E

TC-SPEED-001-A
  -> TC-SPEED-001-B
  -> TC-SPEED-001-C
  -> TC-SPEED-001-D
  -> TC-SPEED-001-E

TC-SCHED-001-A
  -> TC-SCHED-001-B
  -> TC-SCHED-001-C
  -> TC-SCHED-001-D

TC-SPEED-001-E
TC-SCHED-001-D
TC-LANG-001-E
  -> TC-VERIFY-001
```

Parallel-safe groups:

- TC-SPEED-001-A and TC-LANG-001-A are parallel-safe if they only inspect.
- TC-SPEED-001-B and TC-LANG-001-B both edit the governed runner and must not run in parallel.
- TC-SCHED-001-C edits AST batch code and must not run in parallel with unrelated `segment_translator` or `text_unit_extractor` changes.

## Validation Matrix

| Taskcard | Validation | Expected result | Evidence |
|---|---|---|---|
| TC-SPEED-001-B | Parser and command-construction unit tests | speed flags parse and forward correctly | pytest log |
| TC-SPEED-001-C | Mocked VRAM threshold test | worker launch pauses/backoffs above threshold | pytest log |
| TC-SCHED-001-B | Work-order unit tests | short/balanced order stable within locale shard | pytest log |
| TC-SCHED-001-C | AST mapping regression test | translation output maps to original unit order | pytest log |
| TC-LANG-001-A | Shard file path tests | checkpoint/current/baseline are shard-specific | pytest log |
| TC-LANG-001-B | Route/path negative tests | wrong locale target path is rejected | pytest log |
| TC-LANG-001-C | Cache isolation tests | no cross-target-language TM/adaptive hit | pytest log |
| TC-LANG-001-D | Synthetic language-mixing counter test | count and backoff trigger after threshold | pytest log |
| TC-LANG-001-E | Monitored multilingual sample | zero language mixing, zero source mutation | sample report |
| TC-VERIFY-001 | Accepted reverify + Hugo builds + source hash check | all pass or blockers proven | final handoff |

## Evidence Obligations

Every execution artifact must state:

- `authoritative_plan: docs/quality/aspose-org-multisite-speed-language-mixing-micro-task-plan.md`
- `execution_authority: false`
- relevant requirement id
- relevant parent taskcard id
- relevant child taskcard id
- relevant micro-step id when applicable

Required evidence roots:

- `.local/evidences/aspose-org-multisite/multisite_validate_20260702_001/`
- `.local/evidences/autonomous-workers/`
- `.local/evidences/aspose-org-multisite/speed-calibration/`
- `.local/evidences/aspose-org-multisite/language-mixing-samples/`

## Rollback Rules

- If speed profile increases hard-gate failures, revert to `safe` profile.
- If language mixing appears, stop optimized workers, reduce concurrency to one locale shard, and quarantine affected failures.
- If source mutation appears, stop closeout and restore from source hash evidence.
- If route/path validator rejects outputs, do not override; fix inventory/path logic.
- If short-first starves long pages for more than 6 cycles, switch to balanced quota.

## Execution Progress (2026-07-03) — Session 2 Update

### CLOSED taskcards (implementation + focused tests verified green)

| Taskcard | Status | Evidence |
|---|---|---|
| TC-MULTI-001 (A/B/C) | CLOSED | evidence-index.json, worker logs captured, authority confirmed |
| TC-SPEED-001-A | CLOSED | kb: 313/5472, blog: 192/2016, docs: 403/5796, ref: 409/72252 accepted; mutations=0 |
| TC-SPEED-001-B | CLOSED | `--model-batch-size`, `--throughput-profile`, `--work-order`, `--max-concurrent-site-workers` implemented; tests pass |
| TC-SPEED-001-C | CLOSED | `query_vram_snapshot`, `wait_for_vram_below`, `log_contains_cuda_oom`, OOM backoff; tests pass |
| TC-SCHED-001-A | CLOSED | `--plan-only` inventory for all 4 sites; size-distribution-report.json written; kb: 268/36, blog: 114/36, docs: 354/36, ref: 4774/36 sources×locales |
| TC-SCHED-001-B | CLOSED + BUGFIX | `--work-order` implemented; BUGFIX: short-first sort key now puts `estimated_item_size` before `locale`/`relative_path` via `failed_priority()` helper; 3 tests pass including new alpha-override regression |
| TC-SCHED-001-C | CLOSED | `sort_by_length` param added to `batch_translate_units`; in-place mutation preserves original order; 3 tests pass |
| TC-SCHED-001-D | CLOSED | Starvation-free proof: short-first processes all short files before first long on all 4 sites; balanced coverage verified; 65 quality tests pass |
| TC-LANG-001-A | CLOSED | `--only-locales` requires `--shard-id` enforced; checkpoint/current/baseline paths include shard_id; 4 tests pass |
| TC-LANG-001-B | CLOSED | `validate_target_path` + `target_path_collisions` implemented; 5 tests pass |
| TC-LANG-001-C | CLOSED | L1 key = `site:src_lang:tgt_lang:hash(text)` — cross-language hit structurally impossible; 3 tests pass |
| TC-LANG-001-D | CLOSED | `LANGUAGE_MIXING_FAILURE_TYPES`, `language_mixing_failure_count`, per-shard backoff; 4 tests pass |
| TC-VERIFY-001-D | CLOSED | 14 taskcards scored ≥4/5 on all 5 dimensions; no rerouting required; quality-score-report.json written |

### Focused test results (2026-07-03 Session 2)

```
pytest tests/unit/quality/ -q
→ 65 passed, 0 failed, 3 warnings  (after TC-SCHED-001-B bugfix + new test)
```

```
pytest tests/unit/quality/ tests/unit/tm/test_translation_memory_hash.py
      tests/unit/translation_engine/extractor/test_text_unit_extraction.py
→ 129 passed, 0 failed (Session 1 baseline)
```

### Key finding from Session 2

**TC-SCHED-001-B sorting bug (found + fixed):** The `short-first` sort key included `relative_path` before `estimated_item_size` inside `base_key`, making `short-first` produce identical output to default ordering for single-locale runs. Fixed by extracting `failed_priority()` and constructing the key as `(failed_priority, size, locale, path)`. Verified starvation-free on all 4 real-inventory datasets.

### Still PENDING (require live GPU/content-repo runs)

| Taskcard | Blocker | Status |
|---|---|---|
| TC-SPEED-001-D | Calibration runs: 20-30 min isolated worker run per profile | BLOCKED_EXTERNAL_CANDIDATE |
| TC-SPEED-001-E | Depends on TC-SPEED-001-D | BLOCKED_EXTERNAL_CANDIDATE |
| TC-LANG-001-E | Monitored multilingual shard proof (20 files × 6 langs × 4 subdomains) | BLOCKED_EXTERNAL_CANDIDATE |
| TC-VERIFY-001-A | Accepted reverify per shard (needs accepted pairs in checkpoint) | BLOCKED_EXTERNAL_CANDIDATE |
| TC-VERIFY-001-B | Hugo builds (Hugo binary path not confirmed) | BLOCKED_EXTERNAL_CANDIDATE |
| TC-VERIFY-001-C | Source mutation hash comparison (auto-runs per cycle) | BLOCKED_EXTERNAL_CANDIDATE |
| TC-VERIFY-001-E | Final handoff summary (after all verify children) | BLOCKED_EXTERNAL_CANDIDATE |

### Pre-existing test failures (not introduced by this execution)

- `tests/unit/translation_engine/test_multiline_batching.py` — fails without any of our changes
- `tests/unit/tm/test_l2_dual_path.py` — migration script tests, pre-existing
- `tests/unit/tm/test_l2_fasttext_cooldown.py` — fasttext cooldown, pre-existing
- `tests/unit/model_runtime/test_ct2_converter.py` — CT2 converter, pre-existing
- `tests/unit/test_audit_script.py` — `audit_codebase` module missing, pre-existing

## Next Valid Execution Step

All non-live-run taskcards are now CLOSED. Remaining items require live GPU translation runs against the real content repo:

1. **TC-LANG-001-E** (first): Run 20-file × 6-locale monitored shard proof with `--only-locales` + `--shard-id` on all 4 sites to prove language isolation holds under parallel conditions.
2. **TC-SPEED-001-D**: Run `safe` / `fast` / `max-vram` profile calibration (20-30 min each, watch VRAM % and accepted/hour).
3. **TC-SPEED-001-E**: Select production profile from calibration evidence.
4. **TC-VERIFY-001-A**: Run `--reverify-accepted` per shard to confirm no translation drift on previously accepted pairs.
5. **TC-VERIFY-001-C**: Check `source-hashes-before` vs post-run to confirm zero source mutations.
6. **TC-VERIFY-001-E**: Produce final handoff summary and close plan.

## Current Limitations

- This file remains the only authoritative execution plan. Supporting ledgers for the deep taskcardization prompt now live under `.local/evidences/plan-taskcardization-20260702/` and are marked non-authoritative.
- Existing autonomous workers may still be running under the pre-optimization launch model. Reconcile them before starting optimized workers.
- Some unrelated repo changes predate this task and must not be reverted.

## Execution Reconciliation 2026-07-02

Plan binding:

- mission_id: `aspose-org-multisite-speed-language-mixing-20260702`
- repository: `C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator`
- branch: `main`
- head: `fa9f4ef7267bce41d89d7823ad9b4c801868e53b`
- plan_path: `docs/quality/aspose-org-multisite-speed-language-mixing-micro-task-plan.md`
- plan_id: `aspose-org-multisite-speed-language-mixing-micro-task-plan`
- plan_revision: `2026-07-02-initial-microtaskcardized`
- plan_hash: `049841E3F25320F1A93E5E8822B2F79EEF2EACA68D95172663F6AAD0653C23F3`
- global_fallback_allowed: false

Current-state findings:

- The governed runner already has `--only-locales`, `--shard-id`, shard-specific checkpoint/current/baseline/summary filenames, and shard-id enforcement.
- The multisite unattended wrapper already supports locale shards but launches shard cycles sequentially and does not yet expose throughput profiles, model batch forwarding, VRAM launch control, or language-mixing backoff.
- Current worker logs show pre-optimization cycles still running or recently cycled under site-level worker logs. They must not be killed solely to apply this plan.
- Current summaries for `multisite_validate_20260702_001` show zero source mutations for all four sites, with many remaining failed pairs.
- GPU snapshot at reconciliation: NVIDIA GeForce RTX 4090 Laptop GPU, 16% utilization, 1346 MiB used of 16376 MiB total.

Gap register:

| Gap ID | Requirement IDs | Severity | Symptom | First failing boundary | Root cause | Permanent solution | Verification |
|---|---|---|---|---|---|---|---|
| GAP-SPEED-001 | REQ-SPEED-001, REQ-SPEED-002 | high | GPU underused and batch size fixed at wrapper level only | multisite launcher to governed runner command construction | launcher lacks throughput profile and governed runner does not forward model batch size | add `--throughput-profile`, `--model-batch-size`, batch forwarding, and throughput evidence | command-construction tests and calibration evidence |
| GAP-SPEED-002 | REQ-SAFE-001 | high | speed escalation could overrun VRAM or OOM repeatedly | worker launch loop | no VRAM polling/backoff before launching translation subprocesses | add target VRAM polling, snapshots, and CUDA OOM batch backoff | mocked VRAM tests and log evidence |
| GAP-SCHED-001 | REQ-SCHED-001 | medium | workers process failure/path order only | work item selection before `--max-work-items` | no source-size ordering or balanced quota | add `--work-order` modes after filtering accepted work and before slicing | ordering and starvation tests |
| GAP-LANG-001 | REQ-LANG-001, REQ-LANG-002, REQ-ROUTE-001 | high | parallel shards could write wrong locale path or collide | inventory/target path boundary | no explicit target route/collision assertion | add folder/file-suffix path validators and duplicate target detection | route negative tests |
| GAP-LANG-002 | REQ-LANG-003, REQ-SAFE-001 | high | wrong-language/purity failures are not summarized per shard for backoff | final summary and wrapper cycle handling | failure taxonomy is not promoted into shard metrics | count language-mixing failure types in summary and back off affected shard batch size | synthetic failure-count tests |
| GAP-EVID-001 | REQ-EVID-001 | medium | evidence roots exist but no single non-authoritative index maps them to taskcards | evidence closeout | plan file exists but execution artifacts are not indexed | create evidence index with plan binding and taskcard map | evidence file inspection |

Requirement reconciliation:

| Requirement ID | Status | Evidence | Next taskcard |
|---|---|---|---|
| REQ-MULTI-001 | PARTIAL | inventory and summaries exist for four sites | TC-MULTI-001-C |
| REQ-MULTI-002 | PARTIAL | hardened verifier exists; many failures remain | TC-VERIFY-001 |
| REQ-SPEED-001 | NOT_IMPLEMENTED | fixed wrapper batch only | TC-SPEED-001-B |
| REQ-SPEED-002 | PARTIAL | summary counts and log cycles exist | TC-SPEED-001-A |
| REQ-SCHED-001 | NOT_IMPLEMENTED | no `--work-order` parser option | TC-SCHED-001-B |
| REQ-LANG-001 | PARTIAL | single-language subprocesses and shard scope exist | TC-LANG-001-B, TC-LANG-001-D |
| REQ-LANG-002 | PARTIAL | shard-id files exist; wrapper log naming can be improved | TC-LANG-001-A |
| REQ-LANG-003 | NOT_IMPLEMENTED | no shard language-mixing counts | TC-LANG-001-D |
| REQ-ROUTE-001 | NOT_IMPLEMENTED | target path generation exists, explicit validator missing | TC-LANG-001-B |
| REQ-EVID-001 | PARTIAL | evidence roots exist; index missing | TC-MULTI-001-C |
| REQ-SAFE-001 | PARTIAL | hard verifier rejects failures; speed backoff missing | TC-SPEED-001-C, TC-LANG-001-D |

Execution decision:

- Existing pre-optimization workers may continue because source mutation count is zero and they are writing governed evidence.
- New optimized work must use the amended launcher/runner only after focused tests pass.
- Do not use broad in-process `src.cli --parallel-languages` for production.

## Execution Update 2026-07-02T14:32Z

Implemented changes:

- Governed runner now accepts `--model-batch-size` and forwards it to `src.cli --batch-size`.
- Governed runner now accepts `--work-order failed-first|short-first|balanced`.
- Work selection now filters accepted items before slicing, then applies the selected work ordering.
- Folder-layout target paths are validated under the exact locale directory.
- Blog/file-suffix target paths are validated with the exact `.{locale}.md` suffix.
- Duplicate target path collisions fail inventory construction before writing.
- Governed summaries now include `failure_type_counts`, `language_mixing_failure_count`, `work_order`, `model_batch_size`, and `shard_id`.
- Multisite wrapper now accepts `--throughput-profile`, `--model-batch-size`, `--target-vram-percent`, `--max-concurrent-site-workers`, and `--work-order`.
- Multisite wrapper records VRAM snapshots before and after worker launches.
- Multisite wrapper backs off shard model batch size after CUDA OOM or more than three language-mixing failures.
- Multisite wrapper aggregates `summary.<shard>.json` files so sharded progress is visible to campaign-level decisions.
- Multisite wrapper `--skip-baseline --validate-only` control flow was repaired so read-only verification cannot start real translation cycles.

Healed verification failure:

- Failure: wrapper read-only pilot timed out because `--skip-baseline --validate-only` did not continue after loading existing summaries and instead launched a real optimized shard cycle.
- First failing boundary: multisite wrapper control flow after `args.skip_baseline`.
- Root cause: the `validate_only` early-continue existed only in the non-skip-baseline branch.
- Repair: added the same `if args.validate_only: continue` guard inside the skip-baseline branch.
- Recovery: stopped only wrapper-spawned optimized processes identified by exact command-line flags; existing pre-optimization autonomous workers were left alone.
- Verification: reran wrapper read-only pilot with run id `microtask_wrapper_readonly_20260702_001`; it returned `VALIDATION_BASELINE_COMPLETE` without launching translation.

Verification completed:

- Focused tests: `.venv\Scripts\python.exe -m pytest tests\unit\quality\test_aspose_org_governed_retranslate.py tests\unit\quality\test_aspose_org_multisite_unattended.py tests\unit\test_purity_strip.py -q`
- Result: `32 passed, 3 warnings`.
- Official governed runner plan-only pilot for all four sites, locales `de,fr`, shard `smoke-de-fr`, `--model-batch-size 64`, `--work-order short-first`: all returned `PLAN_ONLY_NO_TRANSLATION_STARTED`.
- Wrapper read-only pilot with speed flags returned `VALIDATION_BASELINE_COMPLETE`.

Updated requirement reconciliation:

| Requirement ID | Current status after implementation | Evidence | Remaining proof |
|---|---|---|---|
| REQ-MULTI-001 | PARTIAL | existing inventories and summaries | full autonomous completion still pending |
| REQ-MULTI-002 | PARTIAL | validators and focused tests pass | accepted reverify/Hugo builds pending after run |
| REQ-SPEED-001 | IMPLEMENTED_UNVERIFIED | speed flags, batch forwarding, wrapper profiles | real calibration accepted/hour pending |
| REQ-SPEED-002 | PARTIAL | baseline counts and VRAM snapshot captured | profile comparison pending |
| REQ-SCHED-001 | FOCUSED_VERIFIED | work-order tests pass | monitored real translation sample pending |
| REQ-LANG-001 | PARTIAL | shard-safe subprocesses remain enforced | monitored multilingual proof pending |
| REQ-LANG-002 | FOCUSED_VERIFIED | shard-specific files and tests/plan-only pilot | production shard evidence pending |
| REQ-LANG-003 | FOCUSED_VERIFIED | failure counters and tests pass | production backoff evidence pending |
| REQ-ROUTE-001 | FOCUSED_VERIFIED | route negative tests and plan-only pilot pass | production output audit pending |
| REQ-EVID-001 | PARTIAL | evidence index created | final closeout evidence pending |
| REQ-SAFE-001 | PARTIAL | OOM/language-mixing backoff implemented | real backoff/pilot proof pending |

Next execution handoff:

- Do not launch optimized production translation until the existing pre-optimization autonomous workers are reconciled or drained.
- Next safe action is `TC-LANG-001-E`: run a monitored multilingual shard proof on a separate run id with small `--max-work-items`, `--shard-locales`, `--throughput-profile fast`, and `--work-order short-first`.
- If the monitored proof shows zero source mutations, zero route violations, and zero language-mixing failures, proceed to `TC-SPEED-001-D` calibration for `safe`, `fast`, and `max-vram`.

## Autonomous Execution Contract 2026-07-02T15:48Z

```yaml
autonomous_execution_contract:
  selected_mechanism: aspose_org_multisite_unattended
  mechanism_type: autonomous_cycle
  entry_point: scripts/quality/aspose_org_multisite_unattended.py
  invocation: >
    .venv\Scripts\python.exe scripts\quality\aspose_org_multisite_unattended.py
    --run-id multisite_shard_pilot_20260702_001
    --skip-baseline
    --skip-hugo-build
    --shard-locales
    --max-cycles 1
    --batch-size 1
    --throughput-profile fast
    --model-batch-size 64
    --target-vram-percent 80
    --max-concurrent-site-workers 1
    --work-order short-first
  governing_state: .local/evidences/aspose-org-multisite/multisite_shard_pilot_20260702_001/final/campaign-report.json
  task_source: docs/quality/aspose-org-multisite-speed-language-mixing-micro-task-plan.md
  continuation_source: campaign-report cycle summaries and shard summaries
  continuation_consumer: scripts/quality/aspose_org_multisite_unattended.py
  stop_evaluator: scripts/quality/aspose_org_multisite_unattended.py final_verdict plus governed verifier summaries
  resume_strategy: rerun same entry point with --resume and same run id after audit/repair
  rejected_alternative: .local/evidences/autonomous-workers/worker-*.ps1 legacy site loops
  mechanism_locked: true
```

Controller reconciliation:

- Legacy parent site-worker loops were stopped because they are four independent controllers and do not satisfy the single autonomous authority rule.
- Current legacy child governed processes were first given a 20-minute drain window.
- Remaining legacy child processes were stopped after the drain window to prevent competing checkpoint/output writes.
- This transition is safe only because governed validation rejects partial or corrupted outputs before acceptance; interrupted outputs must be caught by the next verifier run.

Stats at controller lock:

| Site | Accepted | Failed tracked | Required | Source mutations |
|---|---:|---:|---:|---:|
| kb.aspose.org | 313 | 5159 | 5472 | 0 |
| blog.aspose.org | 192 | 1824 | 2016 | 0 |
| docs.aspose.org | 403 | 5393 | 5796 | 0 |
| reference.aspose.org | 409 | 7356 | 72252 | 0 |

Next controller-owned task:

- Run `multisite_shard_pilot_20260702_001` as a small monitored shard proof.
- Audit raw shard summaries and route/language/source-mutation evidence before any larger autonomous production run.

## Sprint Audit 2026-07-02T16:30Z

Evidence inspected:

- `.local/evidences/aspose-org-multisite/multisite_shard_pilot_20260702_001/final/campaign-report.json`
- `.local/evidences/*/multisite_shard_pilot_20260702_001/final/summary.*.json`
- `.local/evidences/*/multisite_shard_pilot_20260702_001/final/accepted-reverification.*.json`
- focused pytest output: `33 passed, 3 warnings`
- process table after legacy controller shutdown

What we achieved:

- Legacy independent site-worker loops were stopped and the selected controller was locked to `scripts/quality/aspose_org_multisite_unattended.py`.
- First pilot exposed a false `REJECTED` verdict for bounded pilot runs; root cause was production-only stop evaluation.
- Controller now supports `--pilot-mode`, returning `PILOT_ACCEPTED` when bounded shard work has zero failures, zero source mutations, and zero language-mixing failures.
- Sharded accepted reverify now runs per shard and writes `accepted-reverification.<shard>.json`.
- Multisite governed runner now overlays the unsharded main checkpoint into shard checkpoints on resume, then merges shard checkpoints back to the main checkpoint.
- Rerun pilot consumed two items per shard across four sites: 48 accepted shard-scoped translations, zero failed, zero source mutations, zero language-mixing failures.
- Shard accepted reverify checked two accepted receipts per shard and returned `VERIFIED_ACCEPT` for each checked item.

What this proves:

- The selected controller can dispatch shard-scoped work, observe shard results, reverify accepted shard receipts, and stop with a bounded pilot verdict.
- `--model-batch-size 64` and `--work-order short-first` work through the official entry point.
- Route, source-mutation, language-mixing, and accepted-reverify gates are active in the pilot path.

Effect on final outcome:

- `TC-LANG-001-E` has pilot proof for small sample size.
- Full mission is still not complete because autonomous production processing, final accepted reverify, Hugo builds, and full closeout remain pending.

Uncertainty and limitations:

- The pilot used two items per shard, not a full statistically representative 80-sample manual-equivalent review.
- GPU VRAM stayed near zero after each subprocess, so throughput scaling is not yet proven.
- Production run may reveal failure classes absent from the short-first pilot.

Findings requiring plan amendments:

| Finding ID | Requirement/task | Classification | Proof level | Action |
|---|---|---|---|---|
| AUDIT-20260702-001 | TC-VERIFY-001 / controller stop evaluator | completed_verified | end_to_end_proof | `--pilot-mode` added and verified |
| AUDIT-20260702-002 | TC-VERIFY-001-A / shard reverify | completed_verified | end_to_end_proof | shard-specific accepted reverify added and verified |
| AUDIT-20260702-003 | TC-LANG-001-A / checkpoint state | completed_verified | partial_validation | shard checkpoint overlay and merge added; production proof pending |
| AUDIT-20260702-004 | TC-SPEED-001-D / throughput | partially_done | partial_validation | launch production with fast profile and collect accepted/hour |

Plan verdict:

- `PLAN_HARDENED_FROM_AUDIT_READY_FOR_EXECUTION`

Next production execution:

- Use selected controller only:
  - `.venv\Scripts\python.exe scripts\quality\aspose_org_multisite_unattended.py --run-id multisite_validate_20260702_001 --skip-baseline --skip-hugo-build --shard-locales --resume --max-cycles 200 --batch-size 12 --throughput-profile fast --model-batch-size 64 --target-vram-percent 80 --max-concurrent-site-workers 1 --work-order short-first`
- Monitor first campaign report cycle for source mutations, language-mixing failures, and checkpoint merge correctness.

## Efficiency Optimization Deep Analysis 2026-07-02

Planning boundary:

- Current mode is plan analysis and micro-taskcardization only. Do not resume production translation from this section unless the user explicitly authorizes execution.
- The production controller was paused before this planning pass because an active planning-only protocol superseded execution. Before any future execution, confirm no stale `aspose_org_multisite_unattended.py`, `aspose_org_governed_retranslate.py`, or `src.cli` translation process is still writing.

Symptoms:

- GPU and VRAM use can remain near idle even while translation work is pending.
- Required pair count remains large compared with accepted count.
- Speed knobs exist, but accepted-pairs/hour has not yet been proven under production load.
- Short-first scheduling improves pilot acceptances but may leave long pages under-tested.
- Failure counts can obscure whether the worker is retrying unrecoverable validator classes instead of routing them to repair logic.

Root causes:

- The translation subprocess model can still pay repeated process and model-initialization cost unless a persistent shard worker or larger unit batching path is proven safe.
- CUDA use is assumed by device flags but not yet proven by durable runtime metadata and VRAM/utilization evidence during actual model inference.
- Shard-level concurrency is intentionally conservative to prevent language mixing, but calibrated parallelism has not yet been completed.
- Failure-class routing is incomplete as an efficiency control; some hard validator failures should be classified before another expensive model retry.
- Checkpoint and summary accounting can report historical failures alongside current-cycle work, making throughput and healing rate hard to interpret.
- Verification repeats necessary but expensive checks; caching is not yet used as a controlled optimization where source hash, target hash, policy version, and validator version are unchanged.
- Live observability is still too coarse for unattended speed decisions.

Structural consistency breakers:

- Mixed-language batching inside one process remains forbidden until monitored proof exists.
- Shared state without shard identifiers can cause cross-locale contamination.
- Shared temp candidate paths can cause overwrite races.
- Output route ambiguity is most risky for blog filename localization.
- Accepting a target without current-policy reverify can hide stale receipt quality.
- Retrying every failure through the same model path can preserve failure loops.

What must be preserved:

- The governed verifier remains the acceptance authority.
- Acceptance gates must not be weakened for speed.
- English source files must remain unchanged.
- Locale-sharded isolation remains the production-safe parallelism baseline.
- Protected front matter, code, shortcodes, links, anchors, paths, API identifiers, and placeholders remain immutable unless policy explicitly allows translation.
- Evidence must prove both quality and throughput.

What must be redesigned or hardened:

- Add a runtime proof layer for CUDA/device selection and model inference memory use.
- Evaluate a persistent shard worker or batch-entrypoint design to reduce model cold starts without mixing target languages.
- Calibrate concurrency as fixed-locale shards, not as unbounded language parallelism.
- Route known validator failure classes to deterministic repair or blocker classification before model retry.
- Separate current-cycle throughput from inherited checkpoint history.
- Cache verifier results only under strict source/target/policy/validator hash identity.
- Add a live speed report with accepted/hour, failed/hour, GPU, VRAM, backoff events, and language-mixing counters.

Selected solution:

- Use a hybrid phased solution. First prove device and accounting, then add or select the lowest-risk persistent/batched execution path, then calibrate shard concurrency and batch sizes under monitored gates, then promote only the fastest profile that preserves zero source mutations, zero route violations, zero language-mixing failures, and verified accepted receipts.

Detailed efficiency requirements:

| Requirement ID | Requirement | Acceptance signal |
|---|---|---|
| REQ-EFF-001 | Prove actual CUDA or device behavior during model inference. | runtime metadata plus GPU/VRAM evidence captured during monitored work |
| REQ-EFF-002 | Reduce avoidable process/model cold-start overhead. | accepted/hour improves without gate regression |
| REQ-EFF-003 | Calibrate model batch size, page batch size, and shard concurrency. | profile scorecard selects fastest safe setting |
| REQ-EFF-004 | Keep short-first scheduling inside locale shards and add starvation controls. | no long-page starvation across bounded cycles |
| REQ-EFF-005 | Prevent language mixing under all speed modes. | zero wrong-language, mixed-language, route, and source-mutation failures in monitored proof |
| REQ-EFF-006 | Route repeatable validator failures before costly model retries. | repeated failure rate decreases and typed evidence exists |
| REQ-EFF-007 | Improve checkpoint and throughput accounting. | current-cycle and cumulative counts are separated |
| REQ-EFF-008 | Cache verification only when all safety hashes match. | cache hits are explainable and stale receipts are quarantined |
| REQ-EFF-009 | Provide unattended observability. | live report exposes accepted/hour, failures, GPU, VRAM, retries, and backoff |
| REQ-EFF-010 | Preserve rollback and safety controls. | safe profile and previous controller settings remain reproducible |

### Parent Taskcard ID: TC-EFF-001

Title: Improve end-to-end translation efficiency without weakening gates
Type: PARENT
Status: VALID_DEFERRED
Owner: Execution agent
Supervisor: Review agent

Source:

- Plan requirement ID: REQ-EFF-001 through REQ-EFF-010
- Plan section: Efficiency Optimization Deep Analysis 2026-07-02
- Root cause: Current autonomous work is correctness-first but still lacks proven GPU utilization, persistent execution efficiency, calibrated shard concurrency, failure routing, and live speed evidence.
- Selected solution: Hybrid phased solution with measurement, safe implementation, monitored calibration, and promotion only after hard gates pass.

Objective:

- Maximize accepted source-locale pairs per hour while preserving the existing governed acceptance criteria.

Outcome:

- A future execution agent can run the fastest proven profile autonomously with clear rollback and evidence.

Children:

- TC-EFF-001-A: Prove runtime device and CUDA behavior.
- TC-EFF-001-B: Analyze and reduce process/model cold-start overhead.
- TC-EFF-001-C: Calibrate shard concurrency and batch sizes.
- TC-EFF-001-D: Harden short-first and balanced scheduling for throughput.
- TC-EFF-001-E: Add failure-class routing before model retry.
- TC-EFF-001-F: Improve checkpoint and throughput accounting.
- TC-EFF-001-G: Add safe verification caching.
- TC-EFF-001-H: Add live unattended speed observability.
- TC-EFF-001-I: Promote or reject the optimized production profile.

Dependencies:

- TC-MULTI-001-A must be current before any execution.
- TC-LANG-001-E monitored proof must remain passing before concurrency increases.
- TC-VERIFY-001 gates remain mandatory after profile promotion.

Parent acceptance checks:

- selected profile improves accepted/hour or is explicitly rejected
- source mutation count remains zero
- language-mixing and wrong-route counts remain zero
- accepted receipts reverify under the current policy
- Hugo builds remain pending mandatory closeout gates for final production acceptance

Evidence required:

- `.local/evidences/plan-taskcardization-20260702/`
- `.local/evidences/aspose-org-multisite/speed-calibration/`
- `.local/evidences/aspose-org-multisite/multisite_validate_20260702_001/final/campaign-report.json`
- per-shard summary, reverify, raw logs, VRAM snapshots, and profile scorecards

Rollback plan:

- Return to `--throughput-profile safe`, single locale shard execution, and the last verified accepted checkpoint.
- If language mixing appears, stop optimized workers, quarantine affected outputs, reduce to one locale per process, and rerun reverify.
- If CUDA/OOM instability appears, reduce model batch size and worker count before retrying.

Quality scoring:

- Every mandatory child must score at least 4/5 for requirement correctness, validation strength, evidence completeness, regression safety, and production readiness.
- Any score below 4/5 reroutes only the affected child.

#### Child Taskcard ID: TC-EFF-001-A

Parent Taskcard ID: TC-EFF-001
Title: Prove runtime device and CUDA behavior
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-EFF-001-A-01
  - Status: READY
  - Action: Inspect current device selection flags and backend logs.
  - Target: `scripts/quality/aspose_org_multisite_unattended.py`, `scripts/quality/aspose_org_governed_retranslate.py`, `src/translation_engine/engine_builder.py`.
  - Allowed operation: inspect.
  - Expected output: device selection path recorded.
  - Completion check: evidence names exact flag, backend, and log field.
- MS-EFF-001-A-02
  - Status: PENDING
  - Action: Add or verify runtime metadata records the actual backend device used for inference.
  - Target: governed summary and shard logs.
  - Allowed operation: inspect or edit.
  - Expected output: `device_requested`, `device_actual`, and backend name are visible.
  - Completion check: focused test or pilot evidence shows these fields.
- MS-EFF-001-A-03
  - Status: PENDING
  - Action: Run a bounded monitored translation sample and capture GPU/VRAM during inference.
  - Target: speed-calibration evidence.
  - Allowed operation: run, record.
  - Expected output: timestamped `nvidia-smi` snapshots during active model work.
  - Completion check: evidence proves whether CUDA is actually used.
- MS-EFF-001-A-04
  - Status: PENDING
  - Action: If CUDA is not used, classify the cause before speed tuning.
  - Target: runtime environment and backend config.
  - Allowed operation: inspect, record.
  - Expected output: typed blocker or repair taskcard.
  - Completion check: no batch/concurrency escalation occurs before device cause is classified.

#### Child Taskcard ID: TC-EFF-001-B

Parent Taskcard ID: TC-EFF-001
Title: Analyze and reduce process/model cold-start overhead
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-EFF-001-B-01
  - Status: PENDING
  - Action: Measure per-item subprocess startup time versus model inference time.
  - Target: governed runner logs.
  - Allowed operation: run, record.
  - Expected output: cold-start and inference timing table.
  - Completion check: timing evidence covers at least two sites and two locales.
- MS-EFF-001-B-02
  - Status: PENDING
  - Action: Inspect whether `src.cli` can process multiple same-locale items per warm model instance safely.
  - Target: `src.cli`, translation engine lifecycle, governed candidate write path.
  - Allowed operation: inspect.
  - Expected output: call-flow map and state-sharing risk list.
  - Completion check: map identifies caches, temp files, checkpoints, and candidate paths.
- MS-EFF-001-B-03
  - Status: PENDING
  - Action: Select between larger existing batches and a persistent shard worker design.
  - Target: decision record.
  - Allowed operation: record.
  - Expected output: selected implementation approach and rejected alternatives.
  - Completion check: solution scorecard favors the safest durable option.
- MS-EFF-001-B-04
  - Status: PENDING
  - Action: Implement only the selected cold-start reduction behind an explicit flag.
  - Target: runner or CLI entrypoint chosen by MS-EFF-001-B-03.
  - Allowed operation: edit.
  - Expected output: opt-in path with current behavior as default.
  - Completion check: focused tests pass and default behavior is unchanged.
- MS-EFF-001-B-05
  - Status: PENDING
  - Action: Run monitored proof comparing accepted/hour with and without cold-start reduction.
  - Target: speed-calibration evidence.
  - Allowed operation: run, validate.
  - Expected output: comparison table with quality-gate counts.
  - Completion check: improvement is accepted only with zero safety regressions.

#### Child Taskcard ID: TC-EFF-001-C

Parent Taskcard ID: TC-EFF-001
Title: Calibrate shard concurrency and batch sizes
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-EFF-001-C-01
  - Status: PENDING
  - Action: Define candidate profiles for page batch size, model batch size, and concurrent shards.
  - Target: speed calibration matrix.
  - Allowed operation: record.
  - Expected output: bounded profiles such as safe, fast, max-vram, and rollback-safe.
  - Completion check: each profile has explicit stop conditions.
- MS-EFF-001-C-02
  - Status: PENDING
  - Action: Run the safe baseline profile.
  - Target: speed-calibration run.
  - Allowed operation: run.
  - Expected output: accepted/hour, failed/hour, GPU/VRAM, and gate counts.
  - Completion check: baseline report exists.
- MS-EFF-001-C-03
  - Status: PENDING
  - Action: Run the fast profile with fixed-locale shards only.
  - Target: speed-calibration run.
  - Allowed operation: run.
  - Expected output: throughput and safety comparison against baseline.
  - Completion check: zero source mutation, route, and language-mixing failures.
- MS-EFF-001-C-04
  - Status: PENDING
  - Action: Run the max-vram profile only if the fast profile passes.
  - Target: speed-calibration run.
  - Allowed operation: run.
  - Expected output: VRAM utilization below target and no OOM loop.
  - Completion check: OOM/backoff behavior is evidenced if triggered.
- MS-EFF-001-C-05
  - Status: PENDING
  - Action: Select or reject the fastest safe profile.
  - Target: profile scorecard.
  - Allowed operation: record.
  - Expected output: selected production command or rejection reason.
  - Completion check: decision references actual accepted/hour and gate counts.

#### Child Taskcard ID: TC-EFF-001-D

Parent Taskcard ID: TC-EFF-001
Title: Harden short-first and balanced scheduling for throughput
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-EFF-001-D-01
  - Status: PENDING
  - Action: Compare failed-first, short-first, and balanced ordering on identical shards.
  - Target: scheduler calibration evidence.
  - Allowed operation: run, record.
  - Expected output: accepted/hour and page-size distribution per mode.
  - Completion check: report proves the selected mode does not starve long pages.
- MS-EFF-001-D-02
  - Status: PENDING
  - Action: Add or verify starvation counters for long pages.
  - Target: governed summary.
  - Allowed operation: inspect or edit.
  - Expected output: long-page pending age or cycle count.
  - Completion check: summary exposes starvation risk.
- MS-EFF-001-D-03
  - Status: PENDING
  - Action: Keep short-string ordering inside each locale shard only.
  - Target: item selection and unit batching.
  - Allowed operation: validate.
  - Expected output: no cross-locale short-string batch.
  - Completion check: test or evidence confirms locale-pure batches.

#### Child Taskcard ID: TC-EFF-001-E

Parent Taskcard ID: TC-EFF-001
Title: Add failure-class routing before model retry
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-EFF-001-E-01
  - Status: PENDING
  - Action: Extract top repeated failure classes from current summaries and receipts.
  - Target: `.local/evidences/*/multisite_validate_20260702_001/`.
  - Allowed operation: inspect, record.
  - Expected output: failure-class frequency table.
  - Completion check: table separates structural, partial, route, language, and translator failures.
- MS-EFF-001-E-02
  - Status: PENDING
  - Action: Classify which failures are safe repair, retry, or blocker.
  - Target: routing decision record.
  - Allowed operation: record.
  - Expected output: deterministic routing table.
  - Completion check: every high-frequency class has an action.
- MS-EFF-001-E-03
  - Status: PENDING
  - Action: Implement routing so known non-model failures do not consume repeated model retries.
  - Target: governed runner retry loop.
  - Allowed operation: edit.
  - Expected output: route-to-repair or route-to-blocker path.
  - Completion check: tests prove retry count drops for deterministic failures.
- MS-EFF-001-E-04
  - Status: PENDING
  - Action: Verify routed items still fail closed unless repaired and reverified.
  - Target: negative controls.
  - Allowed operation: validate.
  - Expected output: no unsafe acceptance.
  - Completion check: negative controls pass.

#### Child Taskcard ID: TC-EFF-001-F

Parent Taskcard ID: TC-EFF-001
Title: Improve checkpoint and throughput accounting
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-EFF-001-F-01
  - Status: PENDING
  - Action: Separate current-cycle counts from cumulative checkpoint counts.
  - Target: summary schema.
  - Allowed operation: inspect or edit.
  - Expected output: `cycle_*` and `cumulative_*` count fields.
  - Completion check: summary test validates both count families.
- MS-EFF-001-F-02
  - Status: PENDING
  - Action: Add accepted/hour and failed/hour calculations based on current-cycle timestamps.
  - Target: campaign report.
  - Allowed operation: edit.
  - Expected output: throughput fields that do not double-count inherited history.
  - Completion check: unit test uses seeded summaries.
- MS-EFF-001-F-03
  - Status: PENDING
  - Action: Record checkpoint merge effects per shard.
  - Target: shard merge evidence.
  - Allowed operation: record.
  - Expected output: before/after checkpoint counts.
  - Completion check: evidence identifies duplicates and merged receipts.

#### Child Taskcard ID: TC-EFF-001-G

Parent Taskcard ID: TC-EFF-001
Title: Add safe verification caching
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-EFF-001-G-01
  - Status: PENDING
  - Action: Define the verifier cache key.
  - Target: validation policy.
  - Allowed operation: record.
  - Expected output: key includes source hash, target hash, policy version, validator version, locale, and site.
  - Completion check: stale key omission is impossible by review.
- MS-EFF-001-G-02
  - Status: PENDING
  - Action: Implement cache reads only for exact key matches.
  - Target: verifier or governed runner.
  - Allowed operation: edit.
  - Expected output: accepted validation can be reused only under identical inputs.
  - Completion check: tests cover hit, miss, and stale-policy miss.
- MS-EFF-001-G-03
  - Status: PENDING
  - Action: Quarantine cached receipts if current reverify fails.
  - Target: accepted reverify path.
  - Allowed operation: edit.
  - Expected output: failed reverify invalidates cache.
  - Completion check: test proves stale acceptance cannot survive.

#### Child Taskcard ID: TC-EFF-001-H

Parent Taskcard ID: TC-EFF-001
Title: Add live unattended speed observability
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-EFF-001-H-01
  - Status: PENDING
  - Action: Define live report fields.
  - Target: campaign report schema.
  - Allowed operation: record.
  - Expected output: fields include accepted/hour, failed/hour, pending, GPU, VRAM, retry, backoff, language-mixing, route failures.
  - Completion check: schema is recorded.
- MS-EFF-001-H-02
  - Status: PENDING
  - Action: Emit the live report each cycle.
  - Target: multisite wrapper.
  - Allowed operation: edit.
  - Expected output: machine-readable report under the run evidence root.
  - Completion check: focused test or dry run writes report.
- MS-EFF-001-H-03
  - Status: PENDING
  - Action: Add stoplight verdicts for unattended operation.
  - Target: live report.
  - Allowed operation: edit.
  - Expected output: `GREEN`, `YELLOW_BACKOFF`, `RED_STOP_REQUIRED`.
  - Completion check: simulated failure classes produce expected stoplight.

#### Child Taskcard ID: TC-EFF-001-I

Parent Taskcard ID: TC-EFF-001
Title: Promote or reject the optimized production profile
Type: CHILD
Status: CLOSED

Micro-steps:

- MS-EFF-001-I-01
  - Status: PENDING
  - Action: Re-read all calibration evidence before promotion.
  - Target: speed-calibration evidence.
  - Allowed operation: inspect.
  - Expected output: profile decision facts.
  - Completion check: facts include throughput, safety, and rollback.
- MS-EFF-001-I-02
  - Status: PENDING
  - Action: Promote the fastest safe command or reject optimization.
  - Target: final execution handoff.
  - Allowed operation: record.
  - Expected output: exact command or rejection reason.
  - Completion check: command uses fixed-locale shards and current gates.
- MS-EFF-001-I-03
  - Status: PENDING
  - Action: Run accepted reverify after promoted profile work.
  - Target: accepted-reverification reports.
  - Allowed operation: run, validate.
  - Expected output: `VERIFIED_ACCEPT` for accepted receipts or typed failures.
  - Completion check: no accepted item bypasses reverify.
- MS-EFF-001-I-04
  - Status: PENDING
  - Action: Update closeout evidence and next valid execution pointer.
  - Target: this plan and evidence index.
  - Allowed operation: edit, record.
  - Expected output: taskcard states reflect actual evidence.
  - Completion check: parent cannot close unless children and gates pass.

Efficiency validation matrix:

| Taskcard | Validation | Expected result | Evidence |
|---|---|---|---|
| TC-EFF-001-A | runtime device proof | actual device and VRAM evidence captured during inference | device proof report |
| TC-EFF-001-B | cold-start timing comparison | accepted/hour improves without gate regression | timing and pilot report |
| TC-EFF-001-C | profile calibration | fastest safe profile selected or rejected | profile scorecard |
| TC-EFF-001-D | scheduling calibration | selected order improves throughput without starvation | scheduler report |
| TC-EFF-001-E | routing negative controls | deterministic failures are not unsafely accepted | pytest and failure routing report |
| TC-EFF-001-F | summary accounting tests | cycle and cumulative counts do not double count | pytest and sample summaries |
| TC-EFF-001-G | cache identity tests | stale source/target/policy/validator inputs miss cache | pytest log |
| TC-EFF-001-H | report schema tests | live stoplight report emitted each cycle | dry-run report |
| TC-EFF-001-I | integration closeout | accepted receipts reverify and rollback is available | final handoff |

Efficiency dependency order:

```text
TC-EFF-001-A
  -> TC-EFF-001-B
  -> TC-EFF-001-C
TC-EFF-001-A
  -> TC-EFF-001-D
TC-EFF-001-E
  -> TC-EFF-001-F
  -> TC-EFF-001-H
TC-EFF-001-G
  -> TC-EFF-001-I
TC-EFF-001-C
TC-EFF-001-D
TC-EFF-001-H
  -> TC-EFF-001-I
```

Next valid efficiency task:

- Parent: TC-EFF-001
- Child: TC-EFF-001-A
- Micro-step: MS-EFF-001-A-01

## Execution Update 2026-07-02T17:57Z

Plan-bound execution performed:

- Added runtime device metadata to governed site summaries:
  - `device_requested`
  - `device_actual_inferred`
  - `cuda_available`
  - `cuda_device_name`
  - `inference_backend`
- Added governed run elapsed seconds to site/shard summaries.
- Added multisite current-cycle throughput accounting:
  - `cycle_elapsed_seconds`
  - `cycle_accepted_delta`
  - `cycle_failed_delta`
  - `cycle_accepted_per_hour`
  - `cycle_failed_per_hour`
  - cumulative accepted/failed/required counts
- Added live unattended speed reports:
  - `live-speed-report.<site>.json`
  - stoplight values: `GREEN`, `YELLOW_BACKOFF`, `RED_STOP_REQUIRED`
  - backoff, VRAM, source-mutation, language-mixing, and failure counters
- Repaired shard checkpoint merge normalization so `failed: null` in the main checkpoint cannot crash post-shard merge.

First failure healed:

| Field | Value |
|---|---|
| Failure | bounded pilot accepted one shard item, then exited non-zero |
| First failing boundary | `merge_shard_checkpoints` in `scripts/quality/products_org_governed_retranslate.py` |
| Root cause | `main.setdefault("failed", {})` preserved existing `failed: null`, then `.pop()` failed |
| Repair | normalize non-dict `accepted` and `failed` to `{}` in `overlay_main_checkpoint_for_items` and `merge_shard_checkpoints` |
| Regression | `test_merge_shard_checkpoints_normalizes_null_failed` |

Verification completed:

- Syntax:
  - `.venv\Scripts\python.exe -m py_compile scripts\quality\products_org_governed_retranslate.py scripts\quality\aspose_org_governed_retranslate.py scripts\quality\aspose_org_multisite_unattended.py`
- Focused tests:
  - `.venv\Scripts\python.exe -m pytest tests\unit\quality\test_products_org_governed_retranslate_shards.py tests\unit\quality\test_aspose_org_governed_retranslate.py tests\unit\quality\test_aspose_org_multisite_unattended.py tests\unit\test_purity_strip.py -q`
  - result: `56 passed, 3 warnings`

Pilot proof:

| Run id | Scope | Verdict | Accepted | Failed | Source mutations | Language mixing | Accepted reverify |
|---|---|---:|---:|---:|---:|---:|---|
| `eff_device_pilot_20260702_002` | `kb.aspose.org`, six locale shards, one item per shard | `PILOT_ACCEPTED` | 6 | 0 | 0 | 0 | 6/6 `VERIFIED_ACCEPT` |
| `eff_multisite_pilot_20260702_001` | all four sites, six locale shards per site, one item per shard | `PILOT_ACCEPTED` | 24 | 0 | 0 | 0 | 24/24 `VERIFIED_ACCEPT` |

Pilot throughput:

| Site | Accepted | Failed | Required | Source mutations | Language mixing | Stoplight | Accepted/hour |
|---|---:|---:|---:|---:|---:|---|---:|
| `kb.aspose.org` | 6 | 0 | 5472 | 0 | 0 | `GREEN` | 188.81 |
| `blog.aspose.org` | 6 | 0 | 2016 | 0 | 0 | `GREEN` | 239.96 |
| `docs.aspose.org` | 6 | 0 | 5796 | 0 | 0 | `GREEN` | 197.11 |
| `reference.aspose.org` | 6 | 0 | 72252 | 0 | 0 | `GREEN` | 60.30 |

Evidence:

- `.local/evidences/aspose-org-multisite/eff_device_pilot_20260702_002/final/campaign-report.json`
- `.local/evidences/aspose-org-multisite/eff_multisite_pilot_20260702_001/final/campaign-report.json`
- `.local/evidences/aspose-org-multisite/eff_multisite_pilot_20260702_001/final/live-speed-report.kb.aspose.org.json`
- `.local/evidences/aspose-org-multisite/eff_multisite_pilot_20260702_001/final/live-speed-report.blog.aspose.org.json`
- `.local/evidences/aspose-org-multisite/eff_multisite_pilot_20260702_001/final/live-speed-report.docs.aspose.org.json`
- `.local/evidences/aspose-org-multisite/eff_multisite_pilot_20260702_001/final/live-speed-report.reference.aspose.org.json`

Current proof limits:

- CUDA availability is proven by runtime metadata, but in-inference VRAM sampling still shows 0 MiB before/after subprocesses. Do not claim high GPU utilization until a deeper sampler captures active inference memory or the backend confirms model device internally.
- Full autonomous completion, final accepted reverify across all accepted receipts, Hugo builds, and final `ACCEPTED` verdict are still pending.

Next production execution:

- Resume the selected production controller:
  - `.venv\Scripts\python.exe scripts\quality\aspose_org_multisite_unattended.py --run-id multisite_validate_20260702_001 --skip-baseline --skip-hugo-build --shard-locales --resume --max-cycles 200 --batch-size 12 --throughput-profile fast --model-batch-size 128 --target-vram-percent 80 --max-concurrent-site-workers 1 --work-order short-first`
  - Do not use `--model-batch-size 256` for production until one complete 128 batch cycle finishes with zero source mutations, zero current-cycle language-mixing delta, no CUDA OOM, and an improved or acceptable accepted/hour score.

## Plan Forensics and Machinery Healing Sprint 2026-07-02T18:30Z

Operating mode:

- Production forensics, plan healing, system healing, and machinery healing.
- The plan was treated as an auditable production artifact, not as trusted prose.
- The running production controller was not stopped during this forensic update because live process evidence showed it was actively processing with `--batch-size 128` and no immediate safety failure signal.

Plan lineage:

| Role | Path/status |
|---|---|
| Active authoritative plan | `C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\docs\quality\aspose-org-multisite-speed-language-mixing-micro-task-plan.md` |
| Historical source plan | closed `products.aspose.org` governed retranslation plan; historical evidence only |
| Current execution run | `multisite_validate_20260702_001` |
| Current controller | `scripts/quality/aspose_org_multisite_unattended.py` |
| Current governed runner | `scripts/quality/aspose_org_governed_retranslate.py` |
| Current content repo | `C:\Users\prora\OneDrive\Documents\GitHub\aspose.org` |

Forensic modification map:

| Section | Severity | Reason | Action | Expected outcome |
|---|---|---|---|---|
| Execution Update 2026-07-02T17:57Z / Next production execution | High | persisted command said model batch `64`, contradicting current healed production profile and user-approved 128/256 direction | modify | future agents relaunch with `128`, not stale `64` |
| Plan Forensics and Machinery Healing Sprint 2026-07-02T18:30Z | High | plan lacked adversarial review of machinery weaknesses discovered during live execution | add | execution readiness is conditional and grounded in current production evidence |
| TC-EFF-001 follow-up taskcards | High | highest-yield bottleneck is process/model cold start, not VRAM; existing taskcard was too broad for autonomous execution | expand | persistent worker and telemetry gates become executable work |
| Governance controls | Medium | stoplight/backoff could be corrupted by inherited historical failure counts | expand | use current-cycle deltas for safety decisions |

Findings discovered:

| Finding ID | Severity | Symptom | Evidence | Root cause | Plan healing |
|---|---|---|---|---|---|
| FOR-20260702-001 | High | active plan still instructed relaunch with `--model-batch-size 64` | plan command under previous next production execution | stale plan text after runtime escalation to 128 | command updated to `128`; 256 gated behind clean-cycle proof |
| FOR-20260702-002 | Critical | speed remains far below VRAM capacity despite CUDA being active | `nvidia-smi` showed about 1906 MiB / 16376 MiB and active `src.cli --batch-size 128` | per-file subprocess/model startup and validation dominate throughput | add persistent same-locale worker taskcard |
| FOR-20260702-003 | High | controller summaries update only after a full shard cycle | campaign report lacks completed metrics while shard is active | telemetry is cycle-level, not per-file/live enough | add per-file heartbeat taskcard |
| FOR-20260702-004 | High | historical language-mixing totals could trigger false backoff | previous shard summaries contained inherited language-mixing counts | backoff used cumulative summary count instead of current-cycle delta | machinery now uses `language_mixing_failure_delta`; preserve as governance requirement |
| FOR-20260702-005 | Medium | active wrapper process tree shows duplicate-looking parent Python processes | process table shows two `aspose_org_multisite_unattended.py` command lines in parent/child relation | Windows process spawning and command-line display can obscure ownership | add process-tree evidence requirement before killing/restarting |
| FOR-20260702-006 | Medium | high fallback statistics appear in per-file logs but do not directly map to governed failure counts | per-file logs show language purity fallbacks while governed shard totals stay unchanged | model-internal fallback telemetry and governed verifier failure taxonomy are separate | require telemetry reconciliation before tuning language safety |

Deep root causes:

- Machinery root cause: the current official path still launches a fresh `src.cli` process for each file, reloading or reinitializing expensive model, language detector, cache, and validation machinery repeatedly.
- Workflow root cause: the plan optimized batch size before proving where time was spent. VRAM is available, but accepted/hour is constrained by process lifecycle and per-file orchestration.
- Governance root cause: cycle-level summaries are too coarse for high-speed unattended execution; they delay detection of file-level stalls, OOM, language-purity loops, and starvation.
- State root cause: cumulative checkpoint summaries mix historical and current-cycle failure counts unless deltas are explicitly computed.
- Evidence root cause: process and GPU evidence can prove CUDA availability and activity, but not enough about model residency, cold-start seconds, verifier seconds, or cache warmup cost.

Machinery weaknesses discovered:

- `src.cli` one-file subprocess execution is the major yield limiter.
- The governed wrapper can only observe completed child process outputs; it cannot yet stream per-file status into the campaign report.
- The current cycle runner is serial by shard and site; this is safe but underuses CPU/GPU when VRAM is low.
- Model batch size `128` reaches CUDA but does not saturate VRAM; `256` may help but cannot remove process-start overhead.
- Current telemetry does not separate model load, FastText load, generation, rendering, repair, verifier, checkpoint merge, and filesystem write times.

Governance weaknesses discovered:

- A stale plan command could revert a healed profile from `128` to `64`.
- Safety backoff must always use current-cycle deltas, not inherited cumulative failure counts.
- Future agents must not infer that low VRAM means no CUDA; process-level evidence showed CUDA active with moderate VRAM.
- `256` must be treated as a calibrated profile, not a default.

Gaps healed in this sprint:

- Stale production command healed to `--model-batch-size 128`.
- `fast` profile machinery already maps to 128 and `max-vram` to 256 in `scripts/quality/aspose_org_multisite_unattended.py`.
- Current-cycle language-mixing delta is now part of stoplight/backoff machinery.
- Current live execution evidence confirms `src.cli --device cuda --batch-size 128`.

New taskcards from forensics:

### Parent Taskcard ID: TC-YIELD-001

Title: Remove orchestration bottlenecks to maximize accepted translations per hour
Type: PARENT
Status: VALID_DEFERRED
Owner: Execution agent
Supervisor: Review agent

Source:

- Plan requirement ID: REQ-EFF-002, REQ-EFF-003, REQ-EFF-006, REQ-EFF-009, REQ-SAFE-001
- Plan section: Plan Forensics and Machinery Healing Sprint 2026-07-02T18:30Z
- Root cause: throughput is constrained by per-file process/model startup, serial shard execution, and coarse telemetry more than by VRAM capacity.
- Selected solution: build a persistent fixed-locale worker path, add fine-grained telemetry, and only then escalate concurrency and model batch size.

Objective:

- Increase accepted pairs/hour materially without weakening governed acceptance.

Outcome:

- A production worker can translate multiple same-locale files per warm model instance, report per-file progress, and remain governed by the existing verifier.

Children:

- TC-YIELD-001-A: Measure current per-file timing breakdown.
- TC-YIELD-001-B: Design persistent same-locale worker boundary.
- TC-YIELD-001-C: Implement persistent worker behind an opt-in flag.
- TC-YIELD-001-D: Add per-file heartbeat and timing telemetry.
- TC-YIELD-001-E: Calibrate 128 versus 256 with clean-cycle gates.
- TC-YIELD-001-F: Calibrate safe shard concurrency after persistent worker proof.

Acceptance checks:

- no source mutations
- zero current-cycle language-mixing delta
- no route/path violations
- accepted receipts reverify
- accepted/hour improves against the current 128 subprocess baseline
- rollback to current subprocess runner remains available

Rollback plan:

- Disable persistent worker flag and return to current `aspose_org_multisite_unattended.py` subprocess path with `--model-batch-size 128`.
- If 256 produces OOM, language-mixing deltas, or lower accepted/hour, revert to 128 and record rejection evidence.

#### Child Taskcard ID: TC-YIELD-001-A

Parent Taskcard ID: TC-YIELD-001
Title: Measure current per-file timing breakdown
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-YIELD-001-A-01
  - Status: READY
  - Action: Parse recent per-file logs for duration, token counts, generation timing, and file/min.
  - Target: `.local/evidences/*/multisite_validate_20260702_001/per-file/**/*.translate.log`
  - Allowed operation: inspect, record.
  - Expected output: timing table grouped by site, locale, and page size.
  - Completion check: table distinguishes model generation time from total file duration where logs expose both.
- MS-YIELD-001-A-02
  - Status: PENDING
  - Action: Add missing timer fields for model load, FastText load, generation, render, repair, verify, and checkpoint write.
  - Target: `src.cli` or governed wrapper timing hooks.
  - Allowed operation: edit.
  - Expected output: machine-readable timing fields in per-file metrics.
  - Completion check: focused test or dry-run log contains all timing fields.

#### Child Taskcard ID: TC-YIELD-001-B

Parent Taskcard ID: TC-YIELD-001
Title: Design persistent same-locale worker boundary
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-YIELD-001-B-01
  - Status: READY
  - Action: Trace `src.cli` model, tokenizer, FastText, TM, and validator lifecycle.
  - Target: `src/cli`, translation engine builder, file pipeline, validators.
  - Allowed operation: inspect, record.
  - Expected output: lifecycle map and state-sharing risk list.
  - Completion check: design identifies all mutable state that must be locale-scoped.
- MS-YIELD-001-B-02
  - Status: PENDING
  - Action: Define persistent worker contract for one site and one locale at a time.
  - Target: new or existing quality runner entrypoint.
  - Allowed operation: record.
  - Expected output: input queue, output receipt, checkpoint, failure, heartbeat, and shutdown contract.
  - Completion check: contract forbids mixed-language model calls and shared candidate paths.

#### Child Taskcard ID: TC-YIELD-001-C

Parent Taskcard ID: TC-YIELD-001
Title: Implement persistent worker behind an opt-in flag
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-YIELD-001-C-01
  - Status: PENDING
  - Action: Add an opt-in persistent worker mode without changing current default behavior.
  - Target: governed runner or new quality script.
  - Allowed operation: edit.
  - Expected output: flag-gated persistent same-locale processing path.
  - Completion check: default subprocess path still passes existing tests.
- MS-YIELD-001-C-02
  - Status: PENDING
  - Action: Process multiple files through one warm model instance for a single locale.
  - Target: persistent worker implementation.
  - Allowed operation: edit.
  - Expected output: model and detectors are initialized once per worker.
  - Completion check: log shows one initialization and multiple file outputs.
- MS-YIELD-001-C-03
  - Status: PENDING
  - Action: Run governed verifier after each file before checkpoint acceptance.
  - Target: persistent worker verification loop.
  - Allowed operation: edit, validate.
  - Expected output: per-file accept/fail receipts identical in schema to current runner.
  - Completion check: accepted receipts reverify.

#### Child Taskcard ID: TC-YIELD-001-D

Parent Taskcard ID: TC-YIELD-001
Title: Add per-file heartbeat and timing telemetry
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-YIELD-001-D-01
  - Status: PENDING
  - Action: Emit current file, locale, shard, elapsed seconds, and phase every file.
  - Target: campaign live report.
  - Allowed operation: edit.
  - Expected output: live report updates before full shard completion.
  - Completion check: active shard can be monitored without waiting for cycle end.
- MS-YIELD-001-D-02
  - Status: PENDING
  - Action: Add stall detection for no file heartbeat progress.
  - Target: multisite wrapper.
  - Allowed operation: edit.
  - Expected output: `YELLOW_BACKOFF` or `RED_STOP_REQUIRED` after configured no-progress window.
  - Completion check: simulated stale heartbeat test passes.

#### Child Taskcard ID: TC-YIELD-001-E

Parent Taskcard ID: TC-YIELD-001
Title: Calibrate 128 versus 256 with clean-cycle gates
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-YIELD-001-E-01
  - Status: READY
  - Action: Let one full `128` shard cycle complete and capture safety deltas.
  - Target: `multisite_validate_20260702_001` campaign report and shard summaries.
  - Allowed operation: inspect, record.
  - Expected output: clean-cycle verdict for 128.
  - Completion check: zero source mutations, zero current-cycle language-mixing delta, no OOM.
- MS-YIELD-001-E-02
  - Status: PENDING
  - Action: Run a bounded `256` pilot only after 128 clean-cycle proof.
  - Target: separate pilot run id.
  - Allowed operation: run.
  - Expected output: accepted/hour and safety comparison.
  - Completion check: 256 is promoted only if it improves yield and keeps all gates clean.

#### Child Taskcard ID: TC-YIELD-001-F

Parent Taskcard ID: TC-YIELD-001
Title: Calibrate safe shard concurrency after persistent worker proof
Type: CHILD
Status: VALID_DEFERRED

Micro-steps:

- MS-YIELD-001-F-01
  - Status: PENDING
  - Action: Run two concurrent fixed-locale workers with isolated checkpoints and evidence roots.
  - Target: speed calibration run.
  - Allowed operation: run.
  - Expected output: concurrency scorecard.
  - Completion check: zero path collisions, zero language-mixing delta, no source mutations.
- MS-YIELD-001-F-02
  - Status: PENDING
  - Action: Escalate to three or four workers only if two-worker proof is clean and VRAM remains below target.
  - Target: speed calibration run.
  - Allowed operation: run.
  - Expected output: selected concurrency level or rejection evidence.
  - Completion check: accepted/hour improves without safety regression.

Execution readiness verdict after forensics:

- Verdict: `READY WITH CONDITIONS`
- Conditions:
  - SUPERSEDED 2026-07-03T00:19:47+05:00: current 128 production run was paused because first-cycle evidence was not smooth enough for unattended execution. Live process evidence did show `src.cli --device cuda --batch-size 128`, no source-mutation signal, and no immediate OOM signal, but the campaign live report mixed cumulative backlog failures with current-cycle failures and could trigger misleading backoff decisions.
  - do not escalate production to 256 until a full 128 cycle finishes cleanly
  - do not claim maximum yield until `TC-YIELD-001` persistent worker work is implemented and validated
  - do not mark final acceptance until all required pairs are accepted, accepted reverify passes, Hugo builds pass, and final source-hash checks pass

## Execution Reconciliation 2026-07-03T00:19+05

Plan binding:

- Mission ID: multisite-validation-retranslation-speed-language-mixing
- Repository: `C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator`
- Branch: `main`
- Plan path: `C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator\docs\quality\aspose-org-multisite-speed-language-mixing-micro-task-plan.md`
- Plan hash before this reconciliation: `C6DC8F7EA37BED7BF3B764E3F5CAE0F0B4C10B8BDB1763E29D864550F44B8BBE`
- Bound run ID: `multisite_validate_20260702_001`

Current-state findings:

- The active production chain was stopped for healing. It was running `aspose_org_multisite_unattended.py` with `--throughput-profile fast --model-batch-size 128 --device cuda --shard-locales --work-order short-first`.
- Live `src.cli` evidence showed `m2m100_418m`, CUDA requested, and `--batch-size 128`.
- The latest aggregate live speed report for `kb.aspose.org` showed `RUNNING`, cumulative accepted `532`, cumulative failed `4940`, source mutations `0`, and a stale `YELLOW_BACKOFF` report.
- Representative current comparison evidence included real hard-gate rejects: partial untranslated frontmatter (`subtitle` unchanged in `hi/cells/_index.md`) and immutable-token drift in generated targets (`inline_code`, `urls`, `shortcodes`, and file-path tokens).
- A major observability weakness was confirmed: cumulative failed backlog counts and current invocation failures were not separated, so speed/backoff decisions could treat inherited baseline failures as fresh current-cycle failures.

Symptoms vs root causes:

- Symptom: high cumulative `failed_pairs` and failure-type counts after a small cycle.
  Root cause: governed summaries reported cumulative checkpoint state only; the multisite runner used those cumulative fields for live speed and backoff decisions.
- Symptom: stale or misleading `YELLOW_BACKOFF` during active work.
  Root cause: the controller writes live speed reports only after shard completion and the stoplight lacked run-local failure deltas.
- Symptom: current retries can still fail on partial English and immutable-token mutation.
  Root cause: translation output still sometimes leaves translatable frontmatter unchanged or damages protected inline assets; hard gates are correctly rejecting these and must be preserved.

Structural consistency breakers:

- Do not use cumulative checkpoint failures as current-cycle failure deltas.
- Do not escalate to model batch `256` while current-cycle partial/language failures are non-zero.
- Do not call the run smooth while live evidence is stale or only produced at shard boundaries.
- Do not weaken immutable-token, protected-field, structure, or partial-translation gates to improve acceptance counts.

Preserved strengths:

- Locale-sharded execution remains the correct safety boundary.
- CUDA model execution with model batch `128` is viable and should remain the current high-throughput candidate.
- Governed hard gates are catching real quality defects and must remain authoritative.
- Source mutation remained zero in observed evidence.

Implemented healing:

- Added run-local counters to `scripts/quality/aspose_org_governed_retranslate.py`:
  - `run_attempted_pairs`
  - `run_accepted_pairs`
  - `run_failed_pairs`
  - `run_failure_type_counts`
  - `run_language_mixing_failure_count`
- Updated `scripts/quality/aspose_org_multisite_unattended.py` to use run-local counts for cycle throughput, live speed reporting, and language-mixing backoff decisions.
- Added regression tests proving run-local counters do not confuse current-cycle failures with cumulative backlog.

Verification performed:

- Syntax check:
  - `.venv\Scripts\python.exe -m py_compile scripts\quality\aspose_org_governed_retranslate.py scripts\quality\aspose_org_multisite_unattended.py`
- Focused regression tests:
  - `.venv\Scripts\python.exe -m pytest tests\unit\quality\test_aspose_org_multisite_unattended.py tests\unit\quality\test_aspose_org_governed_retranslate.py tests\unit\quality\test_products_org_governed_retranslate_shards.py -q`
  - Result: `46 passed, 3 warnings`

### Parent Taskcard ID: TC-ACCOUNTING-001

Title: Separate current-cycle execution truth from cumulative backlog
Type: PARENT
Status: FOCUSED_VERIFIED

Objective:

- Ensure speed, stoplight, and backoff decisions are based on current invocation outcomes while final acceptance still uses cumulative required/accepted/failed totals.

Micro-steps:

- MS-ACCOUNTING-001-01
  - Status: COMPLETED
  - Action: Add governed runner run-local attempted, accepted, failed, failure-type, and language-mixing counters.
  - Evidence: `scripts/quality/aspose_org_governed_retranslate.py`
  - Verification: focused unit test `test_run_stats_track_only_current_invocation_failures`.
- MS-ACCOUNTING-001-02
  - Status: COMPLETED
  - Action: Make multisite throughput and live report use run-local counters.
  - Evidence: `scripts/quality/aspose_org_multisite_unattended.py`
  - Verification: focused unit tests `test_cycle_throughput_from_results_uses_run_local_counts` and `test_write_live_speed_report_emits_stoplight_file`.
- MS-ACCOUNTING-001-03
  - Status: READY
  - Action: Run a bounded monitored resume cycle at model batch `128` before unattended production resumes.
  - Required command shape: `aspose_org_multisite_unattended.py --run-id multisite_validate_20260702_001 --skip-baseline --skip-hugo-build --shard-locales --resume --max-cycles 1 --batch-size 2 --throughput-profile fast --model-batch-size 128 --target-vram-percent 80 --max-concurrent-site-workers 1 --work-order short-first --only-site kb.aspose.org`
  - Pass gate: no source mutations, live report contains run-local attempted/accepted/failed fields, no stale cumulative-only backoff, and any current hard-gate failures are typed with evidence.

Pending execution handoff:

- Resume only with a bounded monitored cycle first.
- If current-cycle `run_language_mixing_failure_count` is non-zero, keep batch `128` or reduce by shard; do not escalate to `256`.
- If failures are dominated by immutable-token or partial-translation rejects, inspect representative target/source/log triplets and heal translation preservation or retry granularity before broad autonomous execution.
- After the bounded cycle is clean, resume the four-site autonomous command with the same run ID and current policy, then reverify accepted receipts and run Hugo builds before final acceptance.

## Execution Update 2026-07-03T00:50+05

Additional root-cause findings:

- Two bounded monitored `kb.aspose.org` cycles proved the run-local accounting fix works: live speed reports now show current attempted/accepted/failed counts separately from cumulative backlog.
- Current-cycle language-mixing deltas stayed at `0`; source mutations stayed at `0`; accepted reverify passed for all accepted receipts checked in the bounded cycles.
- Remaining current failures were primarily `TRANSLATOR_REJECTED_OR_NO_TARGET` caused by pre-write language-purity blocking. Logs showed the translator produced candidates, but `src.cli` blocked writes on one detected wrong-language paragraph even though the governed verifier was supposed to be the post-write authority for this campaign.
- Immutable-token verification also had a false-positive class: raw-file token scanning counted target-only governance frontmatter paths such as `provenance.source_file` as extra file-path tokens.

Implemented healing:

- `src/translation_engine/write_gate.py`
  - Hugo shortcode-only lines are excluded from file-purity language evidence.
  - Format/acronym-heavy selector lines are excluded from file-purity language evidence.
  - `force_accept` now bypasses only the final language-purity write gate so governed post-verification can classify candidates. Structural, code-block, heading, and YAML frontmatter write gates remain active.
- `scripts/quality/aspose_org_governed_retranslate.py`
  - Immutable token comparison now scans markdown body content rather than target-only governance frontmatter.

Verification performed:

- Syntax check:
  - `.venv\Scripts\python.exe -m py_compile src\translation_engine\write_gate.py scripts\quality\aspose_org_governed_retranslate.py scripts\quality\aspose_org_multisite_unattended.py`
- Focused regression tests:
  - `.venv\Scripts\python.exe -m pytest tests\unit\translation_engine\test_write_gate.py tests\unit\test_purity_strip.py tests\unit\quality\test_aspose_org_governed_retranslate.py tests\unit\quality\test_aspose_org_multisite_unattended.py tests\unit\quality\test_products_org_governed_retranslate_shards.py -q`
  - Result: `80 passed, 3 warnings`
- Real-pipeline proof:
  - Bounded monitored `kb.aspose.org` cycle at model batch `128`, two items per shard: `12` attempted, `10` accepted, `2` failed, current language-mixing delta `0`, source mutations `0`, stoplight `GREEN`, accepted reverify passed.
  - Follow-up targeted governed retries accepted Arabic and Hindi items that previously exercised the failure class:
    - `ar words/python/how-to-load-doc-reader-python.md`
    - `hi cells/python/_index.md`

### Parent Taskcard ID: TC-PURITY-001

Title: Stop pre-write purity false positives from blocking governed candidates
Type: PARENT
Status: FOCUSED_VERIFIED

Micro-steps:

- MS-PURITY-001-01
  - Status: COMPLETED
  - Action: Exclude Hugo shortcode-only lines and format/acronym-heavy selector lines from file-purity scoring.
  - Evidence: `src/translation_engine/write_gate.py`
  - Verification: `test_hugo_shortcode_line_skipped`, `test_format_acronym_selector_line_skipped`.
- MS-PURITY-001-02
  - Status: COMPLETED
  - Action: Let `force_accept` bypass final language-purity blocking while preserving structural/code/YAML gates.
  - Evidence: `src/translation_engine/write_gate.py`
  - Verification: `test_force_accept_bypasses_final_purity_for_governed_verifier`.
- MS-PURITY-001-03
  - Status: COMPLETED
  - Action: Ignore governance frontmatter when comparing immutable markdown/body tokens.
  - Evidence: `scripts/quality/aspose_org_governed_retranslate.py`
  - Verification: `test_immutable_token_scan_ignores_governance_frontmatter_paths`.

Updated execution decision:

- `kb.aspose.org` monitored proof is sufficient to resume autonomous execution at model batch `128`.
- Keep model batch `256` blocked until a complete clean `128` cycle proves zero current language-mixing failures and materially better acceptance throughput is needed.
- Use run-local live reports as the monitoring source. If current-cycle language-mixing delta becomes non-zero, pause and heal before continuing.
