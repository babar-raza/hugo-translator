#!/usr/bin/env python3
"""
Production merge: consolidate all legacy LMDB stores into canonical data/tm/l2.lmdb.

Usage:
    python scripts/tm/merge_legacy_lmdb.py --dry-run   # classify only, no writes
    python scripts/tm/merge_legacy_lmdb.py --apply     # actually merge

Design:
    Two-phase per source:
      Phase 1 – read-only scan: classify every source entry against canonical.
                Collect unique entries (key, raw_value) into a list.
      Phase 2 – write: batch-insert unique entries (BATCH_SIZE per txn).
                Handles MapFullError by resizing and retrying.

Safety:
    - Acquires portalocker migration lock before any write.
    - Aborts if any live shard PID is in ResourceGovernor shard_registry.json.
    - Count reconciliation assertion after each source.
    - unexplained_difference must be 0 or the script aborts.
    - Checkpoint: completed sources persisted; safe to resume after crash.
    - Conflict log: every SAME_IDENTITY_DIFFERENT_VALUE entry recorded.
    - canonical wins on conflict (post-surgical-cleanup canonical is authoritative).
"""
import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(ROOT))

import lmdb
import portalocker
import psutil

CANONICAL = ROOT / "data/tm/l2.lmdb"
MIGRATION_LOCK = ROOT / "data/tm/.migration.lock"
CHECKPOINT_FILE = ROOT / "data/tm/.migration_checkpoint.json"
SHARD_REGISTRY = ROOT / ".local/shard_registry.json"

OUTPUT_DIR = ROOT / "reports/agents/lmdb_migration"
CONFLICT_LOG = OUTPUT_DIR / "migration_conflicts.jsonl"
INVALID_LOG = OUTPUT_DIR / "migration_invalid.jsonl"
SUMMARY_FILE = OUTPUT_DIR / "migration_summary.json"

REQUIRED_FIELDS = ("source_text", "translation", "site_id", "src_lang", "tgt_lang")
BATCH_SIZE = 500  # entries per write transaction

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


def check_no_live_shards():
    """Abort if any shard process in ResourceGovernor registry is still alive."""
    if not SHARD_REGISTRY.exists():
        return
    try:
        registry = json.loads(SHARD_REGISTRY.read_text())
    except Exception:
        return
    live = {}
    for pid, info in registry.items():
        if not psutil.pid_exists(int(pid)):
            continue
        try:
            cmdline = " ".join(psutil.Process(int(pid)).cmdline())
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
        # Only count as live if the process is actually a shard
        if "unified_translate.py" in cmdline:
            live[pid] = info
    if live:
        raise RuntimeError(
            f"Live shard PIDs in shard_registry.json: {live}. "
            "Stop all shards before running the migration."
        )


def lmdb_count(env: lmdb.Environment) -> int:
    return env.stat()["entries"]


def load_checkpoint() -> dict:
    if CHECKPOINT_FILE.exists():
        try:
            return json.loads(CHECKPOINT_FILE.read_text())
        except Exception:
            pass
    return {"completed_sources": {}}


def save_checkpoint(checkpoint: dict):
    CHECKPOINT_FILE.write_text(json.dumps(checkpoint, indent=2))


