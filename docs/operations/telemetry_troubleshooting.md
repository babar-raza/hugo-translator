# Telemetry Troubleshooting Guide

**Audience**: On-call engineers, SRE team
**Last Updated**: 2025-12-22
**Related**: PR-04, TI-01, TI-02

---

## Quick Reference

| Issue | Metric/Log | Investigation Priority |
|-------|-----------|----------------------|
| HTTP 422 errors from telemetry API | Search logs for "422" | P1 - Immediate |
| High fallback rate | `telemetry_duration_fallback` | P2 - Within 24h |
| Missing duration data | Search "Duration fallback" | P3 - Backlog |

---

## HTTP 422 Errors: duration_ms field is null

### Symptom

Telemetry API returns validation errors in logs:

```
API HTTP error 422: {"detail":[{"type":"int_type","loc":["body","duration_ms"],
"msg":"Input should be a valid integer","input":null}]}
```

### Root Cause

The `TranslationStats.duration_seconds` field can be None or invalid type when:
- Stats object not properly initialized in error paths
- Translation fails before duration is set
- Race conditions in multi-threaded translation
- Stats object is None (edge case in error handling)

### Resolution

**PR-04 Implementation (2025-12-22)**:
Defensive handling added in `_safe_duration_ms()` helper to ensure `duration_ms` is always integer.

**Code Location**: [src/observability/telemetry_integration.py:273-337](../../src/observability/telemetry_integration.py)

**Fallback Behavior**:
1. If stats is None → `duration_ms = 0`, emit metric with `reason:none_stats`
2. If `duration_seconds` is None → `duration_ms = 0`, emit metric with `reason:none_duration`
3. If `duration_seconds` invalid type → `duration_ms = 0`, emit metric with `reason:invalid_type`
4. If `duration_seconds = 0.0` → `duration_ms = 0` (legitimate, no metric)

**What Changed**:
- Before: Could pass `null` to API, causing 422 errors
- After: Always passes valid integer (0 or calculated value)

### Monitoring

**TI-01 Observability (2025-12-22)**:

**Metrics**:
- **Name**: `telemetry_duration_fallback`
- **Type**: Counter
- **Labels**: `reason` (none_stats | none_duration | invalid_type)

**Alert Thresholds**:
- **P2 Alert**: > 100 fallbacks/hour for 10 minutes (investigate within 24h)
- **P1 Alert**: > 1000 fallbacks/hour for 5 minutes (investigate immediately)
- **Target SLA**: < 0.1% of total translations should use fallback

**Logs**:
Search for: `"Duration fallback"` with structured logging context

Example log entry:
```json
{
  "level": "WARNING",
  "message": "Duration fallback: duration_seconds is None",
  "extra": {
    "context": "translate_file",
    "reason": "none_duration"
  }
}
```

### Dashboards

**Recommended Grafana Panels**:

1. **Fallback Rate Over Time** (Line Chart):
   ```promql
   sum(rate(telemetry_duration_fallback[5m])) * 60
   ```
   Y-axis: Fallbacks per minute

2. **Fallback Reason Breakdown** (Pie Chart):
   ```promql
   sum by (reason) (telemetry_duration_fallback)
   ```

3. **Fallback Percentage of Total Translations** (Gauge):
   ```promql
   (sum(telemetry_duration_fallback) / sum(translations_total)) * 100
   ```
   Target: < 0.1%

4. **Recent Fallback Logs** (Logs Panel):
   ```
   {job="translation-worker"} |= "Duration fallback"
   ```

---

## Investigation Steps

### 1. Check Current Fallback Rate

**Query metrics for last 24 hours**:
```bash
# Prometheus query
curl -G 'http://prometheus:9090/api/v1/query' \
  --data-urlencode 'query=sum by (reason) (rate(telemetry_duration_fallback[24h]))'

# Or via Grafana dashboard (preferred)
# Navigate to: Dashboards → Translation System → Telemetry Health
```

**Expected Result**:
- Fallback rate < 0.1% of total translations
- If > 1%, proceed to step 2

### 2. Search Logs for Context

**Find recent fallback occurrences**:
```bash
# Local development
grep -r "Duration fallback" logs/*.log | tail -20

# Kubernetes
kubectl logs -l app=translation-worker --tail=1000 | grep "Duration fallback"

# Loki (if using Grafana Loki)
logcli query '{job="translation-worker"} |= "Duration fallback"' --limit=100 --since=24h
```

