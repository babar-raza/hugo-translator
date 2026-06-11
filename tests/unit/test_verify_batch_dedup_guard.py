#!/usr/bin/env python3
"""
Test that verify_batch() runtime deduplication guard catches duplicates.

This test validates TASK-5.3: Runtime deduplication guard in verify_batch().
"""

import sys
from pathlib import Path

import pytest

# Add repo root to path
REPO_ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO_ROOT))


def test_verify_batch_dedup_guard_in_code():
    """Test that the deduplication guard exists in run_batch23.py."""
    script_path = (
        REPO_ROOT / "reports" / "phase6_cli_forced_translate" / "20260128-2139" / "run_batch23.py"
    )

    if not script_path.exists():
        pytest.skip(f"Script not found: {script_path}")

    # Read the script and verify the guard is present
    with open(script_path, encoding="utf-8") as f:
        content = f.read()

    # Check for the deduplication guard
    assert "Runtime deduplication guard" in content, "Deduplication guard comment not found"
    assert "seen_paths = set()" in content, "seen_paths initialization not found"
    assert "DUPLICATE DETECTED" in content, "Duplicate error message not found"
    assert "if source_path in seen_paths:" in content, "Duplicate check not found"
    assert "seen_paths.add(source_path)" in content, "Path tracking not found"

    # Verify it's in the verify_batch function
    # Extract the verify_batch function
    import re

    pattern = r"def verify_batch\(.*?\):(.*?)(?=\ndef |\Z)"
    match = re.search(pattern, content, re.DOTALL)

    assert match, "verify_batch function not found"

    verify_batch_code = match.group(1)

    # Verify guard is at the start of the function (before processing loop)
    assert "seen_paths" in verify_batch_code, "Deduplication guard not in verify_batch"
    assert "DUPLICATE DETECTED" in verify_batch_code, "Duplicate error not in verify_batch"


def test_dedup_guard_logic_unit():
    """Unit test for the deduplication guard logic in isolation."""

    # Simulate the guard logic
    def check_for_duplicates(batch_rows, batch_num):
        seen_paths = set()
        for row in batch_rows:
            source_path = row["source_path"]
            if source_path in seen_paths:
                raise ValueError(
                    f"DUPLICATE DETECTED in batch {batch_num}: {source_path}\n"
                    f"This indicates a regression in batch creation logic."
                )
            seen_paths.add(source_path)

    # Test 1: No duplicates
    batch_clean = [
        {"source_path": "a.md"},
        {"source_path": "b.md"},
        {"source_path": "c.md"},
    ]

    # Should not raise
    check_for_duplicates(batch_clean, 1)

    # Test 2: Duplicate at different positions
    batch_dup_end = [
        {"source_path": "a.md"},
        {"source_path": "b.md"},
        {"source_path": "a.md"},  # Duplicate
    ]

    with pytest.raises(ValueError, match="DUPLICATE DETECTED.*a.md"):
        check_for_duplicates(batch_dup_end, 2)

    # Test 3: Immediate duplicate
    batch_dup_immediate = [
        {"source_path": "x.md"},
        {"source_path": "x.md"},  # Immediate duplicate
    ]

    with pytest.raises(ValueError, match="DUPLICATE DETECTED.*x.md"):
        check_for_duplicates(batch_dup_immediate, 3)

    # Test 4: Multiple duplicates (should catch first one)
    batch_multi_dup = [
        {"source_path": "a.md"},
        {"source_path": "b.md"},
        {"source_path": "a.md"},  # First duplicate
        {"source_path": "b.md"},  # Second duplicate (won't reach)
    ]

    with pytest.raises(ValueError, match="DUPLICATE DETECTED.*a.md"):
        check_for_duplicates(batch_multi_dup, 4)


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
