"""TC-APT-004: generic persisted circuit breaker primitive (src/utils/circuit_breaker.py)."""

from __future__ import annotations

import json
from pathlib import Path

from src.utils.circuit_breaker import BreakerConfig, BreakerState, CircuitBreaker


def _breaker(tmp_path: Path, clock, **cfg):
    return CircuitBreaker(
        "m",
        state_path=tmp_path / "m.json",
        config=BreakerConfig(**cfg),
        clock=lambda: clock["now"],
    )


def test_starts_closed_and_persists_state_file(tmp_path):
    clock = {"now": 100.0}
    b = _breaker(tmp_path, clock)
    assert b.allow_request() is True and b.state is BreakerState.CLOSED
    b.record_success()
    saved = json.loads((tmp_path / "m.json").read_text(encoding="utf-8"))
    assert saved["state"] == "closed" and saved["window"] == [1]


def test_consecutive_failures_trip_and_refuse_until_cooldown(tmp_path):
    clock = {"now": 100.0}
    b = _breaker(tmp_path, clock, consecutive_failure_trip=3, cooldown_seconds=30)
    for _ in range(2):
        b.record_failure("x")
    assert b.state is BreakerState.CLOSED
    b.record_failure("x")
    assert b.state is BreakerState.OPEN and b.is_open() and b.allow_request() is False
    clock["now"] += 31
    assert b.is_open() is False
    assert b.allow_request() is True  # the single half-open probe
    assert b.allow_request() is False  # second probe refused while one is in flight
    b.record_success()
    assert b.state is BreakerState.CLOSED and b.snapshot()["consecutive_failures"] == 0


def test_window_ratio_trips_without_consecutive_run(tmp_path):
    clock = {"now": 0.0}
    b = _breaker(
        tmp_path,
        clock,
        consecutive_failure_trip=99,
        window_calls=10,
        min_window_calls=10,
        window_failure_ratio_trip=0.5,
    )
    for i in range(10):
        # last call (i=9) is a failure: the ratio is evaluated on failures once the window is full
        if i % 2 == 0:
            b.record_success()
        else:
            b.record_failure("alt")
    assert b.state is BreakerState.OPEN
    assert "failure ratio" in b.snapshot()["last_transition"]


def test_probe_failure_reopens_with_doubled_cooldown_capped(tmp_path):
    clock = {"now": 0.0}
    b = _breaker(
        tmp_path, clock, consecutive_failure_trip=1, cooldown_seconds=10, cooldown_cap_seconds=35
    )
    b.record_failure("f")
    for expected in (20.0, 35.0, 35.0):
        clock["now"] += b.snapshot()["cooldown_seconds"] + 0.1
        assert b.allow_request() is True
        b.record_failure("probe")
        assert b.snapshot()["cooldown_seconds"] == expected
    assert b.snapshot()["trips"] == 4


def test_unreadable_state_file_fails_safe_open(tmp_path):
    clock = {"now": 0.0}
    (tmp_path / "m.json").write_text("{corrupt", encoding="utf-8")
    b = _breaker(tmp_path, clock)
    assert b.is_open() is True and b.allow_request() is False


def test_two_instances_share_persisted_state(tmp_path):
    clock = {"now": 0.0}
    a = _breaker(tmp_path, clock, consecutive_failure_trip=2)
    other = _breaker(tmp_path, clock, consecutive_failure_trip=2)
    a.record_failure("1")
    other.record_failure("2")
    assert a.is_open() and other.is_open()  # cross-instance (multi-process) visibility
    a.reset()
    assert other.state is BreakerState.CLOSED
