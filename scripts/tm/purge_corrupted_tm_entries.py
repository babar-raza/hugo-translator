#!/usr/bin/env python
"""
TC-P7-13: Purge TM entries whose cached translation carries a corruption
this mission fixes in content files, so a future translation run can never
re-serve the corrupted text into an already-fixed file (see plan's TM
remediation section and "Live-System Reassessment" -- this is the
"otherwise all fixes get overwritten on next translation" concern, treated
as a production problem, not an afterthought).

Modeled on scripts/tm/audit_l2_cache_contamination.py's dry-run/--repair
pattern. Two independent layers:

  L3 (FAISS): src/tm/l3_semantic.py's own `remove_entries(predicate)` is
  used as-is -- existing, safe, rebuilds the index from survivors.

  L2 (LMDB): `L2PersistentTM.delete()` only recomputes the *unscoped* key
  (site_id:src_lang:tgt_lang:hash(text)) and can never reach entries
  stored under a scoped key (site_id:field_name:src_lang:tgt_lang:hash).
  Since store()/find_exact() were reworked (this session, per the
  Live-System Reassessment) to prefer scoped keys for new writes, this gap
  is now MORE likely to matter, not less. This script bypasses delete()
  entirely: open the LMDB env directly, iterate the cursor keeping raw key
  bytes, test the predicate against each entry's `.translation`, collect
  matching keys in a read pass, delete by exact key bytes in a write pass.

Scope: only `(site_id, tgt_lang)` pairs that actually appear in
reports/audit/findings_detail.csv for double_period / link_path_corrupted
-- never a full-store scan.

Safety: dry-run by default. `--write` requires the caller to have already
run scripts/tm/backup_tm.py (this script does not do that itself -- see
plan Deliverable 4 TC-P7-13, which sequences backup before this script).
"""
from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

_PROJECT_ROOT = Path(__file__).resolve().parents[2]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

import lmdb  # noqa: E402

DOUBLE_PERIOD = re.compile(r"(?<!\.)\.\.(?!\.)")
_LINK_RE = re.compile(r"(\[(?:[^\[\]]*)\])\(([^)]+)\)")
_COLLAPSED_DOTDOT_RE = re.compile(r"(?<!\.)\./(?!\.)")


def double_period_predicate(translation: str) -> bool:
    """Same signal as Gate 12 / the audit's double_period check: a stray
    '..' outside fenced code blocks."""
    body_no_code = re.sub(r"```.*?```", "", translation, flags=re.S)
    return bool(DOUBLE_PERIOD.search(body_no_code))


def collapsed_link_predicate(translation: str) -> bool:
    """Root-cause-1 signature: a markdown link target containing a bare
    './' where a '../' would be expected -- the confirmed corruption
    pattern (every '../' had one dot eaten). Heuristic, scoped only to
    (site_id, tgt_lang) pairs already known from the audit -- not applied
    store-wide.
    """
    for m in _LINK_RE.finditer(translation):
        target = m.group(2)
        if _COLLAPSED_DOTDOT_RE.search(target):
            return True
    return False


def build_predicate(issue_types: set[str]):
    checks = []
    if "double_period" in issue_types:
        checks.append(double_period_predicate)
    if "link_path_corrupted" in issue_types:
        checks.append(collapsed_link_predicate)
    if not checks:
        raise ValueError(f"No predicate defined for issue_types={issue_types!r}")

    def predicate(translation: str) -> bool:
        return any(check(translation) for check in checks)

    return predicate


