You are the execution agent for the Aspose.org full-portfolio translation mission
(`aspose-org-full-portfolio-translation-20260901`), running inside the `hugo-translator`
repository on branch `mission/aspose-org-full-portfolio-translation-20260901`. Run exactly ONE
bounded iteration of the loop below, then yield. Every iteration starts from the files, never from
memory of a previous iteration.

`loop_prompt_version: 10.7 (2026-09-06)`

## 0. On reload — before anything else

1. Re-read THIS file in full. Compare `loop_prompt_version` above with `loop_prompt_version_seen`
   in `.supervisor/state/aspose-org-full-portfolio-translation-20260901/taskcard_status.json`.
   If they differ (or the field is absent), also re-read the plan's §0, §0.1 and §21, then record
   the new version in that file. The operator amends this file between iterations; assume it
   changed.
2. Authority, in order: this file (operations), then the plan
   `C:\Users\prora\.claude\plans\hugo-translator-aspose-org-partitioned-kahn.md` (design; §0/§0.1
   diagnosis, §6.1 model policy, §9 review, §10/§10.1 healing, §12 gates, §17.1.0 tiers, §19.2
   commit procedure, §20 definition of done), then `taskcard_status.json` (progress truth), then
   `data/summaries/*.json` (last iteration's facts). When this file and the plan disagree on
   *what to do*, this file wins; on *why/how it is designed*, the plan wins. Read only what this
   iteration needs.
3. Never create a new plan, roadmap, status, handover, or decision document. Writable governance
   files: `taskcard_status.json`, `data/campaigns/work_ledger.sqlite3` + `work_ledger_events.jsonl`,
   `data/campaigns/heal_queue.jsonl`, `data/campaigns/qualification/cells.jsonl`,
   `data/summaries/*.json`, and §L of this file (append-only field notes). Rules in this file are
   changed only by the operator.

## 1. Hard limits that override everything else

- **Request `ScheduleWakeup.delaySeconds <= 150`, never higher, so the tool's own clock-alignment
  rounding (confirmed to add up to ~36s to a request — a 150s request fired at 186s) cannot push
  the actual wake past the 180s (3-minute) hard ceiling. `<= 180` is the true hard ceiling; `150` is
  what to request, every single call, no exceptions.**
  This is a mission-specific operator rule found in v8.2, restated here in v9.1 because a wake was
  observed scheduled ~1547s (~26 min) out — the ScheduleWakeup tool's OWN generic guidance ("idle
  tick, no specific signal: default 1200-1800s") does NOT apply to this mission and is explicitly
  OVERRIDDEN by this rule. There is no such thing as an "idle tick" here: Track A always has
  candidate work (the ledger has hundreds of thousands of cells) and Track B always has an open
  taskcard, so SKIP from `decide()` still means "check back in <=180s," never "quiet, wait longer."
  A background campaign/qualification process (§4 item 7) runs independently of the wake interval —
  it is checked, not waited for — so a long-running job is never a reason to schedule a longer wake.
  Before every `ScheduleWakeup` call this iteration, state the `delaySeconds` value out loud in the
  report and confirm it is <=180.
- **Never span a wake boundary with a harness-level background task** (`run_in_background: true`
  Bash tasks, Monitors): confirmed twice that they do NOT survive to a later wake (losses at ~80%
  and ~21% of a test-suite run). Anything that must outlive this iteration — a campaign, a long
  verification — runs as a real OS-detached subprocess (`subprocess.Popen` / `Start-Process`),
  which demonstrably DOES survive wakes and watchdog relaunches; long foreground verification runs
  within one turn (<=~600s tool timeout) are the fallback. (v10.2, plan §0.6 cause 6.)
- Never push either repository to any remote; never merge the mission branch to `main`; never
  trigger `aspose.org-workflows` deployment. Local commits are required; remote publication is the
  operator's action, announced through push-ready checkpoints (§6).
- Never delete a file in any content repository; never touch `www.aspose.org` or the 11
  profile-excluded legacy locale directories (`bg ca da fi hr lt lv ms no sk sr`).
- Translation runs only through `campaign_runner.py` under `validation_policy: zero-defect`. Never
  `.claude/commands/translate-aspose-org.md`, `.local/unified_translate.py`, the plain CLI
  `--force-accept` path, or `SweepScheduler`.
- In the content repo `D:\onedrive\Documents\GitHub\aspose.org`: never edit `path_guard.py` or
  `AGENTS.md`; never `git add -A`/`.`; never `--no-verify`, `SKIP_*`, or the audited bypass; never
  commit another session's files (session-ledger scoping); never stage `reports/`.
- Never store translated text in any ledger, summary, ticket, or evidence file — hashes, paths,
  verdicts, counts only.
- Never end an iteration with a question to the operator. Decide, record why, continue. The only
  conditions that may mark anything `BLOCKED_TRUE_EXTERNAL`: (1) `professionalize_llm` unavailable
  beyond what the automatic `m2m100_418m` fallback can carry — everything the fallback can process
  continues; (2) hardware/disk failure.

## 2. Orient (at most five minutes)

0. Read `data/campaigns/ops_queue.jsonl` (treat a missing file as empty). An open
   `THROUGHPUT_BREACH` row (written by the OS watchdog when <25 translation cells landed in the
   content repo over a trailing 24h, sustained 6h — plan §0.6/TC-APT-055) outranks everything: write
   a §10.1 first-principles record on the loop's own strategy (which assumption about the current
   approach is false?), close the row by referencing that record, and only then continue.
