# Incident Response Template

Use this template for post-incident reviews (postmortems). Copy this file, fill in the sections, and store the completed postmortem in `docs/operations/postmortems/`.

---

## Incident Summary

| Field | Value |
|-------|-------|
| **Incident ID** | INC-YYYY-NNN |
| **Date** | YYYY-MM-DD |
| **Duration** | HH:MM (from detection to resolution) |
| **Severity** | P0 / P1 / P2 / P3 (see SLA violation levels in [sla.md](sla.md)) |
| **Affected Systems** | e.g., translation worker, TM cache, metrics pipeline |
| **Affected Sites** | e.g., docs.aspose.net, kb.aspose.net |
| **Impact** | e.g., "Translation throughput dropped to 0 for 45 minutes" |
| **Detection Method** | e.g., health check alert, manual observation, SLO breach |

## Severity Classification

Reference: [SLA Violation Response Levels](sla.md)

| Severity | Criteria |
|----------|----------|
| **P0** | >10% error rate, code corruption detected, >12h performance degradation |
| **P1** | <90% completeness, >5% error rate, >4h performance degradation |
| **P2** | >1h sustained performance degradation, batch fallback >50% |
| **P3** | Minor quality degradation, non-critical metric anomaly |

## Timeline

| Time (UTC) | Event |
|------------|-------|
| HH:MM | First sign of issue (e.g., alert fired, user report) |
| HH:MM | Issue confirmed and investigation started |
| HH:MM | Root cause identified |
| HH:MM | Mitigation applied (e.g., rollback, config change, restart) |
| HH:MM | Service restored to normal |
| HH:MM | Monitoring confirms stability |

## Root Cause Analysis (5 Whys)

1. **Why did the incident happen?**
   → [Direct cause]

2. **Why did [direct cause] happen?**
   → [Contributing factor]

3. **Why did [contributing factor] happen?**
   → [Deeper cause]

4. **Why did [deeper cause] happen?**
   → [Systemic issue]

5. **Why did [systemic issue] exist?**
   → [Root cause]

## Impact Assessment

| Dimension | Impact |
|-----------|--------|
| **Files affected** | N files across N languages |
| **Translation quality** | e.g., "N files accepted with lower quality during degradation" |
| **User-facing impact** | e.g., "No user impact — translations not yet published" |
| **Data integrity** | e.g., "TM cache entries from this period may be low quality" |
| **SLO impact** | e.g., "Error budget consumed: 45 of 216 remaining minutes" |

## Action Items

| # | Action | Owner | Deadline | Status |
|---|--------|-------|----------|--------|
| 1 | [Immediate fix applied during incident] | @name | Done | Complete |
| 2 | [Permanent fix to prevent recurrence] | @name | YYYY-MM-DD | TODO |
| 3 | [Monitoring improvement] | @name | YYYY-MM-DD | TODO |
| 4 | [Documentation update] | @name | YYYY-MM-DD | TODO |

## Lessons Learned

### What went well
- [e.g., "Alert fired within 5 minutes of degradation"]
- [e.g., "Rollback script worked correctly"]

### What went poorly
- [e.g., "No automated remediation — required manual intervention"]
- [e.g., "Runbook was outdated for this failure mode"]

### Where we got lucky
- [e.g., "Incident happened during low-traffic hours"]

## Follow-Up

- [ ] Action items assigned and tracked
- [ ] Runbook updated if applicable
- [ ] Monitoring/alerting improved
- [ ] Postmortem shared with team
