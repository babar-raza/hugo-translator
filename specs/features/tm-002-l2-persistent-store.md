# TM-002: L2 Persistent Translation Memory

**Feature:** LMDB-backed persistent exact-match translation memory
**Status:** 🔍 EVIDENCE_ONLY
**Last Updated:** 2025-12-26

---

## Summary

Durable key-value store for exact translation matches using LMDB (Lightning Memory-Mapped Database). Provides persistent caching of translations across sessions with fast lookups, atomic writes, and corruption detection.

---

## Entry Points

**API Class:**
```python
L2PersistentTM(
    db_path: Path | str,
    max_size_mb: int = 1024
)
```

**Primary Methods:**
```python
exact_lookup(site_id, src_lang, tgt_lang, text, context=None) -> Optional[TranslationEntry]
store(site_id, src_lang, tgt_lang, text, translation, ...) -> bool
batch_store(entries: List[TranslationEntry]) -> int
delete(site_id, src_lang, tgt_lang, text) -> bool
count() -> int
clear() -> None
```

**Registration Site:**
- File: `src/tm/l2_persistent.py`
- Lines: 81-113 (class initialization)
- Lines: 114-170 (exact_lookup method)
- Lines: 172-254 (store method)

---

## Inputs/Outputs

### Input: Initialization

```python
L2PersistentTM(
    db_path="/data/tm/l2_lmdb",      # LMDB database directory
    max_size_mb=1024                  # Max DB size (default: 1GB)
)
```

**Evidence:** Lines 89-110

### Input: exact_lookup

```python
exact_lookup(
    site_id: str,              # Site identifier (e.g., "products.aspose.net")
    src_lang: str,             # Source language code (e.g., "en")
    tgt_lang: str,             # Target language code (e.g., "fr")
    text: str,                 # Source text to look up
    context: Optional[str] = None  # Optional context for disambiguation
) -> Optional[TranslationEntry]
```

**Evidence:** Lines 114-121

### Input: store

```python
store(
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    translation: str,
    context: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    overwrite: bool = True        # If False, skip if exists
) -> bool  # True if stored, False if skipped
```

**Evidence:** Lines 172-182

### Output: TranslationEntry

```python
@dataclass
class TranslationEntry:
    source_text: str
    translation: str
    site_id: str
    src_lang: str
    tgt_lang: str
    context: Optional[str] = None      # Frontmatter key, AST path, etc.
    timestamp: Optional[str] = None    # ISO 8601 UTC timestamp
    metadata: Dict[str, Any] = None    # Arbitrary additional data
```

**Evidence:** Lines 22-44

---

## Invariants

### Must (Critical)

1. **Exact key matching:**
   - Key construction: `make_tm_key(site_id, src_lang, tgt_lang, text)`
   - MUST use exact text match (no normalization in key)
   - Evidence: Lines 135, 222
   ```python
   key = make_tm_key(site_id, src_lang, tgt_lang, text)
   ```

2. **Corruption detection on lookup:**
   - MUST catch JSON deserialization errors
   - MUST validate entry with `entry.is_valid()`
   - IF corrupted → log warning and return None (skip entry)
   - Evidence: Lines 144-164
   ```python
   try:
       value_dict = json.loads(value_bytes.decode("utf-8"))
       entry = TranslationEntry.from_dict(value_dict)
   except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
       logger.warning(f"Corrupted cache entry detected and skipped: ...")
       return None

   if not entry.is_valid():
       logger.warning(f"Invalid cache entry detected and skipped: ...")
       return None
   ```

3. **Validation before write:**
   - MUST validate entry with `entry.is_valid()` before storing
   - IF validation fails → raise ValueError
   - Evidence: Lines 214-220
   ```python
   if not entry.is_valid():
       raise ValueError("Translation entry failed validation")
   ```

4. **Atomic writes:**
   - MUST use LMDB transaction with automatic rollback
   - Evidence: Lines 228, 283 (write=True transaction)
   ```python
   with self.env.begin(write=True) as txn:
       # Atomic write - rollback on exception
   ```

5. **Thread-safe operations:**
   - MUST acquire lock before LMDB operations
   - Uses threading.RLock (reentrant lock)
   - Evidence: Lines 112, 137, 226
   ```python
   with self._lock:
       with self.env.begin() as txn:
   ```