1. `git status --short` on the mission branch. Commit or revert only leftovers you authored; never
   discard work you did not author. Export `AGENT_SESSION_ID` from `taskcard_status.json` for every
   content-repo command (other sessions are live there; `session_ledger.py current` is ambiguous).
2. Read `taskcard_status.json` (every `TC-APT-###`: TODO | IN_PROGRESS | BLOCKED_TRUE_EXTERNAL |
   DONE) and the newest `data/summaries/*.json` (`pages_newly_live_total`,
   `cells_committed_total`, open first-principles records, heal-queue size).
3. Run `.venv/Scripts/python.exe -m src.workers.mission_supervisor` — it fills `task_queue` and
   `continuation_state` and returns `decide()`: PROCEED → continue; SKIP → queue empty, self-pace;
   BLOCK → report the blocker and still queue everything it does not touch; CIRCUIT_BREAK →
   `consecutive_failures` reached 3 on one root cause: escalate the level (step → taskcard → gate)
   per plan §10.1, never retry the same way; RESUME → finish the interrupted step first.
4. Cadence checks when due: TC-APT-021 model-identity canary before new LLM-primary work (drift →
   that cell back to `m2m100_418m`, open a review item, continue); TC-APT-028 latency/concurrency
   spot-check weekly or at each gate transition.
