"""
Benchmark CLI - User-friendly interface for benchmark management.

Provides commands for running, listing, reporting, comparing, and recommending models.

Usage:
    python -m src.benchmarking.cli run --model opus_en_fr --device cpu
    python -m src.benchmarking.cli list --limit 5
    python -m src.benchmarking.cli report --run RUN_ID --format markdown
    python -m src.benchmarking.cli compare --runs RUN_A,RUN_B --metric throughput_tokens_per_sec
    python -m src.benchmarking.cli recommend --target-throughput 8 --max-memory-gb 4
"""
import argparse
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional

import yaml

from .reporter import BenchmarkReporter
from .runner import BenchmarkRunner, load_corpus
from .storage import BenchmarkDatabase
from ..model_runtime.recommender import ModelRecommender
from ..model_runtime.registry import ModelRegistry

# Import shared config loader (try relative first, fallback to absolute)
try:
    from ..cli import _load_benchmarking_yaml
except ImportError:
    from src.cli import _load_benchmarking_yaml

logger = logging.getLogger(__name__)


DEFAULT_DB_PATH = Path("data/benchmarks/benchmarks.db")


def get_benchmark_db_path(purpose: str = "benchmark") -> Path:
    """
    Get database path from config/env with precedence: ENV > config > default.

    Args:
        purpose: "benchmark" for explicit benchmarks, "production" for production metrics

    Returns:
        Path to database file

    Environment variable:
        BENCHMARK_DB_PATH: Override any config/default path
    """
    # ENV override takes precedence
    env_var = os.getenv("BENCHMARK_DB_PATH")
    if env_var:
        logger.info(f"Using benchmark database path from ENV: path={env_var} purpose={purpose}")
        return Path(env_var)

    # Load from config (uses shared loader)
    config = _load_benchmarking_yaml()

    if config:
        # Extract database path from config
        db_config = config.get("database", {})

        if purpose == "production":
            path_str = db_config.get("production_path", "data/benchmarks/production.db")
        else:
            path_str = db_config.get("path", "data/benchmarks/benchmarks.db")

        logger.info(f"Using benchmark database path from config: path={path_str} purpose={purpose}")
        return Path(path_str)

    # Default fallback (config doesn't exist or failed to load)
    if purpose == "production":
        default_path = "data/benchmarks/production.db"
    else:
        default_path = "data/benchmarks/benchmarks.db"

    logger.info(f"Using default benchmark database path: path={default_path} purpose={purpose}")
    return Path(default_path)


