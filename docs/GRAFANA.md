# Grafana Dashboards for Hugo Translation System

This document describes the Grafana dashboards available for monitoring the Hugo Translation System.

## Overview

Grafana provides visual dashboards for monitoring translation system metrics collected by Prometheus. The dashboards auto-provision when you start Grafana with Docker Compose.

## Quick Start

### 1. Start Grafana

```bash
# Start Grafana with the monitoring profile
docker-compose --profile monitoring up -d grafana

# This will also start Prometheus and Pushgateway if not already running
```

### 2. Access Grafana

Open your browser and navigate to:
```
http://localhost:3000
```

**Default credentials:**
- Username: `admin`
- Password: `admin`

You'll be prompted to change the password on first login.

### 3. View Dashboards

Navigate to:
- **Dashboards** → **Browse** → **Hugo Translator** folder

Available dashboards:
1. **Translation System Overview** - System health and performance
2. **Translation Memory Performance** - TM hit rates and layer performance

## Dashboard Details

### 1. Translation System Overview

**UID:** `translation-overview`

**Purpose:** Monitor overall system health and translation performance.

**Key Metrics:**

#### System Health
- **Translation Rate**: Translations per second (total, successful, failed)
- **Success Rate**: Percentage of successful translations (gauge)
- **Job Queue Status**: Current queue depth and active jobs

#### Performance
- **Translation Duration (Percentiles)**: p50, p95, p99 latencies
- **Model Translation Duration**: Model inference latencies
- **Translation Results Distribution**: Pie chart of success vs. failed
- **Model Load Events**: Frequency of model loading operations

#### Time Ranges
- Default: Last 1 hour
- Available: 1h, 24h, 7d (via time picker)
- Auto-refresh: Every 30 seconds

#### Alerts/Thresholds
- Success Rate: Red (<90%), Yellow (90-98%), Green (>98%)
- Queue Depth: Green (<50), Yellow (50-100), Red (>100)

### 2. Translation Memory Performance

**UID:** `tm-performance`

**Purpose:** Monitor TM hit rates and layer-specific performance.

**Key Metrics:**

#### TM Hit Rates
- **TM Hit Rate by Layer**: Stacked area chart showing:
  - L1 Cache Hits (green)
  - L2 Exact Hits (blue)
  - L3 Semantic Hits (yellow)
  - Misses requiring model translation (red)

- **Overall TM Hit Rate**: Percentage gauge
  - Red: <50%
  - Yellow: 50-80%
  - Green: >80%

#### Cache Performance
- **L1 Cache Size**: Current number of entries
  - Thresholds: Green (<8000), Yellow (8000-9500), Red (>9500)

#### Latency
- **TM Lookup Duration**: p50, p95, p99 percentiles
- Helps identify performance bottlenecks in TM layers

#### Distribution
- **TM Layer Distribution**: Pie chart showing proportion of:
  - L1 Cache hits
  - L2 Exact matches
  - L3 Semantic matches
  - Model translations (misses)

#### Statistics
- **TM Statistics by Worker**: Detailed table showing:
  - Total lookups per worker
  - Hits by layer (L1, L2, L3)
  - Miss counts

#### Time Ranges
- Default: Last 1 hour
- Auto-refresh: Every 30 seconds

#### Interpretation
- **High L1 hits**: Good - cache is working effectively
- **High L3 hits**: Semantic TM is finding good fuzzy matches
- **High misses**: Consider:
  - Expanding TM database
  - Adjusting semantic threshold
  - Reviewing translation patterns

## Metrics Reference

All metrics are collected via Prometheus from the translation workers and orchestrator.

### Counter Metrics
| Metric Name | Description | Labels |
|------------|-------------|---------|
| `translations_total` | Total translation operations | `worker_id` |
| `translations_success` | Successful translations | `worker_id` |
| `translations_failed` | Failed translations | `worker_id` |
| `tm_lookups_total` | Total TM lookups | `worker_id` |
| `tm_hits_l1` | L1 cache hits | `worker_id` |
| `tm_hits_l2` | L2 exact match hits | `worker_id` |
| `tm_hits_l3` | L3 semantic match hits | `worker_id` |
| `tm_misses` | TM misses (model required) | `worker_id` |
| `model_translations_total` | Model translation calls | `worker_id` |
| `model_load_count` | Model load events | `worker_id` |

### Gauge Metrics
| Metric Name | Description | Labels |
|------------|-------------|---------|
| `queue_depth` | Current job queue depth | `worker_id` |
| `active_jobs` | Active translation jobs | `worker_id` |
| `tm_cache_size` | L1 cache size | `worker_id` |

### Histogram Metrics
| Metric Name | Description | Labels |
|------------|-------------|---------|
| `translation_duration_seconds` | Translation operation duration | `worker_id` |
| `tm_lookup_duration_seconds` | TM lookup duration | `worker_id` |
| `model_translation_duration_seconds` | Model translation duration | `worker_id` |

## Customization

### Modifying Dashboards

