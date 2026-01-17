# Telemetry Event Schema Documentation

**Last Updated**: 2026-01-11
**Schema Version**: 2.0 (Skip Handling)
**Status**: Active

## Overview

This document describes the telemetry event schema for the hugo-translator system, with a focus on skip handling metrics introduced in version 2.0. The telemetry system tracks translation operations, differentiating between actual work performed and skipped operations where outputs already exist.

## Purpose

The telemetry system provides observability for:
- **Translation work**: Actual translation operations performed
- **Skip patterns**: Languages/segments skipped due to existing outputs
- **Performance metrics**: Duration, throughput, cache efficiency
- **Error tracking**: Failures and their causes

Understanding the difference between "work done" and "work skipped" is critical for:
- Accurate capacity planning
- Cost attribution
- Performance optimization
- Problem diagnosis

## Schema Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0 | 2025-12-01 | Initial schema with basic translation metrics |
| 2.0 | 2026-01-11 | Added skip handling fields and `completed_no_changes` status |

## New Fields (Version 2.0)

### TranslationStats Fields

The `TranslationStats` model now includes language-level tracking to differentiate actual work from skipped operations:

#### `langs_skipped` (integer)
- **Definition**: Number of target languages skipped due to existing outputs
- **Range**: 0 to N (where N = number of target languages)
- **When incremented**: When output file already exists and no retranslation needed
- **Use case**: Identify duplicate work attempts, measure caching effectiveness

**Example**:
```python
# Translation requested for ["es", "fr", "de"]
# "es" and "fr" outputs already exist, "de" needs translation
result.stats.langs_skipped = 2  # es, fr
result.stats.langs_translated = 1  # de
```

#### `langs_translated` (integer)
- **Definition**: Number of target languages actually translated (work performed)
- **Range**: 0 to N (where N = number of target languages)
- **When incremented**: When translation is performed and output written
- **Use case**: Measure actual work completed, calculate true throughput

**Relationship**:
```
langs_skipped + langs_translated = total_target_languages
```

**Note**: These fields are available in telemetry events under the `metrics_json` payload.

## Event Status Values

The telemetry system uses event status values to categorize translation run outcomes:

### `completed` (Status)
- **Definition**: Translation run completed with at least one language translated
- **When used**: `langs_translated > 0`
- **Indicates**: Actual work was performed
- **Expected metrics**:
  - `items_succeeded > 0` (segments successfully translated)
  - `duration_ms > 0` (time spent translating)
  - `langs_translated ≥ 1`

**Example scenario**: Job translates 2 languages, skips 1 existing output
```json
{
  "status": "completed",
  "langs_translated": 2,
  "langs_skipped": 1,
  "items_succeeded": 156
}
```

### CRITICAL: No Telemetry Entry When All Skipped (NEW in v2.0)

**Fundamental Principle**: **If no work was done, no telemetry entry is created.**

- **Condition**: `langs_skipped = total_target_languages AND langs_translated = 0`
- **Behavior**: System exits telemetry context without creating any event
- **Log Message**: `"Skipping telemetry entry: all languages skipped (no work done)"`

**Example scenario**: Job attempts to translate 3 languages, all outputs already exist → **NO TELEMETRY EVENT**

**Rationale**:
- Telemetry tracks productive work, not no-ops
- Reduces database noise and storage costs
- Accurate cost/usage metrics (only bill for actual work)
- Simpler querying (all events represent real work)

**Operational Note**: To detect redundant job executions (all-skipped scenarios):
- **Do NOT query telemetry database** (no entries exist for all-skipped runs)
- **Query application logs** for message: `"Skipping telemetry entry: all languages skipped"`
- High frequency of skip log messages may indicate:
  - Duplicate job execution (check scheduling)
  - Configuration issue (job running on wrong directory)
  - Content hash tracking working correctly (positive indicator)

## Output Summary Format

The `output_summary` field provides a human-readable summary of translation results.

### Format Versions

#### Legacy Format (v1.0)
```
"{translations} translations, {errors} errors"
```

**Example**: `"3 translations, 0 errors"`

#### Current Format (v2.0)
```
"{translations} translations, {skipped} skipped (existing outputs), {errors} errors"
```

**Examples**:
- All translated: `"3 translations, 0 errors"`
- Mixed scenario: `"2 translations, 1 skipped (existing outputs), 0 errors"`
- All skipped: `"0 translations, 3 skipped (existing outputs), 0 errors"`
- With errors: `"2 translations, 1 skipped (existing outputs), 1 errors"`

### Format Components

