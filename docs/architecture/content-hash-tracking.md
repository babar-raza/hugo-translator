# Content Hash Tracking Architecture

## Overview

Content hash tracking is a file change detection system that uses cryptographic hashing to accurately identify content changes, eliminating false positives from timestamp-based detection.

**Problem**: Modification time (mtime) triggers retranslation when files are touched but content is unchanged (git operations, file copies, build systems).

**Solution**: Compute and persist content hashes (MD5/SHA256) with fast-path mtime optimization for performance.

## Design Principles

1. **Accuracy**: Use cryptographic hashes for deterministic change detection
2. **Performance**: Fast-path mtime check avoids redundant hashing
3. **Reliability**: Atomic writes with corruption recovery
4. **Compatibility**: Graceful degradation to mtime on errors
5. **Simplicity**: Single-writer design, no locking needed

## Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                     TranslationEngine                        │
│                                                              │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  _should_skip_translation()                            │ │
│  │                                                        │ │
│  │  1. Force retranslate? → No skip                      │ │
│  │  2. Output exists?      → Skip if missing             │ │
│  │  3. Content hash enabled?                             │ │
│  │     ├─ Yes → check_source_changed()                   │ │
│  │     │         ├─ Fast path: mtime unchanged? → Skip   │ │
│  │     │         └─ Slow path: hash unchanged?  → Skip   │ │
│  │     └─ No  → Fall back to mtime comparison            │ │
│  └────────────────────────────────────────────────────────┘ │
│                           ▼                                  │
│  ┌────────────────────────────────────────────────────────┐ │
│  │  After successful translation:                         │ │
│  │  - update_source(file)     # Compute and store hash   │ │
│  │  - update_output(...)       # Record translation      │ │
│  │  - save()                   # Atomic write            │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │      MetadataTracker                  │
        │  (src/utils/metadata_tracker.py)      │
        │                                       │
        │  ┌─────────────────────────────────┐ │
        │  │  _data: Dict[str, FileMetadata] │ │
        │  │    ├─ source: SourceFileMetadata│ │
        │  │    │    ├─ hash: str            │ │
        │  │    │    ├─ last_modified: ISO   │ │
        │  │    │    └─ size_bytes: int      │ │
        │  │    └─ outputs: Dict[lang, ...]  │ │
        │  └─────────────────────────────────┘ │
        │                                       │
        │  Methods:                             │
        │  - load()                  # From disk│
        │  - save()                  # Atomic   │
        │  - check_source_changed()  # Fast path│
        │  - update_source()         # Hash     │
        │  - update_output()         # Track    │
        └───────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │      compute_file_hash()              │
        │  (src/utils/content_hash.py)          │
        │                                       │
        │  Algorithms:                          │
        │  - MD5     (~500 MB/s)                │
        │  - SHA1    (~400 MB/s)                │
        │  - SHA256  (~200 MB/s)                │
        │                                       │
        │  Chunk-based reading (8 KB default)   │
        └───────────────────────────────────────┘
                            │
                            ▼
        ┌───────────────────────────────────────┐
        │      .translation_metadata.json       │
        │  (Persistent storage in output dir)   │
        │                                       │
        │  Schema version: 1.0                  │
        │  Atomic writes via temp + rename      │
        │  Corruption detection on load         │
        └───────────────────────────────────────┘
```

## Component Details

### 1. Content Hash Utility (`src/utils/content_hash.py`)

**Purpose**: Compute cryptographic hashes of file contents.

**API**:
```python
def compute_file_hash(
    file_path: Path,
    algorithm: HashAlgorithm = "md5",
    chunk_size: int = 8192,
) -> str:
    """Compute content hash of a file."""

def quick_hash_check(
    file_path: Path,
    stored_hash: str,
    algorithm: HashAlgorithm = "md5",
) -> bool:
    """Quick validation: Compare stored hash with current file."""
