"""TC-AGT-07: Cross-session continuation state machine.

Tracks what was accomplished in previous runs and what work remains,
enabling the system to resume where it left off across sessions.

State file: ``data/logs/continuation_state.json``

State machine lifecycle:
    IDLE → RUNNING → COMPLETED | FAILED | INTERRUPTED
    INTERRUPTED → RUNNING (resume)

Each run records:
- What sites/languages were processed
- Which files succeeded/failed
- Pending work remaining
- Blockers encountered
- Suggested next action

The worker reads this on startup to decide what to prioritize.
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_STATE_FILE = Path("data/logs/continuation_state.json")


class RunPhase(str, Enum):
    IDLE = "idle"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"
    INTERRUPTED = "interrupted"


def _state_path(override: Path | None = None) -> Path:
    return override or _STATE_FILE


def _atomic_write(path: Path, data: dict[str, Any]) -> None:
    """Atomically write JSON to path."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        delete=False,
        suffix=".tmp",
    ) as tmp:
        json.dump(data, tmp, indent=2, default=str)
        tmp_path = tmp.name
    os.replace(tmp_path, path)


def load_state(*, state_file: Path | None = None) -> dict[str, Any]:
    """Load continuation state from disk. Returns empty state if absent."""
    path = _state_path(state_file)
    if not path.exists():
        return _empty_state()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data
    except Exception as e:
        logger.warning("continuation_state: failed to load: %s", e)
        return _empty_state()


def _empty_state() -> dict[str, Any]:
    return {
        "phase": RunPhase.IDLE.value,
        "run_id": None,
        "started_at": None,
        "updated_at": None,
        "completed_at": None,
        "current_site": None,
        "current_langs": [],
        "runs_history": [],
        "pending_work": [],
        "blockers": [],
        "next_action": None,
        "stats": {
            "total_runs": 0,
            "total_files_processed": 0,
            "total_files_accepted": 0,
            "total_files_rejected": 0,
            "consecutive_failures": 0,
        },
    }


def start_run(
    run_id: str,
    site_id: str,
    target_langs: list[str],
    *,
    state_file: Path | None = None,
) -> dict[str, Any]:
    """Record the start of a new translation run.

    If a previous run was INTERRUPTED, its pending work is preserved.
    """
    state = load_state(state_file=state_file)
    now = datetime.now(timezone.utc).isoformat()

    # If previous run was interrupted, preserve its pending work
    if state["phase"] == RunPhase.INTERRUPTED.value:
        logger.info(
            "continuation_state: resuming after interrupted run %s",
            state.get("run_id"),
        )

    state["phase"] = RunPhase.RUNNING.value
    state["run_id"] = run_id
    state["started_at"] = now
    state["updated_at"] = now
    state["completed_at"] = None
    state["current_site"] = site_id
    state["current_langs"] = target_langs
    state["next_action"] = None

    _atomic_write(_state_path(state_file), state)
    logger.info(
        "continuation_state: run %s started (site=%s, langs=%s)", run_id, site_id, target_langs
    )
    return state


def record_progress(
    *,
    files_processed: int = 0,
    files_accepted: int = 0,
    files_rejected: int = 0,
    pending_items: list[str] | None = None,
    state_file: Path | None = None,
) -> dict[str, Any]:
    """Record incremental progress during a run."""
    state = load_state(state_file=state_file)
    now = datetime.now(timezone.utc).isoformat()

    state["updated_at"] = now
    stats = state.get("stats", {})
    stats["total_files_processed"] = stats.get("total_files_processed", 0) + files_processed
    stats["total_files_accepted"] = stats.get("total_files_accepted", 0) + files_accepted
    stats["total_files_rejected"] = stats.get("total_files_rejected", 0) + files_rejected
    state["stats"] = stats

    if pending_items is not None:
        state["pending_work"] = pending_items

    _atomic_write(_state_path(state_file), state)
    return state


