# Telemetry API HTTP Reference

**Quick Start:** This document is the complete reference for integrating with the Local Telemetry Platform HTTP API. Use this when implementing agents or services that need to track telemetry data.

**Version:** 3.0.0
**Last Updated:** 2026-02-07
**Detailed Specs:** See [specs/features/](../../specs/features/) for endpoint-specific implementation details

## Service

- **Name:** local-telemetry-api
- **Version:** 3.0.0
- **Container:** local-telemetry-api
- **Image:** local-telemetry-api:3.0.0
- **Base URL:** http://localhost:8765 (configurable via `TELEMETRY_API_URL`)
- **OpenAPI:** /openapi.json
- **Interactive Docs:** /docs (Swagger UI), /redoc (ReDoc)

## Authentication

- Optional and disabled by default.
- Enable with `TELEMETRY_API_AUTH_ENABLED=true`.
- When enabled, send `Authorization: Bearer <token>` where `<token>` matches `TELEMETRY_API_AUTH_TOKEN`.
- Missing/invalid auth returns `401` with `WWW-Authenticate: Bearer`.

## Rate Limiting

- Optional and disabled by default.
- Enable with `TELEMETRY_RATE_LIMIT_ENABLED=true`.
- Limit configured by `TELEMETRY_RATE_LIMIT_RPM` (requests per minute per client IP).
- Exceeded limit returns `429` with headers:
  - `Retry-After: 60`
  - `X-RateLimit-Limit: <rpm>`
  - `X-RateLimit-Remaining: 0`

## Common Headers

- `Content-Type: application/json` for all request bodies.
- `Authorization: Bearer <token>` required only when auth is enabled on endpoints that enforce auth.

## Error Format

- Most errors use FastAPI standard shape:
  - `{"detail": "<message>"}`
- Validation errors (422) use:
  - `{"detail": [{"loc": [...], "msg": "...", "type": "..."}]}`

## Key Concepts for Implementation

### Status Values and Normalization

**Canonical Statuses** (stored in database):
- `running` - Run is in progress
- `success` - Run completed successfully
- `failure` - Run failed
- `partial` - Run completed with partial success
- `timeout` - Run exceeded time limit
- `cancelled` - Run was cancelled

**Status Aliases** (automatically normalized on POST and GET queries):
- `failed` → `failure`
- `completed` → `success`
- `succeeded` → `success`

**Validation Differences:**
- **POST /api/v1/runs:** Accepts aliases (`failed`, `completed`, `succeeded`) and normalizes them. Any string is accepted by the Pydantic model; normalization maps known aliases to canonical values.
- **PATCH /api/v1/runs/{event_id}:** Strict validation — only the 6 canonical values are accepted. Aliases and unknown values return 422.
- **GET /api/v1/runs (query filter):** Accepts aliases in the `status` query parameter and normalizes before querying. Invalid values return 400.

### Idempotency via event_id

**Critical:** Always generate unique `event_id` values (UUIDs recommended). The API uses `event_id` as the idempotency key:
- Duplicate `event_id` POST requests return **201 Created** with `"status": "duplicate"` in the response body (not an error)
- Distinguish new vs duplicate by checking the response body `status` field: `"created"` or `"duplicate"`
- This enables safe retries after network failures
- Use the same `event_id` for PATCH updates to the same run

### Timestamp Formats

**Always use ISO8601 with timezone:**
- ✅ `2026-01-12T10:30:00Z` (UTC)
- ✅ `2026-01-12T10:30:00.123456+00:00` (UTC with microseconds)
- ✅ `2026-01-12T10:30:00-08:00` (with timezone offset)
- ❌ `2026-01-12 10:30:00` (no timezone, will cause validation errors)

### Git Commit Tracking

**Two ways to associate commits:**

1. **Include in POST /api/v1/runs** (if known at start):
   ```json
   {
     "event_id": "...",
     "git_repo": "https://github.com/owner/repo",
     "git_commit_hash": "abc123",
     "git_branch": "main"
   }
   ```
   **Note:** `git_commit_source`, `git_commit_author`, and `git_commit_timestamp` are accepted in the POST body but are **NOT persisted** on initial creation. Use PATCH or associate-commit to set these fields.

2. **Associate after run** (if commit created later):
   ```bash
   POST /api/v1/runs/{event_id}/associate-commit
   {"commit_hash": "abc123", "commit_source": "llm"}
   ```

**commit_source values:**
- `manual` - Human-created commit
- `llm` - LLM-generated commit (e.g., Claude Code, Cursor, Copilot)
- `ci` - CI/CD pipeline commit

## Complete Field Reference

### POST /api/v1/runs — Request Fields

Every field accepted by the `POST /api/v1/runs` endpoint, with type, requirement, default, and constraints.

