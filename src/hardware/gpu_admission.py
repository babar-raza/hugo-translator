"""
GPUAdmissionController: real-telemetry cross-process admission control for
concurrent GPU translation shard processes.

Taskcard VR-01 (plans/healing/campaign-tm-concurrency-operations-healing-20260908.md,
gap CO-04): "One 418M process uses far less than the 80% VRAM budget; multiple
model processes need a measured, claimed, safe parallel design."

Relationship to ``resource_governor.py``
-----------------------------------------
``ResourceGovernor`` already implements a file-lock + JSON-registry admission
pattern, but its budget is a hand-tuned static "SM% weight" per model_id
(e.g. ``m2m100_418m: 8``) -- it never queries real GPU state. This module is a
deliberate SIBLING, not an extension of that class:

- Retrofitting real VRAM MiB + temperature onto ``ResourceGovernor`` would mean
  overloading its ``sm_weight``/``sm_ceiling_percent`` fields to secretly mean
  something else, which would make both harder to audit.
- The two controllers can run side by side (a shard may hold a slot in both
  registries at once); this module's registry/lock files are entirely
  separate from ``resource_governor.py``'s, so they never race each other.
- The cross-process safety primitive (portalocker file lock + PID-validated
  stale-entry cleanup) is intentionally copied from ``ResourceGovernor``
  because it is already proven correct under concurrent shard startups.

Telemetry sourcing -- measured empirically 2026-09-09 (RTX 4090 Laptop, 16 GB,
Windows/WDDM driver 616.56, torch 2.7.1+cu118; see
docs/operations/vr-01-concurrency-measurement.md for the full transcript).
**This finding reverses the initial design assumption and is the single most
important empirical result behind this module's probe choice:**

- ``nvidia-smi --query-gpu=memory.used`` is DEVICE-WIDE and CORRECT: a
  from-a-separate-process holder allocating 0, then ~512 MiB, then ~4096 MiB
  produced nvidia-smi readings of ~0, ~967, and ~4551 MiB respectively when
  queried from a second, unrelated observer process -- it tracks other
  processes' real allocations accurately and immediately, and returns to ~0
  as soon as the holder exits.
- ``torch.cuda.mem_get_info()`` (which wraps the device-wide
  ``cudaMemGetInfo`` CUDA API and, in principle, should show the same thing)
  did **NOT** track the sibling's allocation AT ALL in the same three-way
  test: it reported the exact same ``free_mib=15074.0`` / ``total_mib=16375.5``
  every single time, regardless of whether the sibling process held 0, 512,
  or 4096 MiB. On this machine's Windows/WDDM driver, ``mem_get_info()``
  behaves as a per-process-cached or otherwise stale figure for THIS
  purpose, not a live cross-process signal -- despite being device-scoped by
  API contract on Linux/TCC systems.
- Consequence: ``nvidia-smi`` is used as the PRIMARY and only trusted
  device-wide VRAM probe in this module. ``torch.cuda.mem_get_info()`` is
  used only as a last-resort fallback when nvidia-smi cannot be invoked at
  all (e.g. not on PATH), and that fallback's telemetry is explicitly
  labelled as having unverified cross-process visibility so a caller/log
  reader is never misled into treating it as equivalent evidence.
- Temperature has no torch API at all, so it is always read via nvidia-smi.

Design goals (mirrors ``ResourceGovernor``)
--------------------------------------------
- Two independent denial checks, either can refuse admission:
    1. Thermal ceiling: current GPU temperature (nvidia-smi) >= configured
       ceiling. Independent of VRAM bookkeeping -- protects against TDR even
       if VRAM headroom looks fine.
    2. VRAM ceiling, checked TWO ways so neither signal is trusted blindly:
         a. Reservation ledger: sum of every currently-registered process's
            declared MiB reservation (this is the TOCTOU-safe view: a sibling
            process that has been granted a slot but has not finished loading
            its model yet has no allocation for a live probe to see, but its
            reservation is already in the ledger).
         b. Live probe: current device-wide used MiB (mem_get_info /
            nvidia-smi) -- catches VRAM consumed by anything NOT going
            through this admission controller (an untracked process, driver
            overhead drift, etc).
       Admission is granted only when BOTH projected totals stay under budget.
- Crash safe: stale registry entries are PID-validated (via psutil) on every
  request, exactly like ``ResourceGovernor``.
- Zero network dependency; file-based; degrades to "always grant" (with a
  loud warning) when portalocker is unavailable, matching
  ``ResourceGovernor``'s existing fallback behaviour.

NOT wired into any production launcher by default. See VR-01's Status/scope
in the healing plan -- integration is a decision for the orchestrating
session after reviewing the measured evidence in
``data/summaries/vr-01-concurrency-measurement-*.json``.
"""