def complete_run(
    *,
    files_processed: int = 0,
    files_accepted: int = 0,
    files_rejected: int = 0,
    next_action: str | None = None,
    state_file: Path | None = None,
) -> dict[str, Any]:
    """Record successful completion of a run."""
    state = load_state(state_file=state_file)
    now = datetime.now(timezone.utc).isoformat()

    run_record = {
        "run_id": state.get("run_id"),
        "site_id": state.get("current_site"),
        "langs": state.get("current_langs", []),
        "started_at": state.get("started_at"),
        "completed_at": now,
        "outcome": "completed",
        "files_processed": files_processed,
        "files_accepted": files_accepted,
        "files_rejected": files_rejected,
    }

    state["phase"] = RunPhase.COMPLETED.value
    state["completed_at"] = now
    state["updated_at"] = now
    state["pending_work"] = []
    state["next_action"] = next_action

    stats = state.get("stats", {})
    stats["total_runs"] = stats.get("total_runs", 0) + 1
    stats["consecutive_failures"] = 0
    state["stats"] = stats

    history = state.get("runs_history", [])
    history.append(run_record)
    # Keep last 50 runs
    state["runs_history"] = history[-50:]

    _atomic_write(_state_path(state_file), state)
    logger.info(
        "continuation_state: run %s completed (%d processed, %d accepted)",
        state.get("run_id"),
        files_processed,
        files_accepted,
    )
    return state


def fail_run(
    error: str,
    *,
    pending_items: list[str] | None = None,
    state_file: Path | None = None,
) -> dict[str, Any]:
    """Record a failed run."""
    state = load_state(state_file=state_file)
    now = datetime.now(timezone.utc).isoformat()

    run_record = {
        "run_id": state.get("run_id"),
        "site_id": state.get("current_site"),
        "langs": state.get("current_langs", []),
        "started_at": state.get("started_at"),
        "completed_at": now,
        "outcome": "failed",
        "error": error[:500],
    }

    state["phase"] = RunPhase.FAILED.value
    state["completed_at"] = now
    state["updated_at"] = now
    state["next_action"] = f"Investigate failure: {error[:200]}"

    if pending_items is not None:
        state["pending_work"] = pending_items

    stats = state.get("stats", {})
    stats["total_runs"] = stats.get("total_runs", 0) + 1
    stats["consecutive_failures"] = stats.get("consecutive_failures", 0) + 1
    state["stats"] = stats

    history = state.get("runs_history", [])
    history.append(run_record)
    state["runs_history"] = history[-50:]

    _atomic_write(_state_path(state_file), state)
    logger.warning("continuation_state: run %s failed: %s", state.get("run_id"), error[:200])
    return state


def interrupt_run(
    *,
    pending_items: list[str] | None = None,
    state_file: Path | None = None,
) -> dict[str, Any]:
    """Mark a run as interrupted (e.g., process killed, timeout).

    Pending work is preserved for the next session to resume.
    """
    state = load_state(state_file=state_file)
    now = datetime.now(timezone.utc).isoformat()

    state["phase"] = RunPhase.INTERRUPTED.value
    state["updated_at"] = now
    state["next_action"] = "Resume interrupted run"

    if pending_items is not None:
        state["pending_work"] = pending_items

    _atomic_write(_state_path(state_file), state)
    logger.warning(
        "continuation_state: run %s interrupted with %d pending items",
        state.get("run_id"),
        len(state.get("pending_work", [])),
    )
    return state


def add_blocker(
    blocker_id: str,
    description: str,
    *,
    blocker_type: str = "unknown",
    state_file: Path | None = None,
) -> dict[str, Any]:
    """Add a blocker to the current state."""
    state = load_state(state_file=state_file)
    now = datetime.now(timezone.utc).isoformat()

    state.setdefault("blockers", []).append(
        {
            "blocker_id": blocker_id,
            "type": blocker_type,
            "description": description,
            "added_at": now,
        }
    )
    state["updated_at"] = now

    _atomic_write(_state_path(state_file), state)
    logger.info("continuation_state: blocker added: %s — %s", blocker_id, description)
    return state


def get_pending_work(*, state_file: Path | None = None) -> list[str]:
    """Return the list of pending work items from the last interrupted/failed run."""
    state = load_state(state_file=state_file)
    return state.get("pending_work", [])


def get_run_history(
    *,
    limit: int = 10,
    state_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Return the most recent run records."""
    state = load_state(state_file=state_file)
    history = state.get("runs_history", [])
    return history[-limit:]


def should_resume(*, state_file: Path | None = None) -> bool:
    """Check if a previous run was interrupted and should be resumed."""
    state = load_state(state_file=state_file)
    return state.get("phase") == RunPhase.INTERRUPTED.value


def is_circuit_broken(
    *,
    max_consecutive_failures: int = 3,
    state_file: Path | None = None,
) -> bool:
    """Check if consecutive failures exceed the threshold."""
    state = load_state(state_file=state_file)
    failures = state.get("stats", {}).get("consecutive_failures", 0)
    return failures >= max_consecutive_failures
