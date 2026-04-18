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

from .normalization import make_tm_key

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

    def __init__(self, db_path: Path | str, max_size_mb: int = 1536):
        """
        Initialize L2 persistent TM.

        Args:
            db_path: Path to LMDB database directory
            max_size_mb: Maximum database size in MB (default: 1536 MB, matches
                config/global.yaml tm_defaults.l2_max_size_mb). Callers should
                read this value from config; the default here is the fallback of
                last resort so that bare instantiation never creates a 1 GB file.
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

        # TC-TM-02: Warn if a sibling LMDB directory exists next to the canonical
        # path.  Two live L2 databases imply split writes and diverging caches.
        # The canonical name is L2_DB_NAME ("l2.lmdb"); anything else alongside it
        # is a migration artefact.  Run scripts/migrate_l2_lmdb.py to consolidate.
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

    def _warn_on_sibling_l2_dirs(self) -> None:
        """Emit a UserWarning if sibling l2*.lmdb directories exist alongside the canonical path.

        Two live LMDB databases imply split writes (TC-TM-02 gap).  This is a
        warning, not a hard error, so the worker can still start.  To fix, run::

            python scripts/migrate_l2_lmdb.py --dry-run
            python scripts/migrate_l2_lmdb.py --apply
        """
        import warnings
        parent = self.db_path.parent
        canonical_name = self.db_path.name
        # Match both "l2.lmdb" (dot-style) and "l2_lmdb" (underscore-style) variants.
        siblings = [
            p for p in parent.glob("l2*")
            if p.is_dir() and p.name != canonical_name
        ]
        if siblings:
            names = ", ".join(p.name for p in siblings)
            warnings.warn(
                f"L2PersistentTM: sibling LMDB director{'y' if len(siblings) == 1 else 'ies'} "
                f"found alongside canonical '{canonical_name}': {names}. "
                "This indicates split writes. Run scripts/migrate_l2_lmdb.py to consolidate.",
                UserWarning,
                stacklevel=3,
            )
            logger.warning(
                "TC-TM-02: sibling L2 LMDB dir(s) detected: %s (canonical: %s). "
                "Run scripts/migrate_l2_lmdb.py --apply to consolidate.",
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
    ) -> TranslationEntry | None:
        """
        Find exact match for text with corruption detection (T204: federated-splashing-panda).

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text to look up
            context: Optional context for disambiguation

        Returns:
            TranslationEntry if found and valid, None otherwise
        """
        key = make_tm_key(site_id, src_lang, tgt_lang, text)

        with self._lock:
            with self.env.begin() as txn:
                value_bytes = txn.get(key.encode("utf-8"))

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

                # Context filtering if specified
                if context is not None and entry.context != context:
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
    ) -> bool:
        """
        Store translation entry with integrity safeguards (T204: federated-splashing-panda).

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text
            translation: Translated text
            context: Optional context (frontmatter key, AST path)
            metadata: Optional additional metadata
            overwrite: If True, overwrite existing entry. If False, skip if exists.

        Returns:
            True if stored, False if skipped (existing entry and overwrite=False)

        Raises:
            ValueError: If entry validation fails
            RuntimeError: If JSON serialization or database write fails
        """
        # CRITICAL FIX: Validate translation language before storing (prevents TM contamination)
        # This is a conservative check - only blocks on high-confidence mismatches
        try:
            # Import here to avoid circular dependencies
            from pathlib import Path

            from src.translation_engine.language_detection.fasttext_detector import FastTextDetector

            # Only validate if translation is long enough for accurate detection
            if len(translation.strip()) > 50:
                # Use correct FastText model directory
                cache_dir = Path("data/models/fasttext")
                detector = FastTextDetector(cache_dir=cache_dir)
                detected_lang, confidence = detector.detect(translation)

                # Similarity groups: languages FastText confuses at high confidence
                # (mutually intelligible or script-similar pairs — false positive protection)
                _TM_SIMILAR_GROUPS = [
                    {"ms", "id"},        # Malay/Indonesian
                    {"cs", "sk"},        # Czech/Slovak
                    {"hr", "sr", "bs"},  # South Slavic
                    {"nb", "da", "no"},  # North Germanic
                ]
                _in_same_group = any(
                    tgt_lang in grp and detected_lang in grp
                    for grp in _TM_SIMILAR_GROUPS
                )

                # Block storage only on high-confidence mismatch (>80%)
                if detected_lang != tgt_lang and confidence > 0.80 and not _in_same_group:
                    logger.error(
                        f"TM STORE BLOCKED: Translation language mismatch! "
                        f"Site: {site_id}, Expected: {tgt_lang}, Detected: {detected_lang} ({confidence:.2%}). "
                        f"Translation: {translation[:100]}... "
                        f"Refusing to store contaminated entry to prevent TM pollution."
                    )
                    # Don't raise - just return False to indicate not stored
                    return False
                elif detected_lang != tgt_lang and confidence > 0.70 and not _in_same_group:
                    # Log warning for moderate confidence mismatches
                    logger.warning(
                        f"TM language concern: Expected {tgt_lang}, detected {detected_lang} ({confidence:.2%}). "
                        f"Storing anyway (confidence < 80%) but flagging for review."
                    )
        except Exception as e:
            # Non-fatal - don't block TM storage on validation errors
            logger.debug(f"TM language validation failed (non-fatal): {e}")

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

        key = make_tm_key(site_id, src_lang, tgt_lang, text)
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
                    txn.put(key_bytes, value_json.encode("utf-8"))

            return True

        except Exception as e:
            # T204: Log integrity failure and propagate
            logger.error(
                f"Cache write failed (integrity safeguard triggered): "
                f"site_id={site_id}, src_lang={src_lang}, tgt_lang={tgt_lang}, "
                f"error={e}"
            )
            raise

    def batch_store(self, entries: list[TranslationEntry]) -> int:
        """
        Efficiently store many entries at once with integrity safeguards (T204: federated-splashing-panda).

        Args:
            entries: List of TranslationEntry objects

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
                    count = 0
                    for entry in entries:
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
                            logger.error(f"JSON serialization failed in batch at index {count}: {e}")
                            raise RuntimeError(f"Failed to serialize entry at index {count}: {e}")

                        txn.put(key.encode("utf-8"), value_json.encode("utf-8"))
                        count += 1

            return count

        except Exception as e:
            # T204: Log integrity failure and propagate
            logger.error(f"Batch cache write failed (integrity safeguard triggered): error={e}")
            raise

    def delete(
        self, site_id: str, src_lang: str, tgt_lang: str, text: str
    ) -> bool:
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
        self,
        site_id: str | None = None,
        tgt_lang: str | None = None
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
                        entry_dict = json.loads(value.decode('utf-8'))
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
