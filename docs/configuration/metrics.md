# Metrics Configuration

## Overview

The metrics configuration system controls timing metrics collection, storage limits, and performance thresholds across the translation system. It provides configurable bounded storage to prevent memory leaks in long-running processes while maintaining statistical accuracy.

## Configuration File

Location: `config/metrics.yaml`

```yaml
metrics:
  # Bounded storage limits
  storage:
    translation_engine:
      retry_metrics_maxlen: 1000

    l3_semantic:
      timing_metrics_maxlen: 10000

    batch_optimizer:
      timing_metrics_maxlen: 5000

  # Statistics configuration
  statistics:
    percentiles: [0.50, 0.95, 0.99]
    min_samples_for_p95: 20
    min_samples_for_p99: 100

  # Performance thresholds (milliseconds)
  thresholds:
    l3_search_timeout_ms: 100
    l3_search_warning_ms: 50
    retry_max_duration_ms: 30000
    retry_warning_duration_ms: 10000
    batch_prepare_warning_ms: 1000
    batch_process_warning_ms: 5000
    oom_recovery_max_ms: 5000
```

## Configuration Sections

### Storage Limits

Controls the maximum number of timing samples stored in memory using bounded `collections.deque` structures.

#### translation_engine

- **retry_metrics_maxlen** (default: 1000)
  - Number of retry timing samples to keep
  - Memory usage: ~8KB (8 bytes per float × 1000)
  - Recommendation: 1000-2000 for typical workloads

#### l3_semantic

- **timing_metrics_maxlen** (default: 10000)
  - Number of timing samples for L3 semantic operations
  - Higher value due to high operation frequency
  - Memory usage: ~80KB per metric (3 metrics = 240KB total)
  - Recommendation: 10000-20000 for high-traffic scenarios

#### batch_optimizer

- **timing_metrics_maxlen** (default: 5000)
  - Number of timing samples for batch processing operations
  - Memory usage: ~40KB per metric (4 metrics = 160KB total)
  - Recommendation: 5000-10000 depending on batch size and frequency

### Statistics Configuration

Controls how statistics are calculated from timing data.

- **percentiles** (default: [0.50, 0.95, 0.99])
  - List of percentiles to calculate
  - Values must be in range 0.0-1.0
  - Common values: 0.50 (median), 0.95 (p95), 0.99 (p99)

- **min_samples_for_p95** (default: 20)
  - Minimum samples required before calculating p95
  - Falls back to max value if fewer samples exist

- **min_samples_for_p99** (default: 100)
  - Minimum samples required before calculating p99
  - Falls back to max value if fewer samples exist

### Performance Thresholds

Warning and timeout thresholds for performance monitoring (all values in milliseconds).

#### L3 Semantic Search

- **l3_search_timeout_ms** (default: 100)
  - Maximum acceptable search duration
  - Operations exceeding this may timeout

- **l3_search_warning_ms** (default: 50)
  - Warning threshold for slow searches
  - Log warning if search exceeds this duration

#### Retry Operations

- **retry_max_duration_ms** (default: 30000)
  - Maximum total retry duration (30 seconds)
  - Abort retries if total duration exceeds this

- **retry_warning_duration_ms** (default: 10000)
  - Warning threshold for retry duration (10 seconds)
  - Log warning if retries exceed this duration

#### Batch Processing

- **batch_prepare_warning_ms** (default: 1000)
  - Warning threshold for batch preparation (1 second)

- **batch_process_warning_ms** (default: 5000)
  - Warning threshold for batch processing (5 seconds)

#### OOM Recovery

- **oom_recovery_max_ms** (default: 5000)
  - Maximum time for OOM recovery operations (5 seconds)

## Environment Variable Overrides

Override configuration values at runtime using environment variables:

```bash
# Override retry metrics storage limit
export METRICS_ENGINE_MAXLEN=2000

# Override L3 semantic metrics storage limit
export METRICS_L3_MAXLEN=15000

# Override batch optimizer metrics storage limit
export METRICS_BATCH_MAXLEN=7500

# Override percentiles (comma-separated)
export METRICS_PERCENTILES="0.5,0.9,0.95,0.99"
```

### Example

```bash
# Increase all storage limits for high-traffic production
export METRICS_ENGINE_MAXLEN=2000
export METRICS_L3_MAXLEN=20000
export METRICS_BATCH_MAXLEN=10000

python -m src.cli translate --site-id blog.example.com ...
```

## Usage in Code

### Accessing Metrics Configuration

```python
from src.utils.config_loader import get_metrics_config

# Get configuration
config = get_metrics_config()

# Access storage limits
retry_maxlen = config["metrics"]["storage"]["translation_engine"]["retry_metrics_maxlen"]
l3_maxlen = config["metrics"]["storage"]["l3_semantic"]["timing_metrics_maxlen"]

# Access thresholds
timeout = config["metrics"]["thresholds"]["l3_search_timeout_ms"]
```

### Using in Component Initialization

```python
from collections import deque
from src.utils.config_loader import get_metrics_config

class MyComponent:
    def __init__(self):
        # Load metrics config
        metrics_config = get_metrics_config()
        maxlen = metrics_config["metrics"]["storage"]["my_component"]["timing_maxlen"]

        # Create bounded storage
        self._timing_metrics = {
            "operation_ms": deque(maxlen=maxlen),
        }
```

