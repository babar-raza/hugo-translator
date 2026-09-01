# HT-INLINE-CODE-001 — Final Sprint Summary (as of this execution pass)

## Mission
Fix "Inline code translated (identifier corruption)" — 21,904 audit hits
across aspose.org — via root-cause fix, content remediation, TM cleanup,
and structural hardening. Full hardened plan:
`C:\Users\prora\.claude\plans\inline-code-translated-identifier-eventual-bubble.md`

## Verdict: EXECUTION_COMPLETE_WITH_LIMITATIONS

Foundation, root-cause fix, and canary-scale proof are complete and
real-world verified. Full-corpus rollout (all 5 sites' content, all 5
sites' TM) is a genuinely long-running continuation, in progress in the
background at the time of this report, not fabricated as complete.

## What was achieved (all with real, inspected evidence — see verification-matrix.md)

1. **Root cause identified and fixed**: `SegmentExtractor` flattened
   `CODE_SPAN` AST nodes into unprotected plain text before MT/LLM
   translation. Fixed via a shared, tested `preserve_patterns` baseline in
   `config/global.yaml`, inherited by all 5 site profiles (was previously
   staged on one site only — the actual cause of the drift).
2. **Detector consolidated**: one tested primitive
   (`src/translation_engine/quality/inline_code_repair.py`) replaces three
   independently-buggy reimplementations (`write_gate.py` Gate 22,
   `audit_all_content.py`, `UnitQualityScorer`) — all rewired, all
   regression-tested (139+22+38 = 199 tests passing on those files alone).
3. **Governance bug fixed**: Gate 22 was registered `"auto_clean"` but
   behaved as a hard block; now correctly `"block"`, with
   `clear_tm_buffer=True` wired in and proven end-to-end.
4. **Content healer wired**: `unit_heal.py` gained a no-model structural
   fix for `inline_code_integrity_detector` (already a recognized issue
   type upstream — only the fixer was missing).
5. **TM healer built**: `tm_surgical_cleanup.py` gained Rule 5 (patch, not
   full overwrite — only the corrupted span, leaving correct surrounding
   translation untouched), with provenance stamped in the existing
   `metadata` dict.
6. **Live, real-world proof**: a real single-file translation through the
   installed `translate-hugo` CLI (real GPU model call,
   `sentence-transformers`/`m2m100`/`nllb` stack, not mocked) confirmed all
   13 real EN inline-code identifiers survived byte-identical in the
   French output.
7. **Live, real-world TM fix**: applied to `products.aspose.org`'s real
   production TM (49,786 entries scanned) — 7 genuine corrupted entries
   patched (0 errors), re-verified at 0 remaining hits, round-tripped by
   direct query against all 7 patched entries' provenance metadata, L2
   integrity confirmed (1,150,560 total entries, "ok"), L3 health confirmed
   (764,510 entries via `quick_validate_l3.py`).
8. **Extraction-path instrumentation** added (observational only, per the
   plan's explicit decision to not decide the AST/legacy precedence
   question without production data).

## Real bugs found in *other* tooling during this session, disclosed not silently patched
- 3 pre-existing test failures, confirmed unrelated via `git stash`
  bisection before this mission touched anything.
- `tests/unit/test_audit_script.py` pre-existing collection error
  (missing `scripts.audit_codebase` module).
- `scripts/tm/verify_tm_integrity.py`: wrong `PROJECT_ROOT` depth (resolves
  to `scripts/`, not repo root) and a stale `l3_index` directory name
  (real dir is `l3_faiss`) — both pre-existing, both worked around for this
  session's verification, neither fixed (out of scope).
- The full `tests/unit` sweep crashes in pytest's own capture-teardown
  machinery on this repo/environment combination — inconclusive as a whole,
  but zero failures attributable to this mission's files were found in its
  partial output.

## What genuinely remains (continuation, not a blocker)

- **TC-ICR-009** (content): Stage-0 dry-run queue build for kb.aspose.org
  was still running at time of writing (0 `inline_code_integrity_detector`
  hits found in ~1,000 of up to ~11,000 possible pairs scanned so far —
  inconclusive until complete). Stage 1 canary write has not yet run.
  Reference/docs/products/blog sites not yet scanned for content healing.
- **TC-ICR-012** (TM): `products.aspose.org` fully closed (backup can be
  deleted once the L3 rebuild below is confirmed clean). `kb.aspose.org`'s
  dry-run found 13 real patches ready to apply. `docs`/`reference`/`blog`
  not yet scanned.
- **L3 rebuild**: a full re-embed of 1,150,560 entries was in progress
  (GPU) at time of writing — necessary because L2's key is a source-text
  hash unaffected by a patch, so L3's cached target-text metadata needs a
  real rebuild to stop serving the 7 (soon more) stale cached translations
  via fuzzy match.
- **TM backup deletion**: intentionally NOT done yet — gated on the L3
  rebuild completing and a final clean check, per the plan's explicit
  "verify everything before deleting the one safety net" requirement.

## The one decision that needed a human, not a guess

Committing was in scope for this mission's closure, but the working tree
had substantial **pre-existing uncommitted work already present before
this mission began** (an antecedent "phase-7 quality-gates" effort, ~50
files, intermingled in the *same files* this mission needed to edit —
`write_gate.py`, `segment_extractor.py`, `unit_heal.py`,
`tm_surgical_cleanup.py`, several config profiles, etc.). git cannot
cleanly separate two authors' changes within the same file's diff without
interactive hunk-staging (disallowed by this session's own git safety
rules), and the plan's own commit instruction explicitly says "unrelated
files excluded." Guessing wrong here is a one-way door — see the final
chat response for the disclosure and the question put to the user.
