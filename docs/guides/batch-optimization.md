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
python scripts/content/batch_translate.py \
  --input content/ \
  --output translated/ \
  --optimize \
  --report results.json

# Without optimization (baseline)
python scripts/content/batch_translate.py \
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

## Parallel Processing Guidelines

### Overview

Parallel file processing enables concurrent translation of multiple markdown files, improving throughput for large document sets. The system uses ThreadPoolExecutor with configurable worker limits and thread-safe operations.

### Memory Management

**Default Conservative Approach:**
- Uses `max_workers=1` by default to prevent memory exhaustion with large translation models
- Pre-loads translation models before starting parallel workers to avoid race conditions
- Each worker processes one file at a time, ensuring predictable memory usage

**Memory Considerations:**
- Translation models (especially GPU-based) can consume 2-8GB RAM per instance
- Multiple concurrent workers risk OOM if system RAM is insufficient
- File I/O operations are buffered and don't significantly impact memory

**Memory Monitoring:**
```python
import psutil
import os

def get_memory_usage():
    process = psutil.Process(os.getpid())
    return process.memory_info().rss / 1024 / 1024  # MB

# Monitor memory before/after parallel processing
before = get_memory_usage()
# ... run parallel translation ...
after = get_memory_usage()
print(f"Memory delta: {after - before:.1f} MB")
```

### Worker Limits

**Default Configuration:**
- `max_workers=1` (conservative, prevents OOM)
- Can be overridden via `max_workers` parameter in `translate_directory()`

**Worker Scaling Guidelines:**
- **1 worker:** Safe for all systems, predictable memory usage
- **2-4 workers:** Suitable for systems with 16GB+ RAM and fast storage
- **4+ workers:** Only recommended for high-end systems with 32GB+ RAM

**System Requirements by Worker Count:**
| Workers | Min RAM | Recommended CPU | Storage Speed |
|---------|---------|-----------------|---------------|
| 1 | 8GB | 4+ cores | Any |
| 2 | 16GB | 6+ cores | Fast (SSD) |
| 4 | 32GB | 8+ cores | NVMe SSD |

**Thread Safety:**
- Uses locks for shared resources: TM access (`_tm_lock`), model loading (`_model_lock`)
- Pre-loading models prevents race conditions during initialization
- Each worker maintains isolated file processing context

### Performance Optimization

**Pre-loading Strategy:**
```python
# Models are pre-loaded before worker threads start
site_profile = self.config.get_site_profile(site_id)
model_id = self._get_model_id(site_profile)
self.model_loader.load_model(model_id)  # Single load, shared across workers
```

**Optimal Configuration by Use Case:**

**Small Files (< 100KB each):**
- Workers: 2-4
- Benefit: High parallelism, fast I/O
- Risk: Memory spikes if many small files

**Large Files (> 500KB each):**
- Workers: 1-2
- Benefit: Controlled memory usage
- Risk: Sequential bottleneck on I/O

**Mixed File Sizes:**
- Workers: 1 (default)
- Benefit: Predictable performance
- Risk: Under-utilization of CPU cores

**Performance Monitoring:**
```python
# Track parallel processing metrics
start_time = time.time()
result = engine.translate_directory(
    site_id="default",
    directory=Path("content/"),
    target_langs=["es", "fr"],
    parallel=True,
    max_workers=2
)
duration = time.time() - start_time

print(f"Files: {result.successful_files}/{result.total_files}")
print(f"Duration: {duration:.1f}s")
print(f"Throughput: {result.total_files/duration:.1f} files/sec")
```

**I/O Optimization:**
- Use fast storage (NVMe SSD recommended for >2 workers)
- Avoid network-mounted storage for input/output directories
- Ensure sufficient disk space (2x input size for translations)

**CPU Utilization:**
- Monitor with system tools: `htop`, `top`, or Task Manager
- Target: 70-90% CPU utilization during processing
- If CPU < 50%, consider increasing workers or check for I/O bottlenecks

### Troubleshooting Parallel Processing

**High Memory Usage:**
- Reduce `max_workers` to 1
- Monitor with `psutil` or system tools
- Check for memory leaks in model backends

**Slow Performance:**
- Verify storage I/O speed
- Check CPU utilization (should be >70%)
- Consider disabling parallel mode for debugging

**Threading Errors:**
- Ensure model pre-loading completes successfully
- Check for lock contention in logs
- Verify thread-safe operations in custom components

**Best Practices:**
- Start with default settings (1 worker, parallel=True)
- Test with small file sets before scaling up
- Monitor system resources during processing
- Use parallel mode for >10 files, sequential for <10 files
