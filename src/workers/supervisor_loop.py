"""TC-AGT-10: Supervisor loop above worker orchestrator.

Sits above the worker orchestrator and provides autonomous decision-making:
1. Inspect current state (continuation state, task queue, signals)
2. Select next work (from task queue, considering priorities and dependencies)
3. Execute decision (update task status, recommend worker launches)
4. Verify outcome (check signals, update continuation state)
5. Report (emit supervisor events, update task queue)

This is an advisory supervisor — it does not directly launch workers.
Instead, it writes decisions to ``data/logs/supervisor_events.jsonl``
and updates the task queue. The worker orchestrator consumes these
decisions via its trigger evaluation system.

Usage:
    python -m src.workers.supervisor_loop --once
    python -m src.workers.supervisor_loop --dry-run
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

_EVENT_LOG = Path("data/logs/supervisor_events.jsonl")


class SupervisorDecision(str, Enum):
    PROCEED = "proceed"
    SKIP = "skip"
    BLOCK = "block"
    CIRCUIT_BREAK = "circuit_break"
    RESUME = "resume"


def _append_event(event: dict[str, Any], event_log: Path | None = None) -> None:
    """Append a supervisor event to the JSONL log."""
    log = event_log or _EVENT_LOG
    log.parent.mkdir(parents=True, exist_ok=True)
    event["timestamp"] = datetime.now(timezone.utc).isoformat()
    with open(log, "a", encoding="utf-8") as f:
        f.write(json.dumps(event, default=str) + "\n")


def inspect_state(
    *,
    continuation_state_file: Path | None = None,
    task_queue_file: Path | None = None,
    signals_dir: Path | None = None,
) -> dict[str, Any]:
    """Inspect the current system state for decision-making.

    Returns a state snapshot with continuation state, task queue summary,
    and latest signal information.
    """
    from src.workers.continuation_state import (
        is_circuit_broken,
        should_resume,
    )
    from src.workers.continuation_state import (
        load_state as load_continuation,
    )
    from src.workers.task_queue import (
        get_next_task,
        queue_summary,
    )

    snapshot: dict[str, Any] = {}

    # Continuation state
    cont = load_continuation(state_file=continuation_state_file)
    snapshot["continuation"] = {
        "phase": cont.get("phase", "idle"),
        "run_id": cont.get("run_id"),
        "current_site": cont.get("current_site"),
        "pending_work_count": len(cont.get("pending_work", [])),
        "blockers_count": len(cont.get("blockers", [])),
        "consecutive_failures": cont.get("stats", {}).get("consecutive_failures", 0),
        "total_runs": cont.get("stats", {}).get("total_runs", 0),
    }
    snapshot["should_resume"] = should_resume(state_file=continuation_state_file)
    snapshot["circuit_broken"] = is_circuit_broken(state_file=continuation_state_file)

    # Task queue
    snapshot["queue_summary"] = queue_summary(queue_file=task_queue_file)
    next_task = get_next_task(queue_file=task_queue_file)
    snapshot["next_task"] = {
        "task_id": next_task["task_id"] if next_task else None,
        "title": next_task["title"] if next_task else None,
        "priority": next_task.get("priority") if next_task else None,
        "lane": next_task.get("lane") if next_task else None,
    }

    # Latest signal
    sdir = signals_dir or Path("data/signals")
    snapshot["latest_signal"] = None
    if sdir.exists():
        signal_files = sorted(sdir.glob("run-signal-*.json"))
        if signal_files:
            try:
                data = json.loads(signal_files[-1].read_text(encoding="utf-8"))
                snapshot["latest_signal"] = {
                    "run_id": data.get("run_id"),
                    "verdict": data.get("verdict"),
                    "status": data.get("status"),
                }
            except Exception:
                pass

    return snapshot


def decide(
    snapshot: dict[str, Any],
    *,
    max_consecutive_failures: int = 3,
) -> dict[str, Any]:
    """Make a supervisor decision based on the state snapshot.

    Returns a decision dict with:
        - decision: SupervisorDecision enum value
        - reason: human-readable explanation
        - recommended_action: what should happen next
        - task_id: which task to work on (if any)
    """
    result: dict[str, Any] = {
        "decision": SupervisorDecision.PROCEED.value,
        "reason": "",
        "recommended_action": "",
        "task_id": None,
    }

    # Check circuit breaker first
    if snapshot.get("circuit_broken"):
        failures = snapshot["continuation"].get("consecutive_failures", 0)
        result["decision"] = SupervisorDecision.CIRCUIT_BREAK.value
        result["reason"] = f"Circuit broken: {failures} consecutive failures"
        result["recommended_action"] = "Investigate root cause before retrying"
        return result

    # Check for interrupted run needing resume
    if snapshot.get("should_resume"):
        pending = snapshot["continuation"].get("pending_work_count", 0)
        result["decision"] = SupervisorDecision.RESUME.value
        result["reason"] = f"Previous run interrupted with {pending} pending items"
        result["recommended_action"] = "Resume interrupted work"
        return result

    # Check for blockers
    blocker_count = snapshot["continuation"].get("blockers_count", 0)
    if blocker_count > 0:
        result["decision"] = SupervisorDecision.BLOCK.value
        result["reason"] = f"{blocker_count} active blocker(s)"
        result["recommended_action"] = "Resolve blockers before proceeding"
        return result

    # Check task queue
    next_task = snapshot.get("next_task", {})
    if next_task.get("task_id"):
        result["decision"] = SupervisorDecision.PROCEED.value
        result["reason"] = (
            f"Next task available: {next_task['task_id']} ({next_task.get('title', '')})"
        )
        result["recommended_action"] = f"Execute task {next_task['task_id']}"
        result["task_id"] = next_task["task_id"]
        return result

    # Nothing to do
    result["decision"] = SupervisorDecision.SKIP.value
    result["reason"] = "No pending tasks or work items"
    result["recommended_action"] = "Idle — wait for new work"
    return result


def execute_decision(
    decision: dict[str, Any],
    *,
    task_queue_file: Path | None = None,
    event_log: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Execute a supervisor decision.

    For PROCEED decisions with a task_id, marks the task as in_progress.
    All decisions are logged to the supervisor event log.

    Returns the execution result.
    """
    from src.workers.task_queue import TaskStatus, update_task_status

    result: dict[str, Any] = {
        "executed": False,
        "dry_run": dry_run,
        "decision": decision["decision"],
        "task_id": decision.get("task_id"),
    }

    event = {
        "event": "supervisor_decision",
        "decision": decision["decision"],
        "reason": decision["reason"],
        "recommended_action": decision["recommended_action"],
        "task_id": decision.get("task_id"),
        "dry_run": dry_run,
    }

    if dry_run:
        logger.info(
            "[DRY-RUN] Supervisor decision: %s — %s", decision["decision"], decision["reason"]
        )
        _append_event(event, event_log)
        return result

    # Execute the decision
    if decision["decision"] == SupervisorDecision.PROCEED.value and decision.get("task_id"):
        updated = update_task_status(
            decision["task_id"],
            TaskStatus.IN_PROGRESS,
            queue_file=task_queue_file,
        )
        if updated:
            result["executed"] = True
            event["task_updated"] = True
    elif decision["decision"] == SupervisorDecision.RESUME.value:
        result["executed"] = True
        event["resume_requested"] = True
    else:
        result["executed"] = True  # Skip/block/circuit_break are informational

    _append_event(event, event_log)
    logger.info("Supervisor decision: %s — %s", decision["decision"], decision["reason"])
    return result


def run_cycle(
    *,
    continuation_state_file: Path | None = None,
    task_queue_file: Path | None = None,
    signals_dir: Path | None = None,
    event_log: Path | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Run one full supervisor cycle: inspect → decide → execute.

    Returns the full cycle result.
    """
    snapshot = inspect_state(
        continuation_state_file=continuation_state_file,
        task_queue_file=task_queue_file,
        signals_dir=signals_dir,
    )

    decision = decide(snapshot)

    execution = execute_decision(
        decision,
        task_queue_file=task_queue_file,
        event_log=event_log,
        dry_run=dry_run,
    )

    return {
        "snapshot": snapshot,
        "decision": decision,
        "execution": execution,
    }


def load_supervisor_events(
    *,
    limit: int = 20,
    event_log: Path | None = None,
) -> list[dict[str, Any]]:
    """Load recent supervisor events from the JSONL log."""
    log = event_log or _EVENT_LOG
    if not log.exists():
        return []
    events = []
    try:
        for line in log.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                events.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    except Exception:
        pass
    return events[-limit:]
