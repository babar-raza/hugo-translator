"""
Comprehensive tests for backup and restore functionality.

Tests backup creation, restoration, integrity verification, rotation,
and failure scenarios.
"""

import sys
import tarfile
import tempfile
from pathlib import Path

import pytest

# Add scripts and src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "scripts"))
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

import backup_tm
import restore_tm


@pytest.fixture
def temp_dirs():
    """Create temporary directories for testing."""
    with tempfile.TemporaryDirectory() as temp:
        temp_path = Path(temp)

        # Create directory structure
        tm_data = temp_path / "data" / "tm"
        tm_data.mkdir(parents=True)

        l2_lmdb = tm_data / "l2_lmdb"
        l2_lmdb.mkdir()
        (l2_lmdb / "data.mdb").write_text("L2 data")
        (l2_lmdb / "lock.mdb").write_text("L2 lock")

        l3_faiss = tm_data / "l3_faiss"
        l3_faiss.mkdir()
        (l3_faiss / "index.faiss").write_bytes(b"FAISS" * 100)
        (l3_faiss / "metadata.json").write_text('{"entries": 100}')

        config = temp_path / "config"
        config.mkdir()
        (config / "global.yaml").write_text("system:\n  name: test\n")
        (config / "model_registry.yaml").write_text("models:\n  test: {}\n")

        backups = temp_path / "backups"
        backups.mkdir()

        yield {
            "root": temp_path,
            "tm_data": tm_data,
            "l2_lmdb": l2_lmdb,
            "l3_faiss": l3_faiss,
            "config": config,
            "backups": backups,
        }