| Field | Type | Required | Default | Constraints / Notes |
|-------|------|----------|---------|---------------------|
| `event_id` | string | **Yes** | — | Unique idempotency key. UUID recommended. |
| `run_id` | string | **Yes** | — | Application-level run identifier. |
| `agent_name` | string | **Yes** | — | Name of the agent/service. |
| `job_type` | string | **Yes** | — | Type of job being executed. |
| `start_time` | string | **Yes** | — | ISO8601 with timezone. |
| `created_at` | string | No | Current UTC time | ISO8601. Auto-generated if omitted. |
| `end_time` | string | No | `null` | ISO8601. Set on completion. |
| `status` | string | No | `"running"` | Canonical or alias value. Normalized before storage. |
| `product` | string | No | `null` | Product identifier. |
| `product_family` | string | No | `null` | Product family grouping. |
| `platform` | string | No | `null` | Platform identifier (e.g., `"web"`). |
| `subdomain` | string | No | `null` | Site subdomain. |
| `website` | string | No | `null` | Root domain (e.g., `"example.com"`). |
| `website_section` | string | No | `null` | Section of the website (e.g., `"blog"`). |
| `item_name` | string | No | `null` | Specific page/entity being tracked. |
| `items_discovered` | integer | No | `0` | Must be ≥ 0. |
| `items_succeeded` | integer | No | `0` | Must be ≥ 0. |
| `items_failed` | integer | No | `0` | Must be ≥ 0. |
| `items_skipped` | integer | No | `0` | Must be ≥ 0. |
| `duration_ms` | integer\|null | No | `0` | `null` is auto-converted to `0`. Must be ≥ 0. |
| `input_summary` | string | No | `null` | Description of input data. |
| `output_summary` | string | No | `null` | Description of output/results. |
| `source_ref` | string | No | `null` | Source reference (e.g., S3 path, URL). |
| `target_ref` | string | No | `null` | Target/destination reference. |
| `error_summary` | string | No | `null` | Short error description. |
| `error_details` | string | No | `null` | Full error details/traceback. |
| `git_repo` | string | No | `null` | Repository URL (HTTPS or SSH). Persisted on POST. |
| `git_branch` | string | No | `null` | Git branch name. Persisted on POST. |
| `git_commit_hash` | string | No | `null` | Commit SHA. Persisted on POST. |
| `git_run_tag` | string | No | `null` | Run tag (e.g., `"nightly"`). Persisted on POST. |
| `git_commit_source` | string | No | `null` | ⚠️ **Accepted but NOT persisted on POST.** Must be `manual`, `llm`, or `ci`. Use PATCH or associate-commit. |
| `git_commit_author` | string | No | `null` | ⚠️ **Accepted but NOT persisted on POST.** Use PATCH or associate-commit. |
| `git_commit_timestamp` | string | No | `null` | ⚠️ **Accepted but NOT persisted on POST.** ISO8601. Use PATCH or associate-commit. |
| `host` | string | No | `null` | Hostname of the execution environment. |
| `environment` | string | No | `null` | Environment name (e.g., `"prod"`, `"staging"`). |
| `trigger_type` | string | No | `null` | What triggered the run (e.g., `"scheduler"`, `"manual"`). |
| `metrics_json` | object | No | `null` | Any JSON structure for custom metrics. Stored as JSON text. |
| `context_json` | object | No | `null` | Any JSON structure for custom context. Stored as JSON text. |
| `api_posted` | boolean | No | `false` | Whether run was posted to external API. |
| `api_posted_at` | string | No | `null` | ISO8601 timestamp of external API post. |
| `api_retry_count` | integer | No | `0` | Number of external API retry attempts. |
| `insight_id` | string | No | `null` | Links to an originating insight (SEO Intelligence integration). |
| `parent_run_id` | string | No | `null` | Parent run's event_id for hierarchical runs. |

### PATCH /api/v1/runs/{event_id} — Updatable Fields

Only these fields can be updated via PATCH. At least one non-null field is required.

| Field | Type | Constraints |
|-------|------|-------------|
| `status` | string | **Strict validation:** `running`, `success`, `failure`, `partial`, `timeout`, `cancelled` only. Aliases NOT accepted. |
| `end_time` | string | ISO8601 with timezone. |
| `duration_ms` | integer | Must be ≥ 0. |
| `error_summary` | string | Short error description. |
| `error_details` | string | Full error details/traceback. |
| `output_summary` | string | Description of output/results. |
| `items_succeeded` | integer | Must be ≥ 0. |
| `items_failed` | integer | Must be ≥ 0. |
| `items_skipped` | integer | Must be ≥ 0. |
| `metrics_json` | object | Any JSON structure. |
| `context_json` | object | Any JSON structure. |
| `git_commit_source` | string | Must be `manual`, `llm`, or `ci`. |
| `git_commit_author` | string | Author string (e.g., `"Name <email>"`). |
| `git_commit_timestamp` | string | ISO8601 with timezone. |

**Fields NOT updatable via PATCH:** `event_id`, `run_id`, `agent_name`, `job_type`, `start_time`, `created_at`, `product`, `platform`, `website`, `git_repo`, `git_branch`, `git_commit_hash`, `items_discovered`, `input_summary`, `source_ref`, `target_ref`, `host`, `environment`, `trigger_type`, `insight_id`, `parent_run_id`.

