"""Purge L2 TM entries for one source page x target language(s) (v10.3 G-41).

A review-rejected cell's gate-accepted TM flush is live poison: until
TC-APT-035/062 make TM writes transactional with review, every later rerun or
template-sibling page re-serves the rejected translation. This script deletes
every L2 entry whose (site_id, tgt_lang) matches and whose source_text occurs
verbatim in the given source page — the exact inverse of what the page's
translation flushed, independent of key scoping (it matches on entry VALUES,
so scoped and unscoped keys are both reached; cf. purge_corrupted_tm_entries'
direct-env pattern and its rationale for bypassing L2PersistentTM.delete()).

Dry-run by default; --write applies. Hashes/paths/counts only in output.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

import lmdb  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-file", required=True, help="page source .md path")
    parser.add_argument("--site-id", required=True)
    parser.add_argument(
        "--site-id-contains",
        default=None,
        help="additionally require this substring in the entry's composite site_id "
        "(L2 site_ids embed campaign/config/source scope, e.g. 'campaign=gate5-x')",
    )
    parser.add_argument("--tgt-langs", required=True, help="comma-separated language codes")
    parser.add_argument("--l2-path", default="data/tm/l2.lmdb")
    parser.add_argument("--write", action="store_true", help="apply deletions (default: dry-run)")
    args = parser.parse_args()

    page_text = Path(args.source_file).read_text(encoding="utf-8")
    tgt_langs = {lang.strip() for lang in args.tgt_langs.split(",") if lang.strip()}

    # Open through L2PersistentTM so the env geometry/flags are byte-identical
    # to every live campaign process. A raw lmdb.open in write mode fails with
    # "user-mapped section open" on Windows whenever its map_size differs from
    # a live process's mapping (confirmed 2026-09-05: raw open failed 3x while
    # this path deleted 462 entries alongside running campaigns).
    from src.tm.l2_persistent import L2PersistentTM

    env = L2PersistentTM(db_path=args.l2_path).env
    matched: list[bytes] = []
    scanned = 0
    with env.begin(write=False) as txn:
        for key_bytes, value_bytes in txn.cursor():
            scanned += 1
            try:
                entry = json.loads(value_bytes.decode("utf-8"))
            except Exception:
                continue
            entry_site = str(entry.get("site_id") or "")
            if not entry_site.startswith(args.site_id):
                continue
            if args.site_id_contains and args.site_id_contains not in entry_site:
                continue
            if entry.get("tgt_lang") not in tgt_langs:
                continue
            source_text = (entry.get("source_text") or "").strip()
            if source_text and source_text in page_text:
                matched.append(bytes(key_bytes))

    print(f"scanned={scanned} matched={len(matched)} langs={sorted(tgt_langs)}")
    if not args.write:
        print("dry-run: no deletions applied (pass --write)")
        env.close()
        return 0

    deleted = 0
    with env.begin(write=True) as txn:
        for key_bytes in matched:
            if txn.delete(key_bytes):
                deleted += 1
    env.close()
    print(f"deleted={deleted}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
