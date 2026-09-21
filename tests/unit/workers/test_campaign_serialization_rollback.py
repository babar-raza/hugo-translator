"""TC-APT-046 step 1: the code-free rollback switch for TC-APT-044's lock narrowing.

``translation_engine.concurrency.force_serialize_all_backends`` must default to the
safe (pre-044, fully-serialized) behaviour on the campaign path, must be flippable
without a code change, and must fail safe when config cannot be read.
"""

import threading
import time
from concurrent.futures import ThreadPoolExecutor

import src.workers.campaign_runner as campaign_runner
from src.workers.campaign_runner import _force_serialize_all_backends


def test_switch_defaults_to_serialized_when_key_is_absent(monkeypatch):
    monkeypatch.setattr("src.utils.config_loader.get_global_config", lambda: {})

    assert _force_serialize_all_backends() is True


def test_switch_reads_false_from_config(monkeypatch):
    monkeypatch.setattr(
        "src.utils.config_loader.get_global_config",
        lambda: {"translation_engine": {"concurrency": {"force_serialize_all_backends": False}}},
    )

    assert _force_serialize_all_backends() is False


def test_switch_fails_safe_when_config_cannot_be_read(monkeypatch):
    def _boom():
        raise RuntimeError("config unavailable")

    monkeypatch.setattr("src.utils.config_loader.get_global_config", _boom)

    assert _force_serialize_all_backends() is True


def test_shipped_config_still_carries_the_switch():
    """The rollback must stay reachable without editing code."""
    from src.utils.config_loader import get_global_config

    concurrency = (get_global_config().get("translation_engine") or {}).get("concurrency") or {}

    assert "force_serialize_all_backends" in concurrency


class _Runner:
    """Only the rollback machinery, isolated from CampaignRunner's heavy __init__."""

    _rollback_serialization = campaign_runner.CampaignRunner._rollback_serialization

    def __init__(self, force_serialize: bool) -> None:
        self._force_serialize_lock = threading.RLock()
        self._force_serialize = force_serialize


def _max_overlap(runner: _Runner, workers: int = 3, delay: float = 0.15) -> int:
    guard = threading.Lock()
    state = {"active": 0, "max": 0}
    barrier = threading.Barrier(workers)

    def _job(_index: int) -> None:
        barrier.wait(timeout=10)
        with runner._rollback_serialization():
            with guard:
                state["active"] += 1
                state["max"] = max(state["max"], state["active"])
            time.sleep(delay)
            with guard:
                state["active"] -= 1

    with ThreadPoolExecutor(max_workers=workers) as pool:
        list(pool.map(_job, range(workers)))
    return state["max"]


def test_switch_on_serializes_concurrent_engine_calls():
    assert _max_overlap(_Runner(force_serialize=True)) == 1


def test_switch_off_lets_engine_calls_overlap():
    assert _max_overlap(_Runner(force_serialize=False)) == 3
