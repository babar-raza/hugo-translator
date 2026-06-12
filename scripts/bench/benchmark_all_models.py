#!/usr/bin/env python3
"""
Benchmark all registered models comprehensively.

Runs performance benchmarks for all models in the registry, skipping
models that have already been benchmarked.

Usage:
    python scripts/benchmark_all_models.py --device cpu --batch-sizes 4,8
    python scripts/benchmark_all_models.py --device cuda --skip-benchmarked
"""

import argparse
import logging
import sqlite3
import sys
import time
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.runner import BenchmarkRunner
from src.model_runtime.registry import ModelRegistry

logger = logging.getLogger(__name__)


def get_benchmarked_models(db_path: Path) -> set:
    """
    Get set of models that have already been benchmarked.

    Args:
        db_path: Path to benchmark database

    Returns:
        Set of model IDs with existing benchmark data
    """
    db = sqlite3.connect(db_path)
    cursor = db.cursor()
    cursor.execute("SELECT DISTINCT model_id FROM benchmark_results")
    benchmarked = {row[0] for row in cursor.fetchall()}
    db.close()
    return benchmarked


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Benchmark all registered translation models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark all unbenchmarked models on CPU
  python scripts/benchmark_all_models.py --device cpu

  # Benchmark specific batch sizes
  python scripts/benchmark_all_models.py --batch-sizes 4,8,16

  # Force re-benchmark all models
  python scripts/benchmark_all_models.py --no-skip-benchmarked

  # Benchmark only small models (< 1B params)
  python scripts/benchmark_all_models.py --max-size 1000000000

  # GPU benchmarking
  python scripts/benchmark_all_models.py --device cuda --batch-sizes 8,16
        """,
    )

    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device to run benchmarks on (default: cpu)",
    )

    parser.add_argument(
        "--batch-sizes",
        type=str,
        default="4,8",
        help="Comma-separated list of batch sizes to test (default: 4,8)",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=2,
        help="Number of iterations per batch size (default: 2)",
    )

    parser.add_argument(
        "--corpus",
        type=str,
        default="data/benchmark_corpus/tiny.json",
        help="Corpus to use for benchmarking (default: tiny.json)",
    )

    parser.add_argument(
        "--skip-benchmarked",
        action="store_true",
        default=True,
        help="Skip models that have already been benchmarked (default: True)",
    )

    parser.add_argument(
        "--no-skip-benchmarked",
        action="store_true",
        help="Re-benchmark all models, even if already benchmarked",
    )

    parser.add_argument(
        "--max-size",
        type=int,
        help="Skip models with more than N parameters (e.g., 1000000000 for 1B)",
    )

    parser.add_argument(
        "--models",
        type=str,
        help="Comma-separated list of specific model IDs to benchmark",
    )

    parser.add_argument(
        "--exclude-backends",
        type=str,
        help="Comma-separated list of backends to exclude (e.g., 'ctranslate2')",
    )

    parser.add_argument(
        "--registry",
        type=str,
        default="config/model_registry.yaml",
        help="Path to model registry file",
    )

    parser.add_argument(
        "--db-path",
        type=str,
        default="data/benchmarks/benchmarks.db",
        help="Path to benchmark database",
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    return parser.parse_args()


def estimate_model_size(model_id: str, hf_model_name: str) -> int:
    """
    Estimate model parameter count from model ID or name.

    Args:
        model_id: Model identifier
        hf_model_name: HuggingFace model name

    Returns:
        Estimated parameter count
    """
    # Extract size from model ID or name
    name = (model_id + " " + hf_model_name).lower()

    if "3b" in name or "3000m" in name:
        return 3_000_000_000
    elif "1.3b" in name or "1300m" in name:
        return 1_300_000_000
    elif "1.2b" in name or "1200m" in name:
        return 1_200_000_000
    elif "600m" in name:
        return 600_000_000
    elif "418m" in name:
        return 418_000_000
    elif "300m" in name:
        return 300_000_000
    elif "base" in name:
        return 220_000_000  # T5-base is ~220M
    elif "small" in name:
        return 60_000_000  # T5-small is ~60M
    else:
        return 500_000_000  # Default estimate


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Load registry
    with open(args.registry) as f:
        registry_data = yaml.safe_load(f)

    all_models = registry_data.get("models", [])
    logger.info(f"Found {len(all_models)} models in registry")

    # Get already benchmarked models
    skip_benchmarked = args.skip_benchmarked and not args.no_skip_benchmarked
    benchmarked = set()
    if skip_benchmarked:
        benchmarked = get_benchmarked_models(Path(args.db_path))
        logger.info(f"Found {len(benchmarked)} models with existing benchmarks")

    # Filter models
    models_to_benchmark = []
    excluded_backends = set()
    if args.exclude_backends:
        excluded_backends = {b.strip() for b in args.exclude_backends.split(",")}

    specific_models = set()
    if args.models:
        specific_models = {m.strip() for m in args.models.split(",")}

    for model in all_models:
        model_id = model["model_id"]

        # Skip if specific models requested and this isn't one
        if specific_models and model_id not in specific_models:
            continue

        # Skip if already benchmarked
        if skip_benchmarked and model_id in benchmarked:
            logger.info(f"Skipping {model_id} (already benchmarked)")
            continue

        # Skip if backend excluded
        backend = model.get("backend", "huggingface")
        if backend in excluded_backends:
            logger.info(f"Skipping {model_id} (backend {backend} excluded)")
            continue

        # Skip if too large
        if args.max_size:
            hf_name = model.get("hf_model_name", "")
            size = estimate_model_size(model_id, hf_name)
            if size > args.max_size:
                logger.info(
                    f"Skipping {model_id} (estimated {size / 1e9:.1f}B params > {args.max_size / 1e9:.1f}B limit)"
                )
                continue

        models_to_benchmark.append(model)

    if not models_to_benchmark:
        logger.warning("No models to benchmark!")
        return 0

    logger.info(f"\n{'=' * 60}")
    logger.info(f"Benchmarking {len(models_to_benchmark)} models")
    logger.info(f"{'=' * 60}")
    for model in models_to_benchmark:
        logger.info(f"  - {model['model_id']}: {model['name']}")
    logger.info(f"{'=' * 60}\n")

    # Parse batch sizes
    batch_sizes = [int(b.strip()) for b in args.batch_sizes.split(",")]

    # Create benchmark runner
    registry = ModelRegistry(args.registry)
    runner = BenchmarkRunner(
        registry=registry,
        db_path=Path(args.db_path),
    )

    # Benchmark each model
    successful = 0
    failed = 0
    start_time = time.time()

    for i, model in enumerate(models_to_benchmark, 1):
        model_id = model["model_id"]
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Benchmarking [{i}/{len(models_to_benchmark)}]: {model_id}")
        logger.info(f"{'=' * 60}")

        try:
            result = runner.run_benchmark(
                model_id=model_id,
                device=args.device,
                batch_sizes=batch_sizes,
                iterations=args.iterations,
                corpus_filter="tiny",
                corpus_source="json",
            )

            if result and result.results:
                avg_throughput = sum(r.throughput_tokens_per_sec for r in result.results) / len(
                    result.results
                )
                logger.info(
                    f"✅ {model_id}: {len(result.results)} samples, avg {avg_throughput:.1f} tok/s"
                )
                successful += 1
            else:
                logger.warning(f"⚠️  {model_id}: No results obtained")
                failed += 1

        except Exception as e:
            logger.error(f"❌ {model_id}: Benchmark failed - {e}")
            failed += 1
            continue

    total_duration = time.time() - start_time

    # Print summary
    logger.info(f"\n{'=' * 60}")
    logger.info("Comprehensive Benchmarking Complete")
    logger.info(f"{'=' * 60}")
    logger.info(f"Models benchmarked: {successful}/{len(models_to_benchmark)}")
    logger.info(f"Successful: {successful}")
    logger.info(f"Failed: {failed}")
    logger.info(f"Total duration: {total_duration / 60:.1f} minutes")
    logger.info(f"Database: {args.db_path}")
    logger.info(f"{'=' * 60}")

    return 0 if failed == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
