"""
Benchmark CLI - User-friendly interface for benchmark management.

Provides commands for running, listing, reporting, comparing, and recommending models.

Usage:
    python -m src.benchmarking.cli run --model opus_en_fr --device cpu
    python -m src.benchmarking.cli list --limit 5
    python -m src.benchmarking.cli report --run RUN_ID --format markdown
    python -m src.benchmarking.cli compare --runs RUN_A,RUN_B --metric throughput_tokens_per_sec
    python -m src.benchmarking.cli recommend --target-throughput 8 --max-memory-gb 4

Note: Heavy ML dependencies (torch) are lazily imported to allow
--help to work without the full ML stack installed.
"""
import argparse
import importlib.metadata
import json
import logging
import os
import sys
from pathlib import Path
from typing import List, Optional, TYPE_CHECKING

import yaml

# TYPE_CHECKING guard for type hints only
if TYPE_CHECKING:
    from .recommender import ModelRecommender as BenchmarkRecommender
    from .reporter import BenchmarkReporter
    from .runner import BenchmarkRunner
    from .storage import BenchmarkDatabase
    from .schema_migrations import MigrationManager
    from .aggregation import TimeSeriesAggregator
    from .analytics import AnalyticsQueryAPI
    from .retention import RetentionEngine
    from .exporter import BenchmarkExporter, ExportFilter
    from .archiver import BenchmarkArchiver
    from ..model_runtime.recommender import ModelRecommender
    from ..model_runtime.registry import ModelRegistry

# Module-level cache for lazy-loaded heavy dependencies
_heavy_deps_loaded = False
_heavy_deps_cache = {}


def _import_heavy_deps():
    """
    Lazily import heavy ML dependencies when actually needed.

    This allows --help to work without torch installed.
    Imports are cached after first successful load.

    Returns:
        dict: Dictionary containing all heavy dependency modules/classes

    Raises:
        ImportError: If required dependencies are not installed
    """
    global _heavy_deps_loaded, _heavy_deps_cache

    if _heavy_deps_loaded:
        return _heavy_deps_cache

    try:
        from .recommender import ModelRecommender as BenchmarkRecommender
        from .reporter import BenchmarkReporter
        from .runner import BenchmarkRunner, load_corpus
        from .storage import BenchmarkDatabase
        from .schema_migrations import MigrationManager
        from .aggregation import TimeSeriesAggregator
        from .analytics import AnalyticsQueryAPI
        from .retention import RetentionEngine
        from .exporter import BenchmarkExporter, ExportFilter
        from .archiver import BenchmarkArchiver
        from ..model_runtime.recommender import ModelRecommender
        from ..model_runtime.registry import ModelRegistry
    except ImportError as e:
        error_msg = str(e)
        if 'torch' in error_msg.lower() or "No module named 'torch'" in error_msg:
            raise ImportError(
                "PyTorch is required for benchmarking but not installed. "
                "Install with: pip install torch or "
                "install all ML dependencies: pip install -r requirements.txt"
            ) from e
        else:
            raise

    _heavy_deps_cache = {
        'BenchmarkRecommender': BenchmarkRecommender,
        'BenchmarkReporter': BenchmarkReporter,
        'BenchmarkRunner': BenchmarkRunner,
        'load_corpus': load_corpus,
        'BenchmarkDatabase': BenchmarkDatabase,
        'MigrationManager': MigrationManager,
        'TimeSeriesAggregator': TimeSeriesAggregator,
        'AnalyticsQueryAPI': AnalyticsQueryAPI,
        'RetentionEngine': RetentionEngine,
        'BenchmarkExporter': BenchmarkExporter,
        'ExportFilter': ExportFilter,
        'BenchmarkArchiver': BenchmarkArchiver,
        'ModelRecommender': ModelRecommender,
        'ModelRegistry': ModelRegistry,
    }
    _heavy_deps_loaded = True
    return _heavy_deps_cache


