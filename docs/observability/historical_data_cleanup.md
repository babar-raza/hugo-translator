# Historical Data Cleanup - Telemetry Skip Handling

**Created**: 2026-01-11
**Version**: 1.0
**Status**: Recommended for post-deployment execution

---

## Overview

Before the skip handling fix was deployed on **2026-01-11**, the telemetry system logged skipped translations (no work done) identically to successful translations (work done). This created misleading historical data in the telemetry database.

This document provides:
1. Detection patterns for identifying fake entries
2. Query templates for the local-telemetry agent
3. Cleanup options and recommendations
4. Integration guidance for database cleanup

---

## Problem Statement

### What Happened

**Before Fix (pre-2026-01-11)**:
- Translation system correctly skipped files when outputs already existed (RES-05 feature working)
- BUT telemetry logged these skips as `status="completed"` successes
- The `langs_translated` field didn't exist yet (added in fix)

**Example**:
```
User runs: translate-hugo --target-langs ar
Result: 92 files skipped (Arabic outputs already exist)
Telemetry logged: 92 "successful" translations (MISLEADING)
```

### Impact

- **Historical dashboards** show inflated success metrics
- **Monitoring trends** may be misleading (fake productivity spikes)
- **Cannot distinguish** real work from no-ops in historical data
- **Cost analysis** may be inaccurate (skips logged as billable work)

---

## Detection Criteria

Fake skip entries can be identified by **ALL** of the following criteria:

| Criterion | Description | SQL Condition |
|-----------|-------------|---------------|
| **1. Event Status** | Marked as success | `status IN ('completed', 'success')` |
| **2. Job Type** | Translation job | `job_type IN ('translate_file', 'translate_directory')` |
| **3. Missing Field** | No langs_translated field | `JSON_EXTRACT(metrics_json, '$.langs_translated') IS NULL` |
| **4. Zero Translations** | OR langs_translated = 0 | `JSON_EXTRACT(metrics_json, '$.langs_translated') = 0` |
| **5. Pre-Fix Timestamp** | Before fix deployed | `timestamp < '2026-01-11T00:00:00'` |

**Detection Logic**: Criteria 1 AND 2 AND (3 OR 4) AND 5

---

## Query Templates

### SQL Query (SQLite)

```sql
-- Identify fake skip entries in telemetry database
SELECT
    event_id,
    timestamp,
    job_type,
    status,
    output_summary,
    JSON_EXTRACT(metrics_json, '$.langs_translated') AS langs_translated,
    JSON_EXTRACT(metrics_json, '$.langs_skipped') AS langs_skipped
FROM telemetry_events
WHERE job_type IN ('translate_file', 'translate_directory')
  AND status IN ('completed', 'success')
  AND (
      JSON_EXTRACT(metrics_json, '$.langs_translated') IS NULL
      OR JSON_EXTRACT(metrics_json, '$.langs_translated') = 0
  )
  AND timestamp < '2026-01-11T00:00:00'
ORDER BY timestamp DESC;
```

### PostgreSQL Query

```sql
-- For PostgreSQL databases
SELECT
    event_id,
    timestamp,
    job_type,
    status,
    output_summary,
    metrics_json->>'langs_translated' AS langs_translated,
    metrics_json->>'langs_skipped' AS langs_skipped
FROM telemetry_events
WHERE job_type IN ('translate_file', 'translate_directory')
  AND status IN ('completed', 'success')
  AND (
      metrics_json->>'langs_translated' IS NULL
      OR (metrics_json->>'langs_translated')::int = 0
  )
  AND timestamp < '2026-01-11T00:00:00'
ORDER BY timestamp DESC;
```

### Count Query

