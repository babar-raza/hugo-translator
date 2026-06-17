"""TC-AGT-06: Programmatic task queue — JSONL-based machine-readable task backlog.

Standalone utility — not yet consumed by worker_orchestrator.
Integration deferred to a future horizon pending supervisor loop stabilization.
See TC-AGT-22 in the agentic maturity plan for details.

Replaces the prose-based TASK_BACKLOG.md with a structured, programmatic task
queue that the worker orchestrator can read for autonomous task selection.

Format: JSONL (one JSON object per line) at ``data/task_queue.jsonl``.
Each entry:
    {
        "task_id": "TC-AGT-06",
        "title": "Programmatic Task Queue",
        "lane": "D",
        "priority": "P1",
        "status": "pending",
        "horizon": 2,
        "depends_on": [],
        "blockers": [],
        "created_at": "2026-06-13T...",
        "updated_at": "2026-06-13T...",
        "completed_at": null,
        "metadata": {}
    }

Status lifecycle: pending → in_progress → completed | blocked
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

_QUEUE_FILE = Path("data/task_queue.jsonl")


class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    BLOCKED = "blocked"


def _queue_path(override: Path | None = None) -> Path:
    return override or _QUEUE_FILE


def _load_entries(queue_file: Path) -> list[dict[str, Any]]:
    """Load all entries from the queue file."""
    if not queue_file.exists():
        return []
    entries = []
    try:
        for line in queue_file.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                entries.append(json.loads(line))
            except json.JSONDecodeError:
                logger.warning("task_queue: skipping malformed line")
    except Exception as e:
        logger.warning("task_queue: failed to load: %s", e)
    return entries


def _write_entries(entries: list[dict[str, Any]], queue_file: Path) -> None:
    """Atomically write all entries back to the queue file."""
    queue_file.parent.mkdir(parents=True, exist_ok=True)
    dir_ = queue_file.parent
    with tempfile.NamedTemporaryFile(
        mode="w", encoding="utf-8", dir=dir_, delete=False, suffix=".tmp"
    ) as tmp:
        for entry in entries:
            tmp.write(json.dumps(entry, default=str) + "\n")
        tmp_path = tmp.name
    os.replace(tmp_path, queue_file)


def add_task(
    task_id: str,
    title: str,
    *,
    lane: str = "",
    priority: str = "P2",
    horizon: int = 0,
    depends_on: list[str] | None = None,
    metadata: dict[str, Any] | None = None,
    queue_file: Path | None = None,
) -> dict[str, Any]:
    """Add a task to the queue. Deduplicates by task_id.

    Returns the task entry (existing if duplicate, new if added).
    """
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)

    # Dedup check
    for entry in entries:
        if entry.get("task_id") == task_id:
            logger.debug("task_queue: task %s already exists — skipping", task_id)
            return entry

    now = datetime.now(timezone.utc).isoformat()
    task = {
        "task_id": task_id,
        "title": title,
        "lane": lane,
        "priority": priority,
        "status": TaskStatus.PENDING.value,
        "horizon": horizon,
        "depends_on": depends_on or [],
        "blockers": [],
        "created_at": now,
        "updated_at": now,
        "completed_at": None,
        "metadata": metadata or {},
    }
    entries.append(task)
    _write_entries(entries, qf)
    logger.info("task_queue: added %s — %s", task_id, title)
    return task


def update_task_status(
    task_id: str,
    status: TaskStatus,
    *,
    error: str | None = None,
    queue_file: Path | None = None,
) -> dict[str, Any] | None:
    """Update a task's status. Returns the updated entry or None if not found."""
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)

    now = datetime.now(timezone.utc).isoformat()
    found = None
    for entry in entries:
        if entry.get("task_id") == task_id:
            entry["status"] = status.value
            entry["updated_at"] = now
            if status == TaskStatus.COMPLETED:
                entry["completed_at"] = now
            if error:
                entry.setdefault("blockers", []).append({"error": error, "timestamp": now})
            found = entry
            break

    if found:
        _write_entries(entries, qf)
        logger.info("task_queue: %s → %s", task_id, status.value)
    else:
        logger.warning("task_queue: task %s not found", task_id)
    return found


def add_blocker(
    task_id: str,
    blocker_id: str,
    description: str,
    *,
    queue_file: Path | None = None,
) -> dict[str, Any] | None:
    """Add a blocker to a task and set status to BLOCKED."""
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)

    now = datetime.now(timezone.utc).isoformat()
    found = None
    for entry in entries:
        if entry.get("task_id") == task_id:
            entry.setdefault("blockers", []).append(
                {
                    "blocker_id": blocker_id,
                    "description": description,
                    "added_at": now,
                }
            )
            entry["status"] = TaskStatus.BLOCKED.value
            entry["updated_at"] = now
            found = entry
            break

    if found:
        _write_entries(entries, qf)
        logger.info("task_queue: %s blocked by %s", task_id, blocker_id)
    return found


def get_next_task(
    *,
    lane: str | None = None,
    queue_file: Path | None = None,
) -> dict[str, Any] | None:
    """Get the highest-priority pending task, optionally filtered by lane.

    Priority order: P0 > P1 > P2 > P3.
    Within same priority: earlier created_at wins.
    Tasks with unmet dependencies are skipped.
    """
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)

    completed_ids = {e["task_id"] for e in entries if e.get("status") == TaskStatus.COMPLETED.value}

    candidates = []
    for entry in entries:
        if entry.get("status") != TaskStatus.PENDING.value:
            continue
        if lane and entry.get("lane") != lane:
            continue
        # Check dependencies
        deps = entry.get("depends_on", [])
        if deps and not all(d in completed_ids for d in deps):
            continue
        candidates.append(entry)

    if not candidates:
        return None

    # Sort by priority (P0 < P1 < P2), then by created_at
    priority_order = {"P0": 0, "P1": 1, "P2": 2, "P3": 3}
    candidates.sort(
        key=lambda e: (
            priority_order.get(e.get("priority", "P2"), 9),
            e.get("created_at", ""),
        )
    )
    return candidates[0]


def load_all_tasks(
    *,
    status: TaskStatus | None = None,
    queue_file: Path | None = None,
) -> list[dict[str, Any]]:
    """Load all tasks, optionally filtered by status."""
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)
    if status is not None:
        entries = [e for e in entries if e.get("status") == status.value]
    return entries


def remove_task(
    task_id: str,
    *,
    queue_file: Path | None = None,
) -> bool:
    """Remove a task from the queue. Returns True if found and removed."""
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)
    before = len(entries)
    entries = [e for e in entries if e.get("task_id") != task_id]
    if len(entries) < before:
        _write_entries(entries, qf)
        logger.info("task_queue: removed %s", task_id)
        return True
    return False


def queue_summary(*, queue_file: Path | None = None) -> dict[str, int]:
    """Return a summary of task counts by status."""
    qf = _queue_path(queue_file)
    entries = _load_entries(qf)
    summary: dict[str, int] = {}
    for entry in entries:
        status = entry.get("status", "unknown")
        summary[status] = summary.get(status, 0) + 1
    summary["total"] = len(entries)
    return summary
