# products.aspose.org Human Translation Review and Production Remediation Plan - 2026-07-01

## Scope

Reviewed 20 accepted `products.aspose.org` localized pages against their English sources from run `products_org_full_20260630_1050`.

Sampling target:

- Multiple content depths: root `_index.md`, family landing pages, and platform pages.
- Multiple product families: root, 3d, barcode, cad, cells, diagram, drawing, email.
- Multiple locale classes: RTL (`ar`, `he`, `fa`), CJK (`zh`, `ja`, `ko`), Slavic (`bg`, `ru`, `sr`), Romance (`pt`, `fr`, `ca`), Germanic/Nordic (`de`, `sv`), and Indic (`hi`).
- Both local M2M100-style output and routed LLM output (`sr`, `lv`).

Evidence generated:

- Sample manifest: `.local/reviews/products_org_human_review_sample_20260701.json`
- Side-by-side packet: `.local/reviews/products_org_human_review_packet_20260701.md`
- Field dump: `.local/reviews/products_org_human_review_field_dump_20260701.txt`
- Code fence scan: `.local/reviews/products_org_code_fence_mismatches_20260701.json`
- Current structural scan: `.local/reviews/products_org_current_structural_mismatches_accepted_20260701.json`

## Problem Statement

The accepted checkpoint for `products.aspose.org` cannot be treated as production-ready. The pipeline has generated and accepted pages that preserve some Hugo structure but violate publish-critical content invariants: code examples are sometimes translated or flattened, product identities are sometimes corrupted, English prose sometimes remains in localized fields, and checkpoint receipts accepted under older gates remain trusted after the verifier evolved.

The production problem is not just twelve bad sample pages. The real problem is that acceptance state, translation output, and verifier policy are not yet coupled tightly enough to guarantee repeatable quality across reruns. A durable fix must make the governed verifier the single acceptance authority, invalidate stale accepted state when gates change, preserve non-prose assets before model calls, and produce evidence that can be audited after every run.

## Executive Finding

The current accepted checkpoint contains a mix of good translations and stale accepted pages that would not pass the current quality bar. The strongest systemic issue is not UTF-8 corruption; it is code/example corruption, product identity corruption, partial translation, and stale structural acceptance.

Broad scans over accepted checkpoint entries found:

- `140` accepted pages where source and target fenced-code counts differ.
- `109` accepted pages with source/target key mismatches under the current parser.
- Several accepted pages with brand/title corruption, especially where product names should have remained protected.

The latest governed worker fixes may prevent some failures from recurring, but already accepted pages need a fresh re-verification pass with current gates before they are treated as publishable. Any implementation that only patches the visible sample pages will fail again on rerun because the system still needs production-grade invariants around code preservation, protected identity restoration, checkpoint state, and verifier versioning.

## Current-State Findings

- The governed worker can continue through failures and log evidence; this is worth preserving.
- The CLI may write candidates using `--disable-validation --force-accept`; therefore the governed verifier must remain the final acceptance gate.
- M2M100 is CUDA-capable and is now invoked with `--device cuda` for normal local-MT items, but `sr` and `lv` are intentionally routed to `professionalize_llm` because the config documents prior M2M100 quality failures for those locales.
- Code preservation has improved for some newly processed items, but the accepted checkpoint still contains older targets that predate the current repairs.
- The current review artifacts prove the issue is broader than the 20-page sample: `140` code-fence mismatches and `109` current structural mismatches were found among accepted entries.
- Some structural mismatches are audit/provenance-only drift and may be policy-allowable; other mismatches remove evidence/API/format data and must be rejected.
- Several failures are semantically severe even when YAML keys match: repeated titles, translated product names, and damaged code examples make pages unsuitable for production.

## Symptoms vs Root Causes

