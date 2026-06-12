"""
hugo_build_check.py — Hugo build validation gate for translation sprints.

Runs Hugo against the aspose.net content repository and checks for build errors.
Used as a post-batch gate in the words_sprint.py orchestrator.

Usage:
    python scripts/hugo_build_check.py [--source PATH] [--error-threshold N]

Environment:
    ASPOSE_NET_CONTENT   Used as default --source if not specified

Exit codes:
    0   Hugo build succeeded (error count within threshold)
    1   Hugo build failed or exceeded error threshold
    2   Hugo not found in PATH
    3   Source directory not found
"""

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path


def find_hugo() -> str | None:
    """Find hugo executable in PATH."""
    try:
        result = subprocess.run(
            ["where", "hugo"] if sys.platform == "win32" else ["which", "hugo"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            return result.stdout.strip().splitlines()[0]
    except Exception:
        pass
    return None


def run_hugo_build(
    source_dir: str, hugo_path: str, timeout: int = 300
) -> tuple[int, int, int, str]:
    """
    Run Hugo build and return (exit_code, error_count, warning_count, stderr_excerpt).
    """
    cmd = [
        hugo_path,
        "--source",
        source_dir,
        "--buildDrafts",
        "--gc",
        "--logLevel",
        "warn",
    ]
    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        stderr = result.stderr + result.stdout
        # Count ERROR and WARN lines
        error_count = len(re.findall(r"\bERROR\b", stderr, re.IGNORECASE))
        warning_count = len(re.findall(r"\bWARN\b", stderr, re.IGNORECASE))
        excerpt = stderr[-2000:] if len(stderr) > 2000 else stderr
        return result.returncode, error_count, warning_count, excerpt
    except subprocess.TimeoutExpired:
        return 1, 0, 0, f"Hugo build timed out after {timeout}s"
    except Exception as e:
        return 1, 0, 0, f"Hugo build error: {e}"


def main():
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument(
        "--source", help="Hugo site root directory (default: ASPOSE_NET_CONTENT parent)"
    )
    parser.add_argument(
        "--error-threshold", type=int, default=0, help="Max allowed ERROR count (default: 0)"
    )
    parser.add_argument(
        "--warn-threshold", type=int, default=50, help="Max allowed WARN count (default: 50)"
    )
    parser.add_argument(
        "--timeout", type=int, default=300, help="Timeout in seconds (default: 300)"
    )
    args = parser.parse_args()

    # Resolve source directory
    source_dir = args.source
    if not source_dir:
        content_base = os.environ.get("ASPOSE_NET_CONTENT", "")
        if content_base:
            # ASPOSE_NET_CONTENT points to /content; Hugo root is one level up
            source_dir = str(Path(content_base).parent)
        else:
            print("ERROR: --source not specified and ASPOSE_NET_CONTENT not set", file=sys.stderr)
            sys.exit(3)

    if not Path(source_dir).exists():
        print(f"ERROR: Source directory not found: {source_dir}", file=sys.stderr)
        sys.exit(3)

    # Find Hugo
    hugo_path = find_hugo()
    if not hugo_path:
        print("ERROR: hugo not found in PATH", file=sys.stderr)
        print("  Install Hugo: https://gohugo.io/installation/", file=sys.stderr)
        sys.exit(2)

    print(f"Hugo path: {hugo_path}")
    print(f"Source:    {source_dir}")
    print(f"Thresholds: errors={args.error_threshold} warnings={args.warn_threshold}")
    print("Running Hugo build...")

    exit_code, error_count, warning_count, excerpt = run_hugo_build(
        source_dir, hugo_path, args.timeout
    )

    print(f"Exit code: {exit_code}")
    print(f"Errors:    {error_count}")
    print(f"Warnings:  {warning_count}")

    if excerpt.strip():
        print("\n--- Hugo output (last 2000 chars) ---")
        print(excerpt)
        print("--- end ---")

    # Evaluate thresholds
    if exit_code != 0:
        print(f"\nRESULT: FAIL — Hugo exited with code {exit_code}")
        sys.exit(1)

    if error_count > args.error_threshold:
        print(
            f"\nRESULT: FAIL — Error count {error_count} exceeds threshold {args.error_threshold}"
        )
        sys.exit(1)

    if warning_count > args.warn_threshold:
        print(
            f"\nRESULT: FAIL — Warning count {warning_count} exceeds threshold {args.warn_threshold}"
        )
        sys.exit(1)

    print("\nRESULT: PASS — Hugo build succeeded within thresholds")
    sys.exit(0)


if __name__ == "__main__":
    main()
