# Supervisor Prompt: Memory Sync
# Format Factory — Local Supervisor Control Plane
# Usage: Fill [INSERT_...] placeholders with current sprint facts
# Purpose: Update .supervisor/project-memory.md with latest sprint facts
# IMPORTANT: Append only. Do not overwrite history. Idempotent.

---

You are Claude Code updating the supervisor project memory for Format Factory.
Format Factory authority is FINAL. Project memory is advisory only.
You MUST NOT write to AGENTS.md, GOVERNANCE.md, plans/master-plan.md, or registry/**.

## Current Sprint Facts
Sprint ID: [INSERT_SPRINT_ID]
Timestamp: [INSERT_TIMESTAMP]
Evidence verdict: [INSERT_VERDICT]
Test results: [INSERT_TEST_RESULTS]
Gate states: [INSERT_GATE_STATES]
HEAD SHA: [INSERT_GIT_HEAD]

## Prior Memory (last 3 entries)
```
[INSERT_PRIOR_MEMORY_LAST_3]
```

## Memory Update Instructions

1. **Idempotence check:**
   - Search existing .supervisor/project-memory.md for sprint_id: [INSERT_SPRINT_ID]
   - If already present with same bundle_hash: [INSERT_BUNDLE_HASH] → skip (no-op)
   - If sprint_id present but different bundle_hash → append update note

2. **Append new entry:**
   Format:
   ```
   ## Entry: [INSERT_SPRINT_ID]
   - timestamp: [INSERT_TIMESTAMP]
   - sprint_mode: [INSERT_MODE]
   - verdict: [INSERT_VERDICT]
   - test_count: [INSERT_TEST_COUNT]
   - fail_count: [INSERT_FAIL_COUNT]
   - git_head: [INSERT_GIT_HEAD]
   - gate_states_summary: [INSERT_GATE_STATES_SUMMARY]
   - supervisor_artifacts: [INSERT_ARTIFACTS_LIST]
   - next_action: [INSERT_NEXT_ACTION]
   - mcp_activation: [INSERT_MCP_STATUS]
   - daemon_status: [INSERT_DAEMON_STATUS]
   ```

3. **Stale detection:**
   - Check entries more than 3 sprints old
   - Append [STALE] tag to old entries (do not delete them)

4. **Forbidden targets:**
   NEVER write to:
   - AGENTS.md
   - GOVERNANCE.md
   - plans/master-plan.md
   - registry/format-registry.yaml
   - tools/evidence/**
   - tests/evidence/**

5. **Output:**
   - Updated content for .supervisor/project-memory.md
   - Memory sync report for reports/supervisor/ (what was appended, what was skipped)

---

REMINDER: This memory is advisory. Claude Code session memory and Format Factory evidence are authoritative.
Do not claim this memory file as the source of truth for gate states or test results.