def load_scope_pairs(detail_csv: Path, issue_types: set[str]) -> set[tuple[str, str]]:
    """(site_id, tgt_lang/locale) pairs actually flagged for these issue
    types -- the hard scope boundary, never a full-store scan."""
    pairs = set()
    with detail_csv.open(encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r["issue_type"] in issue_types:
                pairs.add((r["site_id"], r["locale"]))
    return pairs


@dataclass
class L2PurgeResult:
    site_id: str
    tgt_lang: str
    scanned: int = 0
    matched_keys: list[bytes] = field(default_factory=list)
    deleted: int = 0


def scan_l2_for_purge(env: "lmdb.Environment", site_id: str, tgt_lang: str, predicate) -> L2PurgeResult:
    """Read-only pass: iterate the cursor keeping raw key bytes, decode
    each entry, test predicate against `.translation`, collect matching
    keys. No writes happen here.
    """
    result = L2PurgeResult(site_id=site_id, tgt_lang=tgt_lang)
    with env.begin() as txn:
        cursor = txn.cursor()
        for key_bytes, value_bytes in cursor.iternext():
            try:
                entry = json.loads(value_bytes.decode("utf-8"))
            except (json.JSONDecodeError, UnicodeDecodeError):
                continue
            if entry.get("site_id") != site_id or entry.get("tgt_lang") != tgt_lang:
                continue
            result.scanned += 1
            translation = entry.get("translation", "")
            if predicate(translation):
                result.matched_keys.append(key_bytes)
    return result


def delete_l2_keys(env: "lmdb.Environment", keys: list[bytes]) -> int:
    """Write pass: delete exact key bytes collected by scan_l2_for_purge.
    LMDB serializes write transactions internally -- safe against a
    concurrent writer at the DB level (the risk this script is designed
    around is the *logical* race of a worker reading a not-yet-purged
    entry, which the mission's worker-stop step eliminates separately)."""
    deleted = 0
    with env.begin(write=True) as txn:
        for key_bytes in keys:
            if txn.delete(key_bytes):
                deleted += 1
    return deleted


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--detail-csv", default="reports/audit/findings_detail.csv")
    ap.add_argument(
        "--l2-path",
        default="data/tm/l2.lmdb",
        help="Canonical L2 LMDB path (must match src/tm/lmdb_registry.APPROVED_LMDB_RELATIVE_PATHS)",
    )
    ap.add_argument("--write", action="store_true", help="Actually delete. Default is dry-run.")
    ap.add_argument(
        "--issue-types",
        nargs="+",
        default=["double_period", "link_path_corrupted"],
        help="Which corruption predicates to scope this purge to",
    )
    args = ap.parse_args()

    issue_types = set(args.issue_types)
    predicate = build_predicate(issue_types)
    scope_pairs = load_scope_pairs(Path(args.detail_csv), issue_types)

    print(f"Scope: {len(scope_pairs)} (site_id, locale) pairs from {args.detail_csv}, issue_types={sorted(issue_types)}")

    l2_path = Path(args.l2_path)
    if not l2_path.exists():
        print(f"L2 path does not exist: {l2_path}")
        return 1

    # map_size must match/exceed what L2PersistentTM itself uses (4096MB
    # default, src/tm/l2_persistent.py) -- lmdb.open()'s own default is far
    # too small for a multi-GB store and a write-mode open (even for
    # deletes: LMDB needs headroom for B-tree rebalancing/copy-on-write
    # during the transaction, not just the net size change). Confirmed by
    # a real MDB_MAP_FULL crash mid-purge with no explicit map_size set.
    env = lmdb.open(str(l2_path), readonly=not args.write, lock=args.write, max_dbs=1, map_size=8192 * 1024 * 1024)

    total_scanned = 0
    total_matched = 0
    total_deleted = 0
    per_pair_results: dict[tuple[str, str], L2PurgeResult] = {}

    for site_id, tgt_lang in sorted(scope_pairs):
        result = scan_l2_for_purge(env, site_id, tgt_lang, predicate)
        per_pair_results[(site_id, tgt_lang)] = result
        total_scanned += result.scanned
        total_matched += len(result.matched_keys)
        if result.matched_keys:
            print(f"  {site_id}:{tgt_lang} -- scanned {result.scanned}, {len(result.matched_keys)} corrupted")

    print()
    print(f"Total scanned: {total_scanned}, total corrupted candidates: {total_matched}")

    if not args.write:
        print("Dry-run only -- no deletions. Re-run with --write after operator sanity-checks these counts")
        print("and scripts/tm/backup_tm.py has completed (see plan TC-P7-13 sequencing).")
        env.close()
        return 0

    for (site_id, tgt_lang), result in per_pair_results.items():
        n_deleted = delete_l2_keys(env, result.matched_keys)
        result.deleted = n_deleted
        total_deleted += n_deleted

    print(f"Deleted: {total_deleted}")
    env.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
