#!/usr/bin/env python
"""Verify translation memory integrity."""
import argparse
import json
import sys
from pathlib import Path


def verify_l2_integrity(tm_path: Path) -> dict:
    """Verify L2 LMDB integrity."""
    import lmdb

    db_path = tm_path / "l2_persistent"
    if not db_path.exists():
        return {"status": "skip", "reason": "L2 not initialized"}

    try:
        env = lmdb.open(str(db_path), readonly=True)
        with env.begin() as txn:
            count = txn.stat()['entries']
        env.close()

        return {
            "status": "ok",
            "entry_count": count,
            "db_size_bytes": sum(f.stat().st_size for f in db_path.glob("*"))
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def verify_l3_integrity(tm_path: Path) -> dict:
    """Verify L3 FAISS integrity."""
    import faiss
    import pickle

    index_path = tm_path / "l3_semantic"
    index_file = index_path / "index.faiss"
    metadata_file = index_path / "metadata.pkl"

    if not index_file.exists():
        return {"status": "skip", "reason": "L3 not initialized"}

    try:
        # Load FAISS index
        index = faiss.read_index(str(index_file))

        # Load metadata
        with open(metadata_file, "rb") as f:
            metadata = pickle.load(f)

        # Verify counts match
        index_count = index.ntotal
        metadata_count = len(metadata)

        counts_match = index_count == metadata_count

        return {
            "status": "ok" if counts_match else "mismatch",
            "index_entries": index_count,
            "metadata_entries": metadata_count,
            "counts_match": counts_match,
            "index_size_bytes": index_file.stat().st_size,
        }
    except Exception as e:
        return {"status": "error", "error": str(e)}


def snapshot_tm_state(tm_path: Path) -> dict:
    """Create snapshot of TM state."""
    return {
        "l2": verify_l2_integrity(tm_path),
        "l3": verify_l3_integrity(tm_path),
    }


def compare_snapshots(before: dict, after: dict) -> bool:
    """Compare TM snapshots and report differences."""
    print("=" * 60)
    print("TM INTEGRITY COMPARISON")
    print("=" * 60)
    print()

    all_ok = True

    # L2 comparison
    print("L2 (LMDB):")
    before_l2 = before.get("l2", {})
    after_l2 = after.get("l2", {})

    if before_l2.get("status") == "ok" and after_l2.get("status") == "ok":
        before_count = before_l2.get("entry_count", 0)
        after_count = after_l2.get("entry_count", 0)

        if after_count >= before_count:
            print(f"  ✓ Entry count increased: {before_count} → {after_count}")
        else:
            print(f"  ✗ Entry count DECREASED: {before_count} → {after_count}")
            all_ok = False
    elif after_l2.get("status") == "error":
        print(f"  ✗ L2 integrity check failed: {after_l2.get('error')}")
        all_ok = False
    else:
        print(f"  - Status: {after_l2.get('status')}")

    print()

    # L3 comparison
    print("L3 (FAISS):")
    before_l3 = before.get("l3", {})
    after_l3 = after.get("l3", {})

    if before_l3.get("status") == "ok" and after_l3.get("status") == "ok":
        if after_l3.get("counts_match"):
            print(f"  ✓ Index/metadata counts match: {after_l3.get('index_entries')}")
        else:
            print(f"  ✗ Index/metadata MISMATCH: index={after_l3.get('index_entries')}, "
                  f"metadata={after_l3.get('metadata_entries')}")
            all_ok = False

        before_count = before_l3.get("index_entries", 0)
        after_count = after_l3.get("index_entries", 0)

        if after_count >= before_count:
            print(f"  ✓ Entry count increased: {before_count} → {after_count}")
        else:
            print(f"  ✗ Entry count DECREASED: {before_count} → {after_count}")
            all_ok = False
    elif after_l3.get("status") == "error":
        print(f"  ✗ L3 integrity check failed: {after_l3.get('error')}")
        all_ok = False
    elif after_l3.get("status") == "mismatch":
        print(f"  ✗ L3 index/metadata mismatch detected")
        all_ok = False
    else:
        print(f"  - Status: {after_l3.get('status')}")

    print()
    print("=" * 60)

    if all_ok:
        print("RESULT: TM integrity verified ✓")
        return True
    else:
        print("RESULT: TM integrity issues detected ✗")
        return False


def main():
    parser = argparse.ArgumentParser(description="Verify TM integrity")
    parser.add_argument("--snapshot", help="Save snapshot to file")
    parser.add_argument("--compare", help="Compare with previous snapshot")
    parser.add_argument("--tm-path", default="data/tm", help="TM directory path")
    args = parser.parse_args()

    tm_path = Path(args.tm_path)

    if args.snapshot:
        # Create snapshot
        snapshot = snapshot_tm_state(tm_path)

        snapshot_file = Path(args.snapshot)
        snapshot_file.parent.mkdir(parents=True, exist_ok=True)
        snapshot_file.write_text(json.dumps(snapshot, indent=2))

        print(f"TM snapshot saved to: {snapshot_file}")

        if args.compare:
            # Also compare
            before_file = Path(args.compare)
            if before_file.exists():
                before = json.loads(before_file.read_text())
                after = snapshot

                if compare_snapshots(before, after):
                    return 0
                else:
                    return 1

        return 0
    else:
        # Just verify current state
        snapshot = snapshot_tm_state(tm_path)
        print(json.dumps(snapshot, indent=2))

        # Check for errors
        if snapshot.get("l2", {}).get("status") == "error":
            return 1
        if snapshot.get("l3", {}).get("status") in ["error", "mismatch"]:
            return 1

        return 0


if __name__ == "__main__":
    sys.exit(main())
