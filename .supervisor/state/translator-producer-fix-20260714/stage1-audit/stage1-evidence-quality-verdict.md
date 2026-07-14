# Stage 1 — Evidence Quality Verdict

**Overall: ADEQUATE_WITH_LIMITATIONS**

## Why not STRONG
- AUDIT-002: safe_io.py's own choke-point behavior lacks a real batch-scale `--apply` run this session.
- AUDIT-003: `.local/unified_translate.py`'s change was reviewed but not executed this session.
- The original full-tree baseline's itemized failure list was lost to a `tail -n 40` truncation mistake early in the session (self-identified, see AUDIT-004 discussion) — the final delta was verified sound via isolation rather than a direct line-by-line diff against the original baseline.

## Why not WEAK/INSUFFICIENT
- Every one of the three target corruption classes (description-truncation, fence-strip, prompt-leak) has direct proof against **real historical wave-3 damage** extracted from aspose.org git history — not synthetic fixtures alone.
- TC-HT-011 provided genuine `pilot_proof`: real GPU model loading, real translation, real gate evaluation, real writes, real comparison against live aspose.org content.
- The +16 full-suite failure delta was not accepted at face value — it was directly investigated (isolated rerun of the exact 902-test set = 100% clean; a second independent full run exposed an unrelated pytest-capture crash, confirming environment-level non-determinism rather than a code regression).
- Scoped regression checks were run identically 8 times (after every commit) with consistent, reproducible results (0 new failures every time) — this is a strong, repeated signal, not a one-off claim.
- All deviations from the literal implementation brief (AUDIT-005, Gate 19 retention, fence-newline idempotency fix, `BYPASS_PLACEHOLDER_PROTECTION` relocation) are disclosed in commit messages with technical justification, not silently introduced.

## Missing raw logs / consumer validation
- None of the 3 target corruption classes lack raw-log evidence: golden-corpus test output and the TC-HT-011 pilot logs are all preserved as pytest output / log files referenced in commit messages.
- Consumer-side validation (the actual aspose.org commit-time gates) is explicitly NOT run this session — correctly deferred per the brief's own scope boundary, not a gap in this audit.
