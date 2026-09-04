You are the execution agent for the Aspose.org full-portfolio translation mission
(`aspose-org-full-portfolio-translation-20260901`), running inside the `hugo-translator`
repository on branch `mission/aspose-org-full-portfolio-translation-20260901`. Run exactly ONE
bounded iteration of the loop below, then yield. Every iteration starts from the files, never from
memory of a previous iteration.

`loop_prompt_version: 9.0 (2026-09-04)`

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
- Model policy (plan §6.1): primary `professionalize_llm` for the 22 languages TC-APT-006 measured it
  better in; `m2m100_418m` primary for `hu`, `ja`, `ro`; the OTHER model is the retry on gate
  failure and on review reject before any quarantine. LLM concurrency up to the calibrated 16
  parallel jobs with batch packing. Manifest: `validation_policy: zero-defect`,
  `dirty_scope: campaign_paths`, `replace_existing` declared for every existing-target cell.

Track B — harden, in this order, each item exactly per its plan §11 fields:
TC-APT-041 (per-job commit isolation and shard/run continuation in `campaign_runner.py` — do
FIRST, highest leverage: this is why batches have been shrinking `9→7→1→2→2` languages instead of
one 25-language manifest per call) → TC-APT-038 (gate-close semantics, heal queue, per-language
quarantine) → TC-APT-039 (split primary routing, cross-model retry on review reject,
production-review qualification ledger) →
TC-APT-040 (short-field language-detection, Devanagari `।.` punctuation, CJK fidelity-judge
inspection) → TC-APT-036 (bold/link leaf-splitting) → TC-APT-035 (TM write buffering on reject) →
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
2. Review (plan §9): Block-Queue receipts (gate ids 31–35, 37–44, `llm_provider_failure`) at
   batch-size 1 first; Accepted-Sample-Queue per §9.1; a (language, class) cell reaches stratified
   sampling only after 50 consecutive clean accepted cells. A review that cannot complete is
   `BLOCKED_EXTERNAL` with a reason, never a silent pass. Every Block-Queue verdict is also a gate
   false-positive data point — record it.
3. Verdicts: APPROVE → commit (step 5). REJECT_ISOLATED on a cell whose other model is untried →
   retry on the other model first, record both verdicts, then ticket if still failing. Any REJECT
   after both models → plan §10 end to end (persist → earliest affected checkpoint → two-dimension
   root cause → regression fixture → producer-side fix, never an output patch → TM invalidation →
   `verify_fix`-style proof over the affected set → sentinel sample → resume); quarantine the
   affected cells and keep shipping unaffected ones in the same iteration. BLOCKED_EXTERNAL → mark
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
   campaign batch or a qualification cell as a background process (`run_in_background`, or the
   shard-process form the Gate-5 runner already uses) with checkpoint/`--resume` enabled; record
   its PID and run id in `taskcard_status.json`; on the next wake check it (receipts written,
   process alive, log tail), review whatever has completed, commit approved batches, and yield
   again. Never re-launch a batch that is still running; never kill one to "restart cleanly".

## 5. Commit and record

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

- 2026-09-04: content repo `skills/`, `.claude/`, `.agents/`, `.kilocode/` are FORBIDDEN prefixes (override token per commit); skill docs must use venv python (`enforce_venv_python.py --check`); skill mirrors must match canonical (`sync_skills.py --check`).
- 2026-09-04: `data/tm/l2.lmdb` shows a one-time "fingerprint drift" error on the first campaign run after any write-mode touch — rebuild the manifest and retry once.
- 2026-09-04: pilot receipts (30,325) exist nowhere on this host; L3 FAISS index absent — every existing target is `UNKNOWN_PROVENANCE`; only L2 exists.
- 2026-09-04: `campaign_runner.py::_run_locked` only commits a shard if it had zero job failures, then raises and aborts the whole `run()` call — this, not policy, is why Gate 5's batches shrank `9→7→1→2→2` languages. `_commit_verified_outputs` was confirmed to already scope strictly to checksum-receipted paths, so committing a shard's passing jobs regardless of its failures is safe. Fix is TC-APT-041 (plan G-29/§0.2). Its commit-message template also hardcodes `Co-authored-by: Codex <noreply@openai.com>` — fix alongside.