from __future__ import annotations

import json
import logging
import os
import subprocess
import time
from pathlib import Path
from typing import Callable, Optional

try:
    import portalocker  # type: ignore

    _HAS_PORTALOCKER = True
except ImportError:
    _HAS_PORTALOCKER = False

try:
    import psutil  # type: ignore

    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

logger = logging.getLogger(__name__)

_REGISTRY_FILENAME = ".local/gpu_admission_registry.json"
_LOCK_FILENAME = ".local/gpu_admission_registry.lock"

# Fallback per-process VRAM reservations (MiB) when the caller does not supply
# one explicitly. Calibrated from VR-01's measured evidence: cached m2m100_418m
# on this machine allocates ~935 MiB per process (see
# docs/operations/vr-01-concurrency-measurement.md); rounded up for headroom.
_DEFAULT_PER_PROCESS_VRAM_MIB: dict[str, float] = {
    "m2m100_418m": 1100.0,
}
_DEFAULT_PER_PROCESS_VRAM_MIB_FALLBACK = 1500.0

# Type for a VRAM probe: returns (used_mib, total_mib, source_label)
VramProbe = Callable[[], tuple[float, float, str]]
# Type for a temperature probe: returns degrees Celsius
TempProbe = Callable[[], float]


class TelemetryError(RuntimeError):
    """Raised when neither telemetry source can be read."""


def query_vram_mib() -> tuple[float, float, str]:
    """
    Return (used_mib, total_mib, source) for the whole GPU device (ALL
    processes, not just the caller).

    nvidia-smi is the PRIMARY and preferred source -- see the module
    docstring's empirical finding: on this machine's Windows/WDDM driver,
    ``torch.cuda.mem_get_info()`` does NOT reflect sibling processes' VRAM
    usage (it returned an identical reading regardless of a 0/512/4096 MiB
    sibling allocation), so it cannot be trusted as the primary cross-process
    signal despite being device-scoped by API contract. It is used here only
    as a last-resort fallback when nvidia-smi itself cannot be invoked, with
    the returned source label explicitly flagging that reduced trust.
    """
    try:
        return _query_vram_mib_nvidia_smi()
    except TelemetryError as smi_exc:
        logger.warning(
            "[gpu_admission] nvidia-smi VRAM probe failed (%s); falling back to "
            "torch.cuda.mem_get_info(), which measured evidence shows does NOT "
            "reliably reflect other processes' usage on this machine's driver -- "
            "see docs/operations/vr-01-concurrency-measurement.md",
            smi_exc,
        )
        try:
            import torch  # type: ignore

            if torch.cuda.is_available():
                free_b, total_b = torch.cuda.mem_get_info(0)
                used_mib = (total_b - free_b) / (1024**2)
                total_mib = total_b / (1024**2)
                return used_mib, total_mib, "torch.cuda.mem_get_info (UNVERIFIED cross-process visibility)"
        except Exception as torch_exc:  # pragma: no cover - torch absent/broken is expected sometimes
            raise TelemetryError(
                f"nvidia-smi failed ({smi_exc}) and torch.cuda.mem_get_info fallback "
                f"also failed: {torch_exc}"
            ) from torch_exc
        raise TelemetryError(f"nvidia-smi failed and CUDA unavailable for fallback: {smi_exc}") from smi_exc