6. **Context filtering:**
   - IF context specified in lookup → filter by context match
   - Evidence: Lines 166-168
   ```python
   if context is not None and entry.context != context:
       return None
   ```

### Should (Important)

7. **LMDB sync enabled:**
   - SHOULD enable sync for durability (sync=True)
   - Evidence: Line 108
   ```python
   sync=True,  # Ensure durability
   ```

8. **Writemap disabled:**
   - SHOULD disable writemap for safer concurrent access
   - Evidence: Line 109
   ```python
   writemap=False,  # Safer for concurrent access
   ```

9. **Auto-timestamp:**
   - SHOULD auto-set timestamp if not provided
   - Evidence: Lines 36-38, 294-295
   ```python
   if self.timestamp is None:
       self.timestamp = datetime.now(timezone.utc).isoformat()
   ```

### Never (Prohibited)

10. **NEVER store invalid entries:**
    - All writes MUST pass validation
    - Evidence: Lines 214-220, 271-278 (batch validation)

11. **NEVER skip corruption detection:**
    - All reads MUST handle deserialization errors
    - Evidence: Lines 144-164

---

## Validation Logic (TranslationEntry.is_valid)

```python
def is_valid(self) -> bool:
    # Required fields: non-empty strings
    - source_text: isinstance(str) AND not empty
    - translation: isinstance(str) AND not empty
    - site_id: isinstance(str) AND not empty
    - src_lang: isinstance(str) AND not empty
    - tgt_lang: isinstance(str) AND not empty

    # Optional fields: correct types if present
    - context: isinstance(str) OR None
    - metadata: isinstance(dict) OR None
    - timestamp: isinstance(str) OR None

    Return: True if all checks pass, False otherwise
```

**Evidence:** Lines 51-78

---

## Database Configuration

### LMDB Parameters

```python
lmdb.open(
    str(db_path),
    map_size=max_size_mb * 1024 * 1024,  # Convert MB to bytes
    max_dbs=1,                            # Single database
    sync=True,                            # Fsync on commit (durability)
    writemap=False,                       # Safer for concurrent access
)
```

**Evidence:** Lines 104-110

**Default Values:**
- `max_size_mb`: 1024 (1 GB)
- `max_dbs`: 1
- `sync`: True
- `writemap`: False

**Storage:**
- Location: `{db_path}/` (LMDB creates data.mdb and lock.mdb)
- Format: Memory-mapped B+ tree

---

## Performance Characteristics

### Lookup Performance

- **Complexity:** O(1) average (B+ tree lookup)
- **Latency:** <1ms for typical entries
- **Cache hits:** Extremely fast (memory-mapped)

### Write Performance

- **Complexity:** O(log N) for insert (B+ tree)
- **Batch operations:** Significantly faster than individual writes
- **Durability overhead:** Fsync on every transaction (sync=True)

**Optimization:** Use `batch_store()` for bulk imports

### Concurrency

- **Reads:** Multiple readers supported (MVCC)
- **Writes:** Single writer at a time (LMDB limitation)
- **Lock contention:** RLock prevents Python-level race conditions

---

## Batch Operations

### batch_store Method

```python
batch_store(entries: List[TranslationEntry]) -> int
```

**Behavior:**
1. Validate all entries before starting transaction
2. Open single write transaction
3. Store all entries atomically
4. Return count of entries stored

**Advantages:**
- Atomic: All entries stored or none (transaction rollback)
- Fast: Single transaction overhead instead of N transactions
- Validated: All entries validated before write begins

**Evidence:** Lines 256-312

**Example:**
```python
entries = [
    TranslationEntry(source_text="Hello", translation="Bonjour", ...),
    TranslationEntry(source_text="World", translation="Monde", ...),
]
count = l2_tm.batch_store(entries)
# count = 2 (both entries stored in single transaction)
```

---

## Errors and Edge Cases

### Error Handling

**Corrupted cache entry (lookup):**
- Behavior: Log warning, return None
- No exception raised (graceful degradation)
- Evidence: Lines 144-164

**Invalid entry (write):**
- Behavior: Raise ValueError
- Transaction rolled back automatically
- Evidence: Lines 214-220

**JSON serialization failure:**
- Behavior: Raise RuntimeError
- Transaction rolled back
- Evidence: Lines 236-240

**LMDB write failure:**
- Behavior: Raise exception, log error
- Transaction rolled back automatically
- Evidence: Lines 247-254

### Edge Cases