| Component | Meaning | When Shown |
|-----------|---------|------------|
| `N translations` | Number of languages successfully translated | Always |
| `M skipped (existing outputs)` | Number of languages skipped due to existing outputs | When M > 0 |
| `X errors` | Number of errors encountered | Always |

**Parsing Logic**:
```python
if skip_count > 0:
    summary = f"{translation_count} translations, {skip_count} skipped (existing outputs), {error_count} errors"
else:
    summary = f"{translation_count} translations, {error_count} errors"
```

## Example Event Payloads

### Example 1: All Languages Skipped (completed_no_changes)

**Scenario**: Translate file to 3 languages, all outputs already exist

**Event**:
```json
{
  "run_id": "run_20260111_143022_abc123",
  "agent_name": "hugo-translator",
  "job_type": "translate_file",
  "trigger_type": "cli",
  "status": "completed",
  "input_summary": "file=content/slides/net/getting-started.md; langs=es,fr,de",
  "output_summary": "0 translations, 3 skipped (existing outputs), 0 errors",
  "duration_ms": 42,
  "items_discovered": 0,
  "items_succeeded": 0,
  "items_failed": 0,
  "metrics_json": {
    "langs_skipped": 3,
    "langs_translated": 0,
    "total_segments": 0,
    "translated_segments": 0,
    "tm_hits": 0,
    "skipped_segments": 0,
    "files_translated": 0,
    "files_generated": 0
  },
  "events": [
    {
      "event_type": "completed_no_changes",
      "timestamp": "2026-01-11T14:30:22.123Z",
      "payload": {
        "reason": "All target languages skipped (outputs already exist)",
        "langs_skipped": 3,
        "total_langs": 3,
        "skipped_langs": ["es", "fr", "de"]
      }
    }
  ]
}
```

**Key Indicators**:
- `langs_translated = 0` (no work done)
- `langs_skipped = 3` (all languages skipped)
- `items_succeeded = 0` (no segments translated)
- `completed_no_changes` event logged
- Very low `duration_ms` (minimal processing)

### Example 2: All Languages Translated (completed)

**Scenario**: Translate file to 3 languages, no outputs exist

**Event**:
```json
{
  "run_id": "run_20260111_143045_def456",
  "agent_name": "hugo-translator",
  "job_type": "translate_file",
  "trigger_type": "cli",
  "status": "completed",
  "input_summary": "file=content/words/java/quick-start.md; langs=es,fr,de",
  "output_summary": "3 translations, 0 errors",
  "duration_ms": 8543,
  "items_discovered": 87,
  "items_succeeded": 87,
  "items_failed": 0,
  "metrics_json": {
    "langs_skipped": 0,
    "langs_translated": 3,
    "total_segments": 87,
    "translated_segments": 65,
    "tm_hits": 22,
    "skipped_segments": 0,
    "files_translated": 1,
    "files_generated": 3,
    "tokens_input": 4250,
    "tokens_output": 4820,
    "tokens_cached": 1100,
    "tokens_total": 5350,
    "tm_hit_rate": 0.253,
    "token_cache_rate": 0.206
  }
}
```

**Key Indicators**:
- `langs_translated = 3` (all work completed)
- `langs_skipped = 0` (nothing skipped)
- `items_succeeded = 87` (all segments translated or cached)
- `files_generated = 3` (one output per language)
- Significant `duration_ms` (actual work performed)
- Token usage tracked (model invoked)

### Example 3: Mixed Scenario (completed)

**Scenario**: Translate file to 3 languages, 1 output already exists

**Event**:
```json
{
  "run_id": "run_20260111_143112_ghi789",
  "agent_name": "hugo-translator",
  "job_type": "translate_file",
  "trigger_type": "cli",
  "status": "completed",
  "input_summary": "file=content/cells/python/tutorial.md; langs=es,fr,de",
  "output_summary": "2 translations, 1 skipped (existing outputs), 0 errors",
  "duration_ms": 5621,
  "items_discovered": 58,
  "items_succeeded": 58,
  "items_failed": 0,
  "metrics_json": {
    "langs_skipped": 1,
    "langs_translated": 2,
    "total_segments": 58,
    "translated_segments": 42,
    "tm_hits": 16,
    "skipped_segments": 0,
    "files_translated": 1,
    "files_generated": 2,
    "tokens_input": 2890,
    "tokens_output": 3210,
    "tokens_cached": 780,
    "tokens_total": 3670,
    "tm_hit_rate": 0.276,
    "token_cache_rate": 0.212
  }
}
```

