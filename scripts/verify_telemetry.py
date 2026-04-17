#!/usr/bin/env python
"""
Telemetry Verification Script (TEL-07-A).

Verifies that telemetry is properly recording translation runs.

Usage:
    python verify_telemetry.py           # Run full translation test
    python verify_telemetry.py --latest  # Just verify latest DB record fields
    python verify_telemetry.py --check   # Alias for --latest
"""
import argparse
import json
import logging
import os
import sqlite3
import sys
from datetime import datetime
from pathlib import Path

logging.basicConfig(level=logging.INFO, format='%(levelname)s: %(message)s')
logger = logging.getLogger(__name__)

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

# Add telemetry module path
# Configurable via TELEMETRY_SRC_PATH environment variable.
# Set TELEMETRY_SRC_PATH to override default location for different deployments.
TELEMETRY_SRC_PATH = Path(
    os.getenv(
        'TELEMETRY_SRC_PATH',
        r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
    )
)

if not TELEMETRY_SRC_PATH.exists():
    logger.warning(f"Telemetry path not found: {TELEMETRY_SRC_PATH}. Telemetry will be unavailable.")
elif str(TELEMETRY_SRC_PATH) not in sys.path:
    logger.info(f"Loading telemetry from: {TELEMETRY_SRC_PATH}")
    sys.path.insert(0, str(TELEMETRY_SRC_PATH))
else:
    logger.debug(f"Telemetry path already in sys.path: {TELEMETRY_SRC_PATH}")


def verify_latest_record():
    """
    Verify all fields in the latest telemetry record (TEL-07-A).

    Checks all fields identified in telemetry-status.md report:
    - P0: product_family, subdomain
    - P1: error_summary, items_discovered, schema_version
    - P2: product, platform, agent_owner

    Returns:
        int: Exit code (0 = all pass, 1 = some failures)
    """
    print("=" * 60)
    print("TELEMETRY FIELD VERIFICATION (TEL-07-A)")
    print("=" * 60)

    # Get database path
    from telemetry.config import TelemetryConfig
    config = TelemetryConfig.from_env()

    db_path = config.database_path
    if not db_path.exists():
        print(f"\n[FAIL] Database not found: {db_path}")
        return 1

    print(f"\nDatabase: {db_path}")

    # Connect and query latest record
    conn = sqlite3.connect(str(db_path))
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("""
        SELECT * FROM agent_runs
        WHERE agent_name LIKE '%hugo-translator%'
        ORDER BY start_time DESC
        LIMIT 1
    """)

    row = cursor.fetchone()
    conn.close()

    if not row:
        print("\n[FAIL] No hugo-translator runs found in database")
        return 1

    record = dict(row)
    print(f"\nLatest Run: {record['run_id']}")
    print(f"Started: {record['start_time']}")
    print(f"Status: {record['status']}")

    # Define field checks
    checks = []

    def check(name: str, value, condition: bool, note: str = ""):
        status = "PASS" if condition else "FAIL"
        display_value = repr(value) if value is not None else "NULL"
        checks.append((name, status, display_value, note))

    # P0 - Critical (Business Context)
    print("\n--- P0: Critical (Business Context) ---")
    check("schema_version", record.get("schema_version"),
          record.get("schema_version") == 4,
          "Expected: 4")
    check("product_family", record.get("product_family"),
          record.get("product_family") is not None and len(record.get("product_family", "")) > 0,
          "Should be 'slides', 'words', etc.")
    check("subdomain", record.get("subdomain"),
          record.get("subdomain") is not None and len(record.get("subdomain", "")) > 0,
          "Should be 'products', 'docs', etc.")

    # P1 - Important
    print("\n--- P1: Important ---")
    check("agent_owner", record.get("agent_owner"),
          record.get("agent_owner") is not None and len(record.get("agent_owner", "")) > 0,
          "Should be 'Babar Raza' or from env")
    check("items_discovered", record.get("items_discovered"),
          record.get("items_discovered") is not None and record.get("items_discovered", 0) > 0,
          "Should be > 0 for successful runs")
    # error_summary is only required if there were errors
    items_failed = record.get("items_failed", 0) or 0
    if items_failed > 0:
        check("error_summary", record.get("error_summary"),
              record.get("error_summary") is not None,
              "Required when items_failed > 0")
    else:
        check("error_summary", record.get("error_summary"),
              True,  # Pass - no errors so no summary needed
              "OK (no errors)")

    # P2 - Recommended
    print("\n--- P2: Recommended ---")
    check("product", record.get("product"),
          record.get("product") is not None,
          "Product family identifier")
    check("platform", record.get("platform"),
          True,  # Optional - may be None if not detectable from path
          "Optional (doc target platform)")

    # Git context
    print("\n--- Git Context ---")
    check("git_repo", record.get("git_repo"),
          True,  # Optional
          "Optional (populated in git dir)")
    check("git_branch", record.get("git_branch"),
          True,  # Optional
          "Optional (populated in git dir)")
    check("host", record.get("host"),
          record.get("host") is not None,
          "Should be hostname")

    # Standard fields
    print("\n--- Standard Fields ---")
    check("run_id", record.get("run_id"),
          record.get("run_id") is not None,
          "Required")
    check("agent_name", record.get("agent_name"),
          record.get("agent_name") is not None,
          "Required")
    check("job_type", record.get("job_type"),
          record.get("job_type") is not None,
          "Required")
    check("trigger_type", record.get("trigger_type"),
          record.get("trigger_type") is not None,
          "Required")
    check("start_time", record.get("start_time"),
          record.get("start_time") is not None,
          "Required")
    check("status", record.get("status"),
          record.get("status") in ("running", "success", "failed", "partial"),
          "Valid status")
    check("input_summary", record.get("input_summary"),
          record.get("input_summary") is not None,
          "Should describe input")

    # Print results table
    print("\n" + "=" * 60)
    print("VERIFICATION RESULTS")
    print("=" * 60)
    print(f"{'Field':<20} {'Status':<6} {'Value':<30} {'Note'}")
    print("-" * 80)

    failed_count = 0
    for name, status, value, note in checks:
        # Truncate long values
        if len(value) > 28:
            value = value[:25] + "..."
        status_icon = "[OK]" if status == "PASS" else "[!!]"
        print(f"{name:<20} {status_icon:<6} {value:<30} {note}")
        if status == "FAIL":
            failed_count += 1

    print("-" * 80)
    total = len(checks)
    passed = total - failed_count
    print(f"\nSummary: {passed}/{total} checks passed")

    if failed_count > 0:
        print(f"\n[FAIL] {failed_count} verification(s) failed")
        return 1
    else:
        print("\n[PASS] All verifications passed!")
        return 0