**Context mismatch:**
- Lookup with context="foo" → returns None if entry.context="bar"
- Allows same text with different contexts
- Evidence: Lines 166-168

**Overwrite=False with existing entry:**
- Behavior: Return False (skip), no write
- Evidence: Lines 230-233

**Empty text string:**
- Behavior: Validation fails, raises ValueError
- Evidence: Lines 59-60 (is_valid check)

**Null/None source_text:**
- Behavior: Validation fails (isinstance check)
- Evidence: Lines 59-60

**Database full (map_size exceeded):**
- Behavior: LMDB raises MDB_MAP_FULL exception
- User action: Increase max_size_mb or clear old entries

**Concurrent writes from multiple processes:**
- Behavior: LMDB handles synchronization
- Single writer at a time (LMDB lock)

---

## Side Effects

### File System

**Reads:**
- Memory-mapped read from `{db_path}/data.mdb`

**Writes:**
- Write to `{db_path}/data.mdb` (atomic via LMDB)
- Fsync on commit (sync=True)
- Lock file: `{db_path}/lock.mdb` (LMDB internal)

**Directory Creation:**
- Auto-creates db_path directory if not exists
- Evidence: Lines 97-98
```python
self.db_path = Path(db_path)
self.db_path.mkdir(parents=True, exist_ok=True)
```

### Logging

**Corruption warnings:**
```python
logger.warning(f"Corrupted cache entry detected and skipped: ...")
logger.warning(f"Invalid cache entry detected and skipped: ...")
```

**Write failures:**
```python
logger.error(f"Invalid translation entry rejected: ...")
logger.error(f"Cache write failed (integrity safeguard triggered): ...")
```

**Evidence:** Lines 150-163, 216-220, 249-253

### No Network Effects

- Entirely local file system
- No external API calls

---

## Evidence

### Code Locations

| Component | File | Lines | Symbol |
|-----------|------|-------|--------|
| Class definition | src/tm/l2_persistent.py | 81-113 | L2PersistentTM |
| exact_lookup method | Same | 114-170 | exact_lookup() |
| store method | Same | 172-254 | store() |
| batch_store method | Same | 256-312 | batch_store() |
| delete method | Same | 314-333 | delete() |
| count method | Same | 335-344 | count() |
| clear method | Same | 346+ | clear() |
| TranslationEntry dataclass | Same | 22-78 | TranslationEntry |
| Validation logic | Same | 51-78 | is_valid() |

### Dependencies

| Dependency | Purpose | Import |
|------------|---------|--------|
| lmdb | Persistent key-value store | External package |
| json | Entry serialization | Standard library |
| threading | Thread safety (RLock) | Standard library |
| make_tm_key | Key construction | src/tm/normalization.py |

### Test Evidence

**Existing Tests:**
- `tests/unit/test_l2_persistent.py` (likely) - Unit tests for L2
- Integration tests with TM lookup order

**Missing Contract Tests:**
- Corruption detection (return None on bad data)
- Validation enforcement (ValueError on invalid entry)
- Atomic writes (rollback on exception)
- Thread safety (concurrent access)
- Context filtering (same text, different contexts)

---

## Verification Status

🔍 **EVIDENCE_ONLY**

**Verification Steps Required:**

1. **Create contract test:** `tests/contract/test_tm_l2_persistent.py`
2. **Test critical invariants:**
   - Exact key matching (no false positives)
   - Corruption detection (graceful degradation)
   - Validation before write (ValueError on invalid)
   - Atomic writes (rollback on failure)
   - Thread safety (concurrent readers/writers)
3. **Test edge cases:**
   - Context filtering
   - overwrite=False with existing entry
   - Empty/null text
   - Database full (map_size exceeded)
4. **Test batch operations:**
   - batch_store atomicity
   - Validation before transaction
5. **Link to spec:** Add docstring `CONTRACT: specs/features/tm-002-l2-persistent-store.md`

**Blockers:** None

---

## Related Specs

- [TM-001: L1 In-Memory Cache](tm-001-l1-cache.md) - First TM layer
- [TM-003: L3 Semantic Search](tm-003-l3-semantic-search.md) - Third TM layer
- [SYS-003: TM Lookup Order](sys-003-tm-lookup-order.md) - L1 → L2 → L3 precedence
- [API-001: translate_file Method](api-001-translate-file.md) - Uses TM lookup
