#!/usr/bin/env python3
"""
Metrics Tail - Windows-friendly real-time metrics viewer.

Usage:
    python -m src.observability.metrics_tail <metrics_file.ndjson>
    python -m src.observability.metrics_tail <metrics_file.ndjson> --compact
    python -m src.observability.metrics_tail <metrics_file.ndjson> --json

This utility follows NDJSON metrics streams and displays them in a
human-readable format. Works on Windows terminals (PowerShell, cmd).
"""

import argparse
import json
import sys
import time
from pathlib import Path
from typing import Any


def format_eta(eta_s: float | None) -> str:
    """Format ETA as human-readable string."""
    if eta_s is None or eta_s < 0:
        return "calculating..."
    if eta_s == 0:
        return "done"

    hours, remainder = divmod(int(eta_s), 3600)
    minutes, seconds = divmod(remainder, 60)

    if hours > 0:
        return f"{hours}h {minutes}m {seconds}s"
    elif minutes > 0:
        return f"{minutes}m {seconds}s"
    else:
        return f"{seconds}s"


def format_duration(seconds: float) -> str:
    """Format duration as human-readable string."""
    if seconds < 60:
        return f"{seconds:.1f}s"
    minutes, secs = divmod(int(seconds), 60)
    if minutes < 60:
        return f"{minutes}m {secs}s"
    hours, mins = divmod(minutes, 60)
    return f"{hours}h {mins}m {secs}s"


def format_compact(data: dict[str, Any]) -> str:
    """Format metrics as compact single line."""
    overall = data.get("overall", {})
    files = data.get("files", {})
    segments = data.get("segments", {})
    perf = data.get("performance", {})
    cache = data.get("cache", {})
    errors = data.get("errors", {})

    pct = overall.get("percent_complete_segments", 0)
    files_done = files.get("done", 0)
    files_total = files.get("total", 0)
    segs_done = segments.get("done", 0)
    segs_total = segments.get("total", 0)
    rate = perf.get("segments_per_sec_rolling", 0)
    hit_rate = cache.get("hit_rate", 0) * 100
    eta = format_eta(data.get("eta_s"))
    err_count = errors.get("count", 0)

    return (
        f"[{pct:.1f}%] "
        f"files={files_done}/{files_total} "
        f"segs={segs_done}/{segs_total} "
        f"rate={rate:.1f}/s "
        f"cache={hit_rate:.0f}% "
        f"ETA={eta} "
        f"err={err_count}"
    )


def format_detailed(data: dict[str, Any]) -> str:
    """Format metrics as detailed multi-line output."""
    lines = []

    # Header
    timestamp = data.get("timestamp_iso", "")
    elapsed = format_duration(data.get("elapsed_s", 0))
    eta = format_eta(data.get("eta_s"))
    lines.append(f"\n{'='*60}")
    lines.append(f"Timestamp: {timestamp}")
    lines.append(f"Elapsed: {elapsed} | ETA: {eta}")
    lines.append(f"{'='*60}")

    # Progress
    overall = data.get("overall", {})
    pct_files = overall.get("percent_complete_files", 0)
    pct_segs = overall.get("percent_complete_segments", 0)
    lines.append("\nProgress:")
    lines.append(f"  Files:    {pct_files:.1f}% complete")
    lines.append(f"  Segments: {pct_segs:.1f}% complete")

    # Files
    files = data.get("files", {})
    lines.append("\nFiles:")
    lines.append(f"  Total:   {files.get('total', 0)}")
    lines.append(f"  Done:    {files.get('done', 0)}")
    lines.append(f"  Failed:  {files.get('failed', 0)}")
    lines.append(f"  Skipped: {files.get('skipped', 0)}")
    if files.get("current"):
        lines.append(f"  Current: {files.get('current')}")

    # Segments
    segments = data.get("segments", {})
    lines.append("\nSegments:")
    lines.append(f"  Total:  {segments.get('total', 0)}")
    lines.append(f"  Done:   {segments.get('done', 0)}")
    lines.append(f"  Failed: {segments.get('failed', 0)}")

    # Performance
    perf = data.get("performance", {})
    lines.append("\nPerformance:")
    lines.append(f"  Rate (rolling):  {perf.get('segments_per_sec_rolling', 0):.2f} segs/sec")
    lines.append(f"  Rate (lifetime): {perf.get('segments_per_sec_lifetime', 0):.2f} segs/sec")
    lines.append(f"  Files/min:       {perf.get('files_per_min', 0):.2f}")
    lines.append(f"  Avg seg time:    {perf.get('avg_segment_ms', 0):.1f} ms")
    lines.append(f"  Avg batch time:  {perf.get('avg_batch_s', 0):.3f} s")

    # Cache
    cache = data.get("cache", {})
    hit_rate = cache.get("hit_rate", 0) * 100
    lines.append("\nCache:")
    lines.append(f"  Hit Rate: {hit_rate:.1f}%")
    lines.append(f"  Hits:     {cache.get('hits', 0)} (L1: {cache.get('l1_hits', 0)}, L2: {cache.get('l2_hits', 0)}, L3: {cache.get('l3_hits', 0)})")
    lines.append(f"  Misses:   {cache.get('misses', 0)}")

    # Translation
    translation = data.get("translation", {})
    if translation.get("model"):
        lines.append("\nTranslation:")
        lines.append(f"  Model:    {translation.get('model', 'unknown')}")
        lines.append(f"  Device:   {translation.get('device', 'unknown')}")
        lines.append(f"  Tokens:   {translation.get('tokens_in', 0):,} in, {translation.get('tokens_out', 0):,} out")
        lines.append(f"  Retries:  {translation.get('retries', 0)}")

    # Errors
    errors = data.get("errors", {})
    if errors.get("count", 0) > 0:
        lines.append(f"\nErrors: {errors.get('count', 0)}")
        if errors.get("last_error"):
            lines.append(f"  Last: {errors.get('last_error')[:80]}...")
        if errors.get("last_failed_file"):
            lines.append(f"  File: {errors.get('last_failed_file')}")

    return "\n".join(lines)


