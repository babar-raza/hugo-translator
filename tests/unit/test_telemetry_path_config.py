"""Test telemetry path configuration via environment variable."""
import os
import sys
from pathlib import Path
import pytest


@pytest.fixture
def clean_env(monkeypatch):
    """Clean environment and sys.path for testing."""
    monkeypatch.delenv('TELEMETRY_SRC_PATH', raising=False)
    original_path = sys.path.copy()
    yield
    sys.path[:] = original_path


def test_default_telemetry_path(clean_env, monkeypatch):
    """Test default telemetry path when env var not set."""
    # Ensure env var is not set
    monkeypatch.delenv('TELEMETRY_SRC_PATH', raising=False)

    # Simulate path resolution logic
    telemetry_path = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    expected_default = Path(r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src")
    assert telemetry_path == expected_default, f"Expected {expected_default}, got {telemetry_path}"


def test_custom_telemetry_path_from_env(clean_env, monkeypatch):
    """Test custom telemetry path from environment variable."""
    custom_path = r"C:\custom\telemetry\src"
    monkeypatch.setenv('TELEMETRY_SRC_PATH', custom_path)

    # Simulate path resolution logic
    telemetry_path = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    assert telemetry_path == Path(custom_path), f"Expected {custom_path}, got {telemetry_path}"


def test_telemetry_path_string_resolution(clean_env, monkeypatch):
    """Test that Path object is created correctly from env var."""
    test_path = r"C:\test\path\to\telemetry"
    monkeypatch.setenv('TELEMETRY_SRC_PATH', test_path)

    # Simulate path resolution logic
    telemetry_path = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    # Verify it's a Path object
    assert isinstance(telemetry_path, Path)
    assert str(telemetry_path) == test_path


def test_telemetry_path_in_sys_path(clean_env, tmp_path, monkeypatch):
    """Test that valid telemetry path is added to sys.path."""
    # Create a temporary valid telemetry path
    telemetry_path = tmp_path / "telemetry_src"
    telemetry_path.mkdir()

    # Set environment variable
    monkeypatch.setenv('TELEMETRY_SRC_PATH', str(telemetry_path))

    # Remove from sys.path if present
    path_str = str(telemetry_path)
    if path_str in sys.path:
        sys.path.remove(path_str)

    # Simulate the loading logic
    TELEMETRY_SRC_PATH = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    if TELEMETRY_SRC_PATH.exists() and str(TELEMETRY_SRC_PATH) not in sys.path:
        sys.path.insert(0, str(TELEMETRY_SRC_PATH))

    # Verify path was added
    assert str(telemetry_path) in sys.path


def test_telemetry_path_not_added_if_missing(clean_env, monkeypatch):
    """Test that invalid/missing path is not added to sys.path."""
    invalid_path = r"C:\nonexistent\telemetry\path"
    monkeypatch.setenv('TELEMETRY_SRC_PATH', invalid_path)

    # Simulate the loading logic
    TELEMETRY_SRC_PATH = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    # Only add if exists
    if TELEMETRY_SRC_PATH.exists() and str(TELEMETRY_SRC_PATH) not in sys.path:
        sys.path.insert(0, str(TELEMETRY_SRC_PATH))

    # Verify invalid path was not added
    assert invalid_path not in sys.path


def test_telemetry_path_skipped_if_already_present(clean_env, tmp_path, monkeypatch):
    """Test that path is not added again if already in sys.path."""
    # Create a temporary valid telemetry path
    telemetry_path = tmp_path / "telemetry_src"
    telemetry_path.mkdir()

    # Add to sys.path first
    path_str = str(telemetry_path)
    sys.path.insert(0, path_str)
    original_path_count = sys.path.count(path_str)

    # Set environment variable
    monkeypatch.setenv('TELEMETRY_SRC_PATH', path_str)

    # Simulate the loading logic
    TELEMETRY_SRC_PATH = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    # Check if already in sys.path before adding
    if TELEMETRY_SRC_PATH.exists() and str(TELEMETRY_SRC_PATH) not in sys.path:
        sys.path.insert(0, str(TELEMETRY_SRC_PATH))

    # Verify path count didn't increase (not added again)
    assert sys.path.count(path_str) == original_path_count
