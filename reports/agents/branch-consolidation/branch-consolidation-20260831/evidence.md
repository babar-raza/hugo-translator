# Evidence — branch-consolidation-20260831

Mission: merge `remediation/audit-phase7-20260723` and `mission/blog-url-production-control-plane` (which subsumes `pilot/foss-localization-zero-defect-translator` and `pilot/foss-localization-zero-defect-translator-runtime`) into `main`, delete confirmed-merged branches, rescue orphaned commits, fix an accidental data deletion and a contradicting `.gitignore` rule, and preserve untracked mission evidence — without losing any information.

Plan: `C:\Users\prora\.claude\plans\carefully-merge-branches-with-jolly-quasar.md`
Taskcards: `.supervisor/state/branch-consolidation-20260831/stage2-plan/stage2-taskcard-index.yaml`

## Pre-merge investigation (evidence, condensed)

- 3 parallel Explore agents + direct `merge-base --is-ancestor`/`fsck`/`git status` verification established: 9 branches fully merged (safe to delete), `remediation` and `pilot`/`pilot-runtime`/`mission` are unmerged siblings forked at `3599a45` (neither subsumes the other), `mission` (`bc5b87a`) is a verified superset merge of `pilot`+`pilot-runtime`.
- `git fsck --unreachable` found 70 unreachable objects: 66 harmless stash debris, 4 real — a 3-attempt independent-rebuild sequence for a url/aliases frontmatter fix (final: `b0f787f`, 35 days old, past the 2-week gc grace window) and `fde9b44` ("prd03-qualified-candidate"), kept alive only by a prunable worktree.
- A governance-conformance review pass (3 more Explore agents + `gh api`, tooling checks) verified this repo's actual `.supervisor/` framework, taskcard conventions, CI/hook behavior, and confirmed `main` was unprotected on GitHub before any push was attempted.

## TC-BRC-001 — Safety net

```
git tag archive/pre-consolidation-main-20260831 main
git branch archive/orphan-url-aliases-fix-20260727 b0f787f
git branch candidate/prd03-qualified-20260729 fde9b44
```
All 3 refs created before any destructive/gc-adjacent operation.

## TC-BRC-002 — Preserved untracked evidence

Force-added 5 mission folders under `.supervisor/state/` that existed only on local disk (gitignored since `d5b67ea`): `heading-i18n-governance-20260723`, `quality-regression-tmkey-router-fix-20260717`, `site-locale-allowlist-generalization-20260725`, `reference-i18n-hardening-20260725`, `HT-INLINE-CODE-001`. Total 422KB, all text (yaml/md/log/json/csv).

## TC-BRC-003–006 — Working-tree triage (on `remediation/audit-phase7-20260723`)

- Restored `data/benchmark_corpus/` (7 files), removed the contradicting `/data/benchmark_corpus` `.gitignore` line (traced to unrelated commit `d5b67ea`).
- Committed the intentional `url`/`aliases: mode: ignore` frontmatter fix (4 site-profile yaml files) — verified byte-identical (blob `820eb28`) across the working tree, mission's already-committed version, and `fde9b44`'s version.
- Committed 2 real, previously-uncommitted ops scripts (`fix_orchestrator_task_path.ps1`, `startup_recovery.py`).
- Removed disposable scratch files; added `.kilo/` to `.gitignore`.

## TC-BRC-007 — Local pre-flight

Full `tests/unit/` run hit a pre-existing, order-dependent `transformers` import-pollution bug — reproduced the exact same failing files in isolation and they passed cleanly (31/31), confirming the pollution is unrelated to this mission. Gated instead on: `tests/unit/config/` + `tests/unit/benchmarking/` (646 passed, 28 skipped), frontmatter suites (66 passed, 9 skipped), `tests/regression/` (122 passed, 1 pre-existing failure traced to a `scripts/` module confirmed absent on `main` itself).

## TC-BRC-008 — Merge `remediation` into an integration branch