def cmd_run(args: argparse.Namespace) -> int:
    """
    Run a new benchmark.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        # Parse batch sizes
        batch_sizes = [int(bs.strip()) for bs in args.batch_sizes.split(',')]
    except ValueError:
        logger.error(f"Invalid batch sizes: {args.batch_sizes}")
        return 1

    # Parse tags
    tags = [tag.strip() for tag in args.tags.split(',')] if args.tags else []

    # Load registry
    try:
        registry_path = Path(args.registry)
        if not registry_path.exists():
            logger.error(f"Registry file not found: {registry_path}")
            return 1

        registry = ModelRegistry(registry_path)
        logger.info(f"Loaded registry with {len(registry.models)} models")
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Determine DB path
    db_path = Path(args.save_to_db) if args.save_to_db else None

    # Initialize runner
    try:
        runner = BenchmarkRunner(registry=registry, db_path=db_path)
    except Exception as e:
        logger.error(f"Failed to initialize runner: {e}")
        return 1

    # Run benchmark
    try:
        result = runner.run_benchmark(
            model_id=args.model,
            device=args.device,
            batch_sizes=batch_sizes,
            iterations=args.iterations,
            corpus_filter=args.corpus,
            purpose=args.purpose,
            tags=tags,
            max_samples=args.max_samples,
        )

        # Print summary
        print("\n" + "="*60)
        print(f"Benchmark Run: {result.run_id}")
        print("="*60)
        print(f"Model:          {result.model_id}")
        print(f"Device:         {result.device}")
        print(f"Batch sizes:    {result.batch_sizes}")
        print(f"Iterations:     {result.iterations}")
        print(f"Corpus:         {result.corpus_category}")
        print(f"Total samples:  {len(result.results)}")
        print(f"Duration:       {result.total_duration_seconds:.2f}s")

        if result.results:
            avg_throughput = sum(r.throughput_tokens_per_sec for r in result.results) / len(result.results)
            print(f"Avg throughput: {avg_throughput:.2f} tokens/sec")

        if db_path:
            print(f"\nResults saved to: {db_path}")
            print(f"Run ID: {result.run_id}")

        return 0

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
        return 1
    except RuntimeError as e:
        logger.error(f"Benchmark failed: {e}")
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
        return 1


def cmd_list(args: argparse.Namespace) -> int:
    """
    List benchmark runs.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    db_path = Path(args.db) if args.db else get_benchmark_db_path()

    # Check if DB exists
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        print(f"ERROR: Benchmark database not found at {db_path}", file=sys.stderr)
        print(f"HINT: Run a benchmark first with:", file=sys.stderr)
        print(f"  python -m src.benchmarking.cli run --model opus_en_fr --device cpu --save-to-db {db_path}", file=sys.stderr)
        return 1

    try:
        db = BenchmarkDatabase(db_path)

        runs = db.list_runs(
            model_id=args.model,
            device=args.device,
            limit=args.limit,
            offset=args.offset,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(
                [
                    {
                        "run_id": run_id,
                        "model_id": model_id,
                        "device": device,
                        "timestamp": timestamp,
                        "result_count": result_count,
                    }
                    for run_id, model_id, device, timestamp, result_count in runs
                ],
                indent=2,
            )
            print(output)
        else:
            # Markdown format
            reporter = BenchmarkReporter()
            output = reporter.format_run_list_markdown(runs, title="Benchmark Runs")
            print(output)

        return 0

    except Exception as e:
        logger.error(f"Failed to list runs: {e}", exc_info=args.verbose)
        return 1


def cmd_report(args: argparse.Namespace) -> int:
    """
    Generate a report for a specific benchmark run.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    db_path = Path(args.db) if args.db else get_benchmark_db_path()

    # Check if DB exists
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        print(f"ERROR: Benchmark database not found at {db_path}", file=sys.stderr)
        return 1

    try:
        db = BenchmarkDatabase(db_path)
        run = db.get_run(args.run)

        if run is None:
            logger.error(f"Run not found: {args.run}")
            print(f"ERROR: Benchmark run '{args.run}' not found in database", file=sys.stderr)
            print(f"HINT: List available runs with:", file=sys.stderr)
            print(f"  python -m src.benchmarking.cli list --db {db_path}", file=sys.stderr)
            return 1

        # Format output
        reporter = BenchmarkReporter()
        if args.format == "json":
            output = reporter.format_json(run, indent=2)
        else:
            output = reporter.format_markdown(run)

        print(output)
        return 0

    except Exception as e:
        logger.error(f"Failed to generate report: {e}", exc_info=args.verbose)
        return 1


def cmd_compare(args: argparse.Namespace) -> int:
    """
    Compare multiple benchmark runs.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    db_path = Path(args.db) if args.db else get_benchmark_db_path()

    # Check if DB exists
    if not db_path.exists():
        logger.error(f"Database not found: {db_path}")
        print(f"ERROR: Benchmark database not found at {db_path}", file=sys.stderr)
        return 1

    # Parse run IDs
    run_ids = [rid.strip() for rid in args.runs.split(',')]

    if len(run_ids) < 2:
        logger.error("Need at least 2 runs to compare")
        print(f"ERROR: Need at least 2 runs to compare (got {len(run_ids)})", file=sys.stderr)
        return 1

    try:
        db = BenchmarkDatabase(db_path)
        comparison = db.compare_runs(run_ids, metric=args.metric)

        # Format output
        reporter = BenchmarkReporter()
        if args.format == "json":
            output = json.dumps(comparison, indent=2)
        else:
            output = reporter.format_comparison_markdown(comparison)

        print(output)
        return 0

    except Exception as e:
        logger.error(f"Failed to compare runs: {e}", exc_info=args.verbose)
        return 1


def cmd_recommend(args: argparse.Namespace) -> int:
    """
    Recommend a model based on constraints and historical data.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    try:
        # Load registry
        registry_path = Path(args.registry)
        if not registry_path.exists():
            logger.error(f"Registry file not found: {registry_path}")
            return 1

        registry = ModelRegistry(registry_path)
        logger.info(f"Loaded registry with {len(registry.models)} models")

        # Load benchmark storage if DB exists
        db_path = Path(args.db) if args.db else get_benchmark_db_path()
        benchmark_storage = None

        if db_path.exists():
            try:
                benchmark_storage = BenchmarkDatabase(db_path)
                logger.info(f"Using benchmark data from {db_path}")
            except Exception as e:
                logger.warning(f"Failed to load benchmark database: {e}")
                logger.info("Falling back to heuristic recommendations")
        else:
            logger.info(f"Benchmark database not found at {db_path}, using heuristics only")

        # Create recommender
        recommender = ModelRecommender(
            registry=registry,
            benchmark_storage=benchmark_storage,
        )

        # Get recommendation
        recommendation = recommender.recommend(
            target_throughput=args.target_throughput,
            max_memory_gb=args.max_memory_gb,
            device_preference=args.device,
        )

        # Format output
        if args.format == "json":
            output = json.dumps(recommendation.to_dict(), indent=2)
            print(output)
        else:
            reporter = BenchmarkReporter()
            output = reporter.format_recommendation_markdown(recommendation.to_dict())
            print(output)

        return 0

    except ValueError as e:
        logger.error(f"Recommendation failed: {e}")
        print(f"ERROR: {e}", file=sys.stderr)
        return 1
    except Exception as e:
        logger.error(f"Unexpected error: {e}", exc_info=args.verbose)
        return 1


def main():
    """
    Main CLI entry point with subcommand routing.
    """
    parser = argparse.ArgumentParser(
        description="Benchmark CLI for translation model performance management",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    # Global options
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    # Subcommands
    subparsers = parser.add_subparsers(dest="command", help="Command to execute")

    # --- run command ---
    run_parser = subparsers.add_parser(
        "run",
        help="Run a new benchmark",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark on CPU with tiny corpus
  python -m src.benchmarking.cli run --model opus_en_fr --device cpu --batch-sizes 8 --iterations 1 --corpus tiny --save-to-db data/benchmarks/dev.db

  # Benchmark with custom purpose and tags
  python -m src.benchmarking.cli run --model m2m100_418m --device cpu --batch-sizes 4 --iterations 2 --purpose "cpu regression" --tags baseline,cpu
        """,
    )
    run_parser.add_argument("--model", required=True, help="Model ID from registry")
    run_parser.add_argument("--device", default="cpu", help="Device (cpu, cuda, etc.)")
    run_parser.add_argument("--batch-sizes", default="8", help="Comma-separated batch sizes (e.g., 8,16)")
    run_parser.add_argument("--iterations", type=int, default=1, help="Iterations per batch size")
    run_parser.add_argument("--corpus", default="tiny", help="Corpus filter (tiny, small, medium)")
    run_parser.add_argument("--purpose", default="benchmark", help="Purpose description")
    run_parser.add_argument("--tags", help="Comma-separated tags (e.g., baseline,gpu)")
    run_parser.add_argument("--save-to-db", help="Database file to save results")
    run_parser.add_argument("--max-samples", type=int, help="Max samples to process (for testing)")
    run_parser.add_argument("--registry", default="config/model_registry.yaml", help="Model registry YAML")

    # --- list command ---
    list_parser = subparsers.add_parser(
        "list",
        help="List benchmark runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List last 10 runs
  python -m src.benchmarking.cli list --limit 10

  # Filter by model
  python -m src.benchmarking.cli list --model opus_en_fr

  # JSON output for scripting
  python -m src.benchmarking.cli list --format json
        """,
    )
    list_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    list_parser.add_argument("--model", help="Filter by model ID")
    list_parser.add_argument("--device", help="Filter by device")
    list_parser.add_argument("--limit", type=int, default=10, help="Max results (default: 10)")
    list_parser.add_argument("--offset", type=int, default=0, help="Result offset")
    list_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")

    # --- report command ---
    report_parser = subparsers.add_parser(
        "report",
        help="Generate report for a benchmark run",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Generate Markdown report
  python -m src.benchmarking.cli report --run abc123 --format markdown > reports/benchmarking/abc123.md

  # Generate JSON report
  python -m src.benchmarking.cli report --run abc123 --format json
        """,
    )
    report_parser.add_argument("--run", required=True, help="Run ID to report on")
    report_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    report_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")

    # --- compare command ---
    compare_parser = subparsers.add_parser(
        "compare",
        help="Compare multiple benchmark runs",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare two runs by throughput
  python -m src.benchmarking.cli compare --runs abc123,def456 --metric throughput_tokens_per_sec

  # Compare by duration
  python -m src.benchmarking.cli compare --runs abc123,def456 --metric duration_seconds --format markdown
        """,
    )
    compare_parser.add_argument("--runs", required=True, help="Comma-separated run IDs")
    compare_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    compare_parser.add_argument(
        "--metric",
        default="throughput_tokens_per_sec",
        choices=["throughput_tokens_per_sec", "duration_seconds", "peak_memory_mb"],
        help="Metric to compare",
    )
    compare_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")

    # --- recommend command ---
    recommend_parser = subparsers.add_parser(
        "recommend",
        help="Recommend a model based on constraints",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Recommend model for CPU with 4GB memory limit
  python -m src.benchmarking.cli recommend --max-memory-gb 4 --device cpu

  # Recommend model targeting 10 tokens/sec throughput
  python -m src.benchmarking.cli recommend --target-throughput 10

  # Use custom registry and benchmark database
  python -m src.benchmarking.cli recommend --registry config/model_registry.yaml --db data/benchmarks/cpu.db --max-memory-gb 4
        """,
    )
    recommend_parser.add_argument("--target-throughput", type=float, help="Minimum target throughput (tokens/sec)")
    recommend_parser.add_argument("--max-memory-gb", type=float, help="Maximum memory budget (GB)")
    recommend_parser.add_argument("--device", help="Preferred device (cpu, cuda, etc.)")
    recommend_parser.add_argument("--db", help="Benchmark database (default: data/benchmarks/benchmarks.db or from config)")
    recommend_parser.add_argument("--registry", default="config/model_registry.yaml", help="Model registry YAML")
    recommend_parser.add_argument("--format", choices=["markdown", "json"], default="markdown", help="Output format")

    # Parse arguments
    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Route to subcommand
    if not args.command:
        parser.print_help()
        return 1

    if args.command == "run":
        return cmd_run(args)
    elif args.command == "list":
        return cmd_list(args)
    elif args.command == "report":
        return cmd_report(args)
    elif args.command == "compare":
        return cmd_compare(args)
    elif args.command == "recommend":
        return cmd_recommend(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
