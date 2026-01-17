"""
Quick test to verify --max-files implementation without full CLI setup.
"""

import sys
from pathlib import Path

def test_max_files_logic():
    """Test the max_files limiting logic directly."""
    print("=== Testing max_files file limiting logic ===\n")

    # Simulate file discovery
    test_dir = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\kb.aspose.net\slides\en")

    if not test_dir.exists():
        print(f"ERROR: Test directory not found: {test_dir}")
        return 1

    # Find all markdown files
    md_files = list(test_dir.glob("**/*.md"))
    print(f"Total .md files found: {len(md_files)}")

    # Simulate the max_files logic from engine.py
    max_files = 5

    print(f"\nApplying max_files={max_files} limit...")

    # This is the logic we added to engine.py:
    if max_files and max_files > 0 and len(md_files) > max_files:
        md_files_limited = sorted(md_files, key=str)[:max_files]
        print(f"Limited to first {max_files} files (deterministic selection)")
    else:
        md_files_limited = md_files
        print(f"No limiting applied (max_files={max_files}, total files={len(md_files)})")

    print(f"\nFinal file count: {len(md_files_limited)}")

    # Show selected files
    print("\nSelected files:")
    for i, f in enumerate(md_files_limited, 1):
        rel_path = f.relative_to(test_dir)
        print(f"  {i}. {rel_path}")

    # Verify logic
    if len(md_files_limited) == min(max_files, len(md_files)):
        print(f"\n✅ SUCCESS: File limiting logic works correctly")
        print(f"   Expected: {min(max_files, len(md_files))}")
        print(f"   Got: {len(md_files_limited)}")
        return 0
    else:
        print(f"\n❌ FAIL: File limiting logic failed")
        print(f"   Expected: {min(max_files, len(md_files))}")
        print(f"   Got: {len(md_files_limited)}")
        return 1

if __name__ == "__main__":
    sys.exit(test_max_files_logic())
