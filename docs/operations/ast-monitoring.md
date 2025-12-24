# AST Translation Monitoring & Dashboards

## Overview

This document describes the telemetry, metrics, and dashboard configuration for monitoring the AST-based translation feature in production.

---

## Telemetry Fields

The following metrics are emitted during translation operations when AST-based translation is enabled:

### TranslationStats Fields

Located in `src/translation_engine/models.py`:

```python
@dataclass
class TranslationStats:
    # ... existing fields ...

    # AST-based translation metrics
    ast_translation_enabled: bool = False  # True if AST-based translation was used
    ast_units_extracted: int = 0  # Total TextUnits extracted from AST
    ast_units_translatable: int = 0  # TextUnits that needed translation
    ast_units_protected: int = 0  # TextUnits marked as do_not_translate
    ast_batch_calls: int = 0  # Number of batch translation calls
    ast_individual_fallbacks: int = 0  # Number of fallbacks to individual translation
```

### Metric Semantics

1. **ast_translation_enabled** (boolean gauge)
   - True when a file was translated using AST-based reconstruction
   - False when legacy reconstruction was used
   - Use to track rollout progress

2. **ast_units_extracted** (counter)
   - Total number of TextUnits extracted from document AST
   - Includes both translatable and protected units
   - Typical range: 10-50 per document (varies by length/complexity)

3. **ast_units_translatable** (counter)
   - Number of units that needed translation (do_not_translate=False)
   - Excludes code spans, URLs, product names
   - Typical range: 60-80% of extracted units

4. **ast_units_protected** (counter)
   - Number of units marked as non-translatable (do_not_translate=True)
   - Includes: code spans, product names, technical identifiers
   - Typical range: 20-40% of extracted units

5. **ast_batch_calls** (counter)
   - Number of batch MT API calls made
   - With default batch_size=50, typically 1-2 calls per document
   - Lower is better (indicates efficient batching)

6. **ast_individual_fallbacks** (counter)
   - Number of times batch translation fell back to individual unit translation
   - Indicates M2M100 delimiter corruption or batch processing issues
   - **Target: <5% of ast_units_translatable**
   - **Alert threshold: >5% sustained**

---

## Grafana Dashboard Configuration

### Dashboard 1: AST Translation Overview

**Purpose**: High-level rollout progress and health metrics

**Panels**:

1. **Rollout Progress**
   - Type: Stat (percentage)
   - Query:
     ```promql
     (count(ast_translation_enabled == 1) / count(ast_translation_enabled)) * 100
     ```
   - Description: Percentage of translations using AST

2. **AST Translations (Last Hour)**
   - Type: Stat (count)
   - Query:
     ```promql
     sum(increase(ast_translation_enabled[1h]))
     ```
   - Description: Number of AST translations in last hour

3. **Average Units per Document**
   - Type: Stat (gauge)
   - Query:
     ```promql
     avg(ast_units_extracted / ast_translation_enabled)
     ```
   - Description: Average TextUnits extracted per document

4. **Protection Rate**
   - Type: Stat (percentage)
   - Query:
     ```promql
     (sum(ast_units_protected) / sum(ast_units_extracted)) * 100
     ```
   - Description: Percentage of units protected (code, product names)

5. **Fallback Rate (CRITICAL)**
   - Type: Stat (percentage) with alert threshold
   - Query:
     ```promql
     (sum(rate(ast_individual_fallbacks[5m])) / sum(rate(ast_units_translatable[5m]))) * 100
     ```
   - Thresholds:
     - Green: <2%
     - Yellow: 2-5%
     - Red: >5%
   - Description: Percentage of units falling back to individual translation

6. **AST Translations Over Time**
   - Type: Time series graph
   - Query:
     ```promql
     sum(rate(ast_translation_enabled[5m])) * 300
     ```
   - Description: AST translations per 5 minutes