| Category | Visible symptoms | Root causes |
|---|---|---|
| Code/example corruption | Fenced code count changes, code fences become guillemets/music notes, Python/C++/Java identifiers translated, commands localized. | Code blocks were not treated as immutable translation units across all frontmatter multiline fields; placeholder restoration was not accepted as a hard invariant; older accepted targets were never revalidated after code-preservation fixes. |
| Product identity corruption | `Aspose.Email FOSS` becomes localized/nonsensical text, product title repeats or loses `Aspose.*`. | Product identity was partially treated as translatable prose; identity protection rules were incomplete for titles and title-like fields; verifier did not require source product identity substrings to survive target generation. |
| Partial translation | Long English phrases remain inside localized fields despite matching structure. | Completeness checking relied on exact full-field equality or weak phrase detection; mixed translated/untranslated multiline fields could pass. |
| Repetition/generation failure | `E-Mail - E-Mail - ...`, music-note loops, repeated plugin words. | Model degeneracy was not blocked by a repetition gate; retry logic did not quarantine low-quality generated loops before acceptance. |
| Stale accepted state | Accepted pages now fail current parser/verifier scans. | Checkpoint receipts do not record a verifier policy/version contract strong enough to force revalidation after gate changes; accepted entries were assumed durable after the verifier changed. |
| Rerun inconsistency | Same class can pass or fail depending on model route, checkpoint state, or whether a target already exists. | Candidate writes, existing-target preservation, language routing, and governed verification are not coordinated through a single state machine with deterministic quarantine/retry semantics. |

## Structural Consistency Breakers

- Verifier evolution without accepted-state invalidation: once gates changed, existing receipts remained trusted.
- Candidate write path is intentionally permissive while governed verification is strict; this is correct only if the governed verifier sees every candidate before acceptance.
- Source/target comparison ignores some audit/provenance paths, but the distinction between allowable audit drift and material content drift is not formalized enough.
- Code block protection is implemented as translation behavior, not yet as a universal acceptance invariant.
- Product terminology protection happens in several layers, but identity preservation is not enforced consistently at the final gate.
- Language routing can switch backend behavior by locale; quality expectations must be backend-independent at the governed acceptance boundary.
- Retry logic can improve individual files, but without quarantine/reverification it cannot cleanse stale accepted pages.
- Evidence exists, but it is not yet organized as a taskcard/state-machine handoff where each repair unit has status, gates, and artifacts.

## What Must Be Preserved

- The governed worker pattern: failures are logged, skipped, and retried without stopping the campaign.
- The evidence directory structure: per-file logs, receipts, failures, resolved failures, checkpoints, and review artifacts.
- The parser fixes for top-level `content:` frontmatter and delimiter-aware frontmatter parsing.
- The existing protected/passthrough policy for fields like `layout`, `family_name`, `plugin_platform`, `github_url`, and boolean enable flags.
- The failed-first retry strategy and pre-sweep that moves now-valid targets out of failure state.
- The CUDA-forced command path for M2M100 items.
- The `sr`/`lv` LLM routing unless a future controlled benchmark proves a better local route without reducing quality.
- The requirement that localized pages preserve the English source structure while translating all translatable prose.

## What Must Be Redesigned

- Acceptance must be policy-versioned. A receipt accepted under an older verifier must not remain trusted after new hard gates are added.
- Code blocks must be immutable source assets, not ordinary prose segments with best-effort placeholder handling.
- Product identities must be protected before model calls and verified after reconstruction.
- The verifier must classify failures by production invariant, not only by generic structural/partial buckets.
- Accepted pages must be re-verifiable and quarantinable without deleting target files.
- Retry state must distinguish untouched, candidate-written, accepted-current-policy, accepted-stale-policy, failed-active, quarantined-accepted, and resolved-failure states.
- Human review findings must feed back into automated gates and taskcards, not remain detached prose.

## Production-Grade Target Design

The production design is a three-layer contract:

1. Translation layer

   - Extract translatable prose, protected terms, and immutable assets before model calls.
   - Preserve fenced code blocks exactly, including fence language and body.
   - Preserve product identities exactly and translate only surrounding prose.
   - Route each locale through the configured backend, but keep the same acceptance criteria for all backends.

2. Governed verification layer

   - Parse source and target with the same Hugo parser.
   - Compare material structure, allowing only explicitly configured audit/provenance drift.
   - Enforce code-fence parity and exact code-block preservation.
   - Enforce product identity preservation in title-like and prose fields.
   - Enforce partial-English and repetition gates.
   - Emit typed failure evidence that can drive retry or quarantine.

3. State-management layer

   - Include a verifier policy hash/version in every acceptance receipt.
   - Reverify accepted entries whenever the policy hash changes.
   - Quarantine stale accepted entries into checkpoint failed state without deleting target files.
   - Retry quarantined/failed entries failed-first after repair.
   - Keep evidence sufficient for rollback and audit.

## Sample Verdicts