def query_vram_mib_nvidia_smi_only() -> tuple[float, float, str]:
    """Strict nvidia-smi probe with NO fallback to ``torch.cuda.mem_get_info()``.

    ``query_vram_mib()`` falls back to ``mem_get_info()`` if nvidia-smi cannot
    be run at all, purely so a caller gets SOME number rather than none -- but
    that fallback has measured evidence (module docstring) of NOT reflecting
    other processes' usage on this machine's driver. Use this strict variant
    wherever failing closed (denying admission / raising) is preferable to
    silently trusting an unverified, possibly stale single-process signal --
    e.g. from a lightweight coordinator/benchmark harness that never loads a
    model itself and has no other reason to want a CUDA context.
    """
    return _query_vram_mib_nvidia_smi()


def _query_vram_mib_nvidia_smi() -> tuple[float, float, str]:
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=memory.used,memory.total", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        used_str, total_str = result.stdout.strip().split("\n")[0].split(",")
        return float(used_str.strip()), float(total_str.strip()), "nvidia-smi"
    except (subprocess.SubprocessError, FileNotFoundError, ValueError, OSError) as exc:
        raise TelemetryError(f"could not query GPU VRAM via torch or nvidia-smi: {exc}") from exc


def query_temperature_c() -> float:
    """Return current GPU temperature in Celsius via nvidia-smi (no torch API exists)."""
    try:
        result = subprocess.run(
            ["nvidia-smi", "--query-gpu=temperature.gpu", "--format=csv,noheader,nounits"],
            capture_output=True,
            text=True,
            timeout=10,
            check=True,
        )
        return float(result.stdout.strip().split("\n")[0])
    except (subprocess.SubprocessError, FileNotFoundError, ValueError, OSError) as exc:
        raise TelemetryError(f"could not query GPU temperature via nvidia-smi: {exc}") from exc


