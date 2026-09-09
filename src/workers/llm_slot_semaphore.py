"""TC-APT-094: cross-process LLM call slot semaphore (plan SS0.10, BLITZ
critical path 3 of 3).

This mission runs K independent launcher processes (one per product family,
plan SS0.6/TC-APT-056), each spawning up to 4 shard-child OS processes
(TC-APT-047). Each process only serializes or bounds ITS OWN LLM calls --
there has never been a shared view of how many `LLMModelBackend.generate()`
calls are in flight across the whole fleet at once. A per-process cap
multiplies with launcher count into an uncapped fleet-wide burst against the
`professionalize_llm` API, exactly the kind of load TC-APT-064's sustained
probe has not yet cleared beyond a measured ceiling.

This gives every `generate()` call a slot in a small shared JSON file
(`data/campaigns/llm_slots.json`) under the same `FileLock` pattern already
used by `work_claims.py` (TC-APT-056) and `CampaignLedger`: total live slots
capped at `DEFAULT_CAPACITY` (64, raised from the original 8 on TC-APT-064's
sustained-load evidence -- 16/32/48/64 concurrent calls against
`professionalize_llm` each held for 450s, 3611 calls total, 0 errors and 0
rate-limited at every level; see
`data/benchmark_corpus/results/professionalize_llm_calibration_tc064_sustained_20260906.json`.
`sustained_safe_ceiling=64` is a floor, not a measured max -- the probe did
not find a ceiling within the tested range), each carrying a TTL so a
crashed holder cannot starve the semaphore forever. The true unit of
concurrency is one in-flight API call, not one process or one launcher --
`LLMSlot` defaults to a fresh holder id per instance so N calls in the same
process (once max_parallel_jobs rises above 1) are counted as N slots, not 1.
"""

from __future__ import annotations

import os
import time
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from src.utils.file_lock import FileLock

_SLOTS_FILE = Path("data/campaigns/llm_slots.json")
# TC-APT-064 sustained-load calibration (2026-09-06) held 16/32/48/64 concurrent
# professionalize_llm calls for 450s each (3611 calls total): 0 errors, 0
# rate-limited at every level. sustained_safe_ceiling=64 is the evidenced floor
# (see module docstring for the full citation).
DEFAULT_CAPACITY = 64
DEFAULT_TTL_SECONDS = 120.0


class LLMSlotTimeoutError(Exception):
    """Raised when no LLM call slot became free within the wait timeout."""


def slot_from_config(**overrides: Any) -> LLMSlot:
    """Build an `LLMSlot` sized from `translation_engine.llm_slot_semaphore` in
    global config -- the shared sizing logic for call sites that hold no
    `LLMModelBackend` instance to read it from (e.g. `src/intelligence/llm_client.py`,
    a bare-provider client also aimed at the `professionalize_llm` endpoint).
    """
    try:
        from src.utils.config_loader import get_global_config

        cfg = get_global_config().get("translation_engine", {}).get("llm_slot_semaphore", {})
        capacity = int(cfg.get("capacity", DEFAULT_CAPACITY))
        ttl_seconds = float(cfg.get("ttl_seconds", DEFAULT_TTL_SECONDS))
    except Exception:
        capacity, ttl_seconds = DEFAULT_CAPACITY, DEFAULT_TTL_SECONDS
    overrides.setdefault("capacity", capacity)
    overrides.setdefault("ttl_seconds", ttl_seconds)
    return LLMSlot(**overrides)


def _slots_path(override: Path | None) -> Path:
    if override is not None:
        return override
    # Same escape hatch as HT_CIRCUIT_BREAKER_DIR/HT_LLM_HEALTH_DIR (TC-APT-004):
    # every LLM-translating call site goes through this module now, so without
    # this, every unit test exercising real (unmocked) LLM translation would
    # read/write the live fleet-shared data/campaigns/llm_slots.json.
    env_override = os.environ.get("HT_LLM_SLOTS_PATH")
    if env_override:
        return Path(env_override)
    return _SLOTS_FILE


def _lock_path(slots_path: Path) -> Path:
    return slots_path.with_suffix(slots_path.suffix + ".lock")


def _parse(ts: str) -> datetime | None:
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        return None


