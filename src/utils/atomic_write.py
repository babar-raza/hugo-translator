"""Atomic file write operations for crash safety.

This module provides atomic file write operations using the temp file + rename
pattern. This ensures files are either fully written or unchanged, preventing
corruption on unexpected termination (Ctrl+C, kill, power loss).

Implementation follows RES-03 from the translation resilience plan.
RES-09: Enhanced with comprehensive error detection and custom exceptions.
"""

import os
import errno
import tempfile
from pathlib import Path
from typing import Optional
import logging

logger = logging.getLogger(__name__)


class AtomicWriteError(Exception):
    """Raised when atomic write operation fails."""
    pass


class DiskFullError(AtomicWriteError):
    """RES-09: Raised when disk is full (ENOSPC)."""
    pass


class InvalidPathError(AtomicWriteError):
    """RES-09: Raised when path is invalid or too long."""
    pass


class ReadOnlyFilesystemError(AtomicWriteError):
    """RES-09: Raised when filesystem is read-only."""
    pass


def _handle_os_error(path: Path, e: OSError) -> None:
    """
    RES-09: Convert OSError to specific exception type.

    Detects and raises appropriate exception for:
    - Disk full (ENOSPC)
    - Permission denied (EACCES, EPERM)
    - Read-only filesystem (EROFS)
    - File name too long (ENAMETOOLONG)
    - Parent directory doesn't exist (ENOENT)

    Args:
        path: Target file path
        e: OSError to handle

    Raises:
        DiskFullError: No space left on device
        PermissionError: Permission denied
        ReadOnlyFilesystemError: Filesystem is read-only
        InvalidPathError: Path invalid or too long
        AtomicWriteError: Other write failures
    """
    err = e.errno

    # Disk full
    if err == errno.ENOSPC:
        raise DiskFullError(
            f"No space left on device when writing {path}. "
            f"Free up space and retry."
        ) from e

    # Permission denied
    if err in (errno.EACCES, errno.EPERM):
        raise PermissionError(
            f"Permission denied: {path}. "
            f"Check file permissions and ownership."
        ) from e

    # Read-only filesystem
    if err == errno.EROFS:
        raise ReadOnlyFilesystemError(
            f"Cannot write to read-only filesystem: {path}"
        ) from e

    # File name too long
    if err == errno.ENAMETOOLONG:
        raise InvalidPathError(
            f"Path or filename too long: {path}"
        ) from e

    # Parent directory doesn't exist
    if err == errno.ENOENT:
        if not path.parent.exists():
            raise InvalidPathError(
                f"Parent directory doesn't exist: {path.parent}"
            ) from e
        # File doesn't exist is OK for write
        raise AtomicWriteError(f"Failed to write {path}: {e}") from e

    # Generic error
    raise AtomicWriteError(
        f"Failed to write {path}: {e} (errno={err})"
    ) from e


def atomic_write(
    path: Path,
    content: str,
    encoding: str = "utf-8",
    fsync: bool = True,
    create_parents: bool = True
) -> None:
    """
    Write content atomically using temp file + rename.

    Guarantees:
    - File either fully written or unchanged
    - No partial content visible at any time
    - Works across platforms (POSIX and Windows)

    Process:
    1. Write to temp file in same directory
    2. fsync() to ensure content on disk
    3. Atomic rename to target path
    4. Clean up temp file on any error

    Args:
        path: Target file path
        content: Content to write
        encoding: Text encoding (default: utf-8)
        fsync: Whether to fsync before rename (default: True)
        create_parents: Create parent directories if needed (default: True)

    Raises:
        AtomicWriteError: If write operation fails
        OSError: If disk full or permission denied
    """
    path = Path(path)

    # Create parent directories
    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    # Temp file in same directory (ensures same filesystem for atomic rename)
    temp_fd = None
    temp_path = None

    try:
        # Create temp file in target directory
        temp_fd, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp"
        )
        temp_path = Path(temp_name)

        # Write content
        with os.fdopen(temp_fd, 'w', encoding=encoding) as f:
            f.write(content)

            if fsync:
                # Ensure content written to disk
                f.flush()
                os.fsync(f.fileno())

        temp_fd = None  # Closed by context manager

        # Atomic rename
        # os.replace() is atomic on both POSIX and Windows
        os.replace(temp_path, path)

        logger.debug(f"Atomically wrote {len(content)} bytes to {path}")

    except OSError as e:
        # RES-09: Comprehensive error detection
        _handle_os_error(path, e)

    except Exception as e:
        # Unexpected error
        raise AtomicWriteError(f"Atomic write failed for {path}: {e}") from e

    finally:
        # Clean up temp file if it exists
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass

        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def atomic_write_binary(
    path: Path,
    content: bytes,
    fsync: bool = True,
    create_parents: bool = True
) -> None:
    """
    Write binary content atomically.

    Same guarantees as atomic_write() but for binary data.

    Args:
        path: Target file path
        content: Binary content to write
        fsync: Whether to fsync before rename (default: True)
        create_parents: Create parent directories if needed (default: True)

    Raises:
        AtomicWriteError: If write operation fails
    """
    path = Path(path)

    if create_parents:
        path.parent.mkdir(parents=True, exist_ok=True)

    temp_fd = None
    temp_path = None

    try:
        temp_fd, temp_name = tempfile.mkstemp(
            dir=path.parent,
            prefix=f".{path.name}.",
            suffix=".tmp"
        )
        temp_path = Path(temp_name)

        with os.fdopen(temp_fd, 'wb') as f:
            f.write(content)

            if fsync:
                f.flush()
                os.fsync(f.fileno())

        temp_fd = None

        os.replace(temp_path, path)

        logger.debug(f"Atomically wrote {len(content)} bytes to {path}")

    except OSError as e:
        # RES-09: Comprehensive error detection
        _handle_os_error(path, e)
    except Exception as e:
        raise AtomicWriteError(f"Atomic write failed for {path}: {e}") from e
    finally:
        if temp_fd is not None:
            try:
                os.close(temp_fd)
            except OSError:
                pass
        if temp_path and temp_path.exists():
            try:
                temp_path.unlink()
            except OSError:
                pass


def verify_atomic_write(path: Path, expected_content: str) -> bool:
    """
    Verify file was written correctly (for testing).

    Args:
        path: File path to verify
        expected_content: Expected file content

    Returns:
        True if content matches, False otherwise
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            actual_content = f.read()
        return actual_content == expected_content
    except Exception:
        return False