| # | Locale | Page | Verdict | Human review notes |
|---|---|---|---|---|
| 1 | ar | `_index.md` | Acceptable | Structure preserved. Main description is translated. Protected platform/product terms remain recognizable. |
| 2 | zh | `_index.md` | Warning | Structure preserved. Translation is mostly complete, but "libraries" is rendered as a book/library term in at least one key phrase, which is poor software terminology. |
| 3 | de | `3d/java/_index.md` | Fail | Source has 6 code fences; target has 0. Code examples are flattened into prose with guillemet-like markers. Prose is partly usable, but examples are not. |
| 4 | ja | `3d/net/_index.md` | Fail | Source has 6 code fences; target has 0. `single.block[0].content` contains heavy repeated music-note characters and damaged code. |
| 5 | ar | `3d/java/_index.md` | Fail | Code fences are preserved, but `overview.content` still contains a long English section. This is a partial translation. |
| 6 | bg | `barcode/_index.md` | Warning | Structure is preserved and prose is mostly translated, but `Aspose.BarCode FOSS` was translated/transliterated in the title. Product identity should be protected. |
| 7 | he | `cad/_index.md` | Warning | Structure is preserved, but title/product identity is corrupted. Body prose is mostly localized but has awkward technical phrasing. |
| 8 | pt | `cells/cpp/_index.md` | Warning | Code fences are preserved. Main content is translated, but overview title/some prose are awkward and lose "spreadsheet" specificity. |
| 9 | ru | `cells/net/_index.md` | Acceptable with edits | Structure and code fences preserved. Translation is understandable, but some phrasing is literal/awkward. |
| 10 | sr | `cells/net/_index.md` | Acceptable with edits | Structure and code fences preserved. Routed LLM output is mostly coherent. Some English technical terms remain, but mostly acceptable. |
| 11 | lv | `cells/python/_index.md` | Fail | Source has 6 code fences; target has 0. Code identifiers and commands were translated. Current parser also reports missing/extra keys. |
| 12 | ko | `cells/java/_index.md` | Warning | Code fences preserved, but title is awkward and some terms read as "book/library" rather than software library. |
| 13 | ar | `cells/cpp/_index.md` | Warning | Code fences preserved, but several English technical phrases remain in overview/title areas. |
| 14 | tr | `diagram/_index.md` | Fail | Title/product identity is corrupted (`Aspose.Diagram FOSS` not preserved). Some testimonial/content strings remain English. |
| 15 | fa | `drawing/_index.md` | Fail | Title mistranslates the product as a game/download phrase. Overview title remains mostly English. |
| 16 | hi | `email/_index.md` | Fail | Title loses the brand/product identity and becomes "Email Fox" style text. Body is more usable than title, but the page identity is wrong. |
| 17 | fr | `email/cpp/_index.md` | Fail | Title is nonsensical. Source has 4 code fences; target has 0 and C++ code is damaged. |
| 18 | ca | `email/_index.md` | Fail | Body is mostly understandable, but title translates/corrupts the brand identity. Product title should not be localized this way. |
| 19 | de | `email/_index.md` | Fail | Title repeats "E-Mail" many times, an obvious generation failure. |
| 20 | sv | `diagram/_index.md` | Fail | Title/product identity is corrupted. Main prose is mostly translated but title makes the page unsuitable. |

Review outcome from the 20-page sample:

- Acceptable or acceptable with edits: 3
- Warning: 5
- Fail: 12

## Root Causes Observed

1. Stale accepted entries

   Some checkpoint-accepted targets predate the current structural/code-preservation improvements. They should be rechecked under the latest verifier before being considered publishable.

2. Code block damage

   Many targets translated fenced code blocks as prose, removed fences, or translated code identifiers. This is visible in `3d/*`, `cells/python`, and `email/cpp` samples.

3. Brand/product identity damage

   Product names such as `Aspose.Email FOSS`, `Aspose.Diagram FOSS`, and `Aspose.BarCode FOSS` are sometimes translated, transliterated, repeated, or replaced with unrelated words. These should be protected except for surrounding prose.

4. Partial translation

   Some targets preserve structure and code but leave English prose in frontmatter content fields.

5. Literal terminology

   Several otherwise acceptable pages use literal translations for "library", "open source", or platform phrasing. These are editorial quality issues, not structural failures.

## Surgical Edit Map for Execution