## Memory Impact

### Before Bounded Storage (Unbounded Lists)

- **Translation Engine**: ~8MB per 1M retries
- **L3 Semantic**: ~80MB per 10M operations (3 metrics)
- **Batch Optimizer**: ~40MB per 1M batches (4 metrics)
- **Total**: Unbounded growth → OOM after days/weeks

### After Bounded Storage (with default limits)

- **Translation Engine**: ~8KB (bounded to 1000 samples)
- **L3 Semantic**: ~240KB (bounded to 10000 samples × 3 metrics)
- **Batch Optimizer**: ~160KB (bounded to 5000 samples × 4 metrics)
- **Total**: ~408KB (fixed, regardless of runtime duration)

### Memory Savings

- **100x reduction** for typical workloads
- **1000x reduction** for long-running processes (weeks)
- Prevents OOM crashes in production

## Tuning Guidelines

### Low-Memory Environments

```yaml
metrics:
  storage:
    translation_engine:
      retry_metrics_maxlen: 500
    l3_semantic:
      timing_metrics_maxlen: 5000
    batch_optimizer:
      timing_metrics_maxlen: 2500
```

- Reduces memory from 408KB to 204KB
- Still provides good statistical accuracy

### High-Traffic Production

```yaml
metrics:
  storage:
    translation_engine:
      retry_metrics_maxlen: 2000
    l3_semantic:
      timing_metrics_maxlen: 20000
    batch_optimizer:
      timing_metrics_maxlen: 10000
```

- Increases memory to 816KB
- Better statistical accuracy for p99
- Recommended for high-volume scenarios

### Development/Testing

```yaml
metrics:
  storage:
    translation_engine:
      retry_metrics_maxlen: 100
    l3_semantic:
      timing_metrics_maxlen: 1000
    batch_optimizer:
      timing_metrics_maxlen: 500
```

- Minimal memory footprint (40KB)
- Sufficient for testing and debugging

## Validation

### Schema Validation

The configuration loader validates:

- All maxlen values are positive integers
- Percentiles are in range 0.0-1.0
- Threshold values are positive numbers

Invalid values are rejected with clear error messages.

### Default Fallback

If configuration file is missing or invalid, the system uses these defaults:

- retry_metrics_maxlen: 1000
- timing_metrics_maxlen (L3): 10000
- timing_metrics_maxlen (Batch): 5000
- percentiles: [0.50, 0.95, 0.99]
- All thresholds as documented above

## Monitoring

### Checking Current Configuration

```python
from src.utils.config_loader import get_metrics_config

config = get_metrics_config()
print(config["metrics"])
```

### Reloading Configuration

```python
from src.utils.config_loader import ConfigService
from pathlib import Path

config_service = ConfigService(Path("config"))
config = config_service.reload_metrics_config()  # Bypasses cache
```

## Related Documentation

- [Benchmarking System](../architecture/benchmarking-system.md) - Overall benchmarking architecture
- [Translation Memory](../architecture/translation-memory.md) - L3 semantic cache details
- [Benchmarking Operations](../operations/benchmarking-operations.md) - Operational procedures

## Troubleshooting

### Memory Usage Still Growing

**Symptoms**: Memory usage continues to grow despite bounded storage

**Causes**:
1. Environment variable override not applied
2. Old code still using unbounded lists
3. Other memory leaks unrelated to metrics

**Solutions**:
```bash
# Verify config is loaded
python -c "from src.utils.config_loader import get_metrics_config; print(get_metrics_config())"

# Check environment variables
env | grep METRICS

# Verify code is using deque(maxlen=N)
grep -r "deque(maxlen=" src/
```

### Statistics Inaccurate

**Symptoms**: P95/P99 values seem incorrect

**Causes**:
1. maxlen too small for percentile calculation
2. Insufficient samples collected

**Solutions**:
```yaml
# Increase storage limits
metrics:
  storage:
    l3_semantic:
      timing_metrics_maxlen: 20000  # Increase for better accuracy

  statistics:
    min_samples_for_p99: 200  # Require more samples
```

### Performance Degradation

**Symptoms**: Slower performance after enabling metrics

**Causes**:
1. Excessive logging at warning thresholds
2. Thresholds set too low

**Solutions**:
```yaml
# Increase thresholds to reduce warnings
metrics:
  thresholds:
    l3_search_warning_ms: 100  # Increase from 50
    batch_prepare_warning_ms: 2000  # Increase from 1000
```

## Best Practices

1. **Start with defaults**: Use default values unless you have specific requirements
2. **Monitor memory**: Track memory usage in production to tune limits
3. **Use environment variables**: Override config in production without code changes
4. **Document changes**: Add comments when deviating from defaults
5. **Test changes**: Validate configuration changes in staging before production
6. **Review periodically**: Adjust limits as workload patterns change

## Change History

- **2025-12-24**: Initial metrics configuration system (CFG-01)
  - Added configurable storage limits
  - Added environment variable overrides
  - Added validation and defaults
  - Replaced hardcoded values across all components
