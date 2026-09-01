# End-to-end pilot rerun: real CLI, before vs after, 2026-07-27

## Design

Not a re-derivation of the full-corpus comparator's synthetic function calls —
this runs the actual `scripts/quality/audit_all_content.py` CLI end-to-end,
twice, against isolated copies of real files, mirroring `TC-DCF-017`'s
established methodology:

- **Before:** `git show 1261521:scripts/quality/audit_all_content.py`
  (the v1 close, immediately prior to this session's v2 work) extracted as a
  standalone script and run unmodified.
- **After:** the current working tree's `scripts/quality/audit_all_content.py`
  (all v2 changes: TC-DCF-019/020/021, uncommitted).
- Both invoked as real subprocesses, both against the **same** isolated
  content roots (`ASPOSE_ORG_CONTENT`/`ASPOSE_NET_CONTENT` env-var overrides
  pointing at `%TEMP%\hugo-translator-dcf-pilot-20260727\{org,net}_content`),
  both producing real JSONL + console logs.

Pilot targets, chosen deliberately, not selectively favorable:
1. `reference.aspose.org/he/3d/java/mesh.md` — the original `AUD-DCF-010`
   purity-defect file.
2. `kb.aspose.org/ar/words/python/how-to-build-ldm-builder-python.md` —
   `TC-DCF-017`'s own clean **negative control**, reused verbatim for
   continuity.
3. `blog.aspose.net/zip/compress-files-folders-in-zip-csharp/index.ca.md` —
   a severe fence-loss (17→0) already caught by both old and new tolerance.
4. `blog.aspose.net/cells/lock-cells-in-excel-csharp/index.ar.md` — a
   moderate fence-loss (5→2) plus a shortcode-leak candidate.
5. `blog.aspose.net/barcode/.../index.bg.md` — deliberately selected as an
   **exact 2-fence loss (12→10)**, sitting precisely on the old tolerance's
   blind-spot boundary (`tgt < src-2` → `10 < 10` = false; new Gate 26:
   `tgt < src` → `10 < 12` = true). This is the case that actually
   distinguishes old vs. new behavior — the two more severe fence-loss
   files above do not, since both old and new catch a loss that large.

## Results

Both runs: **exit code 0**. Zero warnings/errors/retries/skips/tracebacks in
either log (`grep -iE "error|warn|retry|skip|traceback|exception"` on both,
excluding the expected "warn-only" gate-severity label). `missing` locale
counts identical (153 in both) — target-file discovery is unaffected, only
detector behavior differs. SHA-256 of all 10 pilot source files confirmed
byte-identical before and after both runs — the audit is read-only, as
designed; zero content mutation.

### Per-file issue diff

| File | Kept (both) | Resolved (before-only) | New (after-only) |
| --- | --- | --- | --- |
| `barcode/.../index.bg.md` (2-fence boundary case) | — | `inline_code_translated`¹ | **`code_fence_dropped`** |
| `cells/lock-cells-in-excel-csharp/index.ar.md` | `code_fence_dropped`² | `inline_code_translated`¹ | **`shortcode_leak`** |
| `zip/compress-files-folders-in-zip-csharp/index.ca.md` | `code_fence_dropped`², `shortcode_leak`, `gate40_seo_metadata_corruption` | — | — |
| `kb.aspose.org/.../how-to-build-ldm-builder-python.md` (control) | `double_period` | `inline_code_translated`¹ | — |
| `reference.aspose.org/he/3d/java/mesh.md` | `content_hash_stale_gate32`, `dropped_trailing_link_gate35`, `english_headings_nonlatin`, `heading_deficit_gate34`, `purity_issue` | `inline_code_translated`¹ | **`code_fence_dropped`** (a *different* defect than the known purity issue — see below) |

¹ `inline_code_translated` disappearing is **not attributable to this
mission**. Verified via `git diff 1261521 HEAD -- scripts/quality/audit_all_content.py`
(committed history, independent of the uncommitted v2 diff): the check was
rewritten between those two commits to use a dedicated
`src/translation_engine/quality/inline_code_repair.py::find_inline_code_mismatches`
matcher, replacing the old positional-zip backtick-pairing heuristic — a
separate, already-committed, unrelated improvement (matches the taskcard
notes: inline_code_translated is "owned by a separate, concurrent
shared-primitive effort"). Disclosed for completeness, not claimed as this
mission's result.

² Detail string format changed (cosmetic, more informative): before
`"src=5 fences, tgt=2 fences"`; after `"Gate 26 fence parity: src=5 fences,
tgt=2 fences (fence loss)"`. Same underlying finding, no behavior change.

### Site-wide issue totals (all 5 files + their 153 "missing" locale entries)

| Issue type | Before | After |
| --- | ---: | ---: |
| code_fence_dropped | 2 | **4** |
| shortcode_leak | 1 | **2** |
| inline_code_translated | 4 | **0** (unrelated, see¹) |
| purity_issue, english_headings_nonlatin, content_hash_stale_gate32, heading_deficit_gate34, dropped_trailing_link_gate35, double_period, gate40_seo_metadata_corruption | 1 each | 1 each (unchanged) |

## Verification of the targeted fix specifically

The deliberately-chosen boundary case (`index.bg.md`, 12→10 fences) is direct,
unambiguous proof: **before**, this exact 2-fence loss was silently accepted
(old tolerance requires `tgt < src - 2`, and `10 < 10` is false); **after**,
it correctly reports `code_fence_dropped` via Gate 26's zero-tolerance parity
check. This is the precise defect class `TC-DCF-019` was built to close,
demonstrated on a real file, not a synthetic fixture.

The `mesh.md` `code_fence_dropped` finding is a **second, distinct** defect
from its already-known purity issue: the live Gate 26 diagnostic identifies
it specifically as a "reopened fence" (a duplicated opening marker with no
intervening close) — a corruption shape invisible to any naive backtick-count
toggle, only detectable via the real markdown-it tokenizer
(`fence_spans.count_fence_open_reopens`). This is new evidence, not
previously surfaced in this mission's corpus-wide numbers for this specific
file, of the migration finding genuinely distinct real defects.

`shortcode_leak`'s new catch on the `cells/...` file matches the full-corpus
comparison's already-disclosed disposition (real EN/target structural
difference, code-region-aware detection working as intended).

## Summary

1. **What improved:** the exact targeted defect class (small, 1-2 fence
   losses silently tolerated by the old audit) is now caught, proven on a
   real file chosen specifically to sit on the old blind spot's boundary.
   A second, previously-invisible defect shape (reopened mid-snippet fences)
   is also now caught. `shortcode_leak`'s code-region migration surfaces a
   real, previously-missed structural difference. Zero regressions on the
   severe-loss files (already caught both before and after) or the reused
   clean control (identical finding set both times).
2. **What did not improve / is unrelated:** `inline_code_translated`'s
   change is real but belongs to a different, already-committed mission —
   not evidence of this mission's own work, disclosed rather than claimed.
   The five remaining fence-vulnerable checks outside this mission's scope
   (`artifact_corruption`, `eu_hallucination`, `link_path_corrupted`
   migrated with zero real-corpus behavior change observed; `inline_code_translated`
   not migrated here by design) are unchanged, as expected.
3. **Regressions introduced:** none found. Every file's finding set either
   stayed identical or gained a finding; no file lost a finding that this
   mission's changes are responsible for. The reused negative control
   (`kb.aspose.org` file) shows an identical finding set before and after
   (modulo the unrelated inline_code_translated change).
4. **Production-ready verdict:** the code changes are production-ready as a
   **reporting-accuracy improvement** — confirmed via a real CLI run, zero
   content mutation, zero regressions, and the specific targeted defect
   class demonstrated resolved on a real file chosen to isolate exactly that
   behavior. This does not mean the underlying **content** is production-ready:
   the newly-surfaced defects (4,174 code_fence_dropped + 463 purity +
   108 shortcode_leak instances corpus-wide, per the TC-DCF-022 full-corpus
   comparison) are real, previously-invisible content problems that still
   need a remediation pipeline — explicitly out of scope for this
   detector-hardening mission (successor: extend `AUD-DCF-010`).
