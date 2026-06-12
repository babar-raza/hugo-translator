"""
TC-TM-02: Merge sibling l2*.lmdb databases into the canonical l2.lmdb.

Copies all keys from the legacy/sibling database into the canonical l2.lmdb
database without overwriting entries that already exist in the destination.
Idempotent — safe to run multiple times.

Usage (run with both workers stopped):
    python scripts/migrate_l2_lmdb.py --dry-run   # preview only, no writes
    python scripts/migrate_l2_lmdb.py --apply      # apply the merge

After a successful migration, delete the source manually:
    rmdir /s /q data\\tm\\l2_lmdb

The L2PersistentTM startup warning that triggered TC-TM-02 will disappear
once the sibling directory is removed.
"""

import argparse
import sys
from pathlib import Path

try:
    import lmdb
except ImportError:
    print("ERROR: lmdb not installed. Run: pip install lmdb", file=sys.stderr)
    sys.exit(1)


def migrate(src_path: Path, dst_path: Path, dry_run: bool = False) -> None:
    if not src_path.exists():
        print(f"Source does not exist: {src_path}")
        print("Nothing to migrate.")
        return

    if not dst_path.exists():
        print(f"Destination does not exist: {dst_path}")
        print("ERROR: Run workers at least once first to initialise l2.lmdb.")
        sys.exit(1)

    print(f"Source : {src_path}")
    print(f"Dest   : {dst_path}")
    print(f"Dry run: {dry_run}")
    print()

    src_env = lmdb.open(str(src_path), readonly=True, lock=False, max_dbs=1)
    src_stat = src_env.stat()
    print(f"Source entries: {src_stat['entries']}")

    # Open destination with its existing map_size (do not grow the file).
    # On Windows, lmdb.open() extends data.mdb to map_size — so passing a
    # large value here would bloat the file.  Use 0 to inherit the existing
    # map_size from the already-initialised destination database.
    dst_env = lmdb.open(
        str(dst_path),
        map_size=0,  # 0 = keep existing map_size (no file extension)
        max_dbs=1,
        readonly=dry_run,
    )
    dst_stat = dst_env.stat()
    print(f"Dest entries before: {dst_stat['entries']}")

    migrated = 0
    skipped = 0

    with src_env.begin() as src_txn:
        cursor = src_txn.cursor()
        if not dry_run:
            with dst_env.begin(write=True) as dst_txn:
                for key, value in cursor.iternext(keys=True, values=True):
                    if dst_txn.get(key) is None:
                        dst_txn.put(key, value)
                        migrated += 1
                    else:
                        skipped += 1
        else:
            with dst_env.begin() as dst_txn:
                for key, value in cursor.iternext(keys=True, values=True):
                    if dst_txn.get(key) is None:
                        migrated += 1
                    else:
                        skipped += 1

    src_env.close()

    if not dry_run:
        dst_stat_after = dst_env.stat()
        print(f"Dest entries after : {dst_stat_after['entries']}")

    dst_env.close()

    print()
    print(f"Migrated (new keys copied) : {migrated}")
    print(f"Skipped  (already in dest) : {skipped}")
    print(f"Total processed            : {migrated + skipped}")
    print()
    if dry_run:
        print("DRY RUN complete. Re-run without --dry-run to apply.")
    else:
        print("Migration complete.")
        print(f"You can now safely delete: {src_path}")
        print("  Windows: rmdir /s /q data\\tm\\l2_lmdb")
        print("  Git Bash: rm -rf data/tm/l2_lmdb")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--dry-run",
        action="store_true",
        help="Count keys that would be copied without making any writes.",
    )
    mode.add_argument(
        "--apply",
        action="store_true",
        help="Apply the merge (idempotent — same as running without --dry-run).",
    )
    parser.add_argument(
        "--src",
        default="data/tm/l2_lmdb",
        help="Source LMDB directory (default: data/tm/l2_lmdb)",
    )
    parser.add_argument(
        "--dst",
        default="data/tm/l2.lmdb",
        help="Dest LMDB directory (default: data/tm/l2.lmdb)",
    )
    args = parser.parse_args(argv)

    if not args.dry_run and not args.apply:
        parser.error("Specify --dry-run to preview or --apply to execute the merge.")

    repo_root = Path(__file__).parent.parent
    src = (repo_root / args.src).resolve()
    dst = (repo_root / args.dst).resolve()

    migrate(src, dst, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
