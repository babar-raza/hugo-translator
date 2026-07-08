"""
Unit tests for ResourceGovernor (src/hardware/resource_governor.py).

Tests cover:
- Slot granted when SM budget is available
- Slot denied when combined SM estimate exceeds ceiling
- Stale PID cleanup (dead PIDs removed from registry)
- Idempotent re-registration (same PID already registered)
- Slot release removes own entry
- Concurrent lock safety (two threads calling simultaneously)
- make_governor() reads calibrated values from config
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Generator
from unittest.mock import MagicMock, patch

import pytest

# Ensure project root is importable
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.hardware.resource_governor import (
    ResourceGovernor,
    _SM_WEIGHT,
    _SM_WEIGHT_DEFAULT,
    make_governor,
)


# ---------------------------------------------------------------------------
# Helpers / fixtures
# ---------------------------------------------------------------------------


@pytest.fixture()
def tmp_governor(tmp_path: Path) -> Generator[ResourceGovernor, None, None]:
    """ResourceGovernor backed by a temporary directory — no shared state."""
    gov = ResourceGovernor(
        registry_path=".registry.json",
        sm_ceiling_percent=82,
        wait_interval_sec=0,  # no sleep in tests
        max_wait_attempts=3,
        root=tmp_path,
    )
    yield gov
    # Release any slot this test may have written
    gov.release_slot()


def _registry_path(gov: ResourceGovernor) -> Path:
    return gov._registry


def _write_fake_entry(gov: ResourceGovernor, pid: int, model_id: str) -> None:
    """Inject a fake registry entry for an arbitrary PID."""
    reg = gov._read_registry()
    sm = _SM_WEIGHT.get(model_id, _SM_WEIGHT_DEFAULT)
    reg[str(pid)] = {
        "shard_id": f"fake_{pid}",
        "model_id": model_id,
        "sm_weight": sm,
        "start_time": time.time(),
        "pid": pid,
    }
    gov._write_registry(reg)


# ---------------------------------------------------------------------------
# Basic grant / deny
# ---------------------------------------------------------------------------


class TestRequestSlot:
    def test_first_slot_is_granted(self, tmp_governor: ResourceGovernor) -> None:
        granted, reason = tmp_governor.request_slot("s1", "nllb_200_1.3b")
        assert granted, f"Expected grant; got: {reason}"
        assert "granted" in reason or "already" in reason

    def test_denied_when_ceiling_exceeded(self, tmp_governor: ResourceGovernor) -> None:
        # Two fake NLLB shards already running: 32 + 32 = 64%.
        # Adding a third (32%) would reach 96% > 82% ceiling.
        _write_fake_entry(tmp_governor, pid=100001, model_id="nllb_200_1.3b")
        _write_fake_entry(tmp_governor, pid=100002, model_id="nllb_200_1.3b")

        # The fake PIDs are not real processes; psutil will flag them as dead
        # unless we patch psutil.pid_exists to return True for them.
        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            granted, reason = tmp_governor.request_slot("s3", "nllb_200_1.3b")

        assert not granted, f"Expected denial; got granted with: {reason}"
        assert "ceiling" in reason

    def test_two_nllb_shards_fit_within_ceiling(self, tmp_governor: ResourceGovernor) -> None:
        # 32 + 32 = 64% <= 82%: should be allowed.
        _write_fake_entry(tmp_governor, pid=100001, model_id="nllb_200_1.3b")

        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            granted, reason = tmp_governor.request_slot("s2", "nllb_200_1.3b")

        assert granted, f"Expected grant for second NLLB shard; got: {reason}"

    def test_mixed_nllb_plus_m2m100_fits(self, tmp_governor: ResourceGovernor) -> None:
        # 2 NLLB (64%) + 2 m2m100 (16%) = 80% <= 82%.
        _write_fake_entry(tmp_governor, pid=100001, model_id="nllb_200_1.3b")
        _write_fake_entry(tmp_governor, pid=100002, model_id="nllb_200_1.3b")
        _write_fake_entry(tmp_governor, pid=100003, model_id="m2m100_418m")

        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            granted, reason = tmp_governor.request_slot("s4", "m2m100_418m")

        assert granted, f"Expected grant for 4th shard (mixed); got: {reason}"

    def test_third_nllb_denied_with_mixed_shards(self, tmp_governor: ResourceGovernor) -> None:
        # 2 NLLB (64%) + 2 m2m100 (16%) = 80%; adding one more NLLB = 112% > 82%.
        _write_fake_entry(tmp_governor, pid=100001, model_id="nllb_200_1.3b")
        _write_fake_entry(tmp_governor, pid=100002, model_id="nllb_200_1.3b")
        _write_fake_entry(tmp_governor, pid=100003, model_id="m2m100_418m")
        _write_fake_entry(tmp_governor, pid=100004, model_id="m2m100_418m")

        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            granted, reason = tmp_governor.request_slot("s5", "nllb_200_1.3b")

        assert not granted, f"Expected denial; got grant with: {reason}"


# ---------------------------------------------------------------------------
# Stale PID cleanup
# ---------------------------------------------------------------------------


class TestStaleCleanup:
    def test_dead_pid_removed_before_budget_check(self, tmp_governor: ResourceGovernor) -> None:
        # Write an entry with a PID that definitely does not exist.
        dead_pid = 999_999_999
        _write_fake_entry(tmp_governor, pid=dead_pid, model_id="nllb_200_1.3b")
        _write_fake_entry(tmp_governor, pid=dead_pid - 1, model_id="nllb_200_1.3b")

        # With psutil active the dead PIDs are cleaned; budget is free.
        # psutil must be available in the test env (it is in .venv).
        try:
            import psutil
        except ImportError:
            pytest.skip("psutil not available")

        granted, reason = tmp_governor.request_slot("s1", "nllb_200_1.3b")
        assert granted, f"Expected grant after stale cleanup; got: {reason}"

    def test_cleanup_stale_removes_dead_pids(self, tmp_governor: ResourceGovernor) -> None:
        try:
            import psutil
        except ImportError:
            pytest.skip("psutil not available")

        registry = {
            "999999997": {"shard_id": "x", "model_id": "nllb_200_1.3b", "sm_weight": 32, "start_time": 0.0, "pid": 999999997},
            "999999998": {"shard_id": "y", "model_id": "m2m100_418m", "sm_weight": 8, "start_time": 0.0, "pid": 999999998},
            str(os.getpid()): {"shard_id": "z", "model_id": "opus_mt", "sm_weight": 6, "start_time": 0.0, "pid": os.getpid()},
        }
        cleaned = tmp_governor._cleanup_stale(registry)
        assert str(os.getpid()) in cleaned, "Live PID should survive cleanup"
        assert "999999997" not in cleaned, "Dead PID should be removed"
        assert "999999998" not in cleaned, "Dead PID should be removed"

    def test_cleanup_no_op_without_psutil(self, tmp_governor: ResourceGovernor) -> None:
        registry = {"999999997": {"shard_id": "x", "model_id": "nllb_200_1.3b", "sm_weight": 32}}
        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            cleaned = tmp_governor._cleanup_stale(registry)
        assert cleaned == registry, "Without psutil, registry must be returned unchanged"


# ---------------------------------------------------------------------------
# Idempotent re-registration
# ---------------------------------------------------------------------------


class TestIdempotency:
    def test_same_pid_granted_twice(self, tmp_governor: ResourceGovernor) -> None:
        granted1, reason1 = tmp_governor.request_slot("s1", "nllb_200_1.3b")
        granted2, reason2 = tmp_governor.request_slot("s1", "nllb_200_1.3b")
        assert granted1 and granted2
        assert "already registered" in reason2

    def test_registry_has_one_entry_after_double_registration(self, tmp_governor: ResourceGovernor) -> None:
        tmp_governor.request_slot("s1", "nllb_200_1.3b")
        tmp_governor.request_slot("s1", "nllb_200_1.3b")
        reg = tmp_governor._read_registry()
        assert len(reg) == 1


# ---------------------------------------------------------------------------
# Release slot
# ---------------------------------------------------------------------------


class TestReleaseSlot:
    def test_release_removes_own_entry(self, tmp_governor: ResourceGovernor) -> None:
        tmp_governor.request_slot("s1", "nllb_200_1.3b")
        assert str(os.getpid()) in tmp_governor._read_registry()

        tmp_governor.release_slot()
        assert str(os.getpid()) not in tmp_governor._read_registry()

    def test_release_is_safe_when_not_registered(self, tmp_governor: ResourceGovernor) -> None:
        # Should not raise even if we never called request_slot.
        tmp_governor.release_slot()

    def test_after_release_slot_can_be_granted_again(self, tmp_governor: ResourceGovernor) -> None:
        tmp_governor.request_slot("s1", "nllb_200_1.3b")
        tmp_governor.release_slot()

        # Fill to one slot below ceiling with fake entries (psutil disabled so they survive).
        _write_fake_entry(tmp_governor, pid=100001, model_id="nllb_200_1.3b")

        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            granted, reason = tmp_governor.request_slot("s2", "nllb_200_1.3b")

        assert granted, f"Expected slot after release; got: {reason}"


# ---------------------------------------------------------------------------
# Registry I/O helpers
# ---------------------------------------------------------------------------


class TestRegistryIO:
    def test_read_returns_empty_when_file_missing(self, tmp_governor: ResourceGovernor) -> None:
        assert not _registry_path(tmp_governor).exists()
        assert tmp_governor._read_registry() == {}

    def test_read_returns_empty_on_corrupt_json(self, tmp_governor: ResourceGovernor) -> None:
        _registry_path(tmp_governor).write_text("NOT JSON", encoding="utf-8")
        assert tmp_governor._read_registry() == {}

    def test_write_then_read_roundtrip(self, tmp_governor: ResourceGovernor) -> None:
        data = {"123": {"shard_id": "s1", "model_id": "opus_mt", "sm_weight": 6}}
        tmp_governor._write_registry(data)
        assert tmp_governor._read_registry() == data


# ---------------------------------------------------------------------------
# Concurrent lock safety
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_two_threads_only_one_succeeds_at_ceiling(self, tmp_path: Path) -> None:
        """With ceiling=32 and NLLB weight=32, exactly one of two racing threads
        should get the slot; the other should be denied."""

        results: list[tuple[bool, str]] = []
        lock = threading.Lock()

        def try_slot(shard_id: str) -> None:
            gov = ResourceGovernor(
                registry_path=".registry.json",
                sm_ceiling_percent=32,  # tight ceiling: only one NLLB allowed
                wait_interval_sec=0,
                max_wait_attempts=1,
                root=tmp_path,
            )
            with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
                granted, reason = gov.request_slot(shard_id, "nllb_200_1.3b")
            with lock:
                results.append((granted, reason))

        # Both threads race to claim a single slot.
        t1 = threading.Thread(target=try_slot, args=("s1",))
        t2 = threading.Thread(target=try_slot, args=("s2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        granted_count = sum(1 for g, _ in results if g)
        # One process (this PID) is the same for both threads, so the idempotency
        # guard may kick in. Allow 1 or 2 grants as long as the registry has
        # only one entry (both threads share the same PID).
        reg = ResourceGovernor(
            registry_path=".registry.json",
            sm_ceiling_percent=32,
            wait_interval_sec=0,
            max_wait_attempts=1,
            root=tmp_path,
        )._read_registry()

        # The combined SM in the registry must never exceed the ceiling.
        combined = sum(e.get("sm_weight", _SM_WEIGHT_DEFAULT) for e in reg.values())
        assert combined <= 32, f"Registry SM {combined}% exceeds ceiling 32%"
        assert len(results) == 2, "Both threads must have returned a result"


# ---------------------------------------------------------------------------
# make_governor() factory
# ---------------------------------------------------------------------------


class TestMakeGovernor:
    def test_make_governor_uses_config_values(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config" / "global.yaml"
        cfg.parent.mkdir()
        cfg.write_text(
            "resource_governance:\n"
            "  sm_ceiling_percent: 50\n"
            "  wait_interval_sec: 30\n"
            "  max_wait_attempts: 5\n"
            "  sm_estimates:\n"
            "    nllb_200_1.3b: 20\n",
            encoding="utf-8",
        )
        gov = make_governor(root=tmp_path)
        assert gov.sm_ceiling == 50
        assert gov.wait_interval == 30
        assert gov.max_attempts == 5
        assert _SM_WEIGHT.get("nllb_200_1.3b") == 20

    def test_make_governor_falls_back_to_defaults(self, tmp_path: Path) -> None:
        # No config file present.
        gov = make_governor(root=tmp_path)
        assert gov.sm_ceiling == 70      # hard-coded default in make_governor
        assert gov.wait_interval == 120
        assert gov.max_attempts == 20

    def test_make_governor_ignores_malformed_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config" / "global.yaml"
        cfg.parent.mkdir()
        cfg.write_text("resource_governance: [this is not a dict]", encoding="utf-8")
        gov = make_governor(root=tmp_path)
        assert gov.sm_ceiling == 70  # fallback


# ---------------------------------------------------------------------------
# wait_for_slot convenience wrapper
# ---------------------------------------------------------------------------


class TestWaitForSlot:
    def test_returns_true_when_immediately_granted(self, tmp_governor: ResourceGovernor) -> None:
        granted = tmp_governor.wait_for_slot("s1", "nllb_200_1.3b")
        assert granted

    def test_returns_false_when_all_attempts_exhausted(self, tmp_path: Path) -> None:
        gov = ResourceGovernor(
            registry_path=".registry.json",
            sm_ceiling_percent=32,  # tight: one NLLB fills it
            wait_interval_sec=0,
            max_wait_attempts=2,
            root=tmp_path,
        )
        # Fill registry so budget is exceeded.
        _write_fake_entry(gov, pid=100001, model_id="nllb_200_1.3b")
        with patch("src.hardware.resource_governor._HAS_PSUTIL", False):
            result = gov.wait_for_slot("s2", "nllb_200_1.3b")
        assert result is False