class GPUAdmissionController:
    """
    File-lock-based admission controller gated on REAL VRAM + temperature
    telemetry (as opposed to ``ResourceGovernor``'s static SM% estimates).

    Usage
    -----
    controller = GPUAdmissionController()
    granted, reason, info = controller.request_admission(shard_id, "m2m100_418m")
    if not granted:
        sys.exit(f"No admission: {reason}")
    atexit.register(controller.release_admission)
    # ... load model, translate, etc ...
    """

    def __init__(
        self,
        registry_path: Optional[str] = None,
        vram_budget_percent: float = 80.0,
        thermal_ceiling_c: float = 80.0,
        wait_interval_sec: int = 60,
        max_wait_attempts: int = 10,
        root: Optional[Path] = None,
        vram_probe: Optional[VramProbe] = None,
        temp_probe: Optional[TempProbe] = None,
        per_process_vram_mib: Optional[dict[str, float]] = None,
    ) -> None:
        _root = root or Path(__file__).parent.parent.parent
        self._registry = _root / (registry_path or _REGISTRY_FILENAME)
        self._lock_file = _root / _LOCK_FILENAME
        self._registry.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.vram_budget_percent = vram_budget_percent
        self.thermal_ceiling_c = thermal_ceiling_c
        self.wait_interval = wait_interval_sec
        self.max_attempts = max_wait_attempts
        self._vram_probe: VramProbe = vram_probe or query_vram_mib
        self._temp_probe: TempProbe = temp_probe or query_temperature_c
        self._per_process_vram_mib = dict(_DEFAULT_PER_PROCESS_VRAM_MIB)
        if per_process_vram_mib:
            self._per_process_vram_mib.update(per_process_vram_mib)
        self._pid = str(os.getpid())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def reservation_for(self, model_id: str) -> float:
        return self._per_process_vram_mib.get(model_id, _DEFAULT_PER_PROCESS_VRAM_MIB_FALLBACK)

    def request_admission(
        self,
        shard_id: str,
        model_id: str,
        reserve_vram_mib: Optional[float] = None,
    ) -> tuple[bool, str, dict]:
        """
        Try to admit one shard process. Returns (granted, reason, telemetry).

        ``telemetry`` always carries whatever was actually measured (temp_c,
        used_mib, total_mib, source) even on denial, so callers/tests can
        assert on the real numbers that drove the decision.
        """
        reserve_mib = reserve_vram_mib if reserve_vram_mib is not None else self.reservation_for(model_id)
        telemetry: dict = {}

        # Check 1: thermal ceiling -- independent of VRAM bookkeeping.
        try:
            temp_c = self._temp_probe()
            telemetry["temp_c"] = temp_c
        except TelemetryError as exc:
            logger.warning("[gpu_admission] temperature probe failed (denying for safety): %s", exc)
            return False, f"temperature probe failed — denying for safety: {exc}", telemetry

        if temp_c >= self.thermal_ceiling_c:
            return (
                False,
                f"GPU temperature {temp_c:.0f}C >= thermal ceiling {self.thermal_ceiling_c:.0f}C",
                telemetry,
            )

        if not _HAS_PORTALOCKER:
            logger.warning("[gpu_admission] portalocker not available; skipping admission check")
            return True, "portalocker unavailable — skipping", telemetry

        try:
            with portalocker.Lock(str(self._lock_file), timeout=30, mode="a+") as fh:
                fh.seek(0)
                registry = self._read_registry()
                registry = self._cleanup_stale(registry)

                if self._pid in registry:
                    self._write_registry(registry)
                    return True, "already registered", telemetry

                # Check 2a: reservation ledger (TOCTOU-safe view of siblings
                # that may not have finished loading their model yet).
                reserved_by_others = sum(e.get("reserved_vram_mib", 0.0) for e in registry.values())
                projected_reserved = reserved_by_others + reserve_mib

                # Check 2b: live device-wide probe (catches untracked
                # consumers the reservation ledger cannot see).
                try:
                    used_mib, total_mib, source = self._vram_probe()
                except TelemetryError as exc:
                    self._write_registry(registry)  # persist stale-cleaned version
                    logger.warning("[gpu_admission] VRAM probe failed (denying for safety): %s", exc)
                    return False, f"VRAM probe failed — denying for safety: {exc}", telemetry

                telemetry.update({"used_mib": used_mib, "total_mib": total_mib, "vram_source": source})
                budget_mib = total_mib * (self.vram_budget_percent / 100.0)
                projected_live = used_mib + reserve_mib
                telemetry.update(
                    {
                        "budget_mib": budget_mib,
                        "projected_reserved_mib": projected_reserved,
                        "projected_live_mib": projected_live,
                        "reserve_mib": reserve_mib,
                    }
                )

                if projected_reserved > budget_mib:
                    active = [f"{e['shard_id']}({e['model_id']})" for e in registry.values()]
                    self._write_registry(registry)
                    return (
                        False,
                        f"reservation ledger {projected_reserved:.0f}MiB exceeds budget "
                        f"{budget_mib:.0f}MiB ({self.vram_budget_percent:.0f}% of {total_mib:.0f}MiB). "
                        f"Active: {active}",
                        telemetry,
                    )

                if projected_live > budget_mib:
                    self._write_registry(registry)
                    return (
                        False,
                        f"live VRAM probe ({source}) {used_mib:.0f}MiB + reserve {reserve_mib:.0f}MiB "
                        f"= {projected_live:.0f}MiB exceeds budget {budget_mib:.0f}MiB "
                        f"({self.vram_budget_percent:.0f}% of {total_mib:.0f}MiB)",
                        telemetry,
                    )

                registry[self._pid] = {
                    "shard_id": shard_id,
                    "model_id": model_id,
                    "reserved_vram_mib": reserve_mib,
                    "start_time": time.time(),
                    "pid": int(self._pid),
                }
                self._write_registry(registry)
                return (
                    True,
                    f"granted (reserved {projected_reserved:.0f}MiB / live {projected_live:.0f}MiB "
                    f"<= budget {budget_mib:.0f}MiB)",
                    telemetry,
                )

        except portalocker.exceptions.LockException:
            return False, "could not acquire registry lock within 30 s", telemetry
        except TelemetryError as exc:
            logger.warning("[gpu_admission] telemetry error (denying for safety): %s", exc)
            return False, f"telemetry error — denying for safety: {exc}", telemetry
        except Exception as exc:
            logger.warning("[gpu_admission] request_admission error (denying for safety): %s", exc)
            return False, f"admission controller error — denying for safety: {exc}", telemetry

    def release_admission(self) -> None:
        """Remove this process's registry entry. Call via atexit or finally. Never raises."""
        if not _HAS_PORTALOCKER:
            return
        try:
            with portalocker.Lock(str(self._lock_file), timeout=10, mode="a+"):
                registry = self._read_registry()
                registry = self._cleanup_stale(registry)
                registry.pop(self._pid, None)
                self._write_registry(registry)
        except Exception as exc:
            logger.debug("[gpu_admission] release_admission error (ignored): %s", exc)

    def wait_for_admission(self, shard_id: str, model_id: str, reserve_vram_mib: Optional[float] = None) -> bool:
        """Block until admission is granted or max_attempts is exhausted."""
        for attempt in range(self.max_attempts):
            granted, reason, _telemetry = self.request_admission(shard_id, model_id, reserve_vram_mib)
            if granted:
                if attempt > 0:
                    print(f"[gpu_admission] Admission granted on attempt {attempt + 1}: {reason}", flush=True)
                return True
            wait_min = self.wait_interval / 60
            print(
                f"[gpu_admission] Admission denied (attempt {attempt + 1}/{self.max_attempts}): "
                f"{reason}. Waiting {wait_min:.1f} min...",
                flush=True,
            )
            time.sleep(self.wait_interval)
        print(
            f"[gpu_admission] No admission after {self.max_attempts} attempts "
            f"({self.max_attempts * self.wait_interval / 60:.1f} min). Giving up.",
            flush=True,
        )
        return False

    def current_registry(self) -> dict:
        """Return a cleaned copy of the registry (for diagnostics)."""
        registry = self._read_registry()
        return self._cleanup_stale(registry)

    # ------------------------------------------------------------------
    # Internal helpers (mirrors ResourceGovernor's registry I/O exactly)
    # ------------------------------------------------------------------

    def _read_registry(self) -> dict:
        try:
            if self._registry.exists():
                text = self._registry.read_text(encoding="utf-8")
                if text.strip():
                    return json.loads(text)
        except (json.JSONDecodeError, OSError):
            pass
        return {}

    def _write_registry(self, data: dict) -> None:
        self._registry.write_text(json.dumps(data, indent=2), encoding="utf-8")

    def _cleanup_stale(self, registry: dict) -> dict:
        if not _HAS_PSUTIL:
            return registry
        alive: dict = {}
        for pid_str, entry in registry.items():
            try:
                pid = int(pid_str)
                if psutil.pid_exists(pid):
                    alive[pid_str] = entry
            except (ValueError, OSError):
                pass
        stale = len(registry) - len(alive)
        if stale:
            logger.debug("[gpu_admission] Cleaned %d stale registry entries", stale)
        return alive


