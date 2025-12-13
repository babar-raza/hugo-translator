# Batch Optimization Guide

## Overview

Batch optimization automatically tunes processing parameters for large-scale translation jobs, providing 20-40% speedup over naive batching.

## Features

- **Auto-tuned batch sizes** based on available RAM/VRAM
- **Dynamic adjustment** during processing
- **OOM handling** with graceful degradation
- **Length-based sorting** for efficient batching
- **Prefetching** for pipeline efficiency

## Quick Start

```bash
# With optimization
python scripts/batch_translate.py \
  --input content/ \
  --output translated/ \
  --optimize \
  --report results.json

# Without optimization (baseline)
python scripts/batch_translate.py \
  --input content/ \
  --output translated/
```

## Configuration

```python
from src.orchestration import create_batch_optimizer

optimizer = create_batch_optimizer(
    initial_batch_size=32,  # Starting point
    enable_optimization=True,  # Enable dynamic tuning
)

# Prepare batches
batches = optimizer.prepare_batches(segments)

# Process with monitoring
for batch in batches:
    result, success = optimizer.process_batch_with_monitoring(
        batch, translation_func
    )
```

## Performance Tips

1. **Enable optimization** for jobs > 1000 segments
2. **Use GPU** if available (2-5x faster)
3. **Sort by length** for more efficient batches
4. **Monitor OOM events** - reduce initial batch size if frequent

## Metrics

```python
stats = optimizer.get_stats()
print(f"Throughput: {stats.avg_throughput_segments_per_sec:.1f} seg/s")
print(f"Peak memory: {stats.peak_memory_mb:.0f} MB")
print(f"OOM events: {stats.oom_events}")
```

## Best Practices

- Start with batch_size=32 for CPU, 64 for GPU
- Enable optimization for production workloads
- Monitor peak memory usage
- Test with small sample before full batch

## Troubleshooting

**Frequent OOM errors:**
- Reduce initial_batch_size
- Enable oom_retry_enabled
- Check available VRAM with `nvidia-smi`

**Low throughput:**
- Increase num_workers
- Enable sort_by_length
- Use GPU if available
