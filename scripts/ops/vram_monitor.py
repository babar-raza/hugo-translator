#!/usr/bin/env python3
"""
VRAM Monitoring Script for Hugo Translator E2E Tests

Monitors GPU VRAM utilization during translation runs and produces metrics reports.
"""

import argparse
import json
import signal
import subprocess
import sys
import threading
import time
from datetime import datetime
from pathlib import Path
from typing import Any


class VRAMMonitor:
    """Monitor GPU VRAM usage over time."""

    def __init__(self, interval: float = 2.0, output_file: Path | None = None):
        self.interval = interval
        self.output_file = output_file
        self.samples: list[dict[str, Any]] = []
        self._stop_event = threading.Event()
        self._monitor_thread: threading.Thread | None = None

    def _get_gpu_stats(self) -> dict[str, Any] | None:
        """Get current GPU stats using nvidia-smi."""
        try:
            result = subprocess.run(
                [
                    "nvidia-smi",
                    "--query-gpu=name,memory.total,memory.free,memory.used,utilization.gpu",
                    "--format=csv,noheader,nounits",
                ],
                capture_output=True,
                text=True,
                timeout=5,
            )
            if result.returncode != 0:
                return None

            line = result.stdout.strip()
            parts = [p.strip() for p in line.split(",")]
            if len(parts) >= 5:
                return {
                    "timestamp": datetime.now().isoformat(),
                    "gpu_name": parts[0],
                    "memory_total_mb": float(parts[1]),
                    "memory_free_mb": float(parts[2]),
                    "memory_used_mb": float(parts[3]),
                    "gpu_utilization_pct": float(parts[4]) if parts[4] != "[N/A]" else 0.0,
                }
        except Exception as e:
            print(f"Error getting GPU stats: {e}", file=sys.stderr)
        return None

    def _monitor_loop(self):
        """Background monitoring loop."""
        while not self._stop_event.is_set():
            stats = self._get_gpu_stats()
            if stats:
                self.samples.append(stats)
                if self.output_file:
                    with open(self.output_file, "a") as f:
                        f.write(json.dumps(stats) + "\n")
            self._stop_event.wait(self.interval)

    def start(self):
        """Start background monitoring."""
        if self._monitor_thread is not None:
            return
        self._stop_event.clear()
        self._monitor_thread = threading.Thread(target=self._monitor_loop, daemon=True)
        self._monitor_thread.start()
        print(f"VRAM monitoring started (interval: {self.interval}s)")

    def stop(self):
        """Stop background monitoring."""
        if self._monitor_thread is None:
            return
        self._stop_event.set()
        self._monitor_thread.join(timeout=5)
        self._monitor_thread = None
        print(f"VRAM monitoring stopped ({len(self.samples)} samples collected)")

    def get_stats(self) -> dict[str, Any]:
        """Calculate statistics from collected samples."""
        if not self.samples:
            return {"error": "No samples collected"}

        memory_used = [s["memory_used_mb"] for s in self.samples]
        memory_total = self.samples[0]["memory_total_mb"]

        peak_usage = max(memory_used)
        avg_usage = sum(memory_used) / len(memory_used)
        min_usage = min(memory_used)

        return {
            "gpu_name": self.samples[0]["gpu_name"],
            "memory_total_mb": memory_total,
            "samples_collected": len(self.samples),
            "peak_memory_mb": peak_usage,
            "avg_memory_mb": avg_usage,
            "min_memory_mb": min_usage,
            "peak_utilization_pct": round(peak_usage / memory_total * 100, 2),
            "avg_utilization_pct": round(avg_usage / memory_total * 100, 2),
            "memory_headroom_mb": memory_total - peak_usage,
        }

    def generate_report(self, output_path: Path):
        """Generate a markdown report of VRAM utilization."""
        stats = self.get_stats()

        report = f"""# VRAM Utilization Report

**Generated**: {datetime.now().isoformat()}

## Summary

| Metric | Value |
|--------|-------|
| GPU | {stats.get("gpu_name", "N/A")} |
| Total VRAM | {stats.get("memory_total_mb", "N/A")} MiB |
| Samples Collected | {stats.get("samples_collected", 0)} |
| Monitoring Interval | {self.interval}s |

## Utilization Metrics

| Metric | Value |
|--------|-------|
| Peak Memory Used | {stats.get("peak_memory_mb", "N/A")} MiB |
| Average Memory Used | {stats.get("avg_memory_mb", "N/A"):.1f} MiB |
| Minimum Memory Used | {stats.get("min_memory_mb", "N/A")} MiB |
| Peak Utilization | {stats.get("peak_utilization_pct", "N/A")}% |
| Average Utilization | {stats.get("avg_utilization_pct", "N/A")}% |
| Memory Headroom | {stats.get("memory_headroom_mb", "N/A"):.1f} MiB |

## Analysis

"""
        # Determine utilization assessment
        peak_pct = stats.get("peak_utilization_pct", 0)
        if peak_pct < 30:
            report += "**Assessment**: ⚠️ VRAM SIGNIFICANTLY UNDERUTILIZED (<30%)\n"
            report += f"- Only {peak_pct}% of available VRAM was used at peak\n"
            report += f"- {stats.get('memory_headroom_mb', 0):.0f} MiB of VRAM went unused\n"
        elif peak_pct < 50:
            report += "**Assessment**: ⚠️ VRAM MODERATELY UNDERUTILIZED (30-50%)\n"
            report += f"- {peak_pct}% utilization suggests room for larger batch sizes\n"
        elif peak_pct < 80:
            report += "**Assessment**: ✅ VRAM REASONABLY UTILIZED (50-80%)\n"
            report += f"- {peak_pct}% utilization is a reasonable balance\n"
        else:
            report += "**Assessment**: ✅ VRAM WELL UTILIZED (>80%)\n"
            report += f"- {peak_pct}% utilization indicates efficient memory use\n"

        # Add raw samples timeline if requested
        if len(self.samples) <= 60:  # Only include if reasonable number
            report += "\n## Sample Timeline\n\n"
            report += "| Time | Memory Used (MiB) | Utilization (%) |\n"
            report += "|------|-------------------|----------------|\n"
            for s in self.samples:
                util = s["memory_used_mb"] / s["memory_total_mb"] * 100
                report += f"| {s['timestamp'].split('T')[1][:8]} | {s['memory_used_mb']} | {util:.1f}% |\n"

        with open(output_path, "w", encoding="utf-8") as f:
            f.write(report)

        return stats