# ---------------------------------------------------------------------------
# Convenience factory that reads limits from config/global.yaml if present
# ---------------------------------------------------------------------------


def make_admission_controller(root: Optional[Path] = None) -> GPUAdmissionController:
    """
    Build a GPUAdmissionController from config/global.yaml's `gpu_admission`
    section. Falls back to defaults if config is missing or malformed.
    """
    _root = root or Path(__file__).parent.parent.parent
    cfg_path = _root / "config" / "global.yaml"
    defaults = {
        "vram_budget_percent": 80.0,
        "thermal_ceiling_c": 80.0,
        "wait_interval_sec": 60,
        "max_wait_attempts": 10,
    }
    per_process: dict[str, float] = {}
    try:
        import yaml  # type: ignore

        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        gpu_cfg = raw.get("gpu_admission", {})
        if "vram_budget_percent" in gpu_cfg:
            defaults["vram_budget_percent"] = float(gpu_cfg["vram_budget_percent"])
        if "thermal_ceiling_celsius" in gpu_cfg:
            defaults["thermal_ceiling_c"] = float(gpu_cfg["thermal_ceiling_celsius"])
        if "wait_interval_sec" in gpu_cfg:
            defaults["wait_interval_sec"] = int(gpu_cfg["wait_interval_sec"])
        if "max_wait_attempts" in gpu_cfg:
            defaults["max_wait_attempts"] = int(gpu_cfg["max_wait_attempts"])
        for model_id, mib in gpu_cfg.get("per_process_vram_mib", {}).items():
            if model_id == "default":
                continue
            per_process[str(model_id)] = float(mib)
    except Exception:
        pass
    return GPUAdmissionController(root=_root, per_process_vram_mib=per_process or None, **defaults)
