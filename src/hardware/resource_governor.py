"""
ResourceGovernor: cross-process GPU admission controller for translation shards.

Any shard that will load a GPU model MUST call wait_for_slot() before
model loading, and release_slot() on exit.  The governor uses a JSON
registry file protected by a portalocker file lock so that concurrent
shard startups are serialised at the decision point.

Design goals
------------
- Hard limit on estimated combined GPU SM% to prevent DWM starvation /
  TDR (Timeout Detection and Recovery) events.  On the Alienware m18 R2
  (RTX 4090 Laptop, 16 GB, driving display through NVIDIA in hybrid mode)
  three concurrent NLLB-1.3B shards push SM to 98%, causing Windows TDR
  (nvlddmkm Event 13) which blanks all application windows.
- Race-condition safe: registry read + stale-cleanup + own-entry-write
  happens atomically inside one file lock acquisition.
- Crash safe: stale entries are PID-validated on every request_slot()
  call; a hard-killed shard never permanently blocks future shards.
- Zero network dependency: file-based, works offline, no daemon needed.

Limits (defaults, all tunable via config/global.yaml resource_governance)
--------------------------------------------------------------------------
  sm_ceiling_percent : 70   leave ≥30 % SM for Windows DWM + OS
  wait_interval_sec  : 120  poll every 2 min when denied
  max_wait_attempts  : 20   give up after 40 min; operator re-runs shard

SM weight estimates (% of RTX 4090 Laptop SM per concurrent shard)
-------------------------------------------------------------------
  nllb_200_1.3b  : 40 %   (3 shards = 120 % → TDR; 2 shards = 80 % → safe)
  m2m100_418m    : 15 %   (2 shards = 30 %; 2 NLLB + 2 m2m100 = 110 % → deny)
  nllb_200_600m  : 25 %
  opus_mt        : 10 %
  default        : 30 %   conservative fallback for unknown model IDs
"""

from __future__ import annotations

import json
import logging
import os
import time
from pathlib import Path
from typing import Optional

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

# ---------------------------------------------------------------------------
# SM weight table: estimated GPU Streaming Multiprocessor % per concurrent
# forward-pass batch.  Two NLLB shards = 80 % → fine.  Three = 120 % → TDR.
# ---------------------------------------------------------------------------
_SM_WEIGHT: dict[str, int] = {
    # Calibrated from observed nvidia-smi: 3 NLLB-1.3B = 94% SM → each ≈ 31%.
    # m2m100-418M is ~3x smaller; proportional estimate ≈ 8%.
    # ceiling=82 → allows 2 NLLB (64%) + 2 m2m100 (16%) = 80% ≤ 82; denies 3 NLLB (96%).
    "nllb_200_1.3b": 32,
    "nllb_200_600m": 20,
    "m2m100_418m": 8,
    "m2m100_1.2b": 18,
    "opus_mt": 6,
}
_SM_WEIGHT_DEFAULT = 25

_REGISTRY_FILENAME = ".local/shard_registry.json"
_LOCK_FILENAME = ".local/shard_registry.lock"


