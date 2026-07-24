#!/usr/bin/env python
"""
TC-P7-14: Enqueue all backlog-routed rows for future retranslation.

Reuses src/tm/retranslate_queue.py's add_to_queue() directly (the same
real, already-wired-in mechanism directory_orchestrator.py and engine.py
use) rather than force_retranslate_contaminated.py's CLI, since that
script's --inventory expects scan_language_contamination.py's specific
JSON schema and this mission's backlog manifests are simple per-category
CSVs -- calling add_to_queue() directly avoids an unnecessary format
adapter for the same underlying queue.

Reads every reports/audit/backlog_*.csv this mission produced. "No silent
drops": every row is accounted for in the printed counters, matching the
force_retranslate_contaminated.py precedent's own n_queued/n_already_queued
pattern.

Usage:
    python scripts/quality/enqueue_backlog.py --dry-run
    python scripts/quality/enqueue_backlog.py --write
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from src.tm.retranslate_queue import add_to_queue, load_queued_paths  # noqa: E402


def find_backlog_files(reports_dir: Path) -> list[Path]:
    return sorted(reports_dir.glob("backlog_*.csv"))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--reports-dir", default="reports/audit")
    ap.add_argument("--write", action="store_true", help="Actually enqueue. Default is dry-run.")
    args = ap.parse_args()

    backlog_files = find_backlog_files(Path(args.reports_dir))
    print(f"Found {len(backlog_files)} backlog manifest(s): {[f.name for f in backlog_files]}")

    already_queued = load_queued_paths() if args.write else set()

    n_total = 0
    n_queued = 0
    n_already_queued = 0
    n_missing_file = 0
    n_failed = 0

    for backlog_file in backlog_files:
        with backlog_file.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                n_total += 1
                file_path = Path(row["file_path"])
                locale = row["locale"]

                if not file_path.exists():
                    n_missing_file += 1
                    continue

                resolved = str(file_path.resolve())
                if resolved in already_queued:
                    n_already_queued += 1
                    continue

                if args.write:
                    try:
                        add_to_queue(file_path, locale)
                        n_queued += 1
                        already_queued.add(resolved)
                    except Exception as exc:  # noqa: BLE001
                        n_failed += 1
                        print(f"  FAILED to queue {file_path}: {exc}")
                else:
                    n_queued += 1

    print()
    print(f"Total backlog rows: {n_total}")
    print(f"{'Would queue' if not args.write else 'Queued'}: {n_queued}")
    print(f"Already queued (idempotent skip): {n_already_queued}")
    print(f"Missing file (skipped): {n_missing_file}")
    print(f"Failed: {n_failed}")

    accounted = n_queued + n_already_queued + n_missing_file + n_failed
    if accounted != n_total:
        print(f"WARNING: accounted-for rows ({accounted}) != total rows ({n_total}) -- investigate before treating this run as complete")
        return 1

    return 1 if n_failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
