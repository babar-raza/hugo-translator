# Observability Runbook: Translation Telemetry

**Last Updated**: 2026-01-11
**Version**: 1.0
**Target Audience**: DevOps Engineers, SREs, System Operators

## Overview

This runbook provides operational guidance for monitoring and troubleshooting the hugo-translator system using telemetry events. It focuses on understanding skip metrics, identifying anomalies, and resolving common issues.

### When to Use This Runbook

- Monitoring translation job health
- Investigating performance degradation
- Diagnosing duplicate work or inefficiency
- Understanding skip patterns
- Troubleshooting telemetry data issues

### Prerequisites

- Access to telemetry database or API
- Basic SQL knowledge
- Understanding of translation workflow
- Familiarity with [Telemetry Event Schema](./telemetry-events.md)

## Quick Reference

| Metric | Normal Range | Investigation Threshold |
|--------|--------------|-------------------------|
| Skip rate (first run) | 0-10% | >25% |
| Skip rate (re-run) | 80-100% | <50% |
| All-skipped runs (in telemetry) | **NONE** (no entry created) | N/A (check logs instead) |
| `langs_translated` per job | 1-N target languages | N/A (0 = no entry) |
| Token usage when skipped | 0 | >0 (unexpected) |

## Interpreting Skip Metrics

### Core Concepts

#### Actual Work vs Skipped Work

The telemetry system differentiates between:

1. **Actual Work (`langs_translated`)**:
   - Translation was performed
   - Model was invoked
   - Output file was written
   - Tokens were consumed
   - Cost was incurred

2. **Skipped Work (`langs_skipped`)**:
   - Output already exists
   - No translation needed
   - Model was NOT invoked
   - No tokens consumed
   - No cost incurred

**Critical Understanding**:
- `langs_skipped > 0` is GOOD when re-running jobs (indicates efficiency)
- `langs_skipped > 0` is BAD on first run (indicates configuration issue)

#### CRITICAL: Telemetry Entry Creation Rules

**Fundamental Principle**: **If no work was done, no telemetry entry is created.**

##### When Telemetry Entries ARE Created

**Status**: `completed` (the ONLY status for translation events)

- **Condition**: `langs_translated ≥ 1` (at least one language was translated)
- **Indicates**: Job performed actual work
- **Expected when**:
  - First run of translation job
  - Re-run with `--force-retranslate` flag
  - Some (but not all) outputs existed (mixed scenario)
- **Metrics to verify**:
  - `langs_translated ≥ 1`
  - `langs_skipped ≥ 0` (can be mixed)
  - `items_succeeded > 0`
  - `tokens_input > 0` (if model-based)
  - `duration_ms` proportional to work

**Interpretation**:
```
If telemetry event exists → Real work was done (langs_translated > 0)
If langs_skipped > 0 in event → Mixed scenario (some reused, some translated)
If langs_skipped = 0 in event → All languages were fresh translations
```

##### When Telemetry Entries ARE NOT Created

**Condition**: `langs_skipped = total_target_languages AND langs_translated = 0`

- **Behavior**: System exits telemetry context without creating any event
- **Log Message**: `"Skipping telemetry entry: all languages skipped (no work done)"`
- **Expected when**:
  - Re-running same job without changes
  - Job executed on directory with all outputs existing
  - Resuming interrupted job that actually finished
- **How to detect**: **Query application logs**, not telemetry database

**Interpretation**:
```
No telemetry entry for a job run → All languages were skipped (no work done)
completed_no_changes on first run → PROBLEM (investigate)
```

### Skip Patterns

#### Normal Skip Patterns

##### Pattern 1: Re-run After Completion
```json
{
  "run_1": {
    "timestamp": "2026-01-11T10:00:00Z",
    "langs_translated": 3,
    "langs_skipped": 0,
    "status": "completed"
  },
  "run_2": {
    "timestamp": "2026-01-11T10:05:00Z",
    "langs_translated": 0,
    "langs_skipped": 3,
    "event": "completed_no_changes"
  }
}
```
**Analysis**: ✅ Normal - Second run correctly skips already-translated languages