**Key Indicators**:
- `langs_translated = 2` (partial work completed)
- `langs_skipped = 1` (one output existed)
- `items_succeeded = 58` (segments for 2 languages)
- `files_generated = 2` (only new outputs created)
- Output summary includes skip information

**Note**: `items_succeeded` reflects segments translated for the 2 languages that were actually processed, not the skipped language.

## Backward Compatibility

### Version 2.0 Compatibility Notes

#### Additive Changes Only
All changes in version 2.0 are additive:
- **No fields removed**: All v1.0 fields remain unchanged
- **No field types changed**: Existing fields maintain their types
- **No semantic changes**: Existing field meanings unchanged

#### Consumer Compatibility

**Old consumers (v1.0)**:
- Can safely ignore new fields (`langs_skipped`, `langs_translated`)
- Can safely ignore `completed_no_changes` events
- Existing queries continue to work
- `output_summary` parsing may not recognize skip information

**New consumers (v2.0)**:
- Should use `langs_translated` for accurate work measurement
- Should monitor `completed_no_changes` for efficiency analysis
- Should parse enhanced `output_summary` format
- Can still read v1.0 events (missing fields default to 0)

#### Migration Strategy

**No migration required** for existing telemetry data:
- Old events remain valid and readable
- New fields will be absent in old events (treat as 0)
- Queries should handle missing fields gracefully

**Example query handling both versions**:
```sql
SELECT
  run_id,
  COALESCE(JSON_EXTRACT(metrics_json, '$.langs_translated'), 0) as langs_translated,
  COALESCE(JSON_EXTRACT(metrics_json, '$.langs_skipped'), 0) as langs_skipped
FROM telemetry_events
```

#### Field Defaults

| Field | Type | Default (if missing) |
|-------|------|----------------------|
| `langs_skipped` | integer | 0 |
| `langs_translated` | integer | 0 |

### Breaking Changes

**None**: Version 2.0 introduces no breaking changes.

## Schema Field Reference

### Core Fields (All Versions)

| Field | Type | Description |
|-------|------|-------------|
| `run_id` | string | Unique identifier for translation run |
| `agent_name` | string | Always "hugo-translator" |
| `job_type` | string | "translate_file" or "translate_directory" |
| `trigger_type` | string | "cli", "web", "scheduled" |
| `status` | string | "completed", "failed", "cancelled" |
| `input_summary` | string | Summary of input (file path, languages) |
| `output_summary` | string | Summary of output (translations, skips, errors) |
| `duration_ms` | integer | Total run duration in milliseconds |
| `items_discovered` | integer | Total items found (segments or files) |
| `items_succeeded` | integer | Items successfully processed |
| `items_failed` | integer | Items that failed processing |

### Extended Metrics (metrics_json)

All fields below are nested under the `metrics_json` object:

#### Segment-Level Metrics
- `total_segments` (int): Total segments in source file
- `translated_segments` (int): Segments translated by model
- `tm_hits` (int): Segments found in translation memory
- `skipped_segments` (int): Segments excluded by rules

#### Language-Level Metrics (v2.0)
- `langs_skipped` (int): Languages skipped (outputs exist)
- `langs_translated` (int): Languages actually translated

#### Token Metrics
- `tokens_input` (int): Tokens sent to model
- `tokens_output` (int): Tokens generated by model
- `tokens_cached` (int): Tokens saved via TM hits
- `tokens_total` (int): Total tokens processed

#### File Operation Metrics
- `md_files_added` (int): New .md files created
- `md_files_updated` (int): Existing .md files overwritten
- `bytes_written_md` (int): Total bytes written
- `files_translated` (int): Files completed successfully
- `files_generated` (int): Output files produced

## Related Documentation

- **Operational Guide**: [Observability Runbook](./runbook.md)
- **Metrics Guide**: [Content Hash Metrics](./content-hash-metrics.md)
- **Source Code**:
  - `src/translation_engine/models.py` (TranslationStats model)
  - `src/observability/telemetry_integration.py` (Telemetry integration)
  - `src/translation_engine/engine.py` (Event logging)

## Support

For questions or issues with telemetry events:
1. Review the [Observability Runbook](./runbook.md) for troubleshooting
2. Check implementation in source files listed above
3. Contact the observability team

---

## Update - 2026-01-15: Additional Events

This section documents telemetry events discovered during the WI-004 audit that were previously undocumented. These events are emitted via `SharedEngines.telemetry.track_event()`.

---

## Benchmarking Events

The benchmarking subsystem emits events for job scheduling, execution, data management, and monitoring.

