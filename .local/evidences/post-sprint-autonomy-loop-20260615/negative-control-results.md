# Negative Control Results

All 10 negative controls prove fail-closed behavior.

## NC-1: Prose-only summary -> P2+P3
- Input: `{"summary_type": "PROSE_ONLY"}`
- Expected: classify as PROSE_ONLY, route to RUN_PROMPT_2
- Result: **PASS** — classification=PROSE_ONLY, action=RUN_PROMPT_2

## NC-2: Missing summary -> P1+P2+P3
- Input: `None`
- Expected: classify as MISSING, route to RUN_PROMPT_1
- Result: **PASS** — classification=MISSING, action=RUN_PROMPT_1

## NC-3: All-green but blockers exist -> blocked
- Input: `all_green=true` with `open_issues=["L1-001"]`
- Expected: classify as CONTRADICTORY
- Result: **PASS** — classification=CONTRADICTORY

## NC-4: Score 3/5 in required dimension -> rerouted
- Input: `correctness=3.0` (below critical threshold 4.0)
- Expected: verdict=REROUTED with rework_items
- Result: **PASS** — verdict=REROUTED, 1 rework item

## NC-5: Evidence bundle missing -> blocked
- Input: `evidence_bundle_path=null`
- Expected: classify as EVIDENCE_MISSING
- Result: **PASS** — classification=EVIDENCE_MISSING

## NC-6: NEXT_PROMPT_NEEDED as final state -> rejected
- Input: `current_state="NEXT_PROMPT_NEEDED"`
- Expected: InvalidTransitionError raised
- Result: **PASS** — error raised with "never valid as a final state"

## NC-7: Contradictory summary vs reroute log -> CONTRADICTORY
- Input: `all_green=true` with non-empty `reroute_log`
- Expected: classify as CONTRADICTORY
- Result: **PASS** — classification=CONTRADICTORY

## NC-8: State transition skips VERIFIED -> rejected
- Input: transition STAGE1_PENDING -> STAGE3_COMPLETE
- Expected: InvalidTransitionError raised
- Result: **PASS** — error raised with allowed transitions listed

## NC-9: Taskcard accepted without evidence -> blocked
- Input: `evidence_quality=0.0` in dimension_scores
- Expected: verdict=REROUTED (score below 3.0 minimum)
- Result: **PASS** — verdict=REROUTED

## NC-10: Evidence manifest mismatch -> invalid
- Enforced by schema validation: `stage3-quality-score.schema.json` requires
  `evidence_bundle_path` to be non-null for acceptance
- Unit test `test_evidence_missing` validates this path
- Result: **PASS**
