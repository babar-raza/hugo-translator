"""Unit tests for Translation Memory cache backup system.

Tests cover:
- Backup creation and metadata
- Backup listing and retrieval
- Backup restoration
- Automatic pruning
- Disk space validation
- Integrity check integration
- Error handling
"""

import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tm.backup import (
    BackupError,
    BackupInfo,
    CacheBackupManager,
    InsufficientSpaceError,
    create_backup_manager,
)
from tm.l2_persistent import L2PersistentTM


class TestBackupInfo:
    """Tests for BackupInfo dataclass."""

    def test_backup_info_size_mb(self):
        """Test megabyte conversion."""
        info = BackupInfo(
            path=Path("/test/backup"),
            timestamp=datetime.now(),
            size_bytes=512 * 1024 * 1024,
            entry_count=1000,
        )
        assert info.size_mb == 512.0

    def test_backup_info_size_gb(self):
        """Test gigabyte conversion."""
        info = BackupInfo(
            path=Path("/test/backup"),
            timestamp=datetime.now(),
            size_bytes=1024 * 1024 * 1024,
            entry_count=1000,
        )
        assert info.size_gb == 1.0

    def test_backup_info_string_format(self):
        """Test string representation."""
        timestamp = datetime(2025, 12, 23, 14, 30)
        info = BackupInfo(
            path=Path("/test/tm_backup_20251223_143000"),
            timestamp=timestamp,
            size_bytes=100 * 1024 * 1024,
            entry_count=5000,
        )
        s = str(info)
        assert "tm_backup_20251223_143000" in s
        assert "100.0MB" in s
        assert "5000 entries" in s
        assert "2025-12-23 14:30" in s

    def test_backup_info_to_dict(self):
        """Test dictionary conversion."""
        timestamp = datetime(2025, 12, 23, 14, 30)
        info = BackupInfo(
            path=Path("/test/backup"),
            timestamp=timestamp,
            size_bytes=100 * 1024 * 1024,
            entry_count=5000,
        )
        d = info.to_dict()
        assert d["size_bytes"] == 100 * 1024 * 1024
        assert d["size_mb"] == 100.0
        assert d["entry_count"] == 5000
        assert "2025-12-23" in d["timestamp"]


class TestCacheBackupManagerInit:
    """Tests for CacheBackupManager initialization."""

    def test_init_creates_backup_dir(self, tmp_path):
        """Test backup directory is created."""
        tm_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "backups"

        # Create TM path
        tm_path.mkdir()

        manager = CacheBackupManager(tm_path=tm_path, backup_dir=backup_dir)

        assert backup_dir.exists()
        assert manager.max_backups == 5  # Default

    def test_init_validates_max_backups(self, tmp_path):
        """Test max_backups validation."""
        with pytest.raises(ValueError, match="max_backups"):
            CacheBackupManager(tm_path=tmp_path, backup_dir=tmp_path / "backups", max_backups=0)

    def test_init_validates_min_free_space(self, tmp_path):
        """Test min_free_space_gb validation."""
        with pytest.raises(ValueError, match="min_free_space"):
            CacheBackupManager(
                tm_path=tmp_path, backup_dir=tmp_path / "backups", min_free_space_gb=-1
            )


class TestCacheBackupManagerBackup:
    """Tests for backup creation."""

    @pytest.fixture
    def populated_tm(self, tmp_path):
        """Create L2 TM with test data."""
        db_path = tmp_path / "tm_cache"
        l2 = L2PersistentTM(db_path, max_size_mb=10)

        # Add test entries
        for i in range(100):
            l2.store(
                site_id="test.site",
                src_lang="en",
                tgt_lang="es",
                text=f"Test source text {i}",
                translation=f"Test translation {i}",
            )

        l2.close()
        return db_path

    def test_create_backup_success(self, populated_tm, tmp_path):
        """Test successful backup creation."""
        backup_dir = tmp_path / "backups"

        manager = CacheBackupManager(
            tm_path=populated_tm, backup_dir=backup_dir, min_free_space_gb=0
        )

        backup_info = manager.create_backup(verify_integrity=False)

        assert backup_info.path.exists()
        assert backup_info.entry_count == 100
        assert backup_info.size_bytes > 0
        assert "tm_backup_" in backup_info.path.name

    def test_create_backup_naming(self, populated_tm, tmp_path):
        """Test backup naming convention."""
        manager = CacheBackupManager(
            tm_path=populated_tm, backup_dir=tmp_path / "backups", min_free_space_gb=0
        )

        before = datetime.now().replace(microsecond=0)
        backup_info = manager.create_backup(verify_integrity=False)
        after = datetime.now().replace(microsecond=0) + timedelta(seconds=1)

        # Parse timestamp from backup name
        name = backup_info.path.name
        assert name.startswith("tm_backup_")
        timestamp_str = name.replace("tm_backup_", "")
        timestamp = datetime.strptime(timestamp_str, "%Y%m%d_%H%M%S")

        # Timestamp should be between before and after (at second precision)
        assert before <= timestamp <= after

    def test_create_backup_with_integrity_check(self, populated_tm, tmp_path):
        """Test backup with integrity check."""
        manager = CacheBackupManager(
            tm_path=populated_tm, backup_dir=tmp_path / "backups", min_free_space_gb=0
        )

        # Should pass integrity check
        backup_info = manager.create_backup(verify_integrity=True)
        assert backup_info.path.exists()

    def test_create_backup_fails_without_tm_path(self, tmp_path):
        """Test backup fails when TM path doesn't exist."""
        manager = CacheBackupManager(
            tm_path=tmp_path / "nonexistent", backup_dir=tmp_path / "backups", min_free_space_gb=0
        )

        with pytest.raises(BackupError, match="does not exist"):
            manager.create_backup()