```

**Design Decisions**:
- **Chunk-based reading** (8 KB default): Supports large files without memory issues
- **MD5 default**: Fast enough (<20ms for 10MB), collision risk negligible for change detection
- **SHA256 option**: For security-critical use cases (2.5x slower)
- **Exception handling**: Raises `ContentHashError` on I/O failures

**Performance**:
| Algorithm | Speed     | 10 MB file | Use Case |
|-----------|-----------|------------|----------|
| MD5       | ~500 MB/s | <20ms      | Recommended (fast) |
| SHA1      | ~400 MB/s | ~25ms      | Legacy support |
| SHA256    | ~200 MB/s | ~50ms      | High security |

### 2. Metadata Tracker (`src/utils/metadata_tracker.py`)

**Purpose**: Persistent storage and change detection for file hashes.

**Data Model**:
```python
@dataclass
class SourceFileMetadata:
    path: str
    hash: str               # Content hash
    last_modified: str      # ISO 8601 timestamp
    size_bytes: int
    hash_computed_at: str   # ISO 8601 timestamp

@dataclass
class OutputFileMetadata:
    path: str
    hash: str                         # Output content hash
    translated_at: str                # ISO 8601 timestamp
    source_hash_at_translation: str   # Source hash when translated
    size_bytes: int
    status: str                       # "success" | "failed"

@dataclass
class FileMetadata:
    source: SourceFileMetadata
    outputs: Dict[str, OutputFileMetadata]  # {lang_code: metadata}
```

**Key Methods**:

1. **`check_source_changed()`**: Fast-path + slow-path detection
   ```python
   def check_source_changed(
       self,
       source_path: Path,
       fast_path_mtime: bool = True
   ) -> tuple[bool, str]:
       # Fast path: mtime unchanged → assume unchanged
       if fast_path_mtime and mtime_unchanged:
           return (False, "mtime unchanged")

       # Slow path: compute and compare hash
       current_hash = compute_file_hash(source_path)
       if current_hash == stored_hash:
           return (False, "hash match")
       else:
           return (True, "hash changed")
   ```

2. **`load()`**: Corruption recovery
   ```python
   def load(self) -> None:
       try:
           raw = json.load(metadata_file)
           # Validate schema, parse data
       except (JSONDecodeError, KeyError, ValueError):
           logger.warning("Metadata corrupted, rebuilding")
           self._data = {}  # Start fresh
   ```

3. **`save()`**: Atomic writes
   ```python
   def save(self) -> None:
       content = json.dumps(output, indent=2)
       atomic_write(self.metadata_file, content, fsync=True)
   ```

**Design Decisions**:
- **Fast-path mtime optimization**: Avoids hash recomputation (~99% of cases)
- **Atomic writes**: Prevents corruption from interrupted writes
- **Corruption recovery**: Graceful degradation to empty state
- **Schema versioning**: Future-proof (currently v1.0)
- **Per-site metadata**: One file per output directory (no global state)

### 3. Translation Engine Integration

**Modified Methods**:

1. **`__init__()` (line 385-391)**:
   ```python
   self.enable_content_hash = kwargs.get('enable_content_hash_tracking', False)
   if self.enable_content_hash:
       self.metadata_tracker = None  # Lazy init per-site
   ```

2. **`_should_skip_translation()` (line 507-585)**:
   ```python
   # Content hash check (if enabled)
   if self.enable_content_hash and self.metadata_tracker:
       changed, reason = self.metadata_tracker.check_source_changed(
           source_path, fast_path_mtime=True
       )
       if not changed:
           return (True, f"content unchanged: {reason}")
       return (False, f"content changed: {reason}")
   ```

3. **`translate_file()` - Metadata tracker initialization (line 681-698)**:
   ```python
   # Initialize per-site metadata tracker
   if self.enable_content_hash and not self.metadata_tracker:
       metadata_file = output_dir / ".translation_metadata.json"
       self.metadata_tracker = MetadataTracker(
           metadata_file=metadata_file,
           hash_algorithm=hash_algorithm,
           site_id=site_id,
       )
       self.metadata_tracker.load()
   ```

4. **`translate_file()` - After translation (line 1003-1017)**:
   ```python
   # Update content hash metadata
   if self.enable_content_hash and self.metadata_tracker:
       source_hash = self.metadata_tracker.update_source(source_path)
       self.metadata_tracker.update_output(
           source_path, output_path, target_lang, source_hash, "success"
       )
       self.metadata_tracker.save()
   ```

**Integration Points**:
- **Config loading**: `get_global_config()` → `enable_content_hash_tracking`
- **CLI flags**: `--disable-content-hash`, `--rebuild-content-hashes`
- **Per-site initialization**: Metadata tracker created once per site
- **Graceful fallback**: Errors logged, falls back to mtime

### 4. CLI Integration

**New Flags**:
```python
cache_group.add_argument(
    "--disable-content-hash",
    action="store_true",
    help="Disable content hash tracking",
)

