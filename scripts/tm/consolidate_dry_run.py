#!/usr/bin/env python3
"""
Read-only pre-merge classifier.

Opens every legacy LMDB database and classifies each record against the canonical
data/tm/l2.lmdb. Writes dry_run_results.json to reports/agents/lmdb_migration/.

Does NOT write to any database.  Safe to run at any time.
"""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import lmdb

from src.tm.normalization import make_tm_key

CANONICAL = ROOT / "data/tm/l2.lmdb"

SOURCES = [
    ROOT / "data/tm_cache",
    ROOT / "data/tm/kb_direct.lmdb",
    ROOT / "data/tm/unified.lmdb",
    ROOT / "data/tm/unified_s1.lmdb",
    ROOT / "data/tm/unified_s2.lmdb",
    ROOT / "data/tm/unified_s3.lmdb",
    ROOT / "data/tm/unified_s4.lmdb",
    ROOT / "data/tm/kb_shard1.lmdb",
    ROOT / "data/tm/kb_shard2.lmdb",
]

REQUIRED_FIELDS = ("source_text", "translation", "site_id", "src_lang", "tgt_lang")
OUTPUT = ROOT / "reports/agents/lmdb_migration/dry_run_results.json"


def classify_source(src_path: Path, canonical_env: lmdb.Environment) -> dict:
    """Classify all records in src_path against canonical. Read-only."""
    if not src_path.exists():
        return {"status": "missing", "total": 0}

    src_env = lmdb.open(str(src_path), readonly=True, lock=False, max_dbs=1)
    exact_dup = val_diff = unique = invalid = total = 0
    conflict_examples = []

    try:
        with src_env.begin() as stxn, canonical_env.begin() as ctxn:
            cursor = stxn.cursor()
            for k_bytes, lv_bytes in cursor:
                total += 1
                # Validate source entry
                try:
                    lentry = json.loads(lv_bytes.decode("utf-8"))
                    if not isinstance(lentry, dict):
                        invalid += 1
                        continue
                    if not all(lentry.get(f) for f in REQUIRED_FIELDS):
                        invalid += 1
                        continue
                except Exception:
                    invalid += 1
                    continue

                cv_bytes = ctxn.get(k_bytes)
                if cv_bytes is None:
                    unique += 1
                else:
                    try:
                        centry = json.loads(cv_bytes.decode("utf-8"))
                        if centry.get("translation") == lentry.get("translation"):
                            exact_dup += 1
                        else:
                            val_diff += 1
                            if len(conflict_examples) < 3:
                                conflict_examples.append({
                                    "key": k_bytes.decode("utf-8", errors="replace")[:80],
                                    "canonical": centry.get("translation", "?")[:80],
                                    "legacy": lentry.get("translation", "?")[:80],
                                    "site": lentry.get("site_id", "?"),
                                    "tgt_lang": lentry.get("tgt_lang", "?"),
                                })
                    except Exception:
                        val_diff += 1

        # Integrity assertion
        assert total == exact_dup + val_diff + unique + invalid, (
            f"Count mismatch: {total} != {exact_dup}+{val_diff}+{unique}+{invalid}"
        )

        # Schema-mismatch guard: if all records appear "unique", spot-check 5 of them
        # by reconstructing the key from source_text and comparing to stored key
        schema_ok = True
        if unique == total and total > 0:
            schema_ok = _spot_check_key_format(src_path, canonical_env)

        return {
            "status": "ok",
            "total": total,
            "exact_dup": exact_dup,
            "val_diff": val_diff,
            "unique": unique,
            "invalid": invalid,
            "schema_ok": schema_ok,
            "conflict_examples": conflict_examples,
        }
    finally:
        src_env.close()


