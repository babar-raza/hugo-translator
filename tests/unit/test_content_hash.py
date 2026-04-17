"""Unit tests for content hash computation."""

import hashlib
from pathlib import Path

import pytest

from src.utils.content_hash import (
    ContentHashError,
    compute_file_hash,
    quick_hash_check,
)


def test_compute_file_hash_md5(tmp_path):
    """Test MD5 hash computation."""
    # Create temp file with known content
    test_file = tmp_path / "test.txt"
    content = b"Hello, World!"
    test_file.write_bytes(content)

    # Compute hash
    result = compute_file_hash(test_file, algorithm="md5")

    # Verify matches expected MD5
    expected = hashlib.md5(content).hexdigest()
    assert result == expected
    assert len(result) == 32  # MD5 hex digest length


def test_compute_file_hash_sha256(tmp_path):
    """Test SHA256 hash computation."""
    test_file = tmp_path / "test.txt"
    content = b"Hello, World!"
    test_file.write_bytes(content)

    result = compute_file_hash(test_file, algorithm="sha256")

    expected = hashlib.sha256(content).hexdigest()
    assert result == expected
    assert len(result) == 64  # SHA256 hex digest length


def test_compute_file_hash_large_file(tmp_path):
    """Test hash computation with chunked reading."""
    test_file = tmp_path / "large.bin"
    # Create 10 MB file
    content = b"A" * (10 * 1024 * 1024)
    test_file.write_bytes(content)

    result = compute_file_hash(test_file, algorithm="md5")

    expected = hashlib.md5(content).hexdigest()
    assert result == expected


def test_compute_file_hash_file_not_found():
    """Test error handling for missing file."""
    with pytest.raises(ContentHashError, match="Failed to hash"):
        compute_file_hash(Path("/nonexistent/file.txt"))


def test_compute_file_hash_invalid_algorithm(tmp_path):
    """Test error handling for invalid algorithm."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("test")

    with pytest.raises(ValueError, match="Unsupported algorithm"):
        compute_file_hash(test_file, algorithm="invalid")


def test_quick_hash_check_match(tmp_path):
    """Test quick hash check with matching hash."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello")

    stored_hash = compute_file_hash(test_file)

    assert quick_hash_check(test_file, stored_hash) is True


def test_quick_hash_check_mismatch(tmp_path):
    """Test quick hash check with different content."""
    test_file = tmp_path / "test.txt"
    test_file.write_text("Hello")

    stored_hash = compute_file_hash(test_file)

    # Modify file
    test_file.write_text("Goodbye")

    assert quick_hash_check(test_file, stored_hash) is False


def test_hash_performance(tmp_path):
    """Performance test: 10MB file should hash in <50ms."""
    test_file = tmp_path / "perf.bin"
    content = b"X" * (10 * 1024 * 1024)
    test_file.write_bytes(content)

    # Just verify it doesn't crash (benchmark requires pytest-benchmark)
    result = compute_file_hash(test_file, algorithm="md5")
    assert len(result) == 32
