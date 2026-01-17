"""
CONTRACT: specs/core_invariants.md

Verifies only one translation process per site is allowed at a time,
enforced by exclusive file lock.

INV-006 Core Invariant: File Locking Prevents Concurrent Translation

Key Guarantees:
1. Lock is exclusive (only one holder at a time)
2. Lock is blocking (wait up to timeout for lock release)
3. Lock is site-scoped (different sites can run concurrently)
4. Lock is file-based (works across processes)
5. Lock is released on completion (even on exception)
"""

import pytest
import os
import sys
import time
import tempfile
import threading
import multiprocessing
from pathlib import Path
from unittest.mock import Mock, patch

sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.file_lock import FileLock, LockError


# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def lock_dir(tmp_path):
    """Temporary directory for lock files."""
    lock_path = tmp_path / "locks"
    lock_path.mkdir()
    return lock_path


@pytest.fixture
def lock_file(lock_dir):
    """Path to a test lock file."""
    return lock_dir / "test-site.lock"


@pytest.fixture
def file_lock(lock_file):
    """FileLock instance with short timeout for testing."""
    return FileLock(lock_file, timeout=2.0, poll_interval=0.1)


# ==============================================================================
# INV-006: Exclusive Lock Tests
# ==============================================================================


@pytest.mark.contract
def test_lock_is_exclusive(lock_dir):
    """
    Verify only one process can hold lock at a time.

    CONTRACT: INV-006 - Lock is exclusive
    Evidence: src/utils/file_lock.py lines 203-208 (LOCK_EX | LOCK_NB)
    """
    lock_file = lock_dir / "exclusive.lock"
    lock1 = FileLock(lock_file, timeout=0)
    lock2 = FileLock(lock_file, timeout=0)

    # Acquire first lock
    result1 = lock1.acquire()
    assert result1 is True

    # Second lock should fail immediately (timeout=0)
    with pytest.raises(LockError):
        lock2.acquire()

    # Release first lock
    lock1.release()


@pytest.mark.contract
def test_lock_acquire_returns_true_on_success(file_lock):
    """
    Verify acquire returns True when lock obtained.

    CONTRACT: INV-006 - Successful acquisition
    Evidence: src/utils/file_lock.py line 222 (return True)
    """
    result = file_lock.acquire()
    assert result is True
    assert file_lock._locked is True

    file_lock.release()


@pytest.mark.contract
def test_lock_prevents_concurrent_access(lock_dir):
    """
    Verify second acquirer waits then times out.

    CONTRACT: INV-006 - Lock is blocking with timeout
    Evidence: src/utils/file_lock.py lines 246-255 (timeout check)
    """
    lock_file = lock_dir / "concurrent.lock"
    lock1 = FileLock(lock_file, timeout=300)
    lock2 = FileLock(lock_file, timeout=0.5, poll_interval=0.1)

    # First lock acquired
    lock1.acquire()

    # Second should timeout waiting
    start = time.time()
    with pytest.raises(LockError):
        lock2.acquire()
    elapsed = time.time() - start

    # Should have waited approximately 0.5 seconds
    assert elapsed >= 0.4

    lock1.release()


# ==============================================================================
# INV-006: Site-Scoped Lock Tests
# ==============================================================================


@pytest.mark.contract
def test_different_sites_can_lock_concurrently(lock_dir):
    """
    Verify different sites can hold locks simultaneously.

    CONTRACT: INV-006 - Lock is site-scoped
    Evidence: specs/core_invariants.md (different sites can run concurrently)
    """
    lock_file_a = lock_dir / "site-a.lock"
    lock_file_b = lock_dir / "site-b.lock"

    lock_a = FileLock(lock_file_a, timeout=0)
    lock_b = FileLock(lock_file_b, timeout=0)

    # Both should acquire successfully
    result_a = lock_a.acquire()
    result_b = lock_b.acquire()

    assert result_a is True
    assert result_b is True

    # Clean up
    lock_a.release()
    lock_b.release()


# ==============================================================================
# INV-006: Lock Release Tests
# ==============================================================================


