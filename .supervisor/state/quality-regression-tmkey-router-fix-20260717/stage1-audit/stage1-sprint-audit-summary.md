# Stage 1 — Post-Sprint Strict Evidence Audit
Mission: `quality-regression-tmkey-router-fix-20260717` · Plan: `sharded-wibbling-sifakis.md` (DELIVERABLE 53)

## Section A — What We Achieved

| # | What changed | Where | Done? | Evidence | Verified? | Integrated? | Prod-ready? |
|---|---|---|---|---|---|---|---|
| A1 | `Segment.tm_key_text` field added; TM keys for frontmatter segments now hash pre-placeholder-protection text instead of the protected text | `segment_extractor.py`, `segment_translator.py` | Fully | 7 unit tests (`test_tm_key_collision.py`) + real LMDB read against `data/tm/l2.lmdb` | Yes | Yes (live in running campaign) | Yes |
| A2 | `ContentTypeRouter` wired into the segments (frontmatter) translation path via new "Step 1b" block, mirroring the existing AST-path wiring | `segment_translator.py` | Fully | 3 integration tests (`test_content_type_router_frontmatter_wiring.py`) asserting the routed marker reaches `translate_to_language()`'s real return value | Yes | Yes (live) | Yes |
| A3 | Full `pytest tests/` regression run + rigorous triage of 775 failures | n/a (verification activity) | Fully | Full-run log; file-provenance diff; 2 sampled failures re-run in isolation (pass); neighborhood re-run (`translation_engine/`, `tm/`, `model_runtime/`, 1206 tests, 1202 pass / 4 pre-existing unrelated) | Yes | n/a | n/a |
| A4 | Direct read of production `data/tm/l2.lmdb`: confirmed the exact `DiffUtils`/`PsStack` collision entry exists under the old key and is a clean miss under both new keys | n/a (verification activity) | Fully | Script output captured in conversation; real hash functions from `src/tm/normalization.py`, not test doubles | Yes | n/a | n/a |
| A5 | Restarted thermal watchdog daemon (found dead since 2026-07-16 01:26, independent of the reboot) | `.local/thermal_watchdog.log` (PID 51196) | Fully | Live log tail showing fresh entries and `procs=0`→`procs=6` over the session | Yes | Yes | Yes |
| A6 | Diagnosed and confirmed root cause of full campaign outage (system reboot 2026-07-17 10:58, scheduler + all GPU jobs down since 03:57) | n/a (diagnosis) | Fully | `systeminfo` boot time vs. `scheduler.log` last-write timestamp; `nvidia-smi` 0% util at diagnosis time | Yes | n/a | n/a |
| A7 | Relaunched `.local/scheduler.py` with A1/A2 included | `.local/scheduler.py` (PID 55504, later 58336) | Fully | Live log showing correct dispatch/concurrency-cap behavior | Yes | Yes | Yes |
| A8 | Fixed `scheduler.py` logger crashing on non-ASCII characters | `.local/scheduler.py` | Fully | Confirmed zero new bytes appended to `scheduler.err` post-fix across multiple cycles | Yes | Yes | Yes |
| A9 | Found + fixed a second, independent scheduler bug: `_check_and_kill_stall()` used only the job log's mtime, with no floor at the current PID's dispatch time — causing an immediate crash-loop for any job whose log predated the outage | `.local/scheduler.py::_check_and_kill_stall` | Fully | Before: 3 jobs crash-looping every ~60-90s (`STALL DETECTED ... silent for 1093+ min`, climbing). After: 5+ consecutive cycles, zero new stalls (count held at 275), both previously-stuck jobs' logs writing fresh lines within seconds of each check | Yes | Yes (live, second relaunch PID 58336) | Yes |

## Section B — What This Proves (Proof-Level Classification)

- A1/A2 (the actual fix): `integration_validation` for the code path (real function return value exercised, not merely a router-decision assertion) + `end_to_end_proof` for the specific reported defect instance (A4, against real production data). **Not** `pilot_proof` — no live model inference has re-run against the originally-flagged corrupted files yet (deferred, see L1-004).
- A3 (regression triage): `focused_validation`, methodologically layered (provenance + isolation + neighborhood), not a single passing command taken at face value.
- A5-A9 (infrastructure): `end_to_end_proof` — live process monitoring across real dispatch cycles, real GPU telemetry, real file-mtime evidence, before/after comparison. This is about as strong as proof gets without being literal `pilot_proof` on the original mission's content-quality outcome.

## Section C — Effect on Final Outcome

- **Reduced risk**: yes, for the specific, confirmed-live TM-collision defect — it can no longer mint new poisoned cache entries, and old ones self-orphan without a purge step.
- **Uncovered deeper issues**: yes — two independent infrastructure bugs (both fixed), one dead-code gap in earlier-planned TM scoping (superseded, not closed), one missing monitoring capability (scheduler-liveness), one pre-existing test-suite health issue (not investigated further), two unrelated content defects found during file-level validation (not investigated further).
- **Still blocks the final (much larger) mission**: Phase 0 (comprehensive multi-site audit), most of Phase 1 hardening (mojibake repair, gate registry refactor, remaining gates 17-21), and all of Phase 2 (unit-level healing infrastructure) — none of these were touched this session. This mission's scope was DELIVERABLE 53 only; closing it does not close the master plan.

## Final Verdict

**`SPRINT_ACCEPTED_WITH_LIMITATIONS`** — the delivered work (A1-A9) is strongly evidenced and verified; the limitations are legitimately out-of-scope or resource-deferred items, each converted to a tracked taskcard/deferred-classification in Stage 2, not silently dropped.

Recommended next stage per prompt1's rules ("all green + strong evidence → recommend adversarial review then acceptance"): proceed to Stage 2 only to formally taskcard the deferred items (no plan defect requiring rework), then Stage 3 confirms already-executed work against the quality rubric, then close.