def _load_benchmarking_yaml():
    """
    Load benchmarking config from yaml.

    This is a local copy to avoid importing from src.cli which may trigger heavy imports.
    """
    config_path = Path("config/benchmarking.yaml")
    if not config_path.exists():
        return {}
    try:
        with open(config_path) as f:
            return yaml.safe_load(f) or {}
    except Exception:
        return {}


logger = logging.getLogger(__name__)


def get_version() -> str:
    """
    Get package version from importlib.metadata with fallback.

    Returns:
        Version string (e.g., "0.1.0" or "0.1.0-dev" if not installed)
    """
    try:
        return importlib.metadata.version("hugo-translation-system")
    except importlib.metadata.PackageNotFoundError:
        return "0.1.0-dev"  # Fallback for development mode


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
    # Load heavy dependencies
    deps = _import_heavy_deps()
    ModelRegistry = deps['ModelRegistry']
    BenchmarkRunner = deps['BenchmarkRunner']

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
        registry_paths = [Path(p.strip()) for p in args.registry.split(',') if p.strip()]
        missing = [str(p) for p in registry_paths if not p.exists()]
        if missing:
            logger.error(f"Registry file(s) not found: {', '.join(missing)}")
            return 1

        registry = ModelRegistry(args.registry)
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
    # Load heavy dependencies
    deps = _import_heavy_deps()
    BenchmarkDatabase = deps['BenchmarkDatabase']
    BenchmarkReporter = deps['BenchmarkReporter']

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
    # Load heavy dependencies
    deps = _import_heavy_deps()
    BenchmarkDatabase = deps['BenchmarkDatabase']
    BenchmarkReporter = deps['BenchmarkReporter']

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
    # Load heavy dependencies
    deps = _import_heavy_deps()
    BenchmarkDatabase = deps['BenchmarkDatabase']
    BenchmarkReporter = deps['BenchmarkReporter']

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
    # Load heavy dependencies
    deps = _import_heavy_deps()
    BenchmarkDatabase = deps['BenchmarkDatabase']
    BenchmarkRecommender = deps['BenchmarkRecommender']
    BenchmarkReporter = deps['BenchmarkReporter']
    ModelRegistry = deps['ModelRegistry']
    ModelRecommender = deps['ModelRecommender']

    try:
        # Check if this is an OOM-safe batch size recommendation (CUDA + max_memory_gb)
        if args.device and args.device.startswith('cuda') and args.max_memory_gb:
            # Use benchmarking recommender for OOM-safe batch size
            db_path = Path(args.db) if args.db else get_benchmark_db_path()

            if not db_path.exists():
                print(f"ERROR: Benchmark database not found at {db_path}", file=sys.stderr)
                print(f"HINT: Run GPU benchmarks first:", file=sys.stderr)
                print(f"  python -m src.benchmarking.cli run --model m2m100_418m --device {args.device} --batch-sizes 8,16,32 --save-to-db {db_path}", file=sys.stderr)
                return 1

            db = BenchmarkDatabase(db_path)
            recommender = BenchmarkRecommender(db=db)

            # Get OOM-safe batch size recommendation
            max_memory_mb = args.max_memory_gb * 1024
            safety_margin = getattr(args, 'safety_margin', 0.20)

            result = recommender.get_oom_safe_batch_size(
                device=args.device,
                max_memory_mb=max_memory_mb,
                safety_margin=safety_margin
            )

            # Format output
            if args.format == "json":
                print(json.dumps(result, indent=2))
            else:
                # Markdown format
                print("=" * 60)
                print("OOM-Safe Batch Size Recommendation")
                print("=" * 60)
                print(f"Device:              {args.device}")
                print(f"Max GPU Memory:      {result['max_memory_mb']:.0f} MB ({result['max_memory_mb']/1024:.1f} GB)")
                print(f"Safety Margin:       {result['safety_margin_pct']:.0f}%")
                print("")
                print(f"✅ Recommended:      batch_size = {result['recommended_batch_size']}")
                print(f"   Estimated Peak:   {result['estimated_peak_mb']:.0f} MB")
                utilization = result['estimated_peak_mb'] / result['max_memory_mb'] * 100 if result['max_memory_mb'] > 0 else 0
                print(f"   Utilization:      {utilization:.1f}%")
                print(f"   Confidence:       {result['confidence_samples']} historical samples")

                if 'warning' in result:
                    print("")
                    print(f"⚠️  WARNING: {result['warning']}", file=sys.stderr)

            return 0

        # Original model recommender logic for non-OOM-safe cases
        # Load registry
        registry_paths = [Path(p.strip()) for p in args.registry.split(',') if p.strip()]
        missing = [str(p) for p in registry_paths if not p.exists()]
        if missing:
            logger.error(f"Registry file(s) not found: {', '.join(missing)}")
            return 1

        registry = ModelRegistry(args.registry)
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