**Important:** PATCH does **not** automatically update the `updated_at` timestamp. Only the `associate-commit` endpoint updates `updated_at`.

### POST /api/v1/runs/{event_id}/associate-commit — Request Fields

| Field | Type | Required | Constraints |
|-------|------|----------|-------------|
| `commit_hash` | string | **Yes** | 7-40 characters. Git commit SHA. |
| `commit_source` | string | **Yes** | Must be `manual`, `llm`, or `ci`. |
| `commit_author` | string | No | Author string (e.g., `"Name <email>"`). |
| `commit_timestamp` | string | No | ISO8601 with timezone. |

This endpoint updates `git_commit_hash`, `git_commit_source`, `git_commit_author`, `git_commit_timestamp`, and `updated_at` on the run record.

## Typical Workflow for Agents

### Basic Pattern: Start → Work → Complete

```python
import requests
import uuid
from datetime import datetime, timezone

api_url = "http://localhost:8765"
event_id = str(uuid.uuid4())

# 1. Start run
requests.post(f"{api_url}/api/v1/runs", json={
    "event_id": event_id,
    "run_id": f"{datetime.now(timezone.utc).isoformat()}-my-agent-{uuid.uuid4().hex[:8]}",
    "agent_name": "my-agent",
    "job_type": "data-processing",
    "status": "running",
    "start_time": datetime.now(timezone.utc).isoformat(),
    "git_repo": "https://github.com/owner/repo",
    "git_branch": "main"
})

# 2. Do work
try:
    result = do_work()

    # 3. Mark success
    requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
        "status": "success",
        "end_time": datetime.now(timezone.utc).isoformat(),
        "duration_ms": 5000,
        "items_succeeded": result.count,
        "output_summary": "Processed successfully"
    })

except Exception as e:
    # 3. Mark failure
    requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
        "status": "failure",
        "end_time": datetime.now(timezone.utc).isoformat(),
        "error_summary": str(e),
        "error_details": traceback.format_exc()
    })
```

### Pattern with Commit Association

```python
# 1. Start run
event_id = str(uuid.uuid4())
requests.post(f"{api_url}/api/v1/runs", json={
    "event_id": event_id,
    "run_id": f"run-{event_id[:8]}",
    "agent_name": "code-generator",
    "job_type": "feature-implementation",
    "status": "running",
    "start_time": datetime.now(timezone.utc).isoformat()
})

# 2. Do work and create commit
result = generate_code()
commit_sha = create_git_commit()

# 3. Associate commit
requests.post(f"{api_url}/api/v1/runs/{event_id}/associate-commit", json={
    "commit_hash": commit_sha,
    "commit_source": "llm",
    "commit_author": "Claude Code <noreply@anthropic.com>",
    "commit_timestamp": datetime.now(timezone.utc).isoformat()
})

# 4. Mark complete
requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
    "status": "success",
    "end_time": datetime.now(timezone.utc).isoformat()
})
```

### Pattern with Batch Upload

```python
# Collect multiple events (e.g., from buffer/queue)
events = [
    {
        "event_id": str(uuid.uuid4()),
        "run_id": f"run-{i}",
        "agent_name": "bulk-processor",
        "job_type": "batch-job",
        "status": "success",
        "start_time": datetime.now(timezone.utc).isoformat()
    }
    for i in range(50)
]

# Upload in single request
response = requests.post(f"{api_url}/api/v1/runs/batch", json=events)
result = response.json()
print(f"Inserted: {result['inserted']}, Duplicates: {result['duplicates']}")
```

## Implementation Best Practices

### 1. Always Use event_id for Idempotency
```python
# ✅ Good: Generate once, reuse for retries
event_id = str(uuid.uuid4())
for attempt in range(3):
    try:
        response = requests.post(f"{api_url}/api/v1/runs", json={
            "event_id": event_id,  # Same ID for retries
            # ... other fields
        })
        break
    except requests.exceptions.RequestException:
        time.sleep(2 ** attempt)
```

### 2. Use PATCH for Updates (Not POST)
```python
# ✅ Good: Update existing run
requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
    "status": "success",
    "end_time": "..."
})

# ❌ Bad: Creating new run instead of updating
# requests.post(...)
```

### 3. Track Duration in Milliseconds
```python
import time

start_time = time.time()
do_work()
duration_ms = int((time.time() - start_time) * 1000)

requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
    "duration_ms": duration_ms
})
```

### 4. Always Include Timezone in Timestamps
```python
from datetime import datetime, timezone

# ✅ Good: Explicit UTC
start_time = datetime.now(timezone.utc).isoformat()

# ❌ Bad: No timezone (causes validation errors)
# start_time = datetime.now().isoformat()
```

### 5. Handle API Failures Gracefully
```python
try:
    requests.post(f"{api_url}/api/v1/runs", json=run_data)
except requests.exceptions.RequestException as e:
    # Don't crash your agent if telemetry fails
    print(f"Telemetry failed (non-fatal): {e}")
```

