"""
Worker state ledger helpers.

Provides a durable JSON state record per worker under ``data/logs`` so health
tooling can report last-success and last-error provenance independently from
ephemeral process liveness.
"""

from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional


def get_worker_log_dir() -> Path:
    """Return the canonical log directory for worker state and heartbeat files."""
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_worker_state_path(worker_id: str, log_dir: Optional[Path] = None) -> Path:
    """Return the JSON state file path for a worker."""
    base = log_dir or get_worker_log_dir()
    return base / f"{worker_id}.state.json"


def load_worker_state(worker_id: str, log_dir: Optional[Path] = None) -> Dict[str, Any]:
    """Load worker state JSON if present; return empty dict when unavailable."""
    state_path = get_worker_state_path(worker_id, log_dir=log_dir)
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _atomic_write_json(path: Path, payload: Dict[str, Any]) -> None:
    """Atomically write JSON payload to disk."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def record_worker_state(
    worker_id: str,
    state: str,
    *,
    success: bool = False,
    error: Optional[str] = None,
    log_path: Optional[str] = None,
    log_dir: Optional[Path] = None,
    now: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    Update durable worker state.

    Args:
        worker_id: Worker identifier (e.g., ``content_worker``).
        state: Current worker lifecycle state.
        success: If True, updates ``last_success_ts``.
        error: Optional error summary; updates ``last_error_ts`` when provided.
        log_path: Optional worker log path for provenance.
        log_dir: Optional override for state-file directory.
        now: Optional timestamp override for deterministic tests.

    Returns:
        The full updated state payload.
    """
    timestamp = (now or datetime.now(timezone.utc)).isoformat()
    state_path = get_worker_state_path(worker_id, log_dir=log_dir)
    payload = load_worker_state(worker_id, log_dir=log_dir)

    payload["worker_id"] = worker_id
    payload["state"] = state
    payload["pid"] = os.getpid()
    payload["updated_at"] = timestamp

    if log_path:
        payload["log_path"] = log_path

    if success:
        payload["last_success_ts"] = timestamp

    if error:
        payload["last_error_ts"] = timestamp
        payload["last_error"] = str(error)[:500]

    _atomic_write_json(state_path, payload)
    return payload

