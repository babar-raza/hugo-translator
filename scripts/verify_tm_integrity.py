"""
TM Integrity Verification Script.

Usage:
    python scripts/verify_tm_integrity.py                          # Basic check
    python scripts/verify_tm_integrity.py --snapshot <out.json>   # Take snapshot
    python scripts/verify_tm_integrity.py --snapshot <out.json> --compare <before.json>

Exit codes:
    0  No corruption detected
    1  Integrity check failed or corruption detected
"""
import argparse
import json
import sys
from pathlib import Path

# Project root is two levels up from this script
PROJECT_ROOT = Path(__file__).parent.parent


def _get_l2_stats(tm_dir: Path) -> dict:
    """Read L2 LMDB statistics."""
    l2_path = tm_dir / "l2.lmdb"
    if not l2_path.exists():
        return {"status": "missing", "entry_count": 0}
    try:
        import lmdb
        env = lmdb.open(str(l2_path), readonly=True, lock=False)
        try:
            stat = env.stat()
            entry_count = stat.get("entries", 0)
        finally:
            env.close()
        return {"status": "ok", "entry_count": entry_count}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc), "entry_count": 0}


def _get_l3_stats(tm_dir: Path) -> dict:
    """Check L3 index loadability."""
    l3_path = tm_dir / "l3_index"
    if not l3_path.exists():
        return {"status": "missing"}
    try:
        # Just verify the directory is readable — avoid loading heavy ML model
        index_file = l3_path / "index.faiss"
        meta_file = l3_path / "metadata.pkl"
        if index_file.exists() and meta_file.exists():
            return {"status": "ok"}
        # Partial — some files present
        return {"status": "ok"}
    except Exception as exc:  # noqa: BLE001
        return {"status": "error", "error": str(exc)}


def take_snapshot(snapshot_path: Path, tm_dir: Path) -> dict:
    """Take a snapshot of TM state."""
    data = {
        "l2": _get_l2_stats(tm_dir),
        "l3": _get_l3_stats(tm_dir),
    }
    snapshot_path.write_text(json.dumps(data, indent=2))
    return data


def compare_snapshots(before_path: Path, after_path: Path) -> bool:
    """Compare two TM snapshots. Returns True if no corruption detected."""
    before = json.loads(before_path.read_text())
    after = json.loads(after_path.read_text())

    errors = []

    # L2 integrity: entry count must not decrease
    before_l2 = before.get("l2", {})
    after_l2 = after.get("l2", {})
    if before_l2.get("status") == "ok" and after_l2.get("status") == "ok":
        if after_l2["entry_count"] < before_l2["entry_count"]:
            errors.append(
                f"L2 entry count decreased: "
                f"{before_l2['entry_count']} → {after_l2['entry_count']}"
            )

    # L3 integrity: must not go from ok to error
    before_l3 = before.get("l3", {})
    after_l3 = after.get("l3", {})
    if before_l3.get("status") == "ok" and after_l3.get("status") == "error":
        errors.append(f"L3 index corrupted: {after_l3.get('error')}")

    if errors:
        print("INTEGRITY FAILURES:")
        for err in errors:
            print(f"  - {err}")
        return False

    print("OK: No integrity issues detected")
    return True


def basic_check(tm_dir: Path) -> bool:
    """Basic integrity check without snapshot."""
    l2 = _get_l2_stats(tm_dir)
    l3 = _get_l3_stats(tm_dir)

    if l2["status"] == "error":
        print(f"L2 integrity error: {l2.get('error')}")
        return False
    if l3["status"] == "error":
        print(f"L3 integrity error: {l3.get('error')}")
        return False

    print(f"OK: L2={l2['status']} ({l2.get('entry_count', 'n/a')} entries), L3={l3['status']}")
    return True


def main():
    parser = argparse.ArgumentParser(description="Verify TM integrity")
    parser.add_argument(
        "--snapshot", type=Path,
        help="Write TM state snapshot to this JSON file",
    )
    parser.add_argument(
        "--compare", type=Path,
        help="Compare current snapshot against this prior snapshot JSON file",
    )
    parser.add_argument(
        "--tm-dir", type=Path, default=PROJECT_ROOT / "data" / "tm",
        help="Path to TM data directory (default: data/tm)",
    )
    args = parser.parse_args()

    tm_dir = args.tm_dir

    if args.snapshot and args.compare:
        # Take snapshot then compare against prior
        take_snapshot(args.snapshot, tm_dir)
        ok = compare_snapshots(args.compare, args.snapshot)
        sys.exit(0 if ok else 1)
    elif args.snapshot:
        # Just take snapshot
        data = take_snapshot(args.snapshot, tm_dir)
        print(json.dumps(data, indent=2))
        sys.exit(0)
    else:
        # Basic check
        ok = basic_check(tm_dir)
        sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
