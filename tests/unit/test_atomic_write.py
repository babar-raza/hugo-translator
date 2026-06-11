"""Unit tests for atomic file write operations.

Tests cover:
- Successful atomic writes
- Temp file cleanup on success and error
- Parent directory creation
- Error handling (disk full, permission denied)
- Binary content
- Unicode content
- Large files
- Performance characteristics
"""

import os
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from utils.atomic_write import (
    AtomicWriteError,
    atomic_write,
    atomic_write_binary,
    verify_atomic_write,
)


class TestAtomicWriteSuccess:
    """Tests for successful atomic write operations."""

    def test_atomic_write_success(self, tmp_path):
        """Test successful atomic write."""
        path = tmp_path / "test.txt"
        content = "Hello, World!"

        atomic_write(path, content)

        assert path.exists()
        assert path.read_text() == content

    def test_atomic_write_no_partial_files(self, tmp_path):
        """Test no .tmp files left after success."""
        path = tmp_path / "test.txt"
        atomic_write(path, "content")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_creates_parents(self, tmp_path):
        """Test parent directory creation."""
        path = tmp_path / "sub" / "dir" / "test.txt"
        atomic_write(path, "content", create_parents=True)

        assert path.exists()
        assert path.read_text() == "content"

    def test_atomic_write_overwrites_existing(self, tmp_path):
        """Test overwriting existing file."""
        path = tmp_path / "test.txt"
        path.write_text("original content")

        atomic_write(path, "new content")

        assert path.read_text() == "new content"

    def test_atomic_write_unicode(self, tmp_path):
        """Test Unicode content."""
        path = tmp_path / "test.txt"
        content = "Hello 世界 🌍"

        atomic_write(path, content)

        assert path.read_text(encoding="utf-8") == content

    def test_atomic_write_large_file(self, tmp_path):
        """Test large file write (1MB)."""
        path = tmp_path / "large.txt"
        content = "x" * (1024 * 1024)  # 1MB

        atomic_write(path, content)

        assert path.read_text() == content

    def test_atomic_write_empty_content(self, tmp_path):
        """Test writing empty content."""
        path = tmp_path / "empty.txt"

        atomic_write(path, "")

        assert path.exists()
        assert path.read_text() == ""


class TestAtomicWriteCleanup:
    """Tests for temp file cleanup behavior."""

    def test_atomic_write_cleanup_on_error(self, tmp_path):
        """Test temp file cleanup on write error."""
        path = tmp_path / "test.txt"

        # Mock to raise error during rename
        with mock.patch("os.replace", side_effect=OSError("Disk full")):
            with pytest.raises(AtomicWriteError):
                atomic_write(path, "content")

        # Verify no temp files remain
        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0

    def test_atomic_write_cleanup_preserves_original(self, tmp_path):
        """Test original file preserved on error."""
        path = tmp_path / "test.txt"
        original_content = "original content"
        path.write_text(original_content)

        # Mock to raise error during rename
        with mock.patch("os.replace", side_effect=OSError("Disk full")):
            with pytest.raises(AtomicWriteError):
                atomic_write(path, "new content")

        # Verify original file unchanged
        assert path.read_text() == original_content


class TestAtomicWriteErrorHandling:
    """Tests for error handling."""

    def test_atomic_write_disk_full(self, tmp_path):
        """Test disk full error handling."""
        path = tmp_path / "test.txt"

        # Simulate disk full during write
        original_fdopen = os.fdopen

        def mock_fdopen(*args, **kwargs):
            raise OSError(28, "No space left on device")

        with mock.patch("os.fdopen", side_effect=mock_fdopen):
            with pytest.raises(AtomicWriteError, match="No space left on device"):
                atomic_write(path, "content")

    def test_atomic_write_permission_denied_on_create(self, tmp_path):
        """Test permission denied when creating temp file."""
        path = tmp_path / "test.txt"

        # Simulate permission denied during temp file creation
        with mock.patch("tempfile.mkstemp", side_effect=OSError(13, "Permission denied")):
            with pytest.raises(AtomicWriteError):
                atomic_write(path, "content")

    @pytest.mark.skipif(sys.platform == "win32", reason="chmod behaves differently on Windows")
    def test_atomic_write_permission_denied_readonly(self, tmp_path):
        """Test permission denied on read-only file."""
        path = tmp_path / "test.txt"
        path.touch()
        path.chmod(0o444)  # Read-only

        try:
            with pytest.raises(AtomicWriteError):
                atomic_write(path, "content")
        finally:
            path.chmod(0o644)  # Restore permissions for cleanup


