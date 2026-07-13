# POST-SPRINT LOOP CONTROLLER
# Summary Parsing, Next-Stage Decision, Reroute, and All-Green Acceptance
# State machine: .supervisor/schemas/loop-decision-state-machine.schema.json
# Classifier contract: .supervisor/schemas/summary-parser-contract.schema.json

---

## Mission

Read Prompt 1, Prompt 2, and Prompt 3 outputs. Determine the next required stage automatically. Do not ask the user which prompt to run.

## Inputs

- Stage 1 outputs (if present)
- Stage 2 outputs (if present)
- Stage 3 outputs (if present)
- Evidence manifest
- Taskcard index
- Quality evaluations
- Reroute log
- Final sprint summary YAML
- Evidence package path
- Blocker reports

## Summary Classifications

| Classification | Meaning |
|---|---|
| `STRUCTURED_ALL_GREEN` | Valid structured output, all quality scores >= 4, no open issues |
| `STRUCTURED_NOT_GREEN` | Valid structured output but open issues or scores < 4 |
| `PROSE_ONLY` | Output is prose without structured YAML/JSON data |
| `MISSING` | No output found |
| `CONTRADICTORY` | All-green claim contradicts reroute log or open issues |
| `EVIDENCE_MISSING` | Structured output but no evidence bundle |
| `SCORES_MISSING` | Structured output but quality scores not present |
| `TASKCARDS_INCOMPLETE` | Taskcards exist but not all evaluated |
| `BLOCKED_EXTERNAL` | True external blocker identified |

## Decision Rules

| Condition | Action |
|---|---|
| Stage 3 summary is `PROSE_ONLY` | Run Prompt 2 then Prompt 3 |
| Stage 3 summary is `MISSING` | Run Prompt 1 then Prompt 2 then Prompt 3 |
| Stage 3 summary is `STRUCTURED_NOT_GREEN` | Feed open issues into Prompt 2, then run Prompt 3 |
| Stage 3 has `SCORES_MISSING` | Run or rerun quality scoring, then reroute or accept |
| Stage 3 has `EVIDENCE_MISSING` | Run evidence packaging and evidence validation lane |
| Stage 3 taskcards are incomplete | Run Prompt 2 |
| Stage 3 has any score below 4/5 | Reroute to rework, run Prompt 3 for affected taskcards |
| Stage 3 is `STRUCTURED_ALL_GREEN` | Run independent adversarial review. Accept only if it passes |
| Stage 3 is `CONTRADICTORY` | Hard stop, investigate contradiction |
| `BLOCKED_EXTERNAL` | Verify blocker, package evidence, and stop |

## Invalid Final States

These states are NEVER valid as final loop outcomes:
- `NEXT_PROMPT_NEEDED`
- `HUMAN_REVIEW_NEEDED_BEFORE_AGENT_REVIEW`
- `PROSE_ONLY_ACCEPTED`
- `SUMMARY_MISSING_ACCEPTED`
- `SCORE_BELOW_4_ACCEPTED`
- `EVIDENCE_PACKAGE_MISSING_ACCEPTED`
- `PLAN_UPDATED_NOT_EXECUTED`
- `EXECUTED_NOT_EVALUATED`
- `PROMPT_ASSETS_DISCONNECTED`
- `TASKCARDS_MISSING_ACCEPTED`

## Max Loop Iterations

Default: 3 outer loops. After max iterations, STOP and report what remains unresolved.

## Required Outputs

- `loop-summary-classification.yaml`
- `loop-decision.yaml`
- `loop-open-items.yaml`
- `loop-next-stage-inputs.md`
- `loop-final-state-verdict.md`

## Implementation

Python implementation: `tools/supervisor/post_sprint_loop_controller.py`
Summary classifier: `tools/supervisor/summary_classifier.py`
Quality scorer: `tools/supervisor/quality_scorer.py`

CLI: `python tools/supervisor/post_sprint_loop_controller.py --repo-root <path> --run-id <id> [--max-loops 3]`

Exit codes:
- 0: all-green, accepted
- 3: max loops exceeded with remaining issues
- 1: invalid state
- 9: unexpected error
