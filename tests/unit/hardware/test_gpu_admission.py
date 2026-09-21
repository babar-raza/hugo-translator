"""
Unit tests for GPUAdmissionController (src/hardware/gpu_admission.py).

All tests use fake/mocked VRAM + temperature probes -- no GPU or nvidia-smi
required, so this suite runs fast in CI. Real-hardware measurement lives in
scripts/benchmarking/gpu_concurrency_bench.py and
data/summaries/vr-01-concurrency-measurement-*.json (VR-01 evidence).

Tests cover:
- Admission granted when VRAM + thermal budget is available
- Admission denied when reservation ledger would exceed the VRAM budget
- Admission denied when the live VRAM probe alone would exceed budget
  (catches untracked consumers the reservation ledger cannot see)
- Admission denied when temperature is at/above the thermal ceiling,
  independent of VRAM headroom
- Stale PID cleanup (dead PIDs removed from registry)
- Idempotent re-registration (same PID already registered)
- release_admission() removes own entry
- Concurrent lock safety (two threads racing for one slot)
- Telemetry probe failure denies for safety rather than granting blind
- make_admission_controller() reads calibrated values from config
"""
from __future__ import annotations

import json
import os
import sys
import threading
import time
from pathlib import Path
from typing import Generator
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from src.hardware.gpu_admission import (
    GPUAdmissionController,
    TelemetryError,
    make_admission_controller,
)


# ---------------------------------------------------------------------------
# Fixtures / helpers
# ---------------------------------------------------------------------------


def _fake_vram_probe(used_mib: float, total_mib: float = 16376.0, source: str = "fake"):
    def _probe():
        return used_mib, total_mib, source

    return _probe


def _fake_temp_probe(temp_c: float):
    def _probe():
        return temp_c

    return _probe


@pytest.fixture()
def tmp_controller(tmp_path: Path) -> Generator[GPUAdmissionController, None, None]:
    """Controller backed by a temp dir, cool GPU, plenty of free VRAM by default."""
    ctrl = GPUAdmissionController(
        registry_path=".registry.json",
        vram_budget_percent=80.0,
        thermal_ceiling_c=80.0,
        wait_interval_sec=0,
        max_wait_attempts=3,
        root=tmp_path,
        vram_probe=_fake_vram_probe(used_mib=0.0),
        temp_probe=_fake_temp_probe(60.0),
        per_process_vram_mib={"m2m100_418m": 1100.0},
    )
    yield ctrl
    ctrl.release_admission()


def _write_fake_entry(ctrl: GPUAdmissionController, pid: int, model_id: str, reserved_mib: float) -> None:
    reg = ctrl._read_registry()
    reg[str(pid)] = {
        "shard_id": f"fake_{pid}",
        "model_id": model_id,
        "reserved_vram_mib": reserved_mib,
        "start_time": time.time(),
        "pid": pid,
    }
    ctrl._write_registry(reg)


# ---------------------------------------------------------------------------
# Basic grant / deny on VRAM
# ---------------------------------------------------------------------------


