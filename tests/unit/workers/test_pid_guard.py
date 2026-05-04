"""Tests for worker_state.acquire_pid_file single-instance guard."""

from __future__ import annotations

import os
from unittest import mock

from src.workers.worker_state import acquire_pid_file


def test_acquire_pid_file_no_existing(tmp_path):
    """When no PID file exists, acquire succeeds and file contains current PID."""
    result = acquire_pid_file("test_worker", log_dir=tmp_path)
    assert result is True
    pid_file = tmp_path / "test_worker.pid"
    assert pid_file.exists()
    assert int(pid_file.read_text(encoding="utf-8").strip()) == os.getpid()


def test_acquire_pid_file_dead_process(tmp_path):
    """When PID file exists but process is dead, acquire succeeds and overwrites."""
    pid_file = tmp_path / "test_worker.pid"
    pid_file.write_text("99999999", encoding="utf-8")  # unlikely to be alive

    with mock.patch(
        "src.workers.worker_state._is_process_alive", return_value=False
    ):
        result = acquire_pid_file("test_worker", log_dir=tmp_path)

    assert result is True
    assert int(pid_file.read_text(encoding="utf-8").strip()) == os.getpid()


def test_acquire_pid_file_alive_process(tmp_path):
    """When PID file exists and process is alive, acquire fails."""
    pid_file = tmp_path / "test_worker.pid"
    pid_file.write_text("12345", encoding="utf-8")

    with mock.patch(
        "src.workers.worker_state._is_process_alive", return_value=True
    ):
        result = acquire_pid_file("test_worker", log_dir=tmp_path)

    assert result is False
    # PID file should NOT be overwritten
    assert pid_file.read_text(encoding="utf-8").strip() == "12345"
