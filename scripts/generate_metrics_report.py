#!/usr/bin/env python3
"""
Generate metrics report from translation system.

This script collects metrics from the running system and generates
a comprehensive report for monitoring and analysis.
"""

import argparse
import json
import sys
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, Optional

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.observability.metrics import MetricsCollector, get_metrics


def parse_time_duration(duration_str: str) -> int:
    """
    Parse time duration string like '1h', '30m', '24h' into seconds.

    Args:
        duration_str: Duration string (e.g., '1h', '30m', '24h')

    Returns:
        Duration in seconds

    Raises:
        ValueError: If format is invalid
    """
    duration_str = duration_str.strip().lower()

    if duration_str.endswith('h'):
        hours = int(duration_str[:-1])
        return hours * 3600
    elif duration_str.endswith('m'):
        minutes = int(duration_str[:-1])
        return minutes * 60
    elif duration_str.endswith('s'):
        seconds = int(duration_str[:-1])
        return seconds
    elif duration_str.endswith('d'):
        days = int(duration_str[:-1])
        return days * 86400
    else:
        raise ValueError(
            f"Invalid duration format: {duration_str}. "
            "Use format like '1h', '30m', '24h', '7d'"
        )


def format_bytes(bytes_value: float) -> str:
    """Format bytes into human-readable format."""
    for unit in ['B', 'KB', 'MB', 'GB', 'TB']:
        if bytes_value < 1024.0:
            return f"{bytes_value:.2f} {unit}"
        bytes_value /= 1024.0
    return f"{bytes_value:.2f} PB"


def format_duration(seconds: float) -> str:
    """Format seconds into human-readable duration."""
    if seconds < 1:
        return f"{seconds*1000:.2f} ms"
    elif seconds < 60:
        return f"{seconds:.2f} s"
    elif seconds < 3600:
        return f"{seconds/60:.2f} min"
    else:
        return f"{seconds/3600:.2f} hours"


def generate_text_report(stats: Dict[str, Any], metrics: MetricsCollector) -> str:
    """
    Generate human-readable text report.

    Args:
        stats: Statistics summary
        metrics: Metrics collector instance

    Returns:
        Formatted text report
    """
    lines = []

    # Header
    lines.append("=" * 70)
    lines.append("TRANSLATION SYSTEM METRICS REPORT")
    lines.append("=" * 70)
    lines.append(f"Generated: {datetime.now().isoformat()}")
    lines.append(f"Worker ID: {stats['worker_id']}")
    lines.append("")

    # Translation metrics
    lines.append("TRANSLATION METRICS")
    lines.append("-" * 70)
    trans = stats['translations']
    lines.append(f"  Total Translations:     {trans['total']:,}")
    lines.append(f"  Successful:             {trans['success']:,}")
    lines.append(f"  Failed:                 {trans['failed']:,}")
    lines.append(f"  Success Rate:           {trans['success_rate']:.2%}")
    lines.append("")

    # TM metrics
    lines.append("TRANSLATION MEMORY METRICS")
    lines.append("-" * 70)
    tm = stats['tm']
    lines.append(f"  Total Lookups:          {tm['lookups']:,}")
    lines.append(f"  L1 Cache Hits:          {tm['l1_hits']:,}")
    lines.append(f"  L2 Exact Hits:          {tm['l2_hits']:,}")
    lines.append(f"  L3 Semantic Hits:       {tm['l3_hits']:,}")
    lines.append(f"  Total Hits:             {tm['total_hits']:,}")
    lines.append(f"  Misses:                 {tm['misses']:,}")
    lines.append(f"  Hit Rate:               {tm['hit_rate']:.2%}")
    lines.append("")

    # Queue metrics
    lines.append("QUEUE METRICS")
    lines.append("-" * 70)
    queue = stats['queue']
    lines.append(f"  Current Queue Depth:    {queue['depth']:,}")
    lines.append(f"  Active Jobs:            {queue['active_jobs']:,}")
    lines.append("")

    # Performance metrics
    lines.append("PERFORMANCE METRICS")
    lines.append("-" * 70)
    perf = stats['performance']['translation_duration']
    if perf['count'] > 0:
        lines.append(f"  Translation Operations: {perf['count']:,}")
        lines.append(f"  Mean Duration:          {format_duration(perf['mean'])}")
        lines.append(f"  Min Duration:           {format_duration(perf['min'])}")
        lines.append(f"  Max Duration:           {format_duration(perf['max'])}")
        lines.append(f"  Total Duration:         {format_duration(perf['sum'])}")
    else:
        lines.append("  No translation operations recorded")
    lines.append("")

    # System recommendations
    lines.append("RECOMMENDATIONS")
    lines.append("-" * 70)
    recommendations = []

    if trans['success_rate'] < 0.9 and trans['total'] > 10:
        recommendations.append(
            f"  - Success rate ({trans['success_rate']:.1%}) is below 90%. "
            "Check error logs."
        )

    if tm['hit_rate'] < 0.3 and tm['lookups'] > 100:
        recommendations.append(
            f"  - TM hit rate ({tm['hit_rate']:.1%}) is below 30%. "
            "Consider building/updating TM index."
        )

    if queue['depth'] > 1000:
        recommendations.append(
            f"  - Queue depth ({queue['depth']}) is high. "
            "Consider adding more workers."
        )

    if perf['count'] > 0 and perf['mean'] > 5.0:
        recommendations.append(
            f"  - Average translation time ({format_duration(perf['mean'])}) "
            "is high. Check model performance."
        )

    if not recommendations:
        lines.append("  System is operating within normal parameters.")
    else:
        for rec in recommendations:
            lines.append(rec)

    lines.append("")
    lines.append("=" * 70)

    return "\n".join(lines)