`git checkout -b integration/branch-consolidation-20260831 main && git merge --no-ff remediation/audit-phase7-20260723` → commit `103a8c0`, zero conflicts (main was a strict ancestor of `remediation` at merge time). Caught and discarded one incidental test-run side effect (a regression test wrote output back into a tracked fixture file, `tests/fixtures/nested_list_output_debug.md`) via `git restore` before it could pollute the merge.

## TC-BRC-009 — Merge `mission` (the real 3-way merge)

25 conflicted files, 60 hunks. Every hunk resolved to one of:

1. **Pure formatting** (ruff-format-style line-wrapping vs. manual style, byte-identical semantics) — verified programmatically for the largest single hunk (a 36-entry gate-dispatch table, `write_gate.py`) by extracting and diffing every key/lambda body after whitespace normalization.
2. **Mission is a strict superset** — confirmed via `git log 3599a45..remediation/audit-phase7-20260723 -- <file>` showing only the shared fork commit `e9c9e7b` ever touched that file on remediation's side (never independently maintained after the fork), for: `engine.py` (whole `accept_candidate_bytes` method + stricter 44-gate-completeness receipt validation), `engine_builder.py` (L3 encoder model-identity check, closing a real cross-model similarity-score correctness gap), `models.py` (`rejection_gate_results` field, `source_bytes`-based sha256), `file_pipeline.py` (final-byte re-validation via `accept_candidate_bytes`, closing a real gap where auto-cleaned content could be accepted without re-verifying the bytes that reached disk), `llm_backend.py` (`_retry_feedback_var` — required by `translate_with_retry_feedback()`, already present unconditionally in the merged file), `autonomous_content_translation_worker.py` (shard-scoped campaign execution, receipt recovery), 8 add/add campaign files (`campaign_runner.py`, `campaign_manifest.py`, `fidelity_judge.py`, etc.).
3. **Two file-specific reversals**, where remediation's later fix was the superset instead: `scripts/quality/audit_all_content.py` (TC-DCF-022's bounded-timeout `_git_fingerprint` fix + `content_repositories` field) and its test file — confirmed via direct diff that mission's version was byte-identical to remediation's *pre*-fix state.
4. **One required cross-file consistency fix**: `write_gate.py`'s `receipt_action = "block" if action == "warn" else action` and gate-36 fidelity-result propagation — confirmed *mandatory*, not optional, because `engine.py`'s already-merged `accept_candidate_bytes`/`_write_accepted_output` validation explicitly rejects any gate result recorded with `action: "warn"`; without this, every zero-defect run touching a warn-tier gate would fail receipt validation.

Zero hunks met the plan's escalation bar (a genuine competing-implementation conflict on the same logic) — every case resolved to formatting, an unambiguous superset, or a required consistency fix, each independently verified rather than assumed.

Merge commit: `827fb09`.

## TC-BRC-010 — Post-merge verification