@pytest.mark.contract
def test_lock_released_on_normal_exit(lock_dir):
    """
    Verify lock is released after work completes.

    CONTRACT: INV-006 - Lock released on completion
    Evidence: src/utils/file_lock.py lines 260-293 (release method)
    """
    lock_file = lock_dir / "release.lock"
    lock = FileLock(lock_file, timeout=0)

    # Acquire
    lock.acquire()
    assert lock._locked is True

    # Release
    lock.release()
    assert lock._locked is False

    # Another lock should now succeed
    lock2 = FileLock(lock_file, timeout=0)
    result = lock2.acquire()
    assert result is True
    lock2.release()


@pytest.mark.contract
def test_lock_released_via_context_manager(lock_dir):
    """
    Verify context manager releases lock on exit.

    CONTRACT: INV-006 - Lock released via context manager
    Evidence: src/utils/file_lock.py lines 458-466 (__enter__, __exit__)
    """
    lock_file = lock_dir / "context.lock"

    with FileLock(lock_file, timeout=0) as lock:
        assert lock._locked is True

    # After context exit, lock should be released
    # Another lock should succeed
    lock2 = FileLock(lock_file, timeout=0)
    result = lock2.acquire()
    assert result is True
    lock2.release()


@pytest.mark.contract
def test_lock_released_on_exception(lock_dir):
    """
    Verify lock is released even when exception occurs.

    CONTRACT: INV-006 - Lock MUST release even on exception
    Evidence: src/utils/file_lock.py lines 463-466 (context manager exit)
    """
    lock_file = lock_dir / "exception.lock"

    try:
        with FileLock(lock_file, timeout=0) as lock:
            assert lock._locked is True
            raise ValueError("Test exception")
    except ValueError:
        pass  # Expected

    # Lock should be released despite exception
    lock2 = FileLock(lock_file, timeout=0)
    result = lock2.acquire()
    assert result is True
    lock2.release()


# ==============================================================================
# INV-006: Lock File Content Tests
# ==============================================================================


@pytest.mark.contract
def test_lock_file_contains_metadata(lock_dir):
    """
    Verify lock file contains PID and hostname metadata.

    CONTRACT: INV-006 - Lock file is informative
    Evidence: src/utils/file_lock.py lines 210-218 (metadata write)

    Note: On Windows, exclusive byte-range locks prevent reading from ANY
    file handle while lock is held, so we verify via mocking the write call.
    """
    import json
    import sys

    lock_file = lock_dir / "metadata.lock"

    if sys.platform != 'win32':
        # On Unix, we can read the file with a separate handle
        file_lock = FileLock(lock_file, timeout=0)
        file_lock.acquire()

        assert lock_file.exists()
        content = lock_file.read_text()
        data = json.loads(content)

        # Verify metadata
        assert "pid" in data
        assert data["pid"] == os.getpid()
        assert "hostname" in data
        assert "created" in data

        file_lock.release()
    else:
        # On Windows, verify metadata structure via mock
        # This ensures the metadata dict is constructed correctly
        import socket
        from datetime import datetime

        written_data = []

        original_write = os.write
        def capture_write(fd, data):
            written_data.append(data)
            return original_write(fd, data)

        with patch('os.write', side_effect=capture_write):
            file_lock = FileLock(lock_file, timeout=0)
            file_lock.acquire()
            file_lock.release()

        # Verify the JSON metadata was written
        assert len(written_data) > 0, "No data written to lock file"
        metadata = json.loads(written_data[0].decode())

        assert "pid" in metadata
        assert metadata["pid"] == os.getpid()
        assert "hostname" in metadata
        assert "created" in metadata


# ==============================================================================
# INV-006: Non-Blocking Mode Tests
# ==============================================================================


