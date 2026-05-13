# Agent Metrics API Integration

**Last Updated**: 2026-05-13
**Version**: 1.1
**Target Audience**: Engineers, Operators, SREs
**Status**: Dry-run and controlled-test verified. NOT production-enabled.

## Overview

The Agent Metrics API posts per-run translation metrics to a shared Google Sheet. Each worker run that processes a content root produces one row with 17 fields covering agent identity, scope (product, platform, website), item counts, and LLM token usage.

This enables cross-agent visibility into what hugo-translator is doing across sites, products, and time periods.

**Key characteristics:**
- Profile-driven: scope is derived from site profile configuration, not hardcoded
- Append-only: the Google Sheet is write-only production infrastructure (no update/delete)
- Safe defaults: `enabled: false`, `dry_run: true` — must be explicitly activated
- Non-blocking: metrics failures never crash translation workers

## Quick Reference

| Setting | Default | Override |
|---------|---------|----------|
| enabled | `false` | `config/global.yaml` → `agent_metrics.enabled` |
| dry_run | `true` | `config/global.yaml` → `agent_metrics.dry_run` |
| endpoint | (env var) | `AGENT_METRICS_ENDPOINT` |
| token | (env var) | `AGENT_METRICS_TOKEN` |
| test row cap | 3/sprint | `agent_metrics.max_test_rows_per_sprint` |
| evidence dir | `data/metrics/agent_evidence` | `agent_metrics.evidence_dir` |

## Safety Model

The Google Sheet is append-only production infrastructure. Every POST is permanent. There is no undo.

**Safeguards:**
- `enabled: false` by default — integration is entirely skipped unless explicitly enabled
- `dry_run: true` by default — payloads are logged but never POSTed
- Test row cap: maximum 3 rows per sprint with `job_type="test"`
- Test `item_name` must start with `"test "` to distinguish from production rows
- After test posts, `dry_run` must be restored to `true`
- Production enablement (Stage 9) requires separate approval and is NOT part of this sprint
- Stages 9-10 are deferred

## Secret Handling

- `AGENT_METRICS_ENDPOINT` and `AGENT_METRICS_TOKEN` are read from environment variables only
- `config/global.yaml` stores the env var **names** (`endpoint_env`, `token_env`), never values
- `.env.example` contains commented placeholder examples for documentation
- `.env` is gitignored and must never be committed
- Placeholder values like `"YOUR_TOKEN_HERE"`, `"changeme"` are detected and rejected at startup
- If either env var is missing when `enabled: true`, posting is disabled with a warning — the worker continues normally
- Secret scan required before every commit: no token values in source, config, docs, or evidence

## Payload Schema — Exact 17 Fields

The posted JSON contains exactly these 17 keys. No extra keys are sent.

| # | Field | Type | Source | Notes |
|---|-------|------|--------|-------|
| 1 | `timestamp` | string | `make_timestamp()` | ISO 8601 with UTC timezone |
| 2 | `agent_name` | string | constant | Always `"Hugo Translator"` (see Breaking Changes below) |
| 3 | `agent_owner` | string | constant | Always `"Babar Raza"` |
| 4 | `job_type` | string | worker context | `Content Translation`, `TM Improvement`, `Test` (Title Case) |
| 5 | `run_id` | string | `segment_run_id` | UUID5 identifying this specific run |
| 6 | `status` | string | `determine_status()` | `success`, `partial_success`, `failure` only |
| 7 | `product` | string | ScopeResolver | e.g., `Aspose.Words`, `Aspose.Total` |
| 8 | `platform` | string | ScopeResolver | e.g., `.NET`, `Java`, `All` |
| 9 | `website` | string | ScopeResolver | Source domain pass-through, e.g., `aspose.net` |
| 10 | `website_section` | string | ScopeResolver | `Docs`, `KB`, `Blog`, `Product Pages`, etc. |
| 11 | `item_name` | string | `_build_item_name()` | e.g., `Translated Words Docs — 5 files` |
| 12 | `items_discovered` | int | worker counts | Files selected for processing |
| 13 | `items_failed` | int | worker counts | Files that failed |
| 14 | `items_succeeded` | int | worker counts | Files successfully processed |
| 15 | `run_duration_ms` | int | wall clock | Milliseconds elapsed |
| 16 | `token_usage` | int | LLMRunContext | Total tokens (input + output) from completed calls |
| 17 | `api_calls_count` | int | LLMRunContext | Total attempted LLM provider calls |