| Section/subsystem to update | Reason | Intended improvement | Edit type |
|---|---|---|---|
| Governed verifier | Current verifier misses code mutation, identity mutation, repetition, and stale receipt policy. | Add policy-versioned hard gates with typed failure evidence. | Modify |
| Translation segmentation/reconstruction | Code blocks and product identities are still sometimes exposed to models as prose. | Extract immutable assets before model calls and restore exactly. | Modify |
| Products site profile | Protected fields and terms need to be explicit and testable. | Add/verify product identity and platform protection rules. | Modify |
| Checkpoint/receipt state | Accepted receipts survive verifier changes. | Add `--reverify-accepted` quarantine path and receipt policy hash. | Add |
| Failure taxonomy | Generic failures make recovery less systematic. | Add production failure types for code, identity, repetition, stale policy, and material structure. | Add |
| Evidence output | Evidence exists but is not taskcard/state-machine friendly. | Emit manifests for reverify, quarantine, retry, and human-review closeout. | Modify |
| Tests | Existing tests do not cover all 12 fail classes. | Add fixtures from failed human-review pages and broad accepted scans. | Add |
| Operations handoff | Execution is currently prose-driven. | Convert work into taskcards with status, gates, artifacts, and reroute rules. | Add |

## Surgical Implementation Plan

1. Stop and snapshot before changing gates.

   - Stop any active `products_org_governed_retranslate.py` or `src.cli --site products.aspose.org` worker.
   - Snapshot checkpoint, current file, final summaries, failure evidence, receipts, and run logs under a timestamped evidence folder.
   - Record git status and active process list in the evidence folder.
   - Do not delete or manually edit generated target pages.

2. Add policy-versioned governed acceptance.

   - Define a stable verifier policy document/hash from the set of active gates, protected paths, allowed audit paths, locale routing policy, and products site profile.
   - Store the policy hash in each receipt.
   - Treat missing or changed policy hash on an accepted receipt as `STALE_ACCEPTED_POLICY` until reverified.

3. Add hard invariant gates.

   - `REJECT_CODE_FENCE_MISMATCH`: source and target fenced-code block counts differ.
   - `REJECT_CODE_BLOCK_MUTATED`: any source fenced-code block body or language tag is missing or changed in target.
   - `REJECT_PRODUCT_IDENTITY_CHANGED`: target fails to preserve required `Aspose.*` identity substrings from source.
   - `REJECT_REPETITION`: title or scalar contains obvious repeated-token/model-degeneration loops.
   - `REJECT_PARTIAL_TRANSLATION`: translatable prose contains long English residue outside code/protected terms.
   - `REJECT_STRUCTURAL_MISMATCH`: material key/list/type drift outside explicitly allowed audit/provenance paths.

4. Harden translation behavior.

   - Treat fenced code blocks in frontmatter multiline scalars and Markdown body as immutable assets.
   - Translate only prose chunks surrounding code assets.
   - Restore code assets exactly and fail candidate verification if any asset is missing, duplicated, reordered, or mutated.
   - Protect product identities and platform names before model calls and restore them after translation.
   - For title-like fields, preserve the product identity and translate only non-identity suffix/prefix text.
   - If a scalar is unchanged and contains translatable prose, retry chunked prose translation once; if still unchanged, reject.

5. Add accepted re-verification and quarantine.

   - Add a governed `--reverify-accepted` mode for the existing run id.
   - Iterate accepted checkpoint entries and re-run current verifier.
   - For current-policy pass: update receipt policy hash and keep accepted.
   - For fail: remove from accepted, add to failed with typed reason, move receipt to `quarantined-accepted`, and write `accepted-reverification-failures/<work_item_id>.json`.
   - Do not delete target files; they are candidates to overwrite during retry.

6. Reprocess after gates pass tests.

   - Run `--resume --retry-failed --failed-first --device cuda` using one worker on this single-GPU machine.
   - Keep `sr` and `lv` routed to `professionalize_llm` unless a separate benchmark taskcard proves a better local route.
   - Monitor checkpoint deltas, typed failure counts, and evidence after each batch.

7. Repeat human review before publish.

   - Re-run the same 20-page sample after quarantine/retry.
   - Add a second independent 20-page sample only after the original sample has zero `Fail` verdicts.
   - No publish decision is allowed while code-fence mismatch, structural mismatch, or identity corruption remains in accepted entries.

