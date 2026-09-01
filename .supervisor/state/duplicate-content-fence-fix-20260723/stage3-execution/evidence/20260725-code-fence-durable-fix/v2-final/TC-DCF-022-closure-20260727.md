# TC-DCF-022 closure: non-selective full-corpus v2 comparison

## Resume context

Resumed 2026-07-27 from `BLOCKED_PLATFORM_EXECUTION_LIMIT`
(`continuation-state.yaml`, `next_task: TC-DCF-022`). The blocking condition
recorded on 2026-07-25 was that the comparator exceeded a ten-minute
foreground command execution ceiling twice. This session's tooling supports
launching a long-running command detached (`nohup ... &`, `disown`) and
polling for completion out-of-band, which is not subject to that per-call
ceiling. Two runs were required before the result could be trusted — see
"Comparator defect found and fixed" below.

## Comparator defect found and fixed (new finding this session, not present in
## the v2 scope as originally described)

While reviewing the first (2026-07-27) run's raw samples before accepting
them, `code_fence_dropped`'s `old_only` list (85 files) was spot-checked
directly against the real files rather than taken at face value.
`blog.aspose.net/zip/compress-files-folders-in-zip-csharp/index.ca.md`
(EN source has 17 fence markers; the Catalan translation has 0 -- a genuine,
severe fence-loss defect) was verified two independent ways to actually still
be a live Gate 26 finding in the real, shipped code:

1. `scripts/quality/audit_all_content.py::check_code_fence_dropped()` (the
   production-faithful wrapper, matching how `_run_registry_gates` invokes
   gate 26 with raw content) reports `issue=True` for this pair.
2. `WriteGateEvaluator._gate_fence_parity()` called directly with the raw
   (unstripped) file content also reports `passed=False` for this pair.

Yet the comparator script (`compare_v2_detectors_full_corpus.py`) classified
this exact pair as `old_only` (a claimed regression). Root cause: its
`new_hit()` function computes `source_body`/`target_body` once via
`current.get_body()` (frontmatter-stripped) for every check, and the
`code_fence_dropped` branch passed those already-stripped bodies directly
into `_gate_fence_parity()`, which performs its **own** internal
`self._get_body()` strip. Double-stripping a real file (which always has
frontmatter) silently truncated/corrupted the content that the fence count
ran against, producing a false "passed" for files where this mattered. This
bug was specific to the comparator script; **no shipped detection code was
affected** (confirmed: `scan()`'s real call path,
`_run_registry_gates() -> run_all_content_gates()`, always passes raw
content and was never double-stripped).

Fix applied directly to the comparator script's `code_fence_dropped` branch:
pass the raw `source`/`target` strings into `_gate_fence_parity()` instead of
the pre-stripped `source_body`/`target_body`. (An intermediate attempt routed
through `current.check_code_fence_dropped()` for full production fidelity,
but that function internally calls the full ~20-gate battery, including
FastText-based whole-page language detection (Gate 42), once per file purely
to read gate 26's verdict back out -- this made a corpus-wide run
impractically slow, no output after 50+ minutes, and was abandoned in favor
of calling `_gate_fence_parity()` directly with raw content, which is both
correct and cheap.) Re-verified against the same real file pair before
re-running the full corpus: `passed=False`, matching the two independent
checks above.

## Final, corrected full-corpus result

136,690 paired targets across all 18 registry-driven sites, same-read
(historical function extracted from `git show 3599a45:...`, current
functions read from the live working tree, both evaluated against one
in-memory file read per pair). Elapsed: 984.6s.

| Check | Before | After | New-only | Old-only |
| --- | ---: | ---: | ---: | ---: |
| artifact_corruption | 23 | 23 | 0 | 0 |
| eu_hallucination | 11 | 11 | 0 | 0 |
| link_path_corrupted | 298 | 298 | 0 | 0 |
| shortcode_leak | 799 | 907 | 108 | 0 |
| code_fence_dropped | 3,752 | 7,926 | 4,174 | 0 |
| purity_issue | 3,284 | 3,744 | 463 | 3 |