##### Pattern 2: Partial Re-run
```json
{
  "run_1": {
    "timestamp": "2026-01-11T10:00:00Z",
    "langs_translated": 2,
    "langs_skipped": 0,
    "status": "failed",
    "error": "Network timeout on 'de'"
  },
  "run_2": {
    "timestamp": "2026-01-11T10:02:00Z",
    "langs_translated": 1,
    "langs_skipped": 2,
    "status": "completed"
  }
}
```
**Analysis**: ✅ Normal - Retry skips completed languages, completes failed one

##### Pattern 3: Incremental Language Addition
```json
{
  "run_1": {
    "timestamp": "2026-01-11T10:00:00Z",
    "langs_translated": 2,
    "langs_skipped": 0,
    "target_langs": ["es", "fr"]
  },
  "run_2": {
    "timestamp": "2026-01-11T11:00:00Z",
    "langs_translated": 1,
    "langs_skipped": 2,
    "target_langs": ["es", "fr", "de"]
  }
}
```
**Analysis**: ✅ Normal - Adding new language skips existing translations

#### Abnormal Skip Patterns

##### Pattern A: High Skip Rate on First Run
```json
{
  "run_1": {
    "timestamp": "2026-01-11T10:00:00Z",
    "langs_translated": 0,
    "langs_skipped": 3,
    "event": "completed_no_changes"
  }
}
```
**Analysis**: ⚠️ ABNORMAL - First run should not skip all languages

**Possible Causes**:
1. Job running on wrong directory (outputs from previous job)
2. Output directory not cleaned before run
3. Job configuration pointing to existing outputs
4. Duplicate job execution

**Investigation Steps**:
1. Check if output directory contains files from previous run
2. Verify job configuration (input/output paths)
3. Check job execution history for duplicates
4. Review skip reasons in event payload

##### Pattern B: Zero Skips on Re-run
```json
{
  "run_1": {
    "timestamp": "2026-01-11T10:00:00Z",
    "langs_translated": 3,
    "langs_skipped": 0
  },
  "run_2": {
    "timestamp": "2026-01-11T10:05:00Z",
    "langs_translated": 3,
    "langs_skipped": 0
  }
}
```
**Analysis**: ⚠️ ABNORMAL - Re-run should skip existing outputs

**Possible Causes**:
1. Output files deleted between runs
2. `--force-retranslate` flag used (intentional)
3. Output detection logic broken
4. File permissions preventing read

**Investigation Steps**:
1. Check if `--force-retranslate` flag was used (expected behavior)
2. Verify output files exist on filesystem
3. Check file modification times
4. Review application logs for output detection errors

##### Pattern C: Inconsistent Skip Behavior
```json
{
  "run_1": {"langs_skipped": 2, "skipped_langs": ["es", "fr"]},
  "run_2": {"langs_skipped": 1, "skipped_langs": ["es"]},
  "run_3": {"langs_skipped": 3, "skipped_langs": ["es", "fr", "de"]}
}
```
**Analysis**: ⚠️ ABNORMAL - Skip behavior should be deterministic

**Possible Causes**:
1. Output files being created/deleted externally
2. Race condition in multi-job scenario
3. Filesystem synchronization issues (NFS, cloud storage)
4. Cache inconsistency

**Investigation Steps**:
1. Check for concurrent jobs on same files
2. Review filesystem events/audit logs
3. Verify file locking mechanism
4. Check distributed filesystem consistency

### Skip Rate Calculations

#### Job-Level Skip Rate
```
skip_rate = langs_skipped / (langs_skipped + langs_translated)
```

**Interpretation**:
- `skip_rate = 0.0` (0%): All new work (expected on first run)
- `skip_rate = 1.0` (100%): All skipped (expected on re-run)
- `skip_rate = 0.5` (50%): Half skipped (expected on partial retry)

#### Site-Level Skip Rate
```
site_skip_rate = SUM(langs_skipped) / SUM(langs_skipped + langs_translated)
```

**Normal Ranges by Scenario**:
- Fresh translation: 0-10% (mostly new work)
- Re-run after failure: 50-90% (partial work)
- Duplicate execution: 90-100% (mostly skips)

## Monitoring Query Examples

### Query 1: Find All No-Change Runs

**Purpose**: Identify jobs that skipped all languages (no work done)