7. **Fallbacks Over Time**
   - Type: Time series graph
   - Query:
     ```promql
     sum(rate(ast_individual_fallbacks[5m])) * 300
     ```
   - Description: Fallback count per 5 minutes

### Dashboard 2: AST Translation Details

**Purpose**: Detailed metrics for debugging and optimization

**Panels**:

1. **Unit Extraction Breakdown**
   - Type: Bar chart
   - Queries:
     - Translatable: `sum(ast_units_translatable)`
     - Protected: `sum(ast_units_protected)`
   - Description: Distribution of translatable vs protected units

2. **Batch Efficiency**
   - Type: Stat (ratio)
   - Query:
     ```promql
     sum(ast_units_translatable) / sum(ast_batch_calls)
     ```
   - Description: Average units per batch call (target: ~50 with default config)

3. **Segmentation Strategy Distribution**
   - Type: Pie chart
   - Query: (requires custom labels in telemetry)
     ```promql
     count by (segmentation_strategy) (ast_translation_enabled)
     ```
   - Description: Usage of adaptive/leaf_only/sentence_only strategies

4. **Batch Calls vs Fallbacks**
   - Type: Time series graph (dual axis)
   - Queries:
     - Batch calls: `sum(rate(ast_batch_calls[5m]))`
     - Fallbacks: `sum(rate(ast_individual_fallbacks[5m]))`
   - Description: Compare batch usage vs fallback frequency

5. **Units per Document Distribution**
   - Type: Histogram
   - Query:
     ```promql
     histogram_quantile(0.5, sum(rate(ast_units_extracted[5m])) by (le))
     ```
   - Description: Distribution of document complexity (by unit count)

6. **Site-Level AST Adoption**
   - Type: Table
   - Query: (requires site_id labels)
     ```promql
     sum by (site_id) (ast_translation_enabled)
     ```
   - Columns: Site ID, AST Enabled Count, Total Translations, Adoption %

### Dashboard 3: Quality & Performance

**Purpose**: Track quality and performance metrics for AST translation

**Panels**:

1. **Validation Errors (AST vs Legacy)**
   - Type: Time series graph (two lines)
   - Queries:
     - AST: `sum(rate(validation_errors{ast_enabled=true}[5m]))`
     - Legacy: `sum(rate(validation_errors{ast_enabled=false}[5m]))`
   - Description: Compare validation error rates

2. **Translation Duration (AST vs Legacy)**
   - Type: Time series graph (two lines)
   - Queries:
     - AST: `avg(translation_duration{ast_enabled=true})`
     - Legacy: `avg(translation_duration{ast_enabled=false})`
   - Description: Compare translation latency

3. **API Cost Savings from Batching**
   - Type: Stat (percentage)
   - Query:
     ```promql
     ((sum(ast_units_translatable) / sum(ast_batch_calls)) / sum(ast_units_translatable)) * 100
     ```
   - Description: API call reduction from batching vs individual calls

4. **Corruption Rate (Target: 0%)**
   - Type: Stat (count) with alert
   - Query: (requires corruption detection in validation)
     ```promql
     sum(validation_errors{type="corruption", ast_enabled=true})
     ```
   - Thresholds:
     - Green: 0
     - Red: >0
   - Description: Number of detected corruption cases (links, code, images)

---

## Alerts

### Critical Alerts (PagerDuty/Slack)

1. **High Fallback Rate**
   ```yaml
   alert: ASTTranslationHighFallbackRate
   expr: |
     (sum(rate(ast_individual_fallbacks[5m])) / sum(rate(ast_units_translatable[5m]))) > 0.05
   for: 15m
   labels:
     severity: critical
   annotations:
     summary: "AST translation fallback rate is above 5%"
     description: "Current fallback rate: {{ $value | humanizePercentage }}. Investigate M2M100 delimiter corruption."
   ```

