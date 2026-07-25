# End-to-end audit pilot: committed revision vs immediate predecessor

## Design

The pilot uses isolated copies of two real EN/translated pairs under the real
`docs.aspose.org` and `kb.aspose.org` site profiles. The actual audit
`scan()` pipeline performed profile loading, source discovery, locale target
resolution, body parsing, hand-implemented checks, registry gates, console
logging, and JSONL emission. Only one translated locale was copied per site;
the other 24 expected locales are intentionally reported as `missing` in both
runs and are not a quality regression.

- **Before:** `1261521^` (the immediate pre-fix audit script).
- **After:** committed mission revision `1261521`.
- The current working-tree CLI was also run and retained as a reference, but
  is not used for attribution because it includes unrelated unstaged
  inline-code work in `audit_all_content.py`.

## Direct comparison

| Pilot | Before JSONL issues | After JSONL issues | Meaning |
| --- | --- | --- | --- |
| Real broken-fence target: `docs.aspose.org/vi/cells/typescript/getting-started/quickstart.md` | `english_headings_nonlatin`, `inline_code_translated`, `heading_deficit_gate34` | `purity_issue`, `inline_code_translated`, `heading_deficit_gate34` | **Improved:** the new parser-backed purity check flags 14% English prose that the prior regex split masked. Existing inline-code and heading-deficit findings remain visible. |
| Valid-fence control: `kb.aspose.org/ar/words/python/how-to-build-ldm-builder-python.md` | `inline_code_translated`, `double_period` | `inline_code_translated`, `double_period` | **No target regression:** the migration neither added a purity/duplicate/English-heading finding nor hid the pre-existing unrelated findings. |

The previous and committed docs runs each completed with exit code 0, emitted
one JSONL record for the copied translation, and had no audit retry/skip/error
records. Both console runs emitted the existing Gate 9, Gate 26, and Gate 34
diagnostics; these are preserved in the command transcript. SHA256 comparison
after all runs proves all four pilot EN/target files are byte-identical to
their production-checkout originals.

`pilot-comparison.json` contains parsed issue counts, raw JSONL records, log
signal counts, and the hash evidence. The individual generated JSONL/log files
are retained beside it.

## Before vs broad prior run

The earlier 136,689-file same-read comparison remains the non-selective
corpus control: duplicate content changed `62 -> 52` with no new findings;
purity changed `3,313 -> 3,284` with seven newly exposed genuine fence-loss
defects and 36 resolved false positives. This pilot reproduces one of those
seven genuine newly exposed defects through the actual scanner.

## Remaining root cause and production action

The live Gate 26 console diagnostic reports `src=8 fences, tgt=6 fences`, but
the audit JSONL does **not** include `code_fence_dropped`: its hand-implemented
legacy check still accepts a two-fence loss (`tgt < src - 2`). This confirms
the plan's Phase 4 report-parity weakness. Route it to
`AUD-AUDIT-REPRO-001`: replace the stale audit rule with the live zero-
tolerance parity logic, emit the applied threshold/config fingerprint, and
rerun this pilot plus the full corpus before claiming audit-level production
completeness. The five remaining fence-vulnerable checks remain in
`AUD-FENCE-SWEEP-001`.