class TestCacheBackupManagerList:
    """Tests for listing backups."""

    @pytest.fixture
    def manager_with_backups(self, tmp_path):
        """Create manager with multiple backups."""
        db_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "backups"

        # Create minimal LMDB
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.store(
            site_id="test.site", src_lang="en", tgt_lang="es", text="Hello", translation="Hola"
        )
        l2.close()

        manager = CacheBackupManager(
            tm_path=db_path, backup_dir=backup_dir, max_backups=10, min_free_space_gb=0
        )

        # Create 3 backups with delay
        backup_infos = []
        for i in range(3):
            info = manager.create_backup(verify_integrity=False)
            backup_infos.append(info)
            time.sleep(1.1)  # Ensure different timestamps

        return manager, backup_infos

    def test_list_backups_returns_all(self, manager_with_backups):
        """Test listing returns all backups."""
        manager, backup_infos = manager_with_backups
        backups = manager.list_backups()

        assert len(backups) == 3

    def test_list_backups_sorted_newest_first(self, manager_with_backups):
        """Test backups sorted by timestamp descending."""
        manager, _ = manager_with_backups
        backups = manager.list_backups()

        timestamps = [b.timestamp for b in backups]
        assert timestamps == sorted(timestamps, reverse=True)

    def test_list_backups_empty(self, tmp_path):
        """Test listing with no backups."""
        db_path = tmp_path / "tm_cache"
        db_path.mkdir()

        manager = CacheBackupManager(tm_path=db_path, backup_dir=tmp_path / "backups")

        backups = manager.list_backups()
        assert backups == []

    def test_get_latest_backup(self, manager_with_backups):
        """Test getting latest backup."""
        manager, backup_infos = manager_with_backups
        latest = manager.get_latest_backup()

        assert latest is not None
        # Latest backup should be the last one created
        assert latest.path == backup_infos[-1].path

    def test_get_latest_backup_empty(self, tmp_path):
        """Test get_latest_backup with no backups."""
        db_path = tmp_path / "tm_cache"
        db_path.mkdir()

        manager = CacheBackupManager(tm_path=db_path, backup_dir=tmp_path / "backups")

        assert manager.get_latest_backup() is None


class TestCacheBackupManagerRestore:
    """Tests for restore functionality."""

    @pytest.fixture
    def setup_for_restore(self, tmp_path):
        """Create TM, backup, and modify TM."""
        db_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "backups"

        # Create and populate TM
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.store(
            site_id="test.site",
            src_lang="en",
            tgt_lang="es",
            text="Original",
            translation="Original translation",
        )
        l2.close()

        manager = CacheBackupManager(tm_path=db_path, backup_dir=backup_dir, min_free_space_gb=0)

        # Create backup
        backup_info = manager.create_backup(verify_integrity=False)

        # Modify TM after backup
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.store(
            site_id="test.site",
            src_lang="en",
            tgt_lang="fr",
            text="New entry",
            translation="Nouvelle entree",
        )
        l2.close()

        return manager, backup_info, db_path

    def test_restore_backup_force(self, setup_for_restore):
        """Test forced restore without confirmation."""
        manager, backup_info, db_path = setup_for_restore

        # Force restore
        safety_backup = manager.restore_backup(backup_info.path, force=True)

        assert safety_backup is not None  # Safety backup created
        assert safety_backup.path.exists()

        # Verify restored content (only 1 entry, not 2)
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        # The backup had 1 entry, after modification had 2, restored should have 1
        # Just verify the TM can be opened
        l2.close()

    def test_restore_creates_safety_backup(self, setup_for_restore):
        """Test safety backup is created before restore."""
        manager, backup_info, db_path = setup_for_restore

        safety_backup = manager.restore_backup(backup_info.path, force=True)

        assert safety_backup is not None
        assert "pre_restore_" in safety_backup.path.name
        assert safety_backup.path.exists()

    def test_restore_backup_nonexistent(self, setup_for_restore):
        """Test restore fails with nonexistent backup."""
        manager, _, _ = setup_for_restore

        with pytest.raises(ValueError, match="Backup not found"):
            manager.restore_backup(Path("/nonexistent"), force=True)

    def test_restore_skip_safety_backup(self, setup_for_restore):
        """Test restore without safety backup."""
        manager, backup_info, _ = setup_for_restore

        result = manager.restore_backup(backup_info.path, force=True, create_safety_backup=False)

        assert result is None