### Scheduler Events

#### `benchmark_scheduler_started`

- **Description**: Emitted when the benchmark scheduler initializes with SharedEngines integration.
- **Emission Trigger**: Scheduler initialization in shared_engines mode
- **Source**: `src/benchmarking/scheduler.py:156`

**Payload Schema**:
```python
{
    "event_type": "benchmark_scheduler_started",
    "mode": str  # "shared_engines"
}
```

**Example**:
```json
{
    "event_type": "benchmark_scheduler_started",
    "mode": "shared_engines"
}
```

---

#### `benchmark_job_scheduled`

- **Description**: Emitted when a benchmark job is successfully added to the queue.
- **Emission Trigger**: `BenchmarkScheduler.schedule()` success
- **Source**: `src/benchmarking/scheduler.py:290`

**Payload Schema**:
```python
{
    "event_type": "benchmark_job_scheduled",
    "job_id": str,                    # Unique job identifier (8-char UUID prefix)
    "priority": int,                  # Job priority (0=highest, default=5)
    "estimated_memory_mb": float,     # Estimated memory requirement
    "device_required": str            # Required device ("cpu", "cuda", etc.)
}
```

**Example**:
```json
{
    "event_type": "benchmark_job_scheduled",
    "job_id": "a1b2c3d4",
    "priority": 5,
    "estimated_memory_mb": 2048.0,
    "device_required": "cuda"
}
```

---

#### `benchmark_job_schedule_failed`

- **Description**: Emitted when a benchmark job fails to be scheduled.
- **Emission Trigger**: Exception during `BenchmarkScheduler.schedule()`
- **Source**: `src/benchmarking/scheduler.py:308`

**Payload Schema**:
```python
{
    "event_type": "benchmark_job_schedule_failed",
    "error": str  # Error message
}
```

**Example**:
```json
{
    "event_type": "benchmark_job_schedule_failed",
    "error": "Database connection failed: timeout"
}
```

---

#### `benchmark_job_timeout`

- **Description**: Emitted when a job times out waiting for resources.
- **Emission Trigger**: Resource wait timeout in `BenchmarkScheduler.run_next()`
- **Source**: `src/benchmarking/scheduler.py:457`

**Payload Schema**:
```python
{
    "event_type": "benchmark_job_timeout",
    "job_id": str,           # Job identifier
    "timeout_seconds": int   # Configured timeout value
}
```

**Example**:
```json
{
    "event_type": "benchmark_job_timeout",
    "job_id": "a1b2c3d4",
    "timeout_seconds": 3600
}
```

---

#### `benchmark_job_started`

- **Description**: Emitted when a benchmark job begins execution.
- **Emission Trigger**: Job transitions to "running" status
- **Source**: `src/benchmarking/scheduler.py:473`

**Payload Schema**:
```python
{
    "event_type": "benchmark_job_started",
    "job_id": str  # Job identifier
}
```

**Example**:
```json
{
    "event_type": "benchmark_job_started",
    "job_id": "a1b2c3d4"
}
```

---

#### `benchmark_job_completed`

- **Description**: Emitted when a benchmark job completes successfully.
- **Emission Trigger**: Job transitions to "completed" status
- **Source**: `src/benchmarking/scheduler.py:490`

**Payload Schema**:
```python
{
    "event_type": "benchmark_job_completed",
    "job_id": str  # Job identifier
}
```

**Example**:
```json
{
    "event_type": "benchmark_job_completed",
    "job_id": "a1b2c3d4"
}
```

---

#### `benchmark_job_failed`

- **Description**: Emitted when a benchmark job fails during execution.
- **Emission Trigger**: Exception during job execution
- **Source**: `src/benchmarking/scheduler.py:506`

**Payload Schema**:
```python
{
    "event_type": "benchmark_job_failed",
    "error": str  # Error message
}
```

**Example**:
```json
{
    "event_type": "benchmark_job_failed",
    "error": "CUDA out of memory"
}
```

---

### Schema Migration Events

#### `benchmark_schema_migration_started`

- **Description**: Emitted when a database schema migration begins.
- **Emission Trigger**: `SchemaMigrationManager.migrate_to()` start
- **Source**: `src/benchmarking/schema_migrations.py:319`

**Payload Schema**:
```python
{
    "event_type": "benchmark_schema_migration_started",
    "from_version": int,    # Current schema version
    "to_version": int,      # Target schema version
    "dry_run": bool         # Whether this is a dry run
}
```

**Example**:
```json
{
    "event_type": "benchmark_schema_migration_started",
    "from_version": 7,
    "to_version": 8,
    "dry_run": false
}
```

