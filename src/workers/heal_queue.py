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

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

_HEAL_QUEUE_FILE = Path("data/campaigns/heal_queue.jsonl")
QUARANTINE_THRESHOLD = 3
# QU-01 (TC-APT-105 audit): a per-locale threshold of 3 misses a source file
# whose defect reproduces identically across many locales but never
# accumulates 3 tickets for any single one (the live case: quickstart.md hit
# LinkValidator on 7+ distinct locales, one ticket each -- systemic, but
# invisible to the per-locale count). Reusing QUARANTINE_THRESHOLD's own
# number keeps the two dimensions consistent rather than inventing an
# arbitrary second constant: 3 independent signals (here, 3 separate locales
# hitting the same root_cause_class on the same file) is this mission's
# established bar for "this is systemic, not noise" before halting further
# spend on a cell.
PER_FILE_QUARANTINE_THRESHOLD = QUARANTINE_THRESHOLD
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


def open_ticket_locales_by_file_class(
    *, heal_queue_path: Path | None = None
) -> dict[tuple[str, str], set[str]]:
    """Distinct target_lang values with an OPEN, unresolved ticket, grouped by
    (source_path, root_cause_class) -- the per-file quarantine dimension (QU-02).

    A source file whose same defect class reproduces across many locales is
    systemic even when no single locale individually reaches
    QUARANTINE_THRESHOLD tickets of its own.
    """
    path = heal_queue_path or _HEAL_QUEUE_FILE
    locales: dict[tuple[str, str], set[str]] = {}
    for ticket in _load_tickets(path):
        if not _counts_toward_quarantine(ticket):
            continue
        source_path = ticket.get("source_path")
        root_cause_class = ticket.get("root_cause_class")
        lang = ticket.get("target_lang")
        if not source_path or not root_cause_class or not lang:
            continue
        locales.setdefault((source_path, root_cause_class), set()).add(lang)
    return locales


def quarantined_files(
    *,
    heal_queue_path: Path | None = None,
    threshold: int = PER_FILE_QUARANTINE_THRESHOLD,
) -> set[tuple[str, str]]:
    """Return every (source_path, root_cause_class) pair whose OPEN tickets span
    >=threshold distinct locales -- quarantined for that file/class regardless
    of how few tickets any single locale has."""
    locales = open_ticket_locales_by_file_class(heal_queue_path=heal_queue_path)
    return {key for key, langs in locales.items() if len(langs) >= threshold}


def is_source_path_quarantined(
    source_path: str,
    *,
    heal_queue_path: Path | None = None,
    threshold: int = PER_FILE_QUARANTINE_THRESHOLD,
) -> tuple[bool, str | None]:
    """Whether this exact source_path has a root_cause_class quarantined under
    the per-file dimension (QU-02): OPEN tickets for that class spanning
    >=threshold distinct locales, regardless of this call's own locale or
    whether it has any prior failure history at all -- an unseen locale on an
    already-systemic file is still skipped, matching the live incident where
    the same file kept accumulating fresh single-locale tickets for the same
    defect indefinitely.

    Returns (True, root_cause_class) for the first quarantined class found on
    this path, else (False, None). Independent of, and coexists with,
    ``is_quarantined``'s (target_lang, root_cause_class) dimension -- neither
    double-counts the other's tickets since each reads the same underlying
    OPEN-ticket set through its own grouping key.
    """
    for (path, root_cause_class), langs in open_ticket_locales_by_file_class(
        heal_queue_path=heal_queue_path
    ).items():
        if path == source_path and len(langs) >= threshold:
            return True, root_cause_class
    return False, None


# --- QU-03: human/agent-authored advisory holds -----------------------------
#
# A hold is a distinct event kind from the automated ticket lifecycle above
# (status/disposition): it is a deliberate "stop touching this file" signal a
# person or session leaves, with a mandatory reason, appended the same
# append-only way as everything else in this file. It carries no
# root_cause_class/target_lang, so it can never be picked up by
# is_quarantined()/is_source_path_quarantined() or count toward either
# quarantine dimension above -- an advisory hold is an operator decision, not
# a validator finding, and must never be conflated with one.
#
# Closes the confirmed gap where a prior incident's human note describing a
# problem file had zero enforcement effect on the running automation -- it
# was prose nobody's code ever read. This gives that note a machine-checked
# effect instead.

