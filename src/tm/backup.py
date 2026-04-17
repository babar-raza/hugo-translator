"""Automatic cache backup for Translation Memory.

This module provides backup and restore capabilities for the LMDB-based L2 cache,
with automatic pruning and disk space management.

Implementation follows TM-02 from the TM cache integrity plan.
"""

import logging
import shutil
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

import lmdb

logger = logging.getLogger(__name__)


class BackupError(Exception):
    """Raised when backup operation fails."""
    pass


class RestoreError(Exception):
    """Raised when restore operation fails."""
    pass


class InsufficientSpaceError(BackupError):
    """Raised when insufficient disk space for backup."""
    pass


class IntegrityCheckError(BackupError):
    """Raised when cache integrity check fails."""
    pass


@dataclass
class BackupInfo:
    """Metadata about a cache backup."""
    path: Path
    timestamp: datetime
    size_bytes: int
    entry_count: int

    @property
    def size_mb(self) -> float:
        """Get backup size in megabytes."""
        return self.size_bytes / (1024 * 1024)

    @property
    def size_gb(self) -> float:
        """Get backup size in gigabytes."""
        return self.size_bytes / (1024 * 1024 * 1024)

    def __str__(self) -> str:
        return (
            f"Backup({self.path.name}, "
            f"{self.size_mb:.1f}MB, {self.entry_count} entries, "
            f"{self.timestamp.strftime('%Y-%m-%d %H:%M')})"
        )

    def to_dict(self) -> dict:
        """Convert to dictionary for JSON serialization."""
        return {
            "path": str(self.path),
            "timestamp": self.timestamp.isoformat(),
            "size_bytes": self.size_bytes,
            "size_mb": round(self.size_mb, 2),
            "entry_count": self.entry_count
        }


