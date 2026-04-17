"""L3 FAISS Index Rebuild functionality.

This module provides functionality to rebuild the L3 semantic index from L2 data,
ensuring consistency between the persistent cache and the semantic search index.

Implementation follows TM-03 from the TM cache integrity plan.
"""

import logging
import shutil
import time
from dataclasses import dataclass
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from .l2_persistent import L2PersistentTM
    from .l3_semantic import L3SemanticTM

logger = logging.getLogger(__name__)


class RebuildError(Exception):
    """Raised when index rebuild fails."""
    pass


@dataclass
class RebuildResult:
    """Results from L3 index rebuild."""
    entries_exported: int
    entries_indexed: int
    duration_seconds: float
    backup_path: Path | None = None

    @property
    def success(self) -> bool:
        """Check if rebuild was successful."""
        return self.entries_exported == self.entries_indexed

    def __str__(self) -> str:
        return (
            f"RebuildResult(exported={self.entries_exported}, "
            f"indexed={self.entries_indexed}, "
            f"duration={self.duration_seconds:.1f}s)"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "entries_exported": self.entries_exported,
            "entries_indexed": self.entries_indexed,
            "duration_seconds": round(self.duration_seconds, 2),
            "backup_path": str(self.backup_path) if self.backup_path else None,
            "success": self.success
        }


