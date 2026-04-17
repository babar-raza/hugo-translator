"""Archive system for benchmark database.

Provides:
- Archive old benchmark runs to separate SQLite file
- Restore from archive capability
- Archive metadata tracking (creation date, data range, size)
- Archive rotation (keep N most recent archives)

Phase 4.3: Data Retention & Export
"""

import gzip
import json
import logging
import shutil
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import TYPE_CHECKING, Optional

if TYPE_CHECKING:
    from src.shared_engines.composition_root import SharedEngines

logger = logging.getLogger(__name__)


@dataclass
class ArchiveMetadata:
    """Metadata for an archive file.

    Attributes:
        archive_id: Unique archive identifier
        archive_path: Path to archive file
        created_at: Archive creation timestamp
        source_database: Source database path
        data_start_date: Oldest data in archive
        data_end_date: Newest data in archive
        total_runs: Number of benchmark runs
        total_results: Number of benchmark results
        file_size_bytes: Archive file size
        compressed: Whether archive is compressed
        schema_version: Database schema version
    """

    archive_id: str
    archive_path: str
    created_at: str
    source_database: str
    data_start_date: str | None
    data_end_date: str | None
    total_runs: int
    total_results: int
    file_size_bytes: int
    compressed: bool
    schema_version: int

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "archive_id": self.archive_id,
            "archive_path": self.archive_path,
            "created_at": self.created_at,
            "source_database": self.source_database,
            "data_start_date": self.data_start_date,
            "data_end_date": self.data_end_date,
            "total_runs": self.total_runs,
            "total_results": self.total_results,
            "file_size_bytes": self.file_size_bytes,
            "compressed": self.compressed,
            "schema_version": self.schema_version,
        }

    @classmethod
    def from_dict(cls, data: dict) -> "ArchiveMetadata":
        """Create from dictionary."""
        return cls(**data)


@dataclass
class ArchiveResult:
    """Result of archive operation.

    Attributes:
        success: Whether operation succeeded
        archive_path: Path to archive file
        metadata: Archive metadata
        rows_archived: Total rows archived
        rows_deleted: Rows deleted from source (if delete_after_archive)
        duration_seconds: Operation duration
        error: Error message if failed
    """

    success: bool
    archive_path: str | None
    metadata: ArchiveMetadata | None
    rows_archived: int
    rows_deleted: int
    duration_seconds: float
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "archive_path": self.archive_path,
            "metadata": self.metadata.to_dict() if self.metadata else None,
            "rows_archived": self.rows_archived,
            "rows_deleted": self.rows_deleted,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


@dataclass
class RestoreResult:
    """Result of restore operation.

    Attributes:
        success: Whether operation succeeded
        archive_path: Path to restored archive
        rows_restored: Total rows restored
        tables_restored: Tables restored
        duration_seconds: Operation duration
        error: Error message if failed
    """

    success: bool
    archive_path: str
    rows_restored: int
    tables_restored: list[str]
    duration_seconds: float
    error: str | None = None

    def to_dict(self) -> dict:
        """Convert to dictionary."""
        return {
            "success": self.success,
            "archive_path": self.archive_path,
            "rows_restored": self.rows_restored,
            "tables_restored": self.tables_restored,
            "duration_seconds": self.duration_seconds,
            "error": self.error,
        }


