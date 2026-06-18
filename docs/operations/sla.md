# Translation System Service Level Agreements (SLAs)

**Document Owner**: SRE Team
**Last Updated**: 2025-12-22
**Review Frequency**: Quarterly
**Related Documents**:
- [Deployment Checklist](deployment-checklist.md)
- [Rollback Procedure](rollback.md)
- [Metrics Guide](metrics.md)
- [Grafana Dashboards](grafana.md)

---

## Overview

This document defines the Service Level Agreements (SLAs), Service Level Objectives (SLOs), and error budgets for the Hugo Translation System. These targets guide operational decisions, deployment strategies, and incident response.

**Purpose**: Establish clear, measurable targets for system performance, quality, and availability
**Scope**: All production translation workloads
**Enforcement**: Monitored via Prometheus/Grafana, automated alerts configured

---

## Table of Contents

1. [Performance SLAs](#performance-slas)
2. [Quality SLAs](#quality-slas)
3. [Availability SLAs](#availability-slas)
4. [Error Budgets](#error-budgets)
5. [SLA Violation Response](#sla-violation-response)
6. [Measurement and Reporting](#measurement-and-reporting)

---

## Performance SLAs

### Translation Throughput

**Definition**: Number of translation units processed per second in batch mode

**SLO Targets**:
- **Target (P50)**: ≥5 translation units/second
- **Minimum (P95)**: ≥2 translation units/second
- **Critical Threshold**: <1 unit/second sustained for >10 minutes

**Measurement**:
- **Metric**: `translation_throughput_units_per_second` (Prometheus gauge)
- **Window**: Rolling 1-hour average
- **Percentile**: 95th percentile for minimum threshold
- **Dashboard**: [Translation Overview](../../docker/grafana/dashboards/translation_overview.json)

**Violation Response**:
- P50 < 5 units/sec sustained >1 hour → P2 incident (investigate performance)
- P95 < 2 units/sec sustained >1 hour → P1 incident (performance degradation)
- < 1 unit/sec sustained >10 min → P0 incident (critical performance failure)

---

### Batch Fallback Rate

**Definition**: Percentage of batch translation requests that fall back to individual translation

**SLO Targets**:
- **Target**: <30% fallback rate
- **Warning**: 30-50% fallback rate (review required)
- **Critical**: >50% fallback rate sustained

**Measurement**:
- **Metric**: `batch_fallback_rate` (percentage, 0-100)
- **Calculation**: `(fallback_count / total_batch_attempts) * 100`
- **Window**: Rolling 4-hour window
- **Dashboard**: TM Performance dashboard

**Violation Response**:
- 30-50% for >2 hours → P2 incident (investigate batch translation issues)
- >50% for >1 hour → P1 incident (batch system degraded)
- >80% for >30 min → P0 incident (batch system failure, consider rollback)

**Context**:
- <10% is excellent (highly efficient batch translation)
- 10-30% is normal (expected for mixed content types)
- >30% indicates potential issues with model, batch optimization, or content complexity

---

### Translation Latency

**Definition**: End-to-end time to translate a typical document

**SLO Targets**:
- **Target (100 units)**: <10 seconds (P95)
- **Maximum (100 units)**: <30 seconds (P99)
- **Large document (1000 units)**: <120 seconds (P95)

**Measurement**:
- **Metric**: `translation_duration_ms` (milliseconds)
- **Typical Document**: 100 translation units (~2-3 pages)
- **Window**: Per-translation measurement, aggregated hourly
- **Dashboard**: Translation Overview

**Violation Response**:
- P95 > 30 seconds for typical docs → P2 incident (performance review)
- P99 > 60 seconds for typical docs → P1 incident (latency degradation)
- Any translation >5 minutes → P1 incident (investigate timeout/hang)

---

### Telemetry Duration Fallback Rate

**Definition**: Percentage of translations where duration calculation falls back to 0 due to None/invalid values

**SLO Targets**:
- **Target**: <0.1% fallback rate
- **Warning**: 0.1-1.0% fallback rate
- **Critical**: >1.0% fallback rate

**Measurement**:
- **Metric**: `telemetry_duration_fallback` (counter with reason labels)
- **Calculation**: `(fallback_events / total_translations) * 100`
- **Window**: Rolling 24-hour window
- **Alert**: Configured in [alert_rules.yml](../../docker/prometheus/alert_rules.yml)

**Violation Response**:
- 0.1-1.0% for >6 hours → P3 incident (investigate edge cases)
- >1.0% for >2 hours → P2 incident (data quality issue)
- >5.0% for >30 min → P1 incident (systemic duration tracking failure)

**Related**: PR-04 Telemetry Fix (archived), [Troubleshooting Guide](telemetry-troubleshooting.md)

---

## Quality SLAs

### Translation Completeness

**Definition**: Percentage of translatable content that is successfully translated (not left in source language)

**SLO Targets**:
- **Target**: ≥95% completeness
- **Minimum**: ≥90% completeness
- **Critical**: <85% completeness

**Measurement**:
- **Method**: Manual sampling + automated validation
- **Sample Size**: 20 documents per week (randomized selection)
- **Automated**: Post-translation completeness validator
- **Metric**: `translation_completeness_percentage`

**Violation Response**:
- 90-95% completeness → P2 incident (review translation quality)
- 85-90% completeness → P1 incident (significant quality degradation)
- <85% completeness → P0 incident (critical quality failure, rollback candidate)

**Validation**:
```bash
# Automated completeness check
pytest tests/unit/validation/test_completeness_validator.py -v

# Manual spot-check
python scripts/validate_translation_quality.py --sample 20 --lang de
```

---

### Structure Fidelity

**Definition**: Preservation of document structure (headings, lists, code blocks, tables, links, images)

**SLO Targets**:
- **Target**: 100% structure preservation
- **Minimum**: ≥99% structure preservation
- **Critical**: <95% structure preservation

**Measurement**:
- **Method**: Automated validation on all translations
- **Validators**:
  - YAML structure validator
  - Link integrity validator
  - Placeholder preservation validator
  - Shortcode preservation validator
- **Metric**: `structure_validation_pass_rate`

**Violation Response**:
- 99-100% → Normal operation
- 95-99% → P2 incident (structure preservation degradation)
- <95% → P1 incident (critical structure corruption, rollback candidate)

**Automated Enforcement**:
```python
# In config/global.yaml
validation:
  enabled: true
  mode: "strict"  # Fail translation on structure validation errors
```

---

### Code Preservation

**Definition**: Code blocks and inline code remain completely unchanged (no translation, no corruption)

**SLO Targets**:
- **Target**: 100% code preservation (zero tolerance)
- **Minimum**: 100% code preservation
- **Critical**: Any code corruption

**Measurement**:
- **Method**: Automated diff check (byte-for-byte comparison)
- **Scope**: All code blocks, inline code, shortcodes
- **Metric**: `code_preservation_failures` (should be 0)

**Violation Response**:
- Any code corruption detected → P0 incident (immediate rollback)
- Code corruption is a ZERO TOLERANCE failure

**Automated Validation**:
```bash
# Run structure preservation tests
pytest tests/unit/translation_engine/parser/test_structure_preservation.py -v
pytest tests/unit/translation_engine/reconstructor/test_literal_block_preservation.py -v
```

---

### Terminology Preservation

**Definition**: Protected terminology (product names, technical terms) preserved correctly

**SLO Targets**:
- **Target**: ≥98% terminology preservation
- **Minimum**: ≥95% terminology preservation
- **Critical**: <90% terminology preservation

**Measurement**:
- **Method**: Terminology preservation validator (automated)
- **Terminology Sources**:
  - [config/terminology/aspose_terms.txt](../../config/terminology/aspose_terms.txt)
  - [config/terminology/technical_terms.yaml](../../config/terminology/technical_terms.yaml)
  - [config/terminology/protected_terms.yaml](../../config/terminology/protected_terms.yaml)
- **Metric**: `terminology_preservation_rate`

**Violation Response**:
- 95-98% → P2 incident (review terminology protection)
- 90-95% → P1 incident (terminology protection degraded)
- <90% → P1 incident (critical terminology failure)

---

## Availability SLAs

### System Uptime

**Definition**: Translation system available and processing jobs successfully

**SLO Targets**:
- **Target**: 99.5% uptime (43 minutes downtime per month)
- **Minimum**: 99.0% uptime (7.2 hours downtime per month)
- **Critical**: <95% uptime

**Measurement**:
- **Metric**: `translation_job_success_rate` (successful jobs / total jobs)
- **Window**: Rolling 30-day window
- **Exclusions**: Planned maintenance (announced ≥24 hours in advance)

**Violation Response**:
- 99.0-99.5% → P2 incident (reliability review)
- 95-99.0% → P1 incident (availability degradation)
- <95% → P0 incident (critical availability failure)

**Downtime Classification**:
- **Planned**: Scheduled maintenance (excluded from SLA)
- **Unplanned**: System failures, bugs, infrastructure issues (counts against SLA)

---

### Error Rate

**Definition**: Percentage of translation jobs that fail with errors

**SLO Targets**:
- **Target**: <1% error rate
- **Warning**: 1-5% error rate
- **Critical**: >5% error rate

**Measurement**:
- **Metric**: `translation_error_rate` (percentage)
- **Calculation**: `(failed_jobs / total_jobs) * 100`
- **Window**: Rolling 24-hour window
- **Dashboard**: Translation Overview

**Violation Response**:
- 1-5% for >4 hours → P2 incident (investigate error patterns)
- 5-10% for >1 hour → P1 incident (significant error spike)
- >10% for >30 min → P0 incident (critical system failure, rollback candidate)

**Error Categories**:
- **Transient**: Network issues, API timeouts (retry possible)
- **Permanent**: Invalid input, configuration errors (require manual intervention)
- **Systemic**: Code bugs, infrastructure failures (require deployment fix)

---

## Error Budgets

### Monthly Error Budget

**Allocation**: 0.5% downtime per month (216 minutes)

**Calculation**:
```
Total minutes per month: 43,200 (30 days * 24 hours * 60 minutes)
Error budget (0.5%): 216 minutes
Error budget (99.5% uptime): 43,200 - 216 = 42,984 minutes uptime required
```

**Tracking**:
- **Metric**: `error_budget_remaining_minutes` (Prometheus gauge)
- **Update Frequency**: Real-time (per incident)
- **Dashboard**: Operations dashboard (error budget panel)

**Consumption**:
- Deduct actual downtime from monthly budget
- Count only unplanned outages (planned maintenance excluded)
- Reset on 1st of each month

---

### Error Budget Policy

**Budget Consumption Levels**:

**0-50% Budget Consumed** (>108 minutes remaining):
- ✅ **Normal Operations**: Continue feature development and deployments
- No restrictions on deployment frequency
- Standard change management process

**50-80% Budget Consumed** (43-108 minutes remaining):
- ⚠️ **Cautious Mode**: Review reliability trends
- Actions:
  - Increase monitoring attention
  - Review recent incidents for patterns
  - Defer non-critical feature releases
  - Focus on reliability improvements
- **Approval Required**: Engineering lead approval for feature deployments

**80-100% Budget Consumed** (0-43 minutes remaining):
- 🚨 **Freeze Mode**: Freeze non-critical feature releases
- Actions:
  - Deploy only P0/P1 bug fixes and reliability improvements
  - No feature releases until next month
  - Mandatory incident retrospective
  - Reliability improvement plan required
- **Approval Required**: CTO/VP Engineering approval for any deployment

**100% Budget Exhausted** (0 minutes remaining):
- ❌ **Incident Review Required**
- Actions:
  - Complete freeze on all feature releases
  - Mandatory post-mortem for all incidents
  - Reliability improvement roadmap required
  - External communication to stakeholders
- **Next Month**: Start fresh with full budget, implement improvements

---

### Error Budget Tracking

**Dashboard Visualization**:
```
Error Budget Status (December 2025)
┌──────────────────────────────────────────────┐
│ Budget Remaining: 156 / 216 minutes (72%)   │
│ Status: Normal Operations ✅                 │
│                                              │
│ Incidents This Month:                        │
│ - Dec 15: Database outage (45 min)          │
│ - Dec 18: API timeout spike (15 min)        │
│                                              │
│ Trend: 60 minutes consumed in 18 days       │
│ Projected: 100 minutes consumed by month end│
│ Risk Level: LOW                              │
└──────────────────────────────────────────────┘
```

**Alert Thresholds**:
- 50% budget consumed → Notify SRE team (P3)
- 75% budget consumed → Notify engineering leads (P2)
- 90% budget consumed → Feature freeze warning (P1)
- 100% budget consumed → Feature freeze enforced (P0)

---

## SLA Violation Response

### Performance SLA Violated

**Symptom**: Throughput <2 units/sec OR latency >30 sec (P95) OR batch fallback >50%

**Severity**:
- Sustained >1 hour → P2 incident
- Sustained >4 hours → P1 incident
- Sustained >12 hours → P0 incident (rollback candidate)

**Immediate Actions**:
1. Check Grafana dashboard for performance metrics
2. Review recent deployments (within 48 hours)
3. Check system resources (CPU, memory, GPU utilization)
4. Review batch translation logs for failures
5. Check TM cache hit rates

**Investigation Steps**:
```bash
# Check performance metrics
python scripts/analysis/generate_metrics_report.py --last 24h

# Run performance baseline
python scripts/bench/benchmark_production.py --compare-to-baseline

# Check batch fallback reasons
grep "Batch fallback" /var/log/translation/*.log | tail -100

# Check TM performance
python scripts/tm/query_tm_cache.py --stats
```

**Resolution Paths**:
- **If deployment-related**: Consider rollback (see [rollback.md](rollback.md))
- **If resource-related**: Scale infrastructure (add workers, increase GPU memory)
- **If batch optimization issue**: Review batch size settings, model selection
- **If TM cache issue**: Review cache hit rates, consider cache refresh

---

### Quality SLA Violated

**Symptom**: Completeness <90% OR structure preservation <95% OR terminology preservation <90%

**Severity**:
- Completeness <90% → P1 incident
- Structure corruption detected → P0 incident
- Code corruption detected → P0 incident (immediate rollback)

**Immediate Actions**:
1. **CRITICAL**: If code corruption detected, initiate rollback immediately
2. Stop all in-progress translation jobs (if quality issue is systemic)
3. Collect sample translations showing quality degradation
4. Review validation logs for failure patterns
5. Check recent configuration changes

**Investigation Steps**:
```bash
# Run completeness validation
pytest tests/unit/validation/test_completeness_validator.py -v

# Run structure preservation tests
pytest tests/unit/translation_engine/parser/test_structure_preservation.py -v

# Sample 10 recent translations for manual review
python scripts/validate_translation_quality.py --sample 10 --detailed

# Check validation metrics
curl http://localhost:9090/api/v1/query?query=structure_validation_pass_rate
```

**Resolution Paths**:
- **If AST-related**: Review AST rendering logic, consider disabling AST for affected sites
- **If terminology-related**: Review terminology protection configuration
- **If model-related**: Consider switching to alternative model
- **If validation-related**: Review validation rules (may be false positives)

**Rollback Trigger**:
- Any code corruption → Immediate rollback
- Completeness <85% sustained >1 hour → Rollback recommended
- Structure preservation <90% → Rollback recommended

---

### Availability SLA Violated

**Symptom**: Error rate >5% OR uptime <99% (trending)

**Severity**:
- Error rate 5-10% → P1 incident
- Error rate >10% → P0 incident
- Uptime <95% → P0 incident

**Immediate Actions**:
1. Check error logs for patterns
2. Review infrastructure health (database, API, workers)
3. Check deployment status (recent changes)
4. Review alert history in Grafana
5. Check external dependencies (telemetry API, model downloads)

**Investigation Steps**:
```bash
# Check error patterns
grep "ERROR" /var/log/translation/*.log | cut -d' ' -f5- | sort | uniq -c | sort -rn | head -20

# Check system health
python scripts/health_check.py --verbose

# Check recent deployments
git log --oneline -10

# Check infrastructure
docker ps -a  # If using Docker
systemctl status translation-worker  # If using systemd
```

**Resolution Paths**:
- **If API error spike**: Check telemetry API, external services
- **If worker failures**: Restart workers, check resource limits
- **If database issues**: Check DB connection pool, query performance
- **If deployment-related**: Rollback to previous version

---

## Measurement and Reporting

### Data Sources

**Metrics Collection**:
- **Prometheus**: Primary metrics backend
  - Port: 9090
  - Config: [docker/prometheus/prometheus.yml](../../docker/prometheus/prometheus.yml)
  - Retention: 15 days

**Visualization**:
- **Grafana**: Dashboard and alerting
  - Port: 3000
  - Dashboards:
    - [Translation Overview](../../docker/grafana/dashboards/translation_overview.json)
    - [TM Performance](../../docker/grafana/dashboards/tm_performance.json)
  - Provisioning: [docker/grafana/provisioning/](../../docker/grafana/provisioning/)

**Alerts**:
- **Alert Rules**: [docker/prometheus/alert_rules.yml](../../docker/prometheus/alert_rules.yml)
- **Notification Channels**: Slack (#translation-alerts), Email, PagerDuty

---

### Reporting Cadence

**Daily** (Automated):
- Error rate summary (if >1%)
- Performance metrics (throughput, latency)
- Top 5 error messages

**Weekly** (Automated):
- SLA compliance report
- Error budget status
- Quality sampling results (20 documents)
- Performance trend analysis

**Monthly** (Manual):
- SLA compliance scorecard
- Error budget consumption report
- Incident post-mortem summary
- Reliability improvement recommendations

**Quarterly** (Manual):
- SLA target review
- Error budget policy adjustment
- Capacity planning recommendations
- Historical trend analysis

---

### SLA Compliance Scorecard Template

```markdown
## SLA Compliance Report - [Month Year]

### Executive Summary
- **Overall SLA Compliance**: XX%
- **Error Budget Consumed**: XX/216 minutes (XX%)
- **Incidents**: X total (P0: X, P1: X, P2: X)
- **Status**: [PASS / AT RISK / FAIL]

### Performance SLAs
| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Throughput (P95) | ≥2 units/sec | X.X units/sec | ✅/❌ |
| Batch Fallback | <30% | XX% | ✅/❌ |
| Latency (P95) | <10 sec | XX sec | ✅/❌ |
| Duration Fallback | <0.1% | X.XX% | ✅/❌ |

### Quality SLAs
| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Completeness | ≥95% | XX% | ✅/❌ |
| Structure Fidelity | 100% | XX% | ✅/❌ |
| Code Preservation | 100% | XX% | ✅/❌ |
| Terminology Preservation | ≥98% | XX% | ✅/❌ |

### Availability SLAs
| Metric | Target | Actual | Status |
|--------|--------|--------|--------|
| Uptime | ≥99.5% | XX.X% | ✅/❌ |
| Error Rate | <1% | X.X% | ✅/❌ |

### Error Budget
- **Allocated**: 216 minutes
- **Consumed**: XX minutes (XX%)
- **Remaining**: XX minutes (XX%)
- **Incidents**:
  - [Date]: [Description] (XX minutes)
  - [Date]: [Description] (XX minutes)

### Actions Required
- [ ] Action item 1
- [ ] Action item 2
```

---

## Appendix

### SLA Change History

| Date | Change | Reason | Approved By |
|------|--------|--------|-------------|
| 2025-12-22 | Initial SLA definition | Establish production baselines | SRE Team |

---

### Related Documentation

- [Deployment Checklist](deployment-checklist.md) - Pre-deployment validation
- [Rollback Procedure](rollback.md) - Emergency rollback runbook
- [Telemetry Troubleshooting](telemetry-troubleshooting.md) - Debugging telemetry issues
- [Grafana Guide](grafana.md) - Dashboard usage
- [Metrics Reference](metrics.md) - Prometheus metrics catalog

---

### Contact

**SLA Questions**: #sre-team on Slack
**Incident Response**: #translation-alerts on Slack
**On-Call**: See PagerDuty rotation

---

## Sign-Off

- [ ] **SRE Lead**: ___________________ Date: _______
- [ ] **Engineering Lead**: ___________________ Date: _______
- [ ] **Product Manager**: ___________________ Date: _______

**Next Review**: 2026-03-22 (3 months)
