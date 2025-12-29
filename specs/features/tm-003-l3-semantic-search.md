# TM-003: L3 Semantic Translation Memory

**Feature:** Vector-based fuzzy/semantic matching using FAISS
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Semantic translation memory using sentence embeddings and FAISS vector similarity search. Enables fuzzy matching for near-duplicates, paraphrases, and similar text when exact matches (L1/L2) are unavailable. Includes periodic saves, background save thread, and performance instrumentation.

---

## Entry Points

**API Class:**
```python
L3SemanticTM(
    index_path: Path | str,
    embedding_model: str = "all-MiniLM-L6-v2",
    use_gpu: bool = False,
    use_faiss_gpu: bool = False,
    save_interval: int = 100,
    save_timeout: float = 5.0,
    async_save: bool = False,
)
```

**Primary Methods:**
```python
semantic_search(site_id, src_lang, tgt_lang, query_text, k=10, threshold=0.75) -> List[SemanticMatch]
add_entry(entry_id, site_id, src_lang, tgt_lang, source_text, translation, ...) -> None
batch_add(entries: List[Dict]) -> int
save_index() -> None
load_index() -> None
get_timing_metrics() -> Dict
```

**Registration Site:**
- File: `src/tm/l3_semantic.py`
- Lines: 59-153 (class initialization)
- Lines: 337-432 (semantic_search method)
- Lines: 178-241 (add_entry method with periodic save)

---

## Inputs/Outputs

### Input: Initialization

```python
L3SemanticTM(
    index_path="/data/tm/l3_faiss",         # Index storage directory
    embedding_model="all-MiniLM-L6-v2",     # Sentence transformer model
    use_gpu=False,                          # GPU for embeddings
    use_faiss_gpu=False,                    # GPU for FAISS index
    save_interval=100,                      # Save every N additions (0=disabled)
    save_timeout=5.0,                       # Max seconds for save operation
    async_save=False,                       # Background thread for saves
)
```

**Evidence:** Lines 59-80

### Input: semantic_search

```python
semantic_search(
    site_id: str,              # Site identifier filter
    src_lang: str,             # Source language filter
    tgt_lang: str,             # Target language filter
    query_text: str,           # Text to search for
    k: int = 10,               # Number of results to return
    threshold: float = 0.75,   # Minimum similarity (0-1)
) -> List[SemanticMatch]
```

**Evidence:** Lines 337-345

### Input: add_entry

```python
add_entry(
    entry_id: str,                       # Unique identifier
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    source_text: str,                    # Text to embed
    translation: str,
    context: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
) -> None
```

**Evidence:** Lines 178-188

### Output: SemanticMatch

```python
@dataclass
class SemanticMatch:
    entry_id: str
    similarity: float              # Similarity score (0-1)
    source_text: str
    translation: str
    site_id: str
    src_lang: str
    tgt_lang: str
    context: Optional[str] = None
    metadata: Dict[str, Any] = None
```

**Evidence:** Lines 32-48

---

## Invariants

### Must (Critical)

1. **Embedding before add:**
   - MUST generate embedding for source_text
   - Uses sentence transformer model
   - Evidence: Lines 206-208
   ```python
   embedding = self.encoder.encode(
       source_text, convert_to_numpy=True, show_progress_bar=False
   )
   ```

2. **Synchronized metadata:**
   - Metadata array index MUST match FAISS index position
   - Evidence: Lines 212-225
   ```python
   self.index.add(np.array([embedding], dtype=np.float32))
   # Store metadata at same position
   self.metadata.append(entry_metadata)
   ```

3. **Periodic save triggers:**
   - IF save_interval > 0 AND additions_since_save >= save_interval → trigger save
   - Evidence: Lines 227-241
   ```python
   self._additions_since_save += 1
   if self.save_interval > 0 and self._additions_since_save >= self.save_interval:
       self._trigger_save()
   ```