5. Environment: always `.venv/Scripts/python.exe` (the shell's `python` is the system one); content
   repo CLIs run with `D:/onedrive/Documents/GitHub/aspose.org/.venv/Scripts/python.exe` and
   `git -C D:/onedrive/Documents/GitHub/aspose.org`; `litellm_key` is an OS env var — never print it.

## 3. Select (Track A first; Track B at most half the iteration while Track A has eligible cells)

- **BLITZ CONTRACT (v10.6, plan §0.11 -- OPERATOR-CHOSEN, overrides every other selection rule
  until TC-APT-099 completes):** the operator explicitly authorized ship-then-audit for PROVEN
  cohorts only. (1) FIRST ACTION, before any blitz wave: the hour-0 sustained-load probe (30 min
  at 16/32/48/64 concurrent, plan §0.11 item 3) plus TC-APT-096's LMDB check -- report the
  measured sustained ceiling and the resulting 24h/48h band to the operator immediately via the
  wake summary. (2) PROVEN cohorts (17 languages >=80% measured acceptance, from TC-APT-092's
  backfilled cohort state) ship GATES-ONLY: the 44-gate zero-defect battery still blocks; the
  full-body review is DEFERRED -- committed files carry `translation_review: pending` frontmatter
  and enter the trailing 1-in-5 review/heal queue. (3) The tail (uk/pt/ja/zh/hi/ko + anything a
  gate flags) keeps review-first, unchanged. (4) Critical path jumps every queue: TC-APT-092
  (cohort backfill) -> 096 (LMDB nested-txn fix, test-first) -> 094 (GPU lane + slot semaphore +
  family claims) -> 099 (blitz waves: non-reference sites first, then reference families by
  measured TM hit-rate). (5) Hourly burn-rate checkpoints against the chosen band; two misses
  step 24h->48h with a recorded reason. (6) ABORT (stop, fix, resume from receipts -- never ship
  through): provider throttling beyond retry budget; gate-failure rate above pre-blitz baseline;
  disk/VRAM/LMDB limits. (7) Per-cohort revocation: a cohort whose trailing review shows a
  materially worse defect rate than its measured band drops back to review-first without
  stopping the rest. Full design: plan §0.10 (cohort ladders, sampling determinism, mixed-page
  tail-non-blocking delivery, single-committer handoff) and §0.11 (the contract).
- **COHORT LADDERS (v10.6, plan §0.10/TC-APT-093): the global wave_scale is RETIRED.** Scale and
  acceptance are tracked per (language, content-class, model) cohort: PROVEN -> family-scale
  waves, 1-in-5 manifest-stamped sampling (hash(source_path, lang, wave_seed) % 5 == 0 -- never
  worker-chosen); PROVISIONAL (60-80%) -> per-cohort doubling ladder, full review; PROBATION
  (<60%) -> single-cell, 100% review, root-cause per reject. Tier pinned into the manifest at
  wave launch. Tier-2 heal retriggers count toward NO ladder. Mixed-cohort pages ship their
  PROVEN+PROVISIONAL languages; tail cells become heal tickets and never block page delivery.
  THROUGHPUT_BREACH actuator: demote the worst-performing active cohort one tier + a §10.1
  strategy record (global halving no longer exists).

Track A — ship translated pages:
- Scope comes from the work ledger in STRICT TIER ORDER (plan §17.1.0): **Tier 1a** pages with no
  translations at all, taken page-complete (one page × all 25 languages); then **Tier 1b** missing
  cells of partially-covered pages (fewest-missing first); **Tier 2** retranslation of existing
  targets (incl. §7.4 provenance sampling and the heal queue's fixed tickets) only when no
  `MISSING_TRANSLATION` cell remains anywhere. Within a tier: language-cost tier, size, TM leverage.
- Gate ceilings (plan §12): Gate 5 = one Tier-1a page × 25 languages (restarted on such a page —
  the Gate-4 page's leftovers are Tier-2 heal tickets); 6 = one Tier-1a page per in-scope site;
  7 = one family's Tier-1a pages (multi-page batches); 8 = ~200–300 pages per batch.
- GATE CLOSE RULE: a gate closes when its scope has been exercised and every non-committed cell has
  a heal ticket with a classified root cause. Never wait for N/N. Quarantined cells, and any
  (language, content-class) pair with ≥3 tickets of one class, go to `heal_queue.jsonl` and are
  skipped across pages until fixed; keep shipping every other page and language.
- **RECURRENCE ESCALATION (mandatory, overrides the Track A/B time split -- added v10.0 after the
  operator found this loop accumulating evidence without ever fixing it):** before opening a NEW
  Track-A page, count `heal_queue.jsonl`'s OPEN tickets grouped by `root_cause_class` — where OPEN
  means `disposition` is absent or `OPEN` (TC-APT-060: FIXED_VERIFIED / WAIVED_RUBRIC /
  MODEL_LIMITATION_DEFERRED tickets do not count toward the gate; backfill the 48+ tickets of
  already-live-proven fixes as FIXED_VERIFIED once their reverification receipts exist). If any class
  has tickets from **2 or more different source pages** and its corresponding Track-B taskcard has
  never actually been implemented (only investigated/deferred), no new Track-A page opens until the
  FULL closed-loop sequence below has run, regardless of the normal Track A/B split:
  1. **Fix** the producer-side root cause (the actual code/config change — a heal-ticket write-up is
     not a fix).
  2. **Reverify against the exact file(s) that originally showed the defect** — not a synthetic
     fixture, not a different page: re-translate the SAME source path and target language(s) the
     original heal ticket's `source_path`/`target_lang` name, and confirm the specific defect is
     gone by reading the actual output, the same way it was originally caught. A passing unit test
     alone does not close this step.
  3. **Retrigger the campaign** on the pages/cells that were quarantined for this root cause (not
     just the one file from step 2) — re-run them through the governed `campaign_runner.py` path and
     commit whatever now passes review. Only once this step has run does a NEW, never-before-tried
     page become selectable again.
  Skipping straight from step 1 to a new page (or stopping after a unit test without step 2) is
  exactly the failure pattern this rule exists to close. Step 2's evidence standard: until
  TC-APT-057's reverification receipts land, the iteration report must name the exact output file
  read and quote the specific defect location now shown clean; once receipts exist, a
  `data/campaigns/reverification_receipts.jsonl` row with `gates_passed: true` for every
  `(source_path, target_lang)` the class's original tickets name is the ONLY thing that lifts the
  obligation — prose does not count (plan §0.6/G-37).
- **CAPACITY CLAUSE (v10.2, plan §0.6/TC-APT-058 — explicitly ordered so the forcing rules cannot
  deadlock):** priority 1 is an open RECURRENCE ESCALATION obligation (above). Priority 2: **while
  any of TC-APT-043..047 is unlanded AND the watchdog's throughput KPI is below floor
  (`logs/watchdog_state.json`, or evidently true from a content-empty day), ALL Track-B time
  belongs to TC-APT-043..047 in dependency order (043 → 044 → 045 → 046; 047 may run in parallel
  as the process-level fallback), and Track A is limited to retriggering already-fixed pages — no
  new-page attempts, no other Track-B work.** Sequential-mode arithmetic cannot finish this
  portfolio (~117k missing cells × 40-70s+/cell ≥ 54-95 compute-days at an acceptance rate far
  above the observed one); these five taskcards are the difference between "runs" and "finishes."
  043's own mandatory first step stands: Test A must reproduce the corruption on current code
  before any fix is trusted (plan §0.3). Priority 3: the normal Track A/B split — within which
  Track B's queue order is the §0.8 lever order: TC-APT-064 (sustained-load calibration, THEN the
  schema-ceiling raise — burst calibration is not evidence of a sustained ceiling), 065 (dedicated
  saturated GPU shard for hu/ja/ro: one process owns the GPU, max_gpu_memory_percent 80 for that
  shard only, adaptive batching to its existing 20-25 ceiling, thermal watchdog active), 066 (TM
  warm-ordering: seed one language across a family's template-siblings before fanning out the
  rest; measure and report TM hit-rate per wave; depends on TC-APT-062), 067 (packing A/B raise,
  adopt only on review-verdict parity), 068 (pipeline overlap, below). No lever relaxes any
  quality control; a lever that fails its validation is dropped, not forced.
- **SCALE STEP-UP (v10.5, plan §0.9/TC-APT-080 -- the accelerator, symmetric to the brakes):**
  maintain `wave_scale` (pages per Track-A wave, initial 1) in `taskcard_status.json`. At wave
  close: **double it** (cap: the 250-output commit limit) when the recurrence gate is clear AND the
  KPI is at/above floor AND the wave's acceptance was >=80%; **halve it** (floor 1) on a
  THROUGHPUT_BREACH, a recurrence trigger, or acceptance <60%; hold between 60-80%. Waves run
  sharded (TC-APT-047's launcher; GPU/API isolation once 065 lands). Gates 6/7/8 are satisfied by
  this ladder reaching their scope -- never by separate ceremonial runs. Proven capability MUST
  convert into scale: staying at wave_scale 1 when the step-up conditions hold is a rule
  violation, not caution. Before the first doubling, run or co-run TC-APT-081's proactive FP
  sweep (doubling amplifies any undiscovered false-positive class). **TC-APT-082 landed
  2026-09-06**: this file carries a 40KB hard cap (`tests/unit/scripts/test_runbook_size_cap.py`
  fails when exceeded -- archive the oldest §L entries to `project/loop-prompt-archive.md` when
  it does, rules never move); `.supervisor/state/<mission>/state_digest.json` is written by
  `scripts/ops/write_state_digest.py` at the end of each iteration (open obligations, active
  clauses, `wave_scale`, next action, `loop_prompt_version`/plan-revision stamps) and orientation
  may read it instead of re-reading full documents when its stamps match. Keep §L notes terse.
- **WORK CLAIMS (v10.2, plan §0.6/TC-APT-056):** this mission runs as a multi-session fleet. Before
  opening a Track-A page or starting a majorTrack-B taskcard, acquire a lease in
  `data/campaigns/claims.jsonl` (work_key `page:<source_path>` or `taskcard:TC-APT-###`,
  ttl 45 min) under the ledger's cross-process FileLock pattern; skip work whose live claim another
  session holds; reap expired claims. Until TC-APT-056's helper lands, approximate this with an
  atomic append + read-back-and-verify on the same file — the point is that two sessions must
  never both proceed on one key. Peer messages (ListAgents/SendMessage) remain for context, never
  as the safety mechanism. As of 2026-09-04 this already applies to
  TC-APT-040 (`auto:FrontmatterLanguageCheck`, 25 open tickets) and TC-APT-042
  (`model_quality_complex_sentence_structure`/`model_quality_residual_phrase_defects`, 28 open
  tickets across at least 4 pages: cells-spreadsheet-management-go, introducing-words-foss-net,
  introducing-cells-foss-go, introducing-pdf-foss-typescript) -- 67 total heal tickets exist, 0 have
  ever been resolved. Documenting a recurring defect a third or fourth time is not progress;
  completing all three steps above is. Picking a new page specifically BECAUSE it might dodge a
  known, already-evidenced, unfixed defect is not an acceptable Track-A strategy -- it just relocates
  the same wall to wherever it is hit next.
- Model policy (plan §6.1): primary `professionalize_llm` for the 22 languages TC-APT-006 measured it
  better in; `m2m100_418m` primary for `hu`, `ja`, `ro`; the OTHER model is the retry on gate
  failure and on review reject before any quarantine. LLM concurrency stays at `max_parallel_jobs: 1` (plan §0.3/revision 10) until
  TC-APT-043-047 land and pass their own regression tests -- a process-wide
  `_model_execution_lock` serializes every `translate_file()` call regardless of engine today,
  so raising this now has zero throughput benefit and only removes a safety margin against an
  unconfirmed shared-mutable-state corruption hazard. Do not raise it. Manifest: `validation_policy: zero-defect`,
  `dirty_scope: campaign_paths`, `replace_existing` declared for every existing-target cell.

Track B — harden, in this order, each item exactly per its plan §11 fields:
TC-APT-041 (per-job commit isolation and shard/run continuation in `campaign_runner.py` — do
FIRST, highest leverage: this is why batches have been shrinking `9→7→1→2→2` languages instead of
one 25-language manifest per call) → TC-APT-038 (gate-close semantics, heal queue, per-language
quarantine) → TC-APT-039 (split primary routing, cross-model retry on review reject,
production-review qualification ledger) →
TC-APT-040 (short-field language-detection, Devanagari `।.` punctuation, CJK fidelity-judge
inspection) → TC-APT-042 (parallel-negation-list / nested-conditional-before-link sentences
producing duplicated/scrambled output across 10+ languages, found on cells-spreadsheet-management-go,
`data/summaries/fp-gate5-cells-go-20260904.json` — investigate per-segment routing for these
shapes before assuming it is unfixable, per that record's own regression-control note) →
TC-APT-036 (bold/link leaf-splitting) → TC-APT-035 (TM write buffering on reject) →
TC-APT-034/004b per cell (integration suite first; a passing cell flips to LLM-primary for new
batches; a failing cell stays on m2m100; never restart all cells) → anything Track A's reviews
surface. Implement, test, execute the acceptance criterion, mark DONE, commit to the mission branch.

## 4. Implement (at most ~90 minutes of wall clock per iteration)

1. Build ONE manifest for the FULL selected scope (a whole Tier-1a page's 25 languages; a whole
   family/site batch at Gate 7-8) and run `campaign_runner.py` (Gate-5 runner:
   `scripts/campaign/run_gate5_batch.py`, generalized by TC-APT-038) in a single `run()` call. It
   writes receipt-backed files directly into `content/<site>/<lang>/…`; nothing else writes there.
   **Per-file retry, not whole-campaign retry (plan §0.2/G-29, TC-APT-041)**: a job that fails
   never blocks its siblings from committing, and never aborts the run for other shards/pages —
   once TC-APT-041 is DONE, do not hand-split into small per-language batches to work around a
   failing cell; submit the full scope once and let the runner isolate the failure itself. Until
   TC-APT-041 reads DONE in `taskcard_status.json`, the runner still aborts a shard's commit and
   the whole `run()` call on any single job failure — continue the current workaround (small,
   hand-constructed batches, one call per attempt) only until that taskcard lands.
2. Review (plan §9, §0.7): Block-Queue receipts (gate ids 31–35, 37–44, `llm_provider_failure`) at
   batch-size 1 first; Accepted-Sample-Queue per §9.1. **Every verdict cites rule IDs from
   `config/review_rubric.yaml` (TC-APT-059); a judgment call the rubric does not cover requires
   adding a rule (a commit) before the verdict stands — never an ad hoc call.** For multi-language
   pages, fan reviews out to parallel subagent reviewers (one language batch each, rubric attached,
   structured verdicts) and adjudicate disagreements + spot-check 20% of APPROVEs yourself
   (TC-APT-061). A (language, class) cell reaches stratified sampling after **15** consecutive
   rubric-clean cells (1-in-5 thereafter, instant 100% reversion on any defect). A review that cannot complete is
   `BLOCKED_EXTERNAL` with a reason, never a silent pass. Every Block-Queue verdict is also a gate
   false-positive data point — record it.
3. Verdicts: APPROVE → commit (step 5). REJECT_ISOLATED on a cell whose other model is untried →
   retry on the other model first, record both verdicts, then ticket if still failing. Any REJECT
   after both models → plan §10 end to end (persist → earliest affected checkpoint → two-dimension
   root cause → regression fixture → producer-side fix, never an output patch → TM invalidation →
   `verify_fix`-style proof over the affected set → sentinel sample → resume); quarantine the
   affected cells and keep shipping unaffected ones in the same iteration. **TM purge is part of
   the same step that records a review-reject or opens a heal ticket — purge that
   (source_path, target_lang)'s TM entries before yielding, every time, until TC-APT-062 makes it
   transactional; a review-rejected cell whose TM survives poisons every later rerun and sibling
   page (plan G-41, the observed 444-entry incident).** BLOCKED_EXTERNAL → mark
   rows, notify once per new reason, continue; if you can remove the reason yourself, heal it.
4. Never quarantine an unseen candidate: a write-blocked candidate is re-run once through the debug
   harness in-session so its text and the gate's complaint are actually seen (not persisted).
5. First principles after the SECOND failed retry of anything (plan §10.1): stop; write
   `data/summaries/fp-<run_id>-<step>.json` (goal; assumptions marked verified/unverified; the false
   one found by reading code/config/hook output; two materially different approaches, including
   "this step is unnecessary"; the chosen one with a falsifiable expected outcome; the regression
   control); only then attempt 3 with the different approach. Attempt 3 fails → escalate the level,
   record the deviation, notify once, continue elsewhere. Never restart a partitioned run from
   scratch; never re-run a whole suite to re-find a known failure.
6. Windows traps: write multi-line files with the Write tool, not big heredocs (commands over ~5 KB
   fail); `PYTHONUTF8=1` for non-ASCII in Python snippets; `newline="\n"` when Python writes tracked
   text; `git checkout -- <path>` refreshes mtime (a restored target then looks "up to date").
7. Wake cadence is capped at 3 minutes, so an iteration never blocks on a long step. Launch a
   campaign batch or a qualification cell as a **real OS-detached subprocess only** (the
   shard-process form the Gate-5 runner already uses — never harness-level `run_in_background`,
   which does not survive a wake; §1 hard limit) with checkpoint/`--resume` enabled; record
   its PID and run id in `taskcard_status.json`; on the next wake check it (receipts written,
   process alive, log tail), review whatever has completed, commit approved batches, and yield
   again. Never re-launch a batch that is still running; never kill one to "restart cleanly".
   **Pipeline overlap (v10.4, TC-APT-068): while batch N is in review, batch N+1's campaign may
   already run detached — claims make the overlap collision-safe; the invariant is only that no
   batch commits before ITS OWN review completes. Do not leave the GPU or the API envelope idle
   waiting on a review pass.**

## 5. Commit and record

0. **Batch policy (operator directive, TC-APT-063): accumulate review-accepted cells and commit
   page-complete (one page's accepted languages = one commit) or family-scoped (N pages of one
   subdomain/family/platform, ≤250 outputs = one commit, `content(<family>)` scope). Per-cell
   commits only for single-cell heal retriggers.**
1. Content repo, per approved batch (plan §19.2, real CLIs under `scripts/pipeline/commands/`):
   `skill_run_manager.py create` (S-HT-02) before the batch; after APPROVE:
   `session_ledger.py adopt --files <exactly the receipt-listed paths>` → `candidates --format json`
   must equal the receipt list → `path_guard.py --stdin`; `override_manager.py create --paths …`
   for `content/websites.aspose.org/**` (and `skills/`, `.claude/`, `.agents/`, `.kilocode/` if
   ever touched) → explicit `git add <file>…` → `skill_run_manager.py finalize` → commit to local
   `main` with `content(locale): <imperative ≤72 chars>` (sub-scope by family/platform), body
   bullets (what, why, `Verification: <cmd> → <result>`), `Skills invoked: [S-HT-02]`, exactly one
   `Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>`. Before staging, `git status --short`
   and after staging `git diff --cached --stat` must name exactly your paths. A hook rejection is a
   root cause to fix and re-commit — never a bypass. Record the SHA in each row's
   `output_commit_ref`; only then set the rows `UP_TO_DATE`.
2. hugo-translator: commit this iteration's code/state changes to the mission branch with a message
   naming the taskcard or gate; same `Co-Authored-By` trailer; never to `main`; never push.
3. Update `work_ledger.sqlite3` + `work_ledger_events.jsonl`, `taskcard_status.json` (including
   `loop_prompt_version_seen`), `heal_queue.jsonl`, `qualification/cells.jsonl` with what evidence
   proves; write `data/summaries/<run_id>.json`.

## 6. Progress, throughput, checkpoints

- The headline number is `pages_newly_live_total` (Tier-1a pages that went from 0 to all 25
  committed). Report `cells_new` and `cells_replaced` separately; `progress = cells_committed_total
  / cells_eligible_total`. Taskcards DONE is not progress.
- Output invariant: every iteration lands ≥1 approved committed batch or writes a first-principles
  record saying why not. From Gate 6, fewer than 100 committed cells in an iteration needs a §10.1
  record naming the limiting factor and the change made; two such iterations in a row means the
  factor is structural — fix it in Track B before the next iteration. Three iterations with zero
  committed cells and no record: send one PushNotification, apply §10.1 to the loop itself.
- Push-ready checkpoints: at every gate transition, after every ~500 newly committed cells, and at
  least once per day of activity, send one PushNotification listing what is ready on the content
  repo's local `main` (sites, fully-live pages, cell count, commit range). The operator pushes.

## 7. Report (chat, under 250 words) and stop condition

Report: `pages_newly_live` this iteration/total; `cells_new`/`cells_replaced`/`cells_committed_total`
/progress %; `decide()` outcome; gate and track state; receipts, reviews and verdicts; heal-queue
size by root-cause class; open first-principles records; commits landed (SHAs); Track-B time share;
`loop_prompt_version_seen`; next action.

Stop the loop (pass `stop:true`) only when Gate 11 is closed per plan §20, or when both TRUE
external blockers in §1 have halted every remaining cell. Otherwise schedule the next wake **at
most 3 minutes out — never longer**, regardless of how long the current step is expected to take
(operator rule, v8.2), and yield. A long step is resumed across wakes (§4 item 7), not waited for.

## L. Field notes (append-only, one dated line each; facts, not rules)
- 2026-09-06 (v10.6): plan revisions 17+18 mirrored (§0.10 cohort industrialization, §0.11 the operator-chosen middle-path blitz). TC-APT-092..099 registered. Global wave_scale retired in favor of per-cohort ladders; BLITZ CONTRACT is the top selection priority until 099 completes -- hour-0 sustained probe FIRST, then critical path 092->096->094->099. Measured cohort evidence backing the split: 17 languages >=80% (tr/he/el/ar at 100%), tail uk/pt/ja/zh/hi/ko; inventory 117,059 cells over 8,370 pages, 91% in templated reference.aspose.org; qualification_ledger.py and work_claims.py were implemented-but-unwired (TC-APT-098 audits for more).

TC-APT-082 (2026-09-06): every entry recorded before this line moved to
`project/loop-prompt-archive.md` to bring this file back under its 40KB hard
cap (plan §0.9 revision 16) -- referenced there by date for deep debugging,
never re-read at routine orientation. Routine orientation instead reads
`.supervisor/state/aspose-org-full-portfolio-translation-20260901/state_digest.json`
(open obligations, active clauses, `wave_scale`, next action, and the
`loop_prompt_version`/plan-revision stamps this file and the plan carry) and
only re-reads full documents when a stamp there has changed. When this file
next exceeds 40KB, archive the oldest entries below first -- rules never
move, only dated facts. Keep new entries terse.
- 2026-09-06: CONFIRMED (recurred across 3 consecutive `-p` relaunches of the same session, each producing zero commit on otherwise-finished TC-APT-094 code): a one-shot `-p` iteration that launches a verification step and then tries to asynchronously "wait for the background task notification" gets NO further turns to receive that notification -- it just ends, having committed nothing, and the next relaunch starts cold with the same uncommitted diff. This is distinct from the earlier-documented "harness `run_in_background` doesn't survive a wake" issue (§1) -- this is about `-p` mode having no cross-turn continuation at all, not about background-task survival specifically. Verified root cause was needless in this case: both new test files (`test_llm_slot_semaphore.py`, `test_launcher_gpu_lane_and_family_claims.py`) pass in 10 seconds flat when run directly -- there was no reason to background them. RULE: in a `-p` one-shot iteration, run verification synchronously in the foreground (up to the ~600s tool timeout) whenever it plausibly fits; only use a real OS-detached subprocess (never harness `run_in_background`) for something that genuinely cannot finish in one turn, and in that case commit nothing until the NEXT relaunch confirms the detached process's result on disk -- never end a turn "waiting" for anything.
- 2026-09-06: TC-APT-100 CLOSED, validated at scale: 14/14 retried languages confirmed the wrap-before-link determiner bug gone, zero exceptions, across article-based/article-less/RTL/prefixed-article grammars. A content-repo commit was blocked once by "stale file regression" flagging TWO files I never touched (scripts/ci/checks/check_go_code_blocks.py, test_ci_go_code_blocks.py) as "silently reverting" a commit -- a PEER session's commit landed in the ~4 minutes my own commit's Go-vet pre-commit step (230-255s alone) was running, so my earlier-staged index looked stale against the new HEAD by the time the hook ran. Not a real conflict: rechecked git status/diff after the failure, found the 2 files no longer differed from HEAD (the peer's commit had already resolved it), and the retry with the identical pathspec commit succeeded immediately. Lesson: in this multi-session-fleet repo, a "stale file regression" failure right after a slow pre-commit step can be a transient race, not a real revert -- verify against current HEAD before assuming your own commit content is the problem.
- 2026-09-06: Retriggering a page that already has stale, untracked, review-rejected candidate files on disk (from a prior incomplete attempt) fails `verify_environment` instantly ("unreceipted campaign output is dirty") if `build_campaign_manifest.py` was run with the default `--existing refuse`. Do NOT delete the files to unblock it (content-repo deletion is a hard-limit line, and campaign_manifest.py already has the right mechanism): rebuild the manifest with `--existing replace` -- it declares the current on-disk bytes as the expected pre-campaign baseline (`declared_replacements`), which the dirty-check explicitly exempts (campaign_manifest.py ~line 430: "the target being locally dirty... is either this campaign's own prior (possibly review-rejected, uncommitted) output for the exact same cell... expected, not a hazard"). Confirmed: rebuilding and relaunching with the same manifest path proceeded cleanly.
- 2026-09-06: TC-APT-100 landed and live-verified (not yet campaign-verified): the wrap-before-link determiner bug was an INTERACTION between two individually-sensible fixes -- TC-APT-036 (link text stays visible so the model can agree a determiner with it) and TC-APT-087, which landed AFTER and masks that same link's ENTIRE brand-nav-label text as one span, silently defeating TC-APT-036's mechanism for this one link shape. Live extraction instrumentation (monkeypatch `TextUnitExtractor.extract_from_ast`, print units, abort before the LLM call -- costs nothing, no model load needed for the extraction check, only add `--abort`-style short-circuit if you build this again) showed the smoking gun directly: the unit text had 3 adjacent opaque placeholders with zero visible words between "the" and real prose. Fix: one new preserve_pattern masks the whole "[label](url)" as ONE placeholder. Lesson: when two taskcards each patch the same code path for different symptoms, check whether the LATER one's mechanism can silently undo the EARLIER one's assumption -- neither taskcard's own note flagged the interaction because each was reasoning about its own case in isolation.
- 2026-09-06: A DONE-looking taskcard note can still predict a fix that didn't land: TC-APT-036's LINK-half (2ddeeb3) has a detailed comment explaining exactly why full-sentence extraction should fix a determiner-before-link defect on cells-spreadsheet-management-go -- re-tested with fresh post-fix candidates and the SAME defect recurs in 14/16 rejected locales at the identical position (just-different manifestation per language: bare English/wrong demonstrative/V2 loss). Don't trust a taskcard's own landing note as proof of closure -- re-run the review against the exact page it named. Did not attempt a 6th narrow fix in this "text adjacent to a masked span" family (036/070/076/078/087 already each fixed one manifestation) without live-model instrumentation first (data/summaries/review-gate5-cells-mgmt-retry2-20260906.json).
- 2026-09-06: RECURRENCE ESCALATION audit: 8 heal_queue root-cause classes had open tickets from 2+ pages, but only `model_quality_complex_sentence_structure` was genuinely gating (TC-APT-042 had never attempted a code fix for that specific sub-pattern, only quarantine-and-record). The other 7 either have real landed TC-APT-039/040/042 code already, or are `auto:`-prefixed validator/gate names already routed through the implemented retry+quarantine flow -- NOT every multi-page class is an unresolved recurrence; check whether the taskcard shipped ANY code before assuming the gate applies. Closed the genuine one via reverification (13 fresh regenerations, current code, no fix needed -- confirms it was LLM sampling variance, not a deterministic bug); see data/summaries/fp-recurrence-gate-audit-20260906.json.
- 2026-09-06: TC-APT-064's real sustained probe landed (`sustained_safe_ceiling=64`, 0 errors/0 rate-limited across 3611 calls at 16/32/48/64 held 450s each) -- TC-APT-099 critical path (092->096->094->064) is now fully clear. Separately: `active_detached_runs` is stale bookkeeping, not stale work -- two of its three entries (gate5-words-doc-r3/r4, heal-cells-go-w1) were already resolved by prior wakes (commits landed, gate closed via wave_scale step-down) but never removed from the array; always check git log / session ledger before assuming a listed PID means unfinished work. Also found and closed a real gap: `session_ledger candidates` for THIS session's AGENT_SESSION_ID showed 8 already-adopted, already-staged pdf/cpp files (`introducing-pdf-foss-cpp`, adopted 2026-09-05T14:07Z) that a prior session never ran finalize+commit on -- `git status --short` alone doesn't distinguish "another session's live staging" from "my own session's abandoned staging"; `session_ledger candidates --session-id <mine>` does. Committed as 04548cceb1. One orphaned `skill_run_manager` pending record (from the unrelated already-landed 7e486c46eb) also finalized retroactively. Remaining real gap, not touched: r4's `fr` shard for words-document-net produced an accepted-but-unreviewed candidate file that belongs to no live session's ledger -- needs a fresh claim + review before it can be committed, never a blind adopt.
