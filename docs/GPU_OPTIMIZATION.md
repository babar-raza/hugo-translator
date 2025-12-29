# GPU Batch Size Optimization

## Overview

The Hugo Translator now includes **automatic GPU batch size optimization** that targets optimal VRAM utilization (default: 85%) without requiring manual batch size tuning.

## How It Works

When you run a translation command without specifying `--batch-size`, the system automatically:

1. **Detects your GPU**: Identifies available VRAM
2. **Analyzes the model**: Infers model size from model name
3. **Determines precision**: Uses your `--load-mode` setting (fp16, fp32, int8)
4. **Calculates optimal batch size**: Targets 85% VRAM utilization
5. **Applies the batch size**: Automatically sets the optimal value

### Target Utilization

The system targets **85% VRAM utilization** by default. This leaves:
- **15% headroom** for safety (prevents OOM)
- **Space for CUDA overhead** and dynamic allocations
- **Buffer for slight variations** in memory usage

## Usage

### Automatic Optimization (Recommended)

Simply **omit the `--batch-size` flag** when running on GPU:

```bash
python -m src.cli \
  --site kb.aspose.net \
  --input "D:\path\to\content" \
  --target-langs ar bg cs de es fr \
  --load-mode fp16
```

The system will automatically calculate and apply the optimal batch size.

### Manual Override

You can still manually specify batch size if needed:

```bash
python -m src.cli \
  --site kb.aspose.net \
  --input "D:\path\to\content" \
  --target-langs ar bg cs de es fr \
  --load-mode fp16 \
  --batch-size 32  # Manual override
```

## Understanding the Log Output

When GPU optimization is enabled, you'll see a log message like:

```
INFO: GPU optimization enabled: batch_size=44, estimated_vram=10445MB (85.0% of 12288MB)
```

This tells you:
- **batch_size**: The calculated optimal batch size
- **estimated_vram**: Expected VRAM usage in MB
- **utilization**: Percentage of total VRAM that will be used

## Model Size Detection

The system automatically infers model size from the model name:

| Model Name Pattern | Detected Size | Base VRAM (FP16) |
|-------------------|---------------|------------------|
| `*600M*`, `*distilled-600M*` | 600M | ~1.2 GB |
| `*1.3B*`, `*13B*` | 1.3B | ~2.6 GB |
| `*3.3B*`, `*33B*` | 3.3B | ~6.6 GB |
| Unknown | 3.3B (conservative) | ~6.6 GB |

### Examples:
- `facebook/nllb-200-3.3B` → Detected as **3.3B**
- `facebook/nllb-200-distilled-600M` → Detected as **600M**
- `my-custom-model` → Defaults to **3.3B** (safe fallback)

## Precision Impact

Different precisions use different amounts of VRAM:

| Precision | VRAM per Batch Item (3.3B) | Recommended Use |
|-----------|---------------------------|-----------------|
| **fp32** | 150 MB | Highest accuracy, most VRAM |
| **fp16** | 75 MB | **Best balance** (default) |
| **int8** | 35 MB | Most efficient, slight quality loss |

### Example: 3.3B Model on 12GB GPU

| Precision | Batch Size | Estimated VRAM | Utilization |
|-----------|------------|----------------|-------------|
| fp32 | ~23 | 9,950 MB | 81% |
| fp16 | ~44 | 10,400 MB | 85% |
| int8 | ~90 | 10,650 MB | 87% |

## GPU Configurations

### 8GB VRAM (RTX 3060 Ti, RTX 4060)

**3.3B Model + FP16:**
- Batch size: **1** (minimum)
- Note: Model barely fits, consider using:
  - 600M model instead
  - INT8 quantization
  - CPU mode

**600M Model + FP16:**
- Batch size: **64** (maximum)
- Excellent performance

### 12GB VRAM (RTX 3060, RTX 4070)

**3.3B Model + FP16:**
- Batch size: **~44**
- Ideal configuration

**1.3B Model + FP16:**
- Batch size: **64** (maximum)
- Very fast processing

### 24GB VRAM (RTX 3090, RTX 4090, A5000)

**3.3B Model + FP16:**
- Batch size: **64** (maximum)
- Maximum throughput

**3.3B Model + FP32:**
- Batch size: **~58**
- Highest accuracy mode

## Troubleshooting

### OOM (Out of Memory) Errors

If you still get OOM errors with automatic optimization:

1. **Check actual VRAM usage** during initial batches
2. **Manually reduce batch size** by 20-30%:
   ```bash
   --batch-size 30  # If auto-calculated 44
   ```
3. **Use lower precision**:
   ```bash
   --load-mode int8
   ```
4. **Use smaller model**:
   ```bash
   --model facebook/nllb-200-1.3B
   ```

### Underutilization

If your GPU utilization is much lower than expected:

1. **Check if sorting is enabled**:
   ```bash
   --sort-segments-by-length
   ```
   This groups similar-length segments for more efficient batching

2. **Verify the precision**:
   ```bash
   --load-mode fp16  # Explicitly set
   ```

3. **Monitor actual VRAM**:
   Use `nvidia-smi` in another terminal to see real usage

### Optimization Failed

If you see: `WARNING: GPU optimization failed: <error>. Using default batch size.`

This means:
- PyTorch couldn't detect GPU properly
- CUDA drivers may need updating
- Falling back to default batch size of 16

**To fix:**
1. Update GPU drivers
2. Reinstall PyTorch with CUDA support
3. Manually specify batch size as temporary workaround

## Advanced Configuration

