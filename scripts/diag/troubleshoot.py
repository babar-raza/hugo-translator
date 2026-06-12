#!/usr/bin/env python3
"""
Troubleshooting Script.

Automated diagnostics and troubleshooting for common issues.
"""

import argparse
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.observability.metrics import get_metrics
from src.orchestration.health_monitor import HealthMonitor


def diagnose_slow_translations():
    """Diagnose slow translation performance."""
    print("Diagnosing slow translations...")
    print("")

    monitor = HealthMonitor()
    metrics = get_metrics()

    # Check TM hit rate
    hit_rate = metrics.get_tm_hit_rate()
    print(f"✓ TM Hit Rate: {hit_rate:.1%}")
    if hit_rate < 0.3:
        print("  ⚠ Low TM hit rate may cause slow translations")
        print("  → Run: python scripts/tm/build_l3_index.py --force")
    print("")

    # Check model performance
    stats = metrics.get_stats_summary()
    perf = stats["performance"]["translation_duration"]
    if perf["count"] > 0:
        print(f"✓ Average Translation Time: {perf['mean']:.2f}s")
        if perf["mean"] > 5.0:
            print("  ⚠ Translations are slow")
            print("  → Check if GPU is being used")
            print("  → Consider using faster model")
    print("")

    # Check queue depth
    queue = stats["queue"]["depth"]
    print(f"✓ Queue Depth: {queue}")
    if queue > 100:
        print("  ⚠ High queue depth indicates backlog")
        print("  → Consider adding more workers")
    print("")


def diagnose_oom_errors():
    """Diagnose out-of-memory errors."""
    print("Diagnosing memory issues...")
    print("")

    monitor = HealthMonitor()

    # Check memory usage
    result = monitor.check_memory_usage()
    print(f"✓ Memory Status: {result.message}")
    if result.details:
        print(f"  Used: {result.details.get('used_percent', 0):.1f}%")
    print("")

    print("Recommendations:")
    print("  1. Reduce max_workers in config")
    print("  2. Reduce model_cache_size")
    print("  3. Use smaller models")
    print("  4. Add more RAM")
    print("")


def diagnose_cache_misses():
    """Diagnose TM cache misses."""
    print("Diagnosing TM cache misses...")
    print("")

    metrics = get_metrics()
    stats = metrics.get_stats_summary()

    tm = stats["tm"]
    print(f"✓ TM Lookups: {tm['lookups']}")
    print(f"✓ L1 Hits: {tm['l1_hits']}")
    print(f"✓ L2 Hits: {tm['l2_hits']}")
    print(f"✓ L3 Hits: {tm['l3_hits']}")
    print(f"✓ Misses: {tm['misses']}")
    print(f"✓ Hit Rate: {tm['hit_rate']:.1%}")
    print("")

    if tm["hit_rate"] < 0.3:
        print("Recommendations:")
        print("  1. Rebuild L3 index: python scripts/tm/build_l3_index.py")
        print("  2. Check TM database: python scripts/inspect_cache.py")
        print("  3. Verify normalization settings")
    print("")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Troubleshoot translation system issues",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Symptoms:
  slow_translations - Translations taking too long
  oom_errors       - Out of memory errors
  cache_misses     - Low TM hit rate

Examples:
  python scripts/troubleshoot.py --symptom slow_translations
  python scripts/troubleshoot.py --symptom oom_errors
  python scripts/troubleshoot.py --symptom cache_misses
        """,
    )

    parser.add_argument(
        "--symptom",
        choices=["slow_translations", "oom_errors", "cache_misses"],
        required=True,
        help="Symptom to diagnose",
    )

    args = parser.parse_args()

    print("=" * 70)
    print("TRANSLATION SYSTEM TROUBLESHOOTING")
    print("=" * 70)
    print("")

    if args.symptom == "slow_translations":
        diagnose_slow_translations()
    elif args.symptom == "oom_errors":
        diagnose_oom_errors()
    elif args.symptom == "cache_misses":
        diagnose_cache_misses()

    return 0


if __name__ == "__main__":
    sys.exit(main())