**SQL**:
```sql
SELECT
  run_id,
  timestamp,
  input_summary,
  output_summary,
  duration_ms,
  JSON_EXTRACT(metrics_json, '$.langs_skipped') as langs_skipped,
  JSON_EXTRACT(metrics_json, '$.langs_translated') as langs_translated
FROM telemetry_events
WHERE JSON_EXTRACT(metrics_json, '$.langs_translated') = 0
  AND JSON_EXTRACT(metrics_json, '$.langs_skipped') > 0
ORDER BY timestamp DESC
LIMIT 100;
```

**Expected Results**:
- Jobs with `langs_translated = 0` and `langs_skipped > 0`
- `duration_ms` should be very low (<100ms typical)
- `output_summary` should mention "skipped"

**Action Items**:
- Review `input_summary` for duplicate job patterns
- Check timestamp intervals for accidental re-runs
- Investigate if frequency is abnormally high

### Query 2: Calculate Skip Rate by Job

**Purpose**: Measure efficiency of skip detection per job

**SQL**:
```sql
SELECT
  run_id,
  timestamp,
  input_summary,
  JSON_EXTRACT(metrics_json, '$.langs_skipped') as langs_skipped,
  JSON_EXTRACT(metrics_json, '$.langs_translated') as langs_translated,
  CAST(JSON_EXTRACT(metrics_json, '$.langs_skipped') AS FLOAT) /
    (JSON_EXTRACT(metrics_json, '$.langs_skipped') +
     JSON_EXTRACT(metrics_json, '$.langs_translated')) * 100 as skip_rate_pct
FROM telemetry_events
WHERE job_type = 'translate_file'
  AND (JSON_EXTRACT(metrics_json, '$.langs_skipped') +
       JSON_EXTRACT(metrics_json, '$.langs_translated')) > 0
ORDER BY timestamp DESC
LIMIT 100;
```

**Expected Results**:
- `skip_rate_pct` between 0% (first run) and 100% (re-run)
- Most jobs should be either near 0% or near 100%
- Values around 50% indicate partial retries

**Action Items**:
- Investigate jobs with unexpected skip rates
- Correlate with job execution patterns
- Identify inefficient retry strategies

### Query 3: Identify Jobs with High Skip Ratio

**Purpose**: Find jobs that are doing mostly redundant work

**SQL**:
```sql
SELECT
  run_id,
  timestamp,
  input_summary,
  output_summary,
  JSON_EXTRACT(metrics_json, '$.langs_skipped') as langs_skipped,
  JSON_EXTRACT(metrics_json, '$.langs_translated') as langs_translated,
  CAST(JSON_EXTRACT(metrics_json, '$.langs_skipped') AS FLOAT) /
    (JSON_EXTRACT(metrics_json, '$.langs_skipped') +
     JSON_EXTRACT(metrics_json, '$.langs_translated')) * 100 as skip_rate_pct
FROM telemetry_events
WHERE job_type = 'translate_file'
  AND status = 'completed'
  AND JSON_EXTRACT(metrics_json, '$.langs_translated') > 0
  AND CAST(JSON_EXTRACT(metrics_json, '$.langs_skipped') AS FLOAT) /
      (JSON_EXTRACT(metrics_json, '$.langs_skipped') +
       JSON_EXTRACT(metrics_json, '$.langs_translated')) > 0.5
ORDER BY skip_rate_pct DESC, timestamp DESC
LIMIT 50;
```

**Expected Results**:
- Jobs with >50% skip rate but still did some work
- Indicates partial completion scenarios

**Action Items**:
- Review why these jobs had mixed skip/translate behavior
- Check if these are legitimate partial retries
- Identify if job scheduling can be optimized

### Query 4: Track Skip Trends Over Time

**Purpose**: Monitor skip behavior trends to detect configuration drift