1. **In Grafana UI:**
   - Click dashboard title → Settings → JSON Model
   - Edit and save
   - Export to JSON file

2. **Update Dashboard Files:**
   ```bash
   # Replace the JSON file in docker/grafana/dashboards/
   cp /path/to/exported.json docker/grafana/dashboards/translation_overview.json
   ```

3. **Reload:**
   - Dashboards auto-reload every 30 seconds
   - Or restart Grafana: `docker-compose --profile monitoring restart grafana`

### Adding New Panels

Example: Add a panel for error rate

```json
{
  "datasource": "Prometheus",
  "targets": [
    {
      "expr": "rate(translations_failed[5m]) / rate(translations_total[5m]) * 100",
      "refId": "A",
      "legendFormat": "Error Rate %"
    }
  ],
  "title": "Translation Error Rate",
  "type": "timeseries"
}
```

### Creating Alerts

Grafana supports alerting based on metrics:

1. Navigate to **Alerting** → **Alert rules**
2. Create rule based on query
3. Set threshold and notification channel

Example alert:
```
Alert: High translation error rate
Condition: rate(translations_failed[5m]) / rate(translations_total[5m]) > 0.05
Threshold: 5% error rate
Action: Send notification
```

## Architecture

### Data Flow

```
Translation Workers
  ↓ (push metrics every 60s)
Prometheus Pushgateway
  ↓ (scrape every 15s)
Prometheus
  ↓ (query)
Grafana Dashboards
```

### Provisioning

Dashboards are automatically provisioned via:

1. **Datasource Config**: `docker/grafana/provisioning/datasources/prometheus.yml`
   - Configures Prometheus as default datasource
   - URL: `http://prometheus:9090`

2. **Dashboard Provisioning**: `docker/grafana/provisioning/dashboards/dashboards.yml`
   - Auto-loads dashboards from folder
   - Update interval: 30 seconds

3. **Dashboard JSONs**: `docker/grafana/dashboards/*.json`
   - `translation_overview.json`
   - `tm_performance.json`

## Troubleshooting

### Dashboard Not Appearing

1. **Check Grafana logs:**
   ```bash
   docker logs translator-grafana
   ```

2. **Verify provisioning:**
   ```bash
   # Check if files are mounted
   docker exec translator-grafana ls -la /etc/grafana/provisioning/dashboards
   ```

3. **Restart Grafana:**
   ```bash
   docker-compose --profile monitoring restart grafana
   ```

### No Data in Panels

1. **Check Prometheus:**
   - Open `http://localhost:9090`
   - Verify metrics exist: `translations_total`

2. **Check Pushgateway:**
   - Open `http://localhost:9091`
   - Verify workers are pushing metrics

3. **Check worker metrics:**
   ```bash
   docker logs translator-worker-cpu-1 | grep metrics
   ```

### Connection Issues

1. **Verify Prometheus datasource:**
   - Grafana → Configuration → Data Sources → Prometheus
   - Test connection
   - URL should be: `http://prometheus:9090`

2. **Check network:**
   ```bash
   docker network inspect hugo-translator_translator_net
   ```

## Performance Optimization

### Dashboard Performance

For large deployments:

1. **Adjust refresh interval:**
   - Dashboard settings → Auto refresh
   - Set to 1m or 5m instead of 30s

2. **Limit time range:**
   - Use shorter time ranges for real-time monitoring
   - Use longer ranges for historical analysis

3. **Reduce panel count:**
   - Consider separate dashboards for different purposes
   - Use dashboard variables to filter

### Metric Retention

Prometheus retention (configured in docker-compose.yml):
```yaml
command:
  - '--storage.tsdb.retention.time=30d'
```

Adjust based on storage capacity:
- **7d**: Minimal (for active monitoring)
- **30d**: Default (good for trend analysis)
- **90d**: Extended (for long-term tracking)

## Best Practices

1. **Regular Monitoring:**
   - Check dashboards daily during active translation
   - Review TM hit rates to optimize performance

2. **Baseline Metrics:**
   - Establish baseline performance metrics
   - Set alerts for significant deviations

3. **Capacity Planning:**
   - Monitor queue depth and active jobs
   - Scale workers if consistently high

4. **TM Optimization:**
   - High miss rate → expand TM database
   - Low L1 hits → increase cache size
   - Low L3 hits → adjust semantic threshold

5. **Performance Tuning:**
   - Monitor translation duration percentiles
   - Identify slow workers or models
   - Optimize batch sizes based on latency

## Related Documentation

- [Metrics Collection](../src/observability/metrics.py) - Metrics implementation
- [Prometheus Configuration](../docker/prometheus/prometheus.yml) - Prometheus setup
- [Docker Compose](../docker-compose.yml) - Service configuration

## Support

For issues or questions:
1. Check Grafana logs: `docker logs translator-grafana`
2. Verify Prometheus metrics: `http://localhost:9090/targets`
3. Review this documentation
4. Open GitHub issue with dashboard JSON and error logs