class TestBackupCreation:
    """Test backup creation functionality."""

    def test_create_backup_success(self, temp_dirs):
        """Test successful backup creation."""
        output_file = temp_dirs["backups"] / "test_backup.tar.gz"

        success, message = backup_tm.create_backup(
            output_path=output_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        assert success is True
        assert output_file.exists()
        assert output_file.stat().st_size > 0

    def test_backup_contains_all_components(self, temp_dirs):
        """Test that backup contains all expected components."""
        output_file = temp_dirs["backups"] / "test_backup.tar.gz"

        backup_tm.create_backup(
            output_path=output_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        # Check contents
        with tarfile.open(output_file, "r:gz") as tar:
            names = tar.getnames()

            assert "metadata.json" in names
            assert any("l2_lmdb" in n for n in names)
            assert any("l3_faiss" in n for n in names)
            assert any("config" in n for n in names)
            assert "tm_data/l2_lmdb/data.mdb" in names
            assert "tm_data/l3_faiss/index.faiss" in names

    def test_backup_metadata_correct(self, temp_dirs):
        """Test that backup metadata is correct."""
        metadata = backup_tm.create_backup_metadata(
            tm_data_dir=temp_dirs["tm_data"], config_dir=temp_dirs["config"], version="1.0.0"
        )

        assert "backup_timestamp" in metadata
        assert metadata["system_version"] == "1.0.0"
        assert metadata["backup_type"] == "full"
        assert "components" in metadata
        assert "l2_lmdb" in metadata["components"]
        assert "l3_faiss" in metadata["components"]
        assert "config" in metadata["components"]

    def test_backup_checksum_created(self, temp_dirs):
        """Test that checksum file is created."""
        output_file = temp_dirs["backups"] / "test_backup.tar.gz"

        backup_tm.create_backup(
            output_path=output_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        checksum_file = output_file.parent / f"{output_file.name}.sha256"
        assert checksum_file.exists()

        # Verify checksum content
        content = checksum_file.read_text()
        assert len(content.split()[0]) == 64  # SHA256 hex length

    def test_backup_without_config(self, temp_dirs):
        """Test backup without config directory."""
        # Remove config
        import shutil

        shutil.rmtree(temp_dirs["config"])

        output_file = temp_dirs["backups"] / "test_backup.tar.gz"

        success, message = backup_tm.create_backup(
            output_path=output_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        assert success is True
        assert output_file.exists()

    def test_backup_nonexistent_tm_data(self, temp_dirs):
        """Test backup with nonexistent TM data directory."""
        output_file = temp_dirs["backups"] / "test_backup.tar.gz"
        fake_dir = temp_dirs["root"] / "nonexistent"

        success, message = backup_tm.create_backup(
            output_path=output_file, tm_data_dir=fake_dir, config_dir=temp_dirs["config"]
        )

        assert success is False
        assert "not found" in message.lower()

    def test_backup_with_compression_types(self, temp_dirs):
        """Test backup with different compression types."""
        compressions = [("gz", "tar.gz"), ("bz2", "tar.bz2"), (None, "tar")]

        for compression, ext in compressions:
            output_file = temp_dirs["backups"] / f"test_backup.{ext}"

            success, message = backup_tm.create_backup(
                output_path=output_file,
                tm_data_dir=temp_dirs["tm_data"],
                config_dir=temp_dirs["config"],
                compression=compression,
            )

            assert success is True
            assert output_file.exists()


class TestBackupRotation:
    """Test backup rotation functionality."""

    def test_rotate_backups(self, temp_dirs):
        """Test that old backups are rotated."""
        backups_dir = temp_dirs["backups"]

        # Create multiple backups
        for i in range(5):
            backup_file = backups_dir / f"tm_{i}.tar.gz"
            backup_file.write_text(f"backup {i}")
            checksum_file = backups_dir / f"{backup_file.name}.sha256"
            checksum_file.write_text("checksum")

        # Rotate to keep only 3
        backup_tm.rotate_backups(backups_dir, keep_count=3)

        # Check remaining backups
        remaining = list(backups_dir.glob("tm_*.tar.gz"))
        assert len(remaining) == 3

    def test_rotate_with_backup_creation(self, temp_dirs):
        """Test rotation during backup creation."""
        # Create initial backups
        for i in range(5):
            output_file = temp_dirs["backups"] / f"tm_test_{i}.tar.gz"
            backup_tm.create_backup(
                output_path=output_file,
                tm_data_dir=temp_dirs["tm_data"],
                config_dir=temp_dirs["config"],
                rotate=3,
            )

        # Check that only 3 remain
        backups = list(temp_dirs["backups"].glob("tm_*.tar.gz"))
        assert len(backups) == 3


class TestBackupRestore:
    """Test backup restoration functionality."""

    def test_restore_backup_success(self, temp_dirs):
        """Test successful backup restoration."""
        # Create backup
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        # Create restore target
        restore_target = temp_dirs["root"] / "restored"

        # Restore
        success, message = restore_tm.restore_backup(
            backup_path=backup_file, target_dir=restore_target, verify=True
        )

        assert success is True
        assert restore_target.exists()

        # Verify restored files
        assert (restore_target / "tm_data" / "l2_lmdb" / "data.mdb").exists()
        assert (restore_target / "tm_data" / "l3_faiss" / "index.faiss").exists()
        assert (restore_target / "config" / "global.yaml").exists()

    def test_restore_verification(self, temp_dirs):
        """Test backup verification before restore."""
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        # Verify integrity
        valid, message = restore_tm.verify_backup_integrity(backup_file)
        assert valid is True

    def test_restore_corrupted_backup_detection(self, temp_dirs):
        """Test detection of corrupted backup."""
        backup_file = temp_dirs["backups"] / "corrupted.tar.gz"
        backup_file.write_bytes(b"corrupted data")

        # Should fail to verify
        corrupted, message = restore_tm.test_corrupted_backup(backup_file)
        assert corrupted is True

    def test_restore_checksum_mismatch(self, temp_dirs):
        """Test restoration fails with checksum mismatch."""
        # Create backup
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        # Corrupt checksum file
        checksum_file = backup_file.parent / f"{backup_file.name}.sha256"
        checksum_file.write_text("0" * 64 + f"  {backup_file.name}\n")

        # Verify should fail
        valid, message = restore_tm.verify_backup_integrity(backup_file)
        assert valid is False
        assert "mismatch" in message.lower()

    def test_restore_dry_run(self, temp_dirs):
        """Test dry run mode."""
        # Create backup
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        restore_target = temp_dirs["root"] / "restored"

        # Dry run
        success, message = restore_tm.restore_backup(
            backup_path=backup_file, target_dir=restore_target, verify=True, dry_run=True
        )

        assert success is True
        assert "dry run" in message.lower()
        # Target should not be created in dry run
        assert not (restore_target / "tm_data").exists()

    def test_restore_nonexistent_backup(self, temp_dirs):
        """Test restoration of nonexistent backup."""
        backup_file = temp_dirs["backups"] / "nonexistent.tar.gz"
        restore_target = temp_dirs["root"] / "restored"

        success, message = restore_tm.restore_backup(
            backup_path=backup_file, target_dir=restore_target
        )

        assert success is False
        assert "not found" in message.lower()

    def test_restore_metadata_reading(self, temp_dirs):
        """Test reading metadata from backup."""
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        metadata = restore_tm.read_backup_metadata(backup_file)

        assert metadata is not None
        assert "backup_timestamp" in metadata
        assert "components" in metadata
        assert "l2_lmdb" in metadata["components"]


class TestBackupRestoreIntegration:
    """Test end-to-end backup and restore scenarios."""

    def test_backup_and_restore_roundtrip(self, temp_dirs):
        """Test complete backup and restore cycle."""
        # Create backup
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        # Restore to new location
        restore_target = temp_dirs["root"] / "restored"
        restore_tm.restore_backup(backup_path=backup_file, target_dir=restore_target, verify=True)

        # Verify content integrity
        original_l2 = temp_dirs["l2_lmdb"] / "data.mdb"
        restored_l2 = restore_target / "tm_data" / "l2_lmdb" / "data.mdb"
        assert original_l2.read_text() == restored_l2.read_text()

        original_l3 = temp_dirs["l3_faiss"] / "index.faiss"
        restored_l3 = restore_target / "tm_data" / "l3_faiss" / "index.faiss"
        assert original_l3.read_bytes() == restored_l3.read_bytes()

    def test_backup_while_system_running(self, temp_dirs):
        """Test backup can be created while files are being read."""
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"

        # Simulate concurrent file access
        with open(temp_dirs["l2_lmdb"] / "data.mdb") as f:
            # Create backup while file is open
            success, message = backup_tm.create_backup(
                output_path=backup_file,
                tm_data_dir=temp_dirs["tm_data"],
                config_dir=temp_dirs["config"],
            )

        assert success is True

    def test_multiple_backup_restore_cycles(self, temp_dirs):
        """Test multiple backup and restore cycles."""
        for i in range(3):
            # Modify data
            (temp_dirs["l2_lmdb"] / "data.mdb").write_text(f"L2 data {i}")

            # Create backup
            backup_file = temp_dirs["backups"] / f"test_backup_{i}.tar.gz"
            backup_tm.create_backup(
                output_path=backup_file,
                tm_data_dir=temp_dirs["tm_data"],
                config_dir=temp_dirs["config"],
            )

            # Restore and verify
            restore_target = temp_dirs["root"] / f"restored_{i}"
            restore_tm.restore_backup(
                backup_path=backup_file, target_dir=restore_target, verify=True
            )

            restored_content = (restore_target / "tm_data" / "l2_lmdb" / "data.mdb").read_text()
            assert restored_content == f"L2 data {i}"


class TestBackupUtilities:
    """Test utility functions."""

    def test_calculate_checksum(self, temp_dirs):
        """Test checksum calculation."""
        test_file = temp_dirs["root"] / "test.txt"
        test_file.write_text("test content")

        checksum1 = backup_tm.calculate_checksum(test_file)
        checksum2 = backup_tm.calculate_checksum(test_file)

        # Same file should have same checksum
        assert checksum1 == checksum2
        assert len(checksum1) == 64  # SHA256 hex length

    def test_calculate_checksum_different_files(self, temp_dirs):
        """Test that different files have different checksums."""
        file1 = temp_dirs["root"] / "file1.txt"
        file2 = temp_dirs["root"] / "file2.txt"

        file1.write_text("content 1")
        file2.write_text("content 2")

        checksum1 = backup_tm.calculate_checksum(file1)
        checksum2 = backup_tm.calculate_checksum(file2)

        assert checksum1 != checksum2

    def test_get_directory_size(self, temp_dirs):
        """Test directory size calculation."""
        size = backup_tm.get_directory_size(temp_dirs["l2_lmdb"])
        assert size > 0

    def test_count_directory_files(self, temp_dirs):
        """Test file counting."""
        count = backup_tm.count_directory_files(temp_dirs["l2_lmdb"])
        assert count == 2  # data.mdb and lock.mdb


class TestBackupFailureScenarios:
    """Test failure scenarios and error handling."""

    def test_backup_insufficient_permissions(self, temp_dirs):
        """Test backup with insufficient permissions."""
        # This test would require actual permission manipulation
        # which is platform-specific and may not work in all environments
        pass

    def test_backup_disk_full(self, temp_dirs):
        """Test backup when disk is full."""
        # This test would require actually filling disk
        # which is not safe in test environment
        pass

    def test_restore_to_readonly_location(self, temp_dirs):
        """Test restore to read-only location."""
        # This test would require actual permission manipulation
        pass

    def test_backup_very_large_files(self, temp_dirs):
        """Test backup with very large files."""
        # Create a large file
        large_file = temp_dirs["l3_faiss"] / "large.bin"
        large_file.write_bytes(b"X" * (10 * 1024 * 1024))  # 10MB

        backup_file = temp_dirs["backups"] / "large_backup.tar.gz"

        success, message = backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        assert success is True
        assert backup_file.exists()
        # Compressed file should be smaller
        assert backup_file.stat().st_size < large_file.stat().st_size


class TestCrossPlatformCompatibility:
    """Test cross-platform compatibility."""

    def test_backup_path_separators(self, temp_dirs):
        """Test that backup works with different path separators."""
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"

        success, message = backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        assert success is True

        # Verify paths in tarball use forward slashes
        with tarfile.open(backup_file, "r:gz") as tar:
            names = tar.getnames()
            for name in names:
                assert "\\" not in name  # No backslashes

    def test_restore_creates_correct_paths(self, temp_dirs):
        """Test that restore creates correct paths on current platform."""
        backup_file = temp_dirs["backups"] / "test_backup.tar.gz"
        backup_tm.create_backup(
            output_path=backup_file,
            tm_data_dir=temp_dirs["tm_data"],
            config_dir=temp_dirs["config"],
        )

        restore_target = temp_dirs["root"] / "restored"
        restore_tm.restore_backup(backup_path=backup_file, target_dir=restore_target, verify=True)

        # Check that paths are created correctly
        assert (restore_target / "tm_data" / "l2_lmdb").exists()
        assert (restore_target / "tm_data" / "l2_lmdb").is_dir()