@pytest.mark.contract
def test_non_blocking_acquire_returns_false(lock_dir):
    """
    Verify non-blocking mode returns False instead of waiting.

    CONTRACT: INV-006 - Non-blocking option
    Evidence: src/utils/file_lock.py lines 234-235 (blocking=False)
    """
    lock_file = lock_dir / "nonblock.lock"
    lock1 = FileLock(lock_file, timeout=0)
    lock2 = FileLock(lock_file, timeout=300)

    # First lock
    lock1.acquire()

    # Second lock non-blocking should return False immediately
    result = lock2.acquire(blocking=False)
    assert result is False

    lock1.release()


# ==============================================================================
# INV-006: Stale Lock Detection Tests
# ==============================================================================


@pytest.mark.contract
def test_stale_lock_detection_dead_process(lock_dir):
    """
    Verify stale lock detection works for dead processes.

    CONTRACT: INV-006 - Stale lock detection
    Evidence: src/utils/file_lock.py lines 324-391 (_is_stale_lock)
    """
    import json

    lock_file = lock_dir / "stale.lock"

    # Create a fake stale lock (PID that doesn't exist)
    fake_pid = 99999999  # Very unlikely to be a real PID
    stale_content = json.dumps({
        "pid": fake_pid,
        "hostname": "test-host",
        "created": "2020-01-01T00:00:00"
    })
    lock_file.write_text(stale_content)

    # Lock should be detected as stale
    lock = FileLock(lock_file, timeout=0)
    is_stale = lock._is_stale_lock()

    assert is_stale is True


@pytest.mark.contract
def test_force_unlock_removes_lock(lock_dir):
    """
    Verify force_unlock removes lock file.

    CONTRACT: INV-006 - Manual recovery option
    Evidence: src/utils/file_lock.py lines 402-456 (force_unlock)
    """
    import json

    lock_file = lock_dir / "force.lock"

    # Create a fake lock file
    fake_pid = 99999999
    lock_file.write_text(json.dumps({"pid": fake_pid, "hostname": "test"}))

    # Force unlock should succeed
    lock = FileLock(lock_file, timeout=0)
    result = lock.force_unlock(check_pid=True)

    assert result is True
    assert not lock_file.exists()


# ==============================================================================
# INV-006: Directory Creation Tests
# ==============================================================================


@pytest.mark.contract
def test_lock_creates_parent_directory(tmp_path):
    """
    Verify FileLock creates lock directory if needed.

    CONTRACT: INV-006 - Lock directory auto-creation
    Evidence: src/utils/file_lock.py lines 173-174 (mkdir)
    """
    # Nested directory that doesn't exist
    lock_file = tmp_path / "deep" / "nested" / "locks" / "test.lock"

    lock = FileLock(lock_file, timeout=0)
    lock.acquire()

    # Directory and lock file should exist
    assert lock_file.parent.exists()
    assert lock_file.exists()

    lock.release()


# ==============================================================================
# INV-006: Timeout Behavior Tests
# ==============================================================================


@pytest.mark.contract
def test_zero_timeout_fails_immediately(lock_dir):
    """
    Verify timeout=0 fails immediately if lock held.

    CONTRACT: INV-006 - Immediate failure option
    Evidence: src/utils/file_lock.py lines 240-244 (timeout=0 check)
    """
    lock_file = lock_dir / "zerotimeout.lock"
    lock1 = FileLock(lock_file, timeout=0)
    lock2 = FileLock(lock_file, timeout=0)

    lock1.acquire()

    start = time.time()
    with pytest.raises(LockError):
        lock2.acquire()
    elapsed = time.time() - start

    # Should fail almost immediately (< 0.5s)
    assert elapsed < 0.5

    lock1.release()


@pytest.mark.contract
def test_reacquire_after_release(lock_dir):
    """
    Verify lock can be reacquired after release.

    CONTRACT: INV-006 - Lock reusability
    Evidence: src/utils/file_lock.py lines 260-293 (release clears state)
    """
    lock_file = lock_dir / "reacquire.lock"
    lock = FileLock(lock_file, timeout=0)

    # First acquire
    result1 = lock.acquire()
    assert result1 is True
    lock.release()

    # Second acquire (same lock instance)
    result2 = lock.acquire()
    assert result2 is True
    lock.release()