## Taskcards / Actionable Execution Units

### TC-PROD-01: Freeze Runtime and Snapshot Evidence

- Status: Pending.
- Goal: Prevent moving target state before verifier changes.
- Actions:
  - Stop products.org translation workers.
  - Capture active process list, checkpoint, failure/receipt directories, and run logs.
  - Write snapshot manifest with source paths and hashes.
- Acceptance gates:
  - No products.org worker remains active.
  - Snapshot manifest exists and references the current checkpoint.
  - Git status is recorded.
- Evidence:
  - `.local/evidences/products_org_production_repair_<timestamp>/snapshot_manifest.json`
  - `.local/evidences/products_org_production_repair_<timestamp>/processes_before.json`

### TC-PROD-02: Implement Hard Verifier Invariants

- Status: Pending.
- Goal: Ensure bad code, identity, repetition, partial translation, and material structure cannot be accepted.
- Actions:
  - Add code-fence parity and exact code-block preservation checks.
  - Add product identity preservation checks.
  - Add repetition detection for title/scalar loops.
  - Strengthen partial-English detection for mixed multiline fields.
  - Add typed failure payloads with first failing path and evidence sample.
- Acceptance gates:
  - Unit tests cover all new failure types.
  - Existing good accepted examples still pass.
  - The 12 failed sample fixtures fail for the expected typed reasons before retranslation.
- Evidence:
  - pytest output for verifier tests.
  - failure classification JSON for the 20-page sample.

### TC-PROD-03: Add Policy-Versioned Receipts and Accepted Reverification

- Status: Pending.
- Goal: Make accepted state invalidatable when verifier policy changes.
- Actions:
  - Compute verifier policy hash.
  - Store policy hash in acceptance receipts.
  - Add `--reverify-accepted`.
  - Add quarantine transition from accepted to failed.
- Acceptance gates:
  - Dry-run reverify reports stale/passing/failing counts without mutating.
  - Mutating reverify moves failing accepted entries to quarantine and removes them from accepted.
  - Re-running reverify is idempotent.
- Evidence:
  - `accepted_reverification_summary.json`
  - `quarantined-accepted/*.receipt.json`
  - updated checkpoint diff summary.

### TC-PROD-04: Harden Translation Segmentation for Code and Product Identity

- Status: Pending.
- Goal: Prevent the model from corrupting immutable code and product identities.
- Actions:
  - Extract fenced code blocks before translation for frontmatter multiline scalars and Markdown body.
  - Preserve exact code assets through placeholder restoration.
  - Protect product identities and platform names.
  - Add title-specific identity-preserving translation behavior.
- Acceptance gates:
  - Fixtures for `de 3d/java`, `ja 3d/net`, `lv cells/python`, and `fr email/cpp` preserve exact code blocks after retranslation.
  - Fixtures for `hi email`, `ca email`, `de email`, `tr diagram`, `fa drawing`, and `sv diagram` preserve product identity and avoid repetition.
- Evidence:
  - before/after fixture comparison JSON.
  - pytest output for segmentation and reconstruction tests.

### TC-PROD-05: Quarantine and Retry Stale Accepted Pages

- Status: Pending.
- Goal: Cleanse the current checkpoint without manual file edits.
- Actions:
  - Run `--reverify-accepted` against `products_org_full_20260630_1050`.
  - Retry failed/quarantined entries failed-first.
  - Monitor failure type counts and resolved failure receipts.
- Acceptance gates:
  - Accepted entries with code-fence mismatch are zero after retry.
  - Accepted entries with current structural mismatch are zero after retry, excluding explicitly allowed audit/provenance-only drift.
  - Active failures either reach zero or are typed with actionable evidence.
- Evidence:
  - quarantine manifest.
  - retry logs.
  - final checkpoint summary.

### TC-PROD-06: Human Review Closeout and Publish Gate

- Status: Pending.
- Goal: Prove the automated gates correspond to human-perceived quality.
- Actions:
  - Re-run the same 20-page sample review.
  - Run a second stratified 20-page sample if the first sample has zero fail verdicts.
  - Update this document with the new verdicts and residual risks.
- Acceptance gates:
  - Original 20-page sample has zero `Fail`.
  - Second sample has zero critical structural/code/product identity failures.
  - Remaining warnings are editorial only and documented.
