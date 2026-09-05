"""TC-APT-038: heal-queue quarantine bookkeeping.

Gate-close semantics (plan §12/revision 8): a gate closes when its scope is
exercised and every non-committed cell has a ticket -- never N/N. A
(target_lang, root_cause_class) pair with >=3 OPEN tickets is quarantined
as a pair: further attempts on that combination are skipped across every
page (not just the one that first surfaced it) until the underlying defect
is fixed. There is nothing to "re-queue" explicitly -- a pair falls out of
quarantine automatically the moment its OPEN-ticket count drops back below
threshold, which happens once tickets are resolved (see
_counts_toward_quarantine).

Counting rule matches project/loop-prompt.md's RECURRENCE ESCALATION section
exactly, so this module can be dropped into that manual reasoning without
changing its meaning: OPEN means `status == "OPEN"` and `disposition` is
absent or `"OPEN"`. TC-APT-060 will start writing `disposition` values of
FIXED_VERIFIED / WAIVED_RUBRIC / MODEL_LIMITATION_DEFERRED; this module
already treats any of those as resolved so no change will be needed here
when that lands.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

_HEAL_QUEUE_FILE = Path("data/campaigns/heal_queue.jsonl")
QUARANTINE_THRESHOLD = 3
_RESOLVED_DISPOSITIONS = frozenset(
    {"FIXED_VERIFIED", "WAIVED_RUBRIC", "MODEL_LIMITATION_DEFERRED"}
)


def _load_tickets(heal_queue_path: Path) -> list[dict[str, Any]]:
    if not heal_queue_path.exists():
        return []
    tickets: list[dict[str, Any]] = []
    for line in heal_queue_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            tickets.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return tickets


def _counts_toward_quarantine(ticket: dict[str, Any]) -> bool:
    if ticket.get("status") != "OPEN":
        return False
    disposition = ticket.get("disposition")
    return disposition is None or disposition not in _RESOLVED_DISPOSITIONS


def open_ticket_counts_by_pair(
    *, heal_queue_path: Path | None = None
) -> dict[tuple[str, str], int]:
    """Count OPEN, unresolved tickets grouped by (target_lang, root_cause_class)."""
    path = heal_queue_path or _HEAL_QUEUE_FILE
    counts: dict[tuple[str, str], int] = {}
    for ticket in _load_tickets(path):
        if not _counts_toward_quarantine(ticket):
            continue
        lang = ticket.get("target_lang")
        root_cause_class = ticket.get("root_cause_class")
        if not lang or not root_cause_class:
            continue
        key = (lang, root_cause_class)
        counts[key] = counts.get(key, 0) + 1
    return counts


def quarantined_pairs(
    *, heal_queue_path: Path | None = None, threshold: int = QUARANTINE_THRESHOLD
) -> set[tuple[str, str]]:
    """Return every (target_lang, root_cause_class) pair at or past the threshold."""
    counts = open_ticket_counts_by_pair(heal_queue_path=heal_queue_path)
    return {pair for pair, n in counts.items() if n >= threshold}


def is_quarantined(
    target_lang: str,
    root_cause_class: str,
    *,
    heal_queue_path: Path | None = None,
    threshold: int = QUARANTINE_THRESHOLD,
) -> bool:
    """Whether (target_lang, root_cause_class) currently has >=threshold OPEN tickets."""
    return (target_lang, root_cause_class) in quarantined_pairs(
        heal_queue_path=heal_queue_path, threshold=threshold
    )
