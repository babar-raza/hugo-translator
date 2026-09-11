"""Backfill heal-ticket root_cause_class for tickets written before VA-01.

VA-01 (TC-APT-105 audit, `CampaignRunner._failure_metadata`) narrowed the
`validators=` list a failure records to ERROR-severity validators only,
because that value seeds a heal ticket's ``root_cause_class`` and a
warning-only validator was misattributing causation.  Tickets written BEFORE
that fix kept the first validator of an any-severity list, which for this
corpus is almost always ``LinkValidator`` -- a validator that, in every one of
those tickets, only ever warned.

Measured 2026-09-11 on ``data/campaigns/heal_queue.jsonl``: 475 OPEN tickets
carry ``root_cause_class: auto:LinkValidator``; all 475 use the pre-VA-01 note
format (no ``warning_only_validators=`` token) and in 0 of them did
LinkValidator report an error-severity issue.  Their real error validators are
RepetitionDetectorValidator (287), StructureValidator (105) and
SemanticSimilarityValidator (16); 66 carry no parseable fingerprint.

Those labels are not cosmetic: ``heal_queue.is_quarantined`` (per
(target_lang, root_cause_class)) and ``is_source_path_quarantined`` (per
(source_path, root_cause_class)) both key off the class, as does the runbook's
RECURRENCE ESCALATION count.  A mislabelled third of the queue mis-aims all
three.

This rewrites each affected ticket IN PLACE (per the 2026-09-10 field note:
appending a corrected row does NOT work -- readers evaluate every line
independently with no ticket_id dedup) and keeps an audit trail on the row.
Dry-run by default; --write applies.  Hashes/paths/classes only, never text.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from filelock import FileLock  # noqa: E402

_FINGERPRINTS_RE = re.compile(r"issue_fingerprints=(.*?)(?:;|$)")


def error_validators(note: str) -> list[str]:
    """Return the ERROR-severity validators named in a note's fingerprints."""
    match = _FINGERPRINTS_RE.search(note or "")
    if not match:
        return []
    severities: dict[str, set[str]] = {}
    for fingerprint in match.group(1).split(","):
        parts = fingerprint.split(":")
        if len(parts) > 2:
            severities.setdefault(parts[0], set()).add(parts[1])
    return sorted(name for name, sev in severities.items() if "error" in sev)


def new_class(validators: list[str]) -> str:
    return "auto:" + "+".join(validators)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--heal-queue", default="data/campaigns/heal_queue.jsonl")
    parser.add_argument(
        "--from-class",
        default="auto:LinkValidator",
        help="only rewrite tickets currently carrying this root_cause_class",
    )
    parser.add_argument(
        "--lock",
        default=None,
        help="path of a live campaign's ledger-process.lock to serialize against "
        "(the only concurrent writer of heal_queue.jsonl)",
    )
    parser.add_argument("--write", action="store_true", help="apply (default: dry-run)")
    args = parser.parse_args()

    path = Path(args.heal_queue)
    lock = FileLock(args.lock, timeout=60) if args.lock else None
    stamp = datetime.now(timezone.utc).isoformat()

    if lock is not None:
        lock.acquire()
    try:
        raw = path.read_text(encoding="utf-8").splitlines()
        changed = 0
        skipped_no_fingerprint = 0
        skipped_real_error = 0
        by_new: collections.Counter[str] = collections.Counter()
        out: list[str] = []
        for line in raw:
            if not line.strip():
                out.append(line)
                continue
            row = json.loads(line)
            if row.get("root_cause_class") != args.from_class:
                out.append(line)
                continue
            note = str(row.get("note") or "")
            if "warning_only_validators=" in note:
                # post-VA-01 note: the class already reflects an error validator
                skipped_real_error += 1
                out.append(line)
                continue
            validators = error_validators(note)
            named = args.from_class.split("auto:", 1)[-1]
            if not validators:
                skipped_no_fingerprint += 1
                out.append(line)
                continue
            if named in validators:
                skipped_real_error += 1
                out.append(line)
                continue
            row["root_cause_class"] = new_class(validators)
            row["reclassified_from"] = args.from_class
            row["reclassified_at"] = stamp
            row["reclassified_by"] = "scripts/ops/reclassify_va01_heal_tickets.py (VA-01 backfill)"
            row["reclassification_basis"] = (
                "pre-VA-01 note: root_cause_class named a warning-only validator; "
                "rewritten to the ERROR-severity validator(s) in issue_fingerprints"
            )
            by_new[row["root_cause_class"]] += 1
            changed += 1
            out.append(json.dumps(row, ensure_ascii=False, sort_keys=True))

        print(f"lines={len(raw)} matched_class={args.from_class}")
        print(f"reclassified={changed}")
        print(f"left_alone_no_parseable_fingerprint={skipped_no_fingerprint}")
        print(f"left_alone_class_is_a_real_error={skipped_real_error}")
        for klass, count in by_new.most_common():
            print(f"  -> {klass}: {count}")

        if not args.write:
            print("dry-run: no changes written (pass --write)")
            return 0

        backup = path.with_suffix(path.suffix + f".bak-{stamp[:10].replace('-', '')}-va01")
        if not backup.exists():
            shutil.copy2(path, backup)
            print(f"backup: {backup}")
        tmp = path.with_suffix(path.suffix + ".tmp")
        tmp.write_text("\n".join(out) + "\n", encoding="utf-8", newline="\n")
        os.replace(tmp, path)
        after = path.read_text(encoding="utf-8").splitlines()
        assert len(after) == len(raw), f"line count drift: {len(raw)} -> {len(after)}"
        print(f"written: {path} ({len(after)} lines, unchanged count)")
        return 0
    finally:
        if lock is not None:
            lock.release()


if __name__ == "__main__":
    raise SystemExit(main())
