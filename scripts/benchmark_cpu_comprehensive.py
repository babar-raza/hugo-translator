#!/usr/bin/env python3
"""
Comprehensive CPU benchmarking for translation models.

Compares HuggingFace vs CTranslate2 backends with various batch sizes,
thread counts, and quantization levels. Results saved to BenchmarkDatabase.

Usage:
    python scripts/benchmark_cpu_comprehensive.py \
        --models m2m100_418m,m2m100_418m_ct2 \
        --batch-sizes 4,8,16 \
        --iterations 3 \
        --save-to-db data/benchmarks/cpu.db \
        --corpus tiny

Features:
    - Compares HF vs CT2 on CPU
    - Tests multiple batch sizes and thread counts
    - Measures throughput, memory, latency
    - Saves results to benchmark database
    - Gracefully handles missing CT2 models
"""

import argparse
import json
import logging
import platform
import sys
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import psutil

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo
from src.model_runtime.cpu_optimizer import CPUOptimizer
from src.model_runtime.hardware import HardwareDetector
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

logger = logging.getLogger(__name__)


class CPUBenchmarkRunner:
    """
    Comprehensive CPU benchmark runner.

    Compares HF vs CT2 backends with various configurations and saves
    results to the benchmark database from TC-01.
    """

    def __init__(
        self,
        model_ids: List[str],
        batch_sizes: List[int],
        thread_counts: Optional[List[int]] = None,
        iterations: int = 3,
        corpus_path: Optional[Path] = None,
        db_path: Optional[Path] = None,
    ):
        """
        Initialize CPU benchmark runner.

        Args:
            model_ids: List of model IDs to benchmark
            batch_sizes: List of batch sizes to test
            thread_counts: List of thread counts to test (None = auto-detect)
            iterations: Number of iterations per configuration
            corpus_path: Path to benchmark corpus JSON file
            db_path: Path to benchmark database
        """
        self.model_ids = model_ids
        self.batch_sizes = batch_sizes
        self.thread_counts = thread_counts or [self._detect_optimal_threads()]
        self.iterations = iterations
        self.corpus_path = corpus_path
        self.db_path = db_path

        # Locate registry file
        registry_path = Path(__file__).parent.parent / "config" / "model_registry.yaml"
        self.registry = ModelRegistry(registry_path)
        self.hardware = HardwareDetector()
        self.database = BenchmarkDatabase(db_path) if db_path else None

        # Load corpus samples
        self.corpus_samples = self._load_corpus()

        logger.info(
            f"Initialized CPU benchmark: {len(model_ids)} models, "
            f"{len(batch_sizes)} batch sizes, {len(self.thread_counts)} thread counts, "
            f"{iterations} iterations, {len(self.corpus_samples)} samples"
        )

    def _detect_optimal_threads(self) -> int:
        """
        Detect optimal thread count using CPU optimizer.

        Returns:
            Recommended thread count
        """
        optimizer = CPUOptimizer()
        config = optimizer.optimize()
        return config.num_threads

    def _load_corpus(self) -> List[Dict[str, Any]]:
        """
        Load benchmark corpus from JSON file.

        Returns:
            List of corpus samples with 'id' and 'text_en' fields

        Raises:
            FileNotFoundError: If corpus file doesn't exist
            ValueError: If corpus is empty or malformed
        """
        if not self.corpus_path or not self.corpus_path.exists():
            # Fallback to synthetic samples
            logger.warning("Corpus file not found, using synthetic samples")
            return [
                {"id": f"synthetic_{i}", "text_en": f"Sample text {i}" * 10}
                for i in range(10)
            ]

        try:
            with open(self.corpus_path, "r", encoding="utf-8") as f:
                samples = json.load(f)

            if not samples:
                raise ValueError("Corpus is empty")

            if not all("id" in s and "text_en" in s for s in samples):
                raise ValueError("Corpus samples must have 'id' and 'text_en' fields")

            logger.info(f"Loaded {len(samples)} samples from {self.corpus_path}")
            return samples

        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse corpus JSON: {e}")
            raise ValueError(f"Invalid corpus JSON: {e}")

    def run_all_benchmarks(self) -> List[BenchmarkRun]:
        """
        Run all benchmark configurations.

        Returns:
            List of BenchmarkRun objects with results

        Tests each combination of:
        - Model (HF, CT2, CT2-INT8, etc.)
        - Batch size
        - Thread count
        """
        all_runs = []

        for model_id in self.model_ids:
            logger.info(f"\n{'='*60}")
            logger.info(f"Benchmarking model: {model_id}")
            logger.info(f"{'='*60}")

            # Check if model is available
            if not self._check_model_available(model_id):
                logger.warning(f"Model {model_id} not available, skipping")
                continue

            for thread_count in self.thread_counts:
                for batch_size in self.batch_sizes:
                    logger.info(
                        f"\nConfiguration: threads={thread_count}, batch_size={batch_size}"
                    )

                    try:
                        run = self._benchmark_configuration(
                            model_id=model_id,
                            batch_size=batch_size,
                            thread_count=thread_count,
                        )

                        all_runs.append(run)

                        # Save to database if available
                        if self.database:
                            self.database.save_run(run)
                            logger.info(f"Saved run {run.run_id} to database")

                    except Exception as e:
                        logger.error(
                            f"Failed to benchmark {model_id} "
                            f"(threads={thread_count}, batch={batch_size}): {e}",
                            exc_info=True,
                        )
                        continue

        logger.info(f"\nCompleted {len(all_runs)} benchmark runs")
        return all_runs

    def _check_model_available(self, model_id: str) -> bool:
        """
        Check if model is available for benchmarking.

        Args:
            model_id: Model identifier

        Returns:
            True if model can be loaded, False otherwise

        For CT2 models, checks if conversion has been performed.
        """
        try:
            model_info = self.registry.get_model(model_id)
            if not model_info:
                logger.warning(f"Model {model_id} not found in registry")
                return False

            # For CT2 models, check if local_path exists
            if model_info.backend == "ctranslate2":
                if not model_info.local_path:
                    logger.warning(
                        f"CT2 model {model_id} missing local_path - run converter first"
                    )
                    return False

                if not Path(model_info.local_path).exists():
                    logger.warning(
                        f"CT2 model path {model_info.local_path} not found - run converter first"
                    )
                    return False

            return True

        except KeyError:
            logger.warning(f"Model {model_id} not found in registry")
            return False
        except Exception as e:
            logger.error(f"Failed to check model availability: {e}")
            return False

    def _benchmark_configuration(
        self, model_id: str, batch_size: int, thread_count: int
    ) -> BenchmarkRun:
        """
        Benchmark a specific configuration.

        Args:
            model_id: Model identifier
            batch_size: Batch size to test
            thread_count: Thread count to use

        Returns:
            BenchmarkRun with results for all corpus samples

        Measures:
        - Throughput (tokens/sec)
        - Latency (duration)
        - Peak memory (MB)
        """
        run_id = f"cpu_bench_{model_id}_{batch_size}_{thread_count}_{uuid.uuid4().hex[:8]}"

        # Configure CPU optimization
        optimizer = CPUOptimizer(num_threads_override=thread_count)
        config = optimizer.optimize()

        # Collect system info
        system_info = self._collect_system_info()

        # Load model
        start_time = time.perf_counter()
        model_loader = ModelLoader(registry=self.registry, device="cpu")

        try:
            model_info = self.registry.get_model(model_id)
            logger.info(f"Loading model {model_id} ({model_info.backend})...")

            model, tokenizer = model_loader.load_model(model_id, device="cpu")

            load_duration = time.perf_counter() - start_time
            logger.info(f"Model loaded in {load_duration:.2f}s")

        except Exception as e:
            logger.error(f"Failed to load model {model_id}: {e}")
            raise

        # Run benchmark iterations
        results = []
        total_start = time.perf_counter()

        for iteration in range(self.iterations):
            logger.info(f"Iteration {iteration + 1}/{self.iterations}")

            for sample in self.corpus_samples:
                result = self._benchmark_sample(
                    model=model,
                    tokenizer=tokenizer,
                    sample=sample,
                    model_id=model_id,
                    batch_size=batch_size,
                )
                results.append(result)

        total_duration = time.perf_counter() - total_start

        # Create benchmark run
        run = BenchmarkRun(
            run_id=run_id,
            model_id=model_id,
            device="cpu",
            batch_sizes=[batch_size],
            iterations=self.iterations,
            corpus_category=self.corpus_path.stem if self.corpus_path else "synthetic",
            purpose="cpu_optimization",
            tags=["cpu", "comprehensive", f"threads_{thread_count}"],
            system_info=system_info,
            results=results,
            total_duration_seconds=total_duration,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            metadata={
                "thread_count": thread_count,
                "batch_size": batch_size,
                "iterations": self.iterations,
                "corpus_size": len(self.corpus_samples),
            },
        )

        # Log summary
        avg_throughput = sum(r.throughput_tokens_per_sec for r in results) / len(results)
        avg_memory = sum(r.peak_memory_mb for r in results if r.peak_memory_mb) / max(
            1, sum(1 for r in results if r.peak_memory_mb)
        )

        logger.info(
            f"Completed {model_id}: "
            f"avg_throughput={avg_throughput:.1f} tok/s, "
            f"avg_memory={avg_memory:.1f} MB"
        )

        return run

    def _benchmark_sample(
        self,
        model: Any,
        tokenizer: Any,
        sample: Dict[str, Any],
        model_id: str,
        batch_size: int,
    ) -> BenchmarkResult:
        """
        Benchmark a single corpus sample.

        Args:
            model: Loaded model instance
            tokenizer: Loaded tokenizer instance
            sample: Corpus sample with 'id' and 'text_en'
            model_id: Model identifier
            batch_size: Batch size (for metadata)

        Returns:
            BenchmarkResult with timing and memory metrics

        Measures translation latency and peak memory for the sample.
        """
        sample_id = sample["id"]
        text = sample["text_en"]

        # Measure baseline memory
        baseline_memory_mb = psutil.Process().memory_info().rss / 1024 / 1024

        # Tokenize input
        try:
            inputs = tokenizer(
                text,
                return_tensors="pt",
                padding=True,
                truncation=True,
                max_length=512,
            )
            tokens_input = inputs["input_ids"].shape[1]

        except Exception as e:
            logger.error(f"Failed to tokenize sample {sample_id}: {e}")
            return BenchmarkResult(
                sample_id=sample_id,
                model_id=model_id,
                device="cpu",
                batch_size=batch_size,
                duration_seconds=0.0,
                tokens_input=0,
                tokens_output=0,
                throughput_tokens_per_sec=0.0,
                peak_memory_mb=None,
                errors=[str(e)],
            )

        # Run translation
        start_time = time.perf_counter()
        errors = []

        try:
            # Generate translation
            outputs = model.generate(
                inputs["input_ids"],
                max_length=512,
                num_beams=1,  # Greedy for speed
                early_stopping=True,
            )

            # Decode output
            translation = tokenizer.decode(outputs[0], skip_special_tokens=True)
            tokens_output = outputs.shape[1]

        except Exception as e:
            logger.error(f"Failed to translate sample {sample_id}: {e}")
            tokens_output = 0
            errors.append(str(e))

        duration = time.perf_counter() - start_time

        # Measure peak memory
        peak_memory_mb = psutil.Process().memory_info().rss / 1024 / 1024
        memory_delta_mb = peak_memory_mb - baseline_memory_mb

        # Calculate throughput
        total_tokens = tokens_input + tokens_output
        throughput = total_tokens / duration if duration > 0 else 0.0

        return BenchmarkResult(
            sample_id=sample_id,
            model_id=model_id,
            device="cpu",
            batch_size=batch_size,
            duration_seconds=duration,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            throughput_tokens_per_sec=throughput,
            peak_memory_mb=memory_delta_mb,
            errors=errors,
        )

    def _collect_system_info(self) -> SystemInfo:
        """
        Collect system information for benchmark metadata.

        Returns:
            SystemInfo with hardware and platform details

        Uses HardwareDetector for consistency with other benchmarks.
        """
        hw_info = self.hardware.detect()

        # Get CPU model
        try:
            cpu_model = platform.processor()
            if not cpu_model.strip():
                cpu_model = platform.machine()
        except Exception:
            cpu_model = "Unknown CPU"

        # Get versions
        try:
            import torch

            torch_version = torch.__version__
        except ImportError:
            torch_version = "not_installed"

        try:
            import transformers

            transformers_version = transformers.__version__
        except ImportError:
            transformers_version = "not_installed"

        return SystemInfo(
            cpu_model=cpu_model,
            cpu_cores=hw_info.cpu_count,
            total_ram_gb=hw_info.total_ram_gb,
            gpu_model=None,  # CPU benchmarks only
            gpu_vram_gb=None,
            os_name=platform.system(),
            os_version=platform.release(),
            python_version=platform.python_version(),
            torch_version=torch_version,
            transformers_version=transformers_version,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
        )

    def print_summary(self, runs: List[BenchmarkRun]) -> None:
        """
        Print benchmark summary to console.

        Args:
            runs: List of completed benchmark runs

        Outputs comparison table with key metrics.
        """
        if not runs:
            logger.warning("No benchmark runs to summarize")
            return

        print("\n" + "=" * 80)
        print("CPU BENCHMARK SUMMARY")
        print("=" * 80)

        # Group by model
        by_model: Dict[str, List[BenchmarkRun]] = {}
        for run in runs:
            if run.model_id not in by_model:
                by_model[run.model_id] = []
            by_model[run.model_id].append(run)

        # Print comparison table
        print(
            f"\n{'Model':<30} {'Batch':<8} {'Threads':<10} {'Throughput':<15} {'Memory':<12}"
        )
        print("-" * 80)

        for model_id, model_runs in sorted(by_model.items()):
            for run in model_runs:
                batch_size = run.batch_sizes[0] if run.batch_sizes else 0
                thread_count = run.metadata.get("thread_count", "?")

                # Calculate averages
                avg_throughput = (
                    sum(r.throughput_tokens_per_sec for r in run.results) / len(run.results)
                    if run.results
                    else 0.0
                )

                memory_values = [r.peak_memory_mb for r in run.results if r.peak_memory_mb]
                avg_memory = sum(memory_values) / len(memory_values) if memory_values else 0.0

                print(
                    f"{model_id:<30} {batch_size:<8} {thread_count:<10} "
                    f"{avg_throughput:<15.1f} {avg_memory:<12.1f}"
                )

        print("\n" + "=" * 80)


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments.

    Returns:
        Parsed arguments
    """
    parser = argparse.ArgumentParser(
        description="Comprehensive CPU benchmarking for translation models",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Compare HF vs CT2 with multiple batch sizes
  python scripts/benchmark_cpu_comprehensive.py \\
      --models m2m100_418m,m2m100_418m_ct2 \\
      --batch-sizes 4,8,16 \\
      --iterations 3 \\
      --save-to-db data/benchmarks/cpu.db \\
      --corpus tiny

  # Quick test with tiny corpus
  python scripts/benchmark_cpu_comprehensive.py \\
      --models m2m100_418m \\
      --batch-sizes 4,8 \\
      --iterations 1 \\
      --corpus tiny

  # Test multiple thread counts
  python scripts/benchmark_cpu_comprehensive.py \\
      --models m2m100_418m_ct2 \\
      --batch-sizes 8 \\
      --threads 1,2,4,8 \\
      --iterations 2 \\
      --save-to-db data/benchmarks/cpu.db
        """,
    )

    parser.add_argument(
        "--models",
        type=str,
        required=True,
        help="Comma-separated list of model IDs to benchmark (e.g., m2m100_418m,m2m100_418m_ct2)",
    )

    parser.add_argument(
        "--batch-sizes",
        type=str,
        default="4,8,16",
        help="Comma-separated list of batch sizes to test (default: 4,8,16)",
    )

    parser.add_argument(
        "--threads",
        type=str,
        default=None,
        help="Comma-separated list of thread counts to test (default: auto-detect optimal)",
    )

    parser.add_argument(
        "--iterations",
        type=int,
        default=3,
        help="Number of iterations per configuration (default: 3)",
    )

    parser.add_argument(
        "--corpus",
        type=str,
        default="tiny",
        help="Corpus name (tiny/small/medium) or path to JSON file (default: tiny)",
    )

    parser.add_argument(
        "--save-to-db",
        type=str,
        default=None,
        help="Path to benchmark database for saving results (optional)",
    )

    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose logging",
    )

    return parser.parse_args()