---

#### `benchmark_schema_migration_completed`

- **Description**: Emitted when a database schema migration completes successfully.
- **Emission Trigger**: `SchemaMigrationManager.migrate_to()` success
- **Source**: `src/benchmarking/schema_migrations.py:355`

**Payload Schema**:
```python
{
    "event_type": "benchmark_schema_migration_completed",
    "from_version": int,  # Previous schema version
    "to_version": int     # New schema version
}
```

**Example**:
```json
{
    "event_type": "benchmark_schema_migration_completed",
    "from_version": 7,
    "to_version": 8
}
```

---

#### `benchmark_schema_migration_failed`

- **Description**: Emitted when a database schema migration fails.
- **Emission Trigger**: Exception during migration
- **Source**: `src/benchmarking/schema_migrations.py:366`

**Payload Schema**:
```python
{
    "event_type": "benchmark_schema_migration_failed",
    "from_version": int,  # Current schema version
    "to_version": int,    # Target schema version
    "error": str          # Error message
}
```

**Example**:
```json
{
    "event_type": "benchmark_schema_migration_failed",
    "from_version": 7,
    "to_version": 8,
    "error": "Column 'model_id' already exists"
}
```

---

### Retention Events

#### `benchmark_retention_started`

- **Description**: Emitted when retention policy execution begins.
- **Emission Trigger**: `RetentionManager.execute()` start
- **Source**: `src/benchmarking/retention.py:487`

**Payload Schema**:
```python
{
    "event_type": "benchmark_retention_started",
    "dry_run": bool,                      # Whether this is a dry run
    "policy_count": Union[int, str]       # Number of policies or "all"
}
```

**Example**:
```json
{
    "event_type": "benchmark_retention_started",
    "dry_run": false,
    "policy_count": 3
}
```

---

#### `benchmark_retention_completed`

- **Description**: Emitted when retention policy execution completes.
- **Emission Trigger**: `RetentionManager.execute()` success
- **Source**: `src/benchmarking/retention.py:548`

**Payload Schema**:
```python
{
    "event_type": "benchmark_retention_completed",
    "dry_run": bool,              # Whether this was a dry run
    "total_deleted": int,         # Total rows deleted
    "policy_count": int,          # Number of policies executed
    "duration_seconds": float     # Execution duration
}
```

**Example**:
```json
{
    "event_type": "benchmark_retention_completed",
    "dry_run": false,
    "total_deleted": 15420,
    "policy_count": 3,
    "duration_seconds": 2.34
}
```

---

#### `benchmark_retention_failed`

- **Description**: Emitted when retention policy execution fails.
- **Emission Trigger**: Exception during retention execution
- **Source**: `src/benchmarking/retention.py:564`

**Payload Schema**:
```python
{
    "event_type": "benchmark_retention_failed",
    "error": str,      # Error message
    "dry_run": bool    # Whether this was a dry run
}
```

**Example**:
```json
{
    "event_type": "benchmark_retention_failed",
    "error": "Database locked",
    "dry_run": false
}
```

---

### Aggregation Events

#### `benchmark_aggregation_started`

- **Description**: Emitted when benchmark data aggregation begins.
- **Emission Trigger**: `BenchmarkAggregator.aggregate_all()` start
- **Source**: `src/benchmarking/aggregation.py:167`

**Payload Schema**:
```python
{
    "event_type": "benchmark_aggregation_started",
    "lookback_days": int  # Days of data to aggregate
}
```

**Example**:
```json
{
    "event_type": "benchmark_aggregation_started",
    "lookback_days": 90
}
```

---

#### `benchmark_aggregation_completed`

- **Description**: Emitted when benchmark data aggregation completes.
- **Emission Trigger**: `BenchmarkAggregator.aggregate_all()` success
- **Source**: `src/benchmarking/aggregation.py:225`

**Payload Schema**:
```python
{
    "event_type": "benchmark_aggregation_completed",
    "trends_created": int,        # Number of trend records created
    "combinations": int,          # Model/device combinations processed
    "duration_seconds": float     # Execution duration
}
```

**Example**:
```json
{
    "event_type": "benchmark_aggregation_completed",
    "trends_created": 156,
    "combinations": 12,
    "duration_seconds": 4.56
}
```

---

#### `benchmark_aggregation_failed`

- **Description**: Emitted when benchmark data aggregation fails.
- **Emission Trigger**: Exception during aggregation
- **Source**: `src/benchmarking/aggregation.py:239`

