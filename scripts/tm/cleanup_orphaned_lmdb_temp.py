"""Safe cleanup of orphaned pytest LMDB databases from temp directories.

Usage:
    python scripts/cleanup_orphaned_lmdb_temp.py --dry-run
    python scripts/cleanup_orphaned_lmdb_temp.py --apply
    python scripts/cleanup_orphaned_lmdb_temp.py --dry-run --verbose

Exit codes:
    0 — success (dry-run or apply completed)
    1 — apply had failures
    2 — usage error or safety violation
"""

from __future__ import annotations

import argparse
import re
import shutil
import sys
import tempfile
import time
from pathlib import Path

# Patterns that match pytest-owned temp directories
_PYTEST_DIR_PATTERNS = [
    re.compile(r"pytest-of-[^/\\]+[/\\]pytest-\d+[/\\]test_"),
    re.compile(r"tmp[^/\\]*[/\\].*\.lmdb"),
    re.compile(r"pytest-[^/\\]+[/\\].*\.lmdb"),
]


def _is_pytest_owned(path: Path, root: Path) -> bool:
    """Return True if *path* matches a known pytest temp directory pattern."""
    rel = str(path.relative_to(root))
    return any(p.search(rel) for p in _PYTEST_DIR_PATTERNS)


def _is_lmdb_dir(path: Path) -> bool:
    """Return True if *path* contains both data.mdb and lock.mdb."""
    return (path / "data.mdb").exists() and (path / "lock.mdb").exists()


def _dir_age_hours(path: Path) -> float:
    """Return age of directory in hours based on data.mdb mtime."""
    data_mdb = path / "data.mdb"
    if data_mdb.exists():
        return (time.time() - data_mdb.stat().st_mtime) / 3600
    return 0.0


def _dir_size_mb(path: Path) -> float:
    """Return total size of directory contents in MB."""
    total = 0
    for f in path.rglob("*"):
        if f.is_file():
            total += f.stat().st_size
    return total / (1024 * 1024)


def _force_delete(path: Path, retries: int = 3, delay: float = 0.3) -> bool:
    """Delete directory with retry logic for Windows file locks."""
    for attempt in range(retries):
        try:
            shutil.rmtree(path)
            return True
        except PermissionError:
            if attempt < retries - 1:
                time.sleep(delay)
    return False


def find_candidates(
    root: Path,
    max_age_hours: float = 1.0,
    only_name: str | None = None,
) -> list[tuple[Path, float, float]]:
    """Find orphaned LMDB directories under *root*.

    Returns list of (path, size_mb, age_hours) tuples.
    """
    candidates = []
    if not root.exists():
        return candidates

    for data_mdb in root.rglob("data.mdb"):
        lmdb_dir = data_mdb.parent

        if lmdb_dir.is_symlink():
            continue
        if not (lmdb_dir / "lock.mdb").exists():
            continue
        if not _is_pytest_owned(lmdb_dir, root):
            continue

        age = _dir_age_hours(lmdb_dir)
        if age < max_age_hours:
            continue

        if only_name and lmdb_dir.name != only_name:
            continue

        size = _dir_size_mb(lmdb_dir)
        candidates.append((lmdb_dir, size, age))

    return sorted(candidates, key=lambda x: x[0])


def cleanup(
    root: Path,
    dry_run: bool = True,
    max_age_hours: float = 1.0,
    only_name: str | None = None,
    verbose: bool = False,
) -> tuple[int, int]:
    """Clean up orphaned LMDB temp directories.

    Returns (deleted_count, failed_count).
    """
    candidates = find_candidates(root, max_age_hours, only_name)

    if not candidates:
        print("No orphaned LMDB directories found.")
        return 0, 0

    print(f"Found {len(candidates)} candidate(s):\n")

    deleted = 0
    failed = 0

    for path, size_mb, age_hours in candidates:
        print(f"  {path}")
        print(f"    Size: {size_mb:.1f} MB, Age: {age_hours:.1f} hours")

        if dry_run:
            print("    Action: WOULD DELETE (dry-run)")
        else:
            if _force_delete(path):
                print("    Action: DELETED")
                deleted += 1
            else:
                print("    Action: FAILED (PermissionError after retries)")
                failed += 1

    print()
    if dry_run:
        print(f"DRY RUN: {len(candidates)} candidate(s) found, nothing deleted.")
    else:
        print(f"Deleted: {deleted}, Failed: {failed}")

    return deleted, failed


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description=__doc__,
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    mode = parser.add_mutually_exclusive_group(required=False)
    mode.add_argument(
        "--dry-run", action="store_true", help="Preview candidates, delete nothing (default)."
    )
    mode.add_argument(
        "--apply", action="store_true", help="Actually delete orphaned LMDB directories."
    )
    parser.add_argument("--root", default=None, help="Override temp root (default: system temp).")
    parser.add_argument(
        "--allow-custom-root", action="store_true", help="Allow --root outside system temp."
    )
    parser.add_argument(
        "--max-age-hours",
        type=float,
        default=1.0,
        help="Only dirs older than N hours (default: 1).",
    )
    parser.add_argument(
        "--only-name", default=None, help="Restrict to LMDB dirs with this basename."
    )
    parser.add_argument(
        "--verbose", action="store_true", help="Print skipped candidates with reason."
    )

    args = parser.parse_args(argv)

    if not args.dry_run and not args.apply:
        args.dry_run = True

    system_temp = Path(tempfile.gettempdir()).resolve()

    if args.root:
        root = Path(args.root).resolve()
        if not args.allow_custom_root:
            try:
                root.relative_to(system_temp)
            except ValueError:
                print(
                    f"ERROR: --root {root} is outside system temp {system_temp}.", file=sys.stderr
                )
                print("Use --allow-custom-root to override this safety check.", file=sys.stderr)
                return 2
    else:
        root = system_temp

    print(f"Root: {root}")
    print(f"Mode: {'dry-run' if args.dry_run else 'apply'}")
    print(f"Max age: {args.max_age_hours} hours")
    if args.only_name:
        print(f"Only name: {args.only_name}")
    print()

    deleted, failed = cleanup(
        root=root,
        dry_run=args.dry_run,
        max_age_hours=args.max_age_hours,
        only_name=args.only_name,
        verbose=args.verbose,
    )

    if not args.dry_run and failed > 0:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
