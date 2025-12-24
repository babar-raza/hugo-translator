# TM Statistics Monitoring Guide

**Version:** 2.0
**Last Updated:** 2025-12-24
**Related Guides:** [TM Architecture](../architecture/translation-memory.md) | [TM Maintenance](../operations/tm-maintenance.md) | [TM Performance Tuning](../operations/tm-performance-tuning.md)

## Overview

Translation Memory (TM) statistics monitoring provides critical operational visibility into the performance and health of the Hugo Translation System's multi-layer caching architecture. This guide explains how to monitor TM hit rates, cache performance, layer utilization, and integrity metrics to ensure optimal translation efficiency and system reliability.

## TM Architecture Overview

The system employs a 3-layer TM architecture designed for maximum performance:

- **L1 Cache**: In-memory LRU cache for frequently accessed translations (fastest access)
- **L2 Persistent**: LMDB-based disk storage for all exact-match translations
- **L3 Semantic**: FAISS-based vector similarity search for fuzzy/semantic matches

Effective monitoring ensures each layer operates efficiently and provides appropriate fallback when higher layers miss.

## Key Metrics to Monitor

### TM Hit Rates

**Definition**: Percentage of translation requests served from TM layers vs. requiring model translation.

**Critical Thresholds**:
- **Good**: >80% overall hit rate
- **Warning**: 30-80% hit rate (investigate)
- **Critical**: <30% hit rate (immediate action required)

**Monitoring Commands**:
```bash
# Check current hit rate via metrics API
curl http://localhost:9090/api/v1/query?query=tm_hit_rate

# Generate TM statistics report
python scripts/generate_metrics_report.py --since 1h --format json | jq '.tm'
```

### Cache Performance Metrics

**L1 Cache Size**: Current number of entries in memory cache
- **Threshold**: Warning at >8,000 entries, Critical at >9,500 entries (limit: 10,000)

**L1 Hit Rate**: Percentage of lookups served by L1 cache
- **Expected**: 60-80% of total TM hits in steady state

**Lookup Latency**: Time to query TM layers
- **L1**: <1ms typical
- **L2**: <10ms typical
- **L3**: <100ms typical

### Layer Utilization

**L2 Database Size**: Total size of persistent TM storage
- **Info Alert**: >10GB (consider maintenance)
- **Growth Rate**: Monitor for unexpected increases

**L3 Index Size**: Number of semantic vectors indexed
- **Correlation**: Should grow with L2 database size

### Integrity & Health Metrics

**Cache Health Percentage**: Percentage of valid entries in L2 cache
- **Healthy**: 100% (no corruption)
- **Warning**: 95-99.9% (minor corruption, run repair)
- **Critical**: <95% (significant corruption, restore from backup)

**Corrupted Entries**: Number of invalid entries detected
- **Expected**: 0 entries
- **Action Threshold**: >10 entries (investigate)

**Last Integrity Check**: Timestamp of most recent health scan
- **Recommended**: Weekly automated checks
- **Alert**: No check in >30 days

**Monitoring Commands**:
```bash
# Quick health check
venv/Scripts/python.exe -c "
from src.tm.integrity import check_cache_integrity
from pathlib import Path
report = check_cache_integrity(Path('data/tm/l2_lmdb'))
print(f'Health: {report.health_percentage:.1f}%')
print(f'Status: {\"HEALTHY\" if report.is_healthy else \"CORRUPTED\"}')"

# Detailed integrity report
python scripts/check_tm_integrity.py --output integrity_report.json
```