**Validation rules:**
- `items_succeeded + items_failed <= items_discovered`
- `token_usage >= 0` and `api_calls_count >= 0`
- If `api_calls_count > 0` and not all calls failed, then `token_usage > 0`
- If `api_calls_count == 0`, then `token_usage == 0`
- `status` must be one of: `success`, `partial_success`, `failure`
- `"error"` is NOT a posted status. Exceptions map to `failure` with details in evidence only.
- `run_id` must be a valid UUID string
- `website` and `item_name` must not be empty

## Evidence-Only Fields

These fields are written to local evidence sidecars but are NOT posted to the Google Sheet:

- `stable_work_slice_id` — logical work identity (for grouping attempts)
- `execution_attempt_id` — per-invocation identity
- `parent_run_id` — worker process trace
- `site_id` — exact profile identity (e.g., `docs.aspose.net`)
- `source_site_domain` — domain before normalization (e.g., `aspose.net`)
- `content_root_id` — repo-relative content root
- `content_root_raw` — original env-var path from profile
- `locale_grain` — always `"all"` in v1
- `per_locale_breakdown` — per-locale item counts (no per-locale tokens)
- `provider_name` — LLM provider type (e.g., `openai_compatible`)
- `endpoint_host` — LLM endpoint host
- `model_name` — model identifier
- `is_professionalize` — whether endpoint is llm.professionalize.com
- `reporting_confidence` — `high`, `medium`, `low`
- `trigger_type` — `scheduled`, `manual`, `ci`
- `output_summary` — human-readable one-liner
- `error_detail` — exception info when status=failure
- `scope_warnings` — any scope resolution warnings
- `detection_method` — which cascade level resolved scope
- `fallback_used` — any field used Level 4 fallback
- GitLab CI context — pipeline/job IDs, commit SHA
- `call_accounting` — attempted/completed/failed/local_failure breakdowns
- `payload_hash` — SHA-256 of posted JSON
- `posting.status` — `posted`, `dry_run`, `failed`, `skipped_duplicate`

## ScopeResolver

All scope dimensions are **derived** from profile configuration. No hardcoded scope values exist.

### Priority Cascade (first match wins per field)

1. **CLI overrides** — `--metrics-website`, env vars like `HUGO_METRICS_PRODUCT_FAMILY`
2. **Profile `metrics_hints` block** — optional explicit overrides in site profile YAML
3. **Profile field derivation** — site_id parsing, content_root path, filename, display_name, mapping tables
4. **Controlled fallback** — brand Total, platform "all", `fallback_used: true`, lower `reporting_confidence`

### Configurable Mappings

All mappings are in `config/global.yaml` under `agent_metrics`:

- `metrics_website_mapping` — domain normalization (empty by default = pass-through)
- `metrics_section_mapping` — subsystem to section name (e.g., `docs` → `Docs`)
- `metrics_brand_mapping` — domain to brand (e.g., `aspose.com` → `Aspose`)
- Product display mapping — family token to display name (e.g., `3d` → `Aspose.3D`)
- Platform display mapping — platform token to display name (e.g., `net` → `.NET`)
- `known_product_families` — recognized family tokens
- `known_platforms` — recognized platform tokens

### content_root_id

Derived from `content_root_raw` by stripping env-var prefix and normalizing to forward-slash:
- Input: `${ASPOSE_NET_CONTENT}\docs.aspose.net\words` or `${ASPOSE_NET_CONTENT}/docs.aspose.net/words`
- Output: `docs.aspose.net/words` (identical regardless of OS path style)

### Mixed/Total Handling

- Profiles without a specific product family (e.g., `blog.aspose.net`) → `product = "Aspose.Total"`, `reporting_confidence = "medium"`
- TM worker with mixed candidates → `product = "Mixed"`, `reporting_confidence = "low"`

### Locale Grain

In v1, `locale_grain` is always `"all"`. Per-locale token accounting is not available. Per-locale item counts are in evidence only.

## Scope Audit Gate

The scope audit validates that all production profiles resolve to non-ambiguous scope values.

**Command:**
```bash
python -m src.observability.metrics_scope --audit
```

**Output:** `data/metrics/scope_audit.json`

**Classifications:**

| Classification | Meaning | Gate Action |
|---------------|---------|-------------|
| `exact` | All fields derived without fallback | Pass |
| `mixed_accepted` | Content genuinely spans families; documented | Pass |
| `fallback_accepted` | Fallback used but explicitly accepted | Pass |
| `fixture_excluded` | Test/fixture profile; excluded from posting | Pass |
| `ambiguous` | Fallback used, no justification | **BLOCKS** |