class TestVramAdmission:
    def test_first_slot_granted_with_plenty_of_headroom(self, tmp_controller: GPUAdmissionController) -> None:
        granted, reason, telemetry = tmp_controller.request_admission("s1", "m2m100_418m")
        assert granted, f"Expected grant; got: {reason}"
        assert telemetry["used_mib"] == 0.0
        assert telemetry["total_mib"] == 16376.0

    def test_denied_when_reservation_ledger_exceeds_budget(self, tmp_controller: GPUAdmissionController) -> None:
        # Budget = 80% of 16376 = 13100.8 MiB. Fill it with fake reservations.
        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            _write_fake_entry(tmp_controller, pid=100001, model_id="m2m100_418m", reserved_mib=13000.0)
            granted, reason, telemetry = tmp_controller.request_admission("s2", "m2m100_418m")

        assert not granted, f"Expected denial; got granted with: {reason}"
        assert "reservation ledger" in reason
        assert telemetry["projected_reserved_mib"] > telemetry["budget_mib"]

    def test_denied_when_live_probe_alone_exceeds_budget(self, tmp_path: Path) -> None:
        # No sibling reservations at all -- but the live probe already shows
        # near-full VRAM (an untracked consumer). Reservation ledger check
        # alone would grant; the live-probe check must still catch this.
        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            wait_interval_sec=0,
            max_wait_attempts=1,
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=13000.0),  # untracked usage
            temp_probe=_fake_temp_probe(60.0),
            per_process_vram_mib={"m2m100_418m": 1100.0},
        )
        granted, reason, telemetry = ctrl.request_admission("s1", "m2m100_418m")
        assert not granted, f"Expected denial from live probe; got: {reason}"
        assert "live VRAM probe" in reason
        assert telemetry["projected_live_mib"] > telemetry["budget_mib"]

    def test_admission_fits_exactly_under_budget(self, tmp_path: Path) -> None:
        # Budget for a 10000 MiB "total" device at 80% = 8000 MiB.
        # Two 1000 MiB reservations = 2000 <= 8000: fine.
        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            wait_interval_sec=0,
            max_wait_attempts=1,
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=10000.0),
            temp_probe=_fake_temp_probe(60.0),
            per_process_vram_mib={"m2m100_418m": 1000.0},
        )
        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            _write_fake_entry(ctrl, pid=100001, model_id="m2m100_418m", reserved_mib=1000.0)
            granted, reason, telemetry = ctrl.request_admission("s2", "m2m100_418m")
        assert granted, f"Expected grant; got: {reason}"
        assert telemetry["projected_reserved_mib"] == 2000.0
        assert telemetry["budget_mib"] == 8000.0

    def test_third_process_denied_once_ledger_crosses_budget(self, tmp_path: Path) -> None:
        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            wait_interval_sec=0,
            max_wait_attempts=1,
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=3000.0),  # budget = 2400
            temp_probe=_fake_temp_probe(60.0),
            per_process_vram_mib={"m2m100_418m": 1000.0},
        )
        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            _write_fake_entry(ctrl, pid=100001, model_id="m2m100_418m", reserved_mib=1000.0)
            _write_fake_entry(ctrl, pid=100002, model_id="m2m100_418m", reserved_mib=1000.0)
            granted, reason, _telemetry = ctrl.request_admission("s3", "m2m100_418m")
        assert not granted, f"Expected denial (2000+1000=3000 > 2400 budget); got: {reason}"


# ---------------------------------------------------------------------------
# Thermal ceiling
# ---------------------------------------------------------------------------


class TestThermalAdmission:
    def test_denied_when_temperature_at_ceiling(self, tmp_path: Path) -> None:
        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            wait_interval_sec=0,
            max_wait_attempts=1,
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=0.0),  # tons of VRAM headroom
            temp_probe=_fake_temp_probe(80.0),  # exactly at ceiling
        )
        granted, reason, telemetry = ctrl.request_admission("s1", "m2m100_418m")
        assert not granted, f"Expected thermal denial; got: {reason}"
        assert "temperature" in reason
        assert telemetry["temp_c"] == 80.0

    def test_denied_when_temperature_above_ceiling_even_with_free_vram(self, tmp_path: Path) -> None:
        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=78.0,
            wait_interval_sec=0,
            max_wait_attempts=1,
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=0.0),
            temp_probe=_fake_temp_probe(85.0),
        )
        granted, reason, _telemetry = ctrl.request_admission("s1", "m2m100_418m")
        assert not granted
        assert "temperature" in reason

    def test_granted_when_temperature_below_ceiling(self, tmp_controller: GPUAdmissionController) -> None:
        granted, _reason, telemetry = tmp_controller.request_admission("s1", "m2m100_418m")
        assert granted
        assert telemetry["temp_c"] == 60.0


# ---------------------------------------------------------------------------
# Telemetry failure handling
# ---------------------------------------------------------------------------


