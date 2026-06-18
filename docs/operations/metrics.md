# Metrics and Monitoring

This document describes the metrics collection system, available metrics, and how to use them for monitoring and alerting.

## Overview

The translation system collects comprehensive metrics using a Prometheus-compatible metrics system. Metrics are collected asynchronously to minimize performance impact and can be exported for monitoring dashboards and alerting.

## Architecture

```
┌─────────────────┐
│ Translation     │
│ System          │──> MetricsCollector ──> Prometheus
│                 │                     │
└─────────────────┘                     ├──> Grafana
                                        │
                                        └──> Alertmanager
```

### Components

- **MetricsCollector**: Core metrics collection class
- **Prometheus**: Time-series database for storing metrics
- **Grafana**: Visualization and dashboards
- **Alertmanager**: Alert routing and notification

## Metric Types

### Counters

Counters only increase. They reset to zero when the process restarts.

**Use for**: Counting events (translations, errors, cache hits)

**Examples**:
- `translations_total` - Total number of translations
- `tm_hits_l1` - L1 cache hits
- `translation_errors_total` - Total errors

### Gauges

Gauges can go up or down. They represent current values.

**Use for**: Current state (queue depth, memory usage, cache size)

**Examples**:
- `queue_depth` - Current job queue depth
- `memory_usage_percent` - Current memory usage
- `tm_cache_size` - Current L1 cache size

### Histograms

Histograms track distributions of values and calculate percentiles.

**Use for**: Timing and sizes (translation duration, segment length)

**Examples**:
- `translation_duration_seconds` - Translation operation timing
- `tm_lookup_duration_seconds` - TM lookup timing
- `segment_length` - Translation segment lengths

## Available Metrics

### Translation Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `translations_total` | Counter | Total translation operations | `worker_id` |
| `translations_success` | Counter | Successful translations | `worker_id` |
| `translations_failed` | Counter | Failed translations | `worker_id` |
| `translation_errors_total` | Counter | Translation errors by type | `worker_id`, `error_type` |
| `translation_duration_seconds` | Histogram | Translation operation duration | `worker_id` |

### Translation Memory Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `tm_lookups_total` | Counter | Total TM lookups | `worker_id` |
| `tm_hits_l1` | Counter | L1 cache hits | `worker_id` |
| `tm_hits_l2` | Counter | L2 exact match hits | `worker_id` |
| `tm_hits_l3` | Counter | L3 semantic match hits | `worker_id` |
| `tm_misses` | Counter | TM misses (model translation required) | `worker_id` |
| `tm_writes_total` | Counter | TM write operations | `worker_id` |
| `tm_errors_total` | Counter | TM errors | `worker_id`, `error_type` |
| `tm_lookup_duration_seconds` | Histogram | TM lookup duration | `worker_id`, `tm_layer` |
| `tm_cache_size` | Gauge | Current L1 cache size | `worker_id` |
| `tm_l2_size_bytes` | Gauge | L2 database size in bytes | `worker_id` |
| `tm_l3_index_size` | Gauge | L3 index entry count | `worker_id` |

### Model Runtime Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `model_translations_total` | Counter | Model translation calls | `worker_id`, `model_type` |
| `model_load_count` | Counter | Model load operations | `worker_id`, `model_type` |
| `model_errors_total` | Counter | Model errors | `worker_id`, `model_type` |
| `model_translation_duration_seconds` | Histogram | Model translation duration | `worker_id`, `model_type` |
| `model_memory_usage_bytes` | Gauge | Model memory usage | `worker_id` |

### Validation Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `validation_checks_total` | Counter | Validation checks performed | `worker_id`, `validator_type` |
| `validation_failures_total` | Counter | Validation failures | `worker_id`, `validator_type` |

### System Metrics

| Metric Name | Type | Description | Labels |
|------------|------|-------------|--------|
| `queue_depth` | Gauge | Current job queue depth | `worker_id` |
| `active_jobs` | Gauge | Active translation jobs | `worker_id` |
| `disk_usage_percent` | Gauge | Disk usage percentage | `worker_id` |
| `memory_usage_percent` | Gauge | Memory usage percentage | `worker_id` |

### Derived Metrics

These metrics are calculated from other metrics:

| Metric Name | Calculation | Description |
|------------|-------------|-------------|
| `tm_hit_rate` | `(l1_hits + l2_hits + l3_hits) / tm_lookups_total` | Percentage of TM hits |
| `translation_success_rate` | `translations_success / translations_total` | Percentage of successful translations |
| `translation_error_rate` | `translations_failed / translations_total` | Percentage of failed translations |

## Using Metrics

### In Python Code

```python
from src.observability.metrics import get_metrics

# Get global metrics instance
metrics = get_metrics()

# Increment a counter
metrics.increment("translations_total")
metrics.increment("tm_hits_l1")

# Set a gauge
metrics.set_gauge("queue_depth", 42)
metrics.set_gauge("memory_usage_percent", 65.5)

# Observe a value in histogram
metrics.observe("translation_duration_seconds", 1.5)
metrics.observe("tm_lookup_duration_seconds", 0.05)

# Get statistics
stats = metrics.get_stats_summary()
print(f"TM hit rate: {stats['tm']['hit_rate']:.2%}")
print(f"Success rate: {stats['translations']['success_rate']:.2%}")
```

### With Labels

```python
# Register metric with specific labels
metrics.register_counter(
    "translation_requests",
    "Translation requests by language pair",
    labels={"worker_id": "worker-1", "language_pair": "en-es"}
)

# Increment with labels
metrics.increment(
    "translation_requests",
    labels={"language_pair": "en-es"}
)
```

### Generate Reports

```bash
# Text report for last hour
python scripts/analysis/generate_metrics_report.py --since 1h

# JSON report for last 24 hours
python scripts/analysis/generate_metrics_report.py --since 24h --format json

# Prometheus format export
python scripts/analysis/generate_metrics_report.py --format prometheus

# Save to file
python scripts/analysis/generate_metrics_report.py --since 24h --output report.txt
```

### Query Prometheus

```promql
# TM hit rate
(sum(rate(tm_hits_l1[5m])) + sum(rate(tm_hits_l2[5m])) + sum(rate(tm_hits_l3[5m]))) / sum(rate(tm_lookups_total[5m]))

# Translation error rate
rate(translations_failed[5m]) / rate(translations_total[5m])

# 95th percentile translation time
histogram_quantile(0.95, rate(translation_duration_seconds_bucket[5m]))

# Average queue depth over last hour
avg_over_time(queue_depth[1h])
```

## Alerting

### Alert Rules

The system includes comprehensive alert rules in `docker/prometheus/alert_rules.yml`:

#### Critical Alerts (Immediate Action Required)

- **CriticalTranslationFailureRate**: >1 error/sec for 2 minutes
- **WorkerDown**: Worker down for 2 minutes
- **CriticalQueueDepth**: >5000 jobs in queue for 5 minutes
- **CriticalMemoryUsage**: >95% memory usage for 2 minutes
- **CriticalDiskSpace**: >95% disk usage for 2 minutes
- **VerySlowTranslationPerformance**: 95th percentile >30s for 5 minutes

#### Warning Alerts (Investigation Needed)

- **HighTranslationFailureRate**: >0.1 error/sec for 5 minutes
- **LowTMHitRate**: <30% hit rate for 10 minutes
- **TMErrorRate**: >0.05 error/sec for 5 minutes
- **ModelErrorRate**: >0.1 error/sec for 5 minutes
- **HighQueueDepth**: >1000 jobs for 15 minutes
- **HighMemoryUsage**: >80% usage for 10 minutes
- **LowDiskSpace**: >85% usage for 5 minutes
- **SlowTranslationPerformance**: 95th percentile >10s for 10 minutes
- **HighValidationFailureRate**: >10% failures for 5 minutes

#### Info Alerts (Awareness)

- **LowTMHitRate**: <30% hit rate for 10 minutes
- **L1CacheFull**: >9500 entries (limit 10000)
- **L2DatabaseLarge**: >10GB database size

### Alert Configuration

Alerts include runbook URLs pointing to troubleshooting documentation:

```yaml
- alert: HighTranslationFailureRate
  expr: rate(translation_errors_total[5m]) > 0.1
  for: 5m
  labels:
    severity: warning
    component: translation_engine
  annotations:
    summary: "High translation failure rate detected"
    description: "Translation failure rate is {{ $value | humanize }} errors/sec"
    runbook_url: "https://docs/runbooks/TROUBLESHOOTING.md#high-translation-failure-rate"
```

## Performance Impact

Metrics collection is designed to have minimal performance impact:

- **Async Collection**: Metrics are collected asynchronously
- **In-Memory Storage**: Metrics stored in memory with thread-safe access
- **Efficient Export**: Prometheus export is optimized for speed
- **Push Gateway**: Optional push to Prometheus Pushgateway

### Benchmark Results

- 10,000 metric operations: <1 second
- Prometheus export (100 metrics): <0.1 seconds
- Memory overhead: ~1-2 MB per worker

## Grafana Dashboards

### Recommended Dashboards

1. **Translation Overview**
   - Translation rate (ops/sec)
   - Success rate
   - Error rate
   - Queue depth

2. **Translation Memory Performance**
   - TM hit rate by layer (L1/L2/L3)
   - TM lookup latency
   - Cache size and eviction rate

3. **Model Performance**
   - Model translation latency
   - Model load count
   - Model memory usage
   - Model error rate

4. **System Health**
   - CPU usage
   - Memory usage
   - Disk usage
   - Network I/O

### Example Queries

```promql
# Translation rate
rate(translations_total[5m])

# TM hit rate by layer
sum(rate(tm_hits_l1[5m])) / sum(rate(tm_lookups_total[5m]))
sum(rate(tm_hits_l2[5m])) / sum(rate(tm_lookups_total[5m]))
sum(rate(tm_hits_l3[5m])) / sum(rate(tm_lookups_total[5m]))

# Translation latency percentiles
histogram_quantile(0.50, rate(translation_duration_seconds_bucket[5m]))
histogram_quantile(0.95, rate(translation_duration_seconds_bucket[5m]))
histogram_quantile(0.99, rate(translation_duration_seconds_bucket[5m]))
```

## Best Practices

### Metric Naming

- Use descriptive names: `translations_total` not `trans_count`
- Include units: `_seconds`, `_bytes`, `_percent`
- Use consistent prefixes: `tm_*` for TM metrics, `model_*` for model metrics

### Labels

- Keep labels low cardinality (<100 values)
- Don't use unbounded labels (user IDs, file paths)
- Use labels for dimensions: `language_pair`, `model_type`, `tm_layer`

### Collection

- Collect metrics at decision points
- Don't collect too frequently (adds overhead)
- Use histograms for timing, not gauges

### Alerting

- Alert on symptoms, not causes
- Set appropriate thresholds and durations
- Include actionable information in alerts
- Link to runbooks for remediation

## Troubleshooting

### No Metrics Appearing

1. Check metrics collector is initialized:
   ```python
   from src.observability.metrics import get_metrics
   metrics = get_metrics()
   print(metrics.export_prometheus())
   ```

2. Verify Prometheus is scraping:
   ```bash
   curl http://localhost:9090/api/v1/targets
   ```

3. Check for errors in logs:
   ```bash
   grep -i "metric" data/logs/translation.log
   ```

### High Metrics Collection Overhead

1. Reduce push frequency:
   ```python
   metrics = init_metrics(push_interval=300)  # 5 minutes
   ```

2. Disable push for workers:
   ```python
   metrics = init_metrics(enable_push=False)
   ```

3. Use sampling for high-frequency metrics

### Metrics Not Accurate

1. Verify counter increments:
   ```python
   metrics.increment("translations_total", 1)  # Not 0
   ```

2. Check for race conditions in threaded code

3. Ensure metrics are properly labeled

## Agent Metrics API

For external per-run metrics posting to Google Sheets (item counts, LLM token usage, scope), see: [Agent Metrics API](../observability/agent-metrics-api.md).

This is separate from Prometheus metrics and is currently in dry-run mode.

## References

- [Prometheus Documentation](https://prometheus.io/docs/)
- [Grafana Documentation](https://grafana.com/docs/)
- [Metrics Best Practices](https://prometheus.io/docs/practices/naming/)
- [Alert Rules](../../docker/prometheus/alert_rules.yml)
- [Troubleshooting Guide](./troubleshooting.md)
