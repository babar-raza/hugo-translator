"""
Worker state ledger helpers.

Provides a durable JSON state record per worker under ``data/logs`` so health
tooling can report last-success and last-error provenance independently from
ephemeral process liveness.
"""

from __future__ import annotations

import json
import logging
import os
import platform
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _is_process_alive(pid: int) -> bool:
    """Platform-safe check for process liveness."""
    if platform.system() == "Windows":
        try:
            result = subprocess.run(
                ["tasklist", "/FI", f"PID eq {pid}", "/NH"],
                capture_output=True, text=True, timeout=5,
            )
            return str(pid) in result.stdout
        except Exception:
            return False
    else:
        try:
            os.kill(pid, 0)
            return True
        except (OSError, ProcessLookupError):
            return False


def acquire_pid_file(worker_id: str, log_dir: Path | None = None) -> bool:
    """Write PID file only if no live process holds it. Returns True if acquired."""
    pid_path = (log_dir or Path("data/logs")) / f"{worker_id}.pid"
    if pid_path.exists():
        try:
            existing_pid = int(pid_path.read_text(encoding="utf-8").strip())
            if _is_process_alive(existing_pid):
                logger.warning(
                    "PID file %s held by live process %d — refusing to overwrite",
                    pid_path, existing_pid,
                )
                return False
        except (ValueError, OSError):
            pass  # Stale/corrupt PID file — safe to overwrite
    pid_path.parent.mkdir(parents=True, exist_ok=True)
    pid_path.write_text(str(os.getpid()), encoding="utf-8")
    return True


def get_worker_log_dir() -> Path:
    """Return the canonical log directory for worker state and heartbeat files."""
    log_dir = Path("data/logs")
    log_dir.mkdir(parents=True, exist_ok=True)
    return log_dir


def get_worker_state_path(worker_id: str, log_dir: Path | None = None) -> Path:
    """Return the JSON state file path for a worker."""
    base = log_dir or get_worker_log_dir()
    return base / f"{worker_id}.state.json"


def load_worker_state(worker_id: str, log_dir: Path | None = None) -> dict[str, Any]:
    """Load worker state JSON if present; return empty dict when unavailable."""
    state_path = get_worker_state_path(worker_id, log_dir=log_dir)
    if not state_path.exists():
        return {}
    try:
        return json.loads(state_path.read_text(encoding="utf-8"))
    except Exception:
        return {}


def _atomic_write_json(path: Path, payload: dict[str, Any]) -> None:
    """Atomically write JSON payload to disk."""
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
    tmp_path.replace(path)


def record_worker_state(
    worker_id: str,
    state: str,
    *,
    success: bool = False,
    error: str | None = None,
    log_path: str | None = None,
    log_dir: Path | None = None,
    now: datetime | None = None,
    useful_work_count: int | None = None,
    no_work_count: int | None = None,
    failure_count: int | None = None,
    current_mode: str | None = None,
    input_queue: str | None = None,
) -> dict[str, Any]:
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
        useful_work_count: TC-12 — cumulative count of runs that produced output.
        no_work_count: TC-12 — cumulative count of runs with nothing to do.
        failure_count: TC-12 — cumulative count of unhandled exceptions.
        current_mode: TC-12 — "daemon", "oneshot", or "manual".
        input_queue: TC-12 — path or name of the worker's input source.

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

    # TC-12: New optional fields — only written when provided (additive, backward-compat)
    if useful_work_count is not None:
        payload["useful_work_count"] = useful_work_count
    if no_work_count is not None:
        payload["no_work_count"] = no_work_count
    if failure_count is not None:
        payload["failure_count"] = failure_count
    if current_mode is not None:
        payload["current_mode"] = current_mode
    if input_queue is not None:
        payload["input_queue"] = input_queue

    _atomic_write_json(state_path, payload)
    return payload
