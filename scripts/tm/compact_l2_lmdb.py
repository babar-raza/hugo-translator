"""
Compact data/tm/l2.lmdb to reclaim pre-allocated disk space.

LMDB on Windows extends data.mdb to the map_size value when the database is
opened.  If the database was ever opened with a large map_size (e.g. 2 GB),
the file remains at that size even if only 900 MB of data is stored.

This script uses lmdb.copy(compact=True) to produce a new database file
containing only the live data pages, then atomically replaces the original.

REQUIREMENTS:
  - Both workers must be stopped before running.
  - l2_max_size_mb must be set correctly in config/global.yaml first.

Usage:
    python scripts/compact_l2_lmdb.py [--db-path data/tm/l2.lmdb] [--map-size-mb 1536]
"""

import argparse
import os
import shutil
import sys
from pathlib import Path

try:
    import lmdb
except ImportError:
    print("ERROR: lmdb not installed. Run: pip install lmdb", file=sys.stderr)
    sys.exit(1)


def compact(db_path: Path, map_size_mb: int) -> None:
    if not db_path.exists():
        print(f"ERROR: database not found: {db_path}")
        sys.exit(1)

    data_mdb = db_path / "data.mdb"
    original_size = os.path.getsize(data_mdb)

    print(f"Database  : {db_path}")
    print(f"File size : {original_size / 1024 / 1024:.1f} MiB (before)")
    print(f"Target map: {map_size_mb} MiB")
    print()

    # Open source in readonly mode
    src_env = lmdb.open(str(db_path), readonly=True, lock=False, max_dbs=1)
    src_stat = src_env.stat()
    entries = src_stat["entries"]
    print(f"Entries in source: {entries}")

    # Create compacted copy in a sibling temp directory
    tmp_dir = db_path.parent / f"_compact_tmp_{os.getpid()}"
    tmp_dir.mkdir(parents=True, exist_ok=True)
    compact_path = tmp_dir / "l2.lmdb"
    compact_path.mkdir(parents=True, exist_ok=True)  # lmdb.copy() requires dest dir to exist

    try:
        print(f"Writing compacted copy to: {compact_path} ...")
        src_env.copy(str(compact_path), compact=True)
        src_env.close()

        compact_size = os.path.getsize(compact_path / "data.mdb")
        print(f"Compacted size: {compact_size / 1024 / 1024:.1f} MiB")

        # Re-open compacted copy and set the desired map_size
        dst_env = lmdb.open(
            str(compact_path),
            map_size=map_size_mb * 1024 * 1024,
            max_dbs=1,
        )
        dst_stat = dst_env.stat()
        assert dst_stat["entries"] == entries, (
            f"Entry count mismatch after compaction: {dst_stat['entries']} != {entries}"
        )
        dst_env.close()

        after_mapsize = os.path.getsize(compact_path / "data.mdb")
        print(f"After map_size set: {after_mapsize / 1024 / 1024:.1f} MiB")
        print(f"Entries verified: {dst_stat['entries']}")
        print()

        # Backup original
        backup_path = db_path.parent / f"l2.lmdb.bak_{os.getpid()}"
        print(f"Backing up original to: {backup_path}")
        shutil.copytree(str(db_path), str(backup_path))

        # Replace original with compacted copy
        print("Replacing original with compacted copy...")
        shutil.rmtree(str(db_path))
        shutil.move(str(compact_path), str(db_path))

        saved = original_size - after_mapsize
        print()
        print(f"Done. Saved {saved / 1024 / 1024:.1f} MiB.")
        print(f"Backup retained at: {backup_path}")
        print("Delete backup once verified: rm -rf " + str(backup_path))

    except Exception as e:
        print(f"ERROR: {e}")
        src_env.close()
        if tmp_dir.exists():
            shutil.rmtree(str(tmp_dir))
        sys.exit(1)
    finally:
        if tmp_dir.exists():
            shutil.rmtree(str(tmp_dir), ignore_errors=True)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--db-path",
        default="data/tm/l2.lmdb",
        help="Path to LMDB database directory",
    )
    parser.add_argument(
        "--map-size-mb",
        type=int,
        default=1536,
        help="Target map_size in MB (default: 1536)",
    )
    args = parser.parse_args()

    repo_root = Path(__file__).parent.parent
    db_path = (repo_root / args.db_path).resolve()

    compact(db_path, args.map_size_mb)


if __name__ == "__main__":
    main()
