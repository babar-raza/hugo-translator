#!/usr/bin/env python3
"""
Load Testing CLI for Hugo Translation System.

Run load tests to measure system performance under concurrent workloads.
"""
from __future__ import annotations

import argparse
import json
import logging
import sys
import tempfile
from pathlib import Path
from typing import List, TYPE_CHECKING

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

if TYPE_CHECKING:
    from tests.load.test_concurrent_translations import (
        LoadTestConfig,
        LoadTestRunner,
        LoadTestMetrics,
    )

# Setup logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)


def _load_test_classes():
    """Import load test classes lazily to allow --help without pytest."""
    from tests.load.test_concurrent_translations import (
        LoadTestConfig,
        LoadTestRunner,
        LoadTestMetrics,
    )
    return LoadTestConfig, LoadTestRunner, LoadTestMetrics


def create_sample_files(num_files: int = 3) -> List[Path]:
    """
    Create sample Hugo markdown files for testing.

    Args:
        num_files: Number of sample files to create

    Returns:
        List of paths to created files
    """
    files = []
    temp_dir = Path(tempfile.gettempdir()) / "hugo_load_test"
    temp_dir.mkdir(exist_ok=True)

    for i in range(num_files):
        file_path = temp_dir / f"sample_{i}.md"

        # Vary content size
        if i == 0:
            # Small file
            content = f"""---
title: "Load Test Sample {i}"
---

# Sample {i}

This is a small test file for load testing.
"""
        elif i == 1:
            # Medium file
            content = f"""---
title: "Load Test Sample {i}"
description: "Medium-sized test file"
---

# Sample {i}

## Section 1

Lorem ipsum dolor sit amet, consectetur adipiscing elit.
Sed do eiusmod tempor incididunt ut labore et dolore magna aliqua.

## Section 2

Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris
nisi ut aliquip ex ea commodo consequat.
"""
        else:
            # Large file
            sections = ""
            for j in range(5):
                sections += f"""
## Section {j+1}

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam,
quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.

### Subsection {j+1}.1

Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore
eu fugiat nulla pariatur.

### Subsection {j+1}.2

Excepteur sint occaecat cupidatat non proident, sunt in culpa qui officia
deserunt mollit anim id est laborum.

- List item 1
- List item 2
- List item 3
"""

            content = f"""---
title: "Load Test Sample {i}"
description: "Large test file with multiple sections"
tags: ["load-test", "performance"]
---

# Sample {i}

{sections}
"""

        file_path.write_text(content, encoding="utf-8")
        files.append(file_path)

    logger.info(f"Created {len(files)} sample files in {temp_dir}")
    return files


def format_metrics_table(summary: dict) -> str:
    """
    Format metrics summary as a readable table.

    Args:
        summary: Metrics summary dictionary

    Returns:
        Formatted table string
    """
    lines = []
    lines.append("\n" + "="*70)
    lines.append(" LOAD TEST RESULTS ".center(70, "="))
    lines.append("="*70)

    # Request Stats
    lines.append("\n[ Request Statistics ]")
    lines.append(f"  Total Requests:        {summary['total_requests']}")
    lines.append(f"  Successful:            {summary['successful_requests']}")
    lines.append(f"  Failed:                {summary['failed_requests']}")
    lines.append(f"  Success Rate:          {summary['success_rate']:.1f}%")

    # Throughput
    lines.append("\n[ Throughput ]")
    lines.append(f"  Duration:              {summary['duration_seconds']:.2f}s")
    lines.append(f"  Requests/sec:          {summary['throughput_rps']:.2f}")

    # Latency
    lines.append("\n[ Latency (seconds) ]")
    lines.append(f"  Mean:                  {summary['latency_mean']:.3f}s")
    lines.append(f"  Median (p50):          {summary['latency_p50']:.3f}s")
    lines.append(f"  p95:                   {summary['latency_p95']:.3f}s")
    lines.append(f"  p99:                   {summary['latency_p99']:.3f}s")
    lines.append(f"  Min:                   {summary['latency_min']:.3f}s")
    lines.append(f"  Max:                   {summary['latency_max']:.3f}s")

    # TM Stats
    lines.append("\n[ Translation Memory ]")
    lines.append(f"  TM Hit Rate:           {summary['tm_hit_rate']:.1f}%")
    lines.append(f"  L1 Cache Hits:         {summary['l1_hits']}")
    lines.append(f"  L2 Exact Hits:         {summary['l2_hits']}")
    lines.append(f"  L3 Semantic Hits:      {summary['l3_hits']}")

    # Resources
    lines.append("\n[ Resource Usage ]")
    lines.append(f"  Peak Memory:           {summary['peak_memory_mb']:.1f} MB")
    lines.append(f"  Avg CPU:               {summary['avg_cpu_percent']:.1f}%")

    # Errors
    lines.append("\n[ Errors ]")
    lines.append(f"  Total Errors:          {summary['error_count']}")
    lines.append(f"  Unique Errors:         {summary['unique_errors']}")

    lines.append("\n" + "="*70 + "\n")

    return "\n".join(lines)