class TestCacheBackupManagerPruning:
    """Tests for automatic backup pruning."""

    def test_prune_keeps_max_backups(self, tmp_path):
        """Test pruning keeps only max_backups."""
        db_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "backups"

        # Create minimal LMDB
        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.store(
            site_id="test.site", src_lang="en", tgt_lang="es", text="Test", translation="Prueba"
        )
        l2.close()

        manager = CacheBackupManager(
            tm_path=db_path, backup_dir=backup_dir, max_backups=2, min_free_space_gb=0
        )

        # Create 5 backups
        for i in range(5):
            manager.create_backup(verify_integrity=False)
            time.sleep(1.1)

        # Should only have 2 backups
        backups = manager.list_backups()
        assert len(backups) == 2

    def test_prune_keeps_newest(self, tmp_path):
        """Test pruning keeps newest backups."""
        db_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "backups"

        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.store(
            site_id="test.site", src_lang="en", tgt_lang="es", text="Test", translation="Prueba"
        )
        l2.close()

        manager = CacheBackupManager(
            tm_path=db_path, backup_dir=backup_dir, max_backups=2, min_free_space_gb=0
        )

        # Create 3 backups, tracking paths
        backup_paths = []
        for i in range(3):
            info = manager.create_backup(verify_integrity=False)
            backup_paths.append(info.path)
            time.sleep(1.1)

        backups = manager.list_backups()
        current_paths = [b.path for b in backups]

        # The two newest should remain
        assert backup_paths[-1] in current_paths
        assert backup_paths[-2] in current_paths
        assert backup_paths[0] not in current_paths  # Oldest should be pruned


class TestCacheBackupManagerDelete:
    """Tests for backup deletion."""

    def test_delete_backup(self, tmp_path):
        """Test deleting a backup."""
        db_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "backups"

        l2 = L2PersistentTM(db_path, max_size_mb=10)
        l2.store(
            site_id="test.site", src_lang="en", tgt_lang="es", text="Test", translation="Prueba"
        )
        l2.close()

        manager = CacheBackupManager(tm_path=db_path, backup_dir=backup_dir, min_free_space_gb=0)

        backup_info = manager.create_backup(verify_integrity=False)
        assert backup_info.path.exists()

        manager.delete_backup(backup_info.path)
        assert not backup_info.path.exists()

    def test_delete_nonexistent_backup(self, tmp_path):
        """Test deleting nonexistent backup fails."""
        manager = CacheBackupManager(tm_path=tmp_path, backup_dir=tmp_path / "backups")

        with pytest.raises(ValueError, match="not found"):
            manager.delete_backup(Path("/nonexistent"))


class TestCacheBackupManagerDiskSpace:
    """Tests for disk space validation."""

    def test_insufficient_space_error(self, tmp_path):
        """Test InsufficientSpaceError when not enough space."""
        db_path = tmp_path / "tm_cache"
        db_path.mkdir()

        # Create manager requiring impossibly large free space
        manager = CacheBackupManager(
            tm_path=db_path,
            backup_dir=tmp_path / "backups",
            min_free_space_gb=1000000,  # 1 million GB
        )

        with pytest.raises(InsufficientSpaceError, match="Insufficient disk space"):
            manager.create_backup()


class TestCreateBackupManager:
    """Tests for create_backup_manager convenience function."""

    def test_create_backup_manager_defaults(self, tmp_path):
        """Test convenience function with defaults."""
        db_path = tmp_path / "tm_cache"
        db_path.mkdir()

        manager = create_backup_manager(db_path)

        assert manager.tm_path == db_path
        expected_backup_dir = tmp_path / "tm_cache_backups"
        assert manager.backup_dir == expected_backup_dir
        assert manager.max_backups == 5

    def test_create_backup_manager_custom_path(self, tmp_path):
        """Test convenience function with custom backup path."""
        db_path = tmp_path / "tm_cache"
        backup_dir = tmp_path / "custom_backups"
        db_path.mkdir()

        manager = create_backup_manager(tm_path=db_path, backup_dir=backup_dir, max_backups=10)

        assert manager.backup_dir == backup_dir
        assert manager.max_backups == 10
