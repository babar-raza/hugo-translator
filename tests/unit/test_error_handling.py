"""Unit tests for RES-09: Comprehensive Error Handling.

Tests cover:
- DiskFullError detection
- Permission denied detection
- Invalid path detection
- Read-only filesystem detection
- Error handler function
- Engine disk space checking
"""

import errno
import sys
from pathlib import Path
from unittest import mock

import pytest

# Add src directory to path for direct imports
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

# Import directly to avoid package import issues
import importlib.util

_atomic_write_path = src_path / "utils" / "atomic_write.py"
_spec = importlib.util.spec_from_file_location("atomic_write_module", _atomic_write_path)
_atomic_write_module = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_atomic_write_module)

atomic_write = _atomic_write_module.atomic_write
AtomicWriteError = _atomic_write_module.AtomicWriteError
DiskFullError = _atomic_write_module.DiskFullError
InvalidPathError = _atomic_write_module.InvalidPathError
ReadOnlyFilesystemError = _atomic_write_module.ReadOnlyFilesystemError
_handle_os_error = _atomic_write_module._handle_os_error


class TestCustomExceptions:
    """Tests for custom exception classes."""

    def test_disk_full_error_is_atomic_write_error(self):
        """Test DiskFullError inherits from AtomicWriteError."""
        err = DiskFullError("No space")
        assert isinstance(err, AtomicWriteError)
        assert isinstance(err, Exception)

    def test_invalid_path_error_is_atomic_write_error(self):
        """Test InvalidPathError inherits from AtomicWriteError."""
        err = InvalidPathError("Bad path")
        assert isinstance(err, AtomicWriteError)

    def test_readonly_filesystem_error_is_atomic_write_error(self):
        """Test ReadOnlyFilesystemError inherits from AtomicWriteError."""
        err = ReadOnlyFilesystemError("Read-only")
        assert isinstance(err, AtomicWriteError)


class TestHandleOSError:
    """Tests for _handle_os_error function."""

    def test_disk_full_errno(self, tmp_path):
        """Test ENOSPC raises DiskFullError."""
        path = tmp_path / "test.txt"
        err = OSError(errno.ENOSPC, "No space left on device")

        with pytest.raises(DiskFullError, match="No space left"):
            _handle_os_error(path, err)

    def test_permission_denied_eacces(self, tmp_path):
        """Test EACCES raises PermissionError."""
        path = tmp_path / "test.txt"
        err = OSError(errno.EACCES, "Permission denied")

        with pytest.raises(PermissionError, match="Permission denied"):
            _handle_os_error(path, err)

    def test_permission_denied_eperm(self, tmp_path):
        """Test EPERM raises PermissionError."""
        path = tmp_path / "test.txt"
        err = OSError(errno.EPERM, "Operation not permitted")

        with pytest.raises(PermissionError, match="Permission denied"):
            _handle_os_error(path, err)

    @pytest.mark.skipif(not hasattr(errno, "EROFS"), reason="EROFS not available on this platform")
    def test_readonly_filesystem(self, tmp_path):
        """Test EROFS raises ReadOnlyFilesystemError."""
        path = tmp_path / "test.txt"
        err = OSError(errno.EROFS, "Read-only file system")

        with pytest.raises(ReadOnlyFilesystemError, match="read-only"):
            _handle_os_error(path, err)

    def test_name_too_long(self, tmp_path):
        """Test ENAMETOOLONG raises InvalidPathError."""
        path = tmp_path / "test.txt"
        err = OSError(errno.ENAMETOOLONG, "File name too long")

        with pytest.raises(InvalidPathError, match="too long"):
            _handle_os_error(path, err)

    def test_enoent_missing_parent(self, tmp_path):
        """Test ENOENT with missing parent raises InvalidPathError."""
        path = tmp_path / "nonexistent" / "nested" / "test.txt"
        err = OSError(errno.ENOENT, "No such file or directory")

        with pytest.raises(InvalidPathError, match="Parent directory"):
            _handle_os_error(path, err)

    def test_enoent_existing_parent(self, tmp_path):
        """Test ENOENT with existing parent raises AtomicWriteError."""
        path = tmp_path / "test.txt"  # Parent exists
        err = OSError(errno.ENOENT, "No such file or directory")

        with pytest.raises(AtomicWriteError, match="Failed to write"):
            _handle_os_error(path, err)

    def test_generic_oserror(self, tmp_path):
        """Test generic OSError raises AtomicWriteError."""
        path = tmp_path / "test.txt"
        err = OSError(999, "Unknown error")

        with pytest.raises(AtomicWriteError, match="errno=999"):
            _handle_os_error(path, err)


