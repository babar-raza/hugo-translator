# TM Performance Tuning Guide

**Version:** 1.0
**Last Updated:** 2025-12-24
**Audience:** Operators, Performance Engineers
**Prerequisites:** Understanding of [TM Architecture](../architecture/translation-memory.md)

---

## Table of Contents

1. [Quick Start](#quick-start)
2. [Performance Metrics](#performance-metrics)
3. [L1 Cache Tuning](#l1-cache-tuning)
4. [L2 Persistent Tuning](#l2-persistent-tuning)
5. [L3 Semantic Tuning](#l3-semantic-tuning)
6. [Benchmarking Procedures](#benchmarking-procedures)
7. [Optimization Workflows](#optimization-workflows)
8. [Common Scenarios](#common-scenarios)
9. [Troubleshooting Performance](#troubleshooting-performance)

---

## Quick Start

### Default Configuration (Baseline)

**For most users, defaults are well-tuned:**

```python
# config/site_profiles/default.yaml
translation_memory:
  l1_cache_size: 10000          # Good for most workloads
  l2_max_size_mb: 1024          # 1GB LMDB map size
  l3_enabled: true
  l3_save_interval: 100         # Balance between safety and performance
  l3_use_gpu: false             # CPU by default (GPU if available)
```

**Expected Performance:**
- L1 hit latency: <1ms
- L2 hit latency: 5-10ms
- L3 hit latency: 20-100ms
- Overall hit rate: 85-95% (after initial run)
- Throughput: 1000-5000 translations/hour (depending on hit rate)

### When to Tune

Tune TM when you observe:
- ✅ L1 evictions > 50% of L1 hits
- ✅ L2 map full errors (`MDB_MAP_FULL`)
- ✅ L3 save operations taking >10 seconds
- ✅ Hit rates below expectations (<80%)
- ✅ Latency degradation over time

**Don't tune** if:
- ❌ Performance meets requirements
- ❌ You haven't measured baseline metrics
- ❌ System is still warming up caches

---

## Performance Metrics

### Collecting Metrics

**Built-in Statistics:**

```python
from src.tm import TranslationMemory

# Get current TM stats
stats = tm.stats()
print(stats.to_dict())
```

**Output:**
```json
{
  "l1_size": 9523,
  "l1_max_size": 10000,
  "l1_hits": 45230,
  "l1_misses": 8920,
  "l1_evictions": 3200,
  "l1_hit_rate": 83.5,
  "l2_size": 44550,
  "l3_size": 44550,
  "total_lookups": 54150,
  "total_hits": 50120,
  "overall_hit_rate": 92.6
}
```

### Key Performance Indicators

| Metric | Target | Warning | Critical |
|--------|--------|---------|----------|
| **L1 Hit Rate** | >70% | <60% | <40% |
| **L2 Hit Rate** | >85% | <75% | <60% |
| **Overall Hit Rate** | >90% | <80% | <70% |
| **L1 Evictions/Hits** | <0.3 | >0.5 | >1.0 |
| **L2 Lookup Latency (p95)** | <15ms | >30ms | >50ms |
| **L3 Lookup Latency (p95)** | <150ms | >300ms | >500ms |
| **L3 Save Duration** | <5s | >10s | >30s |

### Monitoring Commands

**Quick Health Check:**

```bash
# Check TM statistics
venv/Scripts/python.exe -c "
from src.tm import create_translation_memory
from pathlib import Path
tm = create_translation_memory(Path('data/tm'))
stats = tm.stats()
print(f'Overall Hit Rate: {stats.overall_hit_rate:.1f}%')
print(f'L1 Size: {stats.l1_size:,} / {stats.l1_max_size:,}')
print(f'L1 Hit Rate: {stats.l1_hit_rate:.1f}%')
print(f'L2 Size: {stats.l2_size:,} entries')
print(f'L3 Size: {stats.l3_size:,} vectors')
"
```

**Detailed Metrics with Latency:**

Enable telemetry metrics (see [Observability CLI](../reference/observability-cli.md)):

```bash
# Tail metrics in real-time
venv/Scripts/python.exe -m src.observability.metrics_tail
```

---

## L1 Cache Tuning

### Overview

**L1 Cache = In-Memory LRU Cache**
- **Purpose:** Sub-millisecond lookups for hot data
- **Trade-off:** Memory vs Hit Rate
- **Sweet Spot:** 10K-20K entries for most workloads

### Sizing Guidelines

**Calculate Optimal Size:**

```python
# Rule of thumb: L1 should hold your "working set"
# Working set = translations accessed repeatedly in a session

optimal_l1_size = unique_translations_per_batch × batch_frequency_per_session
```

**Examples:**

| Workload | Batch Size | Batches/Session | Recommended L1 Size |
|----------|-----------|-----------------|---------------------|
| **Small site** | 500 files | 1-2 batches | 5,000 entries |
| **Medium site** | 2,000 files | 2-5 batches | 10,000 entries (default) |
| **Large site** | 10,000 files | 5+ batches | 20,000-50,000 entries |
| **Continuous translation** | Streaming | Infinite | 50,000+ entries |

**Memory Impact:**

```text
Memory per entry ≈ 500 bytes (key + value + overhead)

Examples:
  5,000 entries ≈ 2.5 MB
 10,000 entries ≈ 5 MB (default)
 50,000 entries ≈ 25 MB
100,000 entries ≈ 50 MB
```

### Configuration

**Option 1: Config File**

```yaml
# config/site_profiles/default.yaml
translation_memory:
  l1_cache_size: 20000  # Increase from default 10K
```

**Option 2: Programmatic**

```python
from src.tm.l1_cache import L1Cache

l1 = L1Cache(max_size=20000)
```

### Tuning Process

**1. Measure Evictions:**

```python
stats = tm.stats()
eviction_rate = stats["l1_evictions"] / stats["l1_hits"]

if eviction_rate > 0.5:
    print(f"⚠️ High eviction rate: {eviction_rate:.2f}")
    print(f"Recommendation: Increase L1 size to {stats['l1_max_size'] * 2}")
```

**2. Test Larger Size:**

```python
# Increase by 2x and re-run translation
# config/site_profiles/default.yaml
translation_memory:
  l1_cache_size: 20000  # Was 10000
```

**3. Verify Improvement:**

```python
# Check eviction rate again
# Target: eviction_rate < 0.3
```

**4. Monitor Memory:**

```bash
# Windows (PowerShell)
Get-Process python | Select-Object WorkingSet64

# Linux/Mac
ps aux | grep python
```

### When NOT to Increase L1

- ❌ Memory constrained environment (<2GB available)
- ❌ L1 hit rate already >90%
- ❌ Eviction rate <0.3
- ❌ Single-pass translations (no repeated lookups)

---

## L2 Persistent Tuning

### Overview

**L2 = LMDB Persistent Storage**
- **Purpose:** Durable exact-match cache
- **Trade-off:** Disk space vs capacity
- **Sweet Spot:** 2-3x current cache size

### LMDB Map Size Tuning

**The `map_size` Problem:**

LMDB requires pre-allocating virtual address space via `map_size`. If exceeded, writes fail with `MDB_MAP_FULL`.

**Symptoms of Too Small:**
```text
lmdb.MapFullError: MDB_MAP_FULL: Environment mapsize limit reached
```

**Symptoms of Too Large:**
- Wasted virtual address space (not physical memory!)
- Windows: May fail to allocate on 32-bit systems

### Sizing Guidelines

**Calculate Required Map Size:**

```python
# Estimate entry size
avg_entry_size = 300 bytes  # JSON overhead + content

# Calculate total size
total_size_bytes = num_entries × avg_entry_size

# Add 50-100% buffer for growth
map_size_mb = (total_size_bytes × 2) / (1024 × 1024)
```

**Examples:**

| Entries | Avg Size | Total Data | Recommended `map_size` |
|---------|----------|------------|------------------------|
| 10,000 | 300B | 3 MB | 10-50 MB |
| 50,000 | 300B | 15 MB | 50-100 MB |
| 100,000 | 300B | 30 MB | 100-200 MB |
| 500,000 | 300B | 150 MB | 500 MB |
| 1,000,000 | 300B | 300 MB | 1 GB (default) |
| 10,000,000 | 300B | 3 GB | 10 GB |

**Rule of Thumb:** `map_size = current_db_size × 3`

### Configuration

**Option 1: Config File**

```yaml
# config/site_profiles/default.yaml
translation_memory:
  l2_max_size_mb: 2048  # Increase from default 1GB to 2GB
```

**Option 2: Programmatic**

```python
from src.tm.l2_persistent import L2PersistentTM

l2 = L2PersistentTM(
    db_path="data/tm/l2_lmdb",
    max_size_mb=2048  # 2GB
)
```

### Handling `MDB_MAP_FULL`

**Immediate Fix:**

```python
# 1. Stop translation process
# 2. Increase map_size in config
translation_memory:
  l2_max_size_mb: 4096  # Double it

# 3. Restart translation
# LMDB will use new map_size automatically
```

**Long-term Solution:**

```python
# Monitor database growth
import lmdb
env = lmdb.open("data/tm/l2_lmdb")
stat = env.stat()
info = env.info()

current_size_mb = stat['psize'] * stat['leaf_pages'] / (1024 * 1024)
map_size_mb = info['map_size'] / (1024 * 1024)
utilization = (current_size_mb / map_size_mb) * 100

print(f"DB Size: {current_size_mb:.1f} MB")
print(f"Map Size: {map_size_mb:.1f} MB")
print(f"Utilization: {utilization:.1f}%")

if utilization > 70:
    print(f"⚠️ Consider increasing map_size to {map_size_mb * 2:.0f} MB")
```

### Compaction

**When to Compact:**

LMDB accumulates unused pages over time. Compact when:
- Database file size >> actual data size
- Frequent deletes/updates
- Before backup to save space

**How to Compact:**

```bash
# Create compacted backup
venv/Scripts/python.exe -c "
from src.tm.backup import CacheBackupManager
from pathlib import Path

manager = CacheBackupManager(
    tm_path=Path('data/tm/l2_lmdb'),
    backup_dir=Path('data/tm/backups')
)

backup_info = manager.create_backup(compact=True)
print(f'Compacted: {backup_info.size_mb:.1f} MB')
"

# Restore compacted backup (replaces original)
venv/Scripts/python.exe -c "
from src.tm.backup import CacheBackupManager
from pathlib import Path

manager = CacheBackupManager(
    tm_path=Path('data/tm/l2_lmdb'),
    backup_dir=Path('data/tm/backups')
)

backups = manager.list_backups()
manager.restore_backup(backups[0].path, force=True)
"
```

**Typical Savings:** 30-50% disk space

---

## L3 Semantic Tuning

### Overview

**L3 = FAISS Vector Index**
- **Purpose:** Fuzzy semantic matching
- **Trade-off:** Accuracy vs Speed, GPU vs CPU
- **Sweet Spot:** GPU for >10K entries, periodic saves enabled

### GPU Acceleration

**When to Enable GPU:**

| Scenario | CPU (Default) | GPU (Recommended) |
|----------|---------------|-------------------|
| **Index Size** | <10K entries | >10K entries |
| **Embedding Speed** | 2K texts/sec | 10K texts/sec |
| **Search Speed** | 50 queries/sec | 500 queries/sec |
| **Hardware** | Always available | Requires NVIDIA GPU |
| **Cost** | $0 | GPU hardware/cloud |

**Configuration:**

```yaml
# config/site_profiles/default.yaml
translation_memory:
  l3_use_gpu: true              # Enable GPU for embeddings
  l3_use_faiss_gpu: true        # Enable GPU for FAISS index
```

**Requirements:**
- NVIDIA GPU with CUDA support
- `torch` with CUDA
- `faiss-gpu` package (instead of `faiss-cpu`)

**Installation:**

```bash
# Install CUDA-enabled torch
pip install torch torchvision torchaudio --index-url https://download.pytorch.org/whl/cu118

# Install faiss-gpu
pip uninstall faiss-cpu
pip install faiss-gpu
```

**Verify GPU Usage:**

```python
import torch
print(f"CUDA available: {torch.cuda.is_available()}")
print(f"GPU: {torch.cuda.get_device_name(0)}")

import faiss
print(f"FAISS GPU support: {faiss.get_num_gpus() > 0}")
```

### Periodic Save Tuning

**The Save Interval Trade-off:**

| save_interval | Data Loss Risk | Performance | Disk I/O |
|---------------|----------------|-------------|----------|
| 10 | Minimal (10 entries) | Slower (frequent saves) | High |
| 100 (default) | Low (100 entries) | Balanced | Medium |
| 500 | Moderate (500 entries) | Faster | Low |
| 1000 | High (1000 entries) | Fastest | Minimal |
| 0 (disabled) | Very High (manual save only) | Fastest | None |

**Recommendation:**
- **Production:** 100 (default) - Good balance
- **Development:** 500 - Faster iteration
- **Batch Import:** 1000 or async_save=True - Maximize throughput
- **Critical Data:** 50 - Minimize loss

**Configuration:**

```yaml
# config/site_profiles/default.yaml
translation_memory:
  l3_save_interval: 500         # Save every 500 additions
  l3_async_save: true           # Use background save thread
  l3_save_timeout: 10.0         # Max 10 seconds per save
```

**Async Save (Advanced):**

```python
from src.tm.l3_semantic import L3SemanticTM

l3 = L3SemanticTM(
    index_path="data/tm/l3_semantic",
    save_interval=1000,          # Save less frequently
    async_save=True,             # Non-blocking saves
    save_timeout=30.0            # Allow longer saves
)
```

**Benefits:**
- Translation continues during save
- Higher throughput for bulk imports
- Trade-off: Slightly higher memory usage

**Monitoring Saves:**

```python
save_stats = l3.get_save_stats()
print(f"Total additions: {save_stats['total_additions']}")
print(f"Additions since save: {save_stats['additions_since_save']}")
print(f"Save failures: {save_stats['save_failures']}")
print(f"Last save: {save_stats['last_save_time']}")
```

### FAISS Index Type Optimization

**Default: IndexFlatL2** (Exact search, slow for >1M vectors)

**For Large Indexes (>100K entries):**

```python
# Use IVF (Inverted File Index) for faster search
import faiss

# Replace IndexFlatL2 with IndexIVFFlat
nlist = 100  # Number of clusters (sqrt of data size is common)
quantizer = faiss.IndexFlatL2(embedding_dim)
index = faiss.IndexIVFFlat(quantizer, embedding_dim, nlist)

# Train index on sample data
index.train(sample_embeddings)
```

**Index Type Comparison:**

| Index Type | Build Time | Search Speed | Accuracy | Best For |
|------------|------------|--------------|----------|----------|
| **IndexFlatL2** | Instant | Slow (linear) | 100% | <100K entries |
| **IndexIVFFlat** | Minutes (train) | Fast | 95-99% | 100K-10M entries |
| **IndexHNSWFlat** | Hours (build) | Very Fast | 98-99% | >1M entries |

**Implementation:** Requires code changes in `src/tm/l3_semantic.py` - contact maintainers for guidance.

### Embedding Model Selection

**Default: `all-MiniLM-L6-v2`**
- Dimension: 384
- Speed: Fast
- Quality: Good
- Size: 80 MB

**Alternatives:**

| Model | Dimension | Quality | Speed | Size | Use Case |
|-------|-----------|---------|-------|------|----------|
| `all-MiniLM-L6-v2` (default) | 384 | Good | Fast | 80 MB | Production default |
| `paraphrase-multilingual-MiniLM-L12-v2` | 384 | Better | Medium | 120 MB | Multilingual focus |
| `all-mpnet-base-v2` | 768 | Best | Slow | 420 MB | Quality over speed |
| `all-MiniLM-L12-v2` | 384 | Better | Medium | 120 MB | Balance |

**Configuration:**

```yaml
# config/site_profiles/default.yaml
translation_memory:
  l3_embedding_model: "paraphrase-multilingual-MiniLM-L12-v2"
```

**Trade-offs:**
- Larger models: Better quality, slower embedding, more memory
- Smaller models: Faster embedding, less memory, lower quality

---

## Benchmarking Procedures

### Baseline Benchmark

**1. Prepare Test Set:**

```bash
# Use consistent test data
cp -r content/sample_100_files test_content/
```

**2. Clear Caches:**

```bash
# Start with empty TM
rm -rf data/tm/l2_lmdb
rm -rf data/tm/l3_semantic
```

**3. Run Baseline Translation:**

```bash
time venv/Scripts/python.exe scripts/batch_translate.py \
  --input test_content \
  --output test_output_baseline \
  --site products.aspose.net \
  --langs de fr \
  --report baseline_metrics.json
```

**4. Capture Metrics:**

```bash
# Extract key metrics
cat baseline_metrics.json | jq '{
  total_time: .elapsed_time,
  total_files: .files_processed,
  throughput: (.files_processed / .elapsed_time),
  tm_hit_rate: .tm_stats.overall_hit_rate,
  avg_latency: .avg_translation_time
}'
```

### A/B Testing Configuration Changes

**Test Scenario: Increase L1 Cache Size**

```bash
# A: Baseline (L1=10K)
cat > config/site_profiles/test_a.yaml <<EOF
translation_memory:
  l1_cache_size: 10000
EOF

# B: Larger L1 (L1=20K)
cat > config/site_profiles/test_b.yaml <<EOF
translation_memory:
  l1_cache_size: 20000
EOF

# Run tests
python scripts/benchmark_tm.py --config test_a.yaml --output results_a.json
python scripts/benchmark_tm.py --config test_b.yaml --output results_b.json

# Compare
python scripts/compare_benchmarks.py results_a.json results_b.json
```

### Load Testing

**Simulate High-Volume Translation:**

```bash
# Test with 1000 files
python scripts/generate_test_content.py --num-files 1000 --output test_large/

# Translate and measure
time python scripts/batch_translate.py \
  --input test_large \
  --output test_large_output \
  --site products.aspose.net \
  --langs de fr es ja \
  --report load_test_metrics.json

# Analyze performance degradation
python scripts/analyze_metrics.py load_test_metrics.json \
  --check-degradation \
  --threshold 20  # Warn if >20% slowdown
```

### Profiling

**CPU Profiling:**

```bash
python -m cProfile -o profile.stats scripts/batch_translate.py \
  --input test_content \
  --output test_output

# Analyze hotspots
python -c "
import pstats
p = pstats.Stats('profile.stats')
p.sort_stats('cumulative').print_stats(20)
"
```

**Memory Profiling:**

```bash
pip install memory_profiler

python -m memory_profiler scripts/batch_translate.py \
  --input test_content \
  --output test_output
```

---

## Optimization Workflows

### Workflow 1: Optimize for Hit Rate

**Goal:** Maximize cache hit rate to reduce API costs

**Steps:**

1. **Measure Current Hit Rate:**
   ```bash
   # Run translation and check hit rate
   python scripts/batch_translate.py ... --report metrics.json
   cat metrics.json | jq '.tm_stats.overall_hit_rate'
   ```

2. **Identify Bottleneck:**
   ```python
   # Low L1 hit rate? → Increase L1 size
   # Low L2 hit rate? → Check if content is truly new
   # Low L3 hit rate? → Tune similarity threshold or use better embedding model
   ```

3. **Apply Optimization:**
   ```yaml
   # For low L1 hit rate
   translation_memory:
     l1_cache_size: 20000  # Double it

   # For low L3 hit rate
   translation_memory:
     l3_embedding_model: "all-mpnet-base-v2"  # Better quality
     l3_similarity_threshold: 0.75  # Lower threshold (more fuzzy matches)
   ```

4. **Validate:**
   ```bash
   # Re-run and compare hit rates
   python scripts/batch_translate.py ... --report metrics_after.json
   python scripts/compare_metrics.py metrics.json metrics_after.json
   ```

### Workflow 2: Optimize for Throughput

**Goal:** Maximize translations per hour

**Steps:**

1. **Profile Bottleneck:**
   ```bash
   # Enable detailed timing
   python scripts/batch_translate.py ... --profile --report profile.json
   ```

2. **Apply Optimization:**
   ```yaml
   # If bottleneck is L3 embedding
   translation_memory:
     l3_use_gpu: true              # Enable GPU
     l3_save_interval: 500         # Save less frequently
     l3_async_save: true           # Non-blocking saves

   # If bottleneck is L2 writes
   translation_memory:
     l2_write_batch_size: 1000     # Batch writes

   # If bottleneck is LLM API
   concurrency:
     max_workers: 10               # Parallel API calls
   ```

3. **Validate:**
   ```bash
   # Compare throughput
   # Before: 500 files/hour
   # After: 2000 files/hour (4x improvement)
   ```

### Workflow 3: Optimize for Memory

**Goal:** Reduce memory footprint for resource-constrained environments

**Steps:**

1. **Measure Current Usage:**
   ```bash
   # Monitor memory during translation
   while true; do
     ps aux | grep python | awk '{print $6/1024 "MB"}'
     sleep 5
   done
   ```

2. **Apply Optimization:**
   ```yaml
   translation_memory:
     l1_cache_size: 5000           # Reduce L1 (10K → 5K)
     l3_enabled: false             # Disable L3 if not needed
     l3_use_gpu: false             # Use CPU (no GPU memory)
   ```

3. **Validate:**
   ```bash
   # Compare memory usage
   # Before: 2GB RAM
   # After: 500MB RAM (4x reduction)
   ```

---

## Common Scenarios

### Scenario 1: Small Website (<1000 Pages)

**Characteristics:**
- Single language pair
- Infrequent updates
- Limited budget

**Recommended Config:**

```yaml
translation_memory:
  l1_cache_size: 5000
  l2_max_size_mb: 256          # 256 MB is plenty
  l3_enabled: true             # Enable for semantic matches
  l3_use_gpu: false            # CPU is fine
  l3_save_interval: 100        # Default
```

**Expected Performance:**
- First run: 30-60 min (all translations fresh)
- Second run: 5-10 min (90%+ hit rate)
- Memory: <500 MB
- Disk: <100 MB

---

### Scenario 2: Medium Website (1K-10K Pages)

**Characteristics:**
- Multiple languages (5-10)
- Weekly/monthly updates
- Moderate budget

**Recommended Config:**

```yaml
translation_memory:
  l1_cache_size: 10000         # Default
  l2_max_size_mb: 1024         # 1 GB (default)
  l3_enabled: true
  l3_use_gpu: true             # GPU recommended
  l3_save_interval: 200
  l3_async_save: true          # Background saves
```

**Expected Performance:**
- First run: 2-5 hours
- Subsequent runs: 30-60 min (85%+ hit rate)
- Memory: 1-2 GB
- Disk: 500 MB - 2 GB

---

### Scenario 3: Large Website (>10K Pages)

**Characteristics:**
- 20+ languages
- Daily updates
- High volume

**Recommended Config:**

```yaml
translation_memory:
  l1_cache_size: 50000         # Large L1
  l2_max_size_mb: 10240        # 10 GB
  l3_enabled: true
  l3_use_gpu: true             # GPU required
  l3_use_faiss_gpu: true       # GPU for FAISS too
  l3_save_interval: 1000       # Save less frequently
  l3_async_save: true
  l3_save_timeout: 60.0        # Allow longer saves
```

**Expected Performance:**
- First run: 10-24 hours
- Subsequent runs: 2-4 hours (90%+ hit rate)
- Memory: 4-8 GB
- Disk: 5-20 GB

**Additional Optimizations:**
- Use SSD for LMDB
- Consider FAISS IVFFlat index for >1M entries
- Implement distributed caching if single machine insufficient

---

### Scenario 4: Continuous Translation Pipeline

**Characteristics:**
- Real-time translation
- Streaming content
- 24/7 operation

**Recommended Config:**

```yaml
translation_memory:
  l1_cache_size: 100000        # Very large L1 (keep hot data)
  l2_max_size_mb: 20480        # 20 GB
  l3_enabled: true
  l3_use_gpu: true
  l3_save_interval: 2000       # Save less frequently
  l3_async_save: true          # Non-blocking

  # Enable automatic compaction
  l2_auto_compact: true
  l2_compact_threshold: 0.5    # Compact when 50% fragmentation
```

**Additional Considerations:**
- Monitor disk I/O (SSD required)
- Set up automated backups
- Implement cache warming on startup
- Use health checks to detect degradation

---

## Troubleshooting Performance

### Issue: Low L1 Hit Rate

**Symptoms:**
- L1 hit rate <60%
- High eviction rate

**Diagnosis:**

```python
stats = tm.stats()
print(f"L1 Hit Rate: {stats.l1_hit_rate:.1f}%")
print(f"Evictions: {stats.l1_evictions:,}")
print(f"Eviction Rate: {stats.l1_evictions / stats.l1_hits:.2f}")
```

**Solutions:**

1. **Increase L1 Size:**
   ```yaml
   translation_memory:
     l1_cache_size: 20000  # Double it
   ```

2. **Check Access Pattern:**
   - If translations are not repeated → L1 won't help
   - Consider running multiple passes

---

### Issue: LMDB Map Full Errors

**Symptoms:**
```text
lmdb.MapFullError: MDB_MAP_FULL: Environment mapsize limit reached
```

**Diagnosis:**

```bash
venv/Scripts/python.exe -c "
import lmdb
env = lmdb.open('data/tm/l2_lmdb')
stat = env.stat()
info = env.info()
size_mb = stat['psize'] * stat['leaf_pages'] / (1024 * 1024)
map_mb = info['map_size'] / (1024 * 1024)
print(f'Used: {size_mb:.1f} MB / {map_mb:.1f} MB ({size_mb/map_mb*100:.1f}%)')
"
```

**Solutions:**

1. **Increase Map Size:**
   ```yaml
   translation_memory:
     l2_max_size_mb: 4096  # Double current size
   ```

2. **Compact Database:**
   ```bash
   # See "L2 Persistent Tuning > Compaction" section above
   ```

---

### Issue: Slow L3 Searches

**Symptoms:**
- L3 searches taking >500ms
- High CPU usage during lookups

**Diagnosis:**

```python
# Check index size
print(f"L3 Size: {l3.count():,} vectors")

# If >100K vectors, consider IVF index
```

**Solutions:**

1. **Enable GPU:**
   ```yaml
   translation_memory:
     l3_use_gpu: true
     l3_use_faiss_gpu: true
   ```

2. **Use IVF Index** (for >100K entries):
   - Requires code changes
   - Contact maintainers for guidance

3. **Reduce Semantic Search Scope:**
   ```yaml
   translation_memory:
     l3_search_k: 5            # Reduce from 10 to 5
     l3_similarity_threshold: 0.85  # Increase threshold
   ```

---

### Issue: L3 Save Operations Taking Too Long

**Symptoms:**
- Save operations >30 seconds
- Translation pauses during saves

**Diagnosis:**

```python
save_stats = l3.get_save_stats()
print(f"Additions since save: {save_stats['additions_since_save']}")
print(f"Save failures: {save_stats['save_failures']}")
```

**Solutions:**

1. **Increase Save Interval:**
   ```yaml
   translation_memory:
     l3_save_interval: 1000  # Save less frequently
   ```

2. **Enable Async Save:**
   ```yaml
   translation_memory:
     l3_async_save: true      # Non-blocking saves
     l3_save_timeout: 60.0    # Allow longer saves
   ```

3. **Use Faster Disk:**
   - Move `data/tm/l3_semantic/` to SSD
   - Check disk I/O with `iostat` or Task Manager

---

## Related Documentation

- [TM Architecture](../architecture/translation-memory.md) - Understanding TM internals
- [TM Maintenance](tm-maintenance.md) - Integrity checks, backups
- [TM Troubleshooting](tm-troubleshooting.md) - Diagnose issues
- [Observability CLI](../reference/observability-cli.md) - Metrics and monitoring

---

**Document Status:** ✅ Complete
**Last Updated:** 2025-12-24
**Feedback:** Report issues or optimization tips to the maintainers