def tail_file(path: Path, mode: str = "detailed", poll_interval: float = 0.5) -> None:
    """
    Tail an NDJSON metrics file and display updates.

    Args:
        path: Path to NDJSON file
        mode: Output mode ('compact', 'detailed', or 'json')
        poll_interval: Seconds between file checks
    """
    print(f"Tailing metrics from: {path}")
    print(f"Mode: {mode}")
    print("Press Ctrl+C to stop\n")

    # Wait for file to exist
    while not path.exists():
        print(f"Waiting for {path}...")
        time.sleep(poll_interval)

    # Start from end of file
    position = path.stat().st_size if path.exists() else 0
    last_mtime = path.stat().st_mtime if path.exists() else 0

    try:
        while True:
            try:
                # Check if file was modified
                current_mtime = path.stat().st_mtime
                if current_mtime <= last_mtime:
                    time.sleep(poll_interval)
                    continue

                last_mtime = current_mtime

                # Read new lines
                with open(path, encoding="utf-8") as f:
                    f.seek(position)
                    new_lines = f.readlines()
                    position = f.tell()

                # Process each new line
                for line in new_lines:
                    line = line.strip()
                    if not line:
                        continue

                    try:
                        data = json.loads(line)

                        if mode == "json":
                            print(json.dumps(data, indent=2))
                        elif mode == "compact":
                            # Clear line and print compact status
                            print(f"\r{format_compact(data)}", end="", flush=True)
                        else:
                            print(format_detailed(data))

                    except json.JSONDecodeError as e:
                        print(f"Warning: Invalid JSON line: {e}", file=sys.stderr)

            except FileNotFoundError:
                # File was deleted, wait for it to be recreated
                print(f"\nFile {path} not found, waiting...")
                position = 0
                time.sleep(poll_interval)

    except KeyboardInterrupt:
        print("\n\nStopped.")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(
        description="Tail NDJSON metrics file with real-time updates",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Detailed multi-line output (default)
  python -m src.observability.metrics_tail metrics.ndjson

  # Compact single-line status
  python -m src.observability.metrics_tail metrics.ndjson --compact

  # Raw JSON output
  python -m src.observability.metrics_tail metrics.ndjson --json

Two-terminal setup (Windows PowerShell):
  # Terminal A: Run translation with metrics
  python -m src.cli --site mysite --metrics-file ./metrics

  # Terminal B: Follow metrics stream
  python -m src.observability.metrics_tail ./metrics.ndjson --compact
        """
    )

    parser.add_argument(
        "file",
        type=Path,
        help="Path to NDJSON metrics file to tail",
    )

    parser.add_argument(
        "--compact",
        action="store_true",
        help="Show compact single-line output (updates in place)",
    )

    parser.add_argument(
        "--json",
        action="store_true",
        help="Show raw JSON output (pretty-printed)",
    )

    parser.add_argument(
        "--poll",
        type=float,
        default=0.5,
        metavar="SECS",
        help="Poll interval in seconds (default: 0.5)",
    )

    args = parser.parse_args()

    # Determine mode
    if args.json:
        mode = "json"
    elif args.compact:
        mode = "compact"
    else:
        mode = "detailed"

    # Handle .ndjson extension
    path = args.file
    if not path.suffix:
        path = path.with_suffix(".ndjson")

    tail_file(path, mode=mode, poll_interval=args.poll)


if __name__ == "__main__":
    main()
