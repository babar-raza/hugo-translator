"""TC-APT-057: reverification receipts, the evidence standard for RECURRENCE step 2.

project/loop-prompt.md §3 (RECURRENCE ESCALATION): before a new Track-A page
opens, an OPEN root_cause_class with tickets from 2+ pages and an unimplemented
Track-B taskcard forces a closed-loop fix -> reverify -> retrigger sequence.
Step 2's evidence standard, verbatim: "until TC-APT-057's reverification
receipts land, the iteration report must name the exact output file read and
quote the specific defect location now shown clean... once receipts exist, a
data/campaigns/reverification_receipts.jsonl row with gates_passed: true for
every (source_path, target_lang) the class's original tickets name is the
ONLY thing that lifts the obligation -- prose does not count."

This module is that ledger, plus the check that answers "is step 2 satisfied
for this root_cause_class yet" by comparing its receipts against
heal_queue.py's own open_tickets_by_root_cause_class() -- the two ledgers
share the same root_cause_class vocabulary by construction.

Rows are content-free like every other ledger in this mission: source_path,
target_lang, root_cause_class, gates_passed, evidence_path (a pointer to
where the actual proof lives, e.g. a data/summaries/*.json record), and
verified_at. Never candidate or translated text.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from src.workers.heal_queue import open_tickets_by_root_cause_class

_RECEIPTS_FILE = Path("data/campaigns/reverification_receipts.jsonl")


def _receipts_path(override: Path | None) -> Path:
    return override or _RECEIPTS_FILE


def _load_receipts(path: Path) -> list[dict[str, Any]]:
    if not path.exists():
        return []
    rows: list[dict[str, Any]] = []
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return rows


def record_receipt(
    *,
    source_path: str,
    target_lang: str,
    root_cause_class: str,
    gates_passed: bool,
    evidence_path: str,
    receipts_path: Path | None = None,
    verified_at: str | None = None,
) -> dict[str, Any]:
    """Append one reverification receipt. Never pass candidate/translated text here."""
    path = _receipts_path(receipts_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    row = {
        "source_path": source_path,
        "target_lang": target_lang,
        "root_cause_class": root_cause_class,
        "gates_passed": bool(gates_passed),
        "evidence_path": evidence_path,
        "verified_at": verified_at or datetime.now(timezone.utc).isoformat(),
    }
    with path.open("a", encoding="utf-8", newline="\n") as f:
        f.write(json.dumps(row, ensure_ascii=False) + "\n")
    return row


def has_passing_receipt(
    source_path: str, target_lang: str, root_cause_class: str, *, receipts_path: Path | None = None
) -> bool:
    """True if the MOST RECENT receipt for this exact cell has gates_passed=True.

    Most recent, not "any": a later failing re-run must be able to revoke an
    earlier pass rather than have it linger as stale evidence.
    """
    path = _receipts_path(receipts_path)
    matches = [
        row
        for row in _load_receipts(path)
        if row.get("source_path") == source_path
        and row.get("target_lang") == target_lang
        and row.get("root_cause_class") == root_cause_class
    ]
    if not matches:
        return False
    return bool(matches[-1].get("gates_passed"))


def missing_receipts_for_class(
    root_cause_class: str,
    *,
    heal_queue_path: Path | None = None,
    receipts_path: Path | None = None,
) -> list[tuple[str, str]]:
    """(source_path, target_lang) pairs the class's OPEN heal tickets name that still
    lack a passing receipt -- exactly what RECURRENCE step 2 requires closing to zero."""
    open_tickets = open_tickets_by_root_cause_class(root_cause_class, heal_queue_path=heal_queue_path)
    named_cells = {
        (ticket["source_path"], ticket["target_lang"])
        for ticket in open_tickets
        if ticket.get("source_path") and ticket.get("target_lang")
    }
    return sorted(
        cell
        for cell in named_cells
        if not has_passing_receipt(cell[0], cell[1], root_cause_class, receipts_path=receipts_path)
    )


def recurrence_step2_satisfied(
    root_cause_class: str,
    *,
    heal_queue_path: Path | None = None,
    receipts_path: Path | None = None,
) -> bool:
    """True once every OPEN ticket the class names has a passing receipt.

    A class with zero open tickets is vacuously satisfied -- there is nothing
    left to reverify, which matches the RECURRENCE rule's own intent (it exists
    to force a fix-and-prove cycle, not to block forever once one has happened).
    """
    return not missing_receipts_for_class(
        root_cause_class, heal_queue_path=heal_queue_path, receipts_path=receipts_path
    )
