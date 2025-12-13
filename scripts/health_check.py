#!/usr/bin/env python3
"""
Health Check Script.

Performs comprehensive health check of the translation system
and reports status for monitoring and alerting.
"""

import argparse
import json
import sys
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.orchestration.health_monitor import HealthMonitor, HealthStatus


def format_status_text(overall_status: HealthStatus, results, verbose: bool = False):
    """
    Format health check results as text.

    Args:
        overall_status: Overall health status
        results: List of health check results
        verbose: Include detailed information

    Returns:
        Formatted text output
    """
    lines = []

    # Header
    lines.append("=" * 70)
    lines.append("TRANSLATION SYSTEM HEALTH CHECK")
    lines.append("=" * 70)

    # Overall status
    status_symbols = {
        HealthStatus.HEALTHY: "✓",
        HealthStatus.DEGRADED: "⚠",
        HealthStatus.UNHEALTHY: "✗"
    }
    symbol = status_symbols.get(overall_status, "?")
    lines.append(f"\nOverall Status: {symbol} {overall_status.value.upper()}")
    lines.append("")

    # Component results
    lines.append("Component Health:")
    lines.append("-" * 70)

    for result in results:
        symbol = status_symbols.get(result.status, "?")
        lines.append(f"  {symbol} {result.component:20s} {result.status.value:10s} - {result.message}")

        if verbose and result.details:
            for key, value in result.details.items():
                lines.append(f"      {key}: {value}")

    lines.append("")
    lines.append("=" * 70)

    # Return code hint
    if overall_status == HealthStatus.HEALTHY:
        lines.append("Status: OK (exit code 0)")
    elif overall_status == HealthStatus.DEGRADED:
        lines.append("Status: DEGRADED (exit code 1)")
    else:
        lines.append("Status: UNHEALTHY (exit code 2)")

    return "\n".join(lines)


def format_status_json(monitor: HealthMonitor):
    """
    Format health check results as JSON.

    Args:
        monitor: Health monitor instance

    Returns:
        JSON formatted output
    """
    status = monitor.export_health_status()
    return json.dumps(status, indent=2)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Health check for translation system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Basic health check
  python scripts/health_check.py

  # Verbose output
  python scripts/health_check.py --verbose

  # JSON output
  python scripts/health_check.py --format json

  # Disable auto-recovery
  python scripts/health_check.py --no-recovery

Exit Codes:
  0 - System is healthy
  1 - System is degraded
  2 - System is unhealthy
        """
    )

    parser.add_argument(
        "--tm-data",
        type=str,
        default="./data/tm",
        help="TM data directory path. Default: ./data/tm"
    )

    parser.add_argument(
        "--format",
        choices=["text", "json"],
        default="text",
        help="Output format. Default: text"
    )

    parser.add_argument(
        "--verbose",
        "-v",
        action="store_true",
        help="Show detailed component information"
    )

    parser.add_argument(
        "--no-recovery",
        action="store_true",
        help="Disable automatic recovery attempts"
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Timeout for health checks in seconds. Default: 5.0"
    )

    args = parser.parse_args()

    # Initialize health monitor
    monitor = HealthMonitor(
        tm_data_dir=Path(args.tm_data),
        timeout=args.timeout,
        enable_auto_recovery=not args.no_recovery
    )

    # Perform health check
    overall_status, results = monitor.check_health()

    # Output results
    if args.format == "json":
        output = format_status_json(monitor)
    else:
        output = format_status_text(overall_status, results, args.verbose)

    print(output)

    # Show recovery history if verbose
    if args.verbose and monitor.recovery_attempts:
        print("\n" + "=" * 70)
        print("RECOVERY ATTEMPTS:")
        print("-" * 70)
        for action in monitor.recovery_attempts:
            success_str = "SUCCESS" if action.success else "FAILED"
            print(f"  [{success_str}] {action.component}: {action.action}")
            print(f"      {action.message}")

    # Return appropriate exit code
    if overall_status == HealthStatus.HEALTHY:
        return 0
    elif overall_status == HealthStatus.DEGRADED:
        return 1
    else:
        return 2


if __name__ == "__main__":
    sys.exit(main())
