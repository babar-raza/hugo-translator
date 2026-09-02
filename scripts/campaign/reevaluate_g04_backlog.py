"""Re-evaluate G-04's undrained backlog against the TC-APT-003 work ledger (TC-APT-009).

The audit-phase7 closure left ``data/retranslate_queue.jsonl`` and ``data/quarantine.jsonl``
undrained.  Their original phase-7 categorisation is NOT trusted (plan TC-APT-009): every row is
re-resolved against the ledger's *current* eligibility state, so the backlog stops being a
parallel, stale work list and becomes a view over the one ledger.

Rows are matched by output path (queue rows store a content-repo-relative or absolute output
path).  Each row is reported as:

  resolved_by_ledger  -- the cell exists and the ledger already schedules it (MISSING_TRANSLATION,
                         SOURCE_CHANGED, UNKNOWN_PROVENANCE, ...): the queue entry is redundant
  already_up_to_date  -- the ledger says UP_TO_DATE: the queue entry is stale
  excluded_by_profile -- the queue targets one of the 11 disabled locales: never actionable
  no_ledger_cell      -- the path is not a cell of the current portfolio (retired locale, moved
                         or deleted source): not actionable, recorded
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.utils.atomic_write import atomic_write
from src.workers.work_ledger import DEFAULT_LEDGER_PATH, WorkLedger

DEFAULT_QUEUES = (Path("data/retranslate_queue.jsonl"), Path("data/quarantine.jsonl"))
DEFAULT_REPORT = Path("data/quality/g04_backlog_reevaluation.json")


def normalize(path_value: str, content_repo: Path) -> str:
    """Content-repo-relative POSIX path for a queue row's output_path."""
    raw = str(path_value or "").replace("\\", "/")
    if not raw:
        return ""
    p = Path(raw)
    if p.is_absolute():
        try:
            return p.resolve().relative_to(content_repo.resolve()).as_posix()
        except ValueError:
            return p.as_posix()
    idx = raw.find("content/")
    return raw[idx:] if idx >= 0 else raw


def reevaluate(queues, ledger: WorkLedger, content_repo: Path) -> dict:
    by_output: dict[str, dict] = {}
    for row in ledger.query():
        by_output[row["expected_output_path"]] = row
    report: dict = {"queues": {}, "totals": Counter(), "states": Counter(), "samples": []}
    for queue_path in queues:
        if not Path(queue_path).is_file():
            report["queues"][str(queue_path)] = {"rows": 0, "missing": True}
            continue
        outcome: Counter[str] = Counter()
        states: Counter[str] = Counter()
        rows = 0
        for line in Path(queue_path).read_text(encoding="utf-8").splitlines():
            if not line.strip():
                continue
            rows += 1
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                outcome["unparsable"] += 1
                continue
            rel = normalize(item.get("output_path", ""), content_repo)
            cell = by_output.get(rel)
            if cell is None:
                outcome["no_ledger_cell"] += 1
                if len(report["samples"]) < 15:
                    report["samples"].append(
                        {
                            "queue": Path(queue_path).name,
                            "output_path": rel,
                            "verdict": "no_ledger_cell",
                        }
                    )
                continue
            state = cell["eligibility_state"]
            states[state] += 1
            if state == "EXCLUDED_BY_PROFILE":
                outcome["excluded_by_profile"] += 1
            elif state == "UP_TO_DATE":
                outcome["already_up_to_date"] += 1
            else:
                outcome["resolved_by_ledger"] += 1
        report["queues"][str(queue_path)] = {
            "rows": rows,
            "outcome": dict(outcome),
            "states": dict(states),
        }
        report["totals"].update(outcome)
        report["states"].update(states)
    report["totals"] = dict(report["totals"])
    report["states"] = dict(report["states"])
    return report


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-009 G-04 backlog re-evaluation")
    parser.add_argument(
        "--content-repo", type=Path, default=Path("D:/onedrive/Documents/GitHub/aspose.org")
    )
    parser.add_argument("--ledger", type=Path, default=DEFAULT_LEDGER_PATH)
    parser.add_argument("--queue", action="append", type=Path, dest="queues")
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    with WorkLedger(args.ledger) as ledger:
        report = reevaluate(args.queues or list(DEFAULT_QUEUES), ledger, args.content_repo)
    report["at"] = datetime.now(timezone.utc).isoformat()
    atomic_write(path=args.report, content=json.dumps(report, indent=2))
    print(json.dumps({k: v for k, v in report.items() if k != "samples"}, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