def main():
    parser = argparse.ArgumentParser(description="Monitor VRAM utilization")
    parser.add_argument("--interval", type=float, default=2.0, help="Sampling interval in seconds")
    parser.add_argument("--duration", type=int, default=60, help="Monitoring duration in seconds")
    parser.add_argument("--output", type=Path, help="Output file for raw samples (JSONL)")
    parser.add_argument("--report", type=Path, help="Output path for markdown report")
    args = parser.parse_args()

    monitor = VRAMMonitor(interval=args.interval, output_file=args.output)

    # Handle Ctrl+C gracefully
    def signal_handler(sig, frame):
        monitor.stop()
        sys.exit(0)

    signal.signal(signal.SIGINT, signal_handler)

    monitor.start()

    if args.duration > 0:
        print(f"Monitoring for {args.duration} seconds...")
        time.sleep(args.duration)
        monitor.stop()
    else:
        print("Monitoring indefinitely (Ctrl+C to stop)...")
        try:
            while True:
                time.sleep(1)
        except KeyboardInterrupt:
            monitor.stop()

    # Print and save stats
    stats = monitor.get_stats()
    print("\n=== VRAM Statistics ===")
    print(json.dumps(stats, indent=2))

    if args.report:
        monitor.generate_report(args.report)
        print(f"\nReport written to: {args.report}")


if __name__ == "__main__":
    main()
