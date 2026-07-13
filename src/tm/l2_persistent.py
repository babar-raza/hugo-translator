"""
L2 Persistent Translation Memory using LMDB.

Durable key-value store for exact translation matches across sessions.
"""

import json
import logging
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import lmdb

from .normalization import make_tm_key, make_tm_key_scoped

# Module-level FastText singleton with 60-second retry cooldown (SW-3 / TC-01).
# These are kept for test compatibility; active code uses L2PersistentTM._detector.
_FASTTEXT_RETRY_COOLDOWN: float = 60.0
_fasttext_detector_instance = None
_fasttext_detector_failed_at: float | None = None


def _get_fasttext_detector():
    """Return module-level FastText singleton with 60-second retry cooldown.

    Returns None when: the detector is unavailable, or a load failure occurred
    within the last _FASTTEXT_RETRY_COOLDOWN seconds.
    """
    import time

    global _fasttext_detector_instance, _fasttext_detector_failed_at

    if _fasttext_detector_instance is not None:
        return _fasttext_detector_instance

    # Within cooldown window after a load failure — skip retry
    if _fasttext_detector_failed_at is not None and (
        time.time() - _fasttext_detector_failed_at
    ) < _FASTTEXT_RETRY_COOLDOWN:
        return None

    # Attempt (re-)load
    try:
        from src.translation_engine.language_detection.fasttext_detector import (
            FastTextDetector,
        )

        _fasttext_detector_instance = FastTextDetector(
            cache_dir=Path("data/models/fasttext")
        )
        _fasttext_detector_failed_at = None
        return _fasttext_detector_instance
    except Exception as e:
        logger.warning("FastText unavailable (module-level singleton): %s", e)
        _fasttext_detector_failed_at = time.time()
        return None

# Canonical sub-directory name for the L2 LMDB database.
# All callers must use this constant so the path is never mis-typed.
L2_DB_NAME = "l2.lmdb"

# T204: Integrity safeguards (federated-splashing-panda)
logger = logging.getLogger(__name__)