class BenchmarkArchiver:
    """Archive system for benchmark database.

    Features:
    - Archive old data to separate SQLite files
    - Optional compression (gzip)
    - Restore data from archives
    - Archive metadata tracking
    - Archive rotation (keep N most recent)
    - Telemetry event emission

    Example:
        archiver = BenchmarkArchiver(
            db_path="data/benchmarks.db",
            archive_dir="data/archives"
        )

        # Create archive for data older than 90 days
        result = archiver.create_archive(before_date="2024-01-01")

        # List archives
        archives = archiver.list_archives()

        # Restore from archive
        result = archiver.restore_archive("archive_20240115_120000.db")

        # Rotate archives (keep 5 most recent)
        deleted = archiver.rotate_archives(keep_count=5)
    """

    # Tables to include in archive
    ARCHIVE_TABLES = [
        "benchmark_runs",
        "benchmark_results",
        "system_info",
    ]

    # Metadata table schema
    METADATA_TABLE_SQL = """
        CREATE TABLE IF NOT EXISTS archive_metadata (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        )
    """

    def __init__(
        self,
        db_path: Path | str,
        archive_dir: Path | str | None = None,
        engines: Optional["SharedEngines"] = None,
    ):
        """Initialize archiver.

        Args:
            db_path: Path to benchmark database
            archive_dir: Directory for archive files (default: data/archives)
            engines: Optional SharedEngines for logging/telemetry
        """
        self.db_path = Path(db_path) if db_path != ":memory:" else db_path

        if archive_dir:
            self.archive_dir = Path(archive_dir)
        else:
            if self.db_path == ":memory:":
                self.archive_dir = Path("data/archives")
            else:
                self.archive_dir = self.db_path.parent / "archives"

        self.archive_dir.mkdir(parents=True, exist_ok=True)
        self.engines = engines

        if engines:
            logger.info("BenchmarkArchiver initialized with SharedEngines support")

    def _create_connection(self, db_path: Path | None = None) -> sqlite3.Connection:
        """Create database connection with proper settings.

        Args:
            db_path: Database path (default: self.db_path)

        Returns:
            Configured SQLite connection
        """
        path = db_path or self.db_path
        conn = sqlite3.connect(str(path))
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        return conn

    def _emit_telemetry(self, event: str, **kwargs) -> None:
        """Emit telemetry event.

        Args:
            event: Event name
            **kwargs: Event parameters
        """
        if self.engines:
            self.engines.telemetry.track_event(event, **kwargs)

    def create_archive(
        self,
        before_date: str,
        compress: bool = False,
        delete_after_archive: bool = False,
        archive_name: str | None = None,
    ) -> ArchiveResult:
        """Create archive of benchmark data before a specific date.

        Args:
            before_date: Archive data before this date (ISO format: YYYY-MM-DD)
            compress: Whether to compress the archive with gzip
            delete_after_archive: Whether to delete archived data from source
            archive_name: Custom archive name (default: auto-generated)

        Returns:
            ArchiveResult object
        """
        start_time = datetime.now(UTC)

        self._emit_telemetry(
            "benchmark_archive_started",
            before_date=before_date,
            compress=compress,
            delete_after=delete_after_archive,
        )

        logger.info(
            f"Creating archive for data before {before_date} "
            f"(compress={compress}, delete_after={delete_after_archive})"
        )

        try:
            # Generate archive path
            if archive_name:
                archive_filename = archive_name
            else:
                timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
                archive_filename = f"archive_{timestamp}"

            if compress:
                archive_path = self.archive_dir / f"{archive_filename}.db.gz"
            else:
                archive_path = self.archive_dir / f"{archive_filename}.db"

            # Create archive database
            temp_archive_path = self.archive_dir / f"{archive_filename}_temp.db"

            try:
                metadata = self._create_archive_database(
                    temp_archive_path, before_date
                )
            except Exception:
                if temp_archive_path.exists():
                    temp_archive_path.unlink()
                raise

            if metadata.total_runs == 0:
                # No data to archive
                temp_archive_path.unlink()
                logger.warning(f"No data found to archive before {before_date}")

                return ArchiveResult(
                    success=True,
                    archive_path=None,
                    metadata=None,
                    rows_archived=0,
                    rows_deleted=0,
                    duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                )

            # Compress if requested
            if compress:
                self._compress_file(temp_archive_path, archive_path)
                temp_archive_path.unlink()
            else:
                temp_archive_path.rename(archive_path)

            # Update metadata with final path and size
            metadata.archive_path = str(archive_path)
            metadata.file_size_bytes = archive_path.stat().st_size
            metadata.compressed = compress

            # Save metadata to JSON sidecar
            self._save_archive_metadata(archive_path, metadata)

            # Delete source data if requested
            rows_deleted = 0
            if delete_after_archive:
                rows_deleted = self._delete_archived_data(before_date)

            duration = (datetime.now(UTC) - start_time).total_seconds()

            result = ArchiveResult(
                success=True,
                archive_path=str(archive_path),
                metadata=metadata,
                rows_archived=metadata.total_results,
                rows_deleted=rows_deleted,
                duration_seconds=duration,
            )

            logger.info(
                f"Archive created: {archive_path} "
                f"({metadata.total_runs} runs, {metadata.total_results} results, "
                f"{metadata.file_size_bytes:,} bytes) in {duration:.2f}s"
            )

            self._emit_telemetry(
                "benchmark_archive_created",
                archive_path=str(archive_path),
                runs_archived=metadata.total_runs,
                results_archived=metadata.total_results,
                file_size_bytes=metadata.file_size_bytes,
                compressed=compress,
                rows_deleted=rows_deleted,
                duration_seconds=duration,
            )

            return result

        except Exception as e:
            logger.error(f"Archive creation failed: {e}", exc_info=True)

            self._emit_telemetry(
                "benchmark_archive_failed",
                error=str(e),
            )

            return ArchiveResult(
                success=False,
                archive_path=None,
                metadata=None,
                rows_archived=0,
                rows_deleted=0,
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                error=str(e),
            )

    def _create_archive_database(
        self, archive_path: Path, before_date: str
    ) -> ArchiveMetadata:
        """Create archive database with filtered data.

        Args:
            archive_path: Path for new archive database
            before_date: Archive data before this date

        Returns:
            ArchiveMetadata object
        """
        source_conn = self._create_connection()
        archive_conn = sqlite3.connect(str(archive_path))

        try:
            # Copy schema for archive tables
            for table in self.ARCHIVE_TABLES:
                cursor = source_conn.execute(
                    f"SELECT sql FROM sqlite_master WHERE type='table' AND name='{table}'"
                )
                row = cursor.fetchone()
                if row:
                    archive_conn.execute(row[0])

            # Create metadata table
            archive_conn.execute(self.METADATA_TABLE_SQL)

            # Copy data for benchmark_runs
            cursor = source_conn.execute(
                """
                SELECT * FROM benchmark_runs WHERE timestamp_utc < ?
                """,
                (before_date,),
            )
            runs = cursor.fetchall()

            if not runs:
                archive_conn.close()
                source_conn.close()
                return ArchiveMetadata(
                    archive_id=archive_path.stem,
                    archive_path=str(archive_path),
                    created_at=datetime.now(UTC).isoformat(),
                    source_database=str(self.db_path),
                    data_start_date=None,
                    data_end_date=None,
                    total_runs=0,
                    total_results=0,
                    file_size_bytes=0,
                    compressed=False,
                    schema_version=self._get_schema_version(source_conn),
                )

            run_ids = [row["run_id"] for row in runs]
            columns = [desc[0] for desc in cursor.description]
            placeholders = ",".join("?" * len(columns))

            for row in runs:
                archive_conn.execute(
                    f"INSERT INTO benchmark_runs ({','.join(columns)}) VALUES ({placeholders})",
                    tuple(row),
                )

            # Copy benchmark_results for archived runs
            results_copied = 0
            for run_id in run_ids:
                cursor = source_conn.execute(
                    "SELECT * FROM benchmark_results WHERE run_id = ?",
                    (run_id,),
                )
                results = cursor.fetchall()

                if results:
                    columns = [desc[0] for desc in cursor.description]
                    placeholders = ",".join("?" * len(columns))

                    for row in results:
                        archive_conn.execute(
                            f"INSERT INTO benchmark_results ({','.join(columns)}) VALUES ({placeholders})",
                            tuple(row),
                        )
                        results_copied += 1

            # Copy system_info for archived runs
            for run_id in run_ids:
                cursor = source_conn.execute(
                    "SELECT * FROM system_info WHERE run_id = ?",
                    (run_id,),
                )
                sys_info = cursor.fetchone()

                if sys_info:
                    columns = [desc[0] for desc in cursor.description]
                    placeholders = ",".join("?" * len(columns))

                    archive_conn.execute(
                        f"INSERT INTO system_info ({','.join(columns)}) VALUES ({placeholders})",
                        tuple(sys_info),
                    )

            # Get date range
            timestamps = [row["timestamp_utc"] for row in runs]
            data_start = min(timestamps) if timestamps else None
            data_end = max(timestamps) if timestamps else None

            # Create metadata
            metadata = ArchiveMetadata(
                archive_id=archive_path.stem,
                archive_path=str(archive_path),
                created_at=datetime.now(UTC).isoformat(),
                source_database=str(self.db_path),
                data_start_date=data_start,
                data_end_date=data_end,
                total_runs=len(runs),
                total_results=results_copied,
                file_size_bytes=0,  # Will be updated after compression
                compressed=False,
                schema_version=self._get_schema_version(source_conn),
            )

            # Store metadata in archive
            for key, value in metadata.to_dict().items():
                archive_conn.execute(
                    "INSERT INTO archive_metadata (key, value) VALUES (?, ?)",
                    (key, json.dumps(value)),
                )

            archive_conn.commit()
            return metadata

        finally:
            archive_conn.close()
            source_conn.close()

    def _get_schema_version(self, conn: sqlite3.Connection) -> int:
        """Get database schema version.

        Args:
            conn: Database connection

        Returns:
            Schema version number
        """
        try:
            cursor = conn.execute(
                "SELECT version FROM schema_version ORDER BY version DESC LIMIT 1"
            )
            row = cursor.fetchone()
            return row[0] if row else 0
        except sqlite3.Error:
            return 0

    def _compress_file(self, source: Path, dest: Path) -> None:
        """Compress a file with gzip.

        Args:
            source: Source file path
            dest: Destination file path
        """
        with open(source, "rb") as f_in:
            with gzip.open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _decompress_file(self, source: Path, dest: Path) -> None:
        """Decompress a gzip file.

        Args:
            source: Source file path
            dest: Destination file path
        """
        with gzip.open(source, "rb") as f_in:
            with open(dest, "wb") as f_out:
                shutil.copyfileobj(f_in, f_out)

    def _save_archive_metadata(
        self, archive_path: Path, metadata: ArchiveMetadata
    ) -> None:
        """Save archive metadata to JSON sidecar file.

        Args:
            archive_path: Archive file path
            metadata: Archive metadata
        """
        metadata_path = archive_path.with_suffix(archive_path.suffix + ".meta.json")
        with open(metadata_path, "w") as f:
            json.dump(metadata.to_dict(), f, indent=2)

    def _load_archive_metadata(self, archive_path: Path) -> ArchiveMetadata | None:
        """Load archive metadata from JSON sidecar file.

        Args:
            archive_path: Archive file path

        Returns:
            ArchiveMetadata or None if not found
        """
        metadata_path = archive_path.with_suffix(archive_path.suffix + ".meta.json")

        if not metadata_path.exists():
            # Try to extract from archive database
            return self._extract_metadata_from_archive(archive_path)

        try:
            with open(metadata_path) as f:
                data = json.load(f)
            return ArchiveMetadata.from_dict(data)
        except Exception as e:
            logger.warning(f"Failed to load metadata for {archive_path}: {e}")
            return None

    def _extract_metadata_from_archive(
        self, archive_path: Path
    ) -> ArchiveMetadata | None:
        """Extract metadata from archive database.

        Args:
            archive_path: Archive file path

        Returns:
            ArchiveMetadata or None if not found
        """
        try:
            # Decompress if needed
            if archive_path.suffix == ".gz":
                temp_path = archive_path.with_suffix("")
                self._decompress_file(archive_path, temp_path)
                db_path = temp_path
                cleanup = True
            else:
                db_path = archive_path
                cleanup = False

            conn = sqlite3.connect(str(db_path))
            conn.row_factory = sqlite3.Row

            try:
                cursor = conn.execute("SELECT key, value FROM archive_metadata")
                data = {}
                for row in cursor.fetchall():
                    data[row["key"]] = json.loads(row["value"])

                if data:
                    return ArchiveMetadata.from_dict(data)
                return None

            finally:
                conn.close()
                if cleanup and db_path.exists():
                    db_path.unlink()

        except Exception as e:
            logger.warning(f"Failed to extract metadata from {archive_path}: {e}")
            return None

    def _delete_archived_data(self, before_date: str) -> int:
        """Delete archived data from source database.

        Args:
            before_date: Delete data before this date

        Returns:
            Number of rows deleted
        """
        conn = self._create_connection()
        try:
            # Delete runs (cascades to results and system_info)
            cursor = conn.execute(
                "DELETE FROM benchmark_runs WHERE timestamp_utc < ?",
                (before_date,),
            )
            deleted = cursor.rowcount
            conn.commit()

            logger.info(f"Deleted {deleted} runs from source database")
            return deleted

        finally:
            conn.close()

    def list_archives(self) -> list[ArchiveMetadata]:
        """List all archives in archive directory.

        Returns:
            List of ArchiveMetadata objects, sorted by creation date (newest first)
        """
        archives = []

        for path in self.archive_dir.glob("archive_*.db*"):
            # Skip metadata files
            if ".meta.json" in path.suffixes:
                continue

            metadata = self._load_archive_metadata(path)
            if metadata:
                archives.append(metadata)
            else:
                # Create basic metadata from file info
                archives.append(ArchiveMetadata(
                    archive_id=path.stem.replace(".db", ""),
                    archive_path=str(path),
                    created_at=datetime.fromtimestamp(
                        path.stat().st_mtime, tz=UTC
                    ).isoformat(),
                    source_database="unknown",
                    data_start_date=None,
                    data_end_date=None,
                    total_runs=0,
                    total_results=0,
                    file_size_bytes=path.stat().st_size,
                    compressed=path.suffix == ".gz",
                    schema_version=0,
                ))

        # Sort by creation date (newest first)
        archives.sort(key=lambda a: a.created_at, reverse=True)
        return archives

    def get_archive(self, archive_name: str) -> ArchiveMetadata | None:
        """Get metadata for a specific archive.

        Args:
            archive_name: Archive name (without directory)

        Returns:
            ArchiveMetadata or None if not found
        """
        # Try different extensions
        for ext in [".db", ".db.gz"]:
            path = self.archive_dir / f"{archive_name}{ext}"
            if path.exists():
                return self._load_archive_metadata(path)

        # Try exact name
        path = self.archive_dir / archive_name
        if path.exists():
            return self._load_archive_metadata(path)

        return None

    def restore_archive(
        self,
        archive_name: str,
        skip_duplicates: bool = True,
    ) -> RestoreResult:
        """Restore data from an archive.

        Args:
            archive_name: Archive name or path
            skip_duplicates: Skip records that already exist (default: True)

        Returns:
            RestoreResult object
        """
        start_time = datetime.now(UTC)

        # Find archive path
        archive_path = None
        for ext in ["", ".db", ".db.gz"]:
            test_path = self.archive_dir / f"{archive_name}{ext}"
            if test_path.exists():
                archive_path = test_path
                break

        # Try as full path
        if archive_path is None:
            archive_path = Path(archive_name)

        if not archive_path.exists():
            return RestoreResult(
                success=False,
                archive_path=archive_name,
                rows_restored=0,
                tables_restored=[],
                duration_seconds=0,
                error=f"Archive not found: {archive_name}",
            )

        self._emit_telemetry(
            "benchmark_archive_restore_started",
            archive_path=str(archive_path),
        )

        logger.info(f"Restoring from archive: {archive_path}")

        try:
            # Decompress if needed
            if archive_path.suffix == ".gz":
                temp_path = archive_path.with_suffix("")
                self._decompress_file(archive_path, temp_path)
                db_path = temp_path
                cleanup = True
            else:
                db_path = archive_path
                cleanup = False

            # Restore data
            rows_restored, tables_restored = self._restore_data(
                db_path, skip_duplicates
            )

            if cleanup and db_path.exists():
                db_path.unlink()

            duration = (datetime.now(UTC) - start_time).total_seconds()

            result = RestoreResult(
                success=True,
                archive_path=str(archive_path),
                rows_restored=rows_restored,
                tables_restored=tables_restored,
                duration_seconds=duration,
            )

            logger.info(
                f"Archive restored: {rows_restored} rows from {len(tables_restored)} tables "
                f"in {duration:.2f}s"
            )

            self._emit_telemetry(
                "benchmark_archive_restored",
                archive_path=str(archive_path),
                rows_restored=rows_restored,
                tables_restored=len(tables_restored),
                duration_seconds=duration,
            )

            return result

        except Exception as e:
            logger.error(f"Archive restore failed: {e}", exc_info=True)

            self._emit_telemetry(
                "benchmark_archive_restore_failed",
                archive_path=str(archive_path),
                error=str(e),
            )

            return RestoreResult(
                success=False,
                archive_path=str(archive_path),
                rows_restored=0,
                tables_restored=[],
                duration_seconds=(datetime.now(UTC) - start_time).total_seconds(),
                error=str(e),
            )

    def _restore_data(
        self, archive_db_path: Path, skip_duplicates: bool
    ) -> tuple[int, list[str]]:
        """Restore data from archive database.

        Args:
            archive_db_path: Path to archive database
            skip_duplicates: Skip existing records

        Returns:
            Tuple of (rows_restored, tables_restored)
        """
        archive_conn = sqlite3.connect(str(archive_db_path))
        archive_conn.row_factory = sqlite3.Row

        dest_conn = self._create_connection()

        total_rows = 0
        tables_restored = []

        try:
            for table in self.ARCHIVE_TABLES:
                rows = self._restore_table(
                    archive_conn, dest_conn, table, skip_duplicates
                )
                if rows > 0:
                    total_rows += rows
                    tables_restored.append(table)

            dest_conn.commit()
            return total_rows, tables_restored

        finally:
            archive_conn.close()
            dest_conn.close()

    def _restore_table(
        self,
        archive_conn: sqlite3.Connection,
        dest_conn: sqlite3.Connection,
        table: str,
        skip_duplicates: bool,
    ) -> int:
        """Restore a single table from archive.

        Args:
            archive_conn: Archive database connection
            dest_conn: Destination database connection
            table: Table name
            skip_duplicates: Skip existing records

        Returns:
            Number of rows restored
        """
        try:
            cursor = archive_conn.execute(f"SELECT * FROM {table}")
            rows = cursor.fetchall()

            if not rows:
                return 0

            columns = [desc[0] for desc in cursor.description]
            placeholders = ",".join("?" * len(columns))

            restored = 0
            for row in rows:
                try:
                    dest_conn.execute(
                        f"INSERT INTO {table} ({','.join(columns)}) VALUES ({placeholders})",
                        tuple(row),
                    )
                    restored += 1
                except sqlite3.IntegrityError:
                    if not skip_duplicates:
                        raise
                    # Skip duplicate

            return restored

        except sqlite3.Error as e:
            logger.warning(f"Failed to restore table {table}: {e}")
            return 0

    def rotate_archives(self, keep_count: int = 5) -> int:
        """Rotate archives, keeping only the most recent.

        Args:
            keep_count: Number of archives to keep

        Returns:
            Number of archives deleted
        """
        archives = self.list_archives()

        if len(archives) <= keep_count:
            logger.info(
                f"Archive rotation: {len(archives)} archives, keeping {keep_count} - no rotation needed"
            )
            return 0

        # Delete oldest archives
        to_delete = archives[keep_count:]
        deleted = 0

        for archive in to_delete:
            try:
                archive_path = Path(archive.archive_path)
                metadata_path = archive_path.with_suffix(
                    archive_path.suffix + ".meta.json"
                )

                if archive_path.exists():
                    archive_path.unlink()
                    deleted += 1

                if metadata_path.exists():
                    metadata_path.unlink()

                logger.info(f"Deleted archive: {archive_path}")

            except Exception as e:
                logger.error(f"Failed to delete archive {archive.archive_path}: {e}")

        logger.info(
            f"Archive rotation completed: deleted {deleted} of {len(to_delete)} archives"
        )

        self._emit_telemetry(
            "benchmark_archive_rotation",
            kept=keep_count,
            deleted=deleted,
        )

        return deleted

    def delete_archive(self, archive_name: str) -> bool:
        """Delete a specific archive.

        Args:
            archive_name: Archive name or path

        Returns:
            True if deleted, False if not found
        """
        # Find archive
        archive = self.get_archive(archive_name)
        if not archive:
            logger.warning(f"Archive not found: {archive_name}")
            return False

        try:
            archive_path = Path(archive.archive_path)
            metadata_path = archive_path.with_suffix(
                archive_path.suffix + ".meta.json"
            )

            if archive_path.exists():
                archive_path.unlink()

            if metadata_path.exists():
                metadata_path.unlink()

            logger.info(f"Deleted archive: {archive_path}")
            return True

        except Exception as e:
            logger.error(f"Failed to delete archive {archive_name}: {e}")
            return False

    def get_archive_summary(self) -> dict:
        """Get summary of all archives.

        Returns:
            Dictionary with archive summary
        """
        archives = self.list_archives()

        total_size = sum(a.file_size_bytes for a in archives)
        total_runs = sum(a.total_runs for a in archives)
        total_results = sum(a.total_results for a in archives)

        return {
            "archive_count": len(archives),
            "total_size_bytes": total_size,
            "total_runs": total_runs,
            "total_results": total_results,
            "oldest_archive": archives[-1].created_at if archives else None,
            "newest_archive": archives[0].created_at if archives else None,
            "archive_directory": str(self.archive_dir),
        }
