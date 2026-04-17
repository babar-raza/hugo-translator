#!/usr/bin/env python3
"""
Generate Performance Baseline Report

Reads benchmark JSON and generates a markdown report for documentation.
"""

import argparse
import json
import sys
from pathlib import Path


def generate_markdown_report(data: dict) -> str:
    """Generate markdown report from benchmark data."""
    lines = []

    lines.append("# Performance Baseline Report\n")
    lines.append(f"**Generated:** {data['timestamp']}\n")

    # Hardware section
    lines.append("## Hardware Configuration\n")
    hw = data['hardware']
    lines.append(f"- **Device:** {hw['device']}")
    lines.append(f"- **CPUs:** {hw['cpu_count']}")
    lines.append(f"- **RAM:** {hw['ram_gb']:.1f}GB")
    if hw['gpu_available']:
        lines.append(f"- **GPU:** {hw['gpu_name']}\n")
    else:
        lines.append("")

    # TM Lookups
    lines.append("## Translation Memory Performance\n")
    tm = data['benchmarks']['tm_lookups']
    lines.append(f"**Iterations:** {tm['iterations']}\n")

    lines.append("### L1 Cache (Warm)")
    l1 = tm['layers']['L1']
    lines.append(f"- Mean: {l1['mean_ms']:.3f}ms")
    lines.append(f"- P95: {l1['p95_ms']:.3f}ms")
    lines.append(f"- P99: {l1['p99_ms']:.3f}ms")
    lines.append(f"- Throughput: **{l1['lookups_per_sec']:.0f} lookups/sec**\n")

    lines.append("### L2 Persistent (Cold)")
    l2 = tm['layers']['L2']
    lines.append(f"- Mean: {l2['mean_ms']:.3f}ms")
    lines.append(f"- P95: {l2['p95_ms']:.3f}ms")
    lines.append(f"- P99: {l2['p99_ms']:.3f}ms")
    lines.append(f"- Throughput: **{l2['lookups_per_sec']:.0f} lookups/sec**\n")

    # Segment Translation
    lines.append("## Segment Translation Pipeline\n")
    seg = data['benchmarks']['segment_translation']
    lines.append(f"**Segments:** {seg['segment_count']}")
    lines.append(f"**Iterations:** {seg['iterations']}\n")

    lines.append("| Stage | Mean | P95 |")
    lines.append("|-------|------|-----|")
    lines.append(f"| Parse | {seg['parse']['mean_ms']:.3f}ms | {seg['parse']['p95_ms']:.3f}ms |")
    lines.append(f"| Extract | {seg['extract']['mean_ms']:.3f}ms | {seg['extract']['p95_ms']:.3f}ms |")
    lines.append(f"| Reconstruct | {seg['reconstruct']['mean_ms']:.3f}ms | {seg['reconstruct']['p95_ms']:.3f}ms |")
    lines.append(f"| **Total** | **{seg['total_pipeline']['mean_ms']:.3f}ms** | - |\n")

    # File Sizes
    lines.append("## File Size Performance\n")
    sizes = data['benchmarks']['file_sizes']
    lines.append("| Size | Segments | Mean Time | ms/segment |")
    lines.append("|------|----------|-----------|------------|")
    for size in ['small', 'medium', 'large']:
        s = sizes[size]
        lines.append(f"| {size.capitalize()} | {s['segment_count']} | {s['mean_ms']:.2f}ms | {s['ms_per_segment']:.2f}ms |")
    lines.append("")

    # Memory
    lines.append("## Memory Usage\n")
    mem = data['benchmarks']['memory_usage']
    lines.append(f"- **Baseline:** {mem['baseline_mb']:.1f}MB")
    lines.append(f"- **With 10k TM entries:** {mem['with_tm_mb']:.1f}MB (+{mem['tm_overhead_mb']:.1f}MB)")
    lines.append(f"- **After 1k parses:** {mem['after_parsing_mb']:.1f}MB")
    lines.append(f"- **Peak:** {mem['peak_mb']:.1f}MB\n")

    # Performance Targets
    lines.append("## Performance Targets\n")
    lines.append("| Metric | Target | Actual | Status |")
    lines.append("|--------|--------|--------|--------|")

    l1_throughput = tm['layers']['L1']['lookups_per_sec']
    lines.append(f"| L1 Lookups/sec | >10,000 | {l1_throughput:.0f} | {'✓' if l1_throughput > 10000 else '✗'} |")

    l2_throughput = tm['layers']['L2']['lookups_per_sec']
    lines.append(f"| L2 Lookups/sec | >1,000 | {l2_throughput:.0f} | {'✓' if l2_throughput > 1000 else '✗'} |")

    pipeline_time = seg['total_pipeline']['mean_ms']
    lines.append(f"| Pipeline time | <10ms | {pipeline_time:.2f}ms | {'✓' if pipeline_time < 10 else '✗'} |")

    peak_mem = mem['peak_mb']
    lines.append(f"| Peak memory | <500MB | {peak_mem:.0f}MB | {'✓' if peak_mem < 500 else '✗'} |")

    return "\n".join(lines)


def main():
    """Main execution."""
    parser = argparse.ArgumentParser(description="Generate baseline report from JSON")
    parser.add_argument("--baseline", type=Path, required=True, help="Baseline JSON file")
    parser.add_argument("--output", type=Path, help="Output markdown file (optional)")

    args = parser.parse_args()

    if not args.baseline.exists():
        print(f"Error: Baseline file not found: {args.baseline}")
        return 1

    # Load data
    with open(args.baseline) as f:
        data = json.load(f)

    # Generate report
    report = generate_markdown_report(data)

    # Output
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, 'w') as f:
            f.write(report)
        print(f"Report saved to: {args.output}")
    else:
        print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