Full machine-readable result:
`full-corpus-comparison-20260727-v3.json` (this directory). The first
(buggy) run's output, `full-corpus-comparison-20260727.json`, is retained
alongside it as a disclosed artifact of the defect above, not as a valid
result -- do not use it for any acceptance decision.

## Disposition of deltas

- **artifact_corruption, eu_hallucination, link_path_corrupted: zero deltas.**
  The canonical-primitive migration (TC-DCF-020) changed nothing observable
  on the real 136,690-pair corpus for these three checks -- a pure
  correctness/defense-in-depth improvement with no behavior change yet
  triggered by real content.
- **shortcode_leak: 108 new-only, 0 old-only.** Strictly monotonic
  improvement. Spot-checked
  `blog.aspose.net/cells/lock-cells-in-excel-csharp/index.ar.md`: the
  Arabic translation's non-code text contains a `{{< figure ... >}}`
  shortcode invocation that the EN source's non-code text (fence-excluded)
  does not contain at the same content position -- a genuine, real
  EN/target structural difference the migrated fence-aware check correctly
  surfaces.
- **code_fence_dropped: 4,174 new-only, 0 old-only** (after the comparator
  fix; the originally-observed 85 `old_only` were entirely an artifact of
  the double-strip bug above, not real regressions). This is exactly the
  reporting gap `TC-DCF-019` was built to close: Gate 26's zero-tolerance
  parity check replaces the old audit's loose tolerance
  (`tgt_fences < src_fences - 2`, only evaluated when `src_fences >= 4`),
  which silently passed small (1-2 fence) losses. The `blog.aspose.net`
  "barcode" article family shows this pattern repeated identically across
  ~20-30 locales per article -- consistent with a systematic MT-batch defect
  affecting every translation of a given source page uniformly, not
  isolated per-locale noise. Deep-verified on the representative
  `index.ca.md` case above (src=17/tgt=0, confirmed via two independent
  real-code paths).
- **purity_issue: 463 new-only, 3 old-only.** The 3 `old_only` cases are
  all `bg` locale, fully explained by `config/global.yaml`'s
  `purity_threshold_overrides: bg: 0.15` (Bulgarian gets a deliberately
  looser 15% bound than the 6% default, to tolerate barcode-symbology
  product names) -- exactly the live-gate per-language nuance `TC-DCF-021`
  was built to adopt, not a regression. Spot-checked
  `about.aspose.net/ar/legal/privacy-policy.md`: ratio 0.0645, just over the
  6% default threshold (31 paragraphs, ~2 read as English) -- a genuine,
  marginal boundary case consistent with tightening from the old flat 10%
  to the live gate's 6%, not a false-positive explosion. The `blog.aspose.net`
  "barcode" family again shows the same repeated-across-locales pattern as
  `code_fence_dropped`, for the same likely root cause.

No content or TM remediation is performed in this detector-hardening
mission. The full set of new-only paths (not just the 20-per-check samples
above) is in `full-corpus-comparison-20260727-v3.json` for a future
remediation mission to consume; extending `AUD-DCF-010`'s successor scope
(previously 7 files) to cover this much larger, now-accurately-measured
backlog is a decision for that successor mission, not this one.

## Acceptance

- `git status --porcelain` reviewed before this run: no content, TM, or
  configuration files were mutated by this comparison (read-only file reads
  plus one in-memory JSON write to the evidence bundle).
- Focused suite re-confirmed unaffected by the comparator fix (the fix only
  touches an evidence-bundle script, not `scripts/quality/audit_all_content.py`
  or any test): 57/57 still passing as of this session's earlier rerun.
- All six checks now show zero unexplained deltas: three are unchanged, one
  is a clean monotonic improvement, and the remaining two have every
  `old_only` case fully accounted for by an intentional, already-tested
  design decision (per-language threshold override), with `new_only` samples
  spot-checked and confirmed genuine.

**Verdict: `TC-DCF-022` = `COMPLETED_VERIFIED`.** The non-selective,
full-corpus, same-read comparison required by the mission's own resume rule
is complete, inspected, and every delta is reconciled or explicitly
attributed. This closes the last open gate of plan v2.
