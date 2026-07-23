# Stage 1 Post-Sprint Audit — duplicate-content-fence-fix-20260723

## Section A: What We Achieved

1. **Root-caused the "Duplicate content (repeated paragraph): 3,622" audit finding.** Traced to `scripts/quality/audit_all_content.py:373-380`. The check split translated page bodies on blank lines with no awareness of fenced code blocks, so distinct code examples on the same page sharing a short boilerplate opening line (an `#include`/import right after a fence) were miscounted as "the same paragraph repeated 3+ times." Verified against a real production file (`kb.aspose.org/ar/slides/cpp/how-to-add-comments-cpp.md`) and confirmed at scale via an 84-file stratified sample (fully done, evidence: real-file read + logic re-run, both before and after the fix).
2. **Found and fixed the same bug live in the write-time gate**, `_gate_duplicate_content` (Gate 16, `src/translation_engine/write_gate.py:1390-1431`, `auto_clean` disposition) — this was the more urgent instance, since it runs on every new/retranslated page and could silently delete legitimate boilerplate lines before a file is ever written. Fixed, and the identical fix applied to `scripts/quality/surgical_retranslate.py`'s detector/fixer (so the existing mechanical repair tool is now safe to run) and to `audit_all_content.py` itself (full-paragraph matching, was previously an 80-char-prefix key). Fully done.
3. **Re-scanned all 3,622 originally-flagged files** (exact match to the user-reported count, confirming which snapshot they were looking at) with the patched logic: 3,609 no longer flag (false positives from the code-fence-blindness bug). **13 remain.** Fully done, end-to-end proof (real file reads across the entire flagged set, not a sample).
4. **Manually inspected all 13 remaining candidates.** All trace to one English source page (`reference.aspose.org/en/3d/typescript/transform.md`) across 13 locales. Read the actual translated content with heading context and confirmed: these are legitimate, correct per-method "Returns: same `X` instance for chaining" API-reference documentation lines that genuinely repeat across different chainable setter methods (`setTranslation`, `setScale`, `setRotation`, ...) — not MT corruption. **Zero genuine defects found in the entire originally-flagged set.** Fully done.
5. **Added regression tests**: extended `tests/unit/translation_engine/test_write_gate_new_gates.py` with a Gate-16 code-fence case (73/73 tests pass, exercising the real `WriteGateEvaluator` class) and created `tests/unit/quality/test_surgical_retranslate_duplicate_content.py` (5/5 pass, exercising the real `surgical_retranslate` module functions via direct import, not a reimplementation).
6. **Concluded: no content edits and no TM cleanup are needed anywhere.** Running the mechanical dedup fixer on the 13 remaining files would have actively deleted legitimate documentation, so it was deliberately not applied.

## Section B: What This Proves

| Claim | Proof level |
|---|---|
| `write_gate.py` Gate 16 fix behaves correctly | `integration_validation` — real `WriteGateEvaluator.evaluate()` via pytest |
| `surgical_retranslate.py` fix behaves correctly | `integration_validation` — real module import, real production file + synthetic controls |
| `audit_all_content.py` fix behaves correctly | `integration_validation` — literal extraction+exec of the real on-disk code block (not hand-copied) against real production file + synthetic controls |
| 3,609/3,622 originally-flagged files are false positives | `end_to_end_proof` — every flagged file was actually re-read and re-checked, not sampled |
| The 13 remaining files need no fix | `focused_validation` — direct manual read of heading context for all 13 |
| The official `audit_all_content.py`/`surgical_retranslate.py` CLIs, run unscoped end-to-end, reproduce this | `no_proof_yet` at audit time — a full-corpus `surgical_retranslate.py --dry-run --sites all` run was launched in the background at execution time; see stage3 for its result if it completed before closure, otherwise it is recorded as a still-open, non-blocking verification (see next-stage-recommendation). |

## Section C: Effect on Final Outcome

- Reduced risk: yes — the live write-time Gate 16 bug (deleting real code lines from new translations) is closed, which was actively ongoing, not just a stale report artifact.
- Improved confidence: yes — the 3,622 figure is now understood to be ~99.6% measurement noise, not a real backlog of broken pages; no mass-remediation effort is needed.
- Uncovered a deeper issue: partially — AUD-L3-001 notes the same fence-blindness *pattern* was not swept across the other 22 checks in `audit_all_content.py`; deferred as a future-mission recommendation, not blocking.
- Moved materially closer to the final goal: yes, for this specific reported metric — it is resolved.
- Blockers before closure: work is implemented and tested but **uncommitted**, and 2 of the 4 touched files are co-mingled with large pre-existing unrelated uncommitted work that must be isolated before a clean commit (see AUD-L1-001, AUD-L1-002).

## Structured Issues

See `issues.json` for the full L1/L2/L3 issue records (7 issues: 4 L1, 3 L2, 1 L3). Two are blockers (AUD-L1-001 uncommitted work, AUD-L1-002 hunk isolation required); the rest are either already resolved during this audit pass (AUD-L1-003, test added) or accepted/deferred with justification (AUD-L1-004, AUD-L2-002, AUD-L2-003, AUD-L3-001).

## Evidence Quality Verdict

**STRONG**, with one explicitly-disclosed gap: no committed test exists for `audit_all_content.py`'s check specifically (mitigated via literal extract+exec proof, see AUD-L1-004), and full-CLI unscoped E2E confirmation was still running in the background at audit time rather than complete.