def _load(slots_path: Path) -> dict[str, Any]:
    if not slots_path.exists():
        return {}
    try:
        import json

        return json.loads(slots_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _save(slots_path: Path, data: dict[str, Any]) -> None:
    import json

    slots_path.parent.mkdir(parents=True, exist_ok=True)
    slots_path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8", newline="\n"
    )


def _reap_expired(slots: dict[str, Any], now: datetime) -> dict[str, Any]:
    live = {}
    for slot_id, slot in slots.items():
        expires_at = _parse(slot.get("expires_at", ""))
        if expires_at is not None and expires_at > now:
            live[slot_id] = slot
    return live


def acquire_slot(
    holder_id: str,
    *,
    capacity: int = DEFAULT_CAPACITY,
    ttl_seconds: float = DEFAULT_TTL_SECONDS,
    slots_path: Path | None = None,
    lock_timeout: float = 10.0,
) -> str | None:
    """Try to occupy one of `capacity` global in-flight-LLM-call slots.

    Returns the slot id if acquired (a fresh grant, or a renewal if
    `holder_id` already holds a live slot), or None if all slots are held by
    OTHER holders -- the caller must wait and retry, never proceed anyway.
    """
    path = _slots_path(slots_path)
    with FileLock(_lock_path(path), timeout=lock_timeout):
        now = datetime.now(timezone.utc)
        data = _load(path)
        slots = _reap_expired(data.get("slots", {}), now)
        existing_id = next(
            (sid for sid, s in slots.items() if s.get("holder_id") == holder_id), None
        )
        if existing_id is not None:
            slots[existing_id]["expires_at"] = (
                now + timedelta(seconds=ttl_seconds)
            ).isoformat()
            data["slots"] = slots
            _save(path, data)
            return existing_id
        if len(slots) >= capacity:
            data["slots"] = slots
            _save(path, data)
            return None
        slot_id = f"{holder_id}:{uuid.uuid4().hex[:8]}"
        slots[slot_id] = {
            "holder_id": holder_id,
            "acquired_at": now.isoformat(),
            "expires_at": (now + timedelta(seconds=ttl_seconds)).isoformat(),
        }
        data["slots"] = slots
        _save(path, data)
        return slot_id


def release_slot(
    slot_id: str,
    holder_id: str,
    *,
    slots_path: Path | None = None,
    lock_timeout: float = 10.0,
) -> None:
    """Free `slot_id` early. No-op if it is not live or owned by a different holder."""
    path = _slots_path(slots_path)
    with FileLock(_lock_path(path), timeout=lock_timeout):
        data = _load(path)
        slots = data.get("slots", {})
        slot = slots.get(slot_id)
        if slot is not None and slot.get("holder_id") == holder_id:
            del slots[slot_id]
            data["slots"] = slots
            _save(path, data)


class LLMSlot:
    """Blocking context manager: holds one cross-process LLM-call slot for its body.

    Polls `acquire_slot` until one is free or `wait_timeout` elapses. Always
    releases on exit, including on an exception raised inside the `with` body.
    """

    def __init__(
        self,
        holder_id: str | None = None,
        *,
        capacity: int = DEFAULT_CAPACITY,
        ttl_seconds: float = DEFAULT_TTL_SECONDS,
        wait_timeout: float = 300.0,
        poll_interval: float = 1.0,
        slots_path: Path | None = None,
    ) -> None:
        self.holder_id = holder_id or f"pid{os.getpid()}-{uuid.uuid4().hex[:8]}"
        self.capacity = capacity
        self.ttl_seconds = ttl_seconds
        self.wait_timeout = wait_timeout
        self.poll_interval = poll_interval
        self.slots_path = slots_path
        self.slot_id: str | None = None

    def __enter__(self) -> LLMSlot:
        start = time.monotonic()
        while True:
            self.slot_id = acquire_slot(
                self.holder_id,
                capacity=self.capacity,
                ttl_seconds=self.ttl_seconds,
                slots_path=self.slots_path,
            )
            if self.slot_id is not None:
                return self
            if time.monotonic() - start >= self.wait_timeout:
                raise LLMSlotTimeoutError(
                    f"No LLM call slot free after {self.wait_timeout}s "
                    f"(capacity={self.capacity})"
                )
            time.sleep(self.poll_interval)

    def __exit__(self, exc_type, exc_val, exc_tb) -> bool:
        if self.slot_id is not None:
            release_slot(self.slot_id, self.holder_id, slots_path=self.slots_path)
        return False
