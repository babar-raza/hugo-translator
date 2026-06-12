#!/usr/bin/env python3
"""Start the benchmark dashboard web server."""

import argparse
import sys
import webbrowser
from pathlib import Path
from threading import Timer


def main():
    parser = argparse.ArgumentParser(description="Start benchmark dashboard")
    parser.add_argument("--host", default="127.0.0.1", help="Host to bind to (default: 127.0.0.1)")
    parser.add_argument("--port", type=int, default=5000, help="Port to bind to (default: 5000)")
    parser.add_argument("--debug", action="store_true", help="Enable debug mode")
    parser.add_argument(
        "--no-browser", action="store_true", help="Don't open browser automatically"
    )
    args = parser.parse_args()

    # Validate database exists
    project_root = Path(__file__).parent.parent
    db_path = project_root / "data" / "benchmarks" / "benchmarks.db"

    if not db_path.exists():
        print()
        print("=" * 70)
        print("ERROR: Benchmark database not found")
        print("=" * 70)
        print()
        print(f"Expected location: {db_path}")
        print()
        print("The dashboard requires benchmark data to display.")
        print("Please run benchmarks first:")
        print()
        print("  python -m src.benchmarking.cli benchmark \\")
        print("    --model facebook/nllb-200-distilled-600M \\")
        print("    --device cpu \\")
        print("    --corpus data/corpus/sample_en.txt")
        print()
        print("Or use the comprehensive benchmark script:")
        print()
        print("  python scripts/bench/benchmark_cpu_comprehensive.py")
        print()
        return 1

    # Add src to path for imports
    sys.path.insert(0, str(project_root / "src"))

    try:
        from benchmarking.dashboard.app import app
    except ImportError as e:
        print()
        print("=" * 70)
        print("ERROR: Failed to import dashboard application")
        print("=" * 70)
        print()
        print(f"Import error: {e}")
        print()
        print("Make sure all dependencies are installed:")
        print("  pip install flask")
        print()
        return 1

    # Open browser after short delay (only if not in debug mode and not disabled)
    if not args.debug and not args.no_browser:

        def open_browser():
            webbrowser.open(f"http://{args.host}:{args.port}")

        Timer(1.5, open_browser).start()

    # Print startup message
    print()
    print("=" * 70)
    print("BENCHMARK DASHBOARD")
    print("=" * 70)
    print()
    print(f"Starting server at http://{args.host}:{args.port}")
    print()
    print("Dashboard features:")
    print("  • Summary statistics and trends")
    print("  • Model comparison and rankings")
    print("  • Language coverage overview")
    print("  • Recent benchmark runs")
    print()
    print("Press Ctrl+C to stop the server")
    print("=" * 70)
    print()

    # Start Flask server
    try:
        app.run(host=args.host, port=args.port, debug=args.debug)
    except KeyboardInterrupt:
        print()
        print("Dashboard stopped")
        return 0
    except Exception as e:
        print()
        print("=" * 70)
        print("ERROR: Failed to start dashboard")
        print("=" * 70)
        print()
        print(f"Error: {e}")
        print()
        return 1


if __name__ == "__main__":
    sys.exit(main())
