# v2 execution status and direct pilot comparison

## Completed end-to-end pilot

The actual `audit_all_content.py` pipeline ran on isolated copies of two
real source/target pairs with the production `docs.aspose.org` and
`kb.aspose.org` profiles. Both reruns exited `0`; output JSONL and metadata
parse as standard UTF-8 JSON. The four pilot inputs retain the exact SHA256
values recorded by TC-DCF-017, so the audit made no content mutation.

| Pair | Previous (`1261521^`) | Current v2 | Disposition |
| --- | --- | --- | --- |
| Broken docs VI quickstart | `english_headings_nonlatin`, newline-spanning `inline_code_translated`, `heading_deficit_gate34` | `purity_issue`, `code_fence_dropped` (`src=8`, `tgt=6`), `heading_deficit_gate34` | Gate 26 reporting is fixed. The removed heading and inline findings are prior false-positive shapes, respectively fenced text and a newline-spanning backtick pair; they are not caused by the v2 change. |
| Valid KB AR control | newline-spanning `inline_code_translated`, `double_period` | `double_period` | No new target-check finding. The removed inline finding is the same prior false-positive shape. |

Logs preserve 24 expected missing locales for each one-locale isolated site.
There were no audit retries, no audit read errors, and no generated-file or
pilot-input mutations. The docs log contains the same live Gate 26 diagnostic
that is now present in JSONL.

## Focused verification

- 141 focused fence/audit/write-gate tests passed; only three external
  `SwigPy*` deprecation warnings were emitted.
- The independent reviewer initially rejected v2 for three evidence/
  metadata gaps. The reopen evidence was added, the JSON artifact was
  rewritten BOM-free and parsed by standard UTF-8 JSON, and content-root
  SHA/dirty-or-error fingerprinting was added with regression coverage.
- Final independent review accepted the repaired scope, including the case
  where a bounded `git status` times out after `rev-parse` succeeds: the
  content SHA is retained and only `dirty` is marked unknown.

## Non-selective comparator limitation

Two read-only full-corpus attempts were made:

1. The complete historical all-gate audit was stopped after exceeding the
   platform's ten-minute foreground execution ceiling; its partial logs are
   retained with an explicit stop record.
2. A same-read comparator for the six v2-changed detectors was optimized to
   prefilter non-candidates, then also reached the same hard ten-minute
   ceiling before it could write final totals.

Neither partial log is used as a corpus-result claim. This leaves
TC-DCF-022 open: run the same comparator in an environment without the
per-command ten-minute limit (or add resumable checkpoints) and inspect all
new-only paths before an `ACCEPTED_VERIFIED` production verdict.

## Current verdict

**INCOMPLETE, NOT production-ready for audit-level closure.** The specific
Gate-26 reporting defect and code-region false-positive class are pilot- and
test-proven resolved, but the required non-selective full-corpus v2 delta is
not yet available.