```
git merge-base --is-ancestor pilot/foss-localization-zero-defect-translator HEAD        # true
git merge-base --is-ancestor pilot/foss-localization-zero-defect-translator-runtime HEAD # true
```
`check_manifest.py --strict`: 1 finding (`scripts/diagnose_model_corruption.py`, confirmed untracked on every branch in this merge — disclosed, not adopted). `check_governance.py --strict`: PASS, 15/15. `check_share_safe.sh` (targeted equivalent — the script's step 3 hangs under Git Bash on Windows, disclosed in a prior taskcard note): steps 2/4/5 clean; step 1 (personal paths) and step 3 (large files) both surfaced pre-existing, non-functional, disclosed findings unrelated to this merge. `check_docs_links.py` (advisory): broken links confined to `docs/_archive/`.

Comprehensive test run across `tests/unit/{translation_engine,workers,model_runtime,tm,phase-3,validation,verification,quality}/`: **3067 passed, 8 failed, 17 skipped** (1035s). All 8 failures independently reproduced against `mission`'s own unmodified worktree — 7 fail identically standalone, the 8th (`test_real_model_conversion`) is a pre-existing order-dependent skip/fail flake on `mission` alone. None caused by this merge.

## TC-BRC-011 — Promote to `main`

```
git checkout main && git merge --ff-only integration/branch-consolidation-20260831
```
Fast-forward `65193de..827fb09`, confirmed by `--ff-only` succeeding (proves nothing else moved `main` in the meantime). Integration branch deleted.

## TC-BRC-012 — Retire worktrees and branches

4 live worktrees removed (`pilot`, `pilot-runtime`, `mission`, `zircon-moon`) — all re-verified clean via `git status --short` immediately before removal. `pilot`'s worktree needed `--force` after git's own `rmdir` failed on <400KB of gitignored residue (verified sizes first — no model weights or real data, just tiny cache/log scaffolding). 13 branches deleted via self-verifying `git branch -d` (would have refused any that weren't truly merged): the 9 originally-verified branches plus `remediation`, `mission`, `pilot`, `pilot-runtime`, `zircon-moon`. Final `git branch -a`: `main` + `archive/orphan-url-aliases-fix-20260727` + `candidate/prd03-qualified-20260729` + `backup-before-model-cleanup` (left untouched per explicit decision) — exactly matching the plan's closeout criteria.

## TC-BRC-013 — Prune stale worktree records

`git worktree prune -v` removed both stale `prd03-*` detached-HEAD records (directories already gone from disk) — safe only because `fde9b44` had already been tagged in TC-BRC-001.

## TC-BRC-014 — Remote sync

`git push origin main`: succeeded, `78aed63..827fb09` fast-forward (branch protection confirmed absent via `gh api` before this ran). `git push origin --delete ci/shipping-gate-verification release/phase10_isolated_20260127_112335`: succeeded. `git push gitlab main`: **failed** — HTTP Basic auth rejected, expired/missing credential. This is a genuine external-credentials gap; the agent does not have a valid gitlab token and did not attempt to work around it. Skipped the 3 corresponding gitlab branch deletions rather than proceed with broken auth. See `TERMINAL_CLOSED.yaml`'s `successor_action` for the exact follow-up commands.

## TC-BRC-015 — `fde9b44` review (Part B)

`git diff main candidate/prd03-qualified-20260729 --stat`: 94 files, **+39/-5947**. Read the full diff for every non-`.supervisor` file: `.gitignore` (fde9b44 still has the bad `/data/benchmark_corpus` line TC-BRC-003 already removed), 3 site-profile yaml (fde9b44 still has the unfixed `url: passthrough` bug TC-BRC-004 already fixed), `audit_all_content.py` (fde9b44 has the simpler pre-TC-DCF-022 version), `l2_persistent.py`/`engine.py`/`engine_builder.py`/`test_llm_backend.py` (pure formatting only). **Main is a strict superset of `fde9b44` in every file that differs** — zero cherry-picks applied. Scratch branch `review/prd03-diff-20260831` discarded after the diff review confirmed nothing needed to move.

## TC-BRC-016 — Final audit

`git status` clean, `git worktree list` shows only the primary worktree, `git branch -a` matches closeout criteria exactly. `git fsck --unreachable --no-reflog`: every unreachable commit inspected by message — all but 2 match the standard git-stash-internal pattern; the 2 exceptions were confirmed to be superseded early drafts of the already-rescued `b0f787f` fix (verified `b0f787f`'s real parent is a normal mainline commit, not either of these two).

## Final state

- `main` at `827fb09`, pushed to `origin`, 0 commits ahead of `origin/main`.
- `git branch -a`: `main`, `archive/orphan-url-aliases-fix-20260727`, `candidate/prd03-qualified-20260729`, `backup-before-model-cleanup` (local); expected remotes only.
- 1 worktree (primary), 0 stale worktree records.
- Test suite: 3067 passed / 8 pre-existing-confirmed failures / 17 skipped across the merge-relevant unit suites.
- 1 open follow-up requiring human action: refresh gitlab credentials, complete the gitlab push/branch-deletion (see `TERMINAL_CLOSED.yaml`).