**SQL**:
```sql
SELECT
  DATE(timestamp) as date,
  COUNT(*) as total_jobs,
  SUM(CASE WHEN JSON_EXTRACT(metrics_json, '$.langs_translated') = 0 THEN 1 ELSE 0 END) as no_change_jobs,
  SUM(JSON_EXTRACT(metrics_json, '$.langs_skipped')) as total_skips,
  SUM(JSON_EXTRACT(metrics_json, '$.langs_translated')) as total_translations,
  CAST(SUM(JSON_EXTRACT(metrics_json, '$.langs_skipped')) AS FLOAT) /
    NULLIF(SUM(JSON_EXTRACT(metrics_json, '$.langs_skipped')) +
           SUM(JSON_EXTRACT(metrics_json, '$.langs_translated')), 0) * 100 as daily_skip_rate_pct
FROM telemetry_events
WHERE job_type = 'translate_file'
  AND timestamp >= DATE('now', '-30 days')
GROUP BY DATE(timestamp)
ORDER BY date DESC;
```

**Expected Results**:
- Daily aggregates of skip vs translate activity
- `daily_skip_rate_pct` should be relatively stable
- Sudden changes indicate configuration or behavior shifts

**Action Items**:
- Investigate days with unusual skip rate changes
- Correlate with deployment events or config changes
- Monitor for gradual drift in skip behavior

### Query 5: Find Duplicate Job Executions

**Purpose**: Identify likely duplicate job runs (same input, similar timestamp)

**SQL**:
```sql
WITH job_groups AS (
  SELECT
    input_summary,
    DATE(timestamp) as date,
    COUNT(*) as execution_count,
    MIN(timestamp) as first_run,
    MAX(timestamp) as last_run,
    SUM(JSON_EXTRACT(metrics_json, '$.langs_translated')) as total_translated,
    SUM(JSON_EXTRACT(metrics_json, '$.langs_skipped')) as total_skipped
  FROM telemetry_events
  WHERE job_type = 'translate_file'
    AND timestamp >= DATE('now', '-7 days')
  GROUP BY input_summary, DATE(timestamp)
  HAVING COUNT(*) > 1
)
SELECT *
FROM job_groups
WHERE total_skipped > total_translated
ORDER BY execution_count DESC, date DESC
LIMIT 20;
```

**Expected Results**:
- Jobs that ran multiple times on same day
- Later runs should show higher skip counts
- Identifies potential duplicate/redundant executions

**Action Items**:
- Review job scheduling for duplicate triggers
- Check if automated retries are too aggressive
- Investigate if jobs are being manually re-run unnecessarily

## Operational Guidance

### When to Investigate High Skip Rates

#### Scenario 1: High Skip Rate on First Run
**Threshold**: >25% skip rate on first execution

**Indicators**:
- `completed_no_changes` event on first run
- No previous run in history for same input
- `langs_skipped > 0` without prior translation

**Investigation**:
1. ✅ Check output directory for pre-existing files
2. ✅ Review job configuration (input/output paths)
3. ✅ Verify no concurrent/previous jobs on same files
4. ✅ Check if job is using wrong source directory

**Resolution**:
- Clean output directory before first run
- Fix job configuration paths
- Implement job locking to prevent overlap

#### Scenario 2: Low Skip Rate on Re-run
**Threshold**: <50% skip rate on known re-run

**Indicators**:
- Previous completed run exists
- Output files should exist
- `langs_skipped` lower than expected

**Investigation**:
1. ✅ Check if `--force-retranslate` flag was used (intended behavior)
2. ✅ Verify output files exist on filesystem
3. ✅ Check file permissions (read access)
4. ✅ Review logs for output detection failures

**Resolution**:
- If flag used: Document as expected behavior
- If files missing: Investigate file cleanup process
- If permissions issue: Fix file access
- If detection broken: File bug with implementation team

### How to Differentiate Legitimate Skips from Issues

#### Legitimate Skip Scenarios

1. **Re-run After Completion**
   - ✅ Previous successful run exists
   - ✅ Time gap between runs < TTL of outputs
   - ✅ No `--force-retranslate` flag
   - ✅ `completed_no_changes` event logged

2. **Partial Retry After Failure**
   - ✅ Previous failed run exists
   - ✅ Some languages completed in previous run
   - ✅ Only failed languages are translated
   - ✅ Skip count matches successful languages from previous run

3. **Incremental Language Addition**
   - ✅ Previous run with fewer target languages
   - ✅ New run adds additional languages
   - ✅ Existing languages are skipped
   - ✅ Only new languages are translated

