"""
Quick L3 Metadata Validation (No Dependencies)

Directly loads metadata.pkl to validate structure without importing L3SemanticTM.
Can run without conda environment or heavy dependencies.
"""
import pickle
from pathlib import Path


def quick_validate(index_path: str = "./data/tm/l3_faiss"):
    """
    Quick validation of L3 metadata structure.

    Args:
        index_path: Path to L3 FAISS index directory
    """
    print("=" * 60)
    print("L3 Quick Metadata Validator")
    print("=" * 60)
    print(f"L3 index: {index_path}")
    print()

    metadata_file = Path(index_path) / "metadata.pkl"

    if not metadata_file.exists():
        print(f"[ERROR] Metadata file not found: {metadata_file}")
        return

    # Load metadata
    print("Loading metadata.pkl...")
    try:
        with open(metadata_file, "rb") as f:
            metadata = pickle.load(f)
    except Exception as e:
        print(f"[ERROR] Failed to load metadata: {e}")
        return

    # Basic stats
    print("[OK] Metadata loaded successfully")
    print()
    print("Basic Statistics:")
    print("-" * 60)
    print(f"Metadata type: {type(metadata)}")
    print(f"Total entries: {len(metadata):,}")
    print()

    if not metadata:
        print("[WARN] Metadata is empty")
        return

    # Check first entry
    print("First Entry Structure:")
    print("-" * 60)
    first = metadata[0]
    print(f"Entry type: {type(first)}")
    if isinstance(first, dict):
        print(f"Fields: {list(first.keys())}")
        for key, value in first.items():
            val_str = str(value)[:60]
            print(f"  - {key}: {type(value).__name__} = {val_str}")
    print()

    # Validate all entries
    print("Validation Results:")
    print("-" * 60)

    valid_count = 0
    invalid_type = 0
    missing_entry_id = 0
    malformed_entry_id = 0

    sample_ids = []

    for i, meta in enumerate(metadata):
        if not isinstance(meta, dict):
            invalid_type += 1
            continue

        entry_id = meta.get("entry_id")
        if not entry_id:
            missing_entry_id += 1
            continue

        if not isinstance(entry_id, str) or entry_id.count(":") != 3:
            malformed_entry_id += 1
            continue

        valid_count += 1
        if len(sample_ids) < 5:
            sample_ids.append(entry_id)

    total = len(metadata)
    print(f"Total entries: {total:,}")
    print(f"[OK] Valid entries: {valid_count:,} ({valid_count/total*100:.1f}%)")

    if invalid_type > 0:
        print(f"[WARN] Invalid type: {invalid_type:,} ({invalid_type/total*100:.1f}%)")

    if missing_entry_id > 0:
        print(f"[WARN] Missing entry_id: {missing_entry_id:,} ({missing_entry_id/total*100:.1f}%)")

    if malformed_entry_id > 0:
        print(f"[WARN] Malformed entry_id: {malformed_entry_id:,} ({malformed_entry_id/total*100:.1f}%)")

    print()
    print("Sample Entry IDs:")
    print("-" * 60)
    for entry_id in sample_ids:
        print(f"  {entry_id}")
    print()

    # Conclusion
    print("Conclusion:")
    print("-" * 60)
    if valid_count == total:
        print("[SUCCESS] ALL ENTRIES VALID")
        print("[OK] Resume capability can safely rely on metadata structure")
        print("[OK] All entries have proper entry_id field")
    else:
        invalid_total = invalid_type + missing_entry_id + malformed_entry_id
        print(f"[WARN] {invalid_total:,} entries have issues")
        print(f"[WARN] Resume will skip {invalid_total:,} entries")
        print("[WARN] Consider rebuilding index with --force")
    print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Quick L3 metadata validation")
    parser.add_argument(
        "--index_path",
        type=str,
        default="./data/tm/l3_faiss",
        help="Path to L3 FAISS index directory",
    )
    args = parser.parse_args()

    quick_validate(args.index_path)