**Payload Schema**:
```python
{
    "event_type": "benchmark_aggregation_failed",
    "error": str  # Error message
}
```

**Example**:
```json
{
    "event_type": "benchmark_aggregation_failed",
    "error": "No benchmark data found for aggregation"
}
```

---

### Export Events

#### `benchmark_export_started`

- **Description**: Emitted when a benchmark data export begins.
- **Emission Trigger**: `BenchmarkExporter.export_csv()` (or other export methods) start
- **Source**: `src/benchmarking/exporter.py:226`

**Payload Schema**:
```python
{
    "event_type": "benchmark_export_started",
    "format": str,                      # Export format ("csv", "json", etc.)
    "compress": bool,                   # Whether compression is enabled
    "filter": Optional[Dict[str, Any]]  # Export filter parameters
}
```

**Example**:
```json
{
    "event_type": "benchmark_export_started",
    "format": "csv",
    "compress": true,
    "filter": {"model_id": "m2m100", "lookback_days": 30}
}
```

---

#### `benchmark_export_completed`

- **Description**: Emitted when a benchmark data export completes.
- **Emission Trigger**: Export success
- **Source**: `src/benchmarking/exporter.py:282`

**Payload Schema**:
```python
{
    "event_type": "benchmark_export_completed",
    "format": str,               # Export format
    "rows_exported": int,        # Total rows exported
    "tables_exported": int,      # Number of tables exported
    "file_size_bytes": int,      # Output file size
    "duration_seconds": float    # Execution duration
}
```

**Example**:
```json
{
    "event_type": "benchmark_export_completed",
    "format": "csv",
    "rows_exported": 50000,
    "tables_exported": 5,
    "file_size_bytes": 2456789,
    "duration_seconds": 12.34
}
```

---

#### `benchmark_export_failed`

- **Description**: Emitted when a benchmark data export fails.
- **Emission Trigger**: Exception during export
- **Source**: `src/benchmarking/exporter.py:296`

**Payload Schema**:
```python
{
    "event_type": "benchmark_export_failed",
    "format": str,   # Export format
    "error": str     # Error message
}
```

**Example**:
```json
{
    "event_type": "benchmark_export_failed",
    "format": "csv",
    "error": "Disk full: insufficient space"
}
```

---

### Archive Events

#### `benchmark_archive_started`

- **Description**: Emitted when a benchmark data archive operation begins.
- **Emission Trigger**: `BenchmarkArchiver.create_archive()` start
- **Source**: `src/benchmarking/archiver.py:267`

**Payload Schema**:
```python
{
    "event_type": "benchmark_archive_started",
    "before_date": str,       # Archive data before this date (ISO format)
    "compress": bool,         # Whether to compress the archive
    "delete_after": bool      # Whether to delete source data after archiving
}
```

**Example**:
```json
{
    "event_type": "benchmark_archive_started",
    "before_date": "2025-01-01",
    "compress": true,
    "delete_after": false
}
```

---

#### `benchmark_archive_created`

- **Description**: Emitted when a benchmark archive is successfully created.
- **Emission Trigger**: `BenchmarkArchiver.create_archive()` success
- **Source**: `src/benchmarking/archiver.py:355`

**Payload Schema**:
```python
{
    "event_type": "benchmark_archive_created",
    "archive_path": str,         # Path to the created archive
    "runs_archived": int,        # Number of benchmark runs archived
    "results_archived": int,     # Number of results archived
    "file_size_bytes": int,      # Archive file size
    "compressed": bool,          # Whether archive is compressed
    "rows_deleted": int,         # Rows deleted from source (if delete_after=True)
    "duration_seconds": float    # Operation duration
}
```

**Example**:
```json
{
    "event_type": "benchmark_archive_created",
    "archive_path": "/data/archives/archive_20260115_143022.db.gz",
    "runs_archived": 450,
    "results_archived": 22500,
    "file_size_bytes": 15678901,
    "compressed": true,
    "rows_deleted": 0,
    "duration_seconds": 45.67
}
```

---

#### `benchmark_archive_failed`

- **Description**: Emitted when a benchmark archive operation fails.
- **Emission Trigger**: Exception during archive creation
- **Source**: `src/benchmarking/archiver.py:371`

**Payload Schema**:
```python
{
    "event_type": "benchmark_archive_failed",
    "error": str  # Error message
}
```

**Example**:
```json
{
    "event_type": "benchmark_archive_failed",
    "error": "Archive directory not writable"
}
```

---

### Performance Monitoring Events

#### `benchmark_query_executed`