cache_group.add_argument(
    "--rebuild-content-hashes",
    action="store_true",
    help="Rebuild hashes from scratch",
)

cache_group.add_argument(
    "--validate-output-integrity",
    action="store_true",
    help="Validate output integrity",
)
```

**Rebuild Logic** (line 1541-1555):
```python
if overrides.rebuild_content_hashes:
    metadata_file = output_dir / ".translation_metadata.json"
    if metadata_file.exists():
        logger.info("Rebuild requested, removing metadata")
        metadata_file.unlink()
```

## Decision Rationale

### 1. Why MD5 over SHA256?

**Decision**: Default to MD5, offer SHA256 as option.

**Rationale**:
- **Use case**: Change detection, not cryptographic security
- **Performance**: MD5 is 2.5x faster than SHA256 (~500 MB/s vs ~200 MB/s)
- **Collision risk**: Negligible for this use case (intentional collisions require attacker)
- **Precedent**: Git uses SHA1 for similar purpose

**Trade-off**: SHA256 available for security-critical environments.

### 2. Why Fast-Path Mtime Optimization?

**Decision**: Check mtime before computing hash.

**Rationale**:
- **Common case**: Most files unchanged between runs (~99%)
- **Performance**: Mtime check is ~1000x faster than hash computation
- **Accuracy**: Mtime change is necessary (but not sufficient) for content change

**Trade-off**: Rare edge case where mtime reverted (requires manual tampering).

### 3. Why Per-Site Metadata Instead of Global?

**Decision**: One `.translation_metadata.json` per output directory.

**Rationale**:
- **Isolation**: Each site's metadata independent (no cross-contamination)
- **Simplicity**: No global state, easier to reason about
- **Portability**: Metadata travels with output directory
- **Cleanup**: Delete output dir removes metadata automatically

**Trade-off**: Slight disk space overhead (multiple metadata files).

### 4. Why JSON Over SQLite?

**Decision**: Use JSON with atomic writes.

**Rationale**:
- **Simplicity**: No DB library dependency, human-readable
- **Compatibility**: Works everywhere (Windows, Linux, Docker)
- **Performance**: Sufficient for expected file counts (<10,000)
- **Atomicity**: `atomic_write` utility provides ACID guarantees

**Trade-off**: SQLite would scale better for >100,000 files (unlikely in this domain).

### 5. Why Corruption Recovery Over Strict Validation?

**Decision**: Gracefully recover by resetting to empty state.

**Rationale**:
- **User experience**: Translation continues (vs. crashing)
- **Repair cost**: One-time rehashing (vs. manual intervention)
- **Failure modes**: Disk errors, interrupted writes, manual edits

**Trade-off**: Silently loses metadata history (acceptable, can rebuild).

## Performance Characteristics

### Overhead Analysis

**Scenario 1: First Run (No Metadata)**
- Hash all source files: ~1-2% overhead
- Example: 1000 files × 50 KB average = 50 MB
  - Hash time: 50 MB / 500 MB/s = 0.1 seconds
  - Translation time: ~10-60 seconds (model inference dominates)
  - Overhead: <1%

**Scenario 2: Subsequent Run (Metadata Exists, No Changes)**
- Fast-path mtime check: ~0.1% overhead
- Example: 1000 files × 1 stat() call = 1000 syscalls
  - Stat time: ~1ms total
  - Overhead: negligible

**Scenario 3: Partial Changes (10% Modified)**
- Fast-path: 90% of files (mtime unchanged)
- Slow-path: 10% of files (hash recomputed)
- Example: 100 files rehashed × 50 KB = 5 MB
  - Hash time: 5 MB / 500 MB/s = 0.01 seconds
  - Overhead: ~0.1%

**Conclusion**: Overall overhead <2% in worst case, <0.5% typical.

### Memory Usage

- **In-memory cache**: Configurable LRU cache (default: 1000 entries)
  - Per entry: ~200 bytes (path + hash + metadata)
  - Total: 1000 × 200 bytes = 200 KB
- **JSON metadata**: Loaded into memory on engine initialization
  - Example: 1000 files → ~500 KB JSON (uncompressed)
- **Total**: <1 MB additional memory

## Future Enhancements

### 1. Incremental Hashing for Large Files

**Problem**: Large files (>100 MB) slow to hash.

**Solution**: Store partial hashes at regular intervals, detect changes faster.

**Implementation**:
```python
def incremental_hash(file_path: Path, checkpoint_size: int = 10 * 1024 * 1024):
    """Hash file in chunks, store checkpoints."""
    checkpoints = []
    hasher = hashlib.md5()

    with open(file_path, "rb") as f:
        while chunk := f.read(checkpoint_size):
            hasher.update(chunk)
            checkpoints.append(hasher.hexdigest())

    return checkpoints