```sql
-- Get count of affected events
SELECT COUNT(*) as fake_entry_count
FROM telemetry_events
WHERE job_type IN ('translate_file', 'translate_directory')
  AND status IN ('completed', 'success')
  AND (
      JSON_EXTRACT(metrics_json, '$.langs_translated') IS NULL
      OR JSON_EXTRACT(metrics_json, '$.langs_translated') = 0
  )
  AND timestamp < '2026-01-11T00:00:00';
```

---

## Cleanup Script Usage

### Installation

```bash
# Navigate to project root
cd /path/to/hugo-translator

# Ensure script is executable (Unix/Linux/macOS)
chmod +x scripts/telemetry_cleanup/identify_fake_skip_entries.py
```

### Basic Usage

#### Dry Run (Identify Fake Entries)

```bash
# Auto-detect database and identify fake entries
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --dry-run

# Output:
# ✅ Connected to database: /home/user/.local-telemetry/telemetry.db
# 🔍 Detecting fake skip entries (cutoff: 2026-01-11T00:00:00)...
#
# ================================================================================
# FAKE SKIP ENTRY DETECTION SUMMARY
# ================================================================================
# Database: /home/user/.local-telemetry/telemetry.db
# Cutoff Date: 2026-01-11T00:00:00
# Total Fake Entries Detected: 127
# ================================================================================
```

#### Export Event IDs

```bash
# Export fake entry event IDs to JSON file
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --export fake_entries.json

# Validate output format
python -m json.tool fake_entries.json | head -30
```

#### Count Only

```bash
# Quick count without details
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --dry-run --count

# Output:
# ✅ Total fake entries detected: 127
```

### Advanced Options

#### Custom Database Path

```bash
# Specify custom database location
python scripts/telemetry_cleanup/identify_fake_skip_entries.py \
    --db-path /custom/path/telemetry.db \
    --dry-run
```

#### Custom Cutoff Date

```bash
# Use different cutoff date (e.g., if fix deployed later)
python scripts/telemetry_cleanup/identify_fake_skip_entries.py \
    --cutoff-date 2026-01-15T00:00:00 \
    --dry-run
```

---

## Cleanup Options

### Option 1: Export Event List for Local-Telemetry Agent ✅ **RECOMMENDED**

**Approach**: Export event ID list, provide to local-telemetry agent for cleanup

**Pros**:
- ✅ Safe (no direct database modification by this tool)
- ✅ Maintains audit trail
- ✅ Local-telemetry agent owns database integrity
- ✅ Can implement rollback mechanism

**Cons**:
- ⚠️ Requires coordination with local-telemetry team

**Process**:
1. Run export: `python identify_fake_skip_entries.py --export fake_entries.json`
2. Share `fake_entries.json` with local-telemetry agent
3. Local-telemetry agent reviews and processes list
4. Local-telemetry agent updates database (Option 2 or 3)

**Export Format**:
```json
{
  "metadata": {
    "detection_date": "2026-01-11T14:30:00Z",
    "criteria": "langs_translated is NULL or 0",
    "count": 127,
    "cutoff_date": "2026-01-11T00:00:00",
    "time_range": "inception to 2026-01-11T00:00:00",
    "database_path": "/home/user/.local-telemetry/telemetry.db"
  },
  "events": [
    {
      "event_id": "abc123",
      "timestamp": "2025-12-15T10:30:00Z",
      "job_type": "translate_file",
      "status": "completed",
      "output_summary": "92 translations, 0 errors",
      "reason": "langs_translated field missing (pre-fix version)"
    },
    ...
  ]
}
```

### Option 2: Update Event Status

**Approach**: Change event status to `completed_no_changes_retroactive`

**SQL Update** (for local-telemetry agent):
```sql
-- Update event status for fake entries
UPDATE telemetry_events
SET status = 'completed_no_changes_retroactive',
    updated_at = CURRENT_TIMESTAMP
WHERE event_id IN (
    -- Event IDs from exported list
    'abc123', 'def456', 'ghi789', ...
);
```

**Pros**:
- ✅ Clear differentiation in dashboards (new status value)
- ✅ Preserves original data structure
- ✅ Easily reversible

