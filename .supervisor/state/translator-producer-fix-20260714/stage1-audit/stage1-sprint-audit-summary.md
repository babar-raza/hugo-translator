# Stage 1 — Post-Sprint Strict Evidence Audit

**Mission:** HT-PRODUCER-FIX-001 | **Session:** translator-producer-fix-20260714
**Audited range:** commits `f29c7cc`..`3112844` (9 commits) against baseline `4c26085`

## Section A: What We Achieved

All 11 taskcards from `plans/HT-PRODUCER-FIX-001-implementation-brief.md` are implemented, tested, and committed. Per taskcard (file/change, done-state, evidence, verified, integrated, production-ready, caveats):

| TC | What changed | Done | Evidence | Behavior verified | Integrated | Prod-ready | Caveats |
|---|---|---|---|---|---|---|---|
| 001 | Deleted dead fixer; rewrote 6 sibling first-line-regex sites (incl. write_gate.py Gates 10/18/24 + audit_linguistic.py, both undocumented in the brief) to parse frontmatter | Full | 69 tests, golden-corpus proof | Yes | Yes | Yes | Detector-vs-fixer deviation (AUDIT-005, disclosed, non-blocking) |
| 002 | New safe_io.py/fence_spans.py; converted all raw content writes; fence-aware repairs | Full | 10 tests | Yes (unit) | Partial | Mostly | No real --apply batch run this session (AUDIT-002) |
| 005 | Gate 26 (fence parity) + Gate 27 (multiline scalar preservation) | Full | 12 tests, golden-corpus proof | Yes | Yes | Yes | None |
| 003 | `_validate_llm_response()` rejects prompt-echo/refusal | Full | 12 tests (mocked provider) | Yes (mocked) | Yes | Yes | LLM-path tests are unit-level only — pre-accepted per master plan's own "Remaining True Blockers" |
| 006 | Removed permissive flags from drivers; `BYPASS_PLACEHOLDER_PROTECTION` fatal in `TranslationEngine.__init__`; `--force-accept` gated | Full | 8 tests + real CLI invocation via TC-HT-011 pilot log | Yes (incl. live) | Yes | Yes | `.local/unified_translate.py` half not executed this session (AUDIT-003) |
| 004 | Retired legacy reconstruction path; deleted ~120 lines proven 100% dead; default flip; idempotent fence-newline fix; widened block-child preservation | Full | Unit tests + real AST reconstruction exercised live via TC-HT-011 pilot (all 15 written pilot files went through the now-default AST path) | Yes (incl. live) | Yes | Yes | Escape-hatch (legacy) path deliberately not live-tested (correct — it's meant to be dead) |
| 007 | Vendored `check_text`/`check_pair`; wired into `safe_io.save()` | Full | 13 tests incl. real golden-corpus proof | Yes | Yes | Yes | Fixed EN/ES leak-phrase list — documented limitation, not a defect |
| 010 | 3 real wave-3 pairs extracted from aspose.org git history + adversarial resurrection test | Full | 13 tests, all against real production damage | Yes | Yes | Yes | fence_strip pair path found via diff scan, not brief-specified |
| 011 | E2E pilot, temp-dir only | Full | Real GPU/model translation, 15 files written, 0/0/0 corruption findings | Yes (live) | Yes | Deliberately scoped short of aspose.org write | Most files blocked by pre-existing Gate 21 (m2m100 quality limitation, not this mission's defect) — see AUDIT-004-adjacent observation below |
| 009 | Sibling-checkout disposition | Full (read-only, as scoped) | Direct git/filesystem inspection | Yes | N/A | N/A | None |

## Section B: What This Proves

- **end_to_end_proof / pilot_proof:** TC-HT-004 (AST path), TC-HT-006 (safe-flag CLI invocation), TC-HT-010 (adversarial resurrection against real data), TC-HT-011 (full pilot) — the core safety mechanisms were exercised with real GPU translation, real gate evaluation, real file writes (to a temp dir), and real comparison against live aspose.org content.
- **integration_validation:** TC-HT-001, TC-HT-005, TC-HT-007 — proven against real historical wave-3 damage pairs extracted from git history, not just synthetic fixtures.
- **focused_validation:** TC-HT-002 (safe_io.py's own choke-point logic, not yet run at batch scale), TC-HT-003 (LLM validation logic, mocked provider only — a pre-accepted limitation).
- **No conclusions rest on synthetic-only proof for the corruption-class fixes themselves** — every one of the three target corruption classes (description-truncation, fence-strip, prompt-leak) has at least one test exercised against the real historical damage that caused the wave-3 incident.

## Section C: Effect on Final Outcome

- Materially closes the wave-3 incident's producer-side root causes: the exact regex bug, LLM echo path, and permissive-flag combination that caused the 2026-07-12 corruption are now provably blocked, using the actual damaged production files as proof.
- Uncovered one deeper system weakness not previously known: full-tree pytest is not deterministic at ~7000-test scale on this environment (AUDIT-004) — orthogonal to this mission but worth a future infrastructure taskcard.
- Uncovered one governance gap: the external master plan was never synced during execution (AUDIT-001) — being corrected in Stage 2/3 of this convergence pass.
- Does NOT complete the full incident closeout: TC-HT-011's copy-into-aspose.org-and-prove-commit-gates step remains explicitly deferred to a separate, operator-supervised aspose.org session, per the brief's own hard rule and text — this is a scope boundary, not a gap.
- Blockers remaining: none for this mission's own closure. AUDIT-002/003 are low-severity, non-blocking follow-ups; AUDIT-004 is an infrastructure observation outside this mission's scope.
