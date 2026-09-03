"""TC-APT-029: campaign supervision wired into the existing ``supervisor_loop.decide()``.

Mission ``aspose-org-full-portfolio-translation-20260901`` (plan section 2.7 build-vs-reuse
audit, section 11 TC-APT-029, section 21 STATE step).  The ``/loop`` wake does NOT carry
bespoke phase-check branching; it derives a *mission-scoped* ``task_queue.jsonl`` and
``continuation_state.json`` from the authoritative ``taskcard_status.json`` and hands the
resulting snapshot to :func:`src.workers.supervisor_loop.decide` -- whose branching
logic is reused unmodified (PROCEED / SKIP / BLOCK / CIRCUIT_BREAK / RESUME).

Scope boundary (section 2.7): this deliberately does not route through
``worker_orchestrator.py``'s preflight wrapper, which concerns OS worker-process
launches.

Mapping (deterministic, re-derived every wake so it is idempotent):

* taskcard ``TODO``/``IN_PROGRESS``            -> queue ``pending`` (deps = section 11 depends_on)
* taskcard ``DONE``                            -> queue ``completed`` (so dependents unlock)
* taskcard ``BLOCKED_TRUE_EXTERNAL``           -> queue ``blocked`` + continuation blocker
* open circuit breaker (``data/runtime/circuit_breaker/<model>.json`` state ``open``)
                                               -> continuation blocker ``circuit_breaker_open``
* PHASE B manifest-scoped work items (caller-supplied) -> queue ``pending`` in lane ``PHASE_B``

A ``BLOCK`` never idles the mission (section 21): the caller still works every queued item
the blocker does not touch; this module only *reports* the decision faithfully.

Usage:
    python -m src.workers.mission_supervisor [--mission-dir DIR] [--dry-run] [--json]
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.workers import continuation_state as cs
from src.workers import supervisor_loop as sl
from src.workers import task_queue as tq

logger = logging.getLogger(__name__)

MISSION_ID = "aspose-org-full-portfolio-translation-20260901"
DEFAULT_MISSION_DIR = Path(".supervisor/state") / MISSION_ID
DEFAULT_CIRCUIT_BREAKER_DIR = Path("data/runtime/circuit_breaker")

STATUS_FILE = "taskcard_status.json"
QUEUE_FILE = "task_queue.jsonl"
CONTINUATION_FILE = "continuation_state.json"
EVENTS_FILE = "supervisor_events.jsonl"
SIGNALS_DIR = "signals"

#: Plan section 21: PHASE A while any of these is not DONE; otherwise PHASE B.
PHASE_A_TASKCARDS: tuple[str, ...] = (
    "TC-APT-001",
    "TC-APT-002",
    "TC-APT-003",
    "TC-APT-022",
    "TC-APT-030",
    "TC-APT-029",
    "TC-APT-025",
    "TC-APT-026",
    "TC-APT-027",
    "TC-APT-005",
    "TC-APT-028",
    "TC-APT-004",
    "TC-APT-006",
    # TC-APT-004b deliberately excluded (plan revision 6, section 0): the
    # original design made PHASE B wait for this taskcard, serializing every
    # translation output behind the slowest, most fragile task. It is now
    # Track B qualification work (never gates Track A) -- gate 4's actual
    # blockers (TC-APT-010/026/031/032) are independent of it. Root cause
    # verified live: 30/33 taskcards DONE, four qualification restarts, zero
    # content(locale) commits.
    "TC-APT-021",
    "TC-APT-007",
    "TC-APT-008",
    "TC-APT-009",
    "TC-APT-024",
    "TC-APT-031",
    "TC-APT-032",
    "TC-APT-010",
    "TC-APT-011",
    "TC-APT-023",
    "TC-APT-012",
)

TASKCARD_STATES = ("TODO", "IN_PROGRESS", "BLOCKED_TRUE_EXTERNAL", "DONE")
#: Section 21: the only two conditions that may ever mark BLOCKED_TRUE_EXTERNAL.
TRUE_EXTERNAL_BLOCKER_TYPES = ("provider_outage_beyond_fallback", "hardware_or_disk_failure")


class MissionStatusError(RuntimeError):
    """The taskcard_status.json file is missing or malformed."""


# --------------------------------------------------------------------------- status I/O
def status_path(mission_dir: Path) -> Path:
    return mission_dir / STATUS_FILE


def load_status(mission_dir: Path) -> dict[str, Any]:
    path = status_path(mission_dir)
    if not path.is_file():
        raise MissionStatusError(f"missing {path}")
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise MissionStatusError(f"unreadable {path}: {exc}") from exc
    cards = data.get("taskcards")
    if not isinstance(cards, dict) or not cards:
        raise MissionStatusError(f"{path} has no taskcards")
    for tid, card in cards.items():
        if card.get("status") not in TASKCARD_STATES:
            raise MissionStatusError(f"{tid}: invalid status {card.get('status')!r}")
    return data


def save_status(mission_dir: Path, status: dict[str, Any]) -> None:
    status["updated_at"] = datetime.now(timezone.utc).isoformat()
    tmp = status_path(mission_dir).with_suffix(".json.tmp")
    tmp.write_text(json.dumps(status, indent=2), encoding="utf-8")
    tmp.replace(status_path(mission_dir))


def set_taskcard(
    mission_dir: Path,
    taskcard_id: str,
    status_value: str,
    *,
    evidence_path: str | None = None,
    commit: str | None = None,
    blocking_reason: str | None = None,
    blocker_type: str | None = None,
) -> dict[str, Any]:
    """Update one taskcard; BLOCKED_TRUE_EXTERNAL requires one of the two section-21 blocker types."""
    if status_value not in TASKCARD_STATES:
        raise ValueError(f"invalid taskcard status {status_value!r}")
    if status_value == "BLOCKED_TRUE_EXTERNAL" and blocker_type not in TRUE_EXTERNAL_BLOCKER_TYPES:
        raise ValueError(
            "BLOCKED_TRUE_EXTERNAL is reserved for "
            f"{TRUE_EXTERNAL_BLOCKER_TYPES}; got {blocker_type!r}"
        )
    status = load_status(mission_dir)
    card = status["taskcards"].get(taskcard_id)
    if card is None:
        raise MissionStatusError(f"unknown taskcard {taskcard_id}")
    card["status"] = status_value
    card["last_updated"] = datetime.now(timezone.utc).isoformat()
    if evidence_path is not None:
        card["evidence_path"] = evidence_path
    if commit is not None:
        card["commit"] = commit
    card["blocking_reason"] = blocking_reason if status_value == "BLOCKED_TRUE_EXTERNAL" else None
    card["blocker_type"] = blocker_type if status_value == "BLOCKED_TRUE_EXTERNAL" else None
    save_status(mission_dir, status)
    return card


# --------------------------------------------------------------------------- derivations
def determine_phase(status: dict[str, Any]) -> str:
    cards = status["taskcards"]
    for tid in PHASE_A_TASKCARDS:
        if cards.get(tid, {}).get("status") != "DONE":
            return "A"
    return "B"


def open_circuit_breakers(circuit_breaker_dir: Path | None) -> list[dict[str, Any]]:
    """Return ``[{model_id, state, path}]`` for every breaker file whose state is open.

    Convention (TC-APT-004 writes it, this reads it): ``<dir>/<model_id>.json`` with a
    top-level ``state`` of ``closed`` | ``open`` | ``half_open``.  Unreadable files are
    reported as open -- an unknown breaker state must never be mistaken for healthy.
    """
    if circuit_breaker_dir is None or not circuit_breaker_dir.is_dir():
        return []
    found: list[dict[str, Any]] = []
    for path in sorted(circuit_breaker_dir.glob("*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            state = str(data.get("state", "unknown")).lower()
        except (OSError, json.JSONDecodeError, AttributeError):
            state = "unreadable"
        if state not in ("closed", "half_open"):
            found.append({"model_id": path.stem, "state": state, "path": path.as_posix()})
    return found


def derive_blockers(
    status: dict[str, Any],
    *,
    circuit_breaker_dir: Path | None = None,
) -> list[dict[str, Any]]:
    blockers: list[dict[str, Any]] = []
    for tid, card in sorted(status["taskcards"].items()):
        if card.get("status") == "BLOCKED_TRUE_EXTERNAL":
            blockers.append(
                {
                    "blocker_id": f"taskcard:{tid}",
                    "type": card.get("blocker_type") or "true_external",
                    "description": card.get("blocking_reason") or f"{tid} BLOCKED_TRUE_EXTERNAL",
                }
            )
    for breaker in open_circuit_breakers(circuit_breaker_dir):
        blockers.append(
            {
                "blocker_id": f"circuit_breaker:{breaker['model_id']}",
                "type": "circuit_breaker_open",
                "description": (
                    f"{breaker['model_id']} circuit breaker state={breaker['state']} "
                    f"({breaker['path']}); run this wake on the automatic m2m100_418m fallback"
                ),
            }
        )
    return blockers


def _priority_for_gate(gate: Any) -> str:
    try:
        g = int(gate)
    except (TypeError, ValueError):
        g = 3
    return f"P{min(max(g, 0), 3)}"


def sync_task_queue(
    status: dict[str, Any],
    queue_file: Path,
    *,
    phase_b_items: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Re-derive the mission queue from taskcard status (PHASE A) or supplied items (PHASE B).

    The queue file is rewritten from scratch each wake; it is a projection, not a record.
    """
    phase = determine_phase(status)
    if queue_file.exists():
        queue_file.unlink()
    cards = status["taskcards"]
    if phase == "A":
        for tid, card in cards.items():
            tq.add_task(
                tid,
                str(card.get("title", tid)),
                lane="PHASE_A",
                priority=_priority_for_gate(card.get("gate", 3)),
                horizon=int(card.get("gate", 0) or 0),
                depends_on=list(card.get("depends_on", [])),
                queue_file=queue_file,
            )
            state = card.get("status")
            if state == "DONE":
                tq.update_task_status(tid, tq.TaskStatus.COMPLETED, queue_file=queue_file)
            elif state == "BLOCKED_TRUE_EXTERNAL":
                tq.add_blocker(
                    tid,
                    card.get("blocker_type") or "true_external",
                    card.get("blocking_reason") or "",
                    queue_file=queue_file,
                )
    else:
        # PHASE B: PHASE A cards are all DONE; register them completed so nothing is
        # re-offered, then queue the manifest-scoped work items the caller selected.
        for tid, card in cards.items():
            if card.get("status") == "DONE":
                tq.add_task(tid, str(card.get("title", tid)), queue_file=queue_file)
                tq.update_task_status(tid, tq.TaskStatus.COMPLETED, queue_file=queue_file)
        for item in phase_b_items or []:
            tq.add_task(
                str(item["task_id"]),
                str(item.get("title", item["task_id"])),
                lane="PHASE_B",
                priority=str(item.get("priority", "P1")),
                horizon=int(item.get("wave", 0) or 0),
                depends_on=list(item.get("depends_on", [])),
                metadata=dict(item.get("metadata", {})),
                queue_file=queue_file,
            )
    summary = tq.queue_summary(queue_file=queue_file)
    summary["phase"] = phase
    return summary