### 6. Check Response Body for Created vs Duplicate
```python
response = requests.post(f"{api_url}/api/v1/runs", json=run_data)
# Both created and duplicate return HTTP 201
result = response.json()
if result["status"] == "created":
    print(f"New run created: {result['event_id']}")
elif result["status"] == "duplicate":
    print(f"Run already exists (safe retry): {result['event_id']}")
```

### 7. Use Canonical Statuses on PATCH
```python
# ✅ Good: Use canonical status values on PATCH
requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
    "status": "failure"  # canonical
})

# ❌ Bad: Aliases like "failed" are NOT accepted on PATCH (returns 422)
# requests.patch(..., json={"status": "failed"})

# ✅ OK on POST: Aliases ARE accepted on POST
requests.post(f"{api_url}/api/v1/runs", json={
    "status": "failed",  # normalized to "failure" automatically
    ...
})
```

## Schemas (Examples)

### TelemetryRun (request body for POST /api/v1/runs and /api/v1/runs/batch)
Required fields: `event_id`, `run_id`, `agent_name`, `job_type`, `start_time`

```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123",
  "created_at": "2026-01-05T18:40:27.000000+00:00",
  "start_time": "2026-01-05T18:40:27.000000+00:00",
  "end_time": null,
  "agent_name": "seo_intelligence.insight_engine",
  "job_type": "insight_generation",
  "status": "running",
  "product": "seo-intelligence",
  "product_family": "content",
  "platform": "web",
  "subdomain": "docs",
  "website": "example.com",
  "website_section": "blog",
  "item_name": "how-to-optimize",
  "items_discovered": 10,
  "items_succeeded": 8,
  "items_failed": 2,
  "items_skipped": 0,
  "duration_ms": 0,
  "input_summary": "Indexed blog posts",
  "output_summary": "Generated insights",
  "source_ref": "s3://bucket/input.csv",
  "target_ref": "s3://bucket/output.json",
  "error_summary": null,
  "error_details": null,
  "git_repo": "https://github.com/example/repo",
  "git_branch": "main",
  "git_commit_hash": "abc1234567890",
  "git_run_tag": "nightly",
  "host": "worker-01",
  "environment": "prod",
  "trigger_type": "scheduler",
  "metrics_json": {"token_count": 1234},
  "context_json": {"pipeline": "seo-ingest"},
  "api_posted": false,
  "api_posted_at": null,
  "api_retry_count": 0,
  "insight_id": "insight-001",
  "parent_run_id": "run-parent-123"
}
```

Notes:
- `duration_ms` accepts `null` and is converted to `0`.
- `git_commit_source` must be one of `manual`, `llm`, `ci` (422 if invalid).
- `git_commit_source`, `git_commit_author`, `git_commit_timestamp` are accepted in the request body but are **NOT written to the database** on POST. To set these fields, use PATCH or the associate-commit endpoint.