**What to look for**:
- `context` field: Which function triggered fallback (translate_file, translate_directory, track_translation_stats)
- `reason` field: Why fallback occurred (none_stats, none_duration, invalid_type)
- Timestamp pattern: Is it sporadic or continuous?
- Correlation: Does it happen with specific files or languages?

### 3. Correlate with Translation Errors

**Check if fallbacks correlate with translation failures**:
```bash
# Count translation errors in same time window
grep "Translation failed" logs/*.log | wc -l

# Check for specific error patterns
grep -E "(Translation failed|Duration fallback)" logs/*.log | sort | less
```

**Analysis**:
- If fallbacks == errors: Likely caused by error paths not setting duration
- If fallbacks < errors: Some error paths properly handle duration
- If fallbacks > errors: Race condition or initialization issue

### 4. Identify Affected Files/Languages

**Extract file paths from fallback logs**:
```bash
# Parse structured logs for context
cat logs/*.log | jq 'select(.message | contains("Duration fallback")) | .extra.context' | sort | uniq -c | sort -rn

# Look for patterns
# - Specific languages? (e.g., all fallbacks for zh-CN)
# - Specific file types? (e.g., large files > 10MB)
# - Specific sites? (e.g., kb.aspose.net)
```

### 5. Root Cause Analysis

**Based on reason label**:

**If `reason:none_stats`**:
- **Cause**: Stats object never created or exception thrown before stats initialization
- **Investigation**:
  - Check error paths in `translate_file()` and `translate_directory()`
  - Look for `try/except` blocks that return early without creating stats
  - Search code: `grep -r "return.*Result" src/translation_engine/engine.py`
- **Fix Priority**: P1 (data loss issue)

**If `reason:none_duration`**:
- **Cause**: Stats object created but `duration_seconds` field not set
- **Investigation**:
  - Check where `duration_seconds` should be set: `grep -r "duration_seconds" src/`
  - Look for code paths that create `TranslationStats()` without setting duration
  - Check if timer is started but never stopped
- **Fix Priority**: P2 (timing data missing)

**If `reason:invalid_type`**:
- **Cause**: Type coercion error, wrong data type assigned
- **Investigation**:
  - Check for string-to-float conversions
  - Look for serialization/deserialization issues (pickle, JSON)
  - Check if duration is being read from config/environment variable
- **Fix Priority**: P2 (data corruption issue)

### 6. Escalation Paths

**Escalation Matrix**:

| Fallback Rate | Priority | Action | Timeline |
|---------------|----------|--------|----------|
| < 0.1% | P3 | Log for future analysis | Backlog |
| 0.1% - 1% | P2 | Create bug ticket, investigate | Within 24h |
| 1% - 10% | P1 | Investigate immediately, hotfix | Within 4h |
| > 10% | P0 | Emergency, all hands on deck | Immediate |

**If 422 errors still occurring after PR-04**:
- **Priority**: P0 - Critical bug, defensive handling failed
- **Action**:
  1. Check if `_safe_duration_ms()` is being called (not bypassed)
  2. Verify imports are correct: `from ..observability.telemetry_integration import _safe_duration_ms`
  3. Check for code paths that directly calculate `duration_ms` (should be none)
  4. Emergency hotfix: Disable telemetry until fixed

**Contact Info**:
- **On-call Engineer**: Page via PagerDuty "Translation System - Telemetry"
- **Escalation**: @sre-team on Slack #translation-ops
- **Code Owner**: @backend-team (see CODEOWNERS file)

---

## Prevention Strategies

### For Developers

**When creating TranslationStats objects**:
1. Always initialize with `duration_seconds=0.0` if not yet known
2. Set `duration_seconds` before returning stats from translation functions
3. Use timer pattern:
   ```python
   start_time = time.time()
   # ... do work ...
   stats.duration_seconds = time.time() - start_time
   ```
4. In error paths, still set duration:
   ```python
   try:
       start_time = time.time()
       # ... translation work ...
       stats.duration_seconds = time.time() - start_time
   except Exception as e:
       stats.duration_seconds = time.time() - start_time  # Still set!
       raise
   ```

**Code Review Checklist**:
- [ ] All `TranslationStats()` creations set `duration_seconds`
- [ ] Error paths set duration before returning
- [ ] Timer started before work, stopped after (even in exceptions)
- [ ] Type hints present: `duration_seconds: float`

**Testing**:
- Add unit test for error path: `test_stats_has_duration_on_error()`
- Verify stats in integration tests
- Check telemetry metrics in E2E tests

