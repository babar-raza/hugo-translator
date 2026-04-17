"""
Benchmark Runner - Orchestrates benchmarking runs across models and corpus.

This module provides the BenchmarkRunner class that coordinates:
- Model loading via ModelRegistry and ModelLoader
- Corpus management
- System info collection
- Benchmark execution and result persistence

CLI usage:
    python -m src.benchmarking.runner --model m2m100_418m --device cpu --batch-sizes 8,16
"""

import argparse
import logging
import sys
import time
import uuid
from pathlib import Path

from src.benchmarking.corpus import CorpusManager
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun
from src.benchmarking.system_info import SystemInfoCollector
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry
from src.translation_engine.engine import estimate_token_count

try:
    import torch
    TORCH_AVAILABLE = True
except ImportError:
    TORCH_AVAILABLE = False

logger = logging.getLogger(__name__)


def load_corpus(
    corpus_filter: str,
    corpus_source: str = "json",
    corpus_path: str | Path | None = None,
) -> list[dict[str, str]]:
    """
    Load benchmark corpus from JSON or markdown files.

    Args:
        corpus_filter: Corpus size filter ('tiny', 'small', 'medium') or category filter
        corpus_source: Corpus source ('json' or 'markdown')
        corpus_path: Path to metadata.yaml (required for markdown source)

    Returns:
        List of corpus samples with 'id', 'text_en', 'domain' keys

    Raises:
        FileNotFoundError: If corpus file not found
        ValueError: If corpus is empty or invalid
    """
    manager = CorpusManager()

    if corpus_source == "json":
        # Original JSON corpus loading (backward compatible)
        corpus_sizes = {'tiny', 'small', 'medium'}

        # Determine size/category
        if corpus_filter in corpus_sizes:
            size = corpus_filter
            category = None
        else:
            size = "small"  # Default to small corpus for category filters
            category = corpus_filter

        corpus = manager.load_samples(
            source="json",
            size=size,
            category=category,
        )

    elif corpus_source == "markdown":
        # New markdown corpus loading
        if not corpus_path:
            # Try default location
            corpus_path = Path("data") / "benchmark_corpus" / "metadata.yaml"

        # Parse category from corpus_filter if specified
        category = corpus_filter if corpus_filter not in {'tiny', 'small', 'medium'} else None

        corpus = manager.load_samples(
            source="markdown",
            path=corpus_path,
            category=category,
        )

    else:
        raise ValueError(f"Invalid corpus source: {corpus_source}. Must be 'json' or 'markdown'")

    if not corpus:
        raise ValueError(f"Corpus is empty after loading with source={corpus_source}, filter={corpus_filter}")

    return corpus