### Minimum Viable POST Request
The smallest valid request body for POST /api/v1/runs:
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "my-run-001",
  "agent_name": "my-agent",
  "job_type": "my-job",
  "start_time": "2026-01-05T18:40:27Z"
}
```
All other fields use their defaults: `status` defaults to `"running"`, numeric counters default to `0`, everything else defaults to `null`.

### RunUpdate (request body for PATCH /api/v1/runs/{event_id})
All fields optional; at least one non-null field required.

```json
{
  "status": "success",
  "end_time": "2026-01-05T18:45:10.000000+00:00",
  "duration_ms": 275000,
  "error_summary": null,
  "error_details": null,
  "output_summary": "Completed successfully",
  "items_succeeded": 10,
  "items_failed": 0,
  "items_skipped": 0,
  "metrics_json": {"token_count": 2500},
  "context_json": {"stage": "final"},
  "git_commit_source": "llm",
  "git_commit_author": "Claude <noreply@anthropic.com>",
  "git_commit_timestamp": "2026-01-05T18:45:10Z"
}
```

Notes:
- `status` must be one of `running`, `success`, `failure`, `partial`, `timeout`, `cancelled`. **Aliases are NOT accepted on PATCH** (unlike POST).
- `duration_ms`, `items_succeeded`, `items_failed`, `items_skipped` must be non-negative.
- Fields explicitly set to `null` are ignored (cannot be cleared to null).
- PATCH does **not** automatically update the `updated_at` database column.

### CommitAssociation (request body for POST /api/v1/runs/{event_id}/associate-commit)
```json
{
  "commit_hash": "abc1234567890abcdef",
  "commit_source": "llm",
  "commit_author": "Claude Code <noreply@anthropic.com>",
  "commit_timestamp": "2026-01-02T10:00:00Z"
}
```

Notes:
- `commit_hash` length 7-40 characters.
- `commit_source` must be one of `manual`, `llm`, `ci`.
- This endpoint **does** update the `updated_at` database column.

### RunRecord (response item for GET /api/v1/runs and GET /api/v1/runs/{event_id})
```json
{
  "id": 123,
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123",
  "schema_version": 7,
  "created_at": "2026-01-05T18:40:27.000000+00:00",
  "updated_at": "2026-01-05T18:45:10.000000+00:00",
  "start_time": "2026-01-05T18:40:27.000000+00:00",
  "end_time": "2026-01-05T18:45:10.000000+00:00",
  "agent_name": "seo_intelligence.insight_engine",
  "agent_owner": null,
  "job_type": "insight_generation",
  "status": "success",
  "product": "seo-intelligence",
  "product_family": "content",
  "platform": "web",
  "subdomain": "docs",
  "website": "example.com",
  "website_section": "blog",
  "item_name": "how-to-optimize",
  "items_discovered": 10,
  "items_succeeded": 10,
  "items_failed": 0,
  "items_skipped": 0,
  "duration_ms": 275000,
  "input_summary": "Indexed blog posts",
  "output_summary": "Generated insights",
  "source_ref": "s3://bucket/input.csv",
  "target_ref": "s3://bucket/output.json",
  "error_summary": null,
  "error_details": null,
  "git_repo": "https://github.com/example/repo",
  "git_branch": "main",
  "git_commit_hash": "abc1234567890",
  "git_run_tag": "nightly",
  "git_commit_source": "llm",
  "git_commit_author": "Claude <noreply@anthropic.com>",
  "git_commit_timestamp": "2026-01-05T18:45:10Z",
  "host": "worker-01",
  "environment": "prod",
  "trigger_type": "scheduler",
  "metrics_json": {"token_count": 2500},
  "context_json": {"stage": "final"},
  "api_posted": false,
  "api_posted_at": null,
  "api_retry_count": 0,
  "insight_id": "insight-001",
  "parent_run_id": "run-parent-123",
  "commit_url": "https://github.com/example/repo/commit/abc1234567890",
  "repo_url": "https://github.com/example/repo"
}
```

Notes:
- `metrics_json` and `context_json` are parsed from stored JSON strings.
- If JSON parsing fails, the original string is preserved and an additional field is added:
  - `metrics_json_parse_error` or `context_json_parse_error`
- `commit_url` and `repo_url` are derived fields (not stored in database).
- `id`, `schema_version`, `updated_at`, `agent_owner` are server-managed fields not set by the client.
- `api_posted` is returned as a boolean (`true`/`false`), converted from SQLite integer storage.
- `GET /api/v1/runs` returns an **array** of RunRecord objects.
- `GET /api/v1/runs/{event_id}` returns a **single** RunRecord object (not an array).

### BatchResponse (response body for POST /api/v1/runs/batch)
```json
{
  "inserted": 3,
  "duplicates": 1,
  "errors": [],
  "total": 4
}
```

### POST /api/v1/runs — Response Bodies

**New run created (HTTP 201):**
```json
{
  "status": "created",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123"
}
```

**Duplicate event_id (HTTP 201, idempotent):**
```json
{
  "status": "duplicate",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "message": "Event already exists (idempotent)"
}
```
Note: Both created and duplicate return HTTP 201. Use the `status` field in the response body to distinguish them.

### PATCH /api/v1/runs/{event_id} — Response Body

**Update successful (HTTP 200):**
```json
{
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "updated": true,
  "fields_updated": ["status", "end_time", "duration_ms"]
}
```

### POST /api/v1/runs/{event_id}/associate-commit — Response Body

**Association successful (HTTP 200):**
```json
{
  "status": "success",
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123",
  "commit_hash": "abc1234567890abcdef"
}
```

### HealthResponse (GET /health)
```json
{
  "status": "ok",
  "version": "3.0.0",
  "db_path": "/data/telemetry.sqlite",
  "journal_mode": "DELETE",
  "synchronous": "FULL"
}
```

### MetricsResponse (GET /metrics)
```json
{
  "total_runs": 12345,
  "agents": {"seo_intelligence.insight_engine": 8400},
  "recent_24h": 120,
  "performance": {
    "db_path": "/data/telemetry.sqlite",
    "journal_mode": "DELETE"
  }
}
```

### MetadataResponse (GET /api/v1/metadata)
```json
{
  "agent_names": ["seo_intelligence.insight_engine", "seo_intelligence.scheduler"],
  "job_types": ["insight_generation", "scheduling"],
  "counts": {"agent_names": 2, "job_types": 2},
  "cache_hit": false
}
```

| Field | Type | Description |
|-------|------|-------------|
| agent_names | string[] | Distinct agent names in the database |
| job_types | string[] | Distinct job types in the database |
| counts | object | Count of unique agent_names and job_types |
| cache_hit | boolean | `true` if result was served from cache, `false` if freshly queried |

## Endpoints

### GET /health
Health check for the service.

Auth: not required
Rate limit: not enforced

Status codes:
- 200 OK: returns HealthResponse

Example:
```bash
curl http://localhost:8765/health
```

### GET /metrics
Returns system-level metrics (counts by agent, total runs, recent runs).

Auth: not required
Rate limit: not enforced

Status codes:
- 200 OK: returns MetricsResponse
- 500 Internal Server Error: database errors

Example:
```bash
curl http://localhost:8765/metrics
```

### GET /api/v1/metadata
Returns distinct agent names and job types seen in the database.

Auth: not required
Rate limit: enforced if enabled

**Caching**: Results are cached in-memory for 300 seconds (5 minutes) to improve performance on large datasets. The `cache_hit` field in the response indicates whether the result was served from cache. Cache is automatically invalidated when new runs are created via POST or PATCH endpoints.

Status codes:
- 200 OK: returns MetadataResponse
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl http://localhost:8765/api/v1/metadata
```