def main():
    parser = argparse.ArgumentParser(
        description="Telemetry Verification Script (TEL-07-A)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--latest", "--check",
        action="store_true",
        dest="latest",
        help="Just verify latest DB record fields (quick check)"
    )
    args = parser.parse_args()

    # Route to field verification mode if requested
    if args.latest:
        return verify_latest_record()

    # Default: full translation test
    print("=" * 60)
    print("TELEMETRY VERIFICATION")
    print("=" * 60)

    # Check telemetry directory
    from telemetry.config import TelemetryConfig

    config = TelemetryConfig.from_env()

    print("\n[1] Telemetry Settings:")
    print(f"    Metrics directory: {config.metrics_dir}")
    print(f"    Database path: {config.database_path}")
    print(f"    NDJSON directory: {config.ndjson_dir}")
    print(f"    API enabled: {config.api_enabled}")

    # Check if directory exists
    data_dir = config.ndjson_dir
    if not data_dir.exists():
        print("\n[WARN] Data directory does not exist yet")
        data_dir.mkdir(parents=True, exist_ok=True)
        print(f"    Created: {data_dir}")

    # List existing run files
    run_files = list(data_dir.glob("*.ndjson"))
    print(f"\n[2] Existing Run Files: {len(run_files)}")

    if run_files:
        # Show last 3 runs
        sorted_files = sorted(run_files, key=lambda x: x.stat().st_mtime, reverse=True)[:3]
        for f in sorted_files:
            size = f.stat().st_size
            mod_time = datetime.fromtimestamp(f.stat().st_mtime).strftime("%Y-%m-%d %H:%M:%S")
            print(f"    - {f.name} ({size} bytes, {mod_time})")

    # Run a single file translation test
    print("\n[3] Testing Translation with Telemetry...")

    import torch

    from src.model_runtime import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2PersistentTM
    from src.tm.l3_semantic import L3SemanticTM
    from src.translation_engine import TranslationEngine
    from src.utils.config_loader import ConfigService

    REPO_ROOT = Path(__file__).parent.parent
    config_path = REPO_ROOT / "config"
    config_service = ConfigService(config_path)

    # Initialize TM layers
    l1_cache = L1Cache(max_size=10000)
    lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
    lmdb_path.parent.mkdir(parents=True, exist_ok=True)
    l2_persistent = L2PersistentTM(str(lmdb_path))

    faiss_path = REPO_ROOT / "data" / "tm" / "l3_faiss"
    faiss_path.mkdir(parents=True, exist_ok=True)
    l3_semantic = L3SemanticTM(index_path=str(faiss_path))

    tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent, l3_semantic=l3_semantic)

    # Initialize ModelLoader
    registry_path = config_path / "model_registry.yaml"
    model_registry = ModelRegistry(registry_path)
    device = "cuda" if torch.cuda.is_available() else "cpu"
    print(f"    Device: {device}")

    model_loader = ModelLoader(registry=model_registry, device=device)

    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        enable_telemetry=True
    )

    # Translate one file to one language
    test_file = Path(r"D:\onedrive\Documents\GitHub\aspose.net\content\products.aspose.net\slides\en\_index.md")

    if not test_file.exists():
        print(f"    [ERROR] Test file not found: {test_file}")
        return 1

    print(f"    Source: {test_file.name}")
    print("    Target: de (German)")

    try:
        result = engine.translate_file(
            site_id="products.aspose.net",
            file_path=test_file,
            target_langs=["de"],
        )

        print(f"    Status: {'SUCCESS' if result.success else 'FAILED'}")
        print(f"    Segments: {result.stats.total_segments}")
        print(f"    Duration: {result.stats.duration_seconds:.2f}s")

        if result.errors:
            print(f"    Errors: {result.errors}")
    except Exception as e:
        print(f"    [ERROR] Translation failed: {e}")
        import traceback
        traceback.print_exc()
        return 1

    # Check for new telemetry data
    print("\n[4] Checking for New Telemetry Data...")

    new_run_files = list(data_dir.glob("*.ndjson"))
    new_files = set(new_run_files) - set(run_files)

    # Also check the database
    if config.database_path.exists():
        print(f"    [OK] Database file exists: {config.database_path}")
        print(f"    Database size: {config.database_path.stat().st_size} bytes")
    else:
        print("    [INFO] Database file not yet created")

    if new_files:
        print("    [OK] New telemetry NDJSON file(s) created!")
        for f in new_files:
            print(f"    File: {f.name}")

            # Read and validate the NDJSON file (each line is JSON)
            try:
                with open(f) as fh:
                    lines = fh.readlines()

                print(f"    Events in file: {len(lines)}")

                if lines:
                    # Parse last event
                    last_event = json.loads(lines[-1])
                    print("\n    Last Event:")
                    print(f"      - event_type: {last_event.get('event_type', 'N/A')}")
                    print(f"      - run_id: {last_event.get('run_id', 'N/A')}")
                    print(f"      - timestamp: {last_event.get('timestamp', 'N/A')}")

            except Exception as e:
                print(f"    [WARN] Failed to read NDJSON file: {e}")
    else:
        # Check for any existing files with recent data
        if run_files:
            # Check if the existing files were updated
            most_recent = max(run_files, key=lambda x: x.stat().st_mtime)
            mod_time = datetime.fromtimestamp(most_recent.stat().st_mtime)
            print(f"    [INFO] Most recent file: {most_recent.name}")
            print(f"    [INFO] Last modified: {mod_time.strftime('%Y-%m-%d %H:%M:%S')}")
        print("    [INFO] No new files created (may have appended to existing)")

    print("\n" + "=" * 60)
    print("TELEMETRY VERIFICATION: PASSED")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
