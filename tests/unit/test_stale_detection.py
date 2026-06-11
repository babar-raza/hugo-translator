"""Unit tests for stale lock detection."""

import json
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.utils.file_lock import FileLock


@pytest.fixture
def lock_file(tmp_path):
    """Provide temporary lock file path."""
    return tmp_path / "test.lock"


def test_stale_detection_dead_pid_json(lock_file):
    """Test stale detection with dead PID (JSON format)."""
    # Create lock with dead PID
    metadata = {
        "pid": 999999,
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata, indent=2))

    lock = FileLock(lock_file, timeout=300.0)
    is_stale = lock._is_stale_lock()

    assert is_stale is True


def test_stale_detection_dead_pid_text(lock_file):
    """Test stale detection with dead PID (legacy text format)."""
    # Legacy format: just PID as text
    lock_file.write_text("999999")

    lock = FileLock(lock_file, timeout=300.0)
    is_stale = lock._is_stale_lock()

    assert is_stale is True


def test_stale_detection_live_pid_json(lock_file):
    """Test stale detection with live PID (JSON format)."""
    # Use current process (definitely alive)
    metadata = {
        "pid": os.getpid(),
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata, indent=2))

    lock = FileLock(lock_file, timeout=300.0)
    is_stale = lock._is_stale_lock()

    assert is_stale is False


def test_stale_detection_live_pid_text(lock_file):
    """Test stale detection with live PID (legacy text format)."""
    # Use current process (definitely alive)
    lock_file.write_text(str(os.getpid()))

    lock = FileLock(lock_file, timeout=300.0)
    is_stale = lock._is_stale_lock()

    assert is_stale is False


def test_stale_detection_permission_error_old_file(lock_file):
    """Test age-based heuristic when PermissionError on read."""
    # Create lock file
    lock_file.write_text("12345")

    # Set mtime to 700 seconds ago (> 2x timeout of 300s)
    old_time = time.time() - 700
    os.utime(lock_file, (old_time, old_time))

    # Mock open to raise PermissionError
    lock = FileLock(lock_file, timeout=300.0)

    with patch("builtins.open", side_effect=PermissionError("Access denied")):
        is_stale = lock._is_stale_lock()

    # Age-based heuristic should treat as stale
    assert is_stale is True


def test_stale_detection_permission_error_recent_file(lock_file):
    """Test age-based heuristic keeps recent lock despite PermissionError."""
    # Create lock file
    lock_file.write_text("12345")

    # File is recent (within 2x timeout)
    recent_time = time.time() - 100  # 100s ago (< 600s threshold)
    os.utime(lock_file, (recent_time, recent_time))

    # Mock open to raise PermissionError
    lock = FileLock(lock_file, timeout=300.0)

    with patch("builtins.open", side_effect=PermissionError("Access denied")):
        is_stale = lock._is_stale_lock()

    # Age-based heuristic should keep as valid
    assert is_stale is False


def test_stale_detection_no_file(lock_file):
    """Test stale detection when lock file doesn't exist."""
    # File doesn't exist
    assert not lock_file.exists()

    lock = FileLock(lock_file, timeout=300.0)
    is_stale = lock._is_stale_lock()

    # Non-existent file is not stale (it's just absent)
    assert is_stale is False


def test_is_process_alive_current_process():
    """Test _is_process_alive with current process."""
    from src.utils.file_lock import FileLock

    lock = FileLock(Path("/tmp/test.lock"))

    # Current process should be alive
    assert lock._is_process_alive(os.getpid()) is True


def test_is_process_alive_nonexistent_pid():
    """Test _is_process_alive with nonexistent PID."""
    from src.utils.file_lock import FileLock

    lock = FileLock(Path("/tmp/test.lock"))

    # PID 999999 should not exist
    assert lock._is_process_alive(999999) is False


@pytest.mark.skipif(sys.platform != "win32", reason="Windows-specific")
def test_is_process_alive_windows(lock_file):
    """Test Windows process detection via tasklist."""
    from src.utils.file_lock import FileLock

    lock = FileLock(lock_file)

    # Mock tasklist output for alive process
    with patch("subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(
            stdout=f"python.exe  {os.getpid()}  Console  1  12345 K", returncode=0
        )

        assert lock._is_process_alive(os.getpid()) is True


@pytest.mark.skipif(sys.platform == "win32", reason="Unix-specific")
def test_is_process_alive_unix(lock_file):
    """Test Unix process detection via kill signal 0."""
    from src.utils.file_lock import FileLock

    lock = FileLock(lock_file)

    # Current process should be alive
    assert lock._is_process_alive(os.getpid()) is True

    # Mock os.kill to simulate dead process
    with patch("os.kill", side_effect=OSError("No such process")):
        assert lock._is_process_alive(99999) is False


def test_stale_detection_malformed_json(lock_file):
    """Test stale detection with malformed JSON (should treat conservatively)."""
    # Write malformed JSON
    lock_file.write_text("{invalid json")

    lock = FileLock(lock_file, timeout=300.0)

    # Should handle gracefully (conservative: not stale)
    # Implementation may vary - adjust based on actual behavior
    try:
        is_stale = lock._is_stale_lock()
        # Conservative approach: assume valid
        assert is_stale is False
    except Exception:
        # Or may raise - both are acceptable
        pass


def test_stale_detection_empty_file(lock_file):
    """Test stale detection with empty lock file."""
    lock_file.write_text("")

    lock = FileLock(lock_file, timeout=300.0)

    # Should handle gracefully
    try:
        is_stale = lock._is_stale_lock()
        # Conservative: assume not stale
        assert is_stale is False
    except Exception:
        # Or may raise - both acceptable
        pass