```

### 2. Parallel Hashing

**Problem**: Large projects with many files could parallelize hashing.

**Solution**: Thread pool for hash computation.

**Implementation**:
```python
from concurrent.futures import ThreadPoolExecutor

def hash_files_parallel(files: List[Path], max_workers: int = 4):
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        hashes = executor.map(compute_file_hash, files)
    return dict(zip(files, hashes))
```

### 3. Content-Addressed Storage

**Problem**: Duplicate content across sites wastes storage.

**Solution**: Store translations by content hash (deduplication).

**Implementation**: Similar to Git objects (`.git/objects/`).

### 4. Differential Hashing

**Problem**: Large files with small changes require full rehash.

**Solution**: rsync-style rolling hash to detect changed regions.

**Trade-off**: Complexity vs. marginal performance gain (not worth it for typical Markdown files).

## Migration Path

### Phase 1: Opt-In (Current)
- Feature flag: `enable_content_hash_tracking: false` (default)
- Users enable manually to test
- Metrics collected on performance impact

### Phase 2: Opt-Out
- Feature flag: `enable_content_hash_tracking: true` (default)
- Users can disable with `--disable-content-hash`
- Widespread adoption

### Phase 3: Required
- Remove mtime fallback (content hash only)
- Simplify code, improve performance
- Requires migration guide for users

## Testing Strategy

### Unit Tests
- `test_content_hash.py`: Hash computation, algorithms, performance
- `test_metadata_tracker.py`: Load/save, change detection, corruption recovery
- `test_engine_content_hash.py`: Engine integration, skip logic
- `test_cli_content_hash.py`: CLI flag parsing, overrides

### Integration Tests
- `test_content_hash_e2e.py`: End-to-end workflows
  - Touch without changes → skip
  - Modify content → retranslate
  - Metadata persistence across sessions
  - Corruption recovery
  - Performance benchmarks

### Manual Testing
```bash
# Test git workflow
git checkout feature-branch
translate-hugo --site example.com  # Should skip unchanged files

# Test rebuild
translate-hugo --site example.com --rebuild-content-hashes

# Test corruption recovery
echo "{invalid}" > output/.translation_metadata.json
translate-hugo --site example.com  # Should recover gracefully
```

## Security Considerations

### 1. Hash Collision Attacks

**Risk**: Attacker crafts file with same MD5 as legitimate file.

**Mitigation**:
- Use case is change detection, not security
- For security-critical: Use `hash_algorithm: "sha256"`

### 2. Metadata File Tampering

**Risk**: User edits `.translation_metadata.json` to skip retranslation.

**Mitigation**:
- Detection: Validate hash on load (current implementation)
- Prevention: File permissions (read-only for non-admin)

**Note**: Not a security boundary (user has full file system access).

### 3. Path Traversal

**Risk**: Malicious path in metadata causes writes outside output dir.

**Mitigation**:
- Validate all paths are within expected directories
- Use `Path.resolve()` to normalize paths

**Implementation**:
```python
def validate_path(file_path: Path, allowed_dir: Path) -> bool:
    return file_path.resolve().is_relative_to(allowed_dir.resolve())
```

## References

- [User Guide](../guides/content-hash-tracking.md)
- Implementation Plan (archived)
- Design Document (archived)
- [Atomic Write Utility](../../src/utils/atomic_write.py)
- [Content Hash Utility](../../src/utils/content_hash.py)
- [Metadata Tracker](../../src/utils/metadata_tracker.py)