def merge_source(
    src_path: Path,
    canonical_env: lmdb.Environment,
    dry_run: bool,
    conflict_fh,
    invalid_fh,
    checkpoint: dict,
) -> dict:
    """
    Two-phase merge of one source into canonical.

    Phase 1: read-only scan of source against canonical snapshot.
    Phase 2: batch-write unique entries to canonical.
    """
    label = str(src_path.relative_to(ROOT)).replace("\\", "/")

    if not src_path.exists():
        print(f"  SKIP {label}: not found")
        return {"status": "missing", "label": label}

    if label in checkpoint["completed_sources"]:
        prev = checkpoint["completed_sources"][label]
        print(f"  SKIP {label}: already merged ({prev.get('inserted', 0)} inserted previously)")
        return {"status": "already_done", "label": label, **prev}

    src_env = lmdb.open(str(src_path), readonly=True, lock=False, max_dbs=1)
    src_total = lmdb_count(src_env)
    print(f"  Merging {label}  ({src_total:,} entries) ...", flush=True)

    pre_count = lmdb_count(canonical_env)

    # ── Phase 1: classify ──────────────────────────────────────────────────────
    to_insert: list[tuple[bytes, bytes]] = []  # (key_bytes, raw_value_bytes)
    exact_dup = 0
    val_diff = 0
    invalid = 0
    total = 0

    with src_env.begin() as stxn, canonical_env.begin() as ctxn:
        for k_bytes, lv_bytes in stxn.cursor():
            total += 1
            try:
                lentry = json.loads(lv_bytes.decode("utf-8"))
                if not isinstance(lentry, dict) or not all(
                    lentry.get(f) for f in REQUIRED_FIELDS
                ):
                    raise ValueError("missing_fields")
            except Exception as e:
                invalid += 1
                invalid_fh.write(
                    json.dumps({
                        "source": label,
                        "key": k_bytes.decode("utf-8", errors="replace"),
                        "reason": str(e),
                    }) + "\n"
                )
                continue

            cv_bytes = ctxn.get(k_bytes)
            if cv_bytes is None:
                to_insert.append((k_bytes, lv_bytes))
            elif cv_bytes == lv_bytes:
                exact_dup += 1
            else:
                # Canonical wins; log displaced legacy value
                val_diff += 1
                try:
                    centry = json.loads(cv_bytes.decode("utf-8"))
                    conflict_fh.write(
                        json.dumps({
                            "source_db": label,
                            "key": k_bytes.decode("utf-8", errors="replace"),
                            "canonical_translation": centry.get("translation", ""),
                            "displaced_translation": lentry.get("translation", ""),
                            "canonical_timestamp": centry.get("timestamp"),
                            "legacy_timestamp": lentry.get("timestamp"),
                            "site_id": lentry.get("site_id", ""),
                            "tgt_lang": lentry.get("tgt_lang", ""),
                        }) + "\n"
                    )
                except Exception:
                    pass

    src_env.close()

    # Integrity check
    classified = exact_dup + val_diff + len(to_insert) + invalid
    assert classified == total, (
        f"Classification mismatch for {label}: {total} != {classified}"
    )

    inserted = len(to_insert)

    # ── Phase 2: write ─────────────────────────────────────────────────────────
    if not dry_run and to_insert:
        _batch_write(canonical_env, to_insert)

    if not dry_run:
        post_count = lmdb_count(canonical_env)
        expected_post = pre_count + inserted
        if post_count != expected_post:
            raise RuntimeError(
                f"Count reconciliation FAILED for {label}: "
                f"pre={pre_count} + inserted={inserted} = {expected_post} "
                f"but canonical now has {post_count}. Aborting."
            )

    stats = {
        "status": "ok",
        "label": label,
        "total": total,
        "exact_dup": exact_dup,
        "val_diff": val_diff,
        "inserted": inserted,
        "invalid": invalid,
        "canonical_count_after": lmdb_count(canonical_env),
    }
    print(
        f"    total={total:,}  exact_dup={exact_dup:,}  "
        f"val_diff={val_diff:,}  inserted={inserted:,}  "
        f"invalid={invalid:,}"
    )
    return stats


def _batch_write(
    canonical_env: lmdb.Environment,
    pairs: list[tuple[bytes, bytes]],
):
    """Write pairs to canonical in batches of BATCH_SIZE. Handles MapFullError."""
    for batch_start in range(0, len(pairs), BATCH_SIZE):
        batch = pairs[batch_start: batch_start + BATCH_SIZE]
        for attempt in range(3):
            try:
                with canonical_env.begin(write=True) as wtxn:
                    for k, v in batch:
                        wtxn.put(k, v)
                break  # committed
            except lmdb.MapFullError:
                if attempt == 2:
                    raise
                info = canonical_env.info()
                current_mb = info["map_size"] // (1024 * 1024)
                new_mb = min(int(current_mb * 1.5), 8192)
                print(
                    f"    MapFullError: resizing {current_mb} MB → {new_mb} MB ...",
                    flush=True,
                )
                canonical_env.set_mapsize(new_mb * 1024 * 1024)
                time.sleep(0.5)