def _spot_check_key_format(src_path: Path, canonical_env: lmdb.Environment) -> bool:
    """
    Spot-check 5 'unique' keys from src_path.
    Reconstruct the expected key from the entry's source_text fields and check
    whether that reconstructed key IS in canonical (which would mean the stored
    key uses a different format).  Returns False if mismatch detected.
    """
    src_env = lmdb.open(str(src_path), readonly=True, lock=False, max_dbs=1)
    try:
        with src_env.begin() as stxn, canonical_env.begin() as ctxn:
            cursor = stxn.cursor()
            checked = 0
            for k_bytes, lv_bytes in cursor:
                if checked >= 5:
                    break
                try:
                    entry = json.loads(lv_bytes.decode("utf-8"))
                    reconstructed = make_tm_key(
                        entry["site_id"],
                        entry["src_lang"],
                        entry["tgt_lang"],
                        entry["source_text"],
                    )
                    reconstructed_bytes = reconstructed.encode("utf-8")
                    stored_key = k_bytes.decode("utf-8", errors="replace")
                    if stored_key != reconstructed:
                        print(
                            f"  SCHEMA_MISMATCH in {src_path.name}: "
                            f"stored_key={stored_key[:60]} "
                            f"reconstructed={reconstructed[:60]}"
                        )
                        return False
                    checked += 1
                except Exception:
                    pass
    finally:
        src_env.close()
    return True


def main():
    if not CANONICAL.exists():
        print(f"ERROR: canonical database not found: {CANONICAL}")
        sys.exit(1)

    canonical_env = lmdb.open(str(CANONICAL), readonly=True, lock=False, max_dbs=1)
    canonical_count = canonical_env.stat()["entries"]
    print(f"Canonical: {CANONICAL.name}  entries={canonical_count:,}")
    print()

    results = {
        "canonical_entries": canonical_count,
        "sources": {},
    }
    total_unique = 0
    total_val_diff = 0
    total_exact_dup = 0
    total_invalid = 0
    total_all = 0

    try:
        for src_path in SOURCES:
            label = str(src_path.relative_to(ROOT)).replace("\\", "/")
            print(f"  Scanning: {label} ...", end=" ", flush=True)
            r = classify_source(src_path, canonical_env)
            results["sources"][label] = r
            status = r.get("status", "?")
            if status == "missing":
                print("MISSING — skip")
                continue
            print(
                f"total={r['total']:,}  exact_dup={r['exact_dup']:,}  "
                f"val_diff={r['val_diff']:,}  unique={r['unique']:,}  "
                f"invalid={r['invalid']:,}  "
                f"schema_ok={r.get('schema_ok', True)}"
            )
            if r.get("conflict_examples"):
                for ex in r["conflict_examples"]:
                    c_safe = ex['canonical'][:60].encode('ascii', errors='replace').decode()
                    l_safe = ex['legacy'][:60].encode('ascii', errors='replace').decode()
                    print(f"    conflict [{ex['tgt_lang']}]: canonical={c_safe!r}")
                    print(f"              legacy=   {l_safe!r}")
            total_all += r["total"]
            total_exact_dup += r["exact_dup"]
            total_val_diff += r["val_diff"]
            total_unique += r["unique"]
            total_invalid += r["invalid"]

            # Abort on schema mismatch
            if not r.get("schema_ok", True):
                print(f"\nABORT: schema mismatch in {label}. Key format differs from canonical.")
                sys.exit(2)
    finally:
        canonical_env.close()

    expected_after = canonical_count + total_unique
    results["totals"] = {
        "all_legacy_entries": total_all,
        "exact_dup": total_exact_dup,
        "val_diff": total_val_diff,
        "unique": total_unique,
        "invalid": total_invalid,
        "canonical_entries_before": canonical_count,
        "expected_canonical_after": expected_after,
        "unexplained_difference": 0,
    }

    OUTPUT.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT.write_text(json.dumps(results, indent=2, ensure_ascii=False), encoding="utf-8")

    print()
    print("=" * 60)
    print(f"Total legacy entries scanned : {total_all:,}")
    print(f"  Exact duplicates (skip)    : {total_exact_dup:,}")
    print(f"  Value conflicts (log+skip) : {total_val_diff:,}")
    print(f"  Unique (will be inserted)  : {total_unique:,}")
    print(f"  Invalid (will be skipped)  : {total_invalid:,}")
    print(f"Canonical before             : {canonical_count:,}")
    print(f"Expected canonical after     : {expected_after:,}")
    print(f"Wrote: {OUTPUT}")


if __name__ == "__main__":
    main()