def sync_continuation_blockers(
    status: dict[str, Any],
    state_file: Path,
    *,
    circuit_breaker_dir: Path | None = None,
) -> list[dict[str, Any]]:
    blockers = derive_blockers(status, circuit_breaker_dir=circuit_breaker_dir)
    cs.replace_blockers(blockers, state_file=state_file)
    return blockers


# --------------------------------------------------------------------------- the wake
def wake(
    mission_dir: Path = DEFAULT_MISSION_DIR,
    *,
    phase_b_items: list[dict[str, Any]] | None = None,
    circuit_breaker_dir: Path | None = DEFAULT_CIRCUIT_BREAKER_DIR,
    dry_run: bool = False,
) -> dict[str, Any]:
    """One section-21 STATE step: sync projections, then ``supervisor_loop.decide()`` and act."""
    status = load_status(mission_dir)
    queue_file = mission_dir / QUEUE_FILE
    state_file = mission_dir / CONTINUATION_FILE
    events = mission_dir / EVENTS_FILE

    queue_summary = sync_task_queue(status, queue_file, phase_b_items=phase_b_items)
    blockers = sync_continuation_blockers(
        status, state_file, circuit_breaker_dir=circuit_breaker_dir
    )
    snapshot = sl.inspect_state(
        continuation_state_file=state_file,
        task_queue_file=queue_file,
        signals_dir=mission_dir / SIGNALS_DIR,
    )
    decision = sl.decide(snapshot)
    execution = sl.execute_decision(
        decision, task_queue_file=queue_file, event_log=events, dry_run=dry_run
    )
    # The pending items a BLOCK must still work (section 21: a BLOCK never idles the mission).
    workable = [
        t["task_id"] for t in tq.load_all_tasks(status=tq.TaskStatus.PENDING, queue_file=queue_file)
    ]
    return {
        "mission_id": status.get("mission_id", MISSION_ID),
        "phase": queue_summary["phase"],
        "queue": queue_summary,
        "blockers": blockers,
        "snapshot": snapshot,
        "decision": decision,
        "execution": execution,
        "workable_pending": workable,
    }


