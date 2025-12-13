"""
Inspect L3 Index Metadata Structure

Validates metadata structure, entry_id field presence and format.
Used to verify assumptions before relying on resume capability.
"""
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.tm.l3_semantic import L3SemanticTM


def inspect_metadata(index_path: str = "./data/tm/l3_faiss"):
    """
    Inspect L3 index metadata structure.

    Args:
        index_path: Path to L3 FAISS index directory
    """
    print("=" * 60)
    print("L3 Metadata Structure Inspector")
    print("=" * 60)
    print(f"L3 index: {index_path}")
    print()

    # Load L3 index
    try:
        l3 = L3SemanticTM(
            index_path=index_path,
            embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
            use_gpu=False,  # CPU for inspection
        )
    except Exception as e:
        print(f"❌ Failed to load L3 index: {e}")
        return

    # Basic stats
    print("Basic Statistics:")
    print("-" * 60)
    print(f"Index vectors: {l3.index.ntotal:,}")
    print(f"Metadata entries: {len(l3.metadata):,}")
    print(f"Metadata type: {type(l3.metadata)}")
    print()

    if not l3.metadata:
        print("⚠️ Metadata is empty")
        return

    # Check first entry structure
    print("First Entry Structure:")
    print("-" * 60)
    first_entry = l3.metadata[0]
    print(f"Entry type: {type(first_entry)}")
    if isinstance(first_entry, dict):
        print(f"Fields: {list(first_entry.keys())}")
        for key, value in first_entry.items():
            print(f"  - {key}: {type(value).__name__} = {repr(value)[:80]}")
    else:
        print(f"Unexpected type: {first_entry}")
    print()

    # Validate entry_id presence and format
    print("Entry ID Validation:")
    print("-" * 60)

    total_entries = len(l3.metadata)
    entries_with_id = 0
    entries_without_id = 0
    entries_malformed_id = 0
    entries_wrong_type = 0

    sample_entry_ids = []

    for i, meta in enumerate(l3.metadata):
        # Type check
        if not isinstance(meta, dict):
            entries_wrong_type += 1
            continue

        # entry_id check
        entry_id = meta.get("entry_id")
        if not entry_id:
            entries_without_id += 1
            continue

        # Format check: should be "site_id:src_lang:tgt_lang:hash"
        if not isinstance(entry_id, str) or entry_id.count(":") != 3:
            entries_malformed_id += 1
            continue

        entries_with_id += 1

        # Collect samples
        if len(sample_entry_ids) < 10:
            sample_entry_ids.append(entry_id)

    # Report
    print(f"Total entries: {total_entries:,}")
    print(f"✓ With valid entry_id: {entries_with_id:,} ({entries_with_id/total_entries*100:.1f}%)")

    if entries_without_id > 0:
        print(f"⚠️ Missing entry_id: {entries_without_id:,} ({entries_without_id/total_entries*100:.1f}%)")

    if entries_malformed_id > 0:
        print(f"⚠️ Malformed entry_id: {entries_malformed_id:,} ({entries_malformed_id/total_entries*100:.1f}%)")

    if entries_wrong_type > 0:
        print(f"⚠️ Wrong type (not dict): {entries_wrong_type:,} ({entries_wrong_type/total_entries*100:.1f}%)")

    print()
    print("Sample Entry IDs (first 10):")
    print("-" * 60)
    for entry_id in sample_entry_ids:
        print(f"  {entry_id}")
    print()

    # Conclusion
    print("Conclusions:")
    print("-" * 60)

    if entries_with_id == total_entries:
        print("✓ All metadata entries have valid entry_id field")
        print("✓ Safe to assume entry_id always exists")
        print("✓ Resume capability can rely on metadata structure")
    else:
        print("⚠️ Some metadata entries missing or have invalid entry_id")
        print("⚠️ Resume capability needs validation logic")
        print(f"⚠️ {total_entries - entries_with_id:,} entries would be skipped")

    print()

    # Check for other fields
    print("Other Metadata Fields:")
    print("-" * 60)
    if isinstance(l3.metadata[0], dict):
        for key in l3.metadata[0].keys():
            if key != "entry_id":
                print(f"  - {key}")


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Inspect L3 metadata structure")
    parser.add_argument(
        "--index_path",
        type=str,
        default="./data/tm/l3_faiss",
        help="Path to L3 FAISS index directory",
    )
    args = parser.parse_args()

    inspect_metadata(args.index_path)