def run(dry_run: bool):
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    check_no_live_shards()
    print("Pre-flight: no live shards.")

    if not CANONICAL.exists():
        print(f"ERROR: canonical database not found: {CANONICAL}")
        sys.exit(1)

    # Open canonical: readonly in dry-run, read-write in apply
    canonical_env = lmdb.open(
        str(CANONICAL),
        map_size=0,        # keep existing map_size
        max_dbs=1,
        sync=True,
        writemap=False,
        readonly=dry_run,
    )
    canonical_count_before = lmdb_count(canonical_env)
    print(f"Canonical entries before: {canonical_count_before:,}")
    if dry_run:
        print("DRY RUN — no writes.")
    print()

    checkpoint = load_checkpoint()
    all_stats = {}
    total_inserted = 0
    total_conflicts = 0
    total_invalid = 0

    with (
        open(CONFLICT_LOG, "a", encoding="utf-8") as conflict_fh,
        open(INVALID_LOG, "a", encoding="utf-8") as invalid_fh,
    ):
        for src_path in SOURCES:
            label = str(src_path.relative_to(ROOT)).replace("\\", "/")
            stats = merge_source(
                src_path,
                canonical_env,
                dry_run=dry_run,
                conflict_fh=conflict_fh,
                invalid_fh=invalid_fh,
                checkpoint=checkpoint,
            )
            all_stats[label] = stats

            if stats.get("status") in ("ok", "already_done"):
                total_inserted += stats.get("inserted", 0)
                total_conflicts += stats.get("val_diff", 0)
                total_invalid += stats.get("invalid", 0)

            if not dry_run and stats.get("status") == "ok":
                checkpoint["completed_sources"][label] = {
                    "inserted": stats["inserted"],
                    "canonical_count_after": stats.get("canonical_count_after", 0),
                }
                save_checkpoint(checkpoint)

    canonical_count_after = lmdb_count(canonical_env)
    canonical_env.close()

    expected_after = canonical_count_before + total_inserted
    unexplained = abs(canonical_count_after - expected_after)

    summary = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "dry_run": dry_run,
        "canonical_entries_before": canonical_count_before,
        "canonical_entries_after": canonical_count_after,
        "total_inserted": total_inserted,
        "total_conflicts": total_conflicts,
        "total_invalid": total_invalid,
        "expected_after": expected_after,
        "unexplained_difference": unexplained,
        "per_source": all_stats,
    }
    SUMMARY_FILE.write_text(json.dumps(summary, indent=2, ensure_ascii=False))

    print()
    print("=" * 60)
    print(f"Canonical before : {canonical_count_before:,}")
    print(f"Inserted         : {total_inserted:,}")
    print(f"Conflicts (logged, canonical kept) : {total_conflicts:,}")
    print(f"Invalid (skipped): {total_invalid:,}")
    print(f"Canonical after  : {canonical_count_after:,}")
    print(f"Expected after   : {expected_after:,}")
    print(f"Unexplained diff : {unexplained}")
    print(f"Summary: {SUMMARY_FILE}")

    if unexplained != 0:
        print()
        print(f"ABORT: unexplained_difference={unexplained} != 0.")
        print("Database state may be inconsistent. Restore from backup if needed.")
        sys.exit(3)

    if not dry_run:
        CHECKPOINT_FILE.unlink(missing_ok=True)
        print("Merge complete. unexplained_difference=0.")
    else:
        print("Dry run complete. Run with --apply to perform the merge.")


def main():
    parser = argparse.ArgumentParser(
        description="Merge legacy LMDB stores into canonical l2.lmdb"
    )
    mode = parser.add_mutually_exclusive_group(required=True)
    mode.add_argument("--dry-run", action="store_true", help="Classify only, no writes")
    mode.add_argument("--apply", action="store_true", help="Perform the merge")
    args = parser.parse_args()

    MIGRATION_LOCK.parent.mkdir(parents=True, exist_ok=True)
    try:
        with portalocker.Lock(str(MIGRATION_LOCK), timeout=15, mode="a+"):
            run(dry_run=args.dry_run)
    except portalocker.LockException:
        print("ERROR: Cannot acquire migration lock. Another migration may be running.")
        sys.exit(1)


if __name__ == "__main__":
    main()
