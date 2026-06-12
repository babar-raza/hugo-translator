#!/usr/bin/env python3
"""
Benchmark translation quality using BLEU and COMET metrics.

Evaluates model translations against reference WMT test sets to measure
translation accuracy.

Usage:
    python scripts/benchmark_quality.py --model m2m100_418m --corpus data/reference_corpus/wmt_en_de.json
"""

import argparse
import json
import logging
import sys
import time
import uuid
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.quality_metrics import QualityMetrics
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun
from src.benchmarking.system_info import SystemInfoCollector
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

logger = logging.getLogger(__name__)


class QualityBenchmark:
    """
    Run quality benchmarks using reference translations.
    """

    def __init__(
        self,
        db_path: Path,
        use_comet: bool = False,
        registry_path: Path = Path("config/model_registry.yaml"),
    ):
        """
        Initialize quality benchmark.

        Args:
            db_path: Path to benchmark database
            use_comet: Whether to calculate COMET scores (slower, requires GPU)
            registry_path: Path to model registry YAML
        """
        self.db = BenchmarkDatabase(db_path)
        self.quality_metrics = QualityMetrics(use_comet=use_comet)
        registry = ModelRegistry(registry_path)
        self.model_loader = ModelLoader(registry=registry)

    def load_reference_corpus(self, corpus_path: Path) -> list[dict]:
        """
        Load reference corpus from JSON file.

        Args:
            corpus_path: Path to reference corpus JSON

        Returns:
            List of corpus samples with source and reference translations
        """
        with open(corpus_path, encoding="utf-8") as f:
            data = json.load(f)

        logger.info(f"Loaded {data['sample_count']} samples for {data['language_pair']}")
        return data["samples"]

    def benchmark_model(
        self,
        model_id: str,
        corpus_path: Path,
        device: str = "cpu",
        max_samples: int = None,
        batch_size: int = 4,
    ) -> BenchmarkRun:
        """
        Benchmark a model's quality on reference corpus.

        Args:
            model_id: Model identifier from registry
            corpus_path: Path to reference corpus
            device: Device to run on (cpu/cuda)
            max_samples: Maximum samples to evaluate (for testing)
            batch_size: Batch size for translation

        Returns:
            BenchmarkRun with quality results
        """
        # Load reference corpus
        corpus_samples = self.load_reference_corpus(corpus_path)
        if max_samples:
            corpus_samples = corpus_samples[:max_samples]

        logger.info(f"Benchmarking {model_id} on {len(corpus_samples)} samples...")

        # Load model
        backend = self.model_loader.load_model(model_id, device=device)
        logger.info(f"Model loaded: {model_id}")

        # Collect system info
        system_info = SystemInfoCollector().collect()

        # Benchmark each sample
        results = []
        start_time = time.time()

        for i, sample in enumerate(corpus_samples):
            sample_start = time.time()

            source_text = sample["source_text"]
            reference_text = sample["reference_text"]
            sample_id = sample["id"]

            # Translate
            try:
                # Use model backend for translation
                if hasattr(backend, "translate"):
                    # Direct translation method (may return list or string)
                    translation_result = backend.translate(
                        source_text,
                        src_lang=sample["source_lang"],
                        tgt_lang=sample["target_lang"],
                    )
                    # Handle list return (batch translation) - take first result
                    translation = (
                        translation_result[0]
                        if isinstance(translation_result, list)
                        else translation_result
                    )
                else:
                    # Tokenize and generate
                    inputs = backend.tokenizer(
                        source_text,
                        return_tensors="pt",
                        padding=True,
                        truncation=True,
                    ).to(backend.model.device)

                    outputs = backend.model.generate(
                        **inputs,
                        max_length=512,
                        num_beams=4,
                    )

                    translation = backend.tokenizer.decode(outputs[0], skip_special_tokens=True)

                # Calculate quality metrics
                quality_score = self.quality_metrics.evaluate_translation(
                    hypothesis=translation,
                    reference=reference_text,
                    source=source_text,
                )

                # Calculate throughput metrics
                sample_duration = time.time() - sample_start
                tokens_input = len(backend.tokenizer.encode(source_text))
                tokens_output = len(backend.tokenizer.encode(translation))
                throughput = tokens_output / sample_duration if sample_duration > 0 else 0

                result = BenchmarkResult(
                    sample_id=sample_id,
                    model_id=model_id,
                    device=device,
                    batch_size=batch_size,
                    duration_seconds=sample_duration,
                    tokens_input=tokens_input,
                    tokens_output=tokens_output,
                    throughput_tokens_per_sec=throughput,
                    bleu_score=quality_score.bleu_score,
                    comet_score=quality_score.comet_score,
                )
                results.append(result)

                if (i + 1) % 10 == 0:
                    logger.info(
                        f"Processed {i + 1}/{len(corpus_samples)} samples "
                        f"(avg BLEU: {sum(r.bleu_score for r in results) / len(results):.2f})"
                    )

            except Exception as e:
                logger.error(f"Failed to benchmark sample {sample_id}: {e}")
                continue

        total_duration = time.time() - start_time

        # Create benchmark run
        run = BenchmarkRun(
            run_id=f"quality_bench_{model_id}_{uuid.uuid4().hex[:8]}",
            model_id=model_id,
            device=device,
            batch_sizes=[batch_size],
            iterations=1,
            corpus_category=corpus_path.stem,
            purpose=f"Quality benchmark on {corpus_path.name}",
            tags=["quality", "bleu", "wmt"],
            total_duration_seconds=total_duration,
            timestamp_utc=system_info.collected_at_utc,
            metadata={
                "corpus_path": str(corpus_path),
                "sample_count": len(results),
                "avg_bleu": sum(r.bleu_score for r in results) / len(results) if results else 0,
                "avg_comet": sum(r.comet_score for r in results if r.comet_score is not None)
                / len([r for r in results if r.comet_score is not None])
                if any(r.comet_score for r in results)
                else None,
            },
            system_info=system_info,
            results=results,
        )

        # Save to database
        self.db.save_run(run)
        logger.info(f"Saved quality benchmark run: {run.run_id}")

        return run