Response:
```json
{
  "agent_names": ["agent1", "agent2"],
  "job_types": ["job1", "job2"],
  "counts": {"agent_names": 2, "job_types": 2},
  "cache_hit": true
}
```

### POST /api/v1/runs
Create a single telemetry run (idempotent by `event_id`).

Auth: required if enabled
Rate limit: enforced if enabled

Request body: TelemetryRun

Status codes:
- 201 Created: new run created (response body `status: "created"`)
- 201 Created: duplicate `event_id` (response body `status: "duplicate"`, idempotent)
- 400 Bad Request: database integrity error (e.g., constraint failure)
- 401 Unauthorized: auth required/invalid
- 422 Unprocessable Entity: validation error
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: unexpected database error

**Important:** Both new and duplicate runs return HTTP 201. Check the response body's `status` field to distinguish `"created"` from `"duplicate"`.

Example:
```bash
curl -X POST http://localhost:8765/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"event_id":"550e8400-e29b-41d4-a716-446655440000","run_id":"2026-01-05T18:40:27Z-seo-intelligence-abc123","agent_name":"seo_intelligence.insight_engine","job_type":"insight_generation","start_time":"2026-01-05T18:40:27Z","status":"running"}'
```

Response (new):
```json
{"status": "created", "event_id": "550e8400-e29b-41d4-a716-446655440000", "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123"}
```

Response (duplicate):
```json
{"status": "duplicate", "event_id": "550e8400-e29b-41d4-a716-446655440000", "message": "Event already exists (idempotent)"}
```

### POST /api/v1/runs/batch
Create multiple telemetry runs in one request.

Auth: required if enabled
Rate limit: enforced if enabled

Request body: JSON array of TelemetryRun (no wrapper object)

Status codes:
- 200 OK: returns BatchResponse
- 401 Unauthorized: auth required/invalid
- 422 Unprocessable Entity: validation error
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: unexpected database error

Example:
```bash
curl -X POST http://localhost:8765/api/v1/runs/batch \
  -H "Content-Type: application/json" \
  -d '[{"event_id":"11111111-1111-1111-1111-111111111111","run_id":"run-1","agent_name":"agent-a","job_type":"job-a","start_time":"2026-01-05T18:40:27Z"},{"event_id":"22222222-2222-2222-2222-222222222222","run_id":"run-2","agent_name":"agent-b","job_type":"job-b","start_time":"2026-01-05T18:41:00Z"}]'
```

Response:
```json
{"inserted": 2, "duplicates": 0, "errors": [], "total": 2}
```

### GET /api/v1/runs
Query telemetry runs with filters and pagination.

Auth: not required
Rate limit: enforced if enabled

Query parameters:
- `agent_name` (string, optional): exact match
- `status` (string, optional): one of `running`, `success`, `failure`, `partial`, `timeout`, `cancelled` (aliases also accepted and normalized)
- `job_type` (string, optional): exact match
- `created_before` (string, optional): ISO8601 timestamp (exclusive: `<`)
- `created_after` (string, optional): ISO8601 timestamp (exclusive: `>`)
- `start_time_from` (string, optional): ISO8601 timestamp (inclusive: `>=`)
- `start_time_to` (string, optional): ISO8601 timestamp (inclusive: `<=`)
- `limit` (int, optional): 1-1000, default 100
- `offset` (int, optional): >= 0, default 0

Results are ordered by `created_at DESC` (most recent first).

Status codes:
- 200 OK: returns array of RunRecord
- 400 Bad Request: invalid status or timestamp format
- 422 Unprocessable Entity: invalid limit/offset
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl "http://localhost:8765/api/v1/runs?agent_name=seo_intelligence.scheduler&status=running&limit=50"
```

### GET /api/v1/runs/{event_id}
Fetch a single telemetry run by its event_id (direct lookup).

Auth: not required
Rate limit: enforced if enabled

Path parameters:
- `event_id` (string, required): event identifier

Response: Single RunRecord object (not an array)

Status codes:
- 200 OK: returns RunRecord
- 404 Not Found: event_id not found
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

**Important:** This endpoint returns a single object, not an array. Use this for direct lookups when you know the event_id. Use `GET /api/v1/runs` for queries/filtering.

Example:
```bash
curl http://localhost:8765/api/v1/runs/550e8400-e29b-41d4-a716-446655440000
```

Response:
```json
{
  "id": 123,
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123",
  "agent_name": "seo_intelligence.insight_engine",
  "status": "success",
  "commit_url": "https://github.com/example/repo/commit/abc1234567890",
  "repo_url": "https://github.com/example/repo",
  ...
}
```

### PATCH /api/v1/runs/{event_id}
Update selected fields of an existing run.

Auth: required if enabled
Rate limit: enforced if enabled

Path parameters:
- `event_id` (string, required): event identifier

Request body: RunUpdate

Status codes:
- 200 OK: update applied
- 400 Bad Request: no valid fields to update
- 401 Unauthorized: auth required/invalid
- 404 Not Found: event_id not found
- 422 Unprocessable Entity: validation error (e.g., invalid status, negative numbers)
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl -X PATCH http://localhost:8765/api/v1/runs/550e8400-e29b-41d4-a716-446655440000 \
  -H "Content-Type: application/json" \
  -d '{"status":"success","end_time":"2026-01-05T18:45:10Z","duration_ms":275000}'
```

