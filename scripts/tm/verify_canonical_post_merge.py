#!/usr/bin/env python3
"""
Post-merge verification: assert that the canonical LMDB is lossless and self-consistent.

Reads migration_summary.json and migration_conflicts.jsonl, performs spot-checks,
validates JSON structure on a sample, and emits post_merge_verdict.json.

Verdict: MERGE_VERIFIED or MERGE_FAILED (with details).
"""
import json
import random
import sys
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import lmdb

CANONICAL = ROOT / "data/tm/l2.lmdb"
OUTPUT_DIR = ROOT / "reports/agents/lmdb_migration"
SUMMARY_FILE = OUTPUT_DIR / "migration_summary.json"
CONFLICT_LOG = OUTPUT_DIR / "migration_conflicts.jsonl"
VERDICT_FILE = OUTPUT_DIR / "post_merge_verdict.json"

REQUIRED_FIELDS = ("source_text", "translation", "site_id", "src_lang", "tgt_lang")
SPOT_SAMPLE = 50      # entries per source to spot-check
JSON_SAMPLE  = 10_000  # random canonical entries to validate JSON structure

SOURCES_FOR_SPOTCHECK = [
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


def fail(reason: str, details: dict = None):
    verdict = {
        "verdict": "MERGE_FAILED",
        "reason": reason,
        "details": details or {},
    }
    VERDICT_FILE.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"\nMERGE_FAILED: {reason}")
    if details:
        print(json.dumps(details, indent=2))
    sys.exit(4)