**See also:** [TM Maintenance - Integrity Checks](../operations/tm-maintenance.md#integrity-checks)

---

## Accessing TM Statistics

### Grafana Dashboard

The primary monitoring interface is the "Translation Memory Performance" dashboard:

```bash
# Access Grafana (assuming local deployment)
open http://localhost:3000/d/tm-performance
```

**Key Dashboard Panels**:

1. **TM Hit Rate by Layer**
   - Shows rate of hits/misses per second by layer
   - Green: L1 cache hits
   - Blue: L2 exact hits
   - Yellow: L3 semantic hits
   - Red: Model translations (misses)

2. **Overall TM Hit Rate**
   - Gauge showing total hit percentage
   - Color-coded: Red (<50%), Yellow (50-80%), Green (>80%)

3. **L1 Cache Size**
   - Current cache utilization
   - Thresholds: Yellow (8K), Red (9.5K)

4. **TM Lookup Duration**
   - Percentiles (p50, p95, p99) for lookup times
   - Helps identify performance bottlenecks

5. **TM Layer Distribution**
   - Pie chart showing proportion of hits by layer
   - Useful for understanding cache effectiveness

6. **TM Lookup Rate**
   - Operations per second by worker
   - Helps identify load distribution

7. **TM Statistics by Worker**
   - Table showing per-worker TM performance
   - Includes total lookups, hits by layer, and misses

### Prometheus Queries

**Overall Hit Rate**:
```promql
(sum(rate(tm_hits_l1[5m])) + sum(rate(tm_hits_l2[5m])) + sum(rate(tm_hits_l3[5m]))) / sum(rate(tm_lookups_total[5m])) * 100
```

**Layer-Specific Hit Rates**:
```promql
# L1 hit rate
sum(rate(tm_hits_l1[5m])) / sum(rate(tm_lookups_total[5m])) * 100

# L2 hit rate
sum(rate(tm_hits_l2[5m])) / sum(rate(tm_lookups_total[5m])) * 100

# L3 hit rate
sum(rate(tm_hits_l3[5m])) / sum(rate(tm_lookups_total[5m])) * 100
```

**Cache Performance**:
```promql
# Cache size
sum(tm_cache_size)

# Lookup latency percentiles
histogram_quantile(0.95, rate(tm_lookup_duration_seconds_bucket[5m]))
```

### Command Line Reports

**Generate TM Performance Report**:
```bash
# Last hour summary
python scripts/generate_metrics_report.py --since 1h --output tm_report.txt

# JSON format for analysis
python scripts/generate_metrics_report.py --since 24h --format json --output tm_stats.json

# Prometheus export format
python scripts/generate_metrics_report.py --format prometheus > tm_metrics.txt
```

## Alert Monitoring

### TM-Specific Alerts

**Low TM Hit Rate** (Info):
- **Trigger**: <30% hit rate for 10 minutes
- **Action**: Review TM content relevance, consider rebuilding index

**Very Low TM Hit Rate** (Warning):
- **Trigger**: <10% hit rate for 5 minutes
- **Action**: Check TM database health, verify cache loading

**TM Error Rate** (Warning):
- **Trigger**: >0.05 errors/sec for 5 minutes
- **Action**: Investigate TM database connectivity, check disk space

**L1 Cache Full** (Info):
- **Trigger**: >9,500 entries for 5 minutes
- **Action**: Monitor for increased eviction, consider cache size increase

**L2 Database Large** (Info):
- **Trigger**: >10GB for 1 hour
- **Action**: Plan TM maintenance, consider archiving old entries

### Alert Response Procedures

**Low Hit Rate Investigation**:
```bash
# Check recent TM activity
python scripts/analyze_tm_usage.py --since 1h

# Verify TM database integrity
python scripts/check_tm_health.py

# Compare with baseline performance
python scripts/benchmark_tm_performance.py
```

## Interpreting Metrics

### Normal Operating Patterns

**High Hit Rate Scenario**:
- Overall: 85-95%
- L1: 70% of total hits
- L2: 20% of total hits
- L3: 10% of total hits
- **Interpretation**: Well-populated TM, efficient caching

**Moderate Hit Rate Scenario**:
- Overall: 60-85%
- L1: 50% of total hits
- L2: 35% of total hits
- L3: 15% of total hits
- **Interpretation**: Growing TM, normal for new content

**Low Hit Rate Scenario**:
- Overall: <60%
- L1: <40% of total hits
- L2: <40% of total hits
- L3: >20% of total hits
- **Interpretation**: New content domains, TM rebuild needed

### Performance Degradation Indicators

**Increasing Lookup Latency**:
- L1 >5ms: Memory pressure or cache contention
- L2 >50ms: Disk I/O issues or database fragmentation
- L3 >500ms: Index corruption or insufficient compute resources

**Cache Thrashing**:
- High L1 eviction rate with stable hit rate
- Frequent cache size fluctuations
- **Cause**: Working set larger than cache capacity

**Layer Imbalance**:
- Very high L3 utilization (>50% of hits)
- Low L1 hit rate despite high overall hits
- **Cause**: Cache not warming up or poor access patterns

## Troubleshooting Common Issues

### Low TM Hit Rate

**Symptoms**:
- Overall hit rate <50%
- High model translation volume
- Slow translation performance

**Diagnostic Steps**:
```bash
# Check TM content relevance
python scripts/analyze_tm_content.py --sample-size 1000

# Verify TM loading
python scripts/check_tm_status.py

# Compare with baseline
python scripts/benchmark_translation.py --baseline
```

**Common Causes & Solutions**:
- **New Content Domain**: Build TM for new content types
- **TM Corruption**: Restore from backup, rebuild index
- **Cache Issues**: Clear L1 cache, restart workers

### High TM Lookup Latency

**Symptoms**:
- p95 lookup time >100ms
- Translation throughput reduced
- Worker CPU usage high

**Diagnostic Steps**:
```bash
# Profile TM operations
python scripts/profile_tm_performance.py

# Check system resources
python scripts/monitor_system_resources.py

# Analyze slow queries
python scripts/analyze_slow_tm_queries.py
```

**Common Causes & Solutions**:
- **Disk I/O Contention**: Move TM to faster storage
- **Memory Pressure**: Increase worker memory allocation
- **Index Fragmentation**: Rebuild L3 semantic index

### Cache Performance Issues

**Symptoms**:
- L1 cache frequently full
- High eviction rate
- Inconsistent hit rates

**Diagnostic Steps**:
```bash
# Analyze cache access patterns
python scripts/analyze_cache_patterns.py

# Check cache configuration
python scripts/validate_cache_config.py

# Monitor eviction statistics
python scripts/monitor_cache_eviction.py
```

**Common Causes & Solutions**:
- **Small Cache Size**: Increase L1 cache limit
- **Poor Access Patterns**: Implement cache warming
- **Memory Leaks**: Restart workers, monitor memory usage

## Best Practices

### Monitoring Setup

**Dashboard Customization**:
- Set up alerts for your specific thresholds
- Create custom panels for business-specific metrics
- Archive historical data for trend analysis

**Regular Reviews**:
- Weekly: Review hit rate trends and layer utilization
- Monthly: Analyze TM growth and maintenance needs
- Quarterly: Evaluate TM rebuild requirements

### Performance Optimization

**Cache Tuning**:
- Monitor working set size vs. cache capacity
- Adjust L1 cache size based on memory availability
- Implement cache warming for predictable workloads

**TM Maintenance**:
- Regular cleanup of outdated entries
- Periodic index optimization
- Backup and recovery testing

### Operational Procedures

**Daily Checks**:
```bash
# Quick health check
python scripts/check_system_health.py

# TM performance summary
python scripts/generate_metrics_report.py --since 24h | grep -A 10 "TM"
```

**Weekly Maintenance**:
```bash
# TM integrity check
python scripts/validate_tm_integrity.py

# Performance benchmarking
python scripts/benchmark_tm_performance.py --comprehensive
```

## Related Documentation

- [Metrics and Monitoring](../operations/metrics.md)
- [Grafana Dashboards](../operations/grafana.md)
- [Alert Rules](../../docker/prometheus/alert_rules.yml)
- [TM Override Modes](tm-override-modes.md)
- [Troubleshooting Guide](../operations/troubleshooting.md)
