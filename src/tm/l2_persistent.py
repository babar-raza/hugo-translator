"""
L2 Persistent Translation Memory using LMDB.

Durable key-value store for exact translation matches across sessions.
"""
import json
import threading
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

import lmdb

from .normalization import make_tm_key, normalize_text


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

    def __post_init__(self):
        """Initialize defaults."""
        if self.timestamp is None:
            self.timestamp = datetime.now(timezone.utc).isoformat()
        if self.metadata is None:
            self.metadata = {}

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TranslationEntry":
        """Create from dictionary."""
        return cls(**data)


class L2PersistentTM:
    """
    LMDB-backed persistent translation memory.

    Provides durable storage for exact translation matches
    with fast lookups and batch operations.
    """

    def __init__(self, db_path: Path | str, max_size_mb: int = 1024):
        """
        Initialize L2 persistent TM.

        Args:
            db_path: Path to LMDB database directory
            max_size_mb: Maximum database size in MB (default: 1GB)
        """
        self.db_path = Path(db_path)
        self.db_path.mkdir(parents=True, exist_ok=True)

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

    def exact_lookup(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        context: Optional[str] = None,
    ) -> Optional[TranslationEntry]:
        """
        Find exact match for text.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text to look up
            context: Optional context for disambiguation

        Returns:
            TranslationEntry if found, None otherwise
        """
        key = make_tm_key(site_id, src_lang, tgt_lang, text)

        with self._lock:
            with self.env.begin() as txn:
                value_bytes = txn.get(key.encode("utf-8"))

                if value_bytes is None:
                    return None

                # Deserialize entry
                value_dict = json.loads(value_bytes.decode("utf-8"))
                entry = TranslationEntry.from_dict(value_dict)

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
        context: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None,
        overwrite: bool = True,
    ) -> bool:
        """
        Store translation entry.

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
        """
        entry = TranslationEntry(
            source_text=text,
            translation=translation,
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            context=context,
            metadata=metadata or {},
        )

        key = make_tm_key(site_id, src_lang, tgt_lang, text)
        key_bytes = key.encode("utf-8")

        with self._lock:
            with self.env.begin(write=True) as txn:
                # Check if exists when not overwriting
                if not overwrite:
                    existing = txn.get(key_bytes)
                    if existing is not None:
                        return False  # Skip - already exists

                value_json = json.dumps(entry.to_dict())
                txn.put(key_bytes, value_json.encode("utf-8"))

        return True

    def batch_store(self, entries: List[TranslationEntry]) -> int:
        """
        Efficiently store many entries at once.

        Args:
            entries: List of TranslationEntry objects

        Returns:
            Number of entries stored
        """
        with self._lock:
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

                    value_json = json.dumps(entry.to_dict())
                    txn.put(key.encode("utf-8"), value_json.encode("utf-8"))
                    count += 1

        return count

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