_HOLD_KIND = "hold"
_RELEASE_KIND = "release"


def add_hold(
    source_path: str,
    reason: str,
    *,
    expiry: str | None = None,
    heal_queue_path: Path | None = None,
) -> dict[str, Any]:
    """Place an advisory hold on ``source_path``. Mandatory ``reason``; an
    optional ISO-8601 ``expiry`` (UTC) stops the hold from blocking
    automatically once passed, so a forgotten hold cannot block work
    indefinitely. Appended, never mutates prior entries -- release with
    ``release_hold()``."""
    if not reason or not reason.strip():
        raise ValueError("add_hold requires a non-empty reason")
    path = heal_queue_path or _HEAL_QUEUE_FILE
    ticket: dict[str, Any] = {
        "kind": _HOLD_KIND,
        "source_path": source_path,
        "reason": reason.strip(),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "expiry": expiry,
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ticket) + "\n")
    return ticket


def release_hold(
    source_path: str, *, heal_queue_path: Path | None = None
) -> dict[str, Any]:
    """Release any active advisory hold on ``source_path``."""
    path = heal_queue_path or _HEAL_QUEUE_FILE
    ticket: dict[str, Any] = {
        "kind": _RELEASE_KIND,
        "source_path": source_path,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as f:
        f.write(json.dumps(ticket) + "\n")
    return ticket


def active_hold(
    source_path: str,
    *,
    heal_queue_path: Path | None = None,
    now: datetime | None = None,
) -> dict[str, Any] | None:
    """Return the active hold ticket for ``source_path``, or None.

    Replays hold/release events for this path in file (== chronological,
    append-only) order: the latest event wins. A hold past its ``expiry``
    (if any) is treated as not active, without requiring an explicit
    release.
    """
    path = heal_queue_path or _HEAL_QUEUE_FILE
    current = datetime.now(timezone.utc) if now is None else now
    latest_hold: dict[str, Any] | None = None
    for ticket in _load_tickets(path):
        if ticket.get("source_path") != source_path:
            continue
        kind = ticket.get("kind")
        if kind == _HOLD_KIND:
            latest_hold = ticket
        elif kind == _RELEASE_KIND:
            latest_hold = None
    if latest_hold is None:
        return None
    expiry = latest_hold.get("expiry")
    if expiry:
        try:
            expiry_dt = datetime.fromisoformat(str(expiry).replace("Z", "+00:00"))
        except ValueError:
            return latest_hold  # malformed expiry -- fail safe by still holding
        if current >= expiry_dt:
            return None
    return latest_hold


def _build_cli_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m src.workers.heal_queue",
        description=(
            "Advisory hold management (QU-03). Use `hold` to stop campaign "
            "scheduling on a source_path immediately, without a code deploy, "
            "while investigating a problem file -- prefer this over a plain "
            "comment or Slack note, which have no enforcement effect on the "
            "running automation. Use `release` once done. Use a normal heal "
            "ticket instead of a hold for an automated validator finding."
        ),
    )
    sub = parser.add_subparsers(dest="command", required=True)

    hold = sub.add_parser("hold", help="Place an advisory hold on a source_path.")
    hold.add_argument("--source-path", required=True)
    hold.add_argument("--reason", required=True)
    hold.add_argument(
        "--expiry",
        default=None,
        help="Optional ISO-8601 UTC timestamp (e.g. 2026-09-12T00:00:00Z) after which "
        "the hold stops blocking automatically.",
    )

    release = sub.add_parser("release", help="Release an active advisory hold on a source_path.")
    release.add_argument("--source-path", required=True)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = _build_cli_parser().parse_args(argv)
    if args.command == "hold":
        ticket = add_hold(args.source_path, args.reason, expiry=args.expiry)
        suffix = f" (expires {ticket['expiry']})" if ticket.get("expiry") else ""
        print(f"Hold placed on {ticket['source_path']}: {ticket['reason']}{suffix}")
    elif args.command == "release":
        release_hold(args.source_path)
        print(f"Hold released on {args.source_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
