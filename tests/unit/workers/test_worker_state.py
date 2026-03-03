"""
Unit tests for durable worker state ledger helpers.
"""

from datetime import datetime, timezone
from pathlib import Path

from src.workers.worker_state import load_worker_state, record_worker_state


def test_record_worker_state_only_sets_last_success_on_success(tmp_path: Path):
    """Non-success state transitions must not imply successful completion."""
    t1 = datetime(2026, 2, 16, 10, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 2, 16, 10, 5, 0, tzinfo=timezone.utc)

    record_worker_state(
        "content_worker",
        "running",
        success=False,
        log_dir=tmp_path,
        now=t1,
    )
    state_running = load_worker_state("content_worker", log_dir=tmp_path)
    assert "last_success_ts" not in state_running
    assert state_running["state"] == "running"

    record_worker_state(
        "content_worker",
        "run_completed",
        success=True,
        log_dir=tmp_path,
        now=t2,
    )
    state_success = load_worker_state("content_worker", log_dir=tmp_path)
    assert state_success["last_success_ts"] == t2.isoformat()
    assert state_success["state"] == "run_completed"


def test_record_worker_state_tracks_error_without_erasing_success(tmp_path: Path):
    """Failure updates should set last_error_ts and preserve existing last_success_ts."""
    t1 = datetime(2026, 2, 16, 11, 0, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 2, 16, 11, 10, 0, tzinfo=timezone.utc)

    record_worker_state(
        "tm_worker",
        "run_completed",
        success=True,
        log_dir=tmp_path,
        now=t1,
    )
    record_worker_state(
        "tm_worker",
        "run_failed",
        error="llm unavailable",
        log_dir=tmp_path,
        now=t2,
    )

    state = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state["last_success_ts"] == t1.isoformat()
    assert state["last_error_ts"] == t2.isoformat()
    assert state["last_error"] == "llm unavailable"
    assert state["state"] == "run_failed"

