"""Persistent metadata tracking for content hashes."""

import json
import logging
import time
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import TYPE_CHECKING, Optional

from src.utils.atomic_write import atomic_write
from src.utils.content_hash import HashAlgorithm, compute_file_hash

if TYPE_CHECKING:
    from redis import Redis

    from ..observability.metrics import MetricsCollector

logger = logging.getLogger(__name__)


@dataclass
class SourceFileMetadata:
    """Metadata for source file."""
    path: str
    hash: str
    last_modified: str  # ISO 8601
    size_bytes: int
    hash_computed_at: str  # ISO 8601


@dataclass
class OutputFileMetadata:
    """Metadata for translated output file."""
    path: str
    hash: str
    translated_at: str  # ISO 8601
    source_hash_at_translation: str  # Source hash when this translation was created
    size_bytes: int
    status: str  # "success" | "failed"


@dataclass
class FileMetadata:
    """Complete metadata for source file + all translations."""
    source: SourceFileMetadata
    outputs: dict[str, OutputFileMetadata]  # {lang_code: metadata}


class MetadataTracker:
    """
    Manages persistent metadata for content hash tracking.

    Pattern: Follows ProgressTracker architecture
    Storage: Atomic writes with corruption recovery
    Thread-safety: Multi-worker safe with Redis locking (when redis_client provided)
    """

    def __init__(
        self,
        metadata_file: Path,
        hash_algorithm: HashAlgorithm = "md5",
        site_id: str | None = None,
        redis_client: Optional["Redis"] = None,
        lock_timeout: int = 30,
        metrics: Optional["MetricsCollector"] = None,
        auto_cleanup_config: dict | None = None,
    ):
        self.metadata_file = metadata_file
        self.hash_algorithm = hash_algorithm
        self.site_id = site_id
        self.redis_client = redis_client
        self.lock_timeout = lock_timeout
        self.metrics = metrics  # CHH-04: Metrics collector
        self.auto_cleanup_config = auto_cleanup_config or {}  # CHH-05: Automatic cleanup config
        self._data: dict[str, FileMetadata] = {}
        self._loaded = False

    def load(self) -> None:
        """Load metadata from disk (with corruption recovery)."""
        if not self.metadata_file.exists():
            self._data = {}
            self._loaded = True
            return

        try:
            with open(self.metadata_file, encoding="utf-8") as f:
                raw = json.load(f)

            # Validate schema version
            if raw.get("schema_version") != "1.0":
                raise ValueError(f"Unsupported schema: {raw.get('schema_version')}")

            # Load file entries
            self._data = {}
            for file_path, file_data in raw.get("files", {}).items():
                source = SourceFileMetadata(**file_data["source"])
                outputs = {
                    lang: OutputFileMetadata(**output_data)
                    for lang, output_data in file_data.get("outputs", {}).items()
                }
                self._data[file_path] = FileMetadata(source=source, outputs=outputs)

            self._loaded = True

        except (json.JSONDecodeError, KeyError, ValueError, TypeError) as e:
            # Corruption detected: Start with empty metadata
            logger.warning(f"Metadata corrupted, rebuilding: {e}")
            self._data = {}
            self._loaded = True

        # CHH-05: Automatic cleanup on load
        if self.auto_cleanup_config.get("enabled", False) and self.auto_cleanup_config.get("cleanup_on_load", False):
            max_age = self.auto_cleanup_config.get("max_age_days", 30)
            logger.debug(f"Running automatic cleanup on load (max_age={max_age} days)")
            self.cleanup_old_entries(max_age_days=max_age)

    def save(self) -> None:
        """
        Save metadata to disk (atomic write).

        Uses Redis distributed lock for multi-worker coordination.
        Falls back to file-only atomic write if Redis unavailable.
        """
        save_start = time.time()

        if self.redis_client:
            # Multi-worker mode: Use Redis lock for coordination
            lock_key = f"metadata_lock:{self.metadata_file}"
            try:
                lock_start = time.time()
                with self.redis_client.lock(
                    lock_key,
                    timeout=self.lock_timeout,
                    blocking_timeout=self.lock_timeout,
                ):
                    # CHH-04: Record lock acquisition time
                    if self.metrics:
                        lock_duration = time.time() - lock_start
                        self.metrics.observe("metadata_lock_acquire_duration_seconds", lock_duration)

                    logger.debug(f"Acquired Redis lock for metadata save: {lock_key}")
                    self._save_to_disk()
                    logger.debug(f"Released Redis lock: {lock_key}")
            except Exception as e:
                logger.warning(
                    f"Redis lock failed (falling back to direct write): {e}. "
                    "This may cause race conditions in multi-worker environments."
                )
                # CHH-04: Count lock timeouts
                if self.metrics:
                    self.metrics.increment("metadata_lock_timeouts")
                self._save_to_disk()
        else:
            # Single-worker mode: Direct save without locking
            self._save_to_disk()

        # CHH-04: Record total save duration
        if self.metrics:
            save_duration = time.time() - save_start
            self.metrics.observe("metadata_save_duration_seconds", save_duration)

            # Update metadata file size gauge
            if self.metadata_file.exists():
                file_size = self.metadata_file.stat().st_size
                self.metrics.set_gauge("metadata_file_size_bytes", file_size)

            # Update tracked files count
            self.metrics.set_gauge("metadata_tracked_files", len(self._data))

        # CHH-05: Automatic cleanup on save
        if self.auto_cleanup_config.get("enabled", False) and self.auto_cleanup_config.get("cleanup_on_save", False):
            max_age = self.auto_cleanup_config.get("max_age_days", 30)
            logger.debug(f"Running automatic cleanup on save (max_age={max_age} days)")
            self.cleanup_old_entries(max_age_days=max_age)

    def _save_to_disk(self) -> None:
        """Internal method to save metadata to disk (atomic write)."""
        # Build JSON structure
        files_dict = {}
        for file_path, metadata in self._data.items():
            files_dict[file_path] = {
                "source": asdict(metadata.source),
                "outputs": {
                    lang: asdict(output_meta)
                    for lang, output_meta in metadata.outputs.items()
                }
            }

        output = {
            "schema_version": "1.0",
            "site_id": self.site_id,
            "tracking_config": {
                "hash_algorithm": self.hash_algorithm,
                "track_output_integrity": True,
            },
            "files": files_dict,
            "statistics": {
                "total_files_tracked": len(self._data),
                "total_translations": sum(
                    len(meta.outputs) for meta in self._data.values()
                ),
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        }

        # Atomic write with fsync
        content = json.dumps(output, indent=2, ensure_ascii=False)
        atomic_write(self.metadata_file, content, fsync=True)

    def get_source_hash(self, source_path: Path) -> str | None:
        """Get stored hash for source file."""
        if not self._loaded:
            self.load()

        metadata = self._data.get(str(source_path))
        return metadata.source.hash if metadata else None

    def update_source(self, source_path: Path) -> str:
        """Compute and store hash for source file."""
        if not self._loaded:
            self.load()

        # Compute hash
        file_hash = compute_file_hash(source_path, self.hash_algorithm)
        stat = source_path.stat()

        # Create/update metadata
        source_meta = SourceFileMetadata(
            path=str(source_path),
            hash=file_hash,
            last_modified=datetime.fromtimestamp(stat.st_mtime, timezone.utc).isoformat(),
            size_bytes=stat.st_size,
            hash_computed_at=datetime.now(timezone.utc).isoformat(),
        )

        file_path_str = str(source_path)
        if file_path_str in self._data:
            self._data[file_path_str].source = source_meta
        else:
            self._data[file_path_str] = FileMetadata(source=source_meta, outputs={})

        return file_hash

    def update_output(
        self,
        source_path: Path,
        output_path: Path,
        target_lang: str,
        source_hash: str,
        status: str = "success",
    ) -> None:
        """Record translation output metadata."""
        if not self._loaded:
            self.load()

        # Compute output hash
        output_hash = compute_file_hash(output_path, self.hash_algorithm)
        stat = output_path.stat()

        output_meta = OutputFileMetadata(
            path=str(output_path),
            hash=output_hash,
            translated_at=datetime.now(timezone.utc).isoformat(),
            source_hash_at_translation=source_hash,
            size_bytes=stat.st_size,
            status=status,
        )

        # Ensure source entry exists
        file_path_str = str(source_path)
        if file_path_str not in self._data:
            # Create stub (will be populated next time source is checked)
            self._data[file_path_str] = FileMetadata(
                source=SourceFileMetadata(
                    path=file_path_str,
                    hash=source_hash,
                    last_modified="",
                    size_bytes=0,
                    hash_computed_at="",
                ),
                outputs={}
            )

        # Update output
        self._data[file_path_str].outputs[target_lang] = output_meta

    def check_source_changed(self, source_path: Path, fast_path_mtime: bool = True) -> tuple[bool, str]:
        """
        Check if source file content has changed.

        Args:
            source_path: Path to source file
            fast_path_mtime: If True, skip hash computation if mtime unchanged

        Returns:
            (changed: bool, reason: str)
        """
        if not self._loaded:
            self.load()

        stored_hash = self.get_source_hash(source_path)
        if not stored_hash:
            return (True, "no stored hash (first run)")

        # Fast path: Check mtime first
        if fast_path_mtime:
            metadata = self._data.get(str(source_path))
            if metadata and metadata.source.last_modified:
                try:
                    stored_mtime = datetime.fromisoformat(metadata.source.last_modified)
                    current_mtime = datetime.fromtimestamp(
                        source_path.stat().st_mtime, timezone.utc
                    )

                    if current_mtime <= stored_mtime:
                        # mtime unchanged → content unchanged (high confidence)
                        # CHH-04: Cache hit (mtime fast path)
                        if self.metrics:
                            self.metrics.increment("content_hash_cache_hits")
                            self.metrics.increment("content_hash_no_change")
                        return (False, "mtime unchanged, hash assumed valid")
                except (ValueError, OSError):
                    # Failed to parse timestamp or stat file, fall through to hash check
                    pass

        # Slow path: Compute and compare hash
        # CHH-04: Cache miss (need to recompute hash)
        if self.metrics:
            self.metrics.increment("content_hash_cache_misses")

        current_hash = compute_file_hash(source_path, self.hash_algorithm, metrics=self.metrics)

        if current_hash == stored_hash:
            # CHH-04: No change detected
            if self.metrics:
                self.metrics.increment("content_hash_no_change")
            return (False, f"content unchanged (hash match: {current_hash[:8]}...)")
        else:
            # CHH-04: Change detected
            if self.metrics:
                self.metrics.increment("content_hash_changes_detected")
            return (True, f"content changed (hash {stored_hash[:8]}... → {current_hash[:8]}...)")

    def cleanup_old_entries(self, max_age_days: int = 30) -> list[str]:
        """
        Remove metadata for files not seen in X days.

        Args:
            max_age_days: Remove entries older than this many days

        Returns:
            List of removed file paths

        Notes:
            - Uses hash_computed_at timestamp to determine last activity
            - Invalid timestamps are preserved (safer than removing)
            - Automatically saves if entries removed
        """
        if not self._loaded:
            self.load()

        cutoff = datetime.now(timezone.utc) - timedelta(days=max_age_days)
        removed = []

        for file_path, metadata in list(self._data.items()):
            # Get last activity timestamp
            try:
                last_seen = datetime.fromisoformat(metadata.source.hash_computed_at)
            except (ValueError, AttributeError):
                # Invalid timestamp, keep entry (safer than removing)
                logger.warning(f"Invalid timestamp in metadata for {file_path}")
                continue

            # Check if stale
            if last_seen < cutoff:
                del self._data[file_path]
                removed.append(file_path)
                logger.debug(
                    f"Removed stale metadata for {file_path} "
                    f"(last seen: {last_seen.isoformat()})"
                )

        # Save if anything removed
        if removed:
            self.save()
            logger.info(
                f"Cleaned up {len(removed)} stale metadata entries "
                f"(older than {max_age_days} days)"
            )

        return removed