Any `ambiguous` production profile blocks worker integration and production enablement.

## LLM Accounting

Token usage and API call counts are tracked via `LLMRunContext`, which uses Python's `contextvars.ContextVar` for per-run isolation.

**Counters:**
- `attempted_provider_calls` — every `generate()` entry
- `completed_provider_calls` — successful returns
- `failed_provider_calls` — exceptions from `_generate_impl()`
- `local_failure_calls` — local pre-check failures

**Posted values:**
- `api_calls_count` = `attempted_provider_calls`
- `token_usage` = sum of input + output tokens from **completed** calls only

Failed calls are counted as attempts but do not contribute tokens. The checkpoint/delta pattern allows per-content-root accounting within a single worker run.

Thread-safe via `threading.Lock` on all counter modifications.

**No per-locale token claims in v1.** Token usage is reported at the content_root level only.

## LLM Provider Evidence

Every evidence sidecar includes an `llm_provider` block:

```json
{
  "provider_name": "openai_compatible",
  "model_name": "recommended",
  "endpoint_host": "llm.professionalize.com",
  "is_professionalize": true
}
```

- `is_professionalize` is determined by checking if `endpoint_host` contains `"professionalize.com"`
- Non-professionalize providers are recorded truthfully — no false labeling
- API keys are never included in evidence

## Evidence and Ledger

### Sidecar Files

Path: `data/metrics/agent_evidence/{YYYY-MM-DD}/{segment_run_id}.json`

Schema version: 2. Contains full metadata including IDs, execution context, scope, provider info, posted payload, call accounting, items detail, and posting status.

### Lifecycle

1. **Pre-post sidecar** written before POST with `posting.status = "posting_in_progress"`
2. On success: updated to `"posted"`, marker written, ledger appended
3. On failure: updated to `"failed"`, no marker
4. On crash before update: sidecar remains `"posting_in_progress"` (detected by TC-METRICS-13)

### Posted Markers

Path: `data/metrics/agent_evidence/markers/{segment_run_id}.posted`

Before POST, check marker — skip if exists (duplicate suppression). After POST success, write marker.

### JSONL Ledger

Path: `data/metrics/agent_evidence/metrics_ledger.jsonl`

Events: `pre_post`, `post_confirmed`, `post_failed`, `skipped_duplicate`.

### OneDrive Safety

All file writes use `ThreadPoolExecutor` with 10-second timeout to prevent OneDrive sync lock hangs.

## Worker Integration

### Content Translation Worker

File: `src/workers/autonomous_content_translation_worker.py`

- `MetricsRunContext.start()` before each content_root translation (~line 884)
- `MetricsRunContext.finish()` after coverage telemetry (~line 1137)
- `MetricsRunContext.abort(error_detail)` called on two early-exit paths:
  - Run deadline exceeded before translation started (~line 923)
  - `finish()` itself raises an exception (~line 1160)
- Wrapped in try/except — errors logged at debug level, never crash the worker

**Failure sidecar guarantee:** If the process completes (even partially), `finish()` or `abort()` will always produce a sidecar. If the process is killed externally (SIGKILL), no sidecar is written — this is a documented limitation (see Deferred Work: TC-METRICS-13).

### TM Improvement Worker

File: `src/workers/tm_improvement_worker.py`

- Same pattern in `_execute_improvement_run_with_telemetry()` (~line 825)
- `job_type="tm_improvement"`

### Safety Properties

- Lazy import: `MetricsRunContext` is imported inside try blocks
- Non-blocking: all exceptions caught and suppressed
- Fixture/test profiles (matching `excluded_site_id_prefixes`) are excluded from posting
- If `enabled: false` or secrets missing, all calls are no-ops

### Repeated Feedback Guard (Translation Engine)

The translation engine (`src/translation_engine/engine.py`) includes a guard against futile LLM correction loops.

If the same error validator fires on **two consecutive retries**, the file is failed immediately without exhausting all `max_retry_attempts`. This addresses cases where the LLM generates incorrect output (e.g., Arabic script when translating to Danish) and cannot self-correct — the guard detects the pattern and cuts the loop early, saving API calls.

The guard tracks `_prev_retry_validators: frozenset | None` across retries per file. It triggers only when:
- Same set of `(validator_name, "error")` tuples on consecutive retries
- Current set is non-empty (warnings-only failures are not guarded)
- Not the first retry (no prior state to compare against)

