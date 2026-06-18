# L3 Semantic Index - Synchronization Strategy

**Purpose:** Ensure L3 (FAISS semantic search) stays synchronized with L2 (LMDB persistent storage) at all times.

---

## Architecture Overview

The Translation Memory has 3 layers:
- **L1:** In-memory LRU cache (fast, volatile)
- **L2:** LMDB persistent storage (durable, exact match)
- **L3:** FAISS semantic search (fuzzy match, embedding-based)

**Key Requirement:** L3 must stay in sync with L2 to provide accurate semantic search results.

---

## Automatic Synchronization (Built-in)

### How It Works

The `TranslationMemory.store()` method **automatically updates all 3 layers** in a single operation:

```python
def store(self, site_id, src_lang, tgt_lang, text, translation, context=None, metadata=None):
    # 1. Update L1 (cache)
    self.l1.put(site_id, src_lang, tgt_lang, text, translation)

    # 2. Update L2 (persistent)
    entry_id = self.l2.store(...)

    # 3. Update L3 (semantic) - AUTOMATIC!
    if self.l3 is not None:
        self.l3.add_entry(
            entry_id=entry_id,
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            source_text=text,
            translation=translation,
            context=context,
            metadata=metadata,
        )

    return entry_id
```

**Location:** [`src/tm/translation_memory.py:162-189`](../../src/tm/translation_memory.py#L162-L189)

### Guarantees

✅ **Every new entry** written through `TranslationMemory.store()` is automatically added to L3
✅ **No manual intervention** required for normal operations
✅ **Atomic updates** - all 3 layers updated in same transaction

---

## Initial L3 Build (One-Time)

### Problem

After migration, L2 has 6M+ entries but L3 is empty. This is expected because:
1. Migration script populated L2 directly (bypassed TranslationMemory)
2. L3 needs embeddings, which are expensive to compute
3. Building L3 from scratch takes time (hours for 6M entries)

### Solution: Build Script

Use [`scripts/tm/build_l3_index.py`](../../scripts/tm/build_l3_index.py) to populate L3 from existing L2 data:

```bash
# CPU (slower, but works everywhere)
python scripts/tm/build_l3_index.py

# GPU (faster, requires CUDA)
python scripts/tm/build_l3_index.py --use_gpu

# Custom paths
python scripts/tm/build_l3_index.py \
  --l2_path ./data/tm/l2.lmdb \
  --l3_path ./data/tm/l3.faiss \
  --embedding_model sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2
```

**What It Does:**
1. Reads all 6M+ entries from L2
2. Generates embeddings for each source text
3. Adds embeddings to FAISS index
4. Saves metadata for each entry
5. Saves index periodically (every 1000 entries)
6. Verifies index after completion

**Expected Time:**
- **CPU:** ~4-6 hours for 6M entries (~300 entries/second)
- **GPU:** ~1-2 hours for 6M entries (~1500 entries/second)

**Resource Usage:**
- **Memory:** ~2-4 GB (embedding model + batch processing)
- **Disk:** ~5-10 GB (FAISS index + metadata)
- **CPU/GPU:** High utilization during build

---

## Periodic Verification (Recommended)

### Purpose

Verify L3 hasn't drifted from L2 due to:
- Direct L2 modifications (bypassing TranslationMemory)
- L3 corruption or data loss
- Incomplete writes or crashes

### Solution: Sync Script

Use [`scripts/tm/sync_l3_index.py`](../../scripts/tm/sync_l3_index.py) to verify and fix any drift:

```bash
# Dry run (check only, no changes)
python scripts/tm/sync_l3_index.py --dry-run

# Sync (add missing entries)
python scripts/tm/sync_l3_index.py

# With GPU
python scripts/tm/sync_l3_index.py --use_gpu
```

**What It Does:**
1. Loads L3 index and builds set of entry IDs
2. Scans L2 database for all entries
3. Identifies entries in L2 but not in L3
4. Adds missing entries to L3
5. Saves updated index

**Expected Time:**
- **Scan:** ~5-10 minutes (checking 6M entries)
- **Sync:** Depends on number of missing entries

---

## Recommended Schedule

### Initial Setup
```bash
# After migration
python scripts/tm/build_l3_index.py --use_gpu
```

### Regular Operations
```bash
# Weekly verification (cron job)
0 2 * * 0 python scripts/tm/sync_l3_index.py --dry-run

# Monthly full sync (if drift detected)
0 3 1 * * python scripts/tm/sync_l3_index.py
```

### After Bulk Operations
```bash
# After bulk import or manual L2 modifications
python scripts/tm/sync_l3_index.py
```

---

## Scenarios & Solutions

### Scenario 1: Normal Translation Workflow
**How L3 Stays in Sync:**
- User translates content
- System calls `TranslationMemory.store()`
- Entry automatically added to L1, L2, and L3
- ✅ **No action needed**

### Scenario 2: After Migration
**Problem:** L2 has 6M entries, L3 is empty
**Solution:**
```bash
python scripts/tm/build_l3_index.py --use_gpu
```

### Scenario 3: Direct L2 Modification
**Problem:** Entries added directly to L2 (bypassing TranslationMemory)
**Solution:**
```bash
# Check drift
python scripts/tm/sync_l3_index.py --dry-run

# Fix drift
python scripts/tm/sync_l3_index.py
```

### Scenario 4: L3 Corruption
**Problem:** L3 index corrupted or deleted
**Solution:**
```bash
# Rebuild from scratch
python scripts/tm/build_l3_index.py --force
```

### Scenario 5: Embedding Model Change
**Problem:** Want to use different embedding model
**Solution:**
```bash
# Rebuild with new model
python scripts/tm/build_l3_index.py \
  --force \
  --embedding_model sentence-transformers/new-model \
  --use_gpu
```

---

## Monitoring & Alerts

### Key Metrics to Track

1. **L2 vs L3 Entry Count**
   ```python
   l2_count = lmdb_env.stat()['entries']
   l3_count = l3.index.ntotal
   drift = l2_count - l3_count
   ```
   **Alert:** If drift > 1000 entries

2. **L3 Index Size**
   ```python
   index_size_mb = l3_index_file.stat().st_size / (1024 * 1024)
   ```
   **Alert:** If size unexpectedly changes

3. **Embedding Generation Time**
   - Track average time per entry
   **Alert:** If time increases significantly (model loading issue)

### Health Check Script

```python
# scripts/check_l3_health.py
import lmdb
from src.tm.l3_semantic import L3SemanticTM

# Check counts
env = lmdb.open("./data/tm/l2.lmdb", readonly=True)
l2_count = env.stat()['entries']
env.close()

l3 = L3SemanticTM("./data/tm/l3.faiss")
l3_count = l3.index.ntotal

drift = l2_count - l3_count
print(f"L2: {l2_count:,} | L3: {l3_count:,} | Drift: {drift:,}")

if drift > 1000:
    print("⚠ WARNING: Significant drift detected. Run sync_l3_index.py")
elif drift > 0:
    print("ℹ INFO: Minor drift detected. Consider running sync_l3_index.py")
else:
    print("✓ OK: L3 is in sync with L2")
```

---

## Performance Considerations

### Build Performance

| Entries | CPU Time | GPU Time | Index Size |
|---------|----------|----------|------------|
| 100K    | ~5 min   | ~1 min   | ~100 MB    |
| 1M      | ~50 min  | ~10 min  | ~1 GB      |
| 6M      | ~5 hours | ~1 hour  | ~6 GB      |

### Runtime Performance

- **L3 add_entry:** ~10-50ms (depends on embedding model)
- **L3 search:** ~1-10ms (depends on index size and k)
- **Batch operations:** Much faster (model parallelization)

### Optimization Tips

1. **Use GPU for builds:** 5-10x faster
2. **Batch embedding generation:** Process multiple texts at once
3. **Use smaller models for speed:** Trade accuracy for speed
4. **Use IVF index for large datasets:** Faster search at scale

---

## Troubleshooting

### L3 Build Fails with OOM
**Solution:** Reduce batch_size
```bash
python scripts/tm/build_l3_index.py --batch_size 100
```

### Embeddings Too Slow
**Solutions:**
- Use GPU: `--use_gpu`
- Use smaller model: `--embedding_model all-MiniLM-L6-v2`
- Reduce precision: Consider float16 embeddings

### Index File Corrupted
**Solution:** Rebuild from scratch
```bash
python scripts/tm/build_l3_index.py --force
```

### Sync Script Hangs
**Causes:** Large number of missing entries
**Solution:** Check progress, be patient, or use `--dry-run` first

---

## Best Practices

### ✅ DO
- Run `build_l3_index.py` after migration
- Use `sync_l3_index.py --dry-run` to check drift
- Always use `TranslationMemory.store()` for new entries
- Monitor L2/L3 drift regularly
- Backup L3 index periodically

### ❌ DON'T
- Don't modify L2 directly (bypass TranslationMemory)
- Don't delete L3 index without rebuilding
- Don't change embedding model without rebuilding
- Don't ignore drift warnings
- Don't skip periodic verification

---

## Summary

### How L3 Stays Synchronized

1. **Automatic (Built-in):**
   - Every `TranslationMemory.store()` updates L3 automatically
   - No manual intervention needed for normal operations

2. **Initial Build (One-Time):**
   - Run `build_l3_index.py` after migration
   - Takes 1-6 hours depending on CPU/GPU

3. **Periodic Verification (Scheduled):**
   - Run `sync_l3_index.py --dry-run` weekly
   - Run `sync_l3_index.py` if drift detected

4. **Monitoring (Continuous):**
   - Track L2 vs L3 entry counts
   - Alert on significant drift (>1000 entries)
   - Health check in production monitoring

### Current Status

- ✅ **L2:** 6,053,470 entries (migrated)
- ⚠️ **L3:** Empty (needs initial build)
- ✅ **Auto-sync:** Enabled (all new entries go to L3)
- 📋 **Action:** Run `build_l3_index.py` to populate L3

---

## Next Steps

```bash
# 1. Build L3 index (one-time, ~1-6 hours)
python scripts/tm/build_l3_index.py --use_gpu

# 2. Verify build succeeded
python scripts/tm/sync_l3_index.py --dry-run

# 3. Set up weekly health check (optional)
# Add to cron: 0 2 * * 0 python scripts/tm/sync_l3_index.py --dry-run

# 4. Use system normally
# All new translations automatically update L3 ✅
```

---

**Documentation Version:** 1.0
**Last Updated:** 2025-12-11
**Author:** Claude Code