class BenchmarkRunner:
    """
    Orchestrates benchmark runs across models, devices, and corpus.

    Coordinates ModelRegistry, ModelLoader, corpus management, system info
    collection, and result persistence via BenchmarkDatabase.
    """

    def __init__(
        self,
        registry: ModelRegistry,
        db_path: Path | str | None = None
    ):
        """
        Initialize benchmark runner.

        Args:
            registry: ModelRegistry instance
            db_path: Optional path to benchmark database (if None, results not persisted)
        """
        self.registry = registry
        self.db_path = db_path
        self.db = BenchmarkDatabase(db_path) if db_path else None
        self.system_collector = SystemInfoCollector()
        logger.info(f"Initialized BenchmarkRunner with registry and db_path={db_path}")

    def run_benchmark(
        self,
        model_id: str,
        device: str,
        batch_sizes: list[int],
        iterations: int,
        corpus_filter: str | None = None,
        corpus_source: str = "json",
        corpus_path: str | Path | None = None,
        purpose: str = "benchmark",
        tags: list[str] | None = None,
        max_samples: int | None = None,
        src_lang: str = 'en',
        tgt_lang: str = 'ru',
    ) -> BenchmarkRun:
        """
        Run benchmark for a specific model and configuration.

        Args:
            model_id: Model identifier from registry
            device: Device to run on ('cpu', 'cuda', 'cuda:0', etc.)
            batch_sizes: List of batch sizes to test
            iterations: Number of iterations per batch size
            corpus_filter: Corpus filter ('tiny', 'small', 'medium', or category name)
            corpus_source: Corpus source ('json' or 'markdown')
            corpus_path: Path to metadata.yaml (for markdown source)
            purpose: Purpose description for the run
            tags: Optional tags for categorization
            max_samples: Maximum number of samples to process (for testing)
            src_lang: Source language code (default: 'en')
            tgt_lang: Target language code (default: 'ru')

        Returns:
            BenchmarkRun object with results

        Raises:
            ValueError: If model not found or corpus empty
            RuntimeError: If benchmark execution fails
        """
        run_id = str(uuid.uuid4())[:8]
        tags = tags or []
        corpus_filter = corpus_filter or "tiny"

        logger.info(f"Starting benchmark run {run_id}: model={model_id}, device={device}, "
                   f"batch_sizes={batch_sizes}, iterations={iterations}, corpus={corpus_filter}, "
                   f"source={corpus_source}")

        # Validate model exists
        model_info = self.registry.models.get(model_id)
        if not model_info:
            available = ', '.join(self.registry.models.keys())
            raise ValueError(f"Model '{model_id}' not found in registry. Available: {available}")

        # Check device availability
        if device.startswith('cuda'):
            try:
                import torch
                if not torch.cuda.is_available():
                    raise RuntimeError("CUDA device requested but CUDA is not available")
            except ImportError:
                raise RuntimeError("CUDA device requested but torch is not installed")

        # Collect system info (comprehensive SystemInfo from system_info.py)
        logger.info("Collecting system information...")
        system_info = self.system_collector.collect()

        # Load corpus
        logger.info(f"Loading corpus with filter: {corpus_filter}, source: {corpus_source}")
        corpus = load_corpus(
            corpus_filter=corpus_filter,
            corpus_source=corpus_source,
            corpus_path=corpus_path,
        )

        if max_samples:
            corpus = corpus[:max_samples]
            logger.info(f"Limited corpus to {len(corpus)} samples (max_samples={max_samples})")

        # Initialize model loader
        loader = ModelLoader(self.registry)

        # Track results
        all_results: list[BenchmarkResult] = []
        total_start = time.time()

        try:
            # Load model
            logger.info(f"Loading model {model_id} on {device}...")
            load_start = time.time()
            backend = loader.load_model(model_id, device=device)
            load_duration = time.time() - load_start
            logger.info(f"Model loaded in {load_duration:.2f}s")

            # Run benchmarks for each batch size
            for batch_size in batch_sizes:
                logger.info(f"Running benchmark with batch_size={batch_size}, iterations={iterations}")

                for iteration in range(iterations):
                    logger.info(f"  Iteration {iteration + 1}/{iterations}")

                    # Process corpus in batches
                    for i in range(0, len(corpus), batch_size):
                        batch = corpus[i:i + batch_size]
                        texts = [sample['text_en'] for sample in batch]
                        sample_ids = [sample['id'] for sample in batch]

                        # Benchmark translation
                        result = self._benchmark_translation(
                            backend=backend,
                            texts=texts,
                            sample_ids=sample_ids,
                            model_id=model_id,
                            device=device,
                            batch_size=batch_size,
                            src_lang=src_lang,
                            tgt_lang=tgt_lang,
                        )

                        all_results.extend(result)

                        # Log progress
                        if len(all_results) % 10 == 0:
                            logger.debug(f"  Processed {len(all_results)} samples...")

            total_duration = time.time() - total_start
            logger.info(f"Benchmark completed in {total_duration:.2f}s, {len(all_results)} results")

        except Exception as e:
            logger.error(f"Benchmark failed: {e}", exc_info=True)
            raise RuntimeError(f"Benchmark execution failed: {e}") from e

        finally:
            # Clean up GPU memory if using CUDA
            if device.startswith('cuda') and TORCH_AVAILABLE and torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.debug("GPU memory cache cleared")

            # Unload model
            logger.info("Unloading model...")
            loader.unload_all()

        # Create benchmark run object
        benchmark_run = BenchmarkRun(
            run_id=run_id,
            model_id=model_id,
            device=device,
            batch_sizes=batch_sizes,
            iterations=iterations,
            corpus_category=corpus_filter,
            purpose=purpose,
            tags=tags,
            system_info=system_info,
            results=all_results,
            total_duration_seconds=total_duration,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            metadata={
                "corpus_size": len(corpus),
                "load_duration_seconds": load_duration,
            }
        )

        # Persist to database if configured
        if self.db:
            logger.info(f"Persisting results to database: {self.db_path}")
            self.db.save_run(benchmark_run)
            logger.info(f"Results saved with run_id: {run_id}")

        return benchmark_run

    def _benchmark_translation(
        self,
        backend,
        texts: list[str],
        sample_ids: list[str],
        model_id: str,
        device: str,
        batch_size: int,
        src_lang: str = 'en',
        tgt_lang: str = 'ru',
    ) -> list[BenchmarkResult]:
        """
        Benchmark a single translation batch.

        Args:
            backend: Model backend instance
            texts: Texts to translate
            sample_ids: Sample IDs for tracking
            model_id: Model identifier
            device: Device name
            batch_size: Batch size used
            src_lang: Source language code (default: 'en')
            tgt_lang: Target language code (default: 'ru')

        Returns:
            List of BenchmarkResult objects for each sample
        """
        results = []
        errors = []
        peak_memory_mb = None

        # Reset GPU memory stats before benchmark if using CUDA
        is_cuda = device.startswith('cuda')
        if is_cuda and TORCH_AVAILABLE and torch.cuda.is_available():
            torch.cuda.reset_peak_memory_stats(device=device if ':' in device else None)
            torch.cuda.empty_cache()

        try:
            start_time = time.time()

            # Try to use translate_with_token_counts if available (HuggingFace backend)
            if hasattr(backend, 'translate_with_token_counts'):
                translations, input_tokens, output_tokens = backend.translate_with_token_counts(
                    texts, src_lang=src_lang, tgt_lang=tgt_lang
                )
                # Distribute tokens across batch (rough estimate)
                tokens_per_sample_in = input_tokens // len(texts) if texts else 0
                tokens_per_sample_out = output_tokens // len(texts) if texts else 0
            else:
                # Fallback for CT2 backend: use heuristic token estimation
                translations = backend.translate(texts, src_lang=src_lang, tgt_lang=tgt_lang)
                # Estimate tokens using heuristic
                tokens_per_sample_in = sum(estimate_token_count(t) for t in texts) // len(texts) if texts else 0
                tokens_per_sample_out = sum(estimate_token_count(t) for t in translations) // len(translations) if translations else 0

            duration = time.time() - start_time

            # Capture peak GPU memory after translation
            if is_cuda and TORCH_AVAILABLE and torch.cuda.is_available():
                peak_memory_bytes = torch.cuda.max_memory_allocated(device=device if ':' in device else None)
                peak_memory_mb = peak_memory_bytes / (1024 ** 2)
                logger.debug(f"Peak GPU memory for batch_size={batch_size}: {peak_memory_mb:.2f} MB")

            # Create results for each sample
            for idx, (sample_id, text, translation) in enumerate(zip(sample_ids, texts, translations, strict=False)):
                # Calculate per-sample metrics
                sample_duration = duration / len(texts)
                throughput = (tokens_per_sample_in + tokens_per_sample_out) / sample_duration if sample_duration > 0 else 0

                result = BenchmarkResult(
                    sample_id=sample_id,
                    model_id=model_id,
                    device=device,
                    batch_size=batch_size,
                    duration_seconds=sample_duration,
                    tokens_input=tokens_per_sample_in,
                    tokens_output=tokens_per_sample_out,
                    throughput_tokens_per_sec=throughput,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    peak_memory_mb=peak_memory_mb,
                    errors=[],
                )
                results.append(result)

        except Exception as e:
            # Check if this is an OOM error
            is_oom = False
            if TORCH_AVAILABLE and isinstance(e, torch.cuda.OutOfMemoryError):
                is_oom = True
                error_msg = f"OOM at batch_size={batch_size}"
                logger.error(f"{error_msg}: {e}")

                # Capture memory at OOM
                if torch.cuda.is_available():
                    peak_memory_bytes = torch.cuda.max_memory_allocated(device=device if ':' in device else None)
                    peak_memory_mb = peak_memory_bytes / (1024 ** 2)
                    logger.error(f"Peak GPU memory at OOM: {peak_memory_mb:.2f} MB")

                    # Clean up GPU memory
                    torch.cuda.empty_cache()
            else:
                error_msg = f"Translation failed for batch: {e}"
                logger.error(error_msg)

            errors.append(error_msg)

            # Create error results
            for sample_id in sample_ids:
                result = BenchmarkResult(
                    sample_id=sample_id,
                    model_id=model_id,
                    device=device,
                    batch_size=batch_size,
                    duration_seconds=0.0,
                    tokens_input=0,
                    tokens_output=0,
                    throughput_tokens_per_sec=0.0,
                    src_lang=src_lang,
                    tgt_lang=tgt_lang,
                    peak_memory_mb=peak_memory_mb,
                    errors=errors,
                )
                results.append(result)

        return results


