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
    """Open unless terminally disposed, whichever field carries the state.

    The runbook defines this directly (TC-APT-060): "OPEN means `disposition` is
    absent or `OPEN`". It says nothing about a `status` field, and the heal queue
    genuinely holds both shapes -- older rows carry only `disposition: "OPEN"`
    while newer ones carry `status: "OPEN"`.

    Requiring `status == "OPEN"` therefore made every disposition-only ticket
    invisible to this module. Measured when found: all 16
    producer_softwrap_sentence_split tickets read as zero open tickets, so
    recurrence_step2_satisfied() returned True having verified nothing -- the
    exact false-clearance the receipt standard exists to prevent -- and the
    3-ticket quarantine threshold could never fire for those rows either.
    """
    if ticket.get("disposition") in _RESOLVED_DISPOSITIONS:
        return False
    status = ticket.get("status")
    if status is not None and str(status).upper() != "OPEN":
        return False
    return True


def open_tickets_by_root_cause_class(
    root_cause_class: str, *, heal_queue_path: Path | None = None
) -> list[dict[str, Any]]:
    """OPEN, unresolved tickets for one root_cause_class -- e.g. the exact set the
    RECURRENCE ESCALATION rule (project/loop-prompt.md §3) needs a reverification
    receipt for before a new Track-A page can open."""
    path = heal_queue_path or _HEAL_QUEUE_FILE
    return [
        ticket
        for ticket in _load_tickets(path)
        if ticket.get("root_cause_class") == root_cause_class and _counts_toward_quarantine(ticket)
    ]


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


def open_tickets_for_source_path(
    source_path: str, *, heal_queue_path: Path | None = None
) -> list[dict[str, Any]]:
    """QU-01 (TC-APT-105 audit): OPEN, unresolved tickets naming this exact
    `source_path` -- the read-helper a manifest builder consults before
    scheduling new work against a file, so a fresh campaign_id doesn't
    start blind to a defect a prior campaign already ticketed (confirmed
    live: `build_campaign_manifest.py` never consulted this file at all,
    so `quickstart.md`/`features.md` were re-included in a new manifest a
    day after TC-APT-105's original finding on the same files).

    Matching an exact `source_path` string, not a fuzzy/normalized one --
    callers own path normalization (e.g. posix vs. native separators)
    before calling this.
    """
    path = heal_queue_path or _HEAL_QUEUE_FILE
    return [
        ticket
        for ticket in _load_tickets(path)
        if ticket.get("source_path") == source_path and _counts_toward_quarantine(ticket)
    ]


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