def cmd_migrate(args: argparse.Namespace) -> int:
    """
    Manage database schema migrations.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Load heavy dependencies
    deps = _import_heavy_deps()
    MigrationManager = deps['MigrationManager']

    try:
        # Get database path
        if args.db:
            db_path = Path(args.db)
        else:
            db_path = get_benchmark_db_path()

        # Create migration manager
        manager = MigrationManager(db_path=db_path)

        # List migrations
        if args.list:
            migrations = manager.list_migrations()
            current_version = manager.get_current_version()

            print("\nAvailable Migrations:")
            print("="*80)
            for mig in migrations:
                status = "CURRENT" if mig["current"] else ("APPLIED" if mig["applied"] else "PENDING")
                marker = "*" if mig["current"] else (" " if mig["applied"] else " ")
                print(f"{marker} v{mig['version']:<3} [{status:<8}] {mig['description']}")

            print("="*80)
            print(f"Current schema version: {current_version}")
            return 0

        # Migrate forward
        if args.to:
            dry_run_msg = " [DRY RUN]" if args.dry_run else ""
            print(f"\nMigrating to schema v{args.to}{dry_run_msg}...")
            manager.migrate_to(args.to, dry_run=args.dry_run)

            if not args.dry_run:
                print(f"✓ Migration to v{args.to} completed successfully")
            else:
                print(f"✓ Migration validation passed (dry run)")

            return 0

        # Rollback
        if args.rollback:
            dry_run_msg = " [DRY RUN]" if args.dry_run else ""
            print(f"\nRolling back to schema v{args.rollback}{dry_run_msg}...")
            manager.rollback_to(args.rollback, dry_run=args.dry_run)

            if not args.dry_run:
                print(f"✓ Rollback to v{args.rollback} completed successfully")
            else:
                print(f"✓ Rollback validation passed (dry run)")

            return 0

        # No action specified
        print("ERROR: Must specify --list, --to, or --rollback", file=sys.stderr)
        return 1

    except Exception as e:
        logger.error(f"Migration failed: {e}", exc_info=args.verbose)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_aggregate(args: argparse.Namespace) -> int:
    """
    Aggregate benchmark data into time-series trends.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Load heavy dependencies
    deps = _import_heavy_deps()
    TimeSeriesAggregator = deps['TimeSeriesAggregator']

    try:
        # Get database path
        if args.db:
            db_path = Path(args.db)
        else:
            db_path = get_benchmark_db_path()

        # Create aggregator
        aggregator = TimeSeriesAggregator(db_path=db_path)

        # Create baseline
        if args.baseline:
            if not args.model or not args.device:
                print("ERROR: --baseline requires --model and --device", file=sys.stderr)
                return 1

            print(f"\nCreating {args.type} baseline for {args.model}/{args.device}...")
            baseline_id = aggregator.create_baseline(
                model_id=args.model,
                device=args.device,
                baseline_type=args.type,
                days_back=args.lookback_days
            )

            if baseline_id:
                print(f"✓ Baseline {baseline_id} created successfully")
            else:
                print("⚠ Insufficient data for baseline (need at least 10 samples)")
                return 1

            return 0

        # Aggregate all models
        if args.all:
            print(f"\nAggregating all models (lookback: {args.lookback_days} days)...")
            trends_created = aggregator.aggregate_all(lookback_days=args.lookback_days)
            print(f"✓ Created {trends_created} trend records")
            return 0

        # Aggregate specific model
        if args.model and args.device:
            print(f"\nAggregating {args.model}/{args.device} (lookback: {args.lookback_days} days)...")
            trends_created = aggregator.aggregate_model(
                model_id=args.model,
                device=args.device,
                lookback_days=args.lookback_days
            )
            print(f"✓ Created {trends_created} trend records")
            return 0

        # No action specified
        print("ERROR: Must specify --all or (--model and --device)", file=sys.stderr)
        return 1

    except Exception as e:
        logger.error(f"Aggregation failed: {e}", exc_info=args.verbose)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_retention(args: argparse.Namespace) -> int:
    """
    Execute data retention policies.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Load heavy dependencies
    deps = _import_heavy_deps()
    RetentionEngine = deps['RetentionEngine']

    try:
        db_path = Path(args.db) if args.db else get_benchmark_db_path()

        if not db_path.exists():
            logger.error(f"Database not found: {db_path}")
            print(f"ERROR: Benchmark database not found at {db_path}", file=sys.stderr)
            return 1

        engine = RetentionEngine(db_path)

        # Status command
        if args.status:
            status = engine.get_retention_status()

            print("\nRetention Policy Status")
            print("=" * 80)
            print(f"Total policies: {status['total_policies']}")
            print(f"Enabled: {status['enabled_policies']}, Disabled: {status['disabled_policies']}")
            print()

            print("Policies:")
            print("-" * 80)
            for policy in status["policies"]:
                enabled_str = "ENABLED" if policy["enabled"] else "DISABLED"
                print(f"  {policy['name']:<30} {enabled_str:<10} {policy['retention_days']:>4}d")
                print(f"    Table: {policy['table']:<20} Rows: {policy['rows_total']:>8} To delete: {policy['rows_to_delete']:>8}")
                if policy["last_cleanup"]:
                    print(f"    Last cleanup: {policy['last_cleanup'][:19]}")
                print()

            return 0

        # Run retention
        if args.run:
            dry_run_msg = " [DRY RUN]" if args.dry_run else ""
            print(f"\nExecuting retention policies{dry_run_msg}...")

            policies = args.policies.split(",") if args.policies else None
            results = engine.execute_retention(policy_names=policies, dry_run=args.dry_run)

            print()
            print("Results:")
            print("-" * 80)
            total_deleted = 0
            for result in results:
                action = "Would delete" if result.dry_run else "Deleted"
                status = "ERROR" if result.error else "OK"
                print(f"  {result.policy_name:<30} {status:<6} {action} {result.rows_deleted:>8} rows")
                if result.error:
                    print(f"    Error: {result.error}")
                total_deleted += result.rows_deleted

            print()
            print(f"Total: {total_deleted} rows {'would be ' if args.dry_run else ''}deleted")

            # Vacuum if requested and not dry run
            if args.vacuum and not args.dry_run:
                print("\nVacuuming database...")
                reduction = engine.vacuum_database()
                print(f"Reclaimed {reduction:,} bytes")

            return 0

        # No action specified
        print("ERROR: Must specify --run or --status", file=sys.stderr)
        return 1

    except Exception as e:
        logger.error(f"Retention failed: {e}", exc_info=args.verbose)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_export(args: argparse.Namespace) -> int:
    """
    Export benchmark data to various formats.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Load heavy dependencies
    deps = _import_heavy_deps()
    BenchmarkExporter = deps['BenchmarkExporter']
    ExportFilter = deps['ExportFilter']

    try:
        db_path = Path(args.db) if args.db else get_benchmark_db_path()

        if not db_path.exists():
            logger.error(f"Database not found: {db_path}")
            print(f"ERROR: Benchmark database not found at {db_path}", file=sys.stderr)
            return 1

        exporter = BenchmarkExporter(db_path)

        # Build filter
        filter_obj = None
        if args.start_date or args.end_date or args.model or args.device:
            filter_obj = ExportFilter(
                start_date=args.start_date,
                end_date=args.end_date,
                model_ids=args.model.split(",") if args.model else None,
                devices=args.device.split(",") if args.device else None,
            )

        # Progress callback
        def progress_callback(progress):
            if args.verbose:
                print(f"  {progress.table}: {progress.rows_exported}/{progress.total_rows} ({progress.percent_complete:.1f}%)")

        output_path = Path(args.output)

        # Export based on format
        if args.format == "csv":
            result = exporter.export_csv(
                output_path,
                filter=filter_obj,
                compress=args.compress,
                progress_callback=progress_callback if args.verbose else None,
            )
        elif args.format == "json":
            result = exporter.export_json(
                output_path,
                filter=filter_obj,
                compress=args.compress,
                progress_callback=progress_callback if args.verbose else None,
                pretty_print=args.pretty,
            )
        elif args.format == "sqlite":
            result = exporter.export_sqlite(
                output_path,
                filter=filter_obj,
                progress_callback=progress_callback if args.verbose else None,
            )
        else:
            print(f"ERROR: Unknown format: {args.format}", file=sys.stderr)
            return 1

        # Print result
        if result.error:
            print(f"ERROR: Export failed: {result.error}", file=sys.stderr)
            return 1

        print()
        print("Export completed:")
        print("-" * 60)
        print(f"Format:          {result.format}")
        print(f"Output:          {result.output_path}")
        print(f"Tables:          {', '.join(result.tables_exported)}")
        print(f"Rows exported:   {result.rows_exported:,}")
        print(f"File size:       {result.file_size_bytes:,} bytes")
        print(f"Compressed:      {result.compressed}")
        print(f"Duration:        {result.duration_seconds:.2f}s")

        return 0

    except Exception as e:
        logger.error(f"Export failed: {e}", exc_info=args.verbose)
        print(f"ERROR: {e}", file=sys.stderr)
        return 1


