"""Unit tests for force_unlock() method."""

import json
import os
from pathlib import Path

import pytest

from src.utils.file_lock import FileLock, LockError


@pytest.fixture
def lock_file(tmp_path):
    """Provide temporary lock file path."""
    return tmp_path / "test.lock"


def test_force_unlock_dead_process(lock_file):
    """Test force unlock with dead process."""
    # Create lock with dead PID
    metadata = {
        "pid": 999999,
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata))

    lock = FileLock(lock_file)
    result = lock.force_unlock(check_pid=True)

    assert result is True
    assert not lock_file.exists()


def test_force_unlock_live_process_refuses(lock_file):
    """Test force unlock refuses if process alive."""
    # Create lock with current process (definitely alive)
    metadata = {
        "pid": os.getpid(),
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata))

    lock = FileLock(lock_file)
    result = lock.force_unlock(check_pid=True)

    # Should refuse
    assert result is False
    assert lock_file.exists()  # Lock still there


def test_force_unlock_live_process_override(lock_file):
    """Test force unlock with check_pid=False overrides safety."""
    # Create lock with current process
    metadata = {
        "pid": os.getpid(),
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata))

    lock = FileLock(lock_file)
    result = lock.force_unlock(check_pid=False)

    # Should force unlock even with live process
    assert result is True
    assert not lock_file.exists()


def test_force_unlock_nonexistent_file(lock_file):
    """Test force unlock when lock file doesn't exist."""
    # File doesn't exist
    assert not lock_file.exists()

    lock = FileLock(lock_file)
    result = lock.force_unlock(check_pid=True)

    # Should return True (no-op, but successful)
    assert result is True


def test_force_unlock_permission_error_on_read(lock_file):
    """Test force unlock when cannot read PID (PermissionError)."""
    from unittest.mock import patch

    # Create lock file
    lock_file.write_text("12345")

    lock = FileLock(lock_file)

    # Mock open to raise PermissionError on read
    with patch("builtins.open", side_effect=PermissionError("Access denied")):
        result = lock.force_unlock(check_pid=True)

    # Should proceed with unlock despite PermissionError
    # (assumes external holder, allow removal)
    assert result is True


def test_force_unlock_legacy_text_format(lock_file):
    """Test force unlock with legacy text PID format."""
    # Legacy format: just PID
    lock_file.write_text("999999")

    lock = FileLock(lock_file)
    result = lock.force_unlock(check_pid=True)

    assert result is True
    assert not lock_file.exists()


def test_force_unlock_legacy_text_live_process(lock_file):
    """Test force unlock refuses with legacy format and live PID."""
    # Legacy format with current process
    lock_file.write_text(str(os.getpid()))

    lock = FileLock(lock_file)
    result = lock.force_unlock(check_pid=True)

    # Should refuse
    assert result is False
    assert lock_file.exists()


def test_force_unlock_removal_fails(lock_file):
    """Test force unlock raises if removal fails."""
    from unittest.mock import patch

    # Create dead lock
    lock_file.write_text("999999")

    lock = FileLock(lock_file)

    # Mock unlink to fail
    with patch.object(Path, "unlink", side_effect=OSError("Permission denied")):
        with pytest.raises(LockError, match="Failed to remove lock file"):
            lock.force_unlock(check_pid=True)
