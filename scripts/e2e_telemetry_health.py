#!/usr/bin/env python
"""
Telemetry Health Check for E2E Bulk Verification.

Verifies that the telemetry system is operational before starting bulk translation.
"""
import logging
import os
import sys
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add src to path
repo_root = Path(__file__).parent.parent
sys.path.insert(0, str(repo_root))
os.chdir(repo_root)

def main():
    """Perform telemetry health check."""
    print("=" * 60)
    print("TELEMETRY HEALTH CHECK")
    print("=" * 60)

    exit_code = 0

    # Check 1: Verify TELEMETRY_SRC_PATH exists
    telemetry_src = Path(
        os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        )
    )

    print(f"\n1. Checking telemetry source path...")
    print(f"   Path: {telemetry_src}")

    if not telemetry_src.exists():
        print("   [FAIL] Telemetry source path not found")
        exit_code = 1
    else:
        print("   [PASS] Telemetry source path exists")

    # Check 2: Import telemetry modules
    print(f"\n2. Importing telemetry modules...")

    if str(telemetry_src) not in sys.path:
        sys.path.insert(0, str(telemetry_src))

    try:
        from telemetry.client import TelemetryClient
        from telemetry.config import TelemetryConfig
        print("   [PASS] Telemetry modules imported successfully")
    except ImportError as e:
        print(f"   [FAIL] Could not import telemetry modules: {e}")
        exit_code = 1
        return exit_code

    # Check 3: Get database configuration
    print(f"\n3. Checking database configuration...")

    try:
        config = TelemetryConfig.from_env()
        db_path = config.database_path
        print(f"   Database: {db_path}")

        if not db_path.exists():
            print("   [WARN] Database does not exist yet (will be created on first use)")
            # Not a failure - DB will be created
        else:
            print("   [PASS] Database exists")

            # Check 4: Test database connectivity
            print(f"\n4. Testing database connectivity...")
            import sqlite3

            try:
                conn = sqlite3.connect(str(db_path))
                cursor = conn.cursor()
                cursor.execute("SELECT name FROM sqlite_master WHERE type='table' AND name='agent_runs'")
                table_exists = cursor.fetchone() is not None
                conn.close()

                if table_exists:
                    print("   [PASS] Database connection successful, agent_runs table exists")
                else:
                    print("   [WARN] Database connection successful, but agent_runs table not found")
                    print("          (Table will be created on first telemetry write)")

            except Exception as e:
                print(f"   [FAIL] Database connection failed: {e}")
                exit_code = 1

    except Exception as e:
        print(f"   [FAIL] Could not get database config: {e}")
        exit_code = 1
        return exit_code

    # Check 5: Test telemetry integration availability
    print(f"\n5. Checking telemetry integration...")

    try:
        from src.observability.telemetry_integration import TELEMETRY_AVAILABLE

        if TELEMETRY_AVAILABLE:
            print("   [PASS] Telemetry integration is available")
        else:
            print("   [FAIL] Telemetry integration is not available")
            exit_code = 1

    except Exception as e:
        print(f"   [FAIL] Could not check telemetry integration: {e}")
        exit_code = 1

    # Summary
    print("\n" + "=" * 60)
    if exit_code == 0:
        print("HEALTH CHECK: PASSED")
        print("Telemetry system is operational and ready for E2E bulk verification.")
    else:
        print("HEALTH CHECK: FAILED")
        print("Telemetry system is not fully operational. Review errors above.")
    print("=" * 60)

    return exit_code

if __name__ == "__main__":
    sys.exit(main())