Response:
```json
{"event_id": "550e8400-e29b-41d4-a716-446655440000", "updated": true, "fields_updated": ["status", "end_time", "duration_ms"]}
```

### GET /api/v1/runs/{event_id}/commit-url
Returns a normalized commit URL for the run (GitHub/GitLab/Bitbucket).

Auth: required if enabled
Rate limit: enforced if enabled

Path parameters:
- `event_id` (string, required): event identifier

Status codes:
- 200 OK: returns `{"commit_url": "<url or null>"}`
- 401 Unauthorized: auth required/invalid
- 404 Not Found: event_id not found
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl http://localhost:8765/api/v1/runs/550e8400-e29b-41d4-a716-446655440000/commit-url
```

### GET /api/v1/runs/{event_id}/repo-url
Returns a normalized repository URL for the run.

Auth: required if enabled
Rate limit: enforced if enabled

Path parameters:
- `event_id` (string, required): event identifier

Status codes:
- 200 OK: returns `{"repo_url": "<url or null>"}`
- 401 Unauthorized: auth required/invalid
- 404 Not Found: event_id not found
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl http://localhost:8765/api/v1/runs/550e8400-e29b-41d4-a716-446655440000/repo-url
```

### POST /api/v1/runs/{event_id}/associate-commit
Associate a git commit with an existing run.

Auth: required if enabled
Rate limit: enforced if enabled

Path parameters:
- `event_id` (string, required): event identifier

Request body: CommitAssociation

Status codes:
- 200 OK: association saved
- 401 Unauthorized: auth required/invalid
- 404 Not Found: event_id not found
- 422 Unprocessable Entity: validation error
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl -X POST http://localhost:8765/api/v1/runs/550e8400-e29b-41d4-a716-446655440000/associate-commit \
  -H "Content-Type: application/json" \
  -d '{"commit_hash":"abc1234567890abcdef","commit_source":"llm","commit_author":"Claude Code <noreply@anthropic.com>","commit_timestamp":"2026-01-02T10:00:00Z"}'
```

Response:
```json
{"status": "success", "event_id": "550e8400-e29b-41d4-a716-446655440000", "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123", "commit_hash": "abc1234567890abcdef"}
```


## Quick Reference Table

| Endpoint | Method | Purpose | Auth | Rate Limit | Idempotent |
|----------|--------|---------|------|------------|------------|
| `/health` | GET | Service health check | No | No | Yes |
| `/metrics` | GET | System usage statistics | No | No | Yes |
| `/api/v1/metadata` | GET | Get distinct agents/jobs | No | Yes | Yes |
| `/api/v1/runs` | POST | Create single run | Yes* | Yes | Yes (event_id) |
| `/api/v1/runs/batch` | POST | Create multiple runs | Yes* | Yes | Yes (event_id) |
| `/api/v1/runs` | GET | Query runs (filter/page) | No | Yes | Yes |
| `/api/v1/runs/{event_id}` | GET | Get single run | No | Yes | Yes |
| `/api/v1/runs/{event_id}` | PATCH | Update run fields | Yes* | Yes | Yes |
| `/api/v1/runs/{event_id}/associate-commit` | POST | Link git commit | Yes* | Yes | Yes |
| `/api/v1/runs/{event_id}/commit-url` | GET | Get commit URL | Yes* | Yes | Yes |
| `/api/v1/runs/{event_id}/repo-url` | GET | Get repo URL | Yes* | Yes | Yes |

*Auth required only if `TELEMETRY_API_AUTH_ENABLED=true` (disabled by default)

## Common Troubleshooting

### 422 Validation Error: "field required"
**Problem:** Missing required fields in POST /api/v1/runs
**Solution:** Ensure these fields are present: `event_id`, `run_id`, `agent_name`, `job_type`, `start_time`

### 422 Validation Error: "Status must be one of..."
**Problem:** Invalid status value on PATCH endpoint
**Solution:** Use canonical statuses only: `running`, `success`, `failure`, `partial`, `timeout`, `cancelled`
**Note:** Aliases `failed`, `completed`, `succeeded` are accepted on POST but **NOT on PATCH**

### 422 Validation Error: "ensure this value has at least 1 characters"
**Problem:** Timestamp missing timezone
**Solution:** Always include timezone: `2026-01-12T10:30:00Z` or `2026-01-12T10:30:00+00:00`

### 404 Not Found
**Problem:** event_id doesn't exist in database
**Solution:**
- Verify event_id was created with POST /api/v1/runs first
- Check for typos in event_id
- Use GET /api/v1/runs to verify the run exists

### 429 Too Many Requests
**Problem:** Exceeded rate limit
**Solution:**
- Wait 60 seconds (see `Retry-After` header)
- Reduce request frequency
- Use batch endpoint for multiple events
- Consider disabling rate limiting in development

### 500 Internal Server Error: "database is locked"
**Problem:** Multiple processes trying to write to database
**Solution:**
- Ensure only ONE API worker is running (`TELEMETRY_API_WORKERS=1`)
- Check for other processes accessing database directly
- Wait and retry (transient lock contention)

### Duplicate event_id returns 201 Created (not error)
**Problem:** This is NOT an error - it's idempotent behavior
**Solution:** This is expected. Check the response body `status` field:
- `"status": "created"` = new run was inserted
- `"status": "duplicate"` = run already exists, no changes made
Both return HTTP 201.

### commit_url or repo_url returns null
**Problem:** Missing git metadata or unsupported platform
**Solution:**
- Ensure `git_repo` and `git_commit_hash` are set
- Supported platforms: GitHub.com, GitLab.com, Bitbucket.org only
- Self-hosted instances return null (expected)

### git_commit_source not saved after POST
**Problem:** `git_commit_source`, `git_commit_author`, `git_commit_timestamp` appear to be ignored on POST
**Solution:** These fields are **accepted** by the POST body schema but are **not persisted** during initial creation. Use one of:
- `PATCH /api/v1/runs/{event_id}` with `git_commit_source`, `git_commit_author`, `git_commit_timestamp`
- `POST /api/v1/runs/{event_id}/associate-commit` with `commit_source`, `commit_author`, `commit_timestamp`

## Advanced Integration Patterns

### Pattern: Context Manager for Run Tracking

```python
from contextlib import contextmanager
import requests
import uuid
from datetime import datetime, timezone

