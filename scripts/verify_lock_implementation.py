#!/usr/bin/env python
"""
Verification script for TC1 and TC2 lock implementation.

Tests:
1. Lock acquisition and release with JSON metadata
2. Stale lock detection
3. force_unlock() method
4. diagnose_lock() function
"""
import json
import os
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from utils.file_lock import FileLock, diagnose_lock
from translation_engine.engine import get_site_lock_path, get_site_lock


def test_basic_lock_acquisition():
    """Test basic lock acquisition and release."""
    print("=" * 60)
    print("TEST 1: Basic Lock Acquisition and Release")
    print("=" * 60)

    site_id = "test.example.net"
    lock = get_site_lock(site_id, timeout=5.0)

    try:
        # Acquire lock
        print("Acquiring lock...")
        if not lock.acquire(blocking=True):
            print("✗ FAIL: Could not acquire lock")
            return False

        print("✓ Lock acquired successfully")

        # Check lock file exists
        lock_path = get_site_lock_path(site_id)
        if not lock_path.exists():
            print("✗ FAIL: Lock file does not exist")
            return False

        print(f"✓ Lock file exists: {lock_path}")

        # Check JSON metadata
        with open(lock_path, 'r') as f:
            content = f.read()

        try:
            data = json.loads(content)
            print(f"✓ Lock file contains valid JSON")
            print(f"  - PID: {data.get('pid')}")
            print(f"  - Hostname: {data.get('hostname')}")
            print(f"  - Created: {data.get('created')}")
            print(f"  - Format version: {data.get('format_version')}")

            if data.get('pid') != os.getpid():
                print("✗ FAIL: PID mismatch")
                return False

            if 'hostname' not in data or 'created' not in data:
                print("✗ FAIL: Missing required metadata")
                return False

            print("✓ Metadata validation passed")

        except json.JSONDecodeError:
            print(f"✗ FAIL: Lock file is not valid JSON")
            print(f"Content: {content}")
            return False

        # Release lock
        print("Releasing lock...")
        lock.release()

        if lock_path.exists():
            print("✗ FAIL: Lock file still exists after release")
            return False

        print("✓ Lock released successfully")
        return True

    except Exception as e:
        print(f"✗ FAIL: Exception during test: {e}")
        import traceback
        traceback.print_exc()
        return False


def test_stale_lock_detection():
    """Test stale lock detection."""
    print("\n" + "=" * 60)
    print("TEST 2: Stale Lock Detection")
    print("=" * 60)

    site_id = "test.stale.example.net"
    lock_path = get_site_lock_path(site_id)

    try:
        # Create stale lock with dead PID
        stale_pid = 999999
        metadata = {
            'pid': stale_pid,
            'hostname': 'test-host',
            'created': '2025-01-01T00:00:00',
            'format_version': '1.0'
        }

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, 'w') as f:
            json.dump(metadata, f)

        print(f"Created stale lock with PID {stale_pid}")

        # Test stale detection
        lock = FileLock(lock_path, timeout=5.0)
        is_stale = lock._is_stale_lock()

        if not is_stale:
            print("✗ FAIL: Stale lock not detected")
            return False

        print("✓ Stale lock detected successfully")

        # Cleanup
        if lock_path.exists():
            lock_path.unlink()

        return True

    except Exception as e:
        print(f"✗ FAIL: Exception during test: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Ensure cleanup
        if lock_path.exists():
            try:
                lock_path.unlink()
            except:
                pass


def test_force_unlock():
    """Test force_unlock() method."""
    print("\n" + "=" * 60)
    print("TEST 3: Force Unlock")
    print("=" * 60)

    site_id = "test.force-unlock.example.net"
    lock_path = get_site_lock_path(site_id)

    try:
        # Create stale lock
        stale_pid = 999999
        metadata = {
            'pid': stale_pid,
            'hostname': 'test-host',
            'created': '2025-01-01T00:00:00',
            'format_version': '1.0'
        }

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, 'w') as f:
            json.dump(metadata, f)

        print(f"Created stale lock with PID {stale_pid}")

        # Force unlock
        lock = FileLock(lock_path)
        result = lock.force_unlock(check_pid=True)

        if not result:
            print("✗ FAIL: Force unlock failed")
            return False

        print("✓ Force unlock succeeded")

        if lock_path.exists():
            print("✗ FAIL: Lock file still exists after force unlock")
            return False

        print("✓ Lock file removed")
        return True

    except Exception as e:
        print(f"✗ FAIL: Exception during test: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Ensure cleanup
        if lock_path.exists():
            try:
                lock_path.unlink()
            except:
                pass


def test_diagnose_lock():
    """Test diagnose_lock() function."""
    print("\n" + "=" * 60)
    print("TEST 4: Diagnose Lock Function")
    print("=" * 60)

    site_id = "test.diagnose.example.net"
    lock_path = get_site_lock_path(site_id)

    try:
        # Test with no lock
        print("\n--- Scenario 1: No lock exists ---")
        diagnose_lock(site_id)

        # Test with current process lock
        print("\n--- Scenario 2: Current process holds lock ---")
        metadata = {
            'pid': os.getpid(),
            'hostname': 'test-host',
            'created': '2025-01-01T00:00:00',
            'format_version': '1.0'
        }

        lock_path.parent.mkdir(parents=True, exist_ok=True)
        with open(lock_path, 'w') as f:
            json.dump(metadata, f)

        diagnose_lock(site_id)

        # Test with stale lock
        print("\n--- Scenario 3: Stale lock (dead PID) ---")
        metadata['pid'] = 999999
        with open(lock_path, 'w') as f:
            json.dump(metadata, f)

        diagnose_lock(site_id)

        print("\n✓ Diagnose lock function works")
        return True

    except Exception as e:
        print(f"✗ FAIL: Exception during test: {e}")
        import traceback
        traceback.print_exc()
        return False
    finally:
        # Cleanup
        if lock_path.exists():
            try:
                lock_path.unlink()
            except:
                pass


def main():
    """Run all verification tests."""
    print("\n" + "=" * 60)
    print("LOCK IMPLEMENTATION VERIFICATION SUITE")
    print("=" * 60)

    tests = [
        ("Basic Lock Acquisition", test_basic_lock_acquisition),
        ("Stale Lock Detection", test_stale_lock_detection),
        ("Force Unlock", test_force_unlock),
        ("Diagnose Lock", test_diagnose_lock),
    ]

    results = []
    for name, test_func in tests:
        try:
            result = test_func()
            results.append((name, result))
        except Exception as e:
            print(f"\n✗ FATAL ERROR in {name}: {e}")
            import traceback
            traceback.print_exc()
            results.append((name, False))

    # Summary
    print("\n" + "=" * 60)
    print("TEST SUMMARY")
    print("=" * 60)

    passed = sum(1 for _, result in results if result)
    total = len(results)

    for name, result in results:
        status = "✓ PASS" if result else "✗ FAIL"
        print(f"{status}: {name}")

    print(f"\nTotal: {passed}/{total} tests passed")

    if passed == total:
        print("\n✓✓✓ ALL TESTS PASSED ✓✓✓")
        return 0
    else:
        print(f"\n✗✗✗ {total - passed} TEST(S) FAILED ✗✗✗")
        return 1


if __name__ == "__main__":
    sys.exit(main())
