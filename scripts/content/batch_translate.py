#!/usr/bin/env python3
"""
Batch Translation Script with Optimization.

Translate multiple files with optional batch optimization.
"""

import argparse
import json
import logging
import sys
import time
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.model_runtime import ModelLoader
from src.model_runtime.registry import ModelRegistry
from src.orchestration import create_batch_optimizer
from src.tm import TranslationMemory
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.translation_engine import TranslationEngine
from src.utils.config_loader import ConfigService

logging.basicConfig(level=logging.INFO, stream=sys.stdout)
logger = logging.getLogger(__name__)


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Batch translate Hugo content")

    parser.add_argument("--input", type=Path, required=True, help="Input directory")
    parser.add_argument("--output", type=Path, required=True, help="Output directory")
    parser.add_argument("--site-id", default="default", help="Site ID")
    parser.add_argument("--langs", nargs="+", default=["es", "fr"], help="Target languages")
    parser.add_argument("--optimize", action="store_true", help="Enable batch optimization")
    parser.add_argument("--batch-size", type=int, default=32, help="Initial batch size")
    parser.add_argument("--report", type=Path, help="Output report path")
    parser.add_argument(
        "--parallel",
        action="store_true",
        help="Process files in parallel (default: sequential)",
    )
    parser.add_argument(
        "--config-root",
        type=Path,
        default=Path("config"),
        help="Path to configuration directory (default: ./config)",
    )
    parser.add_argument(
        "--device",
        choices=["auto", "cpu", "cuda"],
        default="cpu",
        help="Device for model inference (default: cpu)",
    )
    parser.add_argument(
        "--model",
        default=None,
        help="Override model ID from registry (e.g., nllb_200_600m)",
    )

    # TMO-04: TM Cache Override Options
    parser.add_argument(
        "--override-mode",
        choices=["normal", "bypass", "refresh", "validate"],
        default=None,
        help="TM cache override mode: normal (default cache behavior), "
        "bypass (skip cache, don't update), refresh (skip cache, update with new), "
        "validate (use cache but also translate for comparison)",
    )
    parser.add_argument(
        "--override-filter-patterns",
        nargs="+",
        default=None,
        help="Source text patterns (regex) to apply override to",
    )
    parser.add_argument(
        "--override-filter-langs",
        nargs="+",
        default=None,
        help="Target languages to apply override to",
    )
    parser.add_argument(
        "--override-filter-keys",
        nargs="+",
        default=None,
        help="Frontmatter keys to apply override to",
    )

    args = parser.parse_args()

    # Initialize components
    config_service = ConfigService(args.config_root)
    global_config = config_service.global_config

    tm_data_dir = Path(global_config.tm_data_dir)
    if not tm_data_dir.is_absolute():
        tm_data_dir = Path.cwd() / tm_data_dir
    tm_data_dir.mkdir(parents=True, exist_ok=True)

    # Build Translation Memory layers
    l1_cache = L1Cache(max_size=50000)
    l2_path = tm_data_dir / "l2_lmdb"
    l2_path.mkdir(parents=True, exist_ok=True)
    l2_persistent = L2PersistentTM(str(l2_path))

    tm = TranslationMemory(l1_cache=l1_cache, l2_persistent=l2_persistent)

    # Initialize model registry/loader
    registry_path = args.config_root / "model_registry.yaml"
    model_registry = ModelRegistry(registry_path)

    device = args.device
    if device == "auto":
        try:
            import torch

            device = "cuda" if torch.cuda.is_available() else "cpu"
        except Exception:
            device = "cpu"
    elif device == "cuda":
        try:
            import torch

            if not torch.cuda.is_available():
                logger.warning("CUDA requested but not available, falling back to CPU")
                device = "cpu"
        except Exception:
            logger.warning("PyTorch not available, falling back to CPU")
            device = "cpu"

    logger.info(f"Using model device: {device}")

    if device == "cuda" and args.parallel:
        logger.warning("Parallel execution is not supported on CUDA runs; forcing sequential mode.")
        args.parallel = False

    model_loader = ModelLoader(registry=model_registry, device=device)

    # TMO-04: Build override filters if any specified
    override_filters = None
    if args.override_filter_patterns or args.override_filter_langs or args.override_filter_keys:
        override_filters = {}
        if args.override_filter_patterns:
            override_filters["source_patterns"] = args.override_filter_patterns
        if args.override_filter_langs:
            override_filters["target_langs"] = args.override_filter_langs
        if args.override_filter_keys:
            override_filters["frontmatter_keys"] = args.override_filter_keys

    engine = TranslationEngine(
        config_service=config_service,
        tm=tm,
        model_loader=model_loader,
        override_mode=args.override_mode,
        override_filters=override_filters,
        model_id=args.model,
        output_dir_override=args.output,
    )

    # Log override mode if set
    if args.override_mode:
        logger.info(f"TM override mode: {args.override_mode}")
        if override_filters:
            logger.info(f"Override filters: {override_filters}")

    # Initialize optimizer if requested
    if args.optimize:
        optimizer = create_batch_optimizer(
            initial_batch_size=args.batch_size,
            enable_optimization=True,
        )
        logger.info("Batch optimization enabled")
    else:
        optimizer = None

    # Find files
    files = list(args.input.glob("**/*.md"))
    logger.info(f"Found {len(files)} files to translate")

    # Translate
    start_time = time.time()

    result = engine.translate_directory(
        site_id=args.site_id,
        directory=args.input,
        target_langs=args.langs,
        parallel=args.parallel,
    )

    duration = time.time() - start_time

    # Report
    print(f"\n{'=' * 60}")
    print("Batch Translation Complete")
    print(f"{'=' * 60}")
    print(f"Files processed: {result.successful_files}/{result.total_files}")
    print(f"Duration: {duration:.1f}s")
    print(f"Throughput: {result.total_files / duration:.1f} files/sec")

    if optimizer:
        stats = optimizer.get_stats()
        print("\nOptimization Stats:")
        print(f"  Batches: {stats.batches_processed}")
        print(f"  Avg batch size: {stats.avg_batch_size:.1f}")
        print(f"  OOM events: {stats.oom_events}")

    # TMO-04: Show override stats if override mode was used
    if args.override_mode:
        override_stats = engine.get_override_stats()
        print("\nTM Override Stats:")
        print(f"  Mode: {override_stats.get('mode', 'unknown')}")
        print(f"  Bypasses: {override_stats.get('override_bypasses', 0)}")
        print(f"  Force translates: {override_stats.get('force_translates', 0)}")
        print(f"  Cache updates: {override_stats.get('cache_updates', 0)}")

    # Save report if requested
    if args.report:
        report = {
            "files_processed": result.successful_files,
            "files_failed": result.failed_files,
            "duration_seconds": duration,
            "throughput_files_per_sec": result.total_files / duration if duration > 0 else 0,
        }

        if optimizer:
            report["optimization"] = {
                "batches": stats.batches_processed,
                "avg_batch_size": stats.avg_batch_size,
                "oom_events": stats.oom_events,
            }

        # TMO-04: Include override stats in report
        if args.override_mode:
            override_stats = engine.get_override_stats()
            report["override"] = {
                "mode": args.override_mode,
                "filters": override_filters,
                "stats": override_stats,
            }

        with open(args.report, "w") as f:
            json.dump(report, f, indent=2)

        logger.info(f"Report saved to {args.report}")

    return 0 if result.successful_files > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