#: TC-APT-033 (plan revision 6, section 0): the "wrong progress metric" root
#: cause -- 30/33 taskcards DONE read as 91% while 0 cells had shipped.
#: Progress is committed/eligible cells, not taskcards. These are the
#: page_language_work states representing real, actionable-now Track A
#: work (excludes UNKNOWN_PROVENANCE, which needs section 7.4's sampling
#: gate first, and the non-actionable/terminal states).
ACTIONABLE_ELIGIBILITY_STATES: tuple[str, ...] = (
    "MISSING_TRANSLATION",
    "SOURCE_CHANGED",
    "PROFILE_CHANGED",
    "PROTECTION_RULE_CHANGED",
    "MODEL_OR_PROMPT_INVALIDATED",
)

DEFAULT_LEDGER_PATH = Path("data/campaigns/work_ledger.sqlite3")


def cells_eligible_total(ledger_path: Path = DEFAULT_LEDGER_PATH) -> int:
    """Count of page_language_work rows in an actionable-now state."""
    if not ledger_path.is_file():
        return 0
    from src.workers.work_ledger import WorkLedger

    with WorkLedger(ledger_path) as ledger:
        counts = ledger.counts_by_state()
    return sum(counts.get(state, 0) for state in ACTIONABLE_ELIGIBILITY_STATES)


