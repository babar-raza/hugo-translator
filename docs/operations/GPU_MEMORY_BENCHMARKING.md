# GPU Memory Benchmarking - Operations Guide

## Overview

The benchmarking system automatically tracks GPU peak memory usage during CUDA-based benchmark runs. This helps identify optimal batch sizes and prevent OOM (Out-Of-Memory) errors.

## Quick Start

### Run Benchmark with GPU Memory Tracking

```bash
python -m src.benchmarking.runner \
  --model m2m100_418m \
  --device cuda \
  --batch-sizes 8,16,32,64 \
  --iterations 5 \
  --corpus small \
  --save-to-db data/benchmarks/gpu_test.db
```

**What happens**:
- System automatically resets GPU memory stats before each batch
- Tracks peak memory usage during translation
- Stores `peak_memory_mb` in BenchmarkResult
- Handles OOM errors gracefully with detailed logging

### Query GPU Memory Results

```bash
# SQLite query
sqlite3 data/benchmarks/gpu_test.db <<EOF
SELECT
    batch_size,
    AVG(peak_memory_mb) as avg_peak_mb,
    MAX(peak_memory_mb) as max_peak_mb,
    COUNT(*) as samples
FROM benchmark_results
WHERE device = 'cuda' AND peak_memory_mb IS NOT NULL
GROUP BY batch_size
ORDER BY batch_size;
EOF
```

**Expected output**:
```
batch_size | avg_peak_mb | max_peak_mb | samples
-----------|-------------|-------------|--------
8          | 512.25      | 520.10      | 50
16         | 1024.50     | 1035.20     | 50
32         | 2048.75     | 2060.45     | 50
64         | OOM         | OOM         | 0
```

## How It Works

### Automatic Tracking

The system uses PyTorch CUDA API:

```python
# Before each batch
torch.cuda.reset_peak_memory_stats()
torch.cuda.empty_cache()

# Translation happens here...

# After translation
peak_memory_bytes = torch.cuda.max_memory_allocated()
peak_memory_mb = peak_memory_bytes / (1024 ** 2)
```

### OOM Handling

When OOM occurs:

1. **Error Logged**: `ERROR: OOM at batch_size=64: CUDA out of memory`
2. **Peak Memory Captured**: `ERROR: Peak GPU memory at OOM: 2048.50 MB`
3. **GPU Cache Cleared**: `torch.cuda.empty_cache()`
4. **Error Result Created**: BenchmarkResult with `errors=['OOM at batch_size=64']`

### Device Support

| Device | GPU Tracking | peak_memory_mb |
|--------|--------------|----------------|
| `cpu` | ❌ Disabled | `None` |
| `cuda` | ✅ Enabled | Float (MB) |
| `cuda:0` | ✅ Enabled | Float (MB) |
| `cuda:1` | ✅ Enabled | Float (MB) |

## Use Cases

### 1. Find Optimal Batch Size

**Goal**: Maximize batch size without OOM.

```bash
python -m src.benchmarking.runner \
  --model facebook/nllb-200-3.3B \
  --device cuda \
  --batch-sizes 1,2,4,8,16,32,64 \
  --iterations 10 \
  --corpus medium \
  --save-to-db data/benchmarks/optimal_batch.db
```

**Analysis**:
```sql
SELECT
    batch_size,
    AVG(peak_memory_mb) as avg_peak_mb,
    COUNT(CASE WHEN errors != '[]' THEN 1 END) as error_count
FROM benchmark_results
WHERE device = 'cuda'
GROUP BY batch_size;
```

**Result**: Largest batch size with `error_count = 0`.

### 2. Compare Model Memory Footprints

**Goal**: Compare memory usage between models.

```bash
# Test model 1
python -m src.benchmarking.runner \
  --model m2m100_418m \
  --device cuda \
  --batch-sizes 16 \
  --iterations 20 \
  --save-to-db data/benchmarks/model_compare.db

# Test model 2
python -m src.benchmarking.runner \
  --model facebook/nllb-200-1.3B \
  --device cuda \
  --batch-sizes 16 \
  --iterations 20 \
  --save-to-db data/benchmarks/model_compare.db
```

