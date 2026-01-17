#!/usr/bin/env python3
"""
Comprehensive Worker Testing Script.

Tests both autonomous workers in oneshot mode to verify functionality
before setting up scheduled daemon mode.
"""

import argparse
import logging
import os
import sys
import time
from pathlib import Path

# Add project root to path
SCRIPT_DIR = Path(__file__).parent.resolve()
PROJECT_ROOT = SCRIPT_DIR.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def test_content_translation_worker(site_id="kb.aspose.net", device="cuda", dry_run=False):
    """
    Test Autonomous Content Translation Worker.

    Args:
        site_id: Site to test with (default: kb.aspose.net)
        device: Device to use (cuda, cpu, auto)
        dry_run: If True, only validate setup without running

    Returns:
        bool: True if test passed, False otherwise
    """
    print("=" * 80)
    print("TEST 1: Autonomous Content Translation Worker")
    print("=" * 80)
    print(f"Site: {site_id}")
    print(f"Device: {device}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE TEST'}")
    print()

    if dry_run:
        print("DRY RUN: Validating worker can be imported...")
        try:
            from src.workers.autonomous_content_translation_worker import (
                AutonomousContentTranslationWorker,
                AutonomousWorkerConfig
            )
            print("[OK] Worker module imported successfully")

            # Validate config
            config = AutonomousWorkerConfig(
                site=site_id,
                mode="oneshot",
                device=device,
                max_sites_per_run=1
            )
            print("[OK] Worker configuration created successfully")

            worker = AutonomousContentTranslationWorker(config)
            print("[OK] Worker instance created successfully")

            print("\n[PASS] Content Translation Worker validation succeeded")
            return True

        except Exception as e:
            print(f"\n[FAIL] Content Translation Worker validation failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    else:
        print("LIVE TEST: Running content translation worker in oneshot mode...")
        print("Note: This will attempt actual translation with limited scope")
        print()

        try:
            from src.workers.autonomous_content_translation_worker import (
                AutonomousContentTranslationWorker,
                AutonomousWorkerConfig
            )

            # Create minimal config for testing
            config = AutonomousWorkerConfig(
                site=site_id,
                mode="oneshot",
                device=device,
                max_sites_per_run=1,  # Only process one site
                max_gpu_memory_percent=50  # Conservative for testing
            )

            worker = AutonomousContentTranslationWorker(config)

            print("Setting up worker...")
            worker.setup()

            print("Running translation (oneshot)...")
            start_time = time.time()
            worker.run()
            elapsed = time.time() - start_time

            print(f"\n[OK] Worker completed in {elapsed:.1f}s")
            print("[PASS] Content Translation Worker test succeeded")
            return True

        except Exception as e:
            print(f"\n[FAIL] Content Translation Worker test failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def test_tm_improvement_worker(device="cuda", dry_run=False):
    """
    Test TM Improvement Worker.

    Args:
        device: Device to use (cuda, cpu, auto)
        dry_run: If True, only validate setup without running

    Returns:
        bool: True if test passed, False otherwise
    """
    print("\n" + "=" * 80)
    print("TEST 2: TM Improvement Worker")
    print("=" * 80)
    print(f"Device: {device}")
    print(f"Mode: {'DRY RUN' if dry_run else 'LIVE TEST'}")
    print()

    if dry_run:
        print("DRY RUN: Validating worker can be imported...")
        try:
            from src.workers.tm_improvement_worker import (
                TMImprovementWorker,
                TMImprovementWorkerConfig
            )
            print("[OK] Worker module imported successfully")

            # Validate config
            config = TMImprovementWorkerConfig(
                mode="oneshot",
                device=device,
                candidates_per_run=5,  # Small batch for testing
                max_llm_calls_per_run=10
            )
            print("[OK] Worker configuration created successfully")

            worker = TMImprovementWorker(config)
            print("[OK] Worker instance created successfully")

            print("\n[PASS] TM Improvement Worker validation succeeded")
            return True

        except Exception as e:
            print(f"\n[FAIL] TM Improvement Worker validation failed: {e}")
            import traceback
            traceback.print_exc()
            return False

    else:
        print("LIVE TEST: Running TM improvement worker in oneshot mode...")
        print("Note: This requires Ollama to be running with llama2 model")
        print()

        try:
            from src.workers.tm_improvement_worker import (
                TMImprovementWorker,
                TMImprovementWorkerConfig
            )

            # Create minimal config for testing
            config = TMImprovementWorkerConfig(
                mode="oneshot",
                device=device,
                candidates_per_run=5,  # Small batch for testing
                max_llm_calls_per_run=10,
                max_seconds_per_run=120,  # 2 minute timeout
                max_gpu_memory_percent=50,  # Conservative for testing
                llm_provider="ollama",
                llm_model="llama2"
            )

            worker = TMImprovementWorker(config)

            print("Setting up worker...")
            worker.setup()

            print("Running TM improvement (oneshot)...")
            start_time = time.time()
            worker.run()
            elapsed = time.time() - start_time

            print(f"\n[OK] Worker completed in {elapsed:.1f}s")
            print("[PASS] TM Improvement Worker test succeeded")
            return True

        except Exception as e:
            print(f"\n[FAIL] TM Improvement Worker test failed: {e}")
            import traceback
            traceback.print_exc()
            return False


def main():
    """Main test orchestrator."""
    parser = argparse.ArgumentParser(
        description="Test autonomous workers before deployment",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Dry run (validation only)
  python scripts/test_workers.py --dry-run

  # Live test with default site
  python scripts/test_workers.py --live

  # Live test with specific site and CPU
  python scripts/test_workers.py --live --site docs.aspose.net --device cpu

  # Test only content worker
  python scripts/test_workers.py --live --content-only

  # Test only TM worker
  python scripts/test_workers.py --live --tm-only
        """
    )

    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Validation only (no actual execution)"
    )

    parser.add_argument(
        "--live",
        action="store_true",
        help="Run live tests with actual execution"
    )

    parser.add_argument(
        "--site",
        type=str,
        default="kb.aspose.net",
        help="Site ID for content worker test (default: kb.aspose.net)"
    )

    parser.add_argument(
        "--device",
        type=str,
        default="cuda",
        choices=["cuda", "cpu", "auto"],
        help="Device for inference (default: cuda)"
    )

    parser.add_argument(
        "--content-only",
        action="store_true",
        help="Test only content translation worker"
    )

    parser.add_argument(
        "--tm-only",
        action="store_true",
        help="Test only TM improvement worker"
    )

    parser.add_argument(
        "--log-level",
        type=str,
        default="INFO",
        choices=["DEBUG", "INFO", "WARNING", "ERROR"],
        help="Logging level (default: INFO)"
    )

    args = parser.parse_args()

    # Configure logging
    logging.basicConfig(
        level=getattr(logging, args.log_level),
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S"
    )

    # Validate arguments
    if not args.dry_run and not args.live:
        print("ERROR: Must specify either --dry-run or --live")
        parser.print_help()
        sys.exit(1)

    dry_run = args.dry_run

    print("=" * 80)
    print("AUTONOMOUS WORKERS TEST SUITE")
    print("=" * 80)
    print(f"Mode: {'DRY RUN (validation only)' if dry_run else 'LIVE TEST (actual execution)'}")
    print(f"Device: {args.device}")
    print(f"Working Directory: {os.getcwd()}")
    print()

    # Run tests
    results = {}

    if not args.tm_only:
        results["content_worker"] = test_content_translation_worker(
            site_id=args.site,
            device=args.device,
            dry_run=dry_run
        )

    if not args.content_only:
        results["tm_worker"] = test_tm_improvement_worker(
            device=args.device,
            dry_run=dry_run
        )

    # Summary
    print("\n" + "=" * 80)
    print("TEST SUMMARY")
    print("=" * 80)

    for test_name, passed in results.items():
        status = "[PASS]" if passed else "[FAIL]"
        print(f"{status} - {test_name}")

    all_passed = all(results.values())

    print()
    if all_passed:
        print("[SUCCESS] All tests passed! Workers are ready for deployment.")
        sys.exit(0)
    else:
        print("[ERROR] Some tests failed. Review errors above.")
        sys.exit(1)


if __name__ == "__main__":
    main()
