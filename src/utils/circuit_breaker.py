"""Generic, persisted circuit breaker (TC-APT-004; plan section 2.7 build-vs-reuse audit).

The repo had two bespoke inline "breakers" (language purity, worker launch rate) and no
shared class.  This is the reusable primitive: keyed, JSON-persisted, multi-process safe
(``FileLock`` around every read-modify-write), with the classic three states::

    closed  --(N consecutive failures | failure ratio over window)-->  open
    open    --(cooldown elapsed)-->  half_open  --(probe success)-->  closed
    half_open --(probe failure)-->  open (cooldown doubled, capped)

State file schema (read by ``src/workers/mission_supervisor.open_circuit_breakers``)::

    {"key", "state": "closed|open|half_open", "consecutive_failures", "window": [0/1,...],
     "opened_at", "cooldown_seconds", "trips", "probes_in_flight", "last_failure_reason",
     "last_transition", "updated_at"}
"""

from __future__ import annotations

import json
import threading
import time
from collections.abc import Callable
from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

from src.utils.atomic_write import atomic_write
from src.utils.file_lock import FileLock


class BreakerState(str, Enum):
    CLOSED = "closed"
    OPEN = "open"
    HALF_OPEN = "half_open"


@dataclass(frozen=True)
class BreakerConfig:
    """Trip/reset thresholds. Defaults = TC-APT-028 recommendation (2026-09-02)."""

    consecutive_failure_trip: int = 5
    window_calls: int = 20
    window_failure_ratio_trip: float = 0.5
    min_window_calls: int = 10  # the ratio rule only applies once the window is this full
    cooldown_seconds: float = 60.0
    cooldown_cap_seconds: float = 600.0
    half_open_max_probes: int = 1


@dataclass
class _State:
    key: str
    state: str = BreakerState.CLOSED.value
    consecutive_failures: int = 0
    window: list[int] = field(default_factory=list)  # 1 = success, 0 = failure (oldest first)
    opened_at: float | None = None
    cooldown_seconds: float = 60.0
    trips: int = 0
    probes_in_flight: int = 0
    last_failure_reason: str | None = None
    last_transition: str | None = None
    updated_at: str = ""