def parse_args() -> argparse.Namespace:
    """Parse command-line arguments."""
    parser = argparse.ArgumentParser(
        description="Benchmark translation quality using BLEU and COMET",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark single model on EN→DE corpus
  python scripts/benchmark_quality.py --model m2m100_418m --corpus data/reference_corpus/wmt_en_de.json

  # Benchmark with COMET (requires GPU, slower)
  python scripts/benchmark_quality.py --model m2m100_418m --corpus data/reference_corpus/wmt_en_de.json --comet

  # Quick test with 10 samples
  python scripts/benchmark_quality.py --model m2m100_418m --corpus data/reference_corpus/wmt_en_de.json --max-samples 10

  # Benchmark all corpora for a model
  python scripts/benchmark_quality.py --model m2m100_418m --all-corpora
        """,
    )

    parser.add_argument(
        "--model",
        type=str,
        required=True,
        help="Model ID from registry (e.g., m2m100_418m)",
    )

    parser.add_argument(
        "--corpus",
        type=str,
        help="Path to reference corpus JSON file",
    )

    parser.add_argument(
        "--all-corpora",
        action="store_true",
        help="Benchmark all available reference corpora",
    )

    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        choices=["cpu", "cuda"],
        help="Device to run on (default: cpu)",
    )

    parser.add_argument(
        "--max-samples",
        type=int,
        help="Maximum samples to evaluate (for quick testing)",
    )

    parser.add_argument(
        "--batch-size",
        type=int,
        default=4,
        help="Batch size for translation (default: 4)",
    )

    parser.add_argument(
        "--comet",
        action="store_true",
        help="Calculate COMET scores (slower, requires GPU)",
    )

    parser.add_argument(
        "--db-path",
        type=str,
        default="data/benchmarks/benchmarks.db",
        help="Path to benchmark database",
    )

    parser.add_argument("-v", "--verbose", action="store_true", help="Enable verbose logging")

    return parser.parse_args()


def main() -> int:
    """Main entry point."""
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Validate arguments
    if not args.all_corpora and not args.corpus:
        logger.error("Must specify --corpus or --all-corpora")
        return 1

    # Get corpus paths
    corpus_paths = []
    if args.all_corpora:
        corpus_dir = Path("data/reference_corpus")
        if not corpus_dir.exists():
            logger.error(f"Reference corpus directory not found: {corpus_dir}")
            return 1
        corpus_paths = list(corpus_dir.glob("wmt_*.json"))
        if not corpus_paths:
            logger.error(f"No reference corpora found in {corpus_dir}")
            return 1
        logger.info(f"Found {len(corpus_paths)} reference corpora")
    else:
        corpus_paths = [Path(args.corpus)]

    # Create benchmark
    benchmark = QualityBenchmark(
        db_path=Path(args.db_path),
        use_comet=args.comet,
    )

    # Run benchmarks
    try:
        for corpus_path in corpus_paths:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Benchmarking on {corpus_path.name}")
            logger.info(f"{'=' * 60}")

            run = benchmark.benchmark_model(
                model_id=args.model,
                corpus_path=corpus_path,
                device=args.device,
                max_samples=args.max_samples,
                batch_size=args.batch_size,
            )

            # Print summary
            if not run.results:
                logger.warning("No results obtained - all samples failed")
                continue

            avg_bleu = sum(r.bleu_score for r in run.results) / len(run.results)
            comet_results = [r.comet_score for r in run.results if r.comet_score is not None]
            avg_comet = sum(comet_results) / len(comet_results) if comet_results else None

            logger.info(f"\n{'=' * 60}")
            logger.info("Quality Benchmark Results")
            logger.info(f"{'=' * 60}")
            logger.info(f"Model: {args.model}")
            logger.info(f"Corpus: {corpus_path.name}")
            logger.info(f"Samples: {len(run.results)}")
            logger.info(f"Average BLEU: {avg_bleu:.2f}")
            if avg_comet is not None:
                logger.info(f"Average COMET: {avg_comet:.4f}")
            logger.info(f"Run ID: {run.run_id}")
            logger.info(f"{'=' * 60}\n")

        logger.info("Quality benchmarks completed successfully!")
        return 0

    except Exception as e:
        logger.error(f"Quality benchmark failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