**Analysis**:
```sql
SELECT
    model_id,
    AVG(peak_memory_mb) as avg_peak_mb
FROM benchmark_results
WHERE batch_size = 16
GROUP BY model_id;
```

### 3. Memory Scaling Analysis

**Goal**: Understand how memory scales with batch size.

```bash
python -m src.benchmarking.runner \
  --model m2m100_1.2b \
  --device cuda \
  --batch-sizes 1,2,4,8,16,32 \
  --iterations 30 \
  --save-to-db data/benchmarks/memory_scaling.db
```

**Analysis**:
```sql
SELECT
    batch_size,
    AVG(peak_memory_mb) as avg_peak_mb,
    AVG(peak_memory_mb) / batch_size as mb_per_item
FROM benchmark_results
WHERE device = 'cuda'
GROUP BY batch_size;
```

**Expected**: Linear scaling → constant `mb_per_item`.

## Troubleshooting

### No peak_memory_mb values

**Symptom**: All `peak_memory_mb` values are `NULL`.

**Causes**:
1. Running on CPU (expected, not an error)
2. PyTorch not installed
3. CUDA not available

**Solution**:
```bash
# Verify CUDA availability
python -c "import torch; print(f'CUDA available: {torch.cuda.is_available()}')"

# Check device
python -c "import torch; print(f'Device count: {torch.cuda.device_count()}')"
```

### OOM on small batch sizes

**Symptom**: OOM error at batch_size=1 or batch_size=2.

**Causes**:
1. Model too large for GPU
2. Other processes using GPU memory

**Solution**:
```bash
# Check GPU memory
nvidia-smi

# Kill other GPU processes if needed
# Try smaller model
python -m src.benchmarking.runner \
  --model m2m100_418m \
  --device cuda \
  --batch-sizes 1
```

### Inconsistent peak_memory_mb

**Symptom**: Large variance in peak memory for same batch size.

**Causes**:
1. Memory fragmentation
2. Background GPU processes
3. Cached allocations

**Solution**:
- Increase `--iterations` to average out variance
- Restart Python process between runs
- Use `torch.cuda.empty_cache()` (done automatically)

## Integration with Production

### Continuous Monitoring

Enable production metrics to track GPU memory in production runs:

```bash
translate-hugo \
  --input content/ \
  --output translated/ \
  --device cuda \
  --batch-size 16
```

Production ingestor automatically records peak memory (when available).

### Alerting

Monitor for increasing memory usage over time:

```sql
SELECT
    DATE(timestamp_utc) as date,
    AVG(peak_memory_mb) as avg_peak_mb
FROM benchmark_results
WHERE device = 'cuda' AND batch_size = 16
GROUP BY date
ORDER BY date DESC
LIMIT 30;
```

**Alert if**: `avg_peak_mb` increases >10% over 7 days.

## Best Practices

1. **Run calibration benchmarks** for each model + GPU combination
2. **Test multiple batch sizes** to find optimal range
3. **Use sufficient iterations** (≥20) for stable averages
4. **Monitor production memory** via production_ingestor
5. **Set batch size** with 20% safety margin below OOM threshold

## Related Documentation

- [GPU Optimization](../GPU_OPTIMIZATION.md) - General GPU optimization guide
- [Benchmarking System Architecture](../architecture/benchmarking-system.md) - System design
- [Production Metrics](./PRODUCTION_METRICS.md) - Continuous learning system

## Technical Details

### Implementation

- **File**: `src/benchmarking/runner.py`
- **Method**: `_benchmark_translation()`
- **Lines**: 314-318 (reset), 340-344 (capture), 369-381 (OOM handling)

### Database Schema

```sql
-- peak_memory_mb field in benchmark_results table
CREATE TABLE benchmark_results (
    -- ... other fields ...
    peak_memory_mb REAL,  -- NULL for CPU, float for CUDA
    errors TEXT,          -- JSON array of error strings
    -- ... other fields ...
);
```

### Testing

```bash
# Unit tests
pytest tests/unit/test_runner_gpu_memory.py -v

# Test coverage:
# - GPU tracking enabled on CUDA
# - GPU tracking disabled on CPU
# - OOM exception handling
# - Multiple batch sizes
# - Device index support (cuda:0)
```