class TestTelemetryFailure:
    def test_temperature_probe_failure_denies(self, tmp_path: Path) -> None:
        def _broken_temp():
            raise TelemetryError("nvidia-smi not found")

        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=0.0),
            temp_probe=_broken_temp,
        )
        granted, reason, _telemetry = ctrl.request_admission("s1", "m2m100_418m")
        assert not granted
        assert "temperature probe failed" in reason

    def test_vram_probe_failure_denies(self, tmp_path: Path) -> None:
        def _broken_vram():
            raise TelemetryError("nvidia-smi not found")

        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            root=tmp_path,
            vram_probe=_broken_vram,
            temp_probe=_fake_temp_probe(60.0),
        )
        granted, reason, _telemetry = ctrl.request_admission("s1", "m2m100_418m")
        assert not granted
        assert "VRAM probe failed" in reason


# ---------------------------------------------------------------------------
# Stale cleanup / idempotency / release
# ---------------------------------------------------------------------------


class TestStaleCleanup:
    def test_dead_pid_removed_before_budget_check(self, tmp_controller: GPUAdmissionController) -> None:
        try:
            import psutil  # noqa: F401
        except ImportError:
            pytest.skip("psutil not available")

        dead_pid = 999_999_999
        _write_fake_entry(tmp_controller, pid=dead_pid, model_id="m2m100_418m", reserved_mib=13000.0)
        granted, reason, _telemetry = tmp_controller.request_admission("s1", "m2m100_418m")
        assert granted, f"Expected grant after stale cleanup; got: {reason}"

    def test_cleanup_no_op_without_psutil(self, tmp_controller: GPUAdmissionController) -> None:
        registry = {"999999997": {"shard_id": "x", "model_id": "m2m100_418m", "reserved_vram_mib": 1000.0}}
        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            cleaned = tmp_controller._cleanup_stale(registry)
        assert cleaned == registry


class TestIdempotency:
    def test_same_pid_granted_twice(self, tmp_controller: GPUAdmissionController) -> None:
        granted1, _r1, _t1 = tmp_controller.request_admission("s1", "m2m100_418m")
        granted2, reason2, _t2 = tmp_controller.request_admission("s1", "m2m100_418m")
        assert granted1 and granted2
        assert "already registered" in reason2

    def test_registry_has_one_entry_after_double_registration(self, tmp_controller: GPUAdmissionController) -> None:
        tmp_controller.request_admission("s1", "m2m100_418m")
        tmp_controller.request_admission("s1", "m2m100_418m")
        reg = tmp_controller._read_registry()
        assert len(reg) == 1


class TestReleaseAdmission:
    def test_release_removes_own_entry(self, tmp_controller: GPUAdmissionController) -> None:
        tmp_controller.request_admission("s1", "m2m100_418m")
        assert str(os.getpid()) in tmp_controller._read_registry()
        tmp_controller.release_admission()
        assert str(os.getpid()) not in tmp_controller._read_registry()

    def test_release_is_safe_when_not_registered(self, tmp_controller: GPUAdmissionController) -> None:
        tmp_controller.release_admission()  # must not raise


# ---------------------------------------------------------------------------
# Concurrency
# ---------------------------------------------------------------------------


class TestConcurrency:
    def test_two_threads_only_ledger_stays_within_budget(self, tmp_path: Path) -> None:
        """With a tight budget only one of two racing requests should be granted
        (both share this test process's PID, so idempotency may also grant the
        second -- the invariant that must always hold is the ledger total)."""
        results: list[tuple[bool, str]] = []
        lock = threading.Lock()

        def try_admission(shard_id: str) -> None:
            ctrl = GPUAdmissionController(
                registry_path=".registry.json",
                vram_budget_percent=80.0,
                thermal_ceiling_c=80.0,
                wait_interval_sec=0,
                max_wait_attempts=1,
                root=tmp_path,
                vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=1250.0),  # budget=1000
                temp_probe=_fake_temp_probe(60.0),
                per_process_vram_mib={"m2m100_418m": 1000.0},
            )
            with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
                granted, reason, _telemetry = ctrl.request_admission(shard_id, "m2m100_418m")
            with lock:
                results.append((granted, reason))

        t1 = threading.Thread(target=try_admission, args=("s1",))
        t2 = threading.Thread(target=try_admission, args=("s2",))
        t1.start()
        t2.start()
        t1.join(timeout=10)
        t2.join(timeout=10)

        reg = GPUAdmissionController(
            registry_path=".registry.json", root=tmp_path
        )._read_registry()
        combined = sum(e.get("reserved_vram_mib", 0.0) for e in reg.values())
        assert combined <= 1000.0, f"Registry reservation {combined}MiB exceeds budget 1000MiB"
        assert len(results) == 2