2. **AST Translation Failures**
   ```yaml
   alert: ASTTranslationFailures
   expr: |
     sum(rate(ast_translation_failures[5m])) > 0
   for: 5m
   labels:
     severity: critical
   annotations:
     summary: "AST translation is failing"
     description: "Failures detected. Check logs for 'AST translation failed' errors."
   ```

3. **Corruption Detected**
   ```yaml
   alert: ASTTranslationCorruption
   expr: |
     sum(increase(validation_errors{type="corruption", ast_enabled=true}[5m])) > 0
   for: 1m
   labels:
     severity: critical
   annotations:
     summary: "Translation corruption detected with AST enabled"
     description: "Immediate rollback may be required. Check validation logs."
   ```

### Warning Alerts (Slack only)

1. **Moderate Fallback Rate**
   ```yaml
   alert: ASTTranslationModerateFallbackRate
   expr: |
     (sum(rate(ast_individual_fallbacks[5m])) / sum(rate(ast_units_translatable[5m]))) > 0.03
   for: 30m
   labels:
     severity: warning
   annotations:
     summary: "AST translation fallback rate is above 3%"
     description: "Current fallback rate: {{ $value | humanizePercentage }}. Monitor for further increases."
   ```

2. **Low Batch Efficiency**
   ```yaml
   alert: ASTTranslationLowBatchEfficiency
   expr: |
     (sum(ast_units_translatable) / sum(ast_batch_calls)) < 25
   for: 1h
   labels:
     severity: warning
   annotations:
     summary: "AST translation batch efficiency is low"
     description: "Average units per batch: {{ $value }}. Consider increasing batch_size or investigate content complexity."
   ```

---

## Log Monitoring

### Key Log Patterns

1. **Normal Operation**
   ```
   INFO: AST Translation: Extracting TextUnits from AST (strategy: adaptive)
   INFO: AST Translation: Extracted 42 units (35 translatable, 7 protected)
   INFO: AST Translation: Translating units (batch_size: 50)
   INFO: AST Translation: Successfully translated 35 units (1 batches, 0 fallbacks)
   ```

2. **Fallback Detected (Warning)**
   ```
   WARNING: Batch translation delimiter corrupted, falling back to individual translation
   ```

3. **AST Translation Failure (Error)**
   ```
   ERROR: AST-based translation failed: <error details>
   WARNING: AST translation failed, falling back to legacy reconstruction
   ```

### Log Aggregation Queries

**Splunk/ELK Query for Fallback Rate**:
```
source="hugo-translator" "falling back to individual translation"
| timechart span=5m count as fallbacks
```

**Grafana Loki Query**:
```
{job="hugo-translator"} |= "AST Translation:" |= "fallbacks"
```

---

## Monitoring Checklist

Before enabling AST translation on a site:

- [ ] Grafana dashboards configured and accessible
- [ ] Critical alerts (fallback rate, failures, corruption) configured
- [ ] Warning alerts configured
- [ ] Log aggregation set up (Splunk/ELK/Loki)
- [ ] On-call team has access to dashboards and alert documentation
- [ ] Runbook created for responding to alerts
- [ ] Baseline metrics captured for comparison (pre-rollout)

During rollout:

- [ ] Monitor Dashboard 1 (Overview) hourly
- [ ] Check fallback rate daily (must be <5%)
- [ ] Review log patterns daily for anomalies
- [ ] Spot-check translated output quality
- [ ] Track API cost trends (should decrease with batching)

After full rollout:

- [ ] Weekly review of Dashboard 2 (Details) for optimization opportunities
- [ ] Monthly review of Dashboard 3 (Quality & Performance) for trends
- [ ] Adjust batch_size or segmentation_strategy based on metrics

---

## Troubleshooting Guide

### High Fallback Rate (>5%)

**Possible Causes**:
1. M2M100 model not initialized with special delimiter tokens
2. Batch size too large for content complexity
3. M2M100 model version incompatible with delimiter strategy

**Investigation Steps**:
1. Check model initialization logs:
   ```
   grep "special_tokens" /var/log/hugo-translator.log
   ```