class CacheBackupManager:
    """
    Manage LMDB cache backups with automatic pruning.

    Features:
    - Atomic backup using LMDB's native copy mechanism
    - Compacted backups to save disk space
    - Automatic pruning of old backups
    - Disk space verification before backup
    - Optional integrity check before backup
    - Safe restore with confirmation and safety backup

    Usage:
        manager = CacheBackupManager(
            tm_path=Path("./tm_cache"),
            backup_dir=Path("./tm_backups"),
            max_backups=5
        )

        # Create backup before translation
        backup_info = manager.create_backup()

        # List available backups
        backups = manager.list_backups()

        # Restore from backup (requires force=True or interactive confirmation)
        manager.restore_backup(backup_info.path, force=True)
    """

    # Backup directory naming pattern
    BACKUP_PREFIX = "tm_backup_"
    TIMESTAMP_FORMAT = "%Y%m%d_%H%M%S"

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
            min_free_space_gb: Minimum free disk space required in GB (default: 5.0)

        Raises:
            ValueError: If max_backups < 1 or min_free_space_gb < 0
        """
        if max_backups < 1:
            raise ValueError(f"max_backups must be >= 1, got {max_backups}")
        if min_free_space_gb < 0:
            raise ValueError(f"min_free_space_gb must be >= 0, got {min_free_space_gb}")

        self.tm_path = Path(tm_path)
        self.backup_dir = Path(backup_dir)
        self.max_backups = max_backups
        self.min_free_space_bytes = int(min_free_space_gb * 1024 * 1024 * 1024)

        # Create backup directory if it doesn't exist
        self.backup_dir.mkdir(parents=True, exist_ok=True)

    def create_backup(
        self,
        verify_integrity: bool = True,
        compact: bool = True
    ) -> BackupInfo:
        """
        Create timestamped backup of LMDB directory.

        Uses LMDB's native copy mechanism for atomic, consistent snapshots.
        The copy does not block ongoing reads to the database.

        Args:
            verify_integrity: Run integrity check before backup (default: True)
            compact: Compact database during copy to save space (default: True)

        Returns:
            BackupInfo with metadata about the created backup

        Raises:
            InsufficientSpaceError: If not enough disk space
            IntegrityCheckError: If cache integrity check fails
            BackupError: If backup operation fails
        """
        # Pre-flight checks
        self._check_tm_path_exists()
        self._check_disk_space()

        # Verify cache integrity (optional but recommended)
        if verify_integrity:
            self._verify_cache_integrity()

        # Generate backup path
        timestamp = datetime.now()
        backup_name = f"{self.BACKUP_PREFIX}{timestamp.strftime(self.TIMESTAMP_FORMAT)}"
        backup_path = self.backup_dir / backup_name

        logger.info(f"Creating backup: {backup_path}")

        try:
            # Open source LMDB in read-only mode (no lock needed)
            env = lmdb.open(str(self.tm_path), readonly=True, lock=False)

            try:
                # Create backup directory first (required on Windows)
                backup_path.mkdir(parents=True, exist_ok=True)

                # Use LMDB's native copy for atomic snapshot
                # compact=True reduces file size by defragmenting
                env.copy(str(backup_path), compact=compact)

                # Get backup statistics
                backup_size = self._get_directory_size(backup_path)
                entry_count = self._get_entry_count(backup_path)

            finally:
                env.close()

            # Prune old backups after successful backup
            self._prune_old_backups()

            backup_info = BackupInfo(
                path=backup_path,
                timestamp=timestamp,
                size_bytes=backup_size,
                entry_count=entry_count
            )

            logger.info(f"Backup created: {backup_info}")
            return backup_info

        except lmdb.Error as e:
            # Clean up partial backup if it exists
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            raise BackupError(f"LMDB copy failed: {e}") from e
        except OSError as e:
            if backup_path.exists():
                shutil.rmtree(backup_path, ignore_errors=True)
            raise BackupError(f"Backup failed: {e}") from e

    def restore_backup(
        self,
        backup_path: Path,
        force: bool = False,
        create_safety_backup: bool = True
    ) -> BackupInfo | None:
        """
        Restore from backup (DESTRUCTIVE operation).

        This operation replaces the current cache with the backup.
        Unless force=True, requires interactive confirmation.

        Args:
            backup_path: Path to backup to restore
            force: Skip confirmation prompt (default: False)
            create_safety_backup: Create backup of current state before restore (default: True)

        Returns:
            BackupInfo for safety backup if created, None otherwise

        Raises:
            ValueError: If backup doesn't exist
            RestoreError: If user doesn't confirm or restore fails
        """
        backup_path = Path(backup_path)

        if not backup_path.exists():
            raise ValueError(f"Backup not found: {backup_path}")

        # Verify backup is valid LMDB
        try:
            env = lmdb.open(str(backup_path), readonly=True)
            env.close()
        except lmdb.Error as e:
            raise ValueError(f"Invalid backup (not a valid LMDB): {backup_path}") from e

        # Confirmation prompt unless forced
        if not force:
            logger.warning(
                f"DESTRUCTIVE: Restoring from {backup_path} will overwrite current cache!"
            )
            response = input("Type 'yes' to continue: ")
            if response.lower().strip() != 'yes':
                raise RestoreError("Restore cancelled by user")

        # Create safety backup of current state
        safety_backup_info = None
        if create_safety_backup and self.tm_path.exists():
            logger.info("Creating safety backup of current cache before restore")
            try:
                safety_timestamp = datetime.now()
                safety_name = f"pre_restore_{safety_timestamp.strftime(self.TIMESTAMP_FORMAT)}"
                safety_path = self.backup_dir / safety_name

                # Copy current cache
                shutil.copytree(self.tm_path, safety_path)

                safety_backup_info = BackupInfo(
                    path=safety_path,
                    timestamp=safety_timestamp,
                    size_bytes=self._get_directory_size(safety_path),
                    entry_count=self._get_entry_count(safety_path)
                )
                logger.info(f"Safety backup created: {safety_backup_info}")

            except Exception as e:
                logger.error(f"Failed to create safety backup: {e}")
                if not force:
                    raise RestoreError(f"Safety backup failed: {e}") from e

        # Perform restore
        logger.info(f"Restoring from {backup_path} to {self.tm_path}")
        try:
            # Remove current cache
            if self.tm_path.exists():
                shutil.rmtree(self.tm_path)

            # Copy backup to cache location
            shutil.copytree(backup_path, self.tm_path)

            logger.info("Restore complete")
            return safety_backup_info

        except Exception as e:
            raise RestoreError(f"Restore failed: {e}") from e

    def list_backups(self) -> list[BackupInfo]:
        """
        List all available backups sorted by timestamp (newest first).

        Returns:
            List of BackupInfo objects for each valid backup
        """
        backups = []

        # Find all backup directories matching the pattern
        pattern = f"{self.BACKUP_PREFIX}*"
        for backup_dir in sorted(self.backup_dir.glob(pattern), reverse=True):
            if not backup_dir.is_dir():
                continue

            try:
                # Parse timestamp from directory name
                timestamp_str = backup_dir.name.replace(self.BACKUP_PREFIX, "")
                timestamp = datetime.strptime(timestamp_str, self.TIMESTAMP_FORMAT)

                # Get size and entry count
                size_bytes = self._get_directory_size(backup_dir)
                entry_count = self._get_entry_count(backup_dir)

                backups.append(BackupInfo(
                    path=backup_dir,
                    timestamp=timestamp,
                    size_bytes=size_bytes,
                    entry_count=entry_count
                ))

            except ValueError as e:
                logger.warning(f"Failed to parse backup timestamp {backup_dir.name}: {e}")
            except lmdb.Error as e:
                logger.warning(f"Failed to read backup {backup_dir}: {e}")
            except Exception as e:
                logger.warning(f"Failed to process backup {backup_dir}: {e}")

        return backups

    def delete_backup(self, backup_path: Path) -> None:
        """
        Delete a specific backup.

        Args:
            backup_path: Path to backup to delete

        Raises:
            ValueError: If backup doesn't exist
        """
        backup_path = Path(backup_path)

        if not backup_path.exists():
            raise ValueError(f"Backup not found: {backup_path}")

        logger.info(f"Deleting backup: {backup_path}")
        shutil.rmtree(backup_path)

    def get_backup_by_timestamp(self, timestamp_str: str) -> BackupInfo | None:
        """
        Find backup by timestamp string.

        Args:
            timestamp_str: Timestamp in YYYYMMDD_HHMMSS format

        Returns:
            BackupInfo if found, None otherwise
        """
        target_name = f"{self.BACKUP_PREFIX}{timestamp_str}"
        target_path = self.backup_dir / target_name

        if target_path.exists():
            try:
                timestamp = datetime.strptime(timestamp_str, self.TIMESTAMP_FORMAT)
                return BackupInfo(
                    path=target_path,
                    timestamp=timestamp,
                    size_bytes=self._get_directory_size(target_path),
                    entry_count=self._get_entry_count(target_path)
                )
            except Exception:
                pass

        return None

    def get_latest_backup(self) -> BackupInfo | None:
        """
        Get the most recent backup.

        Returns:
            BackupInfo for latest backup, or None if no backups exist
        """
        backups = self.list_backups()
        return backups[0] if backups else None

    def _check_tm_path_exists(self) -> None:
        """Verify TM path exists."""
        if not self.tm_path.exists():
            raise BackupError(f"TM cache path does not exist: {self.tm_path}")

    def _check_disk_space(self) -> None:
        """Check if sufficient disk space is available."""
        try:
            stat = shutil.disk_usage(self.backup_dir)
            free_space = stat.free

            if free_space < self.min_free_space_bytes:
                raise InsufficientSpaceError(
                    f"Insufficient disk space: {free_space / (1024**3):.1f}GB free, "
                    f"{self.min_free_space_bytes / (1024**3):.1f}GB required"
                )
        except OSError as e:
            raise BackupError(f"Failed to check disk space: {e}") from e

    def _verify_cache_integrity(self) -> None:
        """Run integrity check before backup."""
        try:
            from .integrity import CacheIntegrityChecker
            from .l2_persistent import L2PersistentTM

            l2 = L2PersistentTM(self.tm_path)
            try:
                checker = CacheIntegrityChecker(l2)
                report = checker.verify_all(repair=False, log_progress=False)

                if report.health_percentage < 95.0:
                    raise IntegrityCheckError(
                        f"Cache integrity check failed: {report.health_percentage:.1f}% healthy. "
                        f"Fix corruption before backup. Corrupted entries: {report.corrupt_count}"
                    )

                logger.info(f"Integrity check passed: {report.health_percentage:.1f}% healthy")

            finally:
                l2.close()

        except ImportError as e:
            logger.warning(f"Integrity check skipped (module not available): {e}")
        except IntegrityCheckError:
            raise
        except Exception as e:
            logger.warning(f"Integrity check skipped (error): {e}")

    def _prune_old_backups(self) -> None:
        """Keep only max_backups most recent backups."""
        backups = self.list_backups()

        if len(backups) > self.max_backups:
            to_delete = backups[self.max_backups:]
            for backup in to_delete:
                logger.info(f"Pruning old backup: {backup.path}")
                try:
                    shutil.rmtree(backup.path)
                except Exception as e:
                    logger.error(f"Failed to prune backup {backup.path}: {e}")

    def _get_directory_size(self, path: Path) -> int:
        """Calculate total size of directory contents."""
        total = 0
        for f in path.rglob("*"):
            if f.is_file():
                try:
                    total += f.stat().st_size
                except OSError:
                    pass
        return total

    def _get_entry_count(self, path: Path) -> int:
        """Get number of entries in LMDB database."""
        try:
            env = lmdb.open(str(path), readonly=True, lock=False)
            try:
                count = env.stat()['entries']
            finally:
                env.close()
            return count
        except lmdb.Error:
            return 0


def create_backup_manager(
    tm_path: Path,
    backup_dir: Path | None = None,
    max_backups: int = 5,
    min_free_space_gb: float = 5.0
) -> CacheBackupManager:
    """
    Convenience function to create a backup manager.

    Args:
        tm_path: Path to LMDB cache directory
        backup_dir: Directory to store backups (default: {tm_path}_backups)
        max_backups: Maximum number of backups to retain
        min_free_space_gb: Minimum free disk space required (GB)

    Returns:
        CacheBackupManager instance
    """
    tm_path = Path(tm_path)

    if backup_dir is None:
        backup_dir = tm_path.parent / f"{tm_path.name}_backups"

    return CacheBackupManager(
        tm_path=tm_path,
        backup_dir=backup_dir,
        max_backups=max_backups,
        min_free_space_gb=min_free_space_gb
    )
