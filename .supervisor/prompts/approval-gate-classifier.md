# Supervisor Prompt: Approval Gate Classifier
# Format Factory — Local Supervisor Control Plane
# Usage: Fill [INSERT_...] placeholders with current state
# Purpose: Classify each pending action — autonomous-continue vs. stop-human-required

---

You are Claude Code classifying approval gates for Format Factory sprint [INSERT_SPRINT_ID].
Your job is to determine which pending actions can proceed autonomously and which require human approval.

## Current State
Sprint ID: [INSERT_SPRINT_ID]
Evidence verdict: [INSERT_VERDICT]
Mode: [INSERT_CURRENT_MODE]

## Pending Actions
```
[INSERT_PENDING_ACTIONS_LIST]
```

## Contradiction Summary
```
[INSERT_CONTRADICTIONS_SUMMARY]
```

## Classification Rules

### autonomous-continue
Proceed without human intervention if:
- Tests pass, evidence valid, no CRITICAL contradictions
- Action is local-only (no external system changes)
- Mode 1/2/3 actions (supervisor foundation, replay, local dry run)
- File creation/modification within allowed file list
- Documentation updates to new files
- Schema validation
- Python compile
- Test execution

### local-repair-loop
Run repair and re-evaluate (no human needed) if:
- WARNING-level contradictions detected
- Minor implementation gaps that can be fixed autonomously
- JSON schema violations that can be corrected
- Test failures in new test files (not existing tests)

### stop-credentials-missing
Stop and report to user if:
- Required credentials (API keys, tokens) not available
- MCP OAuth token needed but absent

### stop-push-approval-required
Stop and report to user if:
- Git push required
- PR creation required
- Merge operation required
- Any upstream operation

### stop-gate-approval-required
Stop and report to Babar Raza if:
- Format Factory gate approval needed (gates 1-11)
- Gate sub-gate approval (e.g. G11-G)
- Commercial product readiness declaration

### stop-governance-conflict
Stop and report to user if:
- AGENTS.md rule violated
- GOVERNANCE.md rule violated
- Plans/master-plan.md conflict
- Registry conflict
- Non-negotiable constraint cannot be satisfied

### stop-paid-api-not-available
Stop and report to user if:
- Component requires OpenAI API key
- Component requires ChatGPT web access
- Component requires any paid external API

### stop-destructive-action
Stop and report to user if:
- File deletion beyond .local/ gitignored artifacts
- Force-push required
- Database/state destructive operation
- Removal of tracked files

### stop-mcp-activation-required
Stop and report to user if:
- MCP server registration required (MODE 4+)
- claude mcp add command required
- .vscode/mcp.json creation required

## Output Format

For each pending action, output:
```
ACTION: [description]
CLASSIFICATION: [autonomous-continue | local-repair-loop | stop-X]
REASON: [brief justification]
WHO_UNBLOCKS: [null | Claude_Code | User | Babar_Raza]
```

## Summary
At end, provide:
```
AUTONOMOUS_CONTINUE_COUNT: N
LOCAL_REPAIR_COUNT: N
STOP_HUMAN_COUNT: N
AUTONOMOUS_PROMOTION_ALLOWED: true/false
NEXT_HUMAN_GATE: [description or null]
```
