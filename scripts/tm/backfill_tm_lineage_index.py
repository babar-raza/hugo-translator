"""One-time backfill of first-class TM lineage + the by_config_fingerprint index (TC-APT-008, plan 7.5).

Walks every L2 entry; for entries whose ``metadata`` carries lineage (``config_fingerprint`` /
``model`` / ``model_id``) but whose first-class fields are empty, rewrites the entry with the
fields populated and records it in the ``by_config_fingerprint`` sub-database.  Entries with no
lineage anywhere are counted as *lineage-unknown* and left untouched (never assumed clean,
never blindly purged).  ``--dry-run`` reports without writing.

Safe on the live 940K-entry store: batched write transactions, resumable (already-indexed
entries are skipped), and it runs ``scripts/tm/backup_tm.py`` first unless ``--no-backup``.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from src.tm.l2_persistent import LINEAGE_DB_NAME, L2PersistentTM, TranslationEntry
from src.tm.lineage import lineage_of
from src.utils.atomic_write import atomic_write

DEFAULT_L2 = Path("data/tm/l2.lmdb")
DEFAULT_REPORT = Path("data/tm/lineage_backfill_report.json")


def backfill(
    tm: L2PersistentTM, *, dry_run: bool = False, batch: int = 5000, limit: int = 0
) -> dict:
    counts: Counter[str] = Counter()
    fingerprints: Counter[str] = Counter()
    models: Counter[str] = Counter()
    pending: list[tuple[bytes, TranslationEntry]] = []
    t0 = time.perf_counter()

    def flush() -> None:
        if not pending or dry_run:
            pending.clear()
            return
        with tm._lock:
            with tm.env.begin(write=True) as txn:
                for key_bytes, entry in pending:
                    tm.rewrite_entry_lineage(txn, key_bytes, entry)
        pending.clear()

    with tm._lock:
        with tm.env.begin() as txn:
            cursor = txn.cursor()
            items = list(
                cursor.iternext()
            )  # keys+values snapshot (~1 GB store fits; avoids write-during-read)
    for key_bytes, value_bytes in items:
        if key_bytes == LINEAGE_DB_NAME:
            continue  # TC-APT-008: the sub-db name key LMDB keeps in the main database
        counts["entries"] += 1
        if limit and counts["entries"] > limit:
            break
        try:
            raw = json.loads(value_bytes.decode("utf-8"))
            entry = TranslationEntry.from_dict(raw)
        except Exception:
            counts["corrupt"] += 1
            continue
        fp, model = lineage_of(entry)
        if not fp and not model:
            counts["lineage_unknown"] += 1
            continue
        counts["with_lineage"] += 1
        if fp:
            fingerprints[fp] += 1
        if model:
            models[model] += 1
        # Already first-class when the stored fields equal the lineage we derived (an entry
        # whose only lineage is a model id keeps config_fingerprint None -- still complete).
        already = raw.get("config_fingerprint") == fp and raw.get("model_id") == model
        if already:
            counts["already_first_class"] += 1
            continue
        counts["to_rewrite"] += 1
        pending.append((key_bytes, entry))
        if len(pending) >= batch:
            flush()
    flush()
    return {
        "dry_run": dry_run,
        "seconds": round(time.perf_counter() - t0, 1),
        "counts": dict(counts),
        "distinct_fingerprints": len(fingerprints),
        "distinct_models": dict(models),
        "top_fingerprints": fingerprints.most_common(10),
        "index_stats": tm.lineage_index_stats(),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="TC-APT-008 TM lineage index backfill")
    parser.add_argument("--l2", type=Path, default=DEFAULT_L2)
    parser.add_argument("--max-size-mb", type=int, default=4096)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--no-backup", action="store_true")
    parser.add_argument("--limit", type=int, default=0)
    parser.add_argument("--report", type=Path, default=DEFAULT_REPORT)
    args = parser.parse_args(argv)

    if not args.dry_run and not args.no_backup:
        print("backing up L2 before the rewrite ...", flush=True)
        subprocess.run([sys.executable, "scripts/tm/backup_tm.py"], check=True)
    with L2PersistentTM(args.l2, max_size_mb=args.max_size_mb) as tm:
        report = backfill(tm, dry_run=args.dry_run, limit=args.limit)
    report["at"] = datetime.now(timezone.utc).isoformat()
    report["l2"] = str(args.l2)
    atomic_write(path=args.report, content=json.dumps(report, indent=2))
    print(json.dumps(report, indent=2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    sys.exit(main())
