# POST-SPRINT LOOP CONTROLLER

## Title
Post-Sprint Loop Controller — Summary Parsing, Next-Stage Decision, Reroute, and All-Green Acceptance

## Purpose
This document instructs the agent on how to use the loop controller to automatically determine the next required stage. **Do not ask the user which prompt to run.**

## How the Loop Works

### 1. Check for Existing State
Read `loop-state.json` in the run directory. If it doesn't exist, run:
```
python scripts/ops/sprint_loop_controller.py --run-dir <path> --dry-run
```
This creates the initial state and determines the first directive.

### 2. Read the Directive
Open `next-directive.json`. It tells you:
- `action`: Which prompt to run (RUN_PROMPT_1, RUN_PROMPT_2, RUN_PROMPT_3, etc.)
- `prompt_asset_path`: Path to the prompt markdown to follow
- `input_dir`: Where to read inputs from
- `output_dir`: Where to write outputs
- `open_issues`: Issue IDs to focus on (if rework)
- `reason`: Why this action was chosen

### 3. Execute the Stage
1. Read the prompt asset at `prompt_asset_path`
2. Follow its instructions exactly
3. Write all outputs to `output_dir`
4. Ensure outputs conform to the schema referenced in the prompt

### 4. Advance the Controller
After completing the stage, run:
```
python scripts/ops/sprint_loop_controller.py --run-dir <path> --advance
```
This reads your outputs, classifies the result, and updates `next-directive.json`.

### 5. Repeat Until Terminated
- Read `loop-state.json` → check `current_state`
- If `TERMINATED`: the loop is complete
- If anything else: go to step 2

## Summary Classification
The controller classifies Stage 3 output automatically:

| Classification | What It Means | Controller Action |
|---------------|---------------|-------------------|
| STRUCTURED_ALL_GREEN | All taskcards accepted, no blockers | Adversarial review |
| STRUCTURED_NOT_GREEN | Structured but issues remain | Feed to Prompt 2 |
| PROSE_ONLY | No structured summary | Run Prompt 2 then 3 |
| MISSING | No summary file found | Run Prompt 1, 2, 3 |
| CONTRADICTORY | All-green claim but reroute log non-empty | Blocked |
| EVIDENCE_MISSING | No evidence bundle | Evidence repair |
| SCORES_MISSING | Unscored taskcards | Quality scoring |
| TASKCARDS_INCOMPLETE | Non-terminal taskcard statuses | Run Prompt 2 |
| BLOCKED_EXTERNAL | True external blocker | Package and stop |

## Invalid Final States
The controller will never accept these as terminal:
- NEXT_PROMPT_NEEDED
- HUMAN_REVIEW_NEEDED_BEFORE_AGENT_REVIEW
- PROSE_ONLY_ACCEPTED
- SUMMARY_MISSING_ACCEPTED
- SCORE_BELOW_4_ACCEPTED
- EVIDENCE_PACKAGE_MISSING_ACCEPTED

If the controller detects any of these, it automatically routes to the appropriate repair stage.

## Quality Thresholds
- Overall score >= 4.0
- No dimension < 3.0
- Critical dimensions (correctness, completeness) >= 4.0
- Any violation → REROUTED

## CLI Reference
```bash
# Initialize or check state (read-only)
python scripts/ops/sprint_loop_controller.py --run-dir <path> --dry-run

# Advance after completing a stage
python scripts/ops/sprint_loop_controller.py --run-dir <path> --advance

# Force a specific stage (override)
python scripts/ops/sprint_loop_controller.py --run-dir <path> --force-stage 1
```
