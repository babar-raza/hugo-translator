"""
One-time migration: merge data/tm/l2_lmdb → data/tm/l2.lmdb

Copies all keys from the legacy l2_lmdb database into the canonical l2.lmdb
database without overwriting entries that already exist in the destination.

Usage (run with both workers stopped):
    python scripts/migrate_l2_lmdb.py [--dry-run]

After a successful migration, delete the source manually:
    rmdir /s /q data\\tm\\l2_lmdb
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

    dst_env = lmdb.open(
        str(dst_path),
        map_size=src_stat["psize"] * src_stat["branch_pages"]
        + 2 * 1024 * 1024 * 1024,  # 2 GB safety headroom
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


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="Count without writing")
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
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    src = (repo_root / args.src).resolve()
    dst = (repo_root / args.dst).resolve()

    migrate(src, dst, dry_run=args.dry_run)


if __name__ == "__main__":
    main()