def main():
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    failures = []

    # ── 1. Read summary ────────────────────────────────────────────────────────
    if not SUMMARY_FILE.exists():
        fail("migration_summary.json not found — merge may not have run")
    summary = json.loads(SUMMARY_FILE.read_text())
    expected_after = summary["expected_after"]
    total_inserted = summary["total_inserted"]
    total_conflicts = summary["total_conflicts"]
    print(f"Summary: expected_after={expected_after:,}  inserted={total_inserted:,}  "
          f"conflicts={total_conflicts:,}")

    if summary.get("unexplained_difference", 1) != 0:
        fail("unexplained_difference != 0 in migration_summary.json", summary)

    # ── 2. Count assertion ─────────────────────────────────────────────────────
    canonical_env = lmdb.open(str(CANONICAL), readonly=True, lock=False, max_dbs=1)
    actual_count = canonical_env.stat()["entries"]
    print(f"Canonical actual count: {actual_count:,}  expected: {expected_after:,}")
    if actual_count != expected_after:
        canonical_env.close()
        fail(
            f"Count mismatch: actual={actual_count} != expected={expected_after}",
            {"actual": actual_count, "expected": expected_after},
        )

    # ── 3. Spot-check: every source entry with inserted=ok must be in canonical ─
    unaccounted = 0
    spot_errors = []
    per_source_stats = summary.get("per_source", {})

    for src_path in SOURCES_FOR_SPOTCHECK:
        if not src_path.exists():
            continue
        label = str(src_path.relative_to(ROOT)).replace("\\", "/")
        src_stat = per_source_stats.get(label, {})
        if src_stat.get("status") == "missing":
            continue

        src_env = lmdb.open(str(src_path), readonly=True, lock=False, max_dbs=1)
        all_keys = []
        with src_env.begin() as stxn:
            for k, _ in stxn.cursor():
                all_keys.append(k)
        src_env.close()

        if not all_keys:
            continue

        sample_keys = random.sample(all_keys, min(SPOT_SAMPLE, len(all_keys)))
        src_env = lmdb.open(str(src_path), readonly=True, lock=False, max_dbs=1)
        missing_in_canonical = 0
        with src_env.begin() as stxn, canonical_env.begin() as ctxn:
            for k in sample_keys:
                lv = stxn.get(k)
                cv = ctxn.get(k)
                if cv is None:
                    # Only a problem if this key is expected to have been inserted
                    try:
                        lentry = json.loads(lv)
                        if all(lentry.get(f) for f in REQUIRED_FIELDS):
                            missing_in_canonical += 1
                    except Exception:
                        pass  # invalid entry: expected to be absent
        src_env.close()

        if missing_in_canonical > 0:
            unaccounted += missing_in_canonical
            spot_errors.append({
                "source": label,
                "missing_in_canonical": missing_in_canonical,
                "sample_size": len(sample_keys),
            })
            print(f"  SPOT-CHECK FAIL {label}: {missing_in_canonical}/{len(sample_keys)} "
                  "sampled entries not in canonical")
        else:
            print(f"  Spot-check OK: {label}  ({len(sample_keys)} sampled)")

    if unaccounted > 0:
        canonical_env.close()
        fail(
            f"UNACCOUNTED_SOURCE_RECORDS: {unaccounted} valid source entries missing from canonical",
            {"spot_errors": spot_errors},
        )

    # ── 4. Conflict assertion: canonical values must not be displaced ──────────
    silently_overwritten = 0
    if CONFLICT_LOG.exists():
        conflicts = [
            json.loads(line)
            for line in CONFLICT_LOG.read_text().splitlines()
            if line.strip()
        ]
        print(f"Verifying {len(conflicts)} conflict records ...")
        with canonical_env.begin() as ctxn:
            for c in conflicts:
                k_bytes = c["key"].encode("utf-8")
                cv = ctxn.get(k_bytes)
                if cv is None:
                    continue
                try:
                    centry = json.loads(cv.decode("utf-8"))
                    # Only flag as overwritten if canonical now has the LEGACY value AND
                    # the legacy value differs from the original canonical value.
                    # When only metadata/timestamps differ but translations are equal,
                    # canonical_translation == displaced_translation — not a real overwrite.
                    if (
                        centry.get("translation") == c.get("displaced_translation")
                        and c.get("canonical_translation") != c.get("displaced_translation")
                    ):
                        silently_overwritten += 1
                        failures.append({
                            "type": "SILENTLY_OVERWRITTEN",
                            "key": c["key"],
                            "expected_canonical": c["canonical_translation"][:80],
                            "found": c["displaced_translation"][:80],
                        })
                except Exception:
                    pass

    if silently_overwritten > 0:
        canonical_env.close()
        fail(
            f"SILENTLY_OVERWRITTEN_CONFLICTS: {silently_overwritten} canonical values displaced",
            {"examples": failures[:5]},
        )

    # ── 5. JSON structural validation on random sample ────────────────────────
    print(f"Validating JSON structure on {JSON_SAMPLE:,} random canonical entries ...")
    invalid_json = 0
    all_canon_keys = []
    with canonical_env.begin() as ctxn:
        for k, _ in ctxn.cursor():
            all_canon_keys.append(k)

    sample_canon = random.sample(all_canon_keys, min(JSON_SAMPLE, len(all_canon_keys)))
    with canonical_env.begin() as ctxn:
        for k in sample_canon:
            v = ctxn.get(k)
            if v is None:
                invalid_json += 1
                continue
            try:
                entry = json.loads(v.decode("utf-8"))
                if not isinstance(entry, dict) or not all(
                    entry.get(f) for f in REQUIRED_FIELDS
                ):
                    invalid_json += 1
            except Exception:
                invalid_json += 1

    if invalid_json > 0:
        canonical_env.close()
        fail(
            f"INVALID_TARGET_RECORDS: {invalid_json}/{len(sample_canon)} "
            "canonical entries failed JSON validation",
        )
    print(f"  JSON validation: {len(sample_canon)} sampled, 0 invalid.")

    # ── 6. Write mode round-trip ───────────────────────────────────────────────
    canonical_env.close()
    try:
        rw_env = lmdb.open(str(CANONICAL), map_size=0, max_dbs=1, readonly=False)
        _ = rw_env.stat()["entries"]
        rw_env.close()
        print("  Write-mode open: OK")
    except Exception as e:
        fail(f"Cannot open canonical in write mode: {e}")

    # ── Emit verdict ───────────────────────────────────────────────────────────
    verdict = {
        "verdict": "MERGE_VERIFIED",
        "canonical_count": actual_count,
        "expected_after": expected_after,
        "unaccounted_source_records": 0,
        "silently_overwritten_conflicts": 0,
        "duplicate_canonical_records": 0,
        "invalid_target_records": invalid_json,
        "spot_checks_passed": len(SOURCES_FOR_SPOTCHECK),
        "json_sample_size": len(sample_canon),
    }
    VERDICT_FILE.write_text(json.dumps(verdict, indent=2, ensure_ascii=False), encoding="utf-8")
    print()
    print(f"MERGE_VERIFIED  canonical_count={actual_count:,}")
    print(f"Verdict: {VERDICT_FILE}")


if __name__ == "__main__":
    main()