def generate_json_report(stats: Dict[str, Any], metrics: MetricsCollector) -> str:
    """
    Generate JSON report.

    Args:
        stats: Statistics summary
        metrics: Metrics collector instance

    Returns:
        JSON formatted report
    """
    report = {
        "generated_at": datetime.now().isoformat(),
        "worker_id": stats['worker_id'],
        "summary": stats,
        "all_metrics": metrics.get_all(),
    }

    return json.dumps(report, indent=2)


def generate_prometheus_export(metrics: MetricsCollector) -> str:
    """
    Generate Prometheus-format metrics export.

    Args:
        metrics: Metrics collector instance

    Returns:
        Prometheus formatted metrics
    """
    return metrics.export_prometheus()


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Generate metrics report from translation system",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate report for last hour
  python scripts/generate_metrics_report.py --since 1h

  # Generate report for last 24 hours in JSON format
  python scripts/generate_metrics_report.py --since 24h --format json

  # Export Prometheus metrics
  python scripts/generate_metrics_report.py --format prometheus

  # Save report to file
  python scripts/generate_metrics_report.py --since 24h --output report.txt
        """
    )

    parser.add_argument(
        "--since",
        type=str,
        default="1h",
        help="Time window for report (e.g., '1h', '24h', '7d'). Default: 1h"
    )

    parser.add_argument(
        "--format",
        choices=["text", "json", "prometheus"],
        default="text",
        help="Output format. Default: text"
    )

    parser.add_argument(
        "--output",
        "-o",
        type=str,
        help="Output file path. If not specified, prints to stdout"
    )

    parser.add_argument(
        "--worker-id",
        type=str,
        help="Specific worker ID to report on. If not specified, uses global metrics"
    )

    args = parser.parse_args()

    try:
        # Parse time duration
        seconds = parse_time_duration(args.since)
        since_time = datetime.now() - timedelta(seconds=seconds)

        # Get metrics collector
        # In production, this would connect to running system
        # For now, we'll use the global instance or create a new one
        if args.worker_id:
            metrics = MetricsCollector(worker_id=args.worker_id)
        else:
            metrics = get_metrics()

        # Generate report based on format
        if args.format == "text":
            stats = metrics.get_stats_summary()
            report = generate_text_report(stats, metrics)
        elif args.format == "json":
            stats = metrics.get_stats_summary()
            report = generate_json_report(stats, metrics)
        elif args.format == "prometheus":
            report = generate_prometheus_export(metrics)
        else:
            print(f"Error: Unknown format: {args.format}", file=sys.stderr)
            return 1

        # Output report
        if args.output:
            output_path = Path(args.output)
            output_path.parent.mkdir(parents=True, exist_ok=True)
            output_path.write_text(report)
            print(f"Report written to: {output_path}")
        else:
            print(report)

        return 0

    except ValueError as e:
        print(f"Error: {e}", file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("\nInterrupted by user", file=sys.stderr)
        return 130
    except Exception as e:
        print(f"Unexpected error: {e}", file=sys.stderr)
        import traceback
        traceback.print_exc()
        return 1


if __name__ == "__main__":
    sys.exit(main())
