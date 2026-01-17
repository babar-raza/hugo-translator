# TODO/FIXME Items - Technical Debt Inventory

**Generated**: 2026-01-17
**Agent**: Agent-C (Testing & Validation)
**Task**: PROD-006
**Status**: DOCUMENTED

---

## Summary

**Total Items**: 3
**Priority**: LOW (none blocking production deployment)
**Estimated Effort**: 2-4 hours total

---

## Item 1: Subprocess Statistics Return

**File**: `src/cli.py:1857`
**Code Context**:
```python
# TODO: Enhance subprocess to return stats via file/stdout
```

**Description**:
When running multi-language translations in subprocess mode (one subprocess per language), the parent process currently does not aggregate statistics from child processes. Each subprocess runs independently and logs its own stats.

**Impact**:
- **User Experience**: Users don't see aggregated statistics for multi-language runs
- **Observability**: Harder to track overall translation progress across languages
- **Functionality**: Does not affect translation quality or correctness

**Proposed Solution**:
1. Each subprocess writes stats to temp file (JSON format)
2. Parent process reads and aggregates stats after all subprocesses complete
3. Display aggregated stats in final summary

**Estimated Effort**: 1-2 hours

**Priority**: LOW (nice-to-have, not blocking)

**Acceptance Criteria**:
- Multi-language translation shows aggregated stats (files translated, segments translated, TM hit rate, etc.)
- No impact on single-language translation performance
- Stats file cleanup on error/interrupt

**Related Files**:
- `src/cli.py` (subprocess spawning logic)
- `src/observability/telemetry.py` (stats collection)

---

## Item 2: Dashboard Security Hardening

**File**: `src/benchmarking/dashboard/app.py:828`
**Code Context**:
```python
# TODO: Future security hardening (authentication, HTTPS, rate limiting)
```

**Description**:
The benchmark dashboard currently runs without authentication, HTTPS, or rate limiting. It's intended for local development use only. The application already displays a warning on startup:

```
⚠️  WARNING: This dashboard is NOT production-ready.
   Security hardening (auth, HTTPS) is planned for future work.
```

**Impact**:
- **Security**: Dashboard should NOT be exposed to public internet in current state
- **Use Case**: Acceptable for local development/debugging
- **Production**: Not intended for production deployment

**Proposed Solution**:
1. **Authentication**: Add basic auth or OAuth2
2. **HTTPS**: Support TLS/SSL certificates
3. **Rate Limiting**: Prevent abuse of API endpoints
4. **CORS**: Configure cross-origin policies
5. **Input Validation**: Sanitize all user inputs

**Estimated Effort**: 4-8 hours

**Priority**: MEDIUM (important if dashboard will be deployed)

**Acceptance Criteria**:
- Dashboard requires authentication to access
- Supports HTTPS mode (with certificate configuration)
- Rate limiting on all API endpoints (e.g., 100 req/min per IP)
- Input validation on query parameters
- Security scan (bandit) passes with no warnings

**Related Files**:
- `src/benchmarking/dashboard/app.py` (Flask app)
- `src/benchmarking/dashboard/templates/` (HTML templates)

**Note**: If dashboard remains local-only, this TODO can be closed as WONTFIX.

---

## Item 3: Translation Memory Query for Missing Segment Count

**File**: `src/translation_engine/scheduling/language_scheduler.py:169`
**Code Context**:
```python
# TODO: Query TM for missing count when TM API is finalized
```

**Description**:
The language scheduler currently cannot query the Translation Memory (TM) to count how many segments are missing translations for a given language. This would enable smarter prioritization of translation work.

**Impact**:
- **Scheduling**: Cannot prioritize languages with fewer TM hits (more work needed)
- **User Experience**: Users don't know which languages need more work
- **Functionality**: Does not affect translation correctness

**Current Behavior**:
Language scheduler prioritizes based on:
- User-specified order
- Language complexity (character sets, RTL, etc.)
- Does NOT consider TM coverage

**Proposed Solution**:
1. Add TM API method: `count_missing(site_id, src_lang, tgt_lang, segment_list)`
2. Language scheduler queries TM before scheduling
3. Prioritize languages with lower TM hit rates (more work needed)

**Estimated Effort**: 2-3 hours

**Priority**: LOW (optimization, not blocking)

**Acceptance Criteria**:
- TM API exposes `count_missing()` method
- Language scheduler queries TM for all target languages
- Scheduling considers TM coverage as prioritization factor
- Unit tests cover TM query failure (graceful degradation)

**Related Files**:
- `src/translation_engine/scheduling/language_scheduler.py` (scheduler)
- `src/tm/translation_memory.py` (TM API)
- `src/tm/l1_cache.py`, `src/tm/l2_persistent.py` (TM implementations)

---

## Recommendations

### Immediate Actions (Pre-Production)

**None**. All TODO items are non-blocking and do not affect production readiness.

### Post-Production Actions

**Priority Order**:

1. **Item 3** (TM Query) - Improves scheduling intelligence
   - Effort: 2-3 hours
   - Impact: Medium (better resource allocation)
   - Risk: Low (isolated change)

2. **Item 1** (Subprocess Stats) - Improves user experience
   - Effort: 1-2 hours
   - Impact: Low (cosmetic improvement)
   - Risk: Low (additive feature)

3. **Item 2** (Dashboard Security) - Only if deploying dashboard publicly
   - Effort: 4-8 hours
   - Impact: High (security requirement)
   - Risk: Medium (requires infrastructure changes)

### Technical Debt Tracking

**Recommendation**: Create GitHub issues for each TODO item:

- Issue #1: "Aggregate subprocess statistics in multi-language mode"
- Issue #2: "Security hardening for benchmark dashboard"
- Issue #3: "Language scheduler TM-aware prioritization"

Label: `technical-debt`, `enhancement`, `low-priority`

---

## Acceptance Criteria for PROD-006

- ✅ All TODO/FIXME items documented
- ✅ Impact assessment completed for each item
- ✅ Priority and effort estimates provided
- ✅ None are production blockers
- ✅ Recommendations provided for future work

**Status**: COMPLETE

---

## References

- Production Readiness Report: `docs/quality/PRODUCTION_READINESS_REPORT.md`
- Production Checklist: `docs/quality/PRODUCTION_CHECKLIST.md`
- Source Files:
  - `src/cli.py:1857`
  - `src/benchmarking/dashboard/app.py:828`
  - `src/translation_engine/scheduling/language_scheduler.py:169`

---

**Last Updated**: 2026-01-17
**Next Review**: After production deployment
