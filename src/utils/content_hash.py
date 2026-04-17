"""Content-based file hashing for change detection."""

import hashlib
import time
from pathlib import Path
from typing import TYPE_CHECKING, Literal, Optional

if TYPE_CHECKING:
    from ..observability.metrics import MetricsCollector

HashAlgorithm = Literal["md5", "sha1", "sha256"]


def compute_file_hash(
    file_path: Path,
    algorithm: HashAlgorithm = "md5",
    chunk_size: int = 8192,
    metrics: Optional["MetricsCollector"] = None,
) -> str:
    """
    Compute content hash of a file.

    Args:
        file_path: Path to file
        algorithm: Hash algorithm (md5, sha1, sha256)
        chunk_size: Read chunk size in bytes (default 8KB)
        metrics: Optional metrics collector for instrumentation (CHH-04)

    Returns:
        Hex digest of file hash

    Raises:
        ContentHashError: If hash computation fails

    Performance:
        - MD5: ~500 MB/s (typical)
        - Chunk reading: Efficient for large files
        - 10 MB file: ~20ms with MD5

    Notes:
        - Consistent with TM segment hashing (normalization.py)
        - Not cryptographically secure (speed priority)
    """
    start_time = time.time()

    if algorithm == "md5":
        hasher = hashlib.md5(usedforsecurity=False)
    elif algorithm == "sha1":
        hasher = hashlib.sha1(usedforsecurity=False)
    elif algorithm == "sha256":
        hasher = hashlib.sha256()
    else:
        raise ValueError(f"Unsupported algorithm: {algorithm}")

    try:
        with open(file_path, "rb") as f:
            while chunk := f.read(chunk_size):
                hasher.update(chunk)

        hash_digest = hasher.hexdigest()

        # CHH-04: Record hash computation duration
        if metrics:
            duration = time.time() - start_time
            metrics.observe("content_hash_compute_duration_seconds", duration)

        return hash_digest
    except OSError as e:
        raise ContentHashError(f"Failed to hash {file_path}: {e}") from e


def quick_hash_check(
    file_path: Path,
    stored_hash: str,
    algorithm: HashAlgorithm = "md5"
) -> bool:
    """
    Quick validation: Compare stored hash with current file.

    Returns:
        True if hashes match (content unchanged)
        False if hashes differ (content changed)
    """
    current_hash = compute_file_hash(file_path, algorithm)
    return current_hash == stored_hash


class ContentHashError(Exception):
    """Raised when hash computation fails."""
    pass
