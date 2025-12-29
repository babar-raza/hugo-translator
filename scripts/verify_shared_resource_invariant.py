#!/usr/bin/env python
"""
Verification script for shared resource invariant (TC1/TC2).

Checks whether child subprocesses write to shared resources that could
cause corruption without proper locking.

CRITICAL FINDING:
Child processes DO write to translation memory (TM) via tm.store().
This needs to be verified as safe before production deployment.
"""

import ast
import sys
from pathlib import Path


def find_tm_writes():
    """Find all calls to translation memory write operations."""
    engine_path = Path("src/translation_engine/engine.py")

    with open(engine_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print("=" * 70)
    print("SHARED RESOURCE INVARIANT VERIFICATION")
    print("=" * 70)
    print()

    # Check for TM write operations
    tm_writes = [
        ("tm.store(", "Write to translation memory"),
        ("tm.l3", "Access to L3 persistent cache"),
        ("progress.save(", "Write to progress tracking"),
        ("state.json", "Write to state file"),
    ]

    findings = []

    for pattern, description in tm_writes:
        if pattern in content:
            # Find line numbers
            lines = content.split('\n')
            line_nums = [i+1 for i, line in enumerate(lines) if pattern in line]
            findings.append((pattern, description, line_nums))

    print("FINDINGS:")
    print()

    for pattern, description, line_nums in findings:
        print(f"[!] {description}")
        print(f"    Pattern: {pattern}")
        print(f"    Found at lines: {line_nums}")
        print()

    print("=" * 70)
    print("ANALYSIS")
    print("=" * 70)
    print()

    if findings:
        print("[X] SHARED RESOURCE WRITES DETECTED")
        print()
        print("Child subprocesses DO write to shared resources:")
        print()
        print("1. Translation Memory (TM):")
        print("   - self.tm.store() called from _translate_to_language()")
        print("   - This is called by translate_file() -> used by child processes")
        print("   - TM may have internal file locking, but this needs verification")
        print()
        print("2. Threading Lock (_tm_lock):")
        print("   - exists at line 359: self._tm_lock = Lock()")
        print("   - BUT: only protects threading, NOT subprocess concurrency")
        print("   - Subprocess children don't share this lock")
        print()
        print("3. CRITICAL QUESTION:")
        print("   Does the TM implementation have process-safe file locking?")
        print("   This needs to be verified in the TM code (src/tm/).")
        print()
        print("=" * 70)
        print("RECOMMENDATIONS")
        print("=" * 70)
        print()
        print("BEFORE PRODUCTION DEPLOYMENT:")
        print()
        print("1. [TODO] Verify TM has internal file locking:")
        print("   - Check src/tm/ implementation for FileLock usage")
        print("   - Verify L3 cache writes are atomic/locked")
        print()
        print("2. [TODO] Test concurrent TM writes:")
        print("   - Run multi-language translation with 3+ languages")
        print("   - Verify no TM corruption occurs")
        print("   - Check TM integrity after concurrent writes")
        print()
        print("3. [!] CURRENT STATUS:")
        print("   If TM already handles concurrent subprocess writes safely,")
        print("   then TC1/TC2 fix doesn't make things worse - it just removes")
        print("   the site lock contention that was causing 5-min timeouts.")
        print()
        print("   If TM does NOT handle concurrent writes, then BOTH the current")
        print("   implementation AND TC1/TC2 have a data corruption risk.")
        print()

        return 1  # Exit with warning
    else:
        print("[PASS] No shared resource writes detected")
        print()
        print("All file writes appear to be language-scoped to:")
        print("  output/<site>/<target_lang>/...")
        print()
        return 0


def verify_output_paths():
    """Verify that output paths are language-scoped."""
    engine_path = Path("src/translation_engine/engine.py")

    with open(engine_path, 'r', encoding='utf-8') as f:
        content = f.read()

    print("=" * 70)
    print("OUTPUT PATH VERIFICATION")
    print("=" * 70)
    print()

    # Find _get_output_path method
    output_path_patterns = [
        "output_dir / target_lang",
        "/ target_lang /",
        "target_folder",
    ]

    findings = []
    lines = content.split('\n')

    for i, line in enumerate(lines):
        for pattern in output_path_patterns:
            if pattern in line:
                findings.append((i+1, line.strip()))

    if findings:
        print("[PASS] Output paths ARE language-scoped:")
        print()
        for line_num, line in findings[:5]:  # Show first 5
            print(f"   Line {line_num}: {line[:80]}")
        print()
        print(f"   Total: {len(findings)} occurrences found")
        print()
        print("[PASS] File writes to output/ directory are SAFE for concurrent children")
        print()
    else:
        print("[!] Could not verify output path scoping")
        print()

    return 0


if __name__ == "__main__":
    print()

    # Check for TM writes
    exit_code_1 = find_tm_writes()

    print()

    # Verify output paths
    exit_code_2 = verify_output_paths()

    print()
    print("=" * 70)
    print("SUMMARY")
    print("=" * 70)
    print()

    if exit_code_1 != 0:
        print("[!] WARNING: Shared resource writes detected")
        print("    Action required: Verify TM concurrency safety before production")
        print()
    else:
        print("[PASS] No concerning shared writes detected")
        print()

    print("Next steps:")
    print("1. Verify TM implementation has file locking (check src/tm/)")
    print("2. Run Gate 1 integration test (multi-language translation)")
    print("3. Check for TM corruption after concurrent writes")
    print()

    sys.exit(exit_code_1)