def record_cells_committed(mission_dir: Path, n: int) -> int:
    """Persist this wake's newly-committed cell count into the mission-scoped
    running total (taskcard_status.json's own field, since the ledger's
    UP_TO_DATE state does not distinguish mission-committed output from
    pre-existing legacy content). Returns the new running total."""
    path = status_path(mission_dir)
    status = load_status(mission_dir)
    total = int(status.get("cells_committed_total", 0)) + int(n)
    status["cells_committed_total"] = total
    path.write_text(json.dumps(status, indent=2), encoding="utf-8")
    return total


def track_b_budget_ok(
    track_b_seconds: float, wake_seconds: float, *, track_a_has_eligible_cells: bool
) -> bool:
    """Section 21 output invariant: Track B may use at most 50% of a wake's
    working time while Track A still has eligible cells -- when Track A is
    genuinely empty, Track B may use the whole wake."""
    if not track_a_has_eligible_cells:
        return True
    if wake_seconds <= 0:
        return True
    return (track_b_seconds / wake_seconds) <= 0.5


def output_invariant_summary(
    mission_dir: Path = DEFAULT_MISSION_DIR,
    *,
    ledger_path: Path = DEFAULT_LEDGER_PATH,
    cells_committed_this_wake: int = 0,
    track_b_seconds: float = 0.0,
    wake_seconds: float = 0.0,
) -> dict[str, Any]:
    """TC-APT-033's fields for the wake summary (section 21 REPORT step)."""
    status = load_status(mission_dir)
    total_committed = int(status.get("cells_committed_total", 0))
    eligible = cells_eligible_total(ledger_path)
    progress = round(total_committed / (total_committed + eligible), 4) if (total_committed + eligible) else 0.0
    return {
        "cells_committed_this_wake": cells_committed_this_wake,
        "cells_committed_total": total_committed,
        "cells_eligible_total": eligible,
        "progress": progress,
        "track_b_time_share": round(track_b_seconds / wake_seconds, 4) if wake_seconds else 0.0,
        "track_b_budget_ok": track_b_budget_ok(
            track_b_seconds, wake_seconds, track_a_has_eligible_cells=eligible > 0
        ),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Mission supervisor wake (TC-APT-029)")
    parser.add_argument("--mission-dir", type=Path, default=DEFAULT_MISSION_DIR)
    parser.add_argument("--circuit-breaker-dir", type=Path, default=DEFAULT_CIRCUIT_BREAKER_DIR)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--json", action="store_true", help="print the full wake result as JSON")
    args = parser.parse_args(argv)
    result = wake(
        args.mission_dir, circuit_breaker_dir=args.circuit_breaker_dir, dry_run=args.dry_run
    )
    if args.json:
        print(json.dumps(result, indent=2, default=str))
    else:
        d = result["decision"]
        print(
            f"phase={result['phase']} decision={d['decision']} "
            f"task={d.get('task_id')} :: {d['reason']}"
        )
        for b in result["blockers"]:
            print(f"  blocker {b['blocker_id']} [{b['type']}]: {b['description']}")
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