class L3IndexRebuilder:
    """
    Rebuild L3 semantic index from L2 persistent cache.

    This ensures the FAISS index is consistent with the LMDB data,
    which can become out of sync if the system crashes during updates.

    Usage:
        from tm.l2_persistent import L2PersistentTM
        from tm.l3_semantic import L3SemanticTM
        from tm.l3_rebuild import L3IndexRebuilder

        l2 = L2PersistentTM(Path("./tm_cache"))
        l3 = L3SemanticTM(Path("./tm_index"))

        rebuilder = L3IndexRebuilder(l2, l3)
        result = rebuilder.rebuild()

        print(f"Rebuilt index: {result}")
    """

    def __init__(
        self,
        l2: 'L2PersistentTM',
        l3: 'L3SemanticTM',
        backup_dir: Path | None = None
    ):
        """
        Initialize index rebuilder.

        Args:
            l2: L2 persistent translation memory instance
            l3: L3 semantic translation memory instance
            backup_dir: Directory for index backups (optional)
        """
        self.l2 = l2
        self.l3 = l3
        self.backup_dir = Path(backup_dir) if backup_dir else None

    def rebuild(
        self,
        site_id: str | None = None,
        tgt_lang: str | None = None,
        backup_existing: bool = True,
        batch_size: int = 1000
    ) -> RebuildResult:
        """
        Rebuild L3 index from L2 data.

        Args:
            site_id: Filter by site ID (optional)
            tgt_lang: Filter by target language (optional)
            backup_existing: Create backup before rebuild (default: True)
            batch_size: Number of entries to process at once (default: 1000)

        Returns:
            RebuildResult with statistics

        Raises:
            RebuildError: If rebuild fails
        """
        start_time = time.perf_counter()
        backup_path = None

        try:
            # Step 1: Backup existing index if requested
            if backup_existing and self._has_existing_index():
                backup_path = self._backup_index()
                logger.info(f"Created index backup: {backup_path}")

            # Step 2: Export all entries from L2
            logger.info("Exporting entries from L2...")
            entries = self.l2.export_all(site_id=site_id, tgt_lang=tgt_lang)
            entries_exported = len(entries)
            logger.info(f"Exported {entries_exported} entries from L2")

            if entries_exported == 0:
                logger.warning("No entries to index - L2 cache is empty or filters match nothing")
                duration = time.perf_counter() - start_time
                return RebuildResult(
                    entries_exported=0,
                    entries_indexed=0,
                    duration_seconds=duration,
                    backup_path=backup_path
                )

            # Step 3: Clear existing L3 index
            logger.info("Clearing existing L3 index...")
            self.l3.clear()

            # Step 4: Batch add entries to L3
            logger.info(f"Indexing {entries_exported} entries (batch_size={batch_size})...")
            entries_indexed = self._batch_add_to_l3(entries, batch_size)

            # Step 5: Save the index
            logger.info("Saving L3 index...")
            self.l3.save_index()

            duration = time.perf_counter() - start_time

            result = RebuildResult(
                entries_exported=entries_exported,
                entries_indexed=entries_indexed,
                duration_seconds=duration,
                backup_path=backup_path
            )

            logger.info(f"Index rebuild complete: {result}")
            return result

        except Exception as e:
            logger.error(f"Index rebuild failed: {e}")
            raise RebuildError(f"Failed to rebuild L3 index: {e}") from e

    def _has_existing_index(self) -> bool:
        """Check if L3 has an existing index file."""
        try:
            # Check if L3 has index_path attribute
            index_path = getattr(self.l3, 'index_path', None)
            if index_path and Path(index_path).exists():
                return True
            return False
        except Exception:
            return False

    def _backup_index(self) -> Path | None:
        """Create backup of existing L3 index."""
        try:
            index_path = getattr(self.l3, 'index_path', None)
            if not index_path or not Path(index_path).exists():
                return None

            index_path = Path(index_path)
            backup_dir = self.backup_dir or index_path.parent

            timestamp = int(time.time())
            backup_path = backup_dir / f"l3_index_backup_{timestamp}"
            backup_path.mkdir(parents=True, exist_ok=True)

            # Copy index file(s)
            if index_path.is_file():
                shutil.copy2(index_path, backup_path / index_path.name)
            elif index_path.is_dir():
                for f in index_path.iterdir():
                    if f.is_file():
                        shutil.copy2(f, backup_path / f.name)

            return backup_path

        except Exception as e:
            logger.warning(f"Failed to backup index: {e}")
            return None

    def _batch_add_to_l3(self, entries: list, batch_size: int) -> int:
        """Add entries to L3 in batches."""
        added = 0
        total = len(entries)

        for i in range(0, total, batch_size):
            batch = entries[i:i + batch_size]

            # Convert TranslationEntry objects to dicts for L3.batch_add
            batch_dicts = []
            for entry in batch:
                batch_dicts.append({
                    "source_text": entry.source_text,
                    "translation": entry.translation,
                    "site_id": entry.site_id,
                    "src_lang": entry.src_lang,
                    "tgt_lang": entry.tgt_lang,
                    "context": entry.context,
                    "metadata": entry.metadata
                })

            # Use L3's batch_add method
            batch_added = self.l3.batch_add(batch_dicts)
            added += batch_added

            progress = (i + len(batch)) / total * 100
            logger.info(f"Indexing progress: {progress:.1f}% ({added}/{total})")

        return added


def rebuild_l3_from_l2(
    l2_path: Path,
    l3_path: Path,
    site_id: str | None = None,
    tgt_lang: str | None = None,
    backup_existing: bool = True
) -> RebuildResult:
    """
    Convenience function to rebuild L3 index from L2 data.

    Args:
        l2_path: Path to L2 LMDB database
        l3_path: Path to L3 FAISS index directory
        site_id: Filter by site ID (optional)
        tgt_lang: Filter by target language (optional)
        backup_existing: Create backup before rebuild (default: True)

    Returns:
        RebuildResult with statistics
    """
    from .l2_persistent import L2PersistentTM
    from .l3_semantic import L3SemanticTM

    l2 = L2PersistentTM(l2_path)
    l3 = L3SemanticTM(l3_path)

    try:
        rebuilder = L3IndexRebuilder(l2, l3)
        return rebuilder.rebuild(
            site_id=site_id,
            tgt_lang=tgt_lang,
            backup_existing=backup_existing
        )
    finally:
        l2.close()