class ResourceGovernor:
    """
    File-lock-based admission controller for GPU translation shards.

    Usage
    -----
    governor = ResourceGovernor()
    granted = governor.wait_for_slot(shard_id, model_id)
    if not granted:
        sys.exit("No slot available; re-run later.")
    atexit.register(governor.release_slot)
    # ... load model, translate, etc. ...
    """

    def __init__(
        self,
        registry_path: Optional[str] = None,
        sm_ceiling_percent: int = 70,
        wait_interval_sec: int = 120,
        max_wait_attempts: int = 20,
        root: Optional[Path] = None,
    ) -> None:
        _root = root or Path(__file__).parent.parent.parent
        self._registry = _root / (registry_path or _REGISTRY_FILENAME)
        self._lock_file = _root / _LOCK_FILENAME
        self._registry.parent.mkdir(parents=True, exist_ok=True)
        self._lock_file.parent.mkdir(parents=True, exist_ok=True)
        self.sm_ceiling = sm_ceiling_percent
        self.wait_interval = wait_interval_sec
        self.max_attempts = max_wait_attempts
        self._pid = str(os.getpid())

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def request_slot(self, shard_id: str, model_id: str) -> tuple[bool, str]:
        """
        Try to claim a resource slot.  Returns (granted, reason).

        Atomically: read registry → remove dead PIDs → check SM budget
        → write own entry → release lock.
        """
        sm_weight = _SM_WEIGHT.get(model_id, _SM_WEIGHT_DEFAULT)

        if not _HAS_PORTALOCKER:
            # Fallback: no locking (single-machine dev environment without portalocker)
            logger.warning("[governor] portalocker not available; skipping admission check")
            return True, "portalocker unavailable — skipping"

        try:
            with portalocker.Lock(
                str(self._lock_file),
                timeout=30,
                mode="a+",
            ) as fh:
                fh.seek(0)
                registry = self._read_registry()
                registry = self._cleanup_stale(registry)

                # Already registered (idempotent restart guard)
                if self._pid in registry:
                    self._write_registry(registry)
                    return True, "already registered"

                combined = self._combined_sm(registry) + sm_weight
                if combined > self.sm_ceiling:
                    active = [
                        f"{e['shard_id']}({e['model_id']})"
                        for e in registry.values()
                    ]
                    self._write_registry(registry)  # persist stale-cleaned version
                    return False, (
                        f"combined SM estimate {combined}% exceeds ceiling "
                        f"{self.sm_ceiling}%. Active: {active}"
                    )

                registry[self._pid] = {
                    "shard_id": shard_id,
                    "model_id": model_id,
                    "sm_weight": sm_weight,
                    "start_time": time.time(),
                    "pid": int(self._pid),
                }
                self._write_registry(registry)
                return True, f"granted (combined SM {combined}% <= {self.sm_ceiling}%)"

        except portalocker.exceptions.LockException:
            # Lock timeout: another shard holds it; be conservative and deny
            return False, "could not acquire registry lock within 30 s"
        except Exception as exc:
            logger.warning("[governor] request_slot error (denying for safety): %s", exc)
            return False, f"governor error — denying for safety: {exc}"

    def release_slot(self) -> None:
        """
        Remove this process's registry entry.  Call via atexit or finally.
        Never raises.
        """
        if not _HAS_PORTALOCKER:
            return
        try:
            with portalocker.Lock(str(self._lock_file), timeout=10, mode="a+"):
                registry = self._read_registry()
                registry = self._cleanup_stale(registry)
                registry.pop(self._pid, None)
                self._write_registry(registry)
        except Exception as exc:
            logger.debug("[governor] release_slot error (ignored): %s", exc)

    def wait_for_slot(self, shard_id: str, model_id: str) -> bool:
        """
        Block until a slot is granted or max_attempts is exhausted.
        Returns True if granted, False if gave up.
        """
        for attempt in range(self.max_attempts):
            granted, reason = self.request_slot(shard_id, model_id)
            if granted:
                if attempt > 0:
                    print(
                        f"[governor] Slot granted on attempt {attempt + 1}: {reason}",
                        flush=True,
                    )
                return True
            wait_min = self.wait_interval // 60
            print(
                f"[governor] Slot denied (attempt {attempt + 1}/{self.max_attempts}): "
                f"{reason}. Waiting {wait_min} min...",
                flush=True,
            )
            time.sleep(self.wait_interval)
        print(
            f"[governor] No slot available after {self.max_attempts} attempts "
            f"({self.max_attempts * self.wait_interval // 60} min). Exiting.",
            flush=True,
        )
        return False

    def current_registry(self) -> dict:
        """Return a cleaned copy of the registry (for diagnostics)."""
        registry = self._read_registry()
        return self._cleanup_stale(registry)

    # ------------------------------------------------------------------
    # Internal helpers
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
            logger.debug("[governor] Cleaned %d stale registry entries", stale)
        return alive

    def _combined_sm(self, registry: dict) -> int:
        return sum(
            e.get("sm_weight", _SM_WEIGHT_DEFAULT) for e in registry.values()
        )


# ---------------------------------------------------------------------------
# Convenience factory that reads limits from config/global.yaml if present
# ---------------------------------------------------------------------------

def make_governor(root: Optional[Path] = None) -> ResourceGovernor:
    """
    Build a ResourceGovernor from config/global.yaml resource_governance section.
    Falls back to defaults if config is missing or malformed.
    """
    _root = root or Path(__file__).parent.parent.parent
    cfg_path = _root / "config" / "global.yaml"
    defaults = {
        "sm_ceiling_percent": 70,
        "wait_interval_sec": 120,
        "max_wait_attempts": 20,
    }
    try:
        import yaml  # type: ignore
        raw = yaml.safe_load(cfg_path.read_text(encoding="utf-8")) or {}
        gov_cfg = raw.get("resource_governance", {})
        for key in defaults:
            if key in gov_cfg:
                defaults[key] = int(gov_cfg[key])
        # Override SM weights from config if provided
        for model_id, weight in gov_cfg.get("sm_estimates", {}).items():
            _SM_WEIGHT[model_id] = int(weight)
    except Exception:
        pass
    return ResourceGovernor(root=_root, **defaults)