### Custom Target Utilization

Currently hardcoded to 85%, but can be modified in [cli.py:1315](../src/cli.py#L1315):

```python
gpu_optimizer = GPUOptimizer(
    model_name=overrides.model,
    precision=precision,
    target_utilization=0.90,  # Change to 90%
    device_id=device_id,
)
```

**Recommendations:**
- **0.75-0.80**: Very conservative, for unstable systems
- **0.85**: Default, good balance
- **0.90-0.95**: Aggressive, maximize throughput (higher OOM risk)

### Multi-GPU Setup

The optimizer automatically detects the device ID from the device string:

```bash
CUDA_VISIBLE_DEVICES=2 python -m src.cli ...
```

Or in code, it will parse `cuda:2` to target GPU 2.

## Calculator Script

For manual batch size calculation before running:

```bash
python scripts/calculate_optimal_batch.py \
  --model facebook/nllb-200-3.3B \
  --precision fp16 \
  --target-utilization 0.85
```

Output:
```
RECOMMENDED BATCH SIZE: 44

Estimated VRAM Usage:
  - Base Model:    6,600 MB
  - CUDA Reserved: 500 MB
  - Batch Data:    3,300 MB (44 items × 75 MB)
  - Total:         10,400 MB (10.2 GB)

Estimated Utilization: 84.6%
```

## Technical Details

### VRAM Calculation Formula

```python
# Target VRAM allocation
target_vram = total_vram * target_utilization  # e.g., 12288 * 0.85 = 10445 MB

# Available for batching
available = target_vram - model_base_vram - cuda_reserved
            # 10445 - 6600 - 500 = 3345 MB

# Optimal batch size
batch_size = int(available / vram_per_batch_item)
             # 3345 / 75 = 44
```

### Constants

Defined in [gpu_optimizer.py](../src/model_runtime/gpu_optimizer.py):

- `CUDA_RESERVED_MB = 500`: Reserved for CUDA overhead
- `MIN_BATCH_SIZE = 1`: Minimum allowed
- `MAX_BATCH_SIZE = 64`: Maximum allowed
- `target_utilization = 0.85`: Default target

## Comparison: CPU vs GPU Optimization

| Feature | CPU Optimizer | GPU Optimizer |
|---------|--------------|---------------|
| **Trigger** | `device=cpu` | `device=cuda` |
| **Target Resource** | RAM | VRAM |
| **Default Target** | 70% RAM | 85% VRAM |
| **Auto-detect** | ✅ Yes | ✅ Yes |
| **Model-aware** | ❌ No | ✅ Yes (size + precision) |
| **Override** | `--batch-size` | `--batch-size` |

## Benchmarking GPU Memory Tracking

The benchmarking system now includes **automatic GPU peak memory tracking** for all CUDA-based benchmark runs.

### How It Works

When running benchmarks on GPU (`--device cuda`), the system automatically:

1. **Resets memory stats** before each batch: `torch.cuda.reset_peak_memory_stats()`
2. **Tracks peak memory** during translation: `torch.cuda.max_memory_allocated()`
3. **Stores results** in the `peak_memory_mb` field of each BenchmarkResult
4. **Handles OOM errors** gracefully with detailed logging

### Usage

Run benchmarks with GPU memory tracking:

```bash
python -m src.benchmarking.runner \
  --model m2m100_418m \
  --device cuda \
  --batch-sizes 8,16,32 \
  --iterations 5 \
  --save-to-db data/benchmarks/gpu_memory_test.db
```

The results will include peak GPU memory usage for each batch size, helping you identify:
- **Optimal batch size** before OOM
- **Memory scaling** patterns (linear vs non-linear)
- **Safe operating range** for your GPU

### OOM Detection

When an OOM error occurs, the system:
- Logs the error with batch size context: `"OOM at batch_size=32"`
- Captures peak memory at failure: `"Peak GPU memory at OOM: 2048.50 MB"`
- Cleans up GPU cache: `torch.cuda.empty_cache()`
- Creates error results with `errors` field populated

### Example Output

```python
# Query results from database
results = db.query_results(run_id='abc123')
for r in results:
    print(f"Batch {r.batch_size}: {r.peak_memory_mb:.2f} MB")

# Output:
# Batch 8: 512.25 MB
# Batch 16: 1024.50 MB
# Batch 32: 2048.75 MB (OOM)
```

### Integration with Recommender

The benchmarking system can use historical GPU memory data to recommend safe batch sizes:

1. Run calibration benchmarks with multiple batch sizes
2. System learns GPU memory patterns
3. Recommender suggests batch sizes with safety margin
4. Prevents OOM in production runs

## Related Documentation

- [CPU Optimization](./CPU_OPTIMIZATION.md) (if exists)
- [Model Registry](./MODEL_REGISTRY.md) (if exists)
- [Telemetry Migration Guide](./operations/TELEMETRY_MIGRATION_GUIDE.md)
- [Benchmarking System Architecture](./architecture/benchmarking-system.md)

## Future Enhancements

Potential improvements (not yet implemented):

1. **Adaptive batch sizing**: Adjust batch size during runtime based on actual memory usage
2. **Multi-GPU load balancing**: Distribute work across multiple GPUs
3. **Memory profiling**: Learn actual VRAM usage patterns over time
4. **OOM recovery**: Automatically reduce batch size on OOM and retry

These features would integrate the existing `BatchOptimizer` module ([batch_optimizer.py](../src/orchestration/batch_optimizer.py)) which has been built but not yet connected.