def main() -> int:
    """
    Main entry point for CPU benchmarking script.

    Returns:
        Exit code (0 for success, 1 for failure)
    """
    args = parse_args()

    # Configure logging
    log_level = logging.DEBUG if args.verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    # Parse arguments
    model_ids = [m.strip() for m in args.models.split(",")]
    batch_sizes = [int(b.strip()) for b in args.batch_sizes.split(",")]
    thread_counts = (
        [int(t.strip()) for t in args.threads.split(",")] if args.threads else None
    )

    # Resolve corpus path
    if args.corpus in ["tiny", "small", "medium"]:
        corpus_path = (
            Path(__file__).parent.parent / "data" / "benchmark_corpus" / f"{args.corpus}.json"
        )
    else:
        corpus_path = Path(args.corpus)

    if not corpus_path.exists():
        logger.error(f"Corpus file not found: {corpus_path}")
        return 1

    # Resolve database path
    db_path = Path(args.save_to_db) if args.save_to_db else None

    # Run benchmarks
    try:
        runner = CPUBenchmarkRunner(
            model_ids=model_ids,
            batch_sizes=batch_sizes,
            thread_counts=thread_counts,
            iterations=args.iterations,
            corpus_path=corpus_path,
            db_path=db_path,
        )

        runs = runner.run_all_benchmarks()

        # Print summary
        runner.print_summary(runs)

        if db_path:
            logger.info(f"\nResults saved to database: {db_path}")

        return 0

    except Exception as e:
        logger.error(f"Benchmark failed: {e}", exc_info=True)
        return 1


if __name__ == "__main__":
    sys.exit(main())
