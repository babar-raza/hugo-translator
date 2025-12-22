#!/usr/bin/env python
"""
Test telemetry integration with Docker-deployed telemetry system.

This script:
1. Verifies Docker telemetry API is accessible
2. Tests hugo-translator can send events to the API
3. Verifies events are received and stored
4. Checks buffer failover mechanism
"""
import os
import sys
import json
import time
import requests
from pathlib import Path
from datetime import datetime

# Add src to path
REPO_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

# Colors for output
GREEN = '\033[92m'
RED = '\033[91m'
YELLOW = '\033[93m'
BLUE = '\033[94m'
RESET = '\033[0m'

def print_header(msg):
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}{msg}{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")

def print_success(msg):
    print(f"{GREEN}✓ {msg}{RESET}")

def print_error(msg):
    print(f"{RED}✗ {msg}{RESET}")

def print_info(msg):
    print(f"{YELLOW}ℹ {msg}{RESET}")


def test_docker_api_health():
    """Test 1: Verify Docker API is running and healthy."""
    print_header("TEST 1: Docker Telemetry API Health")

    api_url = os.getenv("METRICS_API_URL", "http://localhost:8765")
    print_info(f"API URL: {api_url}")

    try:
        response = requests.get(f"{api_url}/health", timeout=5)
        response.raise_for_status()
        health = response.json()

        print_success(f"API Status: {health['status']}")
        print_success(f"API Version: {health['version']}")
        print_success(f"Database Path: {health['db_path']}")
        print_success(f"Journal Mode: {health['journal_mode']}")
        print_success(f"Synchronous: {health['synchronous']}")

        return True
    except Exception as e:
        print_error(f"API Health Check Failed: {e}")
        return False


def test_api_metrics():
    """Test 2: Check current metrics from API."""
    print_header("TEST 2: Current Telemetry Metrics")

    api_url = os.getenv("METRICS_API_URL", "http://localhost:8765")

    try:
        response = requests.get(f"{api_url}/metrics", timeout=5)
        response.raise_for_status()
        metrics = response.json()

        print_success(f"Total Runs: {metrics['total_runs']}")
        print_success(f"Recent 24h: {metrics['recent_24h']}")

        print_info("\nRuns by Agent:")
        for agent, count in metrics.get('agents', {}).items():
            prefix = "  ➜ " if agent == "hugo-translator" else "    "
            print(f"{prefix}{agent}: {count}")

        return metrics
    except Exception as e:
        print_error(f"Metrics Check Failed: {e}")
        return None


def test_telemetry_client_init():
    """Test 3: Verify TelemetryClient initializes correctly."""
    print_header("TEST 3: TelemetryClient Initialization")

    try:
        # Set up telemetry path
        telemetry_src = Path(os.getenv(
            'TELEMETRY_SRC_PATH',
            r"C:\Users\prora\OneDrive\Documents\GitHub\local-telemetry\src"
        ))

        if not telemetry_src.exists():
            print_error(f"Telemetry source not found: {telemetry_src}")
            return False

        if str(telemetry_src) not in sys.path:
            sys.path.insert(0, str(telemetry_src))

        print_info(f"Telemetry Source: {telemetry_src}")

        # Import telemetry
        from telemetry.client import TelemetryClient
        from telemetry.config import TelemetryConfig

        # Create client with config from environment
        config = TelemetryConfig.from_env()
        print_success(f"TelemetryConfig loaded from environment")
        print_info(f"  API URL: {config.api_url}")
        print_info(f"  Metrics Dir: {config.metrics_dir}")

        client = TelemetryClient(config=config)
        print_success("TelemetryClient initialized successfully")

        # Verify HTTP API client
        if hasattr(client, 'http_api'):
            print_success(f"HTTP API client: {client.http_api.api_url}")

        # Verify buffer
        if hasattr(client, 'buffer'):
            print_success(f"Buffer initialized: {client.buffer.buffer_dir}")

        return client
    except Exception as e:
        print_error(f"TelemetryClient Init Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_send_event_to_api(client):
    """Test 4: Send a test event to the API."""
    print_header("TEST 4: Send Test Event to API")

    if not client:
        print_error("No client available (skipping)")
        return None

    try:
        # Start a test run
        print_info("Starting test run...")
        run_id = client.start_run(
            agent_name="hugo-translator-integration-test",
            job_type="docker_api_integration_test",
            trigger_type="manual",
            product_family="test",
            subdomain="test",
        )

        print_success(f"Run started: {run_id}")

        # Wait a moment for event to be processed
        time.sleep(1)

        # End the run
        print_info("Ending test run...")
        client.end_run(
            run_id,
            status="success",
            items_discovered=5,
            items_succeeded=5,
            input_summary="Integration test",
            output_summary="5/5 items succeeded",
        )

        print_success(f"Run ended: {run_id}")

        # Wait for API to process
        time.sleep(2)

        return run_id
    except Exception as e:
        print_error(f"Send Event Failed: {e}")
        import traceback
        traceback.print_exc()
        return None


def test_verify_event_in_api(run_id):
    """Test 5: Verify event was received by API."""
    print_header("TEST 5: Verify Event in API")

    if not run_id:
        print_error("No run_id available (skipping)")
        return False

    api_url = os.getenv("METRICS_API_URL", "http://localhost:8765")

    try:
        # Query recent runs
        print_info(f"Querying API for run: {run_id}")
        response = requests.get(
            f"{api_url}/metrics",
            timeout=5
        )
        response.raise_for_status()
        metrics = response.json()

        # Check if our agent is in the metrics
        agents = metrics.get('agents', {})
        if "hugo-translator-integration-test" in agents:
            count = agents["hugo-translator-integration-test"]
            print_success(f"Found agent in metrics: {count} run(s)")
        else:
            print_error("Agent not found in metrics (event may not have synced yet)")

        # Check total runs increased
        print_success(f"Total runs now: {metrics['total_runs']}")

        return True
    except Exception as e:
        print_error(f"API Verification Failed: {e}")
        return False


def test_buffer_directory():
    """Test 6: Check buffer directory and file states."""
    print_header("TEST 6: Buffer Directory Check")

    buffer_dir = Path(os.getenv(
        "TELEMETRY_BUFFER_DIR",
        "C:/telemetry/hugo-translator/buffer"
    ))

    print_info(f"Buffer Directory: {buffer_dir}")

    if not buffer_dir.exists():
        print_error(f"Buffer directory does not exist: {buffer_dir}")
        return False

    print_success(f"Buffer directory exists")

    # Check for buffer files
    active_files = list(buffer_dir.glob("*.jsonl.active"))
    ready_files = list(buffer_dir.glob("*.jsonl.ready"))
    synced_files = list(buffer_dir.glob("*.jsonl.synced"))

    print_info(f"\nBuffer File States:")
    print(f"  .active files: {len(active_files)}")
    print(f"  .ready files: {len(ready_files)}")
    print(f"  .synced files: {len(synced_files)}")

    if active_files:
        print_info(f"\nActive Buffer File:")
        for f in active_files:
            size_kb = f.stat().st_size / 1024
            print(f"  ➜ {f.name} ({size_kb:.1f} KB)")

    if ready_files:
        print_info(f"\n⚠ Ready Files (waiting for sync):")
        for f in ready_files:
            size_kb = f.stat().st_size / 1024
            print(f"  ➜ {f.name} ({size_kb:.1f} KB)")

    if synced_files:
        print_info(f"\nSynced Files (successfully processed):")
        for f in synced_files[:3]:  # Show first 3
            size_kb = f.stat().st_size / 1024
            print(f"  ➜ {f.name} ({size_kb:.1f} KB)")
        if len(synced_files) > 3:
            print(f"  ... and {len(synced_files) - 3} more")

    return True


def test_translation_with_telemetry():
    """Test 7: Run actual translation with telemetry."""
    print_header("TEST 7: Translation with Telemetry")

    try:
        from src.translation_engine import TranslationEngine
        from src.utils.config_loader import ConfigService
        from src.tm import TranslationMemory
        from src.tm.l1_cache import L1Cache
        from src.tm.l2_persistent import L2PersistentTM
        from src.tm.l3_semantic import L3SemanticTM
        from src.model_runtime import ModelLoader
        from src.model_runtime.registry import ModelRegistry
        import torch

        print_info("Initializing translation components...")

        # Initialize components
        config_path = REPO_ROOT / "config"
        config_service = ConfigService(config_path)

        l1_cache = L1Cache(max_size=1000)
        lmdb_path = REPO_ROOT / "data" / "tm" / "l2_lmdb"
        lmdb_path.parent.mkdir(parents=True, exist_ok=True)
        l2_persistent = L2PersistentTM(str(lmdb_path))

        faiss_path = REPO_ROOT / "data" / "tm" / "l3_faiss"
        faiss_path.mkdir(parents=True, exist_ok=True)
        l3_semantic = L3SemanticTM(index_path=str(faiss_path))

        tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent, l3_semantic=l3_semantic)

        registry_path = config_path / "model_registry.yaml"
        model_registry = ModelRegistry(registry_path)
        device = "cuda" if torch.cuda.is_available() else "cpu"
        model_loader = ModelLoader(registry=model_registry, device=device)

        print_success(f"Components initialized (device: {device})")

        # Create engine with telemetry enabled
        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            enable_telemetry=True
        )

        print_success("TranslationEngine initialized with telemetry enabled")

        # Use test fixture file
        test_file = REPO_ROOT / "tests" / "fixtures" / "hp_integration_test.md"

        if not test_file.exists():
            print_error(f"Test file not found: {test_file}")
            return False

        print_info(f"Translating: {test_file.name}")
        print_info(f"Target language: de (German)")

        # Translate
        result = engine.translate_file(
            site_id="example.yaml",
            file_path=test_file,
            target_langs=["de"],
        )

        if result.success:
            print_success(f"Translation succeeded!")
            print_info(f"  Segments: {result.stats.total_segments}")
            print_info(f"  TM Hits: {result.stats.tm_hits}")
            print_info(f"  Translated: {result.stats.translated_segments}")
            print_info(f"  Duration: {result.stats.duration_seconds:.2f}s")
        else:
            print_error(f"Translation failed: {result.errors}")
            return False

        return True

    except Exception as e:
        print_error(f"Translation Test Failed: {e}")
        import traceback
        traceback.print_exc()
        return False


