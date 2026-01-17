# Telemetry API HTTP Reference

**Quick Start:** This document is the complete reference for integrating with the Local Telemetry Platform HTTP API. Use this when implementing agents or services that need to track telemetry data.

**Version:** 2.2.0
**Last Updated:** 2026-01-15
**Detailed Specs:** See [specs/features/](../../specs/features/) for endpoint-specific implementation details

## Service
- **Name:** local-telemetry-api
- **Version:** 2.2.0
- **Container:** local-telemetry-api
- **Image:** local-telemetry-api:2.2.0
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

**Status Aliases** (automatically normalized):
- `failed` → `failure`
- `completed` → `success`
- `succeeded` → `success`

**Implementation Note:** You can use either canonical or alias values in requests. The API automatically normalizes them before storage and query filtering. This ensures backward compatibility with legacy systems.

### Idempotency via event_id

**Critical:** Always generate unique `event_id` values (UUIDs recommended). The API uses `event_id` as the idempotency key:
- Duplicate `event_id` POST requests return 200 OK with `status: "duplicate"` (not an error)
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
     "git_commit_source": "llm"
   }
   ```

2. **Associate after run** (if commit created later):
   ```bash
   POST /api/v1/runs/{event_id}/associate-commit
   {"commit_hash": "abc123", "commit_source": "llm"}
   ```

**commit_source values:**
- `manual` - Human-created commit
- `llm` - LLM-generated commit (e.g., Claude Code, Cursor, Copilot)
- `ci` - CI/CD pipeline commit

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
  "git_commit_source": "llm",
  "git_commit_author": "Claude <noreply@anthropic.com>",
  "git_commit_timestamp": "2026-01-05T18:40:27Z",
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
- `git_commit_source`, `git_commit_author`, `git_commit_timestamp` are accepted on POST but are only persisted when updated via PATCH or associate-commit.

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
- `status` must be one of `running`, `success`, `failure`, `partial`, `timeout`, `cancelled`.
- `duration_ms`, `items_succeeded`, `items_failed`, `items_skipped` must be non-negative.
- Fields explicitly set to `null` are ignored (cannot be cleared to null).

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

### RunRecord (response item for GET /api/v1/runs)
```json
{
  "id": 123,
  "event_id": "550e8400-e29b-41d4-a716-446655440000",
  "run_id": "2026-01-05T18:40:27Z-seo-intelligence-abc123",
  "created_at": "2026-01-05T18:40:27.000000+00:00",
  "start_time": "2026-01-05T18:40:27.000000+00:00",
  "end_time": "2026-01-05T18:45:10.000000+00:00",
  "agent_name": "seo_intelligence.insight_engine",
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
- `commit_url` and `repo_url` are derived fields.

### BatchResponse (response body for POST /api/v1/runs/batch)
```json
{
  "inserted": 3,
  "duplicates": 1,
  "errors": [],
  "total": 4
}
```

### HealthResponse (GET /health)
```json
{
  "status": "ok",
  "version": "2.1.0",
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
- 201 Created: new run created
- 200 OK: duplicate `event_id` (idempotent)
- 400 Bad Request: database integrity error (e.g., constraint failure)
- 401 Unauthorized: auth required/invalid
- 422 Unprocessable Entity: validation error
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: unexpected database error

Example:
```bash
curl -X POST http://localhost:8765/api/v1/runs \
  -H "Content-Type: application/json" \
  -d '{"event_id":"550e8400-e29b-41d4-a716-446655440000","run_id":"2026-01-05T18:40:27Z-seo-intelligence-abc123","agent_name":"seo_intelligence.insight_engine","job_type":"insight_generation","start_time":"2026-01-05T18:40:27Z","status":"running"}'
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

### GET /api/v1/runs
Query telemetry runs with filters and pagination.

Auth: not required
Rate limit: enforced if enabled

Query parameters:
- `agent_name` (string, optional): exact match
- `status` (string, optional): one of `running`, `success`, `failure`, `partial`, `timeout`, `cancelled`
- `job_type` (string, optional): exact match
- `created_before` (string, optional): ISO8601 timestamp
- `created_after` (string, optional): ISO8601 timestamp
- `start_time_from` (string, optional): ISO8601 timestamp
- `start_time_to` (string, optional): ISO8601 timestamp
- `limit` (int, optional): 1-1000, default 100
- `offset` (int, optional): >= 0, default 0

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
- 422 Unprocessable Entity: validation error
- 429 Too Many Requests: rate limit exceeded
- 500 Internal Server Error: database errors

Example:
```bash
curl -X PATCH http://localhost:8765/api/v1/runs/550e8400-e29b-41d4-a716-446655440000 \
  -H "Content-Type: application/json" \
  -d '{"status":"success","end_time":"2026-01-05T18:45:10Z","duration_ms":275000}'
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
**Problem:** Invalid status value  
**Solution:** Use canonical statuses: `running`, `success`, `failure`, `partial`, `timeout`, `cancelled`  
**Note:** Aliases `failed`, `completed`, `succeeded` are also accepted

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

### Duplicate event_id returns 200 OK (not error)
**Problem:** This is NOT an error - it's idempotent behavior  
**Solution:** This is expected. Check response `status` field:
- `"status": "created"` = new run
- `"status": "duplicate"` = already exists

### commit_url or repo_url returns null
**Problem:** Missing git metadata or unsupported platform  
**Solution:**
- Ensure `git_repo` and `git_commit_hash` are set
- Supported platforms: GitHub.com, GitLab.com, Bitbucket.org only
- Self-hosted instances return null (expected)

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