**Cons**:
- ⚠️ Modifies event status (breaking change for some queries)

### Option 3: Add Data Quality Flag

**Approach**: Add metadata flag to events indicating pre-fix data

**SQL Update** (for local-telemetry agent):
```sql
-- Add data quality flag to metrics_json
UPDATE telemetry_events
SET metrics_json = JSON_SET(
        metrics_json,
        '$.data_quality', 'pre_skip_fix',
        '$.caution', 'may_include_skips',
        '$.is_misleading', true
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE event_id IN (
    -- Event IDs from exported list
    'abc123', 'def456', 'ghi789', ...
);
```

**Pros**:
- ✅ Non-breaking (doesn't change status field)
- ✅ Flexible filtering in queries
- ✅ Preserves original event structure

**Cons**:
- ⚠️ Requires query updates to filter out flagged events

### Option 4: Do Nothing (Document Only)

**Approach**: Document the issue but leave data as-is

**Pros**:
- ✅ Zero risk (no database changes)
- ✅ Fastest option

**Cons**:
- ❌ Historical data remains misleading
- ❌ Requires manual filtering in all queries

---

## Integration with Local-Telemetry Agent

### Step 1: Detection (Hugo-Translator Side)

```bash
# Run detection script
cd /path/to/hugo-translator
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --export fake_entries.json

# Validate output
python -m json.tool fake_entries.json | head -50
```

### Step 2: Review (Manual)

1. Open `fake_entries.json`
2. Review `metadata.count` to understand scope
3. Spot-check sample events in `events` array
4. Verify detection criteria matches expectations

### Step 3: Handoff (to Local-Telemetry Agent)

Provide to local-telemetry agent:
- ✅ `fake_entries.json` file
- ✅ This documentation file (`historical_data_cleanup.md`)
- ✅ Detection criteria explanation
- ✅ Recommended cleanup option (Option 1 or 3)

### Step 4: Cleanup (Local-Telemetry Side)

**Local-Telemetry Agent Actions**:
1. Import event ID list from `fake_entries.json`
2. Validate event IDs exist in database
3. Choose cleanup option (recommend Option 3: add data quality flag)
4. Execute SQL update with transaction
5. Create audit log entry
6. Verify cleanup with validation queries

**Validation Queries** (after cleanup):
```sql
-- Verify data quality flags were added
SELECT COUNT(*) as flagged_count
FROM telemetry_events
WHERE JSON_EXTRACT(metrics_json, '$.data_quality') = 'pre_skip_fix';

-- Compare to expected count
-- (should match metadata.count from fake_entries.json)
```

### Step 5: Rollback (if needed)

**Rollback SQL** (for Option 3):
```sql
-- Remove data quality flags
UPDATE telemetry_events
SET metrics_json = JSON_REMOVE(
        metrics_json,
        '$.data_quality',
        '$.caution',
        '$.is_misleading'
    ),
    updated_at = CURRENT_TIMESTAMP
WHERE JSON_EXTRACT(metrics_json, '$.data_quality') = 'pre_skip_fix';
```

---

## Execution Timeline

### Recommended: Wave 4 (Post-Deployment) ✅

**Rationale**:
1. Deploy core skip handling fix first (Tasks 1.1-3.1)
2. Validate in production (ensure langs_translated field works)
3. THEN run historical cleanup (Wave 4)
4. Lower risk, validated implementation

**Timeline**:
- **Day 1**: Deploy skip handling fix to production
- **Day 2-7**: Monitor production telemetry (verify new fields work)
- **Week 2**: Run historical cleanup (low priority, non-blocking)

### Alternative: Wave 2.5 (Parallel with Testing)

**Rationale**:
- Run cleanup while testing and documentation are in progress
- Requires available agent/resource

**Timeline**:
- **Wave 1**: Implementation (Agent B) ✅ COMPLETE
- **Wave 2.5**: Historical Cleanup (Agent F) - parallel with:
  - **Wave 2**: Testing (Agent C)
  - **Wave 2**: Documentation (Agent D)
- **Wave 3**: Review (Agent E)

### Alternative: Handoff to Local-Telemetry Team

**Rationale**:
- Lower maintenance burden for hugo-translator team
- Local-telemetry team owns database cleanup

**Process**:
1. Provide detection script and documentation
2. Local-telemetry team runs cleanup on their schedule
3. Hugo-translator team provides support as needed

---

## Risk Mitigation

### Safety Measures

1. **Dry-Run Mode (Default)**:
   - Script defaults to read-only mode
   - No database modifications without explicit `--export`
   - Prevents accidental changes

2. **Export-Only Pattern**:
   - Script only exports event IDs (no database writes)
   - Actual cleanup handled by local-telemetry agent
   - Clear separation of concerns

3. **Audit Trail**:
   - All exported lists include metadata (detection date, criteria, count)
   - Local-telemetry agent logs all cleanup actions
   - Rollback supported via SQL

4. **Validation Queries**:
   - Verify cleanup count matches expected count
   - Spot-check sample events
   - Compare before/after metrics

### Rollback Plan

If cleanup causes issues:
1. Identify affected event IDs from audit log
2. Execute rollback SQL (remove flags or revert status)
3. Re-deploy previous database backup (if available)
4. Investigate failure in staging environment

---

## Acceptance Criteria

- [ ] Detection script runs without errors (`--dry-run`)
- [ ] Script exports event ID list in correct JSON format
- [ ] Export includes all required metadata fields
- [ ] Detection criteria match specification (5 criteria)
- [ ] Query templates provided for SQLite and PostgreSQL
- [ ] Integration notes for local-telemetry agent documented
- [ ] Cleanup options documented with pros/cons
- [ ] Rollback mechanism documented
- [ ] Risk mitigation documented
- [ ] Validation queries provided

---

## Evidence Commands

```bash
# Test detection script (dry-run)
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --dry-run

# Export event IDs
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --export fake_entries.json

# Validate output format
python -m json.tool fake_entries.json | head -30

# Count affected events
python scripts/telemetry_cleanup/identify_fake_skip_entries.py --dry-run --count

# Review documentation
cat docs/observability/historical_data_cleanup.md

# Test with custom database
python scripts/telemetry_cleanup/identify_fake_skip_entries.py \
    --db-path /tmp/test_telemetry.db \
    --dry-run
```

---

## FAQ

### Q1: Is this cleanup mandatory for deployment?

**A**: No, this is **NOT BLOCKING** deployment. The core fix (Tasks 1.1-3.1) prevents future fake entries. Historical cleanup improves data quality but can be done anytime.

### Q2: What if I don't have access to the telemetry database?

**A**: Provide the detection script and documentation to the local-telemetry team. They can run cleanup on their schedule.

### Q3: Will this script modify my database?

**A**: No, the script is **read-only**. It only exports event IDs to a JSON file. Actual database cleanup is handled by the local-telemetry agent.

### Q4: How do I know if cleanup was successful?

**A**: Run validation queries (see "Integration with Local-Telemetry Agent" section) to verify:
- Flagged event count matches expected count
- Sample events have correct flags
- No unexpected side effects

### Q5: Can I revert the cleanup?

**A**: Yes, rollback SQL is provided for each cleanup option (see "Integration with Local-Telemetry Agent > Step 5: Rollback").

---

## Support

For questions or issues:
1. Review this documentation
2. Check telemetry event schema: `docs/observability/telemetry_events.md`
3. Check operational runbook: `docs/observability/runbook.md`
4. Contact hugo-translator team or local-telemetry team

---

**Last Updated**: 2026-01-11
**Version**: 1.0
**Status**: Ready for execution (Wave 4 recommended)
