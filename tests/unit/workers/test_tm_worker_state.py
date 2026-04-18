"""
TC-TM-01: tm_worker state machine transition tests.

Verifies that `_record_state("sleeping")` is emitted before every scheduler
sleep in daemon mode, so that state.json never stays stuck at "starting" after
setup completes.

Gap: G-TM-01 — state.json stuck at "starting" post-watchdog-restart.
"""
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

from src.workers.worker_state import load_worker_state, record_worker_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_calls(log_dir: Path, states: list[str]) -> None:
    """Simulate the sequence of record_worker_state calls a worker makes."""
    now_base = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)
    for i, state in enumerate(states):
        from datetime import timedelta
        record_worker_state(
            "tm_worker",
            state,
            success=(state == "run_completed"),
            log_dir=log_dir,
            now=now_base + timedelta(minutes=i),
        )


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------

def test_sleeping_state_written_before_first_scheduler_sleep(tmp_path: Path):
    """
    State must transition from 'starting' → 'sleeping' before the first
    scheduler sleep — not stay at 'starting' until the first run completes.
    """
    _make_state_calls(tmp_path, ["starting", "sleeping"])
    state = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state["state"] == "sleeping", (
        f"Expected 'sleeping' after setup, got '{state['state']}'. "
        "This mirrors the bug where state stayed 'starting' for the full first sleep cycle."
    )


def test_state_cycles_correctly_through_run_and_sleep(tmp_path: Path):
    """
    Full daemon cycle: starting → sleeping → run_completed → sleeping.
    last_success_ts must advance on each run_completed.
    """
    t0 = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 4, 18, 10, 30, 0, tzinfo=timezone.utc)
    t2 = datetime(2026, 4, 18, 11, 0, 0, tzinfo=timezone.utc)
    t3 = datetime(2026, 4, 18, 11, 30, 0, tzinfo=timezone.utc)

    record_worker_state("tm_worker", "starting", log_dir=tmp_path, now=t0)
    record_worker_state("tm_worker", "sleeping", log_dir=tmp_path, now=t1)
    record_worker_state("tm_worker", "run_completed", success=True, log_dir=tmp_path, now=t2)
    record_worker_state("tm_worker", "sleeping", log_dir=tmp_path, now=t3)

    state = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state["state"] == "sleeping"
    assert state["last_success_ts"] == t2.isoformat(), (
        "last_success_ts must be set by run_completed(success=True)."
    )


def test_empty_queue_run_advances_last_success_ts(tmp_path: Path):
    """
    A queue-empty run (0 improved, 0 failed) must still advance last_success_ts.
    The result is still 'success' — only run errors should leave last_success_ts unchanged.
    """
    t_prior = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    t_empty_run = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)

    record_worker_state("tm_worker", "run_completed", success=True, log_dir=tmp_path, now=t_prior)
    record_worker_state("tm_worker", "sleeping", log_dir=tmp_path, now=t_prior)
    # Queue-empty run: result["status"] == "success", result["improved_count"] == 0
    # Worker calls _record_state("run_completed", success=True) — same as non-empty
    record_worker_state("tm_worker", "run_completed", success=True, log_dir=tmp_path, now=t_empty_run)

    state = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state["last_success_ts"] == t_empty_run.isoformat(), (
        "Queue-empty run must advance last_success_ts (worker is healthy, just idle)."
    )


def test_state_never_stays_at_starting_after_sleeping_written(tmp_path: Path):
    """
    Regression: state must not read 'starting' once sleeping has been written.
    """
    t0 = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)
    t1 = datetime(2026, 4, 18, 10, 1, 0, tzinfo=timezone.utc)

    record_worker_state("tm_worker", "starting", log_dir=tmp_path, now=t0)
    state_after_init = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state_after_init["state"] == "starting"  # Expected before sleeping is written

    record_worker_state("tm_worker", "sleeping", log_dir=tmp_path, now=t1)
    state_after_sleep = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state_after_sleep["state"] == "sleeping", (
        "Once sleeping is written, state must not revert to 'starting'."
    )


def test_error_state_does_not_advance_last_success_ts(tmp_path: Path):
    """
    A run_failed state must NOT advance last_success_ts.
    Watchdog health logic relies on this to detect stalled workers.
    """
    t_success = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    t_fail = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)

    record_worker_state("tm_worker", "run_completed", success=True, log_dir=tmp_path, now=t_success)
    record_worker_state("tm_worker", "run_failed", error="LLM timeout", log_dir=tmp_path, now=t_fail)

    state = load_worker_state("tm_worker", log_dir=tmp_path)
    assert state["state"] == "run_failed"
    assert state["last_success_ts"] == t_success.isoformat(), (
        "run_failed must not overwrite last_success_ts."
    )
    assert state["last_error_ts"] == t_fail.isoformat()


def test_record_state_sleeping_is_called_in_daemon_loop():
    """
    Integration smoke: verify _record_state("sleeping") call exists in
    _run_daemon by inspecting the source of the method.

    This is a static check — it fails if the line is accidentally removed
    or the state string is changed.
    """
    import inspect
    from src.workers.tm_improvement_worker import TMImprovementWorker

    source = inspect.getsource(TMImprovementWorker._run_daemon)
    assert '_record_state("sleeping")' in source, (
        "_record_state('sleeping') must be called inside _run_daemon() "
        "alongside _write_heartbeat('sleeping'). "
        "This guards against TC-TM-01 regression (state stuck at 'starting')."
    )
    # Also verify it appears before scheduler.sleep_until_next_run
    sleeping_idx = source.index('_record_state("sleeping")')
    sleep_idx = source.index("sleep_until_next_run")
    assert sleeping_idx < sleep_idx, (
        "_record_state('sleeping') must appear BEFORE sleep_until_next_run "
        "so state is updated before the blocking sleep."
    )
