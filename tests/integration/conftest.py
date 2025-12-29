"""Shared fixtures for integration tests.

SR-01: Centralized test fixtures to eliminate repetitive imports.
"""
import pytest
import sys
from pathlib import Path

# Add src to path once for all integration tests
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))


@pytest.fixture
def progress_tracker_class():
    """
    Load ProgressTracker class avoiding package import issues.

    Returns the ProgressTracker class for use in tests.
    """
    import importlib.util
    progress_path = src_path / "translation_engine" / "progress.py"
    spec = importlib.util.spec_from_file_location("progress_module", progress_path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module.ProgressTracker


@pytest.fixture
def atomic_write_module():
    """Load atomic_write module components."""
    from utils.atomic_write import (
        atomic_write,
        AtomicWriteError,
        DiskFullError,
        InvalidPathError,
        ReadOnlyFilesystemError,
    )
    return {
        'atomic_write': atomic_write,
        'AtomicWriteError': AtomicWriteError,
        'DiskFullError': DiskFullError,
        'InvalidPathError': InvalidPathError,
        'ReadOnlyFilesystemError': ReadOnlyFilesystemError,
    }


@pytest.fixture
def file_lock_class():
    """Load FileLock class and LockError."""
    from utils.file_lock import FileLock, LockError
    return {'FileLock': FileLock, 'LockError': LockError}


@pytest.fixture
def test_environment(tmp_path):
    """
    Create a complete test environment for integration tests.

    Returns dict with all required directories pre-created.
    """
    env = {
        'root': tmp_path,
        'source_dir': tmp_path / "source",
        'output_dir': tmp_path / "output",
        'progress_dir': tmp_path / "progress",
        'lock_file': tmp_path / "translation.lock",
    }

    # Create directories
    env['source_dir'].mkdir(parents=True, exist_ok=True)
    env['output_dir'].mkdir(parents=True, exist_ok=True)
    env['progress_dir'].mkdir(parents=True, exist_ok=True)

    return env