def save_report(metrics: LoadTestMetrics, output_path: Path):
    """
    Save load test report to file.

    Args:
        metrics: Test metrics
        output_path: Path to save report
    """
    summary = metrics.get_summary()

    # Create detailed report
    report = {
        "summary": summary,
        "raw_latencies": metrics.latencies[:100],  # Sample first 100
        "errors": list(set(metrics.errors))[:10],  # Sample unique errors
    }

    # Save as JSON
    if output_path.suffix == ".json":
        with open(output_path, "w") as f:
            json.dump(report, f, indent=2)
        logger.info(f"Report saved to {output_path}")

    # Save as Markdown
    elif output_path.suffix == ".md":
        with open(output_path, "w") as f:
            f.write("# Load Test Report\n\n")
            f.write(f"**Date:** {summary['duration_seconds']}\n\n")

            f.write("## Summary\n\n")
            f.write(format_metrics_table(summary))

            if metrics.errors:
                f.write("\n## Sample Errors\n\n")
                for i, error in enumerate(list(set(metrics.errors))[:5], 1):
                    f.write(f"{i}. `{error}`\n")

            f.write("\n## Recommendations\n\n")

            # Add automated recommendations
            if summary["success_rate"] < 95:
                f.write("- **Low success rate**: Investigate errors and system stability\n")

            if summary["latency_p99"] > 30:
                f.write("- **High p99 latency**: Consider scaling or optimization\n")

            if summary["tm_hit_rate"] < 50:
                f.write("- **Low TM hit rate**: Expand translation memory database\n")

            if summary["peak_memory_mb"] > 2000:
                f.write("- **High memory usage**: Monitor for memory leaks\n")

        logger.info(f"Report saved to {output_path}")

    else:
        logger.error(f"Unsupported output format: {output_path.suffix}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Load test the Hugo Translation System",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic load test with 10 workers for 60 seconds
  python scripts/load_test.py --workers 10 --duration 60

  # Load test with custom files
  python scripts/load_test.py --workers 5 --duration 30 --files content/*.md

  # Heavy load test with report
  python scripts/load_test.py --workers 20 --duration 120 --output reports/load_test.json

  # Test TM performance (warm cache)
  python scripts/load_test.py --workers 5 --duration 60 --no-force

  # Test without TM (force retranslation)
  python scripts/load_test.py --workers 3 --duration 30 --force
        """
    )

    parser.add_argument(
        "--workers",
        type=int,
        default=10,
        help="Number of concurrent workers (default: 10)"
    )

    parser.add_argument(
        "--duration",
        type=int,
        default=60,
        help="Test duration in seconds (default: 60)"
    )

    parser.add_argument(
        "--files",
        nargs="+",
        type=Path,
        help="Test files to use (default: auto-generated)"
    )

    parser.add_argument(
        "--langs",
        nargs="+",
        default=["es", "fr"],
        help="Target languages (default: es fr)"
    )

    parser.add_argument(
        "--ramp-up",
        type=int,
        default=0,
        help="Ramp-up time in seconds (default: 0)"
    )

    parser.add_argument(
        "--force",
        action="store_true",
        help="Force retranslation (disable TM)"
    )

    parser.add_argument(
        "--output",
        type=Path,
        help="Output report path (.json or .md)"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Enable verbose logging"
    )

    args = parser.parse_args()

    # Setup logging
    if args.verbose:
        logging.getLogger().setLevel(logging.DEBUG)

    # Get test files
    if args.files:
        test_files = [Path(f) for f in args.files if Path(f).exists()]
        if not test_files:
            logger.error("No valid test files found")
            return 1
    else:
        # Create sample files
        test_files = create_sample_files(num_files=3)

    logger.info(f"Using {len(test_files)} test files")

    # Create config
    LoadTestConfig, LoadTestRunner, LoadTestMetrics = _load_test_classes()

    config = LoadTestConfig(
        num_workers=args.workers,
        duration_seconds=args.duration,
        test_files=test_files,
        target_langs=args.langs,
        ramp_up_seconds=args.ramp_up,
        enable_tm=not args.force,
        force_retranslation=args.force,
    )

    # Run load test
    logger.info("Starting load test...")
    runner = LoadTestRunner(config)

    try:
        metrics = runner.run()
    except KeyboardInterrupt:
        logger.warning("Load test interrupted by user")
        return 130  # SIGINT exit code
    except Exception as e:
        logger.error(f"Load test failed: {e}")
        return 1

    # Display results
    summary = metrics.get_summary()
    print(format_metrics_table(summary))

    # Save report if requested
    if args.output:
        save_report(metrics, args.output)

    # Exit with error if success rate is too low
    if summary["success_rate"] < 50:
        logger.error("Load test failed: success rate < 50%")
        return 1

    logger.info("Load test completed successfully")
    return 0


if __name__ == "__main__":
    sys.exit(main())