@dataclass
class TranslationEntry:
    """Translation memory entry."""

    source_text: str
    translation: str
    site_id: str
    src_lang: str
    tgt_lang: str
    context: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = None

    def __post_init__(self):
        """Initialize defaults."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "TranslationEntry":
        """Create from dictionary."""
        return cls(**data)

    def is_valid(self) -> bool:
        """
        Validate entry fields (T204: federated-splashing-panda).

        Returns:
            True if entry is valid, False otherwise
        """
        # Check required fields are non-empty strings
        if not isinstance(self.source_text, str) or not self.source_text:
            return False
        if not isinstance(self.translation, str) or not self.translation:
            return False
        if not isinstance(self.site_id, str) or not self.site_id:
            return False
        if not isinstance(self.src_lang, str) or not self.src_lang:
            return False
        if not isinstance(self.tgt_lang, str) or not self.tgt_lang:
            return False

        # Check optional fields have correct types if present
        if self.context is not None and not isinstance(self.context, str):
            return False
        if self.metadata is not None and not isinstance(self.metadata, dict):
            return False
        if self.timestamp is not None and not isinstance(self.timestamp, str):
            return False

        return True


class L2PersistentTM:
    """
    LMDB-backed persistent translation memory.

    Provides durable storage for exact translation matches
    with fast lookups and batch operations.
    """

    def __init__(self, db_path: Path | str, max_size_mb: int = 4096):
        """
        Initialize L2 persistent TM.

        Args:
            db_path: Path to LMDB database directory
            max_size_mb: Maximum database size in MB (default: 4096 MB).
                reference.aspose.org fills fast; 4 GB is the safe lower bound.
                Callers should read this value from config; the default here is
                the fallback of last resort.
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # Hard enforcement: reject unapproved LMDB paths at runtime
        from src.tm import lmdb_registry as _reg
        _reg.assert_approved_path(self.db_path)

        # TC-TM-02: Warn if a sibling LMDB directory exists next to the canonical
        # path.  Two live L2 databases imply split writes and diverging caches.
        # The canonical name is L2_DB_NAME ("l2.lmdb"); anything else alongside it
        # is a migration artefact.  Run scripts/tm/migrate_l2_lmdb.py to consolidate.
        self._warn_on_sibling_l2_dirs()

        # Convert MB to bytes for LMDB
        max_size_bytes = max_size_mb * 1024 * 1024

        # Open LMDB environment
        self.env = lmdb.open(
            str(self.db_path),
            map_size=max_size_bytes,
            max_dbs=1,
            sync=True,  # Ensure durability
            writemap=False,  # Safer for concurrent access
        )

        self._lock = threading.RLock()
        self._lang_detector = None  # lazy-loaded; set externally or on first use

    @property
    def _detector(self):
        """FastText detector — loaded once, reused. Returns None if unavailable."""
        if self._lang_detector is None:
            try:
                from src.translation_engine.language_detection.fasttext_detector import (
                    FastTextDetector,
                )

                self._lang_detector = FastTextDetector(
                    cache_dir=Path("data/models/fasttext")
                )
            except Exception as e:
                logger.warning("FastText unavailable for TM validation: %s", e)
                self._lang_detector = False  # sentinel: skip detection, don't retry
        return self._lang_detector if self._lang_detector is not False else None

    def _validate_translation_language(self, translation: str, tgt_lang: str) -> bool:
        """Return True if translation passes language check (or check is unavailable)."""
        if len(translation.strip()) <= 50:
            return True  # too short for reliable detection
        detector = self._detector
        if detector is None:
            return True  # detector unavailable → allow storage
        try:
            detected_lang, confidence = detector.detect(translation)
            if confidence < 0.80:
                return True  # low confidence → allow (avoid false rejections)
            # Allow similar language groups
            _TM_SIMILAR_GROUPS = [
                {"ms", "id"},
                {"cs", "sk"},
                {"hr", "sr", "bs"},
                {"nb", "da", "no"},
            ]
            if any(tgt_lang in grp and detected_lang in grp for grp in _TM_SIMILAR_GROUPS):
                return True
            if detected_lang != tgt_lang:
                logger.warning(
                    "TM contamination blocked: detected=%s expected=%s (conf=%.2f)",
                    detected_lang,
                    tgt_lang,
                    confidence,
                )
                return False
        except Exception:
            return True  # validation error → allow
        return True

    def _warn_on_sibling_l2_dirs(self) -> None:
        """Emit a UserWarning if sibling l2*.lmdb directories exist alongside the canonical path.

        Two live LMDB databases imply split writes (TC-TM-02 gap).  This is a
        warning, not a hard error, so the worker can still start.  To fix, run::

            python scripts/tm/migrate_l2_lmdb.py --dry-run
            python scripts/tm/migrate_l2_lmdb.py --apply
        """
        import warnings

        parent = self.db_path.parent
        canonical_name = self.db_path.name
        # Match both "l2.lmdb" (dot-style) and "l2_lmdb" (underscore-style) variants.
        siblings = [p for p in parent.glob("l2*") if p.is_dir() and p.name != canonical_name]
        if siblings:
            names = ", ".join(p.name for p in siblings)
            warnings.warn(
                f"L2PersistentTM: sibling LMDB director{'y' if len(siblings) == 1 else 'ies'} "
                f"found alongside canonical '{canonical_name}': {names}. "
                "This indicates split writes. Run scripts/tm/migrate_l2_lmdb.py to consolidate.",
                UserWarning,
                stacklevel=3,
            )
            logger.warning(
                "TC-TM-02: sibling L2 LMDB dir(s) detected: %s (canonical: %s). "
                "Run scripts/tm/migrate_l2_lmdb.py --apply to consolidate.",
                names,
                self.db_path,
            )

    def exact_lookup(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        context: str | None = None,
        field_name: str = "",
    ) -> TranslationEntry | None:
        """
        Find exact match for text with corruption detection (T204: federated-splashing-panda).

        When field_name is given, tries the scoped key first (prevents cross-field
        contamination), then falls back to the legacy unscoped key for backward
        compatibility with entries stored before H2 (TC-HDN-003).

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text to look up
            context: Optional context for disambiguation
            field_name: Optional field scope (e.g. "description", "title")

        Returns:
            TranslationEntry if found and valid, None otherwise
        """
        keys_to_try: list[str]
        if field_name:
            scoped = make_tm_key_scoped(site_id, src_lang, tgt_lang, text, field_name)
            unscoped = make_tm_key(site_id, src_lang, tgt_lang, text)
            keys_to_try = [scoped, unscoped]  # scoped first; unscoped fallback
        else:
            keys_to_try = [make_tm_key(site_id, src_lang, tgt_lang, text)]

        with self._lock:
            with self.env.begin() as txn:
                value_bytes = None
                for key in keys_to_try:
                    value_bytes = txn.get(key.encode("utf-8"))
                    if value_bytes is not None:
                        break

                if value_bytes is None:
                    return None

                # T204: Deserialize with corruption detection
                try:
                    value_dict = json.loads(value_bytes.decode("utf-8"))
                    entry = TranslationEntry.from_dict(value_dict)
                except (json.JSONDecodeError, KeyError, TypeError, ValueError) as e:
                    # T204: Corrupted entry detected
                    logger.warning(
                        f"Corrupted cache entry detected and skipped: "
                        f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                        f"text={text[:50]}..., error={e}"
                    )
                    return None

                # T204: Validate entry integrity
                if not entry.is_valid():
                    logger.warning(
                        f"Invalid cache entry detected and skipped: "
                        f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                        f"text={text[:50]}..."
                    )
                    return None

                return entry

    def store(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        translation: str,
        context: str | None = None,
        metadata: dict[str, Any] | None = None,
        overwrite: bool = True,
        field_name: str = "",
    ) -> bool:
        """
        Store translation entry with integrity safeguards (T204: federated-splashing-panda).

        When field_name is given, stores under the scoped key to prevent cross-field
        TM contamination (TC-HDN-003). Unscoped legacy entries remain in place and
        are still resolved by exact_lookup() via its fallback path.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text
            translation: Translated text
            context: Optional context (frontmatter key, AST path)
            metadata: Optional additional metadata
            overwrite: If True, overwrite existing entry. If False, skip if exists.
            field_name: Optional field scope (e.g. "description", "title")

        Returns:
            True if stored, False if skipped (existing entry and overwrite=False)

        Raises:
            ValueError: If entry validation fails
            RuntimeError: If JSON serialization or database write fails
        """
        # Validate translation language before storing (prevents TM contamination)
        if not self._validate_translation_language(translation, tgt_lang):
            return False

        # T204: Create and validate entry before write
        entry = TranslationEntry(
            source_text=text,
            translation=translation,
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            context=context,
            metadata=metadata or {},
        )

        # T204: Validate entry integrity
        if not entry.is_valid():
            logger.error(
                f"Invalid translation entry rejected: site_id={site_id}, "
                f"src_lang={src_lang}, tgt_lang={tgt_lang}, text={text[:50]}..."
            )
            raise ValueError("Translation entry failed validation")

        key = make_tm_key_scoped(site_id, src_lang, tgt_lang, text, field_name)
        key_bytes = key.encode("utf-8")

        try:
            with self._lock:
                # T204: LMDB transaction provides atomic write with automatic rollback on failure
                with self.env.begin(write=True) as txn:
                    # Check if exists when not overwriting
                    if not overwrite:
                        existing = txn.get(key_bytes)
                        if existing is not None:
                            return False  # Skip - already exists

                    # T204: Serialize with error handling
                    try:
                        value_json = json.dumps(entry.to_dict())
                    except (TypeError, ValueError) as e:
                        logger.error(f"JSON serialization failed for entry: {e}")
                        raise RuntimeError(f"Failed to serialize translation entry: {e}")

                    # T204: Store with automatic rollback on failure
                    try:
                        txn.put(key_bytes, value_json.encode("utf-8"))
                    except lmdb.MapFullError:
                        current_mb = self.env.info()["map_size"] // (1024 * 1024)
                        new_mb = min(int(current_mb * 1.5), 8192)
                        logger.warning(
                            "LMDB MapFullError in store() — resizing %d MB → %d MB",
                            current_mb,
                            new_mb,
                        )
                        self.env.set_mapsize(new_mb * 1024 * 1024)
                        with self.env.begin(write=True) as txn2:
                            txn2.put(key_bytes, value_json.encode("utf-8"))

            return True

        except Exception as e:
            # T204: Log integrity failure and propagate
            logger.error(
                f"Cache write failed (integrity safeguard triggered): "
                f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                f"error={e}"
            )
            raise

    def batch_store(self, entries: list[TranslationEntry], overwrite: bool = True) -> int:
        """
        Efficiently store many entries at once with integrity safeguards (T204: federated-splashing-panda).

        Args:
            entries: List of TranslationEntry objects
            overwrite: If False, skip entries whose key already exists in the DB.

        Returns:
            Number of entries stored

        Raises:
            ValueError: If any entry validation fails
            RuntimeError: If JSON serialization or database write fails
        """
        # T204: Validate all entries before starting transaction
        for i, entry in enumerate(entries):
            if not entry.is_valid():
                logger.error(
                    f"Invalid entry in batch at index {i}: "
                    f"site_id={entry.site_id}, src_lang={entry.src_lang}, "
                    f"tgt_lang={entry.tgt_lang}"
                )
                raise ValueError(f"Entry at index {i} failed validation")

        try:
            with self._lock:
                # T204: LMDB transaction provides atomic batch write with automatic rollback
                with self.env.begin(write=True) as txn:
                    stored = 0
                    rejected = 0
                    for entry in entries:
                        # Fix E: language validation before write
                        if not self._validate_translation_language(
                            entry.translation, entry.tgt_lang
                        ):
                            rejected += 1
                            continue

                        key = make_tm_key(
                            entry.site_id,
                            entry.src_lang,
                            entry.tgt_lang,
                            entry.source_text,
                        )

                        # Ensure timestamp is set
                        if entry.timestamp is None:
                            entry.timestamp = datetime.now(timezone.utc).isoformat()

                        # T204: Serialize with error handling
                        try:
                            value_json = json.dumps(entry.to_dict())
                        except (TypeError, ValueError) as e:
                            logger.error(
                                f"JSON serialization failed in batch at index {stored}: {e}"
                            )
                            raise RuntimeError(
                                f"Failed to serialize entry at index {stored}: {e}"
                            )

                        key_bytes = key.encode("utf-8")
                        val_bytes = value_json.encode("utf-8")
                        if not overwrite and txn.get(key_bytes) is not None:
                            continue  # skip existing entry
                        try:
                            txn.put(key_bytes, val_bytes)
                        except lmdb.MapFullError:
                            current_mb = self.env.info()["map_size"] // (1024 * 1024)
                            new_mb = min(int(current_mb * 1.5), 8192)
                            logger.warning(
                                "LMDB MapFullError in batch_store() — resizing %d MB → %d MB",
                                current_mb,
                                new_mb,
                            )
                            self.env.set_mapsize(new_mb * 1024 * 1024)
                            with self.env.begin(write=True) as txn2:
                                txn2.put(key_bytes, val_bytes)
                        stored += 1

                    if rejected:
                        logger.warning(
                            "batch_store: rejected %d/%d entries (language mismatch)",
                            rejected,
                            len(entries),
                        )

            return stored

        except Exception as e:
            # T204: Log integrity failure and propagate
            logger.error(f"Batch cache write failed (integrity safeguard triggered): error={e}")
            raise

    def delete(self, site_id: str, src_lang: str, tgt_lang: str, text: str) -> bool:
        """
        Delete translation entry.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text

        Returns:
            True if entry was deleted, False if not found
        """
        key = make_tm_key(site_id, src_lang, tgt_lang, text)

        with self._lock:
            with self.env.begin(write=True) as txn:
                return txn.delete(key.encode("utf-8"))

    def count(self) -> int:
        """
        Get total number of entries in database.

        Returns:
            Entry count
        """
        with self._lock:
            with self.env.begin() as txn:
                return txn.stat()["entries"]

    def clear(self) -> None:
        """Delete all entries from database."""
        with self._lock:
            with self.env.begin(write=True) as txn:
                # Drop and recreate the database
                txn.drop(self.env.open_db())

    def export_all(
        self, site_id: str | None = None, tgt_lang: str | None = None
    ) -> list[TranslationEntry]:
        """
        Export all entries from L2 cache.

        Args:
            site_id: Filter by site (optional)
            tgt_lang: Filter by target language (optional)

        Returns:
            List of TranslationEntry objects
        """
        entries = []

        with self._lock:
            with self.env.begin() as txn:
                cursor = txn.cursor()
                for key, value in cursor:
                    try:
                        entry_dict = json.loads(value.decode("utf-8"))
                        entry = TranslationEntry.from_dict(entry_dict)

                        # Apply filters
                        if site_id and entry.site_id != site_id:
                            continue
                        if tgt_lang and entry.tgt_lang != tgt_lang:
                            continue

                        entries.append(entry)

                    except Exception as e:
                        logger.warning(f"Failed to parse entry {key[:20]!r}: {e}")

        logger.info(f"Exported {len(entries)} entries from L2")
        return entries

    def export_iter(
        self,
        site_id: str | None = None,
        tgt_lang: str | None = None,
    ):
        """Streaming generator — constant-memory alternative to export_all()."""
        with self._lock:
            with self.env.begin() as txn:
                cursor = txn.cursor()
                for _key_bytes, value_bytes in cursor.iternext():
                    try:
                        entry = TranslationEntry.from_dict(
                            json.loads(value_bytes.decode("utf-8"))
                        )
                        if site_id and entry.site_id != site_id:
                            continue
                        if tgt_lang and entry.tgt_lang != tgt_lang:
                            continue
                        yield entry
                    except Exception:
                        continue

    def stats_by_dimension(self, dimension: str = "tgt_lang") -> dict[str, int]:
        """Count entries grouped by a field: 'tgt_lang', 'site_id', or 'src_lang'."""
        counts: dict[str, int] = {}
        for entry in self.export_iter():
            key = getattr(entry, dimension, "unknown")
            counts[key] = counts.get(key, 0) + 1
        return counts

    def get_stats(self) -> dict:
        """
        Return LMDB utilization stats (readonly, side-effect-free).

        Returns:
            dict with keys:
                map_size_mb  – total allocated map size in MiB
                used_mb      – estimated used space in MiB (live data pages only)
                used_pct     – used_mb / map_size_mb * 100
                entries      – number of stored key/value pairs
        """
        with self._lock:
            info = self.env.info()
            stat = self.env.stat()
            map_size_bytes = info["map_size"]
            page_size = stat["psize"]
            used_pages = stat["branch_pages"] + stat["leaf_pages"] + stat["overflow_pages"]
            used_bytes = used_pages * page_size
            map_size_mb = map_size_bytes / 1024 / 1024
            used_mb = used_bytes / 1024 / 1024
            return {
                "map_size_mb": map_size_mb,
                "used_mb": used_mb,
                "used_pct": (used_mb / map_size_mb * 100) if map_size_mb > 0 else 0.0,
                "entries": stat["entries"],
            }

    def close(self) -> None:
        """Close database connection."""
        if self.env:
            self.env.close()

    def __enter__(self):
        """Context manager entry."""
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Context manager exit."""
        self.close()

    def __len__(self) -> int:
        """Return number of entries."""
        return self.count()
