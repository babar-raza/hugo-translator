"""Unit tests for diagnose_lock() function."""

import json
import os
import time
from io import StringIO
from unittest.mock import patch

import pytest

from src.utils.file_lock import diagnose_lock


@pytest.fixture
def capture_stdout():
    """Capture stdout for testing diagnostic output."""
    import sys

    def _capture(func, *args, **kwargs):
        old_stdout = sys.stdout
        sys.stdout = captured = StringIO()
        try:
            func(*args, **kwargs)
            return captured.getvalue()
        finally:
            sys.stdout = old_stdout

    return _capture


def test_diagnose_no_lock(capture_stdout, tmp_path, monkeypatch):
    """Test diagnose_lock when no lock exists."""

    # Mock get_site_lock_path to use tmp_path
    def mock_get_lock_path(site_id):
        return tmp_path / f"{site_id}.lock"

    monkeypatch.setattr("src.utils.file_lock.get_site_lock_path", mock_get_lock_path)

    output = capture_stdout(diagnose_lock, "test.example.net")

    assert "Lock Exists: No" in output or "No lock file found" in output
    assert "test.example.net" in output


def test_diagnose_dead_pid(capture_stdout, tmp_path, monkeypatch):
    """Test diagnose_lock with dead PID."""

    lock_file = tmp_path / "test.example.net.lock"
    metadata = {
        "pid": 999999,
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata))

    def mock_get_lock_path(site_id):
        return tmp_path / f"{site_id}.lock"

    monkeypatch.setattr("src.utils.file_lock.get_site_lock_path", mock_get_lock_path)

    output = capture_stdout(diagnose_lock, "test.example.net")

    assert "Lock Exists: Yes" in output
    assert "999999" in output
    assert "<dead>" in output or "dead" in output.lower()
    assert "unlock" in output.lower()  # Should recommend unlock command


def test_diagnose_live_pid(capture_stdout, tmp_path, monkeypatch):
    """Test diagnose_lock with live PID."""
    lock_file = tmp_path / "test.example.net.lock"
    metadata = {
        "pid": os.getpid(),
        "hostname": "test-host",
        "created": "2025-01-01T00:00:00",
        "format_version": "1.0",
    }
    lock_file.write_text(json.dumps(metadata))

    def mock_get_lock_path(site_id):
        return tmp_path / f"{site_id}.lock"

    monkeypatch.setattr("src.utils.file_lock.get_site_lock_path", mock_get_lock_path)

    output = capture_stdout(diagnose_lock, "test.example.net")

    assert "Lock Exists: Yes" in output
    assert str(os.getpid()) in output
    assert "RUNNING" in output or "running" in output.lower()
    assert "Wait" in output or "wait" in output.lower()


def test_diagnose_permission_error(capture_stdout, tmp_path, monkeypatch):
    """Test diagnose_lock with PermissionError on read."""
    lock_file = tmp_path / "test.example.net.lock"
    lock_file.write_text("12345")

    # Set old mtime
    old_time = time.time() - 700
    os.utime(lock_file, (old_time, old_time))

    def mock_get_lock_path(site_id):
        return tmp_path / f"{site_id}.lock"

    monkeypatch.setattr("src.utils.file_lock.get_site_lock_path", mock_get_lock_path)

    # Mock open to raise PermissionError
    with patch("builtins.open", side_effect=PermissionError("Access denied")):
        output = capture_stdout(diagnose_lock, "test.example.net")

    assert "PermissionError" in output or "Cannot read" in output
    assert "unlock" in output.lower()  # Should recommend unlock