### For SREs

**Monitoring Setup**:
1. Create Grafana dashboard with panels listed above
2. Set up alerts in AlertManager:
   ```yaml
   - alert: TelemetryFallbackHigh
     expr: sum(rate(telemetry_duration_fallback[5m])) > 100
     for: 10m
     labels:
       severity: warning
     annotations:
       summary: "High telemetry duration fallback rate"
   ```
3. Configure on-call rotation in PagerDuty
4. Set up log aggregation for "Duration fallback" messages

**Runbook Links**:
- [Telemetry System Architecture](./telemetry_architecture.md) (TODO)
- [Translation Engine Debugging](./translation_debugging.md) (TODO)
- [Production Incident Response](./incident_response.md) (TODO)

---

## Common Patterns and Solutions

### Pattern 1: Fallbacks Spike After Deployment

**Symptom**: Sudden increase in fallbacks after code deployment

**Investigation**:
1. Check recent commits: `git log --since="1 day ago" --oneline`
2. Look for changes to `TranslationStats`, `TranslationResult`, or `engine.py`
3. Check if new error paths were added without setting duration

**Solution**:
- Rollback deployment if > 10% fallback rate
- Fix error paths to set duration
- Add unit tests for new error paths
- Redeploy with fix

### Pattern 2: Intermittent Fallbacks for Specific Language

**Symptom**: Fallbacks only occur for one language (e.g., zh-CN)

**Investigation**:
1. Check if language-specific model loading fails
2. Look for timeouts during translation
3. Check if language has special characters causing issues

**Solution**:
- Add try-catch around language-specific code
- Increase timeout for problematic languages
- Add language-specific unit tests

### Pattern 3: Fallbacks Only in Multi-threaded Mode

**Symptom**: Fallbacks occur in `parallel` mode but not `sequential`

**Investigation**:
1. Check for race conditions in stats aggregation
2. Look for shared state between threads
3. Check if timer is thread-local

**Solution**:
- Use thread-local storage for timers
- Add locks around stats aggregation
- Consider using `threading.Timer` for more reliable timing

---

## Appendix: Useful Commands

### Check Telemetry System Health

```bash
# Check if telemetry API is reachable
curl -f https://telemetry-api.example.com/health || echo "API down"

# Check telemetry buffer status
ls -lh telemetry_buffer/*.json | wc -l  # Should be < 100

# Check for stuck telemetry workers
ps aux | grep telemetry_worker
```

### Extract Fallback Statistics

```bash
# Count fallbacks by reason (from logs)
grep "Duration fallback" logs/*.log | grep -o 'reason=[^,}]*' | sort | uniq -c

# Average fallback rate per hour
grep "Duration fallback" logs/*.log | awk '{print $1" "$2}' | cut -c1-13 | uniq -c

# Find files that trigger fallbacks
grep "Duration fallback" logs/*.log | grep -o 'context=[^,}]*' | sort | uniq -c | sort -rn | head -20
```

### Test Telemetry Locally

```bash
# Run translation with telemetry enabled
export TELEMETRY_API_URL="http://localhost:8080"
./venv/Scripts/python.exe -m src.cli \
  --site kb.aspose.net \
  --input tests/fixtures/test.md \
  --target-langs de \
  --model m2m100_418m

# Check if fallback occurred
grep "Duration fallback" logs/*.log

# Check metrics emitted
curl http://localhost:9090/metrics | grep telemetry_duration_fallback
```

---

## Related Documentation

- **Implementation**: [TI-01 Completion Summary](../../TI-01_COMPLETION_SUMMARY.md)
- **Code**: [telemetry_integration.py](../../src/observability/telemetry_integration.py)
- **Tests**: [test_telemetry_observability.py](../../tests/unit/test_telemetry_observability.py)
- **Original Fix**: [PR-04 Implementation](../../SESSION_PROGRESS_CONTINUE.md#-pr-04-telemetry-api-422-error-fix)

---

## Changelog

| Date | Change | Author |
|------|--------|--------|
| 2025-12-22 | Initial version (TI-02) | Claude (AI Assistant) |
| 2025-12-22 | Added TI-01 metrics documentation | Claude (AI Assistant) |

---

## Feedback

If you encounter issues not covered in this guide:
1. Update this document with the new pattern
2. File a bug report: [GitHub Issues](https://github.com/your-org/hugo-translator/issues)
3. Notify @sre-team in Slack #translation-ops