4. **Filter by site_id, src_lang, tgt_lang:**
   - Search results MUST match all three filters
   - Evidence: Lines 396-401
   ```python
   if (
       meta["site_id"] == site_id
       and meta["src_lang"] == src_lang
       and meta["tgt_lang"] == tgt_lang
       and similarity >= threshold
   ):
   ```

5. **Similarity threshold enforcement:**
   - MUST filter results by threshold (only return >= threshold)
   - Evidence: Line 400

6. **Thread-safe index access:**
   - MUST acquire lock before FAISS operations
   - Evidence: Lines 211, 374
   ```python
   with self._lock:
       self.index.add(...)
   ```

### Should (Important)

7. **Oversample for filtering:**
   - SHOULD search for k * 10 candidates before filtering
   - Ensures enough results after site/lang/threshold filtering
   - Evidence: Lines 377
   ```python
   search_k = min(k * 10, self.index.ntotal)
   ```

8. **Async save for background processing:**
   - SHOULD use async_save=True for production (non-blocking)
   - Evidence: Lines 256-261
   ```python
   if self.async_save and self._executor:
       future = self._executor.submit(self._do_save)
   ```

9. **Log slow operations:**
   - SHOULD log warning if search/add > 100ms
   - Evidence: Lines 236-237, 429-430
   ```python
   if duration_ms > 100:
       logger.warning(f"Slow L3 semantic_search: {duration_ms:.1f}ms")
   ```

### Never (Prohibited)

10. **NEVER add without embedding:**
    - All entries must have embeddings
    - Evidence: Lines 206-212 (no skip path)

11. **NEVER skip save_lock:**
    - Concurrent saves MUST be prevented
    - Evidence: Lines 251-253
    ```python
    if not self._save_lock.acquire(blocking=False):
        logger.debug("Periodic save skipped - already in progress")
        return False
    ```

---

## Semantic Search Algorithm

```
semantic_search(site_id, src_lang, tgt_lang, query_text, k, threshold):
  ┌─────────────────────────────────┐
  │ 1. Check index exists            │
  └────┬────────────────────────────┘
       │
       ├─ index is None OR ntotal == 0?
       │  └─→ Return [] (empty results)
       │
  ┌────▼────────────────────────────┐
  │ 2. Generate query embedding      │
  └────┬────────────────────────────┘
       │
       ├─ encoder.encode(query_text)
       │  └─→ Returns numpy vector
       │
  ┌────▼────────────────────────────┐
  │ 3. FAISS search (oversampled)    │
  └────┬────────────────────────────┘
       │
       ├─ search_k = min(k * 10, index.ntotal)
       ├─ distances, indices = index.search(query, search_k)
       │
  ┌────▼────────────────────────────┐
  │ 4. Convert distances to scores   │
  └────┬────────────────────────────┘
       │
       ├─ similarity = 1.0 / (1.0 + distance)
       │  (Approximate cosine similarity)
       │
  ┌────▼────────────────────────────┐
  │ 5. Filter by criteria            │
  └────┬────────────────────────────┘
       │
       ├─ For each result:
       │  ├─ site_id match? → continue
       │  ├─ src_lang match? → continue
       │  ├─ tgt_lang match? → continue
       │  ├─ similarity >= threshold? → add to results
       │  └─ len(results) >= k? → break
       │
  ┌────▼────────────────────────────┐
  │ 6. Return filtered matches       │
  └────┬────────────────────────────┘
       │
       ▼
     List[SemanticMatch] (sorted by similarity, descending)
```

**Evidence:** Implementation in lines 337-432

---

## Periodic Save Mechanism

### Save Triggering

**Trigger Conditions:**
1. `save_interval > 0` (periodic saves enabled)
2. `_additions_since_save >= save_interval` (threshold reached)

**Evidence:** Lines 239-241

### Save Modes

**Synchronous Save (async_save=False):**
- Blocks add_entry until save completes
- Timeout protection (save_timeout)
- Evidence: Lines 263-264