# ---------------------------------------------------------------------------
# wait_for_admission
# ---------------------------------------------------------------------------


class TestWaitForAdmission:
    def test_returns_true_when_immediately_granted(self, tmp_controller: GPUAdmissionController) -> None:
        assert tmp_controller.wait_for_admission("s1", "m2m100_418m")

    def test_returns_false_when_all_attempts_exhausted(self, tmp_path: Path) -> None:
        ctrl = GPUAdmissionController(
            registry_path=".registry.json",
            vram_budget_percent=80.0,
            thermal_ceiling_c=80.0,
            wait_interval_sec=0,
            max_wait_attempts=2,
            root=tmp_path,
            vram_probe=_fake_vram_probe(used_mib=0.0, total_mib=1000.0),  # budget=800
            temp_probe=_fake_temp_probe(60.0),
            per_process_vram_mib={"m2m100_418m": 1000.0},
        )
        with patch("src.hardware.gpu_admission._HAS_PSUTIL", False):
            _write_fake_entry(ctrl, pid=100001, model_id="m2m100_418m", reserved_mib=800.0)
            result = ctrl.wait_for_admission("s2", "m2m100_418m")
        assert result is False


# ---------------------------------------------------------------------------
# make_admission_controller() factory
# ---------------------------------------------------------------------------


class TestMakeAdmissionController:
    def test_reads_config_values(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config" / "global.yaml"
        cfg.parent.mkdir()
        cfg.write_text(
            "gpu_admission:\n"
            "  enabled: true\n"
            "  vram_budget_percent: 75\n"
            "  thermal_ceiling_celsius: 79\n"
            "  wait_interval_sec: 45\n"
            "  max_wait_attempts: 6\n"
            "  per_process_vram_mib:\n"
            "    m2m100_418m: 1200\n"
            "    default: 1500\n",
            encoding="utf-8",
        )
        ctrl = make_admission_controller(root=tmp_path)
        assert ctrl.vram_budget_percent == 75.0
        assert ctrl.thermal_ceiling_c == 79.0
        assert ctrl.wait_interval == 45
        assert ctrl.max_attempts == 6
        assert ctrl.reservation_for("m2m100_418m") == 1200.0

    def test_falls_back_to_defaults(self, tmp_path: Path) -> None:
        ctrl = make_admission_controller(root=tmp_path)
        assert ctrl.vram_budget_percent == 80.0
        assert ctrl.thermal_ceiling_c == 80.0
        assert ctrl.wait_interval == 60
        assert ctrl.max_attempts == 10

    def test_ignores_malformed_config(self, tmp_path: Path) -> None:
        cfg = tmp_path / "config" / "global.yaml"
        cfg.parent.mkdir()
        cfg.write_text("gpu_admission: [not a dict]", encoding="utf-8")
        ctrl = make_admission_controller(root=tmp_path)
        assert ctrl.vram_budget_percent == 80.0


# ---------------------------------------------------------------------------
# Registry I/O
# ---------------------------------------------------------------------------


class TestRegistryIO:
    def test_read_returns_empty_when_file_missing(self, tmp_controller: GPUAdmissionController) -> None:
        assert not tmp_controller._registry.exists()
        assert tmp_controller._read_registry() == {}

    def test_read_returns_empty_on_corrupt_json(self, tmp_controller: GPUAdmissionController) -> None:
        tmp_controller._registry.write_text("NOT JSON", encoding="utf-8")
        assert tmp_controller._read_registry() == {}

    def test_write_then_read_roundtrip(self, tmp_controller: GPUAdmissionController) -> None:
        data = {"123": {"shard_id": "s1", "model_id": "m2m100_418m", "reserved_vram_mib": 1100.0}}
        tmp_controller._write_registry(data)
        assert tmp_controller._read_registry() == data