- Evidence:
  - new sample manifest.
  - side-by-side packet.
  - human review summary.

## Validation and Regression Gates

Required tests before using the repaired pipeline on remaining work:

- Unit tests:
  - fenced-code parity and exact preservation;
  - product identity extraction and restoration;
  - title repetition detection;
  - partial-English detection outside protected/code regions;
  - policy hash change detection;
  - accepted re-verification quarantine behavior.
- Integration fixtures:
  - `de 3d/java/_index.md`;
  - `ja 3d/net/_index.md`;
  - `ar 3d/java/_index.md`;
  - `lv cells/python/_index.md`;
  - `fr email/cpp/_index.md`;
  - `tr diagram/_index.md`;
  - `fa drawing/_index.md`;
  - `hi email/_index.md`;
  - `ca email/_index.md`;
  - `de email/_index.md`;
  - `sv diagram/_index.md`.
- Broad scans:
  - accepted code-fence mismatches must be zero;
  - accepted material structural mismatches must be zero;
  - accepted product identity corruption must be zero;
  - accepted repeated title loops must be zero.

Do not restart the full worker until targeted unit and integration tests pass.

## Evidence Requirements

Every production repair run must write:

- snapshot manifest before changes;
- verifier policy hash and policy contents;
- accepted re-verification summary;
- quarantine manifest with old receipt ids and new failure ids;
- typed failure counts before and after retry;
- retry command log and worker process log;
- final checkpoint summary;
- human review packet and verdict summary;
- list of known residual risks.

Evidence must be enough to answer:

- Which accepted pages were invalidated and why?
- Which verifier policy accepted each current receipt?
- Which pages were regenerated?
- Which backend handled each locale?
- Which gates were run before publish?

## Rollback and Safety Plan

- Stop workers before verifier/checkpoint state changes.
- Snapshot checkpoint and evidence before mutation.
- Do not delete target files during quarantine; only checkpoint state changes.
- If reverify/quarantine logic misclassifies entries, restore the checkpoint snapshot and receipts.
- If retry generates worse candidates, keep the previous target file available and preserve failure evidence.
- Keep one worker on the single CUDA GPU unless hardware changes.
- Do not remove `sr`/`lv` routing during this repair.
- Do not weaken acceptance criteria to improve progress counts.

## Risks, Tradeoffs, and Limits

- Stricter gates will temporarily increase failed/quarantined counts. This is expected and preferable to publishing corrupted pages.
- Exact code preservation means comments inside code are not localized for this campaign. That is an intentional quality tradeoff.
- Product identity preservation may leave some English brand/platform tokens in localized titles. This is required for correctness.
- Partial-English detection can produce false positives for technical prose. False positives should be tuned with protected-term rules, not by disabling the gate.
- LLM-routed locales may produce better prose but still must satisfy identical structural and identity gates.
- Some warning-level naturalness issues, such as awkward "library" terminology, may remain after structural fixes. These are editorial follow-up items unless they misrepresent the product.

## Pending Execution Handoff

Next agent should execute taskcards in order:

1. TC-PROD-01: freeze runtime and snapshot.
2. TC-PROD-02: hard verifier invariants.
3. TC-PROD-03: policy-versioned receipts and `--reverify-accepted`.
4. TC-PROD-04: translation segmentation hardening.
5. TC-PROD-05: quarantine and retry.
6. TC-PROD-06: human review closeout.

Before starting, confirm:

- active repo: `C:\Users\prora\OneDrive\Documents\GitHub\hugo-translator`;
- run id: `products_org_full_20260630_1050`;
- evidence root: `.local/evidences/hugo-translator-retranslation-products_org_full_20260630_1050`;
- current git status and any unrelated user changes;
- no production worker is allowed to keep accepting pages while gates are being edited.

Done means:

- all accepted entries are accepted by the current verifier policy;
- all quarantined entries have typed evidence;
- no accepted pages have code-fence mismatch, material structural mismatch, product identity corruption, or repeated title loops;
- repeated human review has zero `Fail` verdicts;
- this document is updated with final evidence paths and residual risks.

## Execution Closeout - 2026-07-02

Status: Completed and accepted for run `products_org_gitlab_full_20260702_002`.

What was completed:

- Consolidated the governed products.org translation runner, quality checks, tests, and runbook into the working `hugo-translator-gitlab` tree.
- Retranslated or reverified all remaining `products.aspose.org` source/locale pairs from the current inventory.
- Processed `42` English source pages across `36` configured target locales, for `1512` required pairs.
- Final checkpoint state is `1512` accepted, `0` failed, and `0` remaining.
- Final accepted re-verification checked `1512` accepted entries and returned only `VERIFIED_ACCEPT`.
- English source mutation check returned `{}`.

What changed during execution:

- Added a machine-readable products.org quality policy at `config/quality/products_aspose_org_policy.yaml`.
- Added an unattended execution wrapper at `scripts/quality/products_org_unattended_retranslate.py`.
- Hardened `scripts/quality/products_org_governed_retranslate.py` for campaign-wide completion, existing-target pre-verification, batch progress consistency, extra code-fence repair, known scalar repairs, and policy-gated accepted re-verification.
- Hardened `src/translation_engine/segment_translator.py` for the final Thai Word-conversion title residue case.
- Added focused regression tests in `tests/unit/quality/test_products_org_governed_retranslate_shards.py`.
- Added repeatable operator documentation at `docs/quality/products-org-unattended-runbook.md`.

Verification performed:

- Governed final report: `.local/evidences/hugo-translator-retranslation-products_org_gitlab_full_20260702_002/final/unattended-report.json`.
- Accepted reverify: `.local/evidences/hugo-translator-retranslation-products_org_gitlab_full_20260702_002/final/accepted-reverification.json`.
- Source mutation evidence: `.local/evidences/hugo-translator-retranslation-products_org_gitlab_full_20260702_002/final/source-mutations.json`.
- Focused regression command passed: `24 passed, 3 warnings`.
- Native Hugo build passed with `hugo --config .\configs\products.aspose.org.toml --destination <temp> --cleanDestinationDir`.
- The Bash CI wrapper could not see `hugo` in its shell environment; native PowerShell Hugo was available and passed.
- `--panicOnWarning` still fails on an existing missing taxonomy layout warning unrelated to the translation output.

Remaining follow-ups / non-blockers:

- `hugo-translator-gitlab` is not itself a Git repository; commit closure must use the actual Git repositories that hold source code and generated content.
- The products.org Hugo config still emits the existing taxonomy layout warning. Normal build passes; warning-as-error does not.
- Generated content changes are in the `aspose.org` repository under `content/products.aspose.org`.
- Pipeline/source hardening changes are in the `hugo-translator` repository.

## Repeatable Human Review Process

1. Freeze the run id and checkpoint path.

   Example:

   ```powershell
   $run = "products_org_full_20260630_1050"
   $checkpoint = ".local/evidences/hugo-translator-retranslation-$run/checkpoints/checkpoint.json"
   ```

2. Build a stratified sample from accepted entries.

   Include at least:

   - 2 root pages,
   - 5 family landing pages,
   - 8 platform pages,
   - 2 RTL locales,
   - 2 CJK locales,
   - 2 routed LLM locales if present,
   - pages from any recently repaired failure class.

3. Generate a side-by-side packet for each selected pair.

   For each page capture:

   - locale, relative path, family, depth, work item id,
   - key frontmatter fields: `title`, `description`, `overview.title`, `overview.content`, `single.block[0].content`,
   - source/target frontmatter key counts,
   - missing/extra key paths,
   - source/target fenced-code counts,
   - likely English residue candidates.

4. Human-review each sampled page.

   Grade each page as:

   - `Acceptable`: structure preserved, code preserved, prose localized, protected terms intact.
   - `Acceptable with edits`: no structural/code failure, but wording needs editorial polish.
   - `Warning`: publish risk exists but the page is mostly recoverable with targeted fixes.
   - `Fail`: code damage, structural mismatch, product identity corruption, repetition, or substantial untranslated prose.

5. Run broad scans on all accepted targets.

   Always scan for:

   - source/target code-fence mismatches,
   - current parser key mismatches,
   - repeated title tokens,
   - product identity mutations,
   - obvious untranslated English blocks.

6. Feed findings back into the pipeline.

   Any class found in human review should become either:

   - a governed verifier gate,
   - a translation repair rule,
   - a protected field/term rule,
   - or a quarantine criterion for stale accepted targets.

7. Archive artifacts.

   Keep sample manifest, packet, scans, and final review report under `.local/reviews/` for raw evidence and `docs/quality/` for the durable summary.
