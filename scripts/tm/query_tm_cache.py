#!/usr/bin/env python3
"""TM cache query and inspection tool."""
import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parents[2]
sys.path.insert(0, str(ROOT))

from src.tm.l2_persistent import L2PersistentTM


def main():
    p = argparse.ArgumentParser(description="Query and inspect L2 TM cache")
    p.add_argument("--search", help="Search source text substring")
    p.add_argument("--lang", help="Filter by target language")
    p.add_argument("--site", help="Filter by site_id")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--stats", action="store_true", help="Show stats breakdown by tgt_lang")
    p.add_argument("--by-site", action="store_true", help="Show stats breakdown by site_id")
    p.add_argument("--by-lang", action="store_true", help="Show stats breakdown by tgt_lang")
    p.add_argument("--export", help="Export matching entries to JSONL file path")
    args = p.parse_args()

    db_path = ROOT / "data/tm/l2.lmdb"
    l2 = L2PersistentTM(db_path=db_path)

    if args.stats or args.by_site or args.by_lang:
        dim = "site_id" if args.by_site else "tgt_lang"
        counts = l2.stats_by_dimension(dim)
        print(f"L2 TM stats by {dim}:")
        for k, v in sorted(counts.items(), key=lambda x: -x[1]):
            print(f"  {k}: {v:,}")
        total = sum(counts.values())
        print(f"  TOTAL: {total:,}")
        return

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    count = 0
    for entry in l2.export_iter(site_id=args.site, tgt_lang=args.lang):
        if args.search and args.search.lower() not in entry.source_text.lower():
            continue
        print(f"[{entry.site_id}|{entry.tgt_lang}] {entry.source_text[:60]!r}")
        print(f"  → {entry.translation[:80]!r}")
        count += 1
        if count >= args.limit:
            break

    if not args.export:
        print(f"\n{count} entries shown (--limit {args.limit})")
        return

    with open(args.export, "w", encoding="utf-8") as f:
        exported = 0
        for entry in l2.export_iter(site_id=args.site, tgt_lang=args.lang):
            if args.search and args.search.lower() not in entry.source_text.lower():
                continue
            f.write(json.dumps(entry.to_dict(), ensure_ascii=False) + "\n")
            exported += 1
    print(f"Exported {exported:,} entries to {args.export}")


if __name__ == "__main__":
    main()
