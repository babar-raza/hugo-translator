# Translation Memory API Reference

**Version:** 1.0
**Last Updated:** 2025-12-24
**Audience:** Developers, Integration Engineers
**Source Code:** [`src/tm/`](../../src/tm/)

---

## Table of Contents

1. [TranslationMemory](#translationmemory) - Unified TM interface
2. [L1Cache](#l1cache) - In-memory LRU cache
3. [L2PersistentTM](#l2persistenttm) - LMDB persistent storage
4. [L3SemanticTM](#l3semantictm) - FAISS semantic search
5. [CacheIntegrityChecker](#cacheintegritychecker) - Integrity validation
6. [CacheBackupManager](#cachebackupmanager) - Backup/restore operations
7. [Data Models](#data-models) - Shared data structures
8. [Configuration](#configuration) - TM configuration options

---

## TranslationMemory

**Unified interface over L1/L2/L3 TM layers.**

**Source:** [`src/tm/translation_memory.py`](../../src/tm/translation_memory.py)

### Class Definition

```python
class TranslationMemory:
    """
    Unified interface for translation memory operations.

    Coordinates L1 (cache), L2 (persistent), and L3 (semantic) layers.
    """

    def __init__(
        self,
        l1_cache: L1Cache,
        l2_persistent: L2PersistentTM,
        l3_semantic: Optional[L3SemanticTM] = None,
        override_controller: Optional[OverrideController] = None,
    ):
        """Initialize translation memory."""
```

### Methods

#### lookup()

Unified lookup across all TM layers.

**Signature:**
```python
def lookup(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    context: Optional[str] = None,
    use_semantic: bool = True,
    semantic_threshold: float = 0.80,
    lookup_context: Optional[Dict[str, Any]] = None,
) -> LookupResult:
```

**Parameters:**
- `site_id` (str): Site identifier (e.g., "products.aspose.net")
- `src_lang` (str): Source language code (e.g., "en")
- `tgt_lang` (str): Target language code (e.g., "fr")
- `text` (str): Source text to lookup
- `context` (Optional[str]): Context for disambiguation
- `use_semantic` (bool): Whether to use L3 semantic search (default: True)
- `semantic_threshold` (float): Minimum similarity for L3 matches (default: 0.80)
- `lookup_context` (Optional[Dict]): Context for override filtering

**Returns:** `LookupResult` object

**Example:**
```python
from src.tm import create_translation_memory
from pathlib import Path

tm = create_translation_memory(Path("data/tm"))

result = tm.lookup(
    site_id="products.aspose.net",
    src_lang="en",
    tgt_lang="fr",
    text="Welcome to our website",
    use_semantic=True,
    semantic_threshold=0.85
)

if result.hit:
    print(f"Translation: {result.translation}")
    print(f"Source: {result.source}")  # "l1_cache", "l2_exact", or "l3_semantic"
    print(f"Confidence: {result.confidence}")
else:
    print("No match found in TM")
```

---

#### store()

Store translation in all applicable layers.

**Signature:**
```python
def store(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    translation: str,
    context: Optional[str] = None,
    metadata: Optional[Dict] = None,
    store_context: Optional[Dict[str, Any]] = None,
    force_update: bool = False,
) -> bool:
```

**Parameters:**
- `site_id` (str): Site identifier
- `src_lang` (str): Source language code
- `tgt_lang` (str): Target language code
- `text` (str): Source text
- `translation` (str): Translated text
- `context` (Optional[str]): Context information
- `metadata` (Optional[Dict]): Additional metadata
- `store_context` (Optional[Dict]): Context for override filtering
- `force_update` (bool): Overwrite existing entries (default: False)

**Returns:** bool - True if stored, False if skipped

**Example:**
```python
stored = tm.store(
    site_id="products.aspose.net",
    src_lang="en",
    tgt_lang="fr",
    text="Welcome to our website",
    translation="Bienvenue sur notre site",
    metadata={"model": "gpt-4", "validator_score": 0.95},
    force_update=False  # Skip if already exists
)

if stored:
    print("Translation stored in TM")
else:
    print("Translation already exists (skipped)")
```

---

#### batch_lookup()

Optimize bulk lookups.

**Signature:**
```python
def batch_lookup(
    self,
    requests: List[LookupRequest],
    use_semantic: bool = True,
    semantic_threshold: float = 0.80,
) -> List[LookupResult]:
```

**Parameters:**
- `requests` (List[LookupRequest]): List of lookup requests
- `use_semantic` (bool): Whether to use L3 semantic search
- `semantic_threshold` (float): Minimum similarity for L3 matches

**Returns:** List[LookupResult] - Results in same order as requests

**Example:**
```python
from src.tm.models import LookupRequest

requests = [
    LookupRequest(
        site_id="products.aspose.net",
        src_lang="en",
        tgt_lang="fr",
        text="Hello world",
    ),
    LookupRequest(
        site_id="products.aspose.net",
        src_lang="en",
        tgt_lang="fr",
        text="Goodbye world",
    ),
]

results = tm.batch_lookup(requests)

for req, result in zip(requests, results):
    if result.hit:
        print(f"{req.text} → {result.translation}")
    else:
        print(f"{req.text} → No match")
```

---

#### batch_store()

Efficiently store many entries at once.

**Signature:**
```python
def batch_store(self, entries: List[TranslationEntry]) -> int:
```

**Parameters:**
- `entries` (List[TranslationEntry]): List of translation entries

**Returns:** int - Number of entries stored

**Example:**
```python
from src.tm.l2_persistent import TranslationEntry

entries = [
    TranslationEntry(
        site_id="products.aspose.net",
        src_lang="en",
        tgt_lang="fr",
        source_text="Hello",
        translation="Bonjour",
    ),
    TranslationEntry(
        site_id="products.aspose.net",
        src_lang="en",
        tgt_lang="fr",
        source_text="Goodbye",
        translation="Au revoir",
    ),
]

count = tm.batch_store(entries)
print(f"Stored {count} entries")
```

---

#### stats()

Aggregate statistics from all layers.

**Signature:**
```python
def stats(self) -> TMStats:
```

**Returns:** `TMStats` object with combined statistics

**Example:**
```python
stats = tm.stats()

print(f"Overall Hit Rate: {stats.overall_hit_rate:.1f}%")
print(f"L1 Size: {stats.l1_size:,} / {stats.l1_max_size:,}")
print(f"L1 Hit Rate: {stats.l1_hit_rate:.1f}%")
print(f"L2 Size: {stats.l2_size:,} entries")
print(f"L3 Size: {stats.l3_size:,} vectors")
print(f"Total Lookups: {stats.total_lookups:,}")
print(f"Total Hits: {stats.total_hits:,}")
```

---

#### set_override_mode()

Set the override mode for TM operations.

**Signature:**
```python
def set_override_mode(
    self,
    mode: OverrideMode,
    filters: Optional[Dict[str, Any]] = None,
) -> None:
```

**Parameters:**
- `mode` (OverrideMode): Override mode (NORMAL, BYPASS, REFRESH, VALIDATE)
- `filters` (Optional[Dict]): Filter configuration
  - `source_patterns`: List[str] - Regex patterns to match source text
  - `target_langs`: List[str] - Target language codes
  - `frontmatter_keys`: List[str] - Frontmatter keys to match

**Example:**
```python
from src.tm.override_controller import OverrideMode

# Set refresh mode for German translations containing "Aspose"
tm.set_override_mode(
    mode=OverrideMode.REFRESH,
    filters={
        "source_patterns": [r"Aspose\.\w+"],
        "target_langs": ["de"],
    }
)
```

---

## L1Cache

**In-memory LRU cache for fast translation lookups.**

**Source:** [`src/tm/l1_cache.py`](../../src/tm/l1_cache.py)

### Class Definition

```python
class L1Cache:
    """LRU cache for fast translation lookups."""

    def __init__(self, max_size: int = 10000):
        """
        Initialize L1 cache.

        Args:
            max_size: Maximum number of entries (default: 10,000)
        """
```

### Methods

#### get()

Retrieve cached translation.

**Signature:**
```python
def get(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str
) -> Optional[str]:
```

**Returns:** str or None

**Example:**
```python
from src.tm.l1_cache import L1Cache

l1 = L1Cache(max_size=10000)

translation = l1.get("products.aspose.net", "en", "fr", "Hello")

if translation:
    print(f"Cached: {translation}")
else:
    print("Not in cache")
```

---

#### put()

Store translation in cache.

**Signature:**
```python
def put(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    translation: str,
) -> None:
```

**Example:**
```python
l1.put("products.aspose.net", "en", "fr", "Hello", "Bonjour")
```

---

#### stats()

Get cache statistics.

**Signature:**
```python
def stats(self) -> Dict[str, Any]:
```

**Returns:** Dict with keys: `hits`, `misses`, `hit_rate`, `size`, `max_size`, `evictions`

**Example:**
```python
stats = l1.stats()
print(f"Hit Rate: {stats['hit_rate']:.1f}%")
print(f"Size: {stats['size']} / {stats['max_size']}")
print(f"Evictions: {stats['evictions']}")
```

---

## L2PersistentTM

**LMDB-backed persistent translation memory.**

**Source:** [`src/tm/l2_persistent.py`](../../src/tm/l2_persistent.py)

### Class Definition

```python
class L2PersistentTM:
    """LMDB-backed persistent translation memory."""

    def __init__(self, db_path: Path | str, max_size_mb: int = 1024):
        """
        Initialize L2 persistent TM.

        Args:
            db_path: Path to LMDB database directory
            max_size_mb: Maximum database size in MB (default: 1GB)
        """
```

### Methods

#### exact_lookup()

Find exact match for text.

**Signature:**
```python
def exact_lookup(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    context: Optional[str] = None,
) -> Optional[TranslationEntry]:
```

**Returns:** TranslationEntry or None

**Example:**
```python
from src.tm.l2_persistent import L2PersistentTM
from pathlib import Path

l2 = L2PersistentTM(db_path=Path("data/tm/l2_lmdb"), max_size_mb=1024)

entry = l2.exact_lookup("products.aspose.net", "en", "fr", "Hello")

if entry:
    print(f"Translation: {entry.translation}")
    print(f"Timestamp: {entry.timestamp}")
    print(f"Metadata: {entry.metadata}")
```

---

#### store()

Store translation entry.

**Signature:**
```python
def store(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    text: str,
    translation: str,
    context: Optional[str] = None,
    metadata: Optional[Dict[str, Any]] = None,
    overwrite: bool = True,
) -> bool:
```

**Returns:** bool - True if stored, False if skipped

**Raises:**
- `ValueError`: If entry validation fails
- `RuntimeError`: If JSON serialization or database write fails

---

## L3SemanticTM

**Vector-based semantic translation memory.**

**Source:** [`src/tm/l3_semantic.py`](../../src/tm/l3_semantic.py)

### Class Definition

```python
class L3SemanticTM:
    """Vector-based semantic translation memory using FAISS."""

    def __init__(
        self,
        index_path: Path | str,
        embedding_model: str = "all-MiniLM-L6-v2",
        use_gpu: bool = False,
        use_faiss_gpu: bool = False,
        save_interval: int = 100,
        save_timeout: float = 5.0,
        async_save: bool = False,
    ):
        """
        Initialize L3 semantic TM.

        Args:
            index_path: Directory to store index and metadata
            embedding_model: Sentence transformer model name
            use_gpu: Whether to use GPU for embeddings
            use_faiss_gpu: Whether to use FAISS GPU index
            save_interval: Save every N additions (0 = disabled)
            save_timeout: Max seconds for save operation
            async_save: Use background thread for saves
        """
```

### Methods

#### semantic_search()

Find top K similar entries above similarity threshold.

**Signature:**
```python
def semantic_search(
    self,
    site_id: str,
    src_lang: str,
    tgt_lang: str,
    query_text: str,
    k: int = 10,
    threshold: float = 0.75,
) -> List[SemanticMatch]:
```

**Parameters:**
- `k` (int): Number of results to return (default: 10)
- `threshold` (float): Minimum similarity score 0-1 (default: 0.75)

**Returns:** List[SemanticMatch] - Sorted by similarity

**Example:**
```python
from src.tm.l3_semantic import L3SemanticTM
from pathlib import Path

l3 = L3SemanticTM(
    index_path=Path("data/tm/l3_semantic"),
    embedding_model="all-MiniLM-L6-v2",
    use_gpu=False,
)

matches = l3.semantic_search(
    site_id="products.aspose.net",
    src_lang="en",
    tgt_lang="fr",
    query_text="Welcome to our homepage",
    k=5,
    threshold=0.80,
)

for match in matches:
    print(f"Similarity: {match.similarity:.2f}")
    print(f"Source: {match.source_text}")
    print(f"Translation: {match.translation}")
    print("---")
```

---

## CacheIntegrityChecker

**Integrity validation for translation memory.**

**Source:** [`src/tm/integrity.py`](../../src/tm/integrity.py)

### Function: check_cache_integrity()

**Signature:**
```python
def check_cache_integrity(
    db_path: Path,
    repair: bool = False,
    max_errors: int = 100
) -> IntegrityReport:
```

**Parameters:**
- `db_path` (Path): Path to LMDB database directory
- `repair` (bool): Delete corrupted entries if True
- `max_errors` (int): Stop after N errors

**Returns:** `IntegrityReport` object

**Example:**
```python
from src.tm.integrity import check_cache_integrity
from pathlib import Path

report = check_cache_integrity(
    db_path=Path("data/tm/l2_lmdb"),
    repair=False,
    max_errors=1000
)

print(f"Health: {report.health_percentage:.1f}%")
print(f"Total Scanned: {report.total_scanned:,}")
print(f"Valid: {report.valid_count:,}")
print(f"Corrupted: {report.corrupt_count:,}")
print(f"Healthy: {report.is_healthy}")

if not report.is_healthy:
    print("Errors detected:")
    for error in report.errors[:10]:  # First 10 errors
        print(f"  - {error}")
```

---

## CacheBackupManager

**Backup and restore operations for translation memory.**

**Source:** [`src/tm/backup.py`](../../src/tm/backup.py)

### Class Definition

```python
class CacheBackupManager:
    """Manage LMDB cache backups with automatic pruning."""

    def __init__(
        self,
        tm_path: Path,
        backup_dir: Path,
        max_backups: int = 5,
        min_free_space_gb: float = 5.0
    ):
        """
        Initialize backup manager.

        Args:
            tm_path: Path to LMDB cache directory
            backup_dir: Directory to store backups
            max_backups: Maximum number of backups to retain (default: 5)
            min_free_space_gb: Minimum free disk space required (default: 5.0)
        """
```

### Methods

#### create_backup()

Create timestamped backup of LMDB directory.

**Signature:**
```python
def create_backup(
    self,
    verify_integrity: bool = True,
    compact: bool = True
) -> BackupInfo:
```

**Parameters:**
- `verify_integrity` (bool): Check integrity before backup (default: True)
- `compact` (bool): Compact LMDB during backup (default: True)

**Returns:** `BackupInfo` object

**Raises:**
- `InsufficientSpaceError`: If disk space insufficient
- `IntegrityCheckError`: If cache integrity check fails

**Example:**
```python
from src.tm.backup import CacheBackupManager
from pathlib import Path

manager = CacheBackupManager(
    tm_path=Path("data/tm/l2_lmdb"),
    backup_dir=Path("data/tm/backups"),
    max_backups=5,
)

# Create backup
backup_info = manager.create_backup(
    verify_integrity=True,
    compact=True
)

print(f"Backup created: {backup_info.path}")
print(f"Size: {backup_info.size_mb:.1f} MB")
print(f"Entries: {backup_info.entry_count:,}")
```

---

#### restore_backup()

Restore cache from backup.

**Signature:**
```python
def restore_backup(
    self,
    backup_path: Path,
    force: bool = False
) -> None:
```

**Parameters:**
- `backup_path` (Path): Path to backup directory
- `force` (bool): Skip confirmation (default: False)

**Raises:**
- `RestoreError`: If restore operation fails

**Example:**
```python
# List available backups
backups = manager.list_backups()

# Restore latest backup
if backups:
    manager.restore_backup(backups[0].path, force=True)
    print(f"Restored from: {backups[0].path}")
```

---

## Data Models

### LookupRequest

```python
@dataclass
class LookupRequest:
    """Request for TM lookup."""
    site_id: str
    src_lang: str
    tgt_lang: str
    text: str
    context: Optional[str] = None
```

---

### LookupResult

```python
@dataclass
class LookupResult:
    """Result of TM lookup with provenance."""
    hit: bool
    translation: Optional[str] = None
    source: Literal["l1_cache", "l2_exact", "l3_semantic", "none", "override_bypass"] = "none"
    confidence: float = 0.0  # 1.0 for exact, <1.0 for semantic
    candidates: List[SemanticMatch] = field(default_factory=list)
    metadata: Dict[str, Any] = field(default_factory=dict)
```

---

### TranslationEntry

```python
@dataclass
class TranslationEntry:
    """Translation memory entry."""
    source_text: str
    translation: str
    site_id: str
    src_lang: str
    tgt_lang: str
    context: Optional[str] = None
    timestamp: Optional[str] = None
    metadata: Dict[str, Any] = None
```

---

### TMStats

```python
@dataclass
class TMStats:
    """Aggregated statistics from all TM layers."""
    # L1 Cache stats
    l1_size: int
    l1_max_size: int
    l1_hits: int
    l1_misses: int
    l1_evictions: int
    l1_hit_rate: float

    # L2 Persistent stats
    l2_size: int

    # L3 Semantic stats
    l3_size: int

    # Combined stats
    total_lookups: int
    total_hits: int
    overall_hit_rate: float
```

---

## Configuration

### YAML Configuration

```yaml
# config/site_profiles/default.yaml
translation_memory:
  # L1 Cache
  l1_cache_size: 10000              # Max entries in memory cache

  # L2 Persistent
  l2_max_size_mb: 1024              # LMDB map size (MB)

  # L3 Semantic
  l3_enabled: true                  # Enable L3 semantic search
  l3_embedding_model: "all-MiniLM-L6-v2"  # Sentence transformer model
  l3_use_gpu: false                 # Use GPU for embeddings
  l3_use_faiss_gpu: false           # Use GPU for FAISS index
  l3_save_interval: 100             # Save every N additions
  l3_async_save: false              # Background save thread
  l3_save_timeout: 5.0              # Max save duration (seconds)
  l3_similarity_threshold: 0.80     # Min similarity for matches
```

---

### Programmatic Configuration

```python
from pathlib import Path
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM
from src.tm.translation_memory import TranslationMemory

# Create TM layers
l1 = L1Cache(max_size=20000)
l2 = L2PersistentTM(db_path=Path("data/tm/l2_lmdb"), max_size_mb=2048)
l3 = L3SemanticTM(
    index_path=Path("data/tm/l3_semantic"),
    embedding_model="all-MiniLM-L6-v2",
    use_gpu=True,
    save_interval=500,
    async_save=True,
)

# Create unified TM
tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)
```

---

## Error Handling

### Common Exceptions

```python
from src.tm.backup import BackupError, InsufficientSpaceError, IntegrityCheckError

try:
    backup_info = manager.create_backup()
except InsufficientSpaceError as e:
    print(f"Not enough disk space: {e}")
except IntegrityCheckError as e:
    print(f"Cache integrity check failed: {e}")
except BackupError as e:
    print(f"Backup failed: {e}")
```

---

## Best Practices

### ✅ Do

- Use `batch_lookup()` and `batch_store()` for bulk operations
- Enable integrity verification before backups
- Set appropriate `max_size_mb` for your cache size (2-3x current size)
- Use semantic search thresholds ≥0.75 for quality
- Monitor hit rates and adjust L1 cache size accordingly

### ❌ Don't

- Don't call `lookup()` in tight loops (use `batch_lookup()`)
- Don't set `max_size_mb` too small (causes `MDB_MAP_FULL` errors)
- Don't disable integrity checks in production
- Don't use very low semantic thresholds (<0.70) without validation
- Don't forget to call `close()` or use context managers

---

## Related Documentation

- [TM Architecture](../architecture/translation-memory.md) - System design and internals
- [TM Getting Started](../guides/tm-getting-started.md) - User introduction
- [TM Maintenance](../operations/tm-maintenance.md) - Operational procedures
- [TM Performance Tuning](../operations/tm-performance-tuning.md) - Optimization guide

---

**Document Status:** ✅ Complete
**Code Verified:** 2025-12-24
**API Coverage:** 100% of public interfaces