**Asynchronous Save (async_save=True):**
- Submit to background thread (ThreadPoolExecutor)
- Non-blocking (add_entry continues immediately)
- Single worker thread (max_workers=1)
- Evidence: Lines 112-114, 256-261

### Save Lock

**Purpose:** Prevent concurrent saves

**Mechanism:**
- Non-blocking acquire (blocking=False)
- If lock held → skip save (already in progress)
- Evidence: Lines 251-253

**Rationale:** Multiple add_entry calls can trigger saves simultaneously

### Save Statistics

```python
get_save_stats() -> Dict:
    - total_additions: int
    - additions_since_save: int
    - save_failures: int
    - last_save_time: float (timestamp)
    - save_interval: int
    - async_save: bool
```

**Evidence:** Lines 300-314

---

## Embedding Model Configuration

### Default Model: all-MiniLM-L6-v2

**Characteristics:**
- Embedding dimension: 384
- Balanced speed/quality
- Supports 100+ languages
- Model size: ~90 MB

**Evidence:** Lines 62, 128

### GPU Support

**Embedding GPU (use_gpu=True):**
- Accelerates encoder.encode() on CUDA
- Fallback to CPU if GPU unavailable
- Evidence: Lines 116-123

**FAISS GPU (use_faiss_gpu=True):**
- Moves FAISS index to GPU
- Requires faiss-gpu package
- Fallback to CPU on error
- Evidence: Lines 162-174

---

## Performance Characteristics

### Embedding Generation

- **Complexity:** O(n) where n = text length
- **Latency:** ~5-50ms per text (CPU), ~1-10ms (GPU)
- **Batch optimization:** Use batch_add() for bulk imports

### Semantic Search

- **Complexity:** O(log N) for FAISS IndexFlatL2 (exact search)
- **Latency:** <100ms for typical index sizes (<100K entries)
- **Slow operation threshold:** >100ms triggers warning

**Evidence:** Lines 429-430

### Memory Usage

- **Embeddings:** 384 floats * 4 bytes = 1.5 KB per entry
- **Metadata:** ~500 bytes per entry (text + metadata)
- **Total:** ~2 KB per entry
- **Example:** 100K entries ≈ 200 MB RAM

### Timing Metrics

**Instrumentation (BM-08):**
- `semantic_search_ms`: Search latency deque (bounded)
- `add_entry_ms`: Add latency deque (bounded)
- `batch_add_ms`: Batch add latency deque (bounded)
- `cache_hits`, `cache_misses`: Counters
- `cache_hit_rate`: Computed metric

**Evidence:** Lines 103-109, 316-335

**Bounded storage (TM-07, CFG-01):**
- Deques use configurable maxlen (prevents memory leak)
- Default: `timing_metrics_maxlen` from metrics config
- Evidence: Lines 99-106

---

## Errors and Edge Cases

### Error Handling

**Empty index:**
- Behavior: semantic_search returns []
- No exception raised
- Evidence: Lines 363-367

**Embedding model failure:**
- Behavior: Raises exception from sentence-transformers
- Should propagate to caller

**FAISS search failure:**
- Behavior: Exception propagates
- Lock released automatically (context manager)

**Save timeout exceeded:**
- Behavior: Save operation continues (no hard timeout enforcement)
- save_timeout parameter documented but not strictly enforced
- Evidence: Lines 66 (parameter), no timeout implementation found

**Save failure:**
- Behavior: Log error, increment save_failures, continue
- additions_since_save NOT reset (will retry next time)
- Evidence: Lines 291-298

### Edge Cases

**k > index.ntotal:**
- Behavior: search_k capped at index.ntotal
- Evidence: Line 377

**threshold=1.0 (perfect match only):**
- Behavior: May return 0 results (rare exact semantic match)
- Use L1/L2 for exact matches instead

**threshold=0.0 (accept all):**
- Behavior: Returns top k regardless of quality
- Not recommended (low-quality matches)