def main():
    """
    CLI entry point for benchmark runner.

    Examples:
        python -m src.benchmarking.runner --model m2m100_418m --device cpu --batch-sizes 8,16
        python -m src.benchmarking.runner --model opus_en_fr --device cpu --iterations 1 --corpus tiny
    """
    parser = argparse.ArgumentParser(
        description="Run translation model benchmarks",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Benchmark on CPU with tiny corpus
  python -m src.benchmarking.runner --model m2m100_418m --device cpu --batch-sizes 8 --iterations 1 --corpus tiny --save-to-db data/benchmarks/dev.db

  # Benchmark on GPU with multiple batch sizes
  python -m src.benchmarking.runner --model m2m100_418m --device cuda --batch-sizes 8,16 --iterations 5 --corpus small --save-to-db data/benchmarks/prod.db

  # Benchmark with custom purpose and tags
  python -m src.benchmarking.runner --model opus_en_fr --device cpu --batch-sizes 4 --iterations 2 --purpose "regression test" --tags baseline,cpu
        """,
    )

    parser.add_argument(
        "--model",
        required=True,
        help="Model ID from registry (e.g., m2m100_418m, opus_en_fr)",
    )

    parser.add_argument(
        "--device",
        default="cpu",
        help="Device to run on (cpu, cuda, cuda:0, etc.)",
    )

    parser.add_argument(
        "--batch-sizes",
        default="8",
        help="Comma-separated batch sizes to test (e.g., 8,16,32)",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=1,
        help="Number of iterations per batch size",
    )

    parser.add_argument(
        "--corpus",
        default="tiny",
        help="Corpus filter: 'tiny', 'small', 'medium', or category name (e.g., 'technical')",
    )

    parser.add_argument(
        "--corpus-source",
        default="json",
        choices=["json", "markdown"],
        help="Corpus source: 'json' (default, synthetic corpus) or 'markdown' (real .md files)",
    )

    parser.add_argument(
        "--corpus-path",
        help="Path to metadata.yaml (required for --corpus-source markdown)",
    )

    parser.add_argument(
        "--purpose",
        default="benchmark",
        help="Purpose description for the run",
    )

    parser.add_argument(
        "--tags",
        help="Comma-separated tags (e.g., baseline,gpu,smoke)",
    )

    parser.add_argument(
        "--save-to-db",
        help="Path to database file to save results (e.g., data/benchmarks/dev.db)",
    )

    parser.add_argument(
        "--max-samples",
        type=int,
        help="Maximum number of samples to process (for testing)",
    )

    parser.add_argument(
        "--registry",
        default="config/model_registry.yaml",
        help="Path to model registry YAML file",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    args = parser.parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Parse batch sizes
    try:
        batch_sizes = [int(bs.strip()) for bs in args.batch_sizes.split(',')]
    except ValueError:
        logger.error(f"Invalid batch sizes: {args.batch_sizes}")
        return 1

    # Parse tags
    tags = [tag.strip() for tag in args.tags.split(',')] if args.tags else []

    # Load registry
    try:
        registry_paths = [Path(p.strip()) for p in args.registry.split(",") if p.strip()]
        missing = [str(p) for p in registry_paths if not p.exists()]
        if missing:
            logger.error(f"Registry file(s) not found: {', '.join(missing)}")
            return 1

        registry = ModelRegistry(args.registry)
        logger.info(f"Loaded registry with {len(registry.models)} models")
    except Exception as e:
        logger.error(f"Failed to load registry: {e}")
        return 1

    # Initialize runner
    try:
        runner = BenchmarkRunner(
            registry=registry,
            db_path=args.save_to_db,
        )
    except Exception as e:
        logger.error(f"Failed to initialize runner: {e}")
        return 1

    # Validate corpus-source and corpus-path
    if args.corpus_source == "markdown" and not args.corpus_path:
        logger.error("--corpus-path is required when using --corpus-source markdown")
        return 1

    # Run benchmark
    try:
        result = runner.run_benchmark(
            model_id=args.model,
            device=args.device,
            batch_sizes=batch_sizes,
            iterations=args.iterations,
            corpus_filter=args.corpus,
            corpus_source=args.corpus_source,
            corpus_path=args.corpus_path,
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

        if args.save_to_db:
            print(f"\nResults saved to: {args.save_to_db}")
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


if __name__ == "__main__":
    sys.exit(main())