- **Description**: Emitted for every analytics query executed.
- **Emission Trigger**: Query execution in analytics or performance monitor
- **Source**: `src/benchmarking/analytics.py:215`, `src/benchmarking/performance_monitor.py:207`

**Payload Schema** (Analytics):
```python
{
    "event_type": "benchmark_query_executed",
    "query_type": str,            # Type of query
    "duration_seconds": float,    # Query duration
    # Additional kwargs vary by query type
}
```

**Payload Schema** (Performance Monitor):
```python
{
    "event_type": "benchmark_query_executed",
    "query_name": str,       # Query identifier
    "duration_ms": float,    # Duration in milliseconds
    "cache_hit": bool,       # Whether result was cached
    "row_count": int         # Number of rows returned
}
```

**Example**:
```json
{
    "event_type": "benchmark_query_executed",
    "query_name": "get_performance_trends",
    "duration_ms": 45.6,
    "cache_hit": false,
    "row_count": 156
}
```

---

#### `benchmark_slow_query`

- **Description**: Emitted when a query exceeds the slow query threshold.
- **Emission Trigger**: Query duration > slow_threshold_ms
- **Source**: `src/benchmarking/performance_monitor.py:193`

**Payload Schema**:
```python
{
    "event_type": "benchmark_slow_query",
    "query_name": str,        # Query identifier
    "duration_ms": float,     # Query duration in milliseconds
    "threshold_ms": float,    # Slow query threshold
    "params": Dict[str, Any]  # Query parameters
}
```

**Example**:
```json
{
    "event_type": "benchmark_slow_query",
    "query_name": "get_performance_trends",
    "duration_ms": 2345.67,
    "threshold_ms": 1000.0,
    "params": {"model_id": "m2m100", "lookback_days": 365}
}
```

---

### Dashboard Events

#### `benchmark_dashboard_started`

- **Description**: Emitted when the benchmark dashboard initializes with SharedEngines.
- **Emission Trigger**: Dashboard initialization
- **Source**: `src/benchmarking/dashboard/app.py:780`

**Payload Schema**:
```python
{
    "event_type": "benchmark_dashboard_started",
    "mode": str,      # "shared_engines"
    "db_path": str    # Path to benchmark database
}
```

**Example**:
```json
{
    "event_type": "benchmark_dashboard_started",
    "mode": "shared_engines",
    "db_path": "/data/benchmark.db"
}
```

---

## Worker Events

Events emitted by translation worker processes.

### `worker_started`

- **Description**: Emitted when a worker process initializes with SharedEngines.
- **Emission Trigger**: JobProcessor initialization
- **Source**: `src/workers/job_processor.py:126`

**Payload Schema**:
```python
{
    "event_type": "worker_started",
    "worker_id": str,   # Worker identifier (from WORKER_ID env or "worker-unknown")
    "mode": str         # "shared_engines"
}
```

**Example**:
```json
{
    "event_type": "worker_started",
    "worker_id": "worker-001",
    "mode": "shared_engines"
}
```

---

### `worker_started_with_execution_mode`

- **Description**: Emitted when a worker starts with specific execution mode configuration.
- **Emission Trigger**: Worker runner initialization
- **Source**: `src/workers/job_processor.py:454`

**Payload Schema**:
```python
{
    "event_type": "worker_started_with_execution_mode",
    "worker_id": str,         # Worker identifier
    "execution_mode": str,    # Execution mode ("cpu", "gpu", "auto")
    "device": str,            # Device being used
    "mode": str               # "worker_runner"
}
```

**Example**:
```json
{
    "event_type": "worker_started_with_execution_mode",
    "worker_id": "gpu-worker-01",
    "execution_mode": "gpu",
    "device": "cuda:0",
    "mode": "worker_runner"
}
```

---

## Orchestrator Events

Events emitted by the translation orchestrator.

### `orchestrator_started`

- **Description**: Emitted when the orchestrator initializes with SharedEngines.
- **Emission Trigger**: TranslationOrchestrator initialization
- **Source**: `src/orchestrator/orchestrator.py:66`

**Payload Schema**:
```python
{
    "event_type": "orchestrator_started",
    "mode": str,                       # "shared_engines"
    "file_watcher_enabled": bool,      # Whether file watching is enabled
    "sweep_scheduler_enabled": bool    # Whether sweep scheduling is enabled
}
```

**Example**:
```json
{
    "event_type": "orchestrator_started",
    "mode": "shared_engines",
    "file_watcher_enabled": true,
    "sweep_scheduler_enabled": true
}
```

---

### `orchestrator_stopped`