When triggered, a `TranslationRejectedError` is raised — the file is marked as failed and the worker moves on to the next file. The error is counted in `items_failed` for the metrics sidecar.

## Testing and Verification

### Unit Tests

```bash
pytest tests/unit/observability/ -v
```

Covers: llm_run_context (18), metrics_scope (28), agent_metrics_payload (21), metrics_evidence (18), idempotency (9), agent_metrics_poster (14), gitlab_context (5), metrics_run_context_abort (7), repeated_feedback_guard (8) — **128 tests total**.

### Integration Tests

```bash
pytest tests/integration/test_dry_run_matrix.py tests/integration/test_provider_instrumentation.py tests/integration/test_scope_audit_gate.py tests/integration/test_id_stability.py tests/integration/test_payload_schema.py -v
```

Covers: dry-run matrix M1-M15 (16), provider instrumentation (5), scope audit gate (3), ID stability (2), payload schema (2) — **28 tests total**.

### Scope Audit

```bash
python -m src.observability.metrics_scope --audit
```

Produces `data/metrics/scope_audit.json`. Verify no `ambiguous` classifications for production profiles.

### Secret Safety Scan

Before every commit, verify no real tokens are present:
```bash
grep -r "AGENT_METRICS_TOKEN" --include="*.py" --include="*.yaml" --include="*.md"
# Should only show env var NAME references, never values
```

### Dry-Run Verification

Set `enabled: true`, `dry_run: true` in `global.yaml`, run a worker in oneshot mode, then inspect `data/metrics/agent_evidence/` for sidecar files. Verify payload has exactly 17 keys.

## Deferred Work

None of the deferred items block content worker production enablement. TC-METRICS-15 blocks TM worker production.

| Taskcard | Description | Status | Blocks Production? |
|----------|-------------|--------|--------------------|
| TC-METRICS-12 | Per-locale token tracking | Deferred | No — content_root-level `locale_grain="all"` is correct for v1 |
| TC-METRICS-13 | Failed post backfill (orphan sidecar scan + retry) | Deferred | No for pilot; recommended before broad rollout |
| TC-METRICS-14 | Persistent CI ledger | Deferred | No — production runs on local Windows with persistent workspace |
| TC-METRICS-15 | TM queue family metadata | Deferred | Yes — blocks TM worker production (hardcoded `site_id="tm_improvement"`) |
| Stage 9 | Content worker production (`enabled: true`, `dry_run: false`) | Requires separate approval | Ready for controlled pilot |
| Stage 10 | TM worker production | Requires TC-METRICS-15 or explicit "Mixed" acceptance | Blocked by TC-METRICS-15 |

## Breaking Changes

### v1.1 (2026-05-13): agent_name, job_type, website, item_name

The following field values changed between the initial production pilot (2026-05-07) and v1.1:

| Field | Legacy (3 rows in sheet) | Current (v1.1+) | Reason |
|-------|-------------------------|------------------|--------|
| `agent_name` | `"hugo-translator"` | `"Hugo Translator"` | Title Case normalization (commit d8c71b5) |
| `job_type` | `"content_translation"` | `"Content Translation"` | Title Case normalization |
| `website` | `"aspose.com"` (cross-mapped) | `"aspose.net"` (pass-through) | Website mapping changed to pass-through |
| `item_name` | `"docs.aspose.net/words content_translation"` | `"Translated Words Docs — 1 file"` | `_build_item_name()` wired in |

The 3 legacy rows (2 test + 1 production) cannot be corrected (append-only sheet). When filtering, use both old and new values or filter by `run_id` date range.

## Test Row Identification

Test rows are identified by `job_type="Test"`, NOT by the `status` field. The `status` field always reflects the actual outcome of the run (`success`, `partial_success`, or `failure`), even for test runs. This design ensures test rows exercise the same status derivation logic as production rows.

To filter test rows in the sheet: `job_type = "Test"`.

## Source of Truth

| Component | File |
|-----------|------|
| Payload model | `src/observability/agent_metrics_payload.py` |
| ScopeResolver | `src/observability/metrics_scope.py` |
| LLM accounting | `src/observability/llm_run_context.py` |
| Evidence/ledger | `src/observability/metrics_evidence.py` |
| HTTP poster | `src/observability/agent_metrics_poster.py` |
| Integration glue | `src/observability/agent_metrics_integration.py` |
| GitLab context | `src/observability/gitlab_context.py` |
| Config section | `config/global.yaml` lines 747-848 |
| Env vars | `.env.example` lines 121-124 |

---

**Version**: 1.1 | **Last Updated**: 2026-05-13