class TestAtomicWriteOptions:
    """Tests for optional parameters."""

    def test_atomic_write_fsync_optional(self, tmp_path):
        """Test fsync can be disabled for performance."""
        path = tmp_path / "test.txt"

        # Should work without fsync
        atomic_write(path, "content", fsync=False)
        assert path.exists()
        assert path.read_text() == "content"

    def test_atomic_write_create_parents_false(self, tmp_path):
        """Test no parent creation when disabled."""
        path = tmp_path / "nonexistent" / "test.txt"

        with pytest.raises(AtomicWriteError):
            atomic_write(path, "content", create_parents=False)

    def test_atomic_write_custom_encoding(self, tmp_path):
        """Test custom encoding."""
        path = tmp_path / "test.txt"
        content = "Test content"

        atomic_write(path, content, encoding="latin-1")

        assert path.read_text(encoding="latin-1") == content


class TestAtomicWriteBinary:
    """Tests for binary content writes."""

    def test_atomic_write_binary(self, tmp_path):
        """Test binary content write."""
        path = tmp_path / "test.bin"
        content = b"\x00\x01\x02\x03"

        atomic_write_binary(path, content)

        assert path.read_bytes() == content

    def test_atomic_write_binary_large(self, tmp_path):
        """Test large binary write."""
        path = tmp_path / "large.bin"
        content = bytes(range(256)) * 4096  # ~1MB

        atomic_write_binary(path, content)

        assert path.read_bytes() == content

    def test_atomic_write_binary_cleanup_on_error(self, tmp_path):
        """Test binary write cleans up temp on error."""
        path = tmp_path / "test.bin"

        with mock.patch("os.replace", side_effect=OSError("Disk full")):
            with pytest.raises(AtomicWriteError):
                atomic_write_binary(path, b"content")

        tmp_files = list(tmp_path.glob("*.tmp"))
        assert len(tmp_files) == 0


class TestVerifyAtomicWrite:
    """Tests for verification helper."""

    def test_verify_atomic_write_success(self, tmp_path):
        """Test verification passes for correct content."""
        path = tmp_path / "test.txt"
        content = "test content"
        path.write_text(content)

        assert verify_atomic_write(path, content) is True

    def test_verify_atomic_write_mismatch(self, tmp_path):
        """Test verification fails for wrong content."""
        path = tmp_path / "test.txt"
        path.write_text("actual content")

        assert verify_atomic_write(path, "expected content") is False

    def test_verify_atomic_write_missing_file(self, tmp_path):
        """Test verification fails for missing file."""
        path = tmp_path / "nonexistent.txt"

        assert verify_atomic_write(path, "content") is False


class TestAtomicWritePerformance:
    """Performance-related tests."""

    def test_atomic_write_performance_small(self, tmp_path):
        """Test performance overhead is acceptable for small files."""
        import time

        path = tmp_path / "perf.txt"
        content = "x" * 1000  # 1KB

        start = time.perf_counter()
        for i in range(100):
            atomic_write(path, content, fsync=False)
        elapsed = time.perf_counter() - start

        # Should complete 100 writes in under 1 second
        assert elapsed < 1.0, f"100 small writes took {elapsed:.2f}s"

    def test_atomic_write_performance_with_fsync(self, tmp_path):
        """Test fsync adds acceptable overhead."""
        import time

        path = tmp_path / "perf.txt"
        content = "x" * 10000  # 10KB

        start = time.perf_counter()
        for i in range(10):
            atomic_write(path, content, fsync=True)
        elapsed = time.perf_counter() - start

        # With fsync, 10 writes should still complete reasonably
        # (fsync can be slow on some systems)
        assert elapsed < 10.0, f"10 fsync writes took {elapsed:.2f}s"