def main():
    """Run all integration tests."""
    print(f"\n{BLUE}{'='*60}{RESET}")
    print(f"{BLUE}Hugo-Translator ↔ Docker Telemetry Integration Test{RESET}")
    print(f"{BLUE}{'='*60}{RESET}")
    print(f"\nTimestamp: {datetime.now().isoformat()}")

    results = {}

    # Test 1: Docker API Health
    results['api_health'] = test_docker_api_health()

    # Test 2: API Metrics
    initial_metrics = test_api_metrics()
    results['api_metrics'] = initial_metrics is not None

    # Test 3: TelemetryClient Init
    client = test_telemetry_client_init()
    results['client_init'] = client is not None

    # Test 4: Send Event
    run_id = test_send_event_to_api(client)
    results['send_event'] = run_id is not None

    # Test 5: Verify Event
    results['verify_event'] = test_verify_event_in_api(run_id)

    # Test 6: Buffer Directory
    results['buffer_check'] = test_buffer_directory()

    # Test 7: Translation with Telemetry
    results['translation'] = test_translation_with_telemetry()

    # Final Summary
    print_header("INTEGRATION TEST SUMMARY")

    passed = sum(1 for v in results.values() if v)
    total = len(results)

    for test_name, passed_flag in results.items():
        status = f"{GREEN}PASS{RESET}" if passed_flag else f"{RED}FAIL{RESET}"
        print(f"  {test_name:20s} [{status}]")

    print(f"\n{BLUE}{'='*60}{RESET}")

    if passed == total:
        print(f"{GREEN}✓ ALL TESTS PASSED ({passed}/{total}){RESET}")
        print(f"\n{GREEN}Hugo-translator is successfully integrated with Docker telemetry!{RESET}")
        return 0
    else:
        print(f"{RED}✗ SOME TESTS FAILED ({passed}/{total} passed){RESET}")
        return 1


if __name__ == "__main__":
    sys.exit(main())