2. Check batch size configuration:
   ```yaml
   # In site profile
   ast_batch_size: 50  # Try reducing to 25
   ```

3. Review sample fallback cases in logs:
   ```
   grep -A 10 "falling back to individual translation" /var/log/hugo-translator.log
   ```

4. Test with smaller batch size:
   ```yaml
   ast_batch_size: 10  # Minimal batching for testing
   ```

**Resolution**:
- If model initialization issue: Restart service with proper tokenizer setup
- If batch size issue: Reduce `ast_batch_size` in affected site profiles
- If model incompatibility: Consider using different M2M100 checkpoint

### Low Batch Efficiency (<25 units/batch)

**Possible Causes**:
1. Documents are very short (few TextUnits)
2. High proportion of protected units (code-heavy content)
3. Batch size set too low

**Investigation Steps**:
1. Check average units per document:
   ```promql
   avg(ast_units_extracted / ast_translation_enabled)
   ```

2. Check protection rate:
   ```promql
   (sum(ast_units_protected) / sum(ast_units_extracted)) * 100
   ```

**Resolution**:
- If short documents: This is expected, no action needed
- If high protection rate: Consider whether AST translation is beneficial for this content type
- If batch size too low: Increase `ast_batch_size` if fallback rate is low

### Validation Errors Increased

**Possible Causes**:
1. AST rendering bug (structure not correctly reconstructed)
2. Translation quality regression
3. Validation rules too strict for AST output format

**Investigation Steps**:
1. Compare validation errors AST vs Legacy:
   ```promql
   sum(validation_errors{ast_enabled=true}) vs sum(validation_errors{ast_enabled=false})
   ```

2. Review specific validation failures in logs

3. Manually inspect failed translations

**Resolution**:
- If AST rendering bug: File issue, rollback site, fix bug
- If translation quality issue: Adjust segmentation strategy
- If validation too strict: Update validation rules to accommodate AST output format

---

## Success Metrics

After full rollout, target metrics:

- **Fallback Rate**: <2% (target: <5% acceptable)
- **Batch Efficiency**: >40 units/batch (target: ~50 with default config)
- **Corruption Rate**: 0% (critical: must remain 0%)
- **API Cost Reduction**: 10-30% (from batching efficiency)
- **Validation Error Rate**: Equal to or better than legacy
- **Translation Latency**: Equal to or better than legacy

---

## Dashboard JSON Exports

### Example: Rollout Progress Panel

```json
{
  "title": "AST Translation Rollout Progress",
  "type": "stat",
  "targets": [
    {
      "expr": "(count(ast_translation_enabled == 1) / count(ast_translation_enabled)) * 100",
      "refId": "A"
    }
  ],
  "fieldConfig": {
    "defaults": {
      "unit": "percent",
      "thresholds": {
        "mode": "absolute",
        "steps": [
          { "value": null, "color": "red" },
          { "value": 10, "color": "yellow" },
          { "value": 50, "color": "green" }
        ]
      }
    }
  }
}
```

### Example: Fallback Rate Alert Panel

```json
{
  "title": "Fallback Rate (Alert Threshold: 5%)",
  "type": "stat",
  "targets": [
    {
      "expr": "(sum(rate(ast_individual_fallbacks[5m])) / sum(rate(ast_units_translatable[5m]))) * 100",
      "refId": "A"
    }
  ],
  "fieldConfig": {
    "defaults": {
      "unit": "percent",
      "thresholds": {
        "mode": "absolute",
        "steps": [
          { "value": null, "color": "green" },
          { "value": 3, "color": "yellow" },
          { "value": 5, "color": "red" }
        ]
      }
    }
  }
}
```

---

## Contact & Support

For dashboard issues or metric questions:
- Check this documentation first
- Review Grafana dashboard configuration
- Consult telemetry integration code: `src/observability/telemetry_integration.py`
- File issue if metrics not appearing as expected