@contextmanager
def telemetry_run(agent_name, job_type, api_url="http://localhost:8765"):
    event_id = str(uuid.uuid4())
    start_time = datetime.now(timezone.utc)

    # Start run
    requests.post(f"{api_url}/api/v1/runs", json={
        "event_id": event_id,
        "run_id": f"{start_time.isoformat()}-{agent_name}-{uuid.uuid4().hex[:8]}",
        "agent_name": agent_name,
        "job_type": job_type,
        "status": "running",
        "start_time": start_time.isoformat()
    })

    try:
        yield event_id
        # Mark success
        requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
            "status": "success",
            "end_time": datetime.now(timezone.utc).isoformat(),
            "duration_ms": int((datetime.now(timezone.utc) - start_time).total_seconds() * 1000)
        })
    except Exception as e:
        # Mark failure
        requests.patch(f"{api_url}/api/v1/runs/{event_id}", json={
            "status": "failure",
            "end_time": datetime.now(timezone.utc).isoformat(),
            "error_summary": str(e)
        })
        raise

# Usage
with telemetry_run("my-agent", "processing") as event_id:
    do_work()
```

### Pattern: Retry with Exponential Backoff

```python
import time
import requests

def post_with_retry(url, json_data, max_retries=3):
    for attempt in range(max_retries):
        try:
            response = requests.post(url, json=json_data, timeout=10)
            response.raise_for_status()
            return response.json()
        except requests.exceptions.RequestException as e:
            if attempt == max_retries - 1:
                # Log but don't crash your agent
                print(f"Telemetry failed after {max_retries} attempts: {e}")
                return None
            time.sleep(2 ** attempt)  # 1s, 2s, 4s
```

### Pattern: Buffered Telemetry Writer

```python
import queue
import threading
import requests

class BufferedTelemetry:
    def __init__(self, api_url, flush_size=50, flush_interval=30):
        self.api_url = api_url
        self.buffer = queue.Queue()
        self.flush_size = flush_size
        self.flush_interval = flush_interval
        self.worker = threading.Thread(target=self._flush_worker, daemon=True)
        self.worker.start()

    def add(self, run_data):
        self.buffer.put(run_data)
        if self.buffer.qsize() >= self.flush_size:
            self._flush()

    def _flush(self):
        events = []
        while not self.buffer.empty() and len(events) < self.flush_size:
            try:
                events.append(self.buffer.get_nowait())
            except queue.Empty:
                break

        if events:
            try:
                requests.post(f"{self.api_url}/api/v1/runs/batch", json=events)
            except Exception as e:
                print(f"Batch upload failed: {e}")
                # Re-queue failed events
                for event in events:
                    self.buffer.put(event)

    def _flush_worker(self):
        while True:
            time.sleep(self.flush_interval)
            self._flush()
```

## See Also

- **Detailed Endpoint Specs:** [specs/features/](../../specs/features/)
- **System Architecture:** [specs/_index.md](../../specs/_index.md)
- **Deployment Guide:** [docs/DEPLOYMENT_GUIDE.md](../DEPLOYMENT_GUIDE.md)
- **Python Client SDK:** Use `TelemetryClient` from `src/telemetry/client.py` for automatic buffer failover and retry logic