#### Issue Indicators

1. **Unexpected All-Skip**
   - ⚠️ First run shows all languages skipped
   - ⚠️ No previous run in history
   - ⚠️ `completed_no_changes` without explanation
   - **Action**: Check for configuration error

2. **No Skips on Re-run**
   - ⚠️ Re-run translates everything again
   - ⚠️ Previous outputs should exist
   - ⚠️ No `--force-retranslate` flag documented
   - **Action**: Check output detection logic

3. **Inconsistent Skip Behavior**
   - ⚠️ Same job shows different skip counts across runs
   - ⚠️ No changes to source or configuration
   - ⚠️ Non-deterministic skip pattern
   - **Action**: Check for race conditions or filesystem issues

### Cost and Performance Implications

#### Cost Analysis

**Skipped work** (cost = $0):
- No model invocation
- No token consumption
- Minimal CPU/memory usage
- Fast completion (<100ms)

**Translated work** (cost = variable):
- Model API calls (if cloud-based)
- Token consumption (charged)
- Significant CPU/memory (if local)
- Slower completion (seconds to minutes)

**Cost Calculation**:
```
cost_per_job = (langs_translated * avg_tokens_per_lang * cost_per_token)
cost_saved = (langs_skipped * avg_tokens_per_lang * cost_per_token)
```

**Example**:
```
Job: 3 languages, 2 skipped, 1 translated
Avg: 5000 tokens/lang
Rate: $0.01/1000 tokens

Cost = (1 * 5000 * 0.00001) = $0.05
Savings = (2 * 5000 * 0.00001) = $0.10
Efficiency = 66% cost avoidance
```

#### Performance Optimization

**Leverage skip detection**:
1. Enable resume features (skip completed work)
2. Avoid `--force-retranslate` unless necessary
3. Use incremental translation for updates
4. Monitor skip rates to validate efficiency

**Red flags**:
- Low skip rate on re-runs (not leveraging caching)
- High `completed_no_changes` frequency (redundant executions)
- Token usage when skip rate is high (detection not working)

## Troubleshooting

### Issue 1: Skips Not Appearing in Telemetry

**Symptoms**:
- `langs_skipped` always 0
- All jobs show `langs_translated = total_langs`
- Output files exist but skips not detected

**Possible Causes**:
1. Telemetry version mismatch (pre-v2.0)
2. Implementation bug in skip detection
3. Skip logic bypassed by flags

**Diagnostic Steps**:
```bash
# Check telemetry version
grep "langs_skipped" docs/observability/telemetry_events.md

# Check implementation version
grep -n "langs_skipped" src/translation_engine/models.py

# Review recent events for new fields
sqlite3 telemetry.db "SELECT metrics_json FROM telemetry_events ORDER BY timestamp DESC LIMIT 1;"
```

**Resolution**:
1. Verify telemetry system is v2.0+
2. Check if skip detection logic is enabled
3. Review application logs for skip detection errors
4. File bug if implementation is incorrect

### Issue 2: Status Always "completed" (Never "completed_no_changes")

**Symptoms**:
- Jobs with all languages skipped show `status = "completed"`
- No `completed_no_changes` events in logs
- Expected status differentiation missing

**Possible Causes**:
1. Status is not an event type, it's a run-level field
2. Looking for wrong field in telemetry data
3. Event logging not implemented

**Diagnostic Steps**:
```bash
# Check for completed_no_changes events (not status)
sqlite3 telemetry.db "SELECT * FROM telemetry_events WHERE JSON_EXTRACT(metrics_json, '$.langs_translated') = 0 LIMIT 10;"

# Check events array for event_type
# Note: completed_no_changes is an EVENT, not a STATUS
```

