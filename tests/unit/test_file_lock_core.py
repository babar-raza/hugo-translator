"""Unit tests for FileLock class core functionality."""
import os
import sys
import time
from pathlib import Path
from unittest.mock import patch, mock_open, MagicMock
import pytest

from src.utils.file_lock import FileLock, LockError


@pytest.fixture
def lock_file(tmp_path):
    """Provide temporary lock file path."""
    return tmp_path / "test.lock"


def test_acquire_release_basic(lock_file):
    """Test basic lock acquisition and release."""
    lock = FileLock(lock_file, timeout=5.0)

    # Acquire
    assert lock.acquire(blocking=True) is True
    assert lock._locked is True
    assert lock_file.exists()

    # Release
    lock.release()
    assert lock._locked is False
    assert not lock_file.exists()


def test_acquire_twice_same_instance(lock_file):
    """Test acquiring lock twice on same instance is idempotent."""
    lock = FileLock(lock_file, timeout=5.0)

    # First acquire
    assert lock.acquire(blocking=True) is True

    # Second acquire (should return True immediately)
    assert lock.acquire(blocking=True) is True
    assert lock._locked is True

    lock.release()


def test_acquire_timeout_expires(lock_file):
    """Test lock acquisition timeout."""
    # Create competing lock
    lock1 = FileLock(lock_file, timeout=1.0)
    lock1.acquire(blocking=True)

    # Try to acquire with short timeout
    lock2 = FileLock(lock_file, timeout=1.0)

    start = time.time()
    with pytest.raises(LockError, match="Failed to acquire lock"):
        lock2.acquire(blocking=True)
    duration = time.time() - start

    # Should timeout around 1 second
    assert 0.8 < duration < 2.0

    lock1.release()


def test_acquire_non_blocking_fails_immediately(lock_file):
    """Test non-blocking acquire fails immediately if locked."""
    lock1 = FileLock(lock_file)
    lock1.acquire(blocking=True)

    lock2 = FileLock(lock_file)

    # Non-blocking should return False immediately
    start = time.time()
    result = lock2.acquire(blocking=False)
    duration = time.time() - start

    assert result is False
    assert duration < 0.5  # Should be instant

    lock1.release()


def test_json_metadata_written(lock_file):
    """Test lock file contains JSON metadata."""
    import json

    lock = FileLock(lock_file, timeout=5.0)
    lock.acquire(blocking=True)

    # Read lock file
    with open(lock_file, 'r') as f:
        content = f.read()

    # Should be valid JSON
    data = json.loads(content)

    # Verify metadata fields
    assert 'pid' in data
    assert 'hostname' in data
    assert 'created' in data
    assert 'format_version' in data

    assert data['pid'] == os.getpid()

    lock.release()


def test_context_manager(lock_file):
    """Test FileLock works as context manager."""
    lock = FileLock(lock_file, timeout=5.0)

    assert not lock._locked

    with lock:
        assert lock._locked
        assert lock_file.exists()

    # Should auto-release
    assert not lock._locked
    assert not lock_file.exists()


def test_context_manager_exception_cleanup(lock_file):
    """Test lock released even if exception in context."""
    lock = FileLock(lock_file, timeout=5.0)

    with pytest.raises(ValueError):
        with lock:
            assert lock._locked
            raise ValueError("Test exception")

    # Lock should still be released
    assert not lock._locked
    assert not lock_file.exists()


def test_release_without_acquire(lock_file):
    """Test releasing without acquiring is safe (no-op)."""
    lock = FileLock(lock_file)

    # Should not raise
    lock.release()

    assert not lock._locked


def test_multiple_lock_instances_same_file(lock_file):
    """Test multiple FileLock instances for same file."""
    lock1 = FileLock(lock_file, timeout=1.0)
    lock2 = FileLock(lock_file, timeout=1.0)

    # lock1 acquires
    assert lock1.acquire(blocking=True) is True

    # lock2 should timeout
    with pytest.raises(LockError):
        lock2.acquire(blocking=True)

    # Release lock1
    lock1.release()

    # Now lock2 can acquire
    assert lock2.acquire(blocking=True) is True

    lock2.release()


@pytest.mark.skipif(sys.platform != 'win32', reason="Windows-specific test")
def test_windows_msvcrt_locking(lock_file):
    """Test Windows msvcrt.locking is called."""
    with patch('msvcrt.locking') as mock_locking:
        lock = FileLock(lock_file, timeout=5.0)

        lock.acquire(blocking=True)

        # Verify locking was called
        assert mock_locking.called

        lock.release()


@pytest.mark.skipif(sys.platform == 'win32', reason="Unix-specific test")
def test_unix_fcntl_flock(lock_file):
    """Test Unix fcntl.flock is called."""
    with patch('fcntl.flock') as mock_flock:
        lock = FileLock(lock_file, timeout=5.0)

        lock.acquire(blocking=True)

        # Verify flock was called
        assert mock_flock.called

        lock.release()


def test_lock_file_permissions(lock_file):
    """Test lock file created with correct permissions."""
    lock = FileLock(lock_file, timeout=5.0)
    lock.acquire(blocking=True)

    # Lock file should exist and be readable
    assert lock_file.exists()
    assert lock_file.is_file()

    # Should be readable
    with open(lock_file, 'r') as f:
        content = f.read()
        assert len(content) > 0

    lock.release()


def test_concurrent_acquire_same_process(lock_file):
    """Test concurrent acquire attempts in same process."""
    import threading

    lock1 = FileLock(lock_file, timeout=5.0)
    lock2 = FileLock(lock_file, timeout=2.0)

    results = []

    def acquire_lock1():
        try:
            lock1.acquire(blocking=True)
            time.sleep(0.5)
            lock1.release()
            results.append("lock1_ok")
        except Exception as e:
            results.append(f"lock1_error: {e}")

    def acquire_lock2():
        time.sleep(0.1)  # Let lock1 acquire first
        try:
            lock2.acquire(blocking=True)
            lock2.release()
            results.append("lock2_ok")
        except LockError:
            results.append("lock2_timeout")

    t1 = threading.Thread(target=acquire_lock1)
    t2 = threading.Thread(target=acquire_lock2)

    t1.start()
    t2.start()

    t1.join(timeout=10)
    t2.join(timeout=10)

    # lock1 should succeed, lock2 should timeout
    assert "lock1_ok" in results
    assert "lock2_timeout" in results
