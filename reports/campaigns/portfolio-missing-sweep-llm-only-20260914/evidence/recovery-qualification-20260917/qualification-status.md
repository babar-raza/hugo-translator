# Recovery qualification status

Status: PAUSED_VALIDATION_REGRESSION

The Gate 45 receipt-contract repair was verified by focused tests and a
single-controller canary. Six receipt-backed files landed in one governed
`docs.aspose.org/barcode/python` commit (`81ea7f1331bbfd736e16c60ca9fa270b84af8e3e`)
with `Codex` co-authorship and post-commit hash verification.

The supervised four-worker soak reached 20 terminal jobs: 16 accepted and 4
rejected (80% acceptance). It was then paused by the watchdog after three
consecutive `GATE14` mixed-language failures. No unattended release is
authorized until those failures are diagnosed with protected candidate
quarantine and fixed only with evidence-backed regression tests.

TM spool was drained after the soak: `PENDING=0`, `CLAIMED=0`, `APPLIED=8101`.

Follow-up repair `e22e65e3` adds evidence-backed GATE14 retry guidance and a
regression test (retry-feedback tests pass). A write-enabled post-repair
GATE14 canary is still required; the first diagnostic attempt was stopped
after bounded observation because the provider work was not yet terminal.

The 2026-09-17 post-repair canary remained non-compliant: `encode-options.md`
continued to reject for ja, ko, and zh with five untranslated English lines.
The additional table/list/frontmatter retry wording is covered by five focused
tests, but runtime output did not improve. The canary was terminated with
receipts preserved; no unattended release or soak restart is authorized.
It also produced one unrelated accepted `ko/barcode-rendering.md` receipt,
left uncommitted because it is not a governed minimum-size batch. Current
ledger totals are 23 receipts and 143 failure records and are historical, not
a release qualification.
