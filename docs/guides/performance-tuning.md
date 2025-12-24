# Performance Tuning Guide

## Overview

This guide covers performance optimization strategies for the Hugo Translator, including batch sizing, GPU configuration, and segment sorting.

## Segment Sorting

Segment sorting is an optional optimization that processes segments in length order (shortest→longest) instead of document order. This improves GPU batching efficiency for documents with variable segment lengths.

**Quick Decision Guide:**

| Scenario | Enable Sorting? | Expected Benefit |
|----------|-----------------|------------------|
| 10,000+ segments, blog posts | ✅ Yes | 10-20% faster |
| 1,000+ segments, API docs | ✅ Yes | 5-10% faster |
| <100 segments, any content | ❌ No | <1% (overhead) |
| Uniform segment lengths | ❌ No | ~0% |
| High TM cache hit rate (>90%) | ❌ No | <1% |
| CPU-only translation | ❌ Maybe | 0-5% |

### When to Enable

**Recommended scenarios:**
1. **Large jobs:** 1000+ segments to translate
2. **High length variance:** Short titles (5-20 chars) + long paragraphs (500+ chars)
3. **GPU translation:** CUDA-accelerated models
4. **Low TM hit rate:** <50% of segments cached

**Not recommended:**
- Small jobs (<100 segments)
- Uniform content (all segments ~same length)
- High TM hit rates (>90% cached)

### How to Enable

**Via CLI flag:**
```bash
python -m src.cli translate \
  --site mysite \
  --target-langs es,fr \
  --sort-segments-by-length
```

**Via configuration:**
```yaml
# config/default.yaml
body_rules:
  sort_segments_by_length: true
```

### Benchmarking Methodology

Measure the impact of segment sorting on your specific corpus:

**Step 1: Baseline benchmark (sorting disabled)**
```bash
python -m src.benchmarking.cli benchmark run \
  --model facebook/m2m100_418M \
  --device cuda \
  --batch-size 16 \
  --corpus production_sample
```

**Step 2: Enable sorting in config**
```yaml
# config/default.yaml
body_rules:
  sort_segments_by_length: true
```

**Step 3: Benchmark with sorting**
```bash
python -m src.benchmarking.cli benchmark run \
  --model facebook/m2m100_418M \
  --device cuda \
  --batch-size 16 \
  --corpus production_sample
```

**Step 4: Compare results**
```bash
python -m src.benchmarking.cli query compare \
  --metric throughput_segments_per_sec
```

**Interpreting results:**
- **>10% improvement:** Sorting is beneficial, keep enabled
- **5-10% improvement:** Sorting helps, consider enabling
- **<5% improvement:** Sorting overhead ≈ benefit, optional
- **Negative impact:** Disable sorting (uniform content or small job)

### Performance Tuning Checklist

- [ ] Analyze segment length distribution (`min`, `max`, `variance`)
- [ ] Measure TM cache hit rate
- [ ] Run baseline benchmark without sorting
- [ ] Run comparison benchmark with sorting
- [ ] Calculate throughput improvement
- [ ] Check GPU memory usage (should be more consistent with sorting)
- [ ] Verify no OOM errors with sorting enabled
- [ ] Document decision (enable/disable) in site config

### Trade-offs

**Benefits:**
- Improved GPU memory efficiency (homogeneous batches)
- Reduced OOM risk
- 0-20% throughput improvement (varies by corpus)

**Costs:**
- O(n log n) sorting overhead (~1% of translation time)
- Logs show sorted order, not document order
- Debugging complexity (segment IDs help)

See [Segment Sorting Feature Guide](../features/segment-sorting.md) for implementation details.

## Other Performance Optimizations

### Batch Sizing

Batch size affects memory usage and throughput. Larger batches improve GPU utilization but increase memory requirements.

**Auto-detection:** By default, batch size is automatically determined based on available RAM.

**Manual override:**
```bash
python -m src.cli translate --batch-size 32
```

**Guidelines:**
- GPU (16GB VRAM): 16-32 segments per batch
- GPU (8GB VRAM): 8-16 segments per batch
- CPU: 4-8 segments per batch

### GPU Configuration

For CUDA-accelerated translation:

**Device selection:**
```bash
# Auto-detect best device
python -m src.cli translate --device auto

# Force GPU
python -m src.cli translate --device cuda

# Force CPU
python -m src.cli translate --device cpu
```

### Translation Memory Tuning

Translation Memory (TM) caching can dramatically reduce translation time:

**Monitor cache hit rate:**
- Check telemetry metrics for `tm_hit_rate`
- High hit rate (>80%) = most segments cached
- Low hit rate (<20%) = TM needs population

**Optimize cache:**
- Use semantic TM for fuzzy matching
- Keep TM database updated with production translations
- See [Translation Memory Guide](./tm-navigation.md) for details

## Measuring Performance

### Telemetry Metrics

Enable telemetry to track performance:

```bash
python -m src.cli translate --site mysite --log-level INFO
```

**Key metrics:**
- `throughput_segments_per_sec`: Translation speed
- `tm_hit_rate`: Cache efficiency
- `avg_batch_size`: Actual batch size used
- `total_translation_time`: End-to-end time

### Profiling

For detailed performance analysis:

```bash
# Enable DEBUG logging
python -m src.cli translate --log-level DEBUG > perf.log 2>&1

# Analyze bottlenecks
grep "took.*seconds" perf.log
```

## See Also

- [Segment Sorting Feature Guide](../features/segment-sorting.md) - Detailed sorting documentation
- [Translation Memory Navigation](./tm-navigation.md) - TM optimization guide
- [CLI Reference](../reference/cli.md) - All performance-related flags
