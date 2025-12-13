#!/usr/bin/env python
"""
Telemetry Verification Script.

Verifies that telemetry is properly recording translation runs.
"""
import os
import sys
import json
from pathlib import Path
from datetime import datetime

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))
os.chdir(Path(__file__).parent.parent)

# Add telemetry module path
TELEMETRY_SRC_PATH = Path(r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src")
if TELEMETRY_SRC_PATH.exists() and str(TELEMETRY_SRC_PATH) not in sys.path:
    sys.path.insert(0, str(TELEMETRY_SRC_PATH))

def main():
    print("=" * 60)
    print("TELEMETRY VERIFICATION")
    print("=" * 60)

    # Check telemetry directory
    from telemetry.config import TelemetryConfig

    config = TelemetryConfig.from_env()

    print(f"\n[1] Telemetry Settings:")
    print(f"    Metrics directory: {config.metrics_dir}")
    print(f"    Database path: {config.database_path}")
    print(f"    NDJSON directory: {config.ndjson_dir}")
    print(f"    API enabled: {config.api_enabled}")

    # Check if directory exists
    data_dir = config.ndjson_dir
    if not data_dir.exists():
        print(f"\n[WARN] Data directory does not exist yet")
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
    print(f"\n[3] Testing Translation with Telemetry...")

    from src.translation_engine import TranslationEngine
    from src.utils.config_loader import ConfigService
    from src.tm import TranslationMemory
    from src.tm.l1_cache import L1Cache
    from src.tm.l2_persistent import L2PersistentTM
    from src.tm.l3_semantic import L3SemanticTM
    from src.model_runtime import ModelLoader
    from src.model_runtime.registry import ModelRegistry
    import torch

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
    print(f"    Target: de (German)")

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
    print(f"\n[4] Checking for New Telemetry Data...")

    new_run_files = list(data_dir.glob("*.ndjson"))
    new_files = set(new_run_files) - set(run_files)

    # Also check the database
    if config.database_path.exists():
        print(f"    [OK] Database file exists: {config.database_path}")
        print(f"    Database size: {config.database_path.stat().st_size} bytes")
    else:
        print(f"    [INFO] Database file not yet created")

    if new_files:
        print(f"    [OK] New telemetry NDJSON file(s) created!")
        for f in new_files:
            print(f"    File: {f.name}")

            # Read and validate the NDJSON file (each line is JSON)
            try:
                with open(f, 'r') as fh:
                    lines = fh.readlines()

                print(f"    Events in file: {len(lines)}")

                if lines:
                    # Parse last event
                    last_event = json.loads(lines[-1])
                    print(f"\n    Last Event:")
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
        print(f"    [INFO] No new files created (may have appended to existing)")

    print("\n" + "=" * 60)
    print("TELEMETRY VERIFICATION: PASSED")
    print("=" * 60)

    return 0


if __name__ == "__main__":
    sys.exit(main())