class CircuitBreaker:
    """One breaker for one ``key`` (e.g. a model id), persisted to ``state_path``."""

    def __init__(
        self,
        key: str,
        *,
        state_path: Path,
        config: BreakerConfig | None = None,
        clock: Callable[[], float] = time.time,
        lock_timeout: float = 10.0,
    ) -> None:
        self.key = key
        self.state_path = Path(state_path)
        self.config = config or BreakerConfig()
        self._clock = clock
        self._lock = FileLock(
            self.state_path.with_suffix(".lock"), timeout=lock_timeout, poll_interval=0.05
        )
        # In-process serialization: FileLock is per-process (fd + PID) and not thread-safe;
        # threads sharing this breaker must take turns before touching the lock file.
        self._thread_lock = threading.RLock()

    # ------------------------------------------------------------------ persistence
    def _load(self) -> _State:
        if not self.state_path.is_file():
            return _State(key=self.key, cooldown_seconds=self.config.cooldown_seconds)
        try:
            raw = json.loads(self.state_path.read_text(encoding="utf-8"))
            return _State(
                key=str(raw.get("key", self.key)),
                state=str(raw.get("state", BreakerState.CLOSED.value)),
                consecutive_failures=int(raw.get("consecutive_failures", 0)),
                window=[int(x) for x in raw.get("window", [])][-self.config.window_calls :],
                opened_at=raw.get("opened_at"),
                cooldown_seconds=float(raw.get("cooldown_seconds", self.config.cooldown_seconds)),
                trips=int(raw.get("trips", 0)),
                probes_in_flight=int(raw.get("probes_in_flight", 0)),
                last_failure_reason=raw.get("last_failure_reason"),
                last_transition=raw.get("last_transition"),
                updated_at=str(raw.get("updated_at", "")),
            )
        except (OSError, ValueError, TypeError):
            # An unreadable state file must never be mistaken for "closed": fail safe as OPEN.
            return _State(
                key=self.key,
                state=BreakerState.OPEN.value,
                opened_at=self._clock(),
                cooldown_seconds=self.config.cooldown_seconds,
                last_failure_reason="unreadable state file",
            )

    def _save(self, st: _State) -> None:
        st.updated_at = datetime.now(timezone.utc).isoformat()
        atomic_write(self.state_path, json.dumps(asdict(st), indent=2), fsync=False)

    def snapshot(self) -> dict[str, Any]:
        with self._thread_lock, self._lock:
            st = self._load()
            self._maybe_half_open(st)
            return asdict(st)

    # ------------------------------------------------------------------ transitions
    def _transition(self, st: _State, new: BreakerState, why: str) -> None:
        st.state = new.value
        st.last_transition = f"{datetime.now(timezone.utc).isoformat()} {why}"

    def _maybe_half_open(self, st: _State) -> None:
        if st.state == BreakerState.OPEN.value and st.opened_at is not None:
            if self._clock() >= float(st.opened_at) + float(st.cooldown_seconds):
                self._transition(st, BreakerState.HALF_OPEN, "cooldown elapsed")
                st.probes_in_flight = 0

    def _trip(self, st: _State, reason: str) -> None:
        if st.state == BreakerState.OPEN.value:
            return
        # first trip uses the base cooldown; every re-trip doubles it up to the cap
        if st.trips > 0:
            st.cooldown_seconds = min(st.cooldown_seconds * 2, self.config.cooldown_cap_seconds)
        else:
            st.cooldown_seconds = self.config.cooldown_seconds
        st.trips += 1
        st.opened_at = self._clock()
        st.probes_in_flight = 0
        self._transition(st, BreakerState.OPEN, f"tripped: {reason}")

    # ------------------------------------------------------------------ public API
    @property
    def state(self) -> BreakerState:
        return BreakerState(self.snapshot()["state"])

    def is_open(self) -> bool:
        """True while requests must be refused (open and cooldown not elapsed). Side-effect free."""
        with self._thread_lock, self._lock:
            st = self._load()
            if st.state != BreakerState.OPEN.value or st.opened_at is None:
                return False
            return self._clock() < float(st.opened_at) + float(st.cooldown_seconds)

    def allow_request(self) -> bool:
        """Gate a call. In half-open, admits at most ``half_open_max_probes`` in-flight probes."""
        with self._thread_lock, self._lock:
            st = self._load()
            self._maybe_half_open(st)
            if st.state == BreakerState.CLOSED.value:
                return True
            if st.state == BreakerState.HALF_OPEN.value:
                if st.probes_in_flight < self.config.half_open_max_probes:
                    st.probes_in_flight += 1
                    self._save(st)
                    return True
                return False
            self._save(st)
            return False

    def record_success(self) -> None:
        with self._thread_lock, self._lock:
            st = self._load()
            st.consecutive_failures = 0
            st.window = (st.window + [1])[-self.config.window_calls :]
            if st.state != BreakerState.CLOSED.value:
                self._transition(st, BreakerState.CLOSED, "probe succeeded")
                st.cooldown_seconds = self.config.cooldown_seconds
                st.probes_in_flight = 0
            self._save(st)

    def record_failure(self, reason: str = "") -> None:
        with self._thread_lock, self._lock:
            st = self._load()
            self._maybe_half_open(st)
            st.consecutive_failures += 1
            st.window = (st.window + [0])[-self.config.window_calls :]
            st.last_failure_reason = (reason or "failure")[:200]
            if st.state == BreakerState.HALF_OPEN.value:
                self._trip(st, f"probe failed: {st.last_failure_reason}")
            elif st.state == BreakerState.CLOSED.value:
                failures = st.window.count(0)
                ratio = failures / len(st.window) if st.window else 0.0
                if st.consecutive_failures >= self.config.consecutive_failure_trip:
                    self._trip(st, f"{st.consecutive_failures} consecutive failures")
                elif (
                    len(st.window) >= self.config.min_window_calls
                    and ratio >= self.config.window_failure_ratio_trip
                ):
                    self._trip(st, f"failure ratio {ratio:.2f} over last {len(st.window)} calls")
            self._save(st)

    def force_open(self, reason: str, *, cooldown_seconds: float | None = None) -> None:
        """Quarantine: open the breaker deliberately (e.g. model-identity drift, TC-APT-021).

        ``cooldown_seconds`` defaults to the configured cap so the quarantine outlasts a
        normal trip; a later ``record_success`` (probe) or ``reset`` closes it.
        """
        with self._thread_lock, self._lock:
            st = self._load()
            st.trips += 1
            st.opened_at = self._clock()
            st.cooldown_seconds = float(
                cooldown_seconds
                if cooldown_seconds is not None
                else self.config.cooldown_cap_seconds
            )
            st.probes_in_flight = 0
            st.last_failure_reason = (reason or "forced open")[:200]
            self._transition(st, BreakerState.OPEN, f"forced open: {st.last_failure_reason}")
            self._save(st)

    def reset(self) -> None:
        with self._thread_lock, self._lock:
            self._save(_State(key=self.key, cooldown_seconds=self.config.cooldown_seconds))