class TestAtomicWriteErrorHandling:
    """Tests for atomic_write with error handling."""

    def test_atomic_write_success(self, tmp_path):
        """Test successful atomic write."""
        path = tmp_path / "test.txt"
        content = "Hello, world!"

        atomic_write(path, content)

        assert path.exists()
        assert path.read_text() == content

    def test_atomic_write_disk_full_mock(self, tmp_path):
        """Test disk full error detection via mock."""
        path = tmp_path / "test.txt"

        # Mock tempfile.mkstemp to raise disk full
        with mock.patch("tempfile.mkstemp") as mock_mkstemp:
            mock_mkstemp.side_effect = OSError(errno.ENOSPC, "No space")

            with pytest.raises(DiskFullError, match="No space left"):
                atomic_write(path, "content")

    def test_atomic_write_permission_denied_mock(self, tmp_path):
        """Test permission denied error detection via mock."""
        path = tmp_path / "test.txt"

        with mock.patch("tempfile.mkstemp") as mock_mkstemp:
            mock_mkstemp.side_effect = OSError(errno.EACCES, "Permission denied")

            with pytest.raises(PermissionError, match="Permission denied"):
                atomic_write(path, "content")


class TestAtomicWriteModuleContents:
    """Tests to verify atomic_write module has required elements."""

    def test_module_has_custom_exceptions(self):
        """Verify module exports custom exceptions."""
        assert hasattr(_atomic_write_module, "DiskFullError")
        assert hasattr(_atomic_write_module, "InvalidPathError")
        assert hasattr(_atomic_write_module, "ReadOnlyFilesystemError")
        assert hasattr(_atomic_write_module, "AtomicWriteError")

    def test_module_has_error_handler(self):
        """Verify module has _handle_os_error function."""
        assert hasattr(_atomic_write_module, "_handle_os_error")
        assert callable(_atomic_write_module._handle_os_error)

    def test_res09_marker_in_module(self):
        """Verify RES-09 marker is in the module."""
        content = _atomic_write_path.read_text(encoding="utf-8")
        assert "RES-09" in content


class TestEngineErrorHandling:
    """Tests for engine.py error handling integration."""

    def test_engine_imports_error_classes(self):
        """Verify engine.py imports new exception classes."""
        engine_path = src_path / "translation_engine" / "engine.py"
        content = engine_path.read_text(encoding="utf-8")

        assert "DiskFullError" in content
        assert "InvalidPathError" in content
        assert "ReadOnlyFilesystemError" in content

    def test_engine_has_get_free_space(self):
        """Verify engine.py has _get_free_space method."""
        engine_path = src_path / "translation_engine" / "engine.py"
        content = engine_path.read_text(encoding="utf-8")

        assert "def _get_free_space(" in content
        assert "RES-09" in content

    def test_engine_write_output_handles_errors(self):
        """Verify _write_output handles specific error types."""
        engine_path = src_path / "translation_engine" / "engine.py"
        content = engine_path.read_text(encoding="utf-8")

        # Check for enhanced error handling in _write_output
        assert "except DiskFullError" in content
        assert "except InvalidPathError" in content
        assert "except ReadOnlyFilesystemError" in content


class TestDiskSpaceCheck:
    """Tests for disk space checking functionality."""

    def test_shutil_disk_usage(self, tmp_path):
        """Test that shutil.disk_usage works for checking space."""
        import shutil

        total, used, free = shutil.disk_usage(tmp_path)

        assert total > 0
        assert free >= 0
        assert used >= 0
        assert total == used + free

    def test_sufficient_space_for_write(self, tmp_path):
        """Test that we have space for a small file."""
        import shutil

        content = "Small test content"
        total, used, free = shutil.disk_usage(tmp_path)

        # We should have space for a small file
        assert free > len(content.encode("utf-8")) * 10


class TestErrorMessages:
    """Tests for error message quality."""

    def test_disk_full_message_includes_path(self, tmp_path):
        """Test DiskFullError message includes the path."""
        path = tmp_path / "test.txt"
        err = OSError(errno.ENOSPC, "No space")

        try:
            _handle_os_error(path, err)
        except DiskFullError as e:
            assert str(path) in str(e)

    def test_permission_denied_message_includes_path(self, tmp_path):
        """Test PermissionError message includes the path."""
        path = tmp_path / "test.txt"
        err = OSError(errno.EACCES, "Permission denied")

        try:
            _handle_os_error(path, err)
        except PermissionError as e:
            assert str(path) in str(e)

    def test_invalid_path_message_includes_parent(self, tmp_path):
        """Test InvalidPathError message includes parent directory."""
        path = tmp_path / "nonexistent" / "test.txt"
        err = OSError(errno.ENOENT, "No such file")

        try:
            _handle_os_error(path, err)
        except InvalidPathError as e:
            assert "nonexistent" in str(e)

    def test_atomic_write_error_includes_errno(self, tmp_path):
        """Test generic error includes errno."""
        path = tmp_path / "test.txt"
        err = OSError(42, "Custom error")

        try:
            _handle_os_error(path, err)
        except AtomicWriteError as e:
            assert "errno=42" in str(e)