def cmd_archive(args: argparse.Namespace) -> int:
    """
    Manage benchmark data archives.

    Args:
        args: Parsed command-line arguments

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    # Load heavy dependencies
    deps = _import_heavy_deps()
    BenchmarkArchiver = deps['BenchmarkArchiver']

    try:
        db_path = Path(args.db) if args.db else get_benchmark_db_path()
        archive_dir = Path(args.archive_dir) if args.archive_dir else None

        archiver = BenchmarkArchiver(db_path, archive_dir=archive_dir)

        # List archives
        if args.list:
            archives = archiver.list_archives()

            print("\nAvailable Archives")
            print("=" * 100)

            if not archives:
                print("No archives found.")
                return 0

            for archive in archives:
                compressed = "[GZIP]" if archive.compressed else ""
                print(f"\n{archive.archive_id} {compressed}")
                print(f"  Path:      {archive.archive_path}")
                print(f"  Created:   {archive.created_at[:19]}")
                print(f"  Data:      {archive.data_start_date[:10] if archive.data_start_date else 'N/A'} to {archive.data_end_date[:10] if archive.data_end_date else 'N/A'}")
                print(f"  Runs:      {archive.total_runs:,}")
                print(f"  Results:   {archive.total_results:,}")
                print(f"  Size:      {archive.file_size_bytes:,} bytes")

            # Print summary
            summary = archiver.get_archive_summary()
            print()
            print("-" * 100)
            print(f"Total: {summary['archive_count']} archives, {summary['total_size_bytes']:,} bytes")

            return 0

        # Create archive
        if args.create:
            if not args.before:
                print("ERROR: --before DATE is required for archive creation", file=sys.stderr)
                return 1

            if not db_path.exists():
                print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
                return 1

            print(f"\nCreating archive for data before {args.before}...")

            result = archiver.create_archive(
                before_date=args.before,
                compress=args.compress,
                delete_after_archive=args.delete_after,
            )

            if not result.success:
                print(f"ERROR: Archive creation failed: {result.error}", file=sys.stderr)
                return 1

            if result.archive_path is None:
                print("No data found to archive.")
                return 0

            print()
            print("Archive created:")
            print("-" * 60)
            print(f"Path:            {result.archive_path}")
            print(f"Runs archived:   {result.metadata.total_runs:,}")
            print(f"Results:         {result.metadata.total_results:,}")
            print(f"File size:       {result.metadata.file_size_bytes:,} bytes")
            print(f"Duration:        {result.duration_seconds:.2f}s")
            if result.rows_deleted > 0:
                print(f"Rows deleted:    {result.rows_deleted:,}")

            return 0

        # Restore archive
        if args.restore:
            if not db_path.exists():
                print(f"ERROR: Database not found: {db_path}", file=sys.stderr)
                return 1

            print(f"\nRestoring from archive: {args.restore}...")

            result = archiver.restore_archive(args.restore)

            if not result.success:
                print(f"ERROR: Restore failed: {result.error}", file=sys.stderr)
                return 1

            print()
            print("Archive restored:")
            print("-" * 60)
            print(f"Archive:         {result.archive_path}")
            print(f"Tables:          {', '.join(result.tables_restored)}")
            print(f"Rows restored:   {result.rows_restored:,}")
            print(f"Duration:        {result.duration_seconds:.2f}s")

            return 0

        # Rotate archives
        if args.rotate:
            print(f"\nRotating archives (keeping {args.keep} most recent)...")

            deleted = archiver.rotate_archives(keep_count=args.keep)

            print(f"Deleted {deleted} old archives.")
            return 0

        # No action specified
        print("ERROR: Must specify --list, --create, --restore, or --rotate", file=sys.stderr)
        return 1

    except Exception as e:
        logger.error(f"Archive operation failed: {e}", exc_info=args.verbose)
        print(f"ERROR: {e}", file=sys.stderr)
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

    parser.add_argument(
        "--version",
        action="version",
        version=f"%(prog)s {get_version()}",
        help="Show program version and exit",
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

    # --- migrate command ---
    migrate_parser = subparsers.add_parser(
        "migrate",
        help="Manage database schema migrations",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Migrate to latest schema version
  python -m src.benchmarking.cli migrate --to 8

  # List available migrations
  python -m src.benchmarking.cli migrate --list

  # Dry run migration (validate only)
  python -m src.benchmarking.cli migrate --to 8 --dry-run

  # Rollback to previous version
  python -m src.benchmarking.cli migrate --rollback 7
        """,
    )
    migrate_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    migrate_parser.add_argument("--to", type=int, help="Target schema version (migrate forward)")
    migrate_parser.add_argument("--rollback", type=int, help="Rollback to schema version (migrate backward)")
    migrate_parser.add_argument("--list", action="store_true", help="List available migrations")
    migrate_parser.add_argument("--dry-run", action="store_true", help="Validate migration without executing")

    # --- aggregate command ---
    aggregate_parser = subparsers.add_parser(
        "aggregate",
        help="Aggregate benchmark data into time-series trends",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Aggregate all models (last 90 days)
  python -m src.benchmarking.cli aggregate --all

  # Aggregate specific model
  python -m src.benchmarking.cli aggregate --model m2m100_418m --device cpu

  # Create performance baseline
  python -m src.benchmarking.cli aggregate --baseline --model m2m100_418m --device cpu --type weekly
        """,
    )
    aggregate_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    aggregate_parser.add_argument("--all", action="store_true", help="Aggregate all models/devices")
    aggregate_parser.add_argument("--model", help="Model ID to aggregate")
    aggregate_parser.add_argument("--device", help="Device to aggregate")
    aggregate_parser.add_argument("--lookback-days", type=int, default=90, help="Days to look back (default: 90)")
    aggregate_parser.add_argument("--baseline", action="store_true", help="Create performance baseline")
    aggregate_parser.add_argument("--type", default="weekly", choices=["daily", "weekly", "monthly"], help="Baseline type")

    # --- retention command ---
    retention_parser = subparsers.add_parser(
        "retention",
        help="Execute data retention policies",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Show retention policy status
  python -m src.benchmarking.cli retention --status

  # Dry run (show what would be deleted)
  python -m src.benchmarking.cli retention --run --dry-run

  # Execute retention and vacuum database
  python -m src.benchmarking.cli retention --run --vacuum

  # Execute specific policies
  python -m src.benchmarking.cli retention --run --policies benchmark_results_90d
        """,
    )
    retention_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    retention_parser.add_argument("--status", action="store_true", help="Show retention policy status")
    retention_parser.add_argument("--run", action="store_true", help="Execute retention policies")
    retention_parser.add_argument("--dry-run", action="store_true", help="Show what would be deleted without deleting")
    retention_parser.add_argument("--policies", help="Comma-separated policy names to execute (default: all enabled)")
    retention_parser.add_argument("--vacuum", action="store_true", help="Vacuum database after retention")

    # --- export command ---
    export_parser = subparsers.add_parser(
        "export",
        help="Export benchmark data to various formats",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Export to CSV
  python -m src.benchmarking.cli export --format csv --output export/

  # Export to JSON with compression
  python -m src.benchmarking.cli export --format json --output export.json.gz --compress

  # Export to SQLite backup
  python -m src.benchmarking.cli export --format sqlite --output backup.db

  # Export with filters
  python -m src.benchmarking.cli export --format json --output filtered.json --model m2m100_418m --device cpu --start-date 2024-01-01
        """,
    )
    export_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    export_parser.add_argument("--format", required=True, choices=["csv", "json", "sqlite"], help="Export format")
    export_parser.add_argument("--output", required=True, help="Output path (file or directory)")
    export_parser.add_argument("--compress", action="store_true", help="Compress output with gzip (csv/json only)")
    export_parser.add_argument("--pretty", action="store_true", help="Pretty-print JSON output")
    export_parser.add_argument("--start-date", help="Filter: start date (YYYY-MM-DD)")
    export_parser.add_argument("--end-date", help="Filter: end date (YYYY-MM-DD)")
    export_parser.add_argument("--model", help="Filter: comma-separated model IDs")
    export_parser.add_argument("--device", help="Filter: comma-separated devices")

    # --- archive command ---
    archive_parser = subparsers.add_parser(
        "archive",
        help="Manage benchmark data archives",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # List archives
  python -m src.benchmarking.cli archive --list

  # Create archive for data before a date
  python -m src.benchmarking.cli archive --create --before 2024-01-01

  # Create compressed archive and delete source data
  python -m src.benchmarking.cli archive --create --before 2024-01-01 --compress --delete-after

  # Restore from archive
  python -m src.benchmarking.cli archive --restore archive_20240115_120000

  # Rotate archives (keep 5 most recent)
  python -m src.benchmarking.cli archive --rotate --keep 5
        """,
    )
    archive_parser.add_argument("--db", help="Database path (default: data/benchmarks/benchmarks.db or from config)")
    archive_parser.add_argument("--archive-dir", help="Archive directory (default: data/archives)")
    archive_parser.add_argument("--list", action="store_true", help="List all archives")
    archive_parser.add_argument("--create", action="store_true", help="Create new archive")
    archive_parser.add_argument("--before", help="Archive data before this date (YYYY-MM-DD)")
    archive_parser.add_argument("--compress", action="store_true", help="Compress archive with gzip")
    archive_parser.add_argument("--delete-after", action="store_true", help="Delete source data after archiving")
    archive_parser.add_argument("--restore", help="Restore from archive (archive name)")
    archive_parser.add_argument("--rotate", action="store_true", help="Rotate old archives")
    archive_parser.add_argument("--keep", type=int, default=5, help="Number of archives to keep when rotating")

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
    elif args.command == "migrate":
        return cmd_migrate(args)
    elif args.command == "aggregate":
        return cmd_aggregate(args)
    elif args.command == "retention":
        return cmd_retention(args)
    elif args.command == "export":
        return cmd_export(args)
    elif args.command == "archive":
        return cmd_archive(args)
    else:
        parser.print_help()
        return 1


if __name__ == "__main__":
    sys.exit(main())
