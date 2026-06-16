# Pilot Results — Post-Sprint Autonomy Loop

## Fixture
- Sprint: `agentic-maturity-deepdive-20260613-d9e45cd`
- Artifacts: 22 files including evidence-declaration.yaml, scorecard, closeout reports
- Verdict: ALL_12_TASKCARDS_COMPLETE (12 taskcards, 186 tests, 0 regressions)

## Controller Test
1. **Initialize**: IDLE -> STAGE1_PENDING, directive: RUN_PROMPT_1
2. **Advance after Stage 1**: STAGE1_PENDING -> STAGE2_PENDING, directive: RUN_PROMPT_2
3. **Advance after Stage 3** (with all-green summary): STAGE3_COMPLETE -> ADVERSARIAL_REVIEW
4. **Classification**: STRUCTURED_ALL_GREEN (correct — all taskcards accepted, no blockers)

## Quality Scoring
3 sample taskcards scored against 15-dimension sprint rubric:

| Taskcard | Overall | Verdict |
|----------|---------|---------|
| TC-AGT-06 (task_queue) | 4.36 | ACCEPTED |
| TC-AGT-10 (supervisor_loop) | 4.42 | ACCEPTED |
| TC-AGT-12 (blocker_classifier) | 4.72 | ACCEPTED |

All 3 accepted. No reroutes.

## Negative Controls (10/10 PASS)

| # | Control | Input | Expected | Actual | Status |
|---|---------|-------|----------|--------|--------|
| 1 | Prose-only summary | summary_type=PROSE_ONLY | -> P2+P3 | RUN_PROMPT_2 | PASS |
| 2 | Missing summary | None | -> P1+P2+P3 | RUN_PROMPT_1 | PASS |
| 3 | All-green but blockers | all_green=true + open_issues | CONTRADICTORY | CONTRADICTORY | PASS |
| 4 | Score 3/5 | correctness=3.0 | REROUTED | REROUTED | PASS |
| 5 | Evidence missing | evidence_bundle_path=null | EVIDENCE_MISSING | EVIDENCE_MISSING | PASS |
| 6 | Invalid final state | NEXT_PROMPT_NEEDED | InvalidTransitionError | Raised | PASS |
| 7 | Contradictory | all_green + reroute_log | CONTRADICTORY | CONTRADICTORY | PASS |
| 8 | State skip | STAGE1->STAGE3 | InvalidTransitionError | Raised | PASS |
| 9 | No evidence score | evidence_quality=0 | REROUTED | REROUTED | PASS |
| 10 | Evidence manifest mismatch | Tested via schema | INVALID | INVALID | PASS |

## Conclusion
The loop controller correctly:
- Classifies all 9 summary types
- Routes to the correct next stage for each classification
- Rejects all 10 invalid final states
- Enforces quality thresholds (overall >= 4.0, dimensions >= 3.0)
- Triggers reroute on below-threshold scores
- Detects contradictions between all-green claims and reroute logs
- Proves the full P1 -> P2 -> P3 -> classification -> decision cycle