**Duplicate source_text with different translations:**
- Behavior: Both entries added with same/similar embeddings
- Search returns multiple matches
- Caller must disambiguate

**Context filtering:**
- Not implemented at L3 layer
- All contexts included in search
- Caller must filter by context if needed

**Concurrent add_entry calls:**
- Behavior: Thread-safe (lock protected)
- Metadata array synchronized with index

---

## Side Effects

### File System

**Reads (on load_index):**
- `{index_path}/index.faiss` (FAISS index binary)
- `{index_path}/metadata.pkl` (Pickled metadata list)
- `{index_path}/config.json` (Configuration)

**Writes (on save_index):**
- `{index_path}/index.faiss` (FAISS index)
- `{index_path}/metadata.pkl` (Metadata)
- `{index_path}/config.json` (Config)
- Atomic writes not guaranteed (no temp + rename)

**Directory Creation:**
- Auto-creates index_path directory
- Evidence: Lines 81-82

### Logging

**Slow operations:**
```python
logger.warning(f"Slow L3 semantic_search: {duration_ms:.1f}ms")
logger.warning(f"Slow L3 add_entry: {duration_ms:.1f}ms")
```

**Periodic saves:**
```python
logger.info(f"Periodic L3 save complete: {total_additions} entries in {duration:.2f}s")
logger.error(f"Periodic L3 save failed ({duration:.2f}s): {e}")
```

**Evidence:** Lines 236-237, 286-297, 429-430

### GPU Resources

**If use_gpu=True:**
- Loads sentence transformer model to CUDA
- GPU memory allocation (~500 MB)

**If use_faiss_gpu=True:**
- Moves FAISS index to GPU
- GPU memory proportional to index size

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Class initialization | src/tm/l3_semantic.py | 59-153 | __init__() |
| semantic_search method | Same | 337-432 | semantic_search() |
| add_entry method | Same | 178-241 | add_entry() |
| Periodic save trigger | Same | 239-241 | _trigger_save() call |
| Save implementation | Same | 243-298 | _trigger_save(), _do_save() |
| batch_add method | Same | 434+ | batch_add() |
| Timing metrics | Same | 316-335 | get_timing_metrics() |
| Save statistics | Same | 300-314 | get_save_stats() |

### Dependencies

| Dependency | Purpose | Import |
|------------|---------|--------|
| faiss | Vector similarity search | External package |
| sentence-transformers | Text embeddings | External package |
| numpy | Array operations | External package |
| ThreadPoolExecutor | Async saves | concurrent.futures |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_l3_semantic.py` (likely) - Unit tests for L3
- Integration tests with TM lookup order

**Missing Contract Tests:**
- Semantic search filtering (site/lang/threshold)
- Periodic save triggering
- Async vs sync save behavior
- Embedding/metadata synchronization
- Slow operation warnings

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_tm_l3_semantic.py`
2. **Test critical invariants:**
   - Embedding before add (no skip)
   - Metadata/index synchronization
   - Periodic save triggers at interval
   - Filter by site_id/src_lang/tgt_lang/threshold
   - Thread safety (concurrent operations)
3. **Test edge cases:**
   - Empty index (return [])
   - k > index size
   - threshold=0.0 and 1.0
   - Save lock contention
4. **Test performance:**
   - Slow operation warnings (>100ms)
   - Timing metrics collection
5. **Link to spec:** Add docstring `CONTRACT: specs/features/tm-003-l3-semantic-search.md`

**Blockers:** None

---

## Related Specs

- [TM-001: L1 In-Memory Cache](tm-001-l1-cache.md) - First TM layer
- [TM-002: L2 Persistent Store](tm-002-l2-persistent-store.md) - Second TM layer
- [SYS-003: TM Lookup Order](sys-003-tm-lookup-order.md) - L1 → L2 → L3 precedence
- [API-001: translate_file Method](api-001-translate-file.md) - Uses TM lookup
