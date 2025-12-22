"""
Clear Translation Memory cache to force retranslation.

Usage:
    python scripts/clear_tm.py                    # Clear all TM layers
    python scripts/clear_tm.py --l1-only          # Clear only L1 (in-memory cache)
    python scripts/clear_tm.py --l2-only          # Clear only L2 (persistent LMDB)
    python scripts/clear_tm.py --l3-only          # Clear only L3 (semantic index)
"""
import argparse
import shutil
import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.utils.config_loader import ConfigService


def clear_tm(l1_only=False, l2_only=False, l3_only=False):
    """Clear TM layers."""
    print("=" * 60)
    print("Translation Memory Cache Clear Utility")
    print("=" * 60)
    print()

    # Load config
    config = ConfigService(project_root / "config")
    global_config = config.global_config
    tm_data_dir = Path(global_config.tm_data_dir)
    tm_data_dir.mkdir(parents=True, exist_ok=True)

    # Determine which layers to clear
    clear_l1 = l1_only or (not l2_only and not l3_only)
    clear_l2 = l2_only or (not l1_only and not l3_only)
    clear_l3 = l3_only or (not l1_only and not l2_only)

    # Clear L1
    if clear_l1:
        print("Clearing L1 Cache (in-memory)...")
        l1 = L1Cache(max_size=10000)
        l1.clear()
        print("  ✓ L1 cleared")
        print()

    # Clear L2
    if clear_l2:
        print("Clearing L2 Persistent (LMDB)...")
        l2_path = tm_data_dir / "l2_lmdb"
        l2_path.mkdir(parents=True, exist_ok=True)
        l2 = L2PersistentTM(db_path=str(l2_path))
        try:
            l2.clear()
            print(f"  ✓ L2 cleared: {l2_path}")
        finally:
            l2.close()
        print()

    # Clear L3
    if clear_l3:
        print("Clearing L3 Semantic (FAISS index)...")
        if not global_config.default_tm_prefs.use_semantic_tm:
            print("  ? L3 semantic TM is disabled in config")
            print()
        else:
            try:
                l3_path = tm_data_dir / "l3_faiss"
                if l3_path.exists():
                    shutil.rmtree(l3_path)
                l3_path.mkdir(parents=True, exist_ok=True)
                print(f"  ? L3 cleared: {l3_path}")
            except Exception as e:
                print(f"  ?- Failed to clear L3: {e}")
            print()

    print("=" * 60)
    print("TM Cache Cleared Successfully")
    print("=" * 60)
    print()
    print("Next translation will:")
    if clear_l1 and clear_l2 and clear_l3:
        print("  - Retranslate ALL segments (no TM cache available)")
    else:
        if clear_l1:
            print("  - Rebuild L1 cache from L2/L3")
        if clear_l2:
            print("  - Bypass L2 exact matches")
        if clear_l3:
            print("  - Bypass L3 semantic matches")
    print()


def main():
    parser = argparse.ArgumentParser(description="Clear TM cache for force retranslation")
    parser.add_argument("--l1-only", action="store_true", help="Clear only L1 cache")
    parser.add_argument("--l2-only", action="store_true", help="Clear only L2 persistent")
    parser.add_argument("--l3-only", action="store_true", help="Clear only L3 semantic")

    args = parser.parse_args()

    # Confirm destructive operation
    layers = []
    if args.l1_only:
        layers.append("L1")
    if args.l2_only:
        layers.append("L2")
    if args.l3_only:
        layers.append("L3")
    if not layers:
        layers = ["L1", "L2", "L3"]

    print()
    print("⚠ WARNING: This will clear the following TM layers:")
    for layer in layers:
        print(f"  - {layer}")
    print()
    response = input("Continue? [y/N]: ")

    if response.lower() != "y":
        print("Aborted.")
        return

    clear_tm(
        l1_only=args.l1_only,
        l2_only=args.l2_only,
        l3_only=args.l3_only,
    )


if __name__ == "__main__":
    main()
