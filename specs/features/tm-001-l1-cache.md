# TM-001: L1 In-Memory Cache

**Feature:** Translation Memory Layer 1 (in-memory LRU cache)
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Fast in-memory LRU (Least Recently Used) cache for translation lookups. First layer in 3-layer Translation Memory hierarchy. Provides sub-millisecond lookup times for frequently accessed translations.

---

## Entry Points

**API Class:** `L1Cache`

**Registration Site:**
- File: `src/tm/l1_cache.py`
- Symbol: `L1Cache` class

**Integration:**
- Used by: `TranslationMemory` class
- Position: First lookup layer (L1 → L2 → L3)

---

## Inputs/Outputs

### Initialization

```python
L1Cache(max_size: int = 10000)
```

**Parameters:**
- `max_size`: Maximum number of entries (default: 10000)
- Rationale: Balance memory usage vs hit rate

### Lookup Method

```python
def get(
    site_id: str,
    source_text: str,
    source_lang: str,
    target_lang: str
) -> Optional[str]
```

**Returns:**
- `str`: Translated text (if found)
- `None`: Cache miss

### Store Method

```python
def put(
    site_id: str,
    source_text: str,
    source_lang: str,
    target_lang: str,
    target_text: str
) -> None
```

**Side Effect:** Stores translation, may evict LRU entry if cache full

---

## Invariants

### Must (Critical)

1. **LRU eviction policy:**
   - MUST evict least recently used entry when cache is full
   - Evidence: LRU cache implementation (OrderedDict or similar)
   - Rationale: Maximize hit rate for frequently accessed translations

2. **Key uniqueness:**
   - Cache key MUST be tuple: (site_id, source_text, source_lang, target_lang)
   - Evidence: Key construction in get/put methods
   - Rationale: Different sites/languages may have different translations for same source text

3. **Get updates recency:**
   - Successful `get()` MUST mark entry as recently used
   - Evidence: LRU cache behavior
   - Rationale: Prevent eviction of frequently accessed entries

4. **Thread-safe access:**
   - MUST support concurrent reads and writes without corruption
   - Evidence: Lock usage or thread-safe data structure
   - Rationale: Multiple workers or threads may access cache

### Should (Important)

5. **Cache statistics:**
   - SHOULD track hits, misses, evictions
   - Evidence: `get_stats()` method
   - Rationale: Observability and optimization

6. **Size limit enforcement:**
   - SHOULD enforce max_size limit strictly
   - Evidence: Eviction trigger on put()

### Never (Prohibited)

7. **NEVER exceed max_size:**
   - Cache size must never grow beyond max_size
   - Eviction must occur before insertion if at limit

8. **NEVER return stale data:**
   - No TTL expiration (entries valid until evicted)
   - Rationale: Translation correctness is permanent for given source/lang pair

---

## Cache Key Structure

### Key Components

```python
cache_key = (site_id, source_text, source_lang, target_lang)
```

**Example:**
```python
("products.aspose.net", "Hello world", "en", "fr")
→ Cache entry: "Bonjour le monde"
```

### Key Normalization

**Source text normalization:**
- Likely: Whitespace normalization (strip, collapse multiple spaces)
- Evidence: Check `src/tm/normalization.py` for normalize_text()
- Rationale: "Hello  world" (2 spaces) should match "Hello world" (1 space)

**Case sensitivity:**
- Likely: Case-sensitive (preserve original case)
- Rationale: Translation may depend on case ("Apple" company vs "apple" fruit)

---

## Performance Characteristics

### Lookup Performance

**Best Case (Hit):**
- Time: O(1) - Hash table lookup
- Latency: <1ms (in-memory)

**Worst Case (Miss):**
- Time: O(1) - Hash table lookup
- Latency: <1ms, but triggers L2 lookup

### Memory Usage

**Per Entry:**
- ~200-500 bytes (key + value strings)
- Example: 10,000 entries ≈ 2-5 MB

**Total:**
- `max_size * avg_entry_size`
- Default: 10,000 * 300 bytes ≈ 3 MB

### Eviction Overhead

**Eviction Cost:**
- O(1) - Remove LRU entry, insert new entry
- Negligible (pointer updates)

---

## Configuration

### Construction Parameters