- **Description**: Emitted when the orchestrator shuts down.
- **Emission Trigger**: TranslationOrchestrator.stop()
- **Source**: `src/orchestrator/orchestrator.py:144`

**Payload Schema**:
```python
{
    "event_type": "orchestrator_stopped",
    "mode": str  # "shared_engines"
}
```

**Example**:
```json
{
    "event_type": "orchestrator_stopped",
    "mode": "shared_engines"
}
```

---

## CLI Events

Events emitted by the command-line interface during translation operations.

### `translation_session_start`

- **Description**: Emitted when a translation session begins via CLI.
- **Emission Trigger**: CLI translate command start
- **Source**: `src/cli.py:1392`

**Payload Schema**:
```python
{
    "event_type": "translation_session_start",
    "site_id": str,             # Site identifier
    "target_langs": List[str],  # Target languages
    "model_id": str             # Model identifier or "default"
}
```

**Example**:
```json
{
    "event_type": "translation_session_start",
    "site_id": "docs.aspose.com",
    "target_langs": ["es", "fr", "de"],
    "model_id": "m2m100"
}
```

---

### `multilang_processing_complete`

- **Description**: Emitted when multi-language processing completes (all languages processed).
- **Emission Trigger**: All language subprocesses complete
- **Source**: `src/cli.py:1844`

**Payload Schema**:
```python
{
    "event_type": "multilang_processing_complete",
    "site_id": str,               # Site identifier
    "total_languages": int,       # Total target languages
    "successful_languages": int,  # Languages completed successfully
    "failed_languages": int,      # Languages that failed
    "success_rate": float         # Success rate (0.0 to 1.0)
}
```

**Example**:
```json
{
    "event_type": "multilang_processing_complete",
    "site_id": "docs.aspose.com",
    "total_languages": 5,
    "successful_languages": 4,
    "failed_languages": 1,
    "success_rate": 0.8
}
```

---

### `translation_success`

- **Description**: Emitted when a single-file translation completes successfully.
- **Emission Trigger**: File translation success
- **Source**: `src/cli.py:2224`

**Payload Schema**:
```python
{
    "event_type": "translation_success",
    "site_id": str,             # Site identifier
    "file_path": str,           # Translated file path
    "target_langs": List[str]   # Target languages
}
```

**Example**:
```json
{
    "event_type": "translation_success",
    "site_id": "docs.aspose.com",
    "file_path": "/content/slides/net/getting-started.md",
    "target_langs": ["es", "fr"]
}
```

---

### `translation_failure`

- **Description**: Emitted when a translation fails.
- **Emission Trigger**: File translation failure
- **Source**: `src/cli.py:2242`

**Payload Schema**:
```python
{
    "event_type": "translation_failure",
    "site_id": str,        # Site identifier
    "file_path": str,      # File that failed to translate
    "errors": List[str]    # List of error messages
}
```

**Example**:
```json
{
    "event_type": "translation_failure",
    "site_id": "docs.aspose.com",
    "file_path": "/content/slides/net/getting-started.md",
    "errors": ["Model timeout after 300s", "Validation failed: missing segments"]
}
```

---

### `directory_translation_complete`

- **Description**: Emitted when a directory translation operation completes.
- **Emission Trigger**: Directory translation complete
- **Source**: `src/cli.py:2268`

**Payload Schema**:
```python
{
    "event_type": "directory_translation_complete",
    "site_id": str,             # Site identifier
    "total_files": int,         # Total files processed
    "successful_files": int,    # Files completed successfully
    "failed_files": int,        # Files that failed
    "target_langs": List[str]   # Target languages
}
```

**Example**:
```json
{
    "event_type": "directory_translation_complete",
    "site_id": "docs.aspose.com",
    "total_files": 150,
    "successful_files": 147,
    "failed_files": 3,
    "target_langs": ["es", "fr", "de"]
}
```

---

## Event Coverage Summary

| Category | Event Count | Status |
|----------|-------------|--------|
| Translation (Core) | 3 | Documented (v1.0) |
| Subprocess | 4 | Documented (v1.0) |
| Validation | 2 | Documented (v1.0) |
| Benchmarking | 21 | Documented (v2.1) |
| Worker | 2 | Documented (v2.1) |
| Orchestrator | 2 | Documented (v2.1) |
| CLI | 5 | Documented (v2.1) |
| **Total** | **39** | **100% Coverage** |

---

**Document Version**: 2.1
**Schema Version**: 2.0
**Maintained By**: Observability Team
**Last Review**: 2026-01-15
