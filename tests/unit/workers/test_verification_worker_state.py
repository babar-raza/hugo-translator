"""
TC-VW-01: Verification worker state transitions.

Verifies:
1. State transitions: starting → sleeping → running → run_completed → sleeping.
2. last_success_ts advances on every clean pass (even 0-file passes).
3. _run_daemon() calls _record_state("sleeping") before every scheduler sleep.
4. Watchdog idle WARN threshold: Invoke-VerificationIdleCheck present in watchdog.
"""
from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.workers.worker_state import load_worker_state, record_worker_state


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_state_calls(log_dir: Path, transitions: list[tuple]) -> None:
    """
    transitions: list of (state_name, kwargs) where kwargs include success/error.
    """
    from datetime import timedelta
    base = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)
    for i, (state, kwargs) in enumerate(transitions):
        record_worker_state(
            "verification_worker",
            state,
            log_dir=log_dir,
            now=base + timedelta(minutes=i),
            **kwargs,
        )


# ---------------------------------------------------------------------------
# State transition tests
# ---------------------------------------------------------------------------

def test_state_sleeping_written_before_scheduler_sleep(tmp_path):
    """
    State must transition from 'starting' → 'sleeping' before the first
    scheduler sleep (identical requirement as TC-TM-01 but for verification_worker).
    """
    _make_state_calls(tmp_path, [
        ("starting", {}),
        ("sleeping", {}),
    ])
    state = load_worker_state("verification_worker", log_dir=tmp_path)
    assert state["state"] == "sleeping", (
        f"Expected 'sleeping' after setup, got '{state['state']}'. "
        "Verification worker must write sleeping before scheduler sleep."
    )


def test_full_daemon_cycle(tmp_path):
    """
    Full cycle: starting → sleeping → running → run_completed → sleeping.
    last_success_ts must advance on run_completed.
    """
    from datetime import timedelta
    t0 = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)
    t1 = t0 + timedelta(minutes=1)
    t2 = t0 + timedelta(minutes=2)
    t3 = t0 + timedelta(minutes=3)

    record_worker_state("verification_worker", "starting", log_dir=tmp_path, now=t0)
    record_worker_state("verification_worker", "sleeping", log_dir=tmp_path, now=t1)
    record_worker_state("verification_worker", "running", log_dir=tmp_path, now=t2)
    record_worker_state("verification_worker", "run_completed", success=True, log_dir=tmp_path, now=t3)

    state = load_worker_state("verification_worker", log_dir=tmp_path)
    assert state["state"] == "run_completed"
    assert state["last_success_ts"] == t3.isoformat()


def test_zero_file_pass_advances_last_success_ts(tmp_path):
    """
    A verification pass with 0 files verified (config-only check) must still
    advance last_success_ts. The pass is a success if no checks failed.
    """
    t_prior = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    t_now = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)

    record_worker_state("verification_worker", "run_completed", success=True, log_dir=tmp_path, now=t_prior)
    record_worker_state("verification_worker", "sleeping", log_dir=tmp_path, now=t_prior)
    # Zero-file pass: still success=True
    record_worker_state("verification_worker", "run_completed", success=True, log_dir=tmp_path, now=t_now)

    state = load_worker_state("verification_worker", log_dir=tmp_path)
    assert state["last_success_ts"] == t_now.isoformat(), (
        "Zero-file verification pass must advance last_success_ts."
    )


def test_run_failed_does_not_advance_last_success_ts(tmp_path):
    """
    run_failed must NOT overwrite last_success_ts.
    """
    t_success = datetime(2026, 4, 17, 10, 0, 0, tzinfo=timezone.utc)
    t_fail = datetime(2026, 4, 18, 10, 0, 0, tzinfo=timezone.utc)

    record_worker_state("verification_worker", "run_completed", success=True, log_dir=tmp_path, now=t_success)
    record_worker_state("verification_worker", "run_failed", error="config missing", log_dir=tmp_path, now=t_fail)

    state = load_worker_state("verification_worker", log_dir=tmp_path)
    assert state["state"] == "run_failed"
    assert state["last_success_ts"] == t_success.isoformat()
    assert state["last_error_ts"] == t_fail.isoformat()


# ---------------------------------------------------------------------------
# Static source inspection
# ---------------------------------------------------------------------------

def test_verification_daemon_calls_record_state_sleeping():
    """
    Static check: _run_daemon() must call _record_state("sleeping") before
    sleep_until_next_run. Guards against regression of TC-VW-01.
    """
    import inspect
    from src.workers.autonomous_verification_worker import AutonomousVerificationWorker

    source = inspect.getsource(AutonomousVerificationWorker._run_daemon)
    assert '_record_state("sleeping")' in source, (
        "_run_daemon() must call _record_state('sleeping') before scheduler sleep. "
        "This ensures verification_worker state.json never stays stuck at 'starting'."
    )
    # Also verify it appears before sleep_until_next_run
    sleeping_idx = source.index('_record_state("sleeping")')
    sleep_idx = source.index("sleep_until_next_run")
    assert sleeping_idx < sleep_idx, (
        "_record_state('sleeping') must appear BEFORE sleep_until_next_run."
    )


# ---------------------------------------------------------------------------
# Watchdog idle check presence
# ---------------------------------------------------------------------------

def test_watchdog_has_verification_idle_check():
    """
    TC-VW-01: worker_watchdog.ps1 must contain Invoke-VerificationIdleCheck
    to warn when verification_worker last_success_ts is stale.
    """
    watchdog_path = Path("scripts/worker_watchdog.ps1")
    if not watchdog_path.exists():
        pytest.skip("scripts/worker_watchdog.ps1 not found")

    source = watchdog_path.read_text(encoding="utf-8")
    assert "Invoke-VerificationIdleCheck" in source, (
        "scripts/worker_watchdog.ps1 must define and call Invoke-VerificationIdleCheck "
        "(TC-VW-01: watchdog idle WARN for verification_worker)."
    )
    assert "last_success_ts" in source, (
        "Invoke-VerificationIdleCheck must check last_success_ts from state.json."
    )