**Resolution**:
1. `completed_no_changes` is an **event type**, not a status
2. Status field remains `"completed"` for successful runs
3. Look for `completed_no_changes` in events array or as separate event record
4. See [Telemetry Event Schema](./telemetry-events.md#event-status-values) for clarification

### Issue 3: High Skip Rate But Token Usage Shows Charges

**Symptoms**:
- `langs_skipped` high
- `tokens_input > 0` or `tokens_output > 0`
- Unexpected token charges

**Possible Causes**:
1. Token metrics include segment-level cache hits
2. Validation or other processing invoked model
3. Metrics aggregation error

**Diagnostic Steps**:
```sql
-- Check correlation between skips and tokens
SELECT
  run_id,
  JSON_EXTRACT(metrics_json, '$.langs_skipped') as langs_skipped,
  JSON_EXTRACT(metrics_json, '$.langs_translated') as langs_translated,
  JSON_EXTRACT(metrics_json, '$.tokens_input') as tokens_input,
  JSON_EXTRACT(metrics_json, '$.tokens_output') as tokens_output
FROM telemetry_events
WHERE JSON_EXTRACT(metrics_json, '$.langs_skipped') > 0
  AND (JSON_EXTRACT(metrics_json, '$.tokens_input') > 0
       OR JSON_EXTRACT(metrics_json, '$.tokens_output') > 0)
ORDER BY timestamp DESC
LIMIT 20;
```

**Resolution**:
1. If `langs_translated > 0`: Tokens are for translated languages only (expected)
2. If `langs_translated = 0`: Investigate why model was invoked (bug)
3. Check if validation or other features use model separately
4. Review token tracking implementation

### Issue 4: Inconsistent Skip Counts Across Runs

**Symptoms**:
- Same input shows different `langs_skipped` values
- Non-deterministic skip behavior
- Skip counts don't match expectations

**Possible Causes**:
1. Outputs being modified/deleted externally
2. Race condition with concurrent jobs
3. Distributed filesystem sync delays
4. Timestamp-based detection with clock skew

**Diagnostic Steps**:
```bash
# Check for concurrent jobs on same input
sqlite3 telemetry.db "
SELECT run_id, timestamp, input_summary,
       JSON_EXTRACT(metrics_json, '$.langs_skipped') as langs_skipped
FROM telemetry_events
WHERE input_summary = 'file=content/example.md; langs=es,fr,de'
ORDER BY timestamp;
"

# Check filesystem for output file timestamps
ls -l output/es/example.md output/fr/example.md output/de/example.md
```

**Resolution**:
1. Implement job locking to prevent concurrent runs
2. Use distributed locks for shared filesystem scenarios
3. Verify filesystem consistency (fsck, cloud storage sync)
4. Consider using content hashes instead of timestamps

## Related Documentation

- **Schema Reference**: [Telemetry Event Schema](./telemetry-events.md)
- **Metrics Guide**: [Content Hash Metrics](./content-hash-metrics.md)
- **Source Code**:
  - `src/translation_engine/models.py` - TranslationStats model
  - `src/observability/telemetry_integration.py` - Metrics calculation
  - `src/translation_engine/engine.py` - Event logging

## Appendix: Metrics Dashboard Suggestions

### Recommended Grafana Panels

1. **Skip Rate Over Time** (Line Chart)
   - X: timestamp
   - Y: `langs_skipped / (langs_skipped + langs_translated)`
   - Alert: >25% on first-run jobs

2. **Work Distribution** (Pie Chart)
   - Slices: `langs_translated`, `langs_skipped`
   - Shows actual work vs avoided work

3. **No-Change Job Frequency** (Bar Chart)
   - X: date
   - Y: Count of jobs with `langs_translated = 0`
   - Alert: Unusual spikes

4. **Cost Savings from Skips** (Stat Panel)
   - Calculation: `langs_skipped * avg_tokens * cost_per_token`
   - Shows cumulative savings

### Alerting Rules

**Alert 1: High Skip Rate on First Run**
```yaml
condition: skip_rate > 0.25 AND previous_runs = 0
severity: warning
message: "Job skipping languages on first run - possible config issue"
```

**Alert 2: Low Skip Rate on Re-run**
```yaml
condition: skip_rate < 0.5 AND previous_runs > 0
severity: info
message: "Re-run not leveraging skips - check output detection"
```

**Alert 3: Frequent No-Change Jobs**
```yaml
condition: completed_no_changes_count > 10 per hour
severity: warning
message: "High frequency of no-change jobs - possible duplicate execution"
```

---

**Document Version**: 1.0
**Maintained By**: Observability Team
**Last Review**: 2026-01-11
**Next Review**: 2026-04-11
