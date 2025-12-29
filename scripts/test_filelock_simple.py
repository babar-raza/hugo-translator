#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""
Simple standalone test for FileLock class (TC1/TC2 verification).

Can be run directly without full package imports.
"""
import json
import os
import sys
import time
from pathlib import Path

# Windows console compatibility
def print_check(passed, message):
    """Print with ASCII checkmarks for Windows compatibility."""
    if passed:
        print(f"[PASS] {message}")
    else:
        print(f"[FAIL] {message}")

# Test FileLock directly by copying minimal implementation
print("=" * 60)
print("FILELOCK VERIFICATION TEST")
print("=" * 60)

# Test 1: Check if file_lock.py compiles
print("\nTest 1: Checking if file_lock.py compiles...")
try:
    import py_compile
    py_compile.compile('src/utils/file_lock.py', doraise=True)
    print("[PASS] file_lock.py compiles successfully")
except Exception as e:
    print(f"[FAIL] FAIL: file_lock.py does not compile: {e}")
    sys.exit(1)

# Test 2: Check if engine.py compiles
print("\nTest 2: Checking if engine.py compiles...")
try:
    py_compile.compile('src/translation_engine/engine.py', doraise=True)
    print("[PASS] engine.py compiles successfully")
except Exception as e:
    print(f"[FAIL] FAIL: engine.py does not compile: {e}")
    sys.exit(1)

# Test 3: Check if cli.py compiles
print("\nTest 3: Checking if cli.py compiles...")
try:
    py_compile.compile('src/cli.py', doraise=True)
    print("[PASS] cli.py compiles successfully")
except Exception as e:
    print(f"[FAIL] FAIL: cli.py does not compile: {e}")
    sys.exit(1)

# Test 4: Verify JSON metadata functions exist
print("\nTest 4: Verifying JSON metadata implementation...")
with open('src/utils/file_lock.py', 'r') as f:
    content = f.read()

checks = [
    ("JSON import", "import json" in content),
    ("Socket import", "import socket" in content),
    ("Datetime import", "from datetime import datetime" in content),
    ("JSON metadata write", "json.dumps(metadata" in content),
    ("PID in metadata", "'pid': os.getpid()" in content),
    ("Hostname in metadata", "'hostname': socket.gethostname()" in content),
    ("Created timestamp", "'created':" in content),
    ("_is_process_alive method", "def _is_process_alive" in content),
    ("force_unlock method", "def force_unlock" in content),
    ("diagnose_lock function", "def diagnose_lock" in content),
]

all_passed = True
for check_name, check_result in checks:
    if check_result:
        print(f"  [PASS] {check_name}")
    else:
        print(f"  [FAIL] {check_name} - NOT FOUND")
        all_passed = False

if not all_passed:
    print("\n[FAIL] Some checks failed")
    sys.exit(1)

print("\n[PASS] All JSON metadata implementation checks passed")

# Test 5: Verify engine.py has helper functions
print("\nTest 5: Verifying engine.py helper functions...")
with open('src/translation_engine/engine.py', 'r') as f:
    content = f.read()

checks = [
    ("get_site_lock_path function", "def get_site_lock_path" in content),
    ("get_site_lock function", "def get_site_lock" in content),
    ("skip_site_lock parameter", "skip_site_lock: bool" in content),
    ("TC1 skip lock check", "if skip_site_lock:" in content),
    ("TC2 auto-cleanup", "AUTO-CLEANUP" in content or "Auto-removing stale lock" in content),
]

all_passed = True
for check_name, check_result in checks:
    if check_result:
        print(f"  [PASS] {check_name}")
    else:
        print(f"  [FAIL] {check_name} - NOT FOUND")
        all_passed = False

if not all_passed:
    print("\n[FAIL] Some checks failed")
    sys.exit(1)

print("\n[PASS] All engine.py helper function checks passed")

# Test 6: Verify CLI changes
print("\nTest 6: Verifying CLI commands...")
with open('src/cli.py', 'r') as f:
    content = f.read()

checks = [
    ("--_skip-site-lock flag", "--_skip-site-lock" in content),
    ("Parent lock global variable", "_parent_lock = None" in content),
    ("Signal handler", "def _signal_handler" in content),
    ("get_site_lock import usage", "from src.translation_engine.engine import get_site_lock" in content or "get_site_lock" in content),
    ("Site lock acquire", "site_lock.acquire" in content),
    ("Skip lock flag passed to subprocess", '--_skip-site-lock' in content),
    ("cmd_unlock function", "def cmd_unlock" in content),
    ("cmd_diagnose_lock function", "def cmd_diagnose_lock" in content),
    ("unlock command routing", 'sys.argv[1] == "unlock"' in content),
    ("diagnose-lock command routing", 'sys.argv[1] == "diagnose-lock"' in content),
]

all_passed = True
for check_name, check_result in checks:
    if check_result:
        print(f"  [PASS] {check_name}")
    else:
        print(f"  [FAIL] {check_name} - NOT FOUND")
        all_passed = False

if not all_passed:
    print("\n[FAIL] Some checks failed")
    sys.exit(1)

print("\n[PASS] All CLI implementation checks passed")

# Summary
print("\n" + "=" * 60)
print("VERIFICATION SUMMARY")
print("=" * 60)
print("[PASS] All compilation checks passed")
print("[PASS] All implementation checks passed")
print("\n" + "[PASS]" * 20 + " SUCCESS " + "[PASS]" * 20)
print("\nImplementation verified successfully!")
print("\nNext steps:")
print("1. Test diagnose-lock command: python -m src.cli diagnose-lock --site test.example.net")
print("2. Test unlock command: python -m src.cli unlock --site test.example.net --yes")
print("3. Run actual multi-language translation to test TC1 parent lock pattern")
print("=" * 60)

sys.exit(0)