```python
# Default configuration
l1_cache = L1Cache(max_size=10000)

# High-memory configuration
l1_cache = L1Cache(max_size=50000)

# Low-memory configuration
l1_cache = L1Cache(max_size=1000)
```

### Tuning Guidelines

| Use Case | max_size | Rationale |
|----------|----------|-----------|
| Desktop/CLI | 10,000 | Balanced (3-5 MB) |
| Server/Worker | 50,000+ | High hit rate (15-25 MB) |
| Embedded/Limited | 1,000-5,000 | Conserve memory |

**Evidence:** Default value in class definition or config

---

## Statistics and Observability

### Statistics Tracking

```python
@dataclass
class L1CacheStats:
    size: int                    # Current entry count
    max_size: int               # Maximum capacity
    hits: int                   # Successful lookups
    misses: int                 # Failed lookups
    evictions: int              # LRU evictions
    hit_rate: float             # hits / (hits + misses)
```

### Methods

```python
def get_stats() -> L1CacheStats:
    """Return current cache statistics."""
    pass

def reset_stats() -> None:
    """Reset hit/miss counters (for benchmarking)."""
    pass
```

---

## Errors and Edge Cases

### Edge Cases

**Empty cache:**
- Behavior: All lookups miss, forwards to L2
- Evidence: Initial state

**Full cache:**
- Behavior: Evict LRU entry before insert
- Evidence: Eviction logic in put()

**Duplicate put:**
- Behavior: Updates existing entry, marks as recently used
- Evidence: Overwrite behavior in put()

**Concurrent access:**
- Behavior: Thread-safe operations (lock or lock-free structure)
- Evidence: Lock usage or concurrent data structure

**Cache key collision:**
- Behavior: Impossible (tuple keys are unique by value equality)
- Evidence: Python hash table semantics

---

## Side Effects

### State Changes

**On get() hit:**
- Increments hit counter
- Moves entry to MRU position (most recently used)

**On get() miss:**
- Increments miss counter
- No cache modification

**On put():**
- Inserts or updates entry
- May trigger eviction (if at max_size)
- Increments eviction counter (if evicted)

### No External Side Effects

L1 cache is **pure in-memory state**:
- No file system access
- No network calls
- No database writes

---

## Evidence

### Code Locations

| Component | File | Symbol |
|-----------|------|--------|
| L1Cache class | src/tm/l1_cache.py | L1Cache |
| get() method | src/tm/l1_cache.py | L1Cache.get() |
| put() method | src/tm/l1_cache.py | L1Cache.put() |
| get_stats() method | src/tm/l1_cache.py | L1Cache.get_stats() |
| Integration | src/tm/translation_memory.py | TranslationMemory.exact_lookup() |

### Data Structure Evidence

**LRU Implementation:**
- Likely: `collections.OrderedDict` (Python stdlib)
- Alternative: `functools.lru_cache` (if simple)
- Alternative: Custom LRU with doubly-linked list + hash map

**Evidence Location:** Check imports and class definition in `src/tm/l1_cache.py`

### Test Evidence

**Existing Tests:**
- `tests/unit/phase-3/test_l1_cache.py` - Unit tests for L1 cache

**Missing Contract Tests:**
- LRU eviction behavior (verify LRU entry evicted, not random)
- max_size enforcement (verify never exceeds limit)
- Thread-safety (concurrent access from multiple threads)
- Key uniqueness (different sites/languages get different entries)

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_tm_l1_cache.py`
2. **Test invariants:**
   - LRU eviction policy (fill cache, verify LRU evicted)
   - max_size enforcement (verify size never exceeds limit)
   - Key uniqueness (same text, different site/lang)
   - Thread-safety (concurrent get/put)
3. **Test statistics:**
   - Hit/miss tracking accuracy
   - Eviction counting
   - Hit rate calculation
4. **Test edge cases:**
   - Empty cache
   - Full cache
   - Duplicate put
5. **Link to spec:** Add docstring `CONTRACT: specs/features/tm-001-l1-cache.md`

**Blockers:** None

---

## Related Specs

- [TM-002: L2 Persistent Store](tm-002-l2-persistent.md) - Next lookup layer
- [TM-003: L3 Semantic Search](tm-003-l3-semantic.md) - Final lookup layer
- [API-001: translate_file Method](api-001-translate-file.md) - Uses TM for lookups
