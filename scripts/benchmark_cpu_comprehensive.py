#!/usr/bin/env python3
"""
Comprehensive CPU benchmarking for translation models across 36 languages.

Benchmarks HuggingFace and CTranslate2 backends with various batch sizes,
thread counts, and target languages. Results saved to BenchmarkDatabase.

Usage:
    # Benchmark all 4 models for all 36 languages
    python scripts/benchmark_cpu_comprehensive.py \
        --models m2m100_418m,m2m100_1.2b,nllb_200_600m,nllb_200_1.3b \
        --languages all \
        --batch-sizes 4,8,16 \
        --iterations 3 \
        --save-to-db data/benchmarks/benchmarks.db \
        --corpus tiny

    # Benchmark specific languages only
    python scripts/benchmark_cpu_comprehensive.py \
        --models nllb_200_600m \
        --languages fr,es,de,zh,ja \
        --batch-sizes 8 \
        --iterations 2

Features:
    - Multi-language benchmarking (all 36 target languages)
    - Supports NLLB-200 and M2M100 multilingual models
    - Compares HF vs CT2 on CPU
    - Tests multiple batch sizes and thread counts
    - Measures throughput, memory, latency per language
    - Saves results to benchmark database
    - Progress tracking across languages
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
        target_languages: Optional[List[str]] = None,
        device: str = "cpu",
    ):
        """
        Initialize CPU/GPU benchmark runner.

        Args:
            model_ids: List of model IDs to benchmark
            batch_sizes: List of batch sizes to test
            thread_counts: List of thread counts to test (None = auto-detect, CPU only)
            iterations: Number of iterations per configuration
            corpus_path: Path to benchmark corpus JSON file
            db_path: Path to benchmark database
            target_languages: List of target language codes (None = ['en'])
            device: Device to use ('cpu', 'cuda', 'cuda:0', etc.)
        """
        self.model_ids = model_ids
        self.batch_sizes = batch_sizes
        self.thread_counts = thread_counts or ([self._detect_optimal_threads()] if device == "cpu" else [1])
        self.iterations = iterations
        self.corpus_path = corpus_path
        self.db_path = db_path
        self.target_languages = target_languages or ['en']
        self.device = device

        # Locate registry file
        registry_path = Path(__file__).parent.parent / "config" / "model_registry.yaml"
        self.registry = ModelRegistry(registry_path)
        self.hardware = HardwareDetector()
        self.database = BenchmarkDatabase(db_path) if db_path else None

        # Load corpus samples
        self.corpus_samples = self._load_corpus()

        logger.info(
            f"Initialized benchmark: device={device}, {len(model_ids)} models, "
            f"{len(batch_sizes)} batch sizes, {len(self.thread_counts)} thread counts, "
            f"{iterations} iterations, {len(self.corpus_samples)} samples, "
            f"{len(self.target_languages)} target languages"
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
        - Target language
        - Model (HF, CT2, CT2-INT8, etc.)
        - Batch size
        - Thread count
        """
        all_runs = []
        total_configs = (
            len(self.target_languages)
            * len(self.model_ids)
            * len(self.thread_counts)
            * len(self.batch_sizes)
        )
        completed = 0

        for target_lang in self.target_languages:
            logger.info(f"\n{'='*70}")
            logger.info(f"TARGET LANGUAGE: {target_lang.upper()}")
            logger.info(f"{'='*70}")

            for model_id in self.model_ids:
                logger.info(f"\n{'='*60}")
                logger.info(f"Benchmarking model: {model_id} -> {target_lang}")
                logger.info(f"{'='*60}")

                # Check if model is available
                if not self._check_model_available(model_id):
                    logger.warning(f"Model {model_id} not available, skipping")
                    continue

                for thread_count in self.thread_counts:
                    for batch_size in self.batch_sizes:
                        completed += 1
                        progress_pct = (completed / total_configs) * 100

                        logger.info(
                            f"\nConfiguration [{completed}/{total_configs}] ({progress_pct:.1f}%): "
                            f"lang={target_lang}, threads={thread_count}, batch_size={batch_size}"
                        )

                        try:
                            run = self._benchmark_configuration(
                                model_id=model_id,
                                batch_size=batch_size,
                                thread_count=thread_count,
                                target_language=target_lang,
                            )

                            all_runs.append(run)

                            # Save to database if available
                            if self.database:
                                self.database.save_run(run)
                                logger.info(f"Saved run {run.run_id} to database")

                        except Exception as e:
                            logger.error(
                                f"Failed to benchmark {model_id} -> {target_lang} "
                                f"(threads={thread_count}, batch={batch_size}): {e}",
                                exc_info=True,
                            )
                            continue

        logger.info(f"\n{'='*70}")
        logger.info(f"Completed {len(all_runs)} benchmark runs across {len(self.target_languages)} languages")
        logger.info(f"{'='*70}")
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
        self, model_id: str, batch_size: int, thread_count: int, target_language: str = "en"
    ) -> BenchmarkRun:
        """
        Benchmark a specific configuration.

        Args:
            model_id: Model identifier
            batch_size: Batch size to test
            thread_count: Thread count to use
            target_language: Target language code (ISO 639-1)

        Returns:
            BenchmarkRun with results for all corpus samples

        Measures:
        - Throughput (tokens/sec)
        - Latency (duration)
        - Peak memory (MB)
        """
        device_short = self.device.replace(":", "_")
        run_id = f"{device_short}_bench_{model_id}_{target_language}_{batch_size}_{thread_count}_{uuid.uuid4().hex[:8]}"

        # Configure CPU optimization (CPU only)
        if self.device == "cpu":
            optimizer = CPUOptimizer(num_threads_override=thread_count)
            config = optimizer.optimize()

        # Collect system info
        system_info = self._collect_system_info()

        # Load model
        start_time = time.perf_counter()
        model_loader = ModelLoader(registry=self.registry, device=self.device)

        try:
            model_info = self.registry.get_model(model_id)
            logger.info(f"Loading model {model_id} ({model_info.backend})...")

            backend = model_loader.load_model(model_id, device=self.device)

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
                    model=backend.model,
                    tokenizer=backend.tokenizer,
                    sample=sample,
                    model_id=model_id,
                    batch_size=batch_size,
                    target_language=target_language,
                    device=self.device,
                )
                results.append(result)

        total_duration = time.perf_counter() - total_start

        # Create benchmark run
        run = BenchmarkRun(
            run_id=run_id,
            model_id=model_id,
            device=self.device,
            batch_sizes=[batch_size],
            iterations=self.iterations,
            corpus_category=self.corpus_path.stem if self.corpus_path else "synthetic",
            purpose=f"{self.device}_multilang_benchmark",
            tags=[self.device.split(":")[0], "comprehensive", f"lang_{target_language}", f"threads_{thread_count}"],
            system_info=system_info,
            results=results,
            total_duration_seconds=total_duration,
            timestamp_utc=datetime.now(timezone.utc).isoformat(),
            metadata={
                "thread_count": thread_count,
                "batch_size": batch_size,
                "iterations": self.iterations,
                "corpus_size": len(self.corpus_samples),
                "target_language": target_language,
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
        target_language: str = "en",
        device: str = "cpu",
    ) -> BenchmarkResult:
        """
        Benchmark a single corpus sample.

        Args:
            model: Loaded model instance
            tokenizer: Loaded tokenizer instance
            sample: Corpus sample with 'id' and 'text_en'
            model_id: Model identifier
            batch_size: Batch size (for metadata)
            target_language: Target language code (ISO 639-1)
            device: Device being used ('cpu', 'cuda', etc.)

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
                device=device,
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
            # Determine forced_bos_token_id for target language
            forced_bos_token_id = self._get_target_language_token_id(
                tokenizer, model_id, target_language
            )

            # Generate translation
            generate_kwargs = {
                "max_length": 512,
                "num_beams": 1,  # Greedy for speed
                "early_stopping": True,
            }

            if forced_bos_token_id is not None:
                generate_kwargs["forced_bos_token_id"] = forced_bos_token_id

            outputs = model.generate(
                inputs["input_ids"],
                **generate_kwargs,
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
            device=device,
            batch_size=batch_size,
            duration_seconds=duration,
            tokens_input=tokens_input,
            tokens_output=tokens_output,
            throughput_tokens_per_sec=throughput,
            peak_memory_mb=memory_delta_mb,
            errors=errors,
        )

    def _get_target_language_token_id(
        self, tokenizer: Any, model_id: str, target_language: str
    ) -> Optional[int]:
        """
        Get the forced_bos_token_id for the target language.

        Args:
            tokenizer: Model tokenizer
            model_id: Model identifier
            target_language: Target language code (ISO 639-1)

        Returns:
            Token ID for the target language, or None if not applicable

        For NLLB models: Uses language code format like "fra_Latn"
        For M2M100 models: Uses get_lang_id() method
        """
        try:
            # NLLB models use special language tokens
            if "nllb" in model_id.lower():
                # NLLB language code mapping (ISO 639-1 -> NLLB code)
                nllb_lang_map = {
                    "ar": "arb_Arab", "bg": "bul_Cyrl", "ca": "cat_Latn",
                    "cs": "ces_Latn", "da": "dan_Latn", "de": "deu_Latn",
                    "el": "ell_Grek", "es": "spa_Latn", "fa": "pes_Arab",
                    "fi": "fin_Latn", "fr": "fra_Latn", "he": "heb_Hebr",
                    "hi": "hin_Deva", "hr": "hrv_Latn", "hu": "hun_Latn",
                    "id": "ind_Latn", "it": "ita_Latn", "ja": "jpn_Jpan",
                    "ko": "kor_Hang", "lt": "lit_Latn", "lv": "lav_Latn",
                    "ms": "zsm_Latn", "nl": "nld_Latn", "no": "nob_Latn",
                    "pl": "pol_Latn", "pt": "por_Latn", "ro": "ron_Latn",
                    "ru": "rus_Cyrl", "sk": "slk_Latn", "sr": "srp_Cyrl",
                    "sv": "swe_Latn", "th": "tha_Thai", "tr": "tur_Latn",
                    "uk": "ukr_Cyrl", "vi": "vie_Latn", "zh": "zho_Hans",
                }

                nllb_code = nllb_lang_map.get(target_language)
                if nllb_code:
                    # NLLB uses special tokens like "<fra_Latn>"
                    token = f"{nllb_code}"
                    if hasattr(tokenizer, 'convert_tokens_to_ids'):
                        token_id = tokenizer.convert_tokens_to_ids(token)
                        if token_id != tokenizer.unk_token_id:
                            return token_id
                    logger.warning(f"Could not find NLLB token for {target_language} ({nllb_code})")
                    return None

            # M2M100 models use lang_code_to_id or get_lang_id
            elif "m2m100" in model_id.lower():
                if hasattr(tokenizer, 'get_lang_id'):
                    try:
                        return tokenizer.get_lang_id(target_language)
                    except Exception as e:
                        logger.warning(f"get_lang_id failed for {target_language}: {e}")
                        return None
                elif hasattr(tokenizer, 'lang_code_to_id'):
                    return tokenizer.lang_code_to_id.get(target_language)

            # For other models, no forced token needed
            return None

        except Exception as e:
            logger.warning(f"Failed to get target language token for {target_language}: {e}")
            return None

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

        # Detect GPU info if running on CUDA
        gpu_model = None
        gpu_memory_gb = None
        if self.device.startswith("cuda"):
            try:
                import torch
                if torch.cuda.is_available():
                    device_idx = 0  # Default to first GPU
                    if ":" in self.device:
                        device_idx = int(self.device.split(":")[1])

                    gpu_model = torch.cuda.get_device_name(device_idx)
                    gpu_memory_gb = torch.cuda.get_device_properties(device_idx).total_memory / (1024**3)
            except Exception as e:
                logger.warning(f"Failed to detect GPU info: {e}")

        return SystemInfo(
            cpu_model=cpu_model,
            cpu_cores=hw_info.cpu_count,
            total_ram_gb=hw_info.total_ram_gb,
            gpu_model=gpu_model,
            gpu_memory_gb=gpu_memory_gb,
            os_name=platform.system(),
            os_version=platform.release(),
            python_version=platform.python_version(),
            torch_version=torch_version,
            collected_at_utc=datetime.now(timezone.utc).isoformat(),
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
  # Benchmark all models for all 36 languages
  python scripts/benchmark_cpu_comprehensive.py \\
      --models m2m100_418m,m2m100_1.2b,nllb_200_600m,nllb_200_1.3b \\
      --languages all \\
      --batch-sizes 4,8,16 \\
      --iterations 3 \\
      --save-to-db data/benchmarks/benchmarks.db \\
      --corpus tiny

  # Benchmark specific languages
  python scripts/benchmark_cpu_comprehensive.py \\
      --models nllb_200_600m \\
      --languages fr,es,de,zh,ja \\
      --batch-sizes 8 \\
      --iterations 2 \\
      --save-to-db data/benchmarks/benchmarks.db

  # Quick test with tiny corpus (single language)
  python scripts/benchmark_cpu_comprehensive.py \\
      --models m2m100_418m \\
      --batch-sizes 4,8 \\
      --iterations 1 \\
      --corpus tiny

  # Test multiple thread counts
  python scripts/benchmark_cpu_comprehensive.py \\
      --models m2m100_418m \\
      --batch-sizes 8 \\
      --threads 1,2,4,8 \\
      --iterations 2 \\
      --save-to-db data/benchmarks/benchmarks.db
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
        "--languages",
        type=str,
        default=None,
        help="Comma-separated list of target language codes (ISO 639-1) or 'all' for all 36 languages (default: en only)",
    )

    parser.add_argument(
        "--device",
        type=str,
        default="cpu",
        help="Device to use: 'cpu', 'cuda', 'cuda:0', 'cuda:1', etc. (default: cpu)",
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

    # Parse target languages
    target_languages = None
    if args.languages:
        if args.languages.lower() == "all":
            # Load all 36 languages from config/target_languages.yaml
            import yaml
            config_path = Path(__file__).parent.parent / "config" / "target_languages.yaml"
            if config_path.exists():
                with open(config_path) as f:
                    lang_config = yaml.safe_load(f)
                    target_languages = [lang["iso_code"] for lang in lang_config.get("languages", [])]
                    logger.info(f"Loaded {len(target_languages)} target languages from config")
            else:
                logger.error(f"Target languages config not found: {config_path}")
                return 1
        else:
            # Parse comma-separated language codes
            target_languages = [lang.strip() for lang in args.languages.split(",")]
            logger.info(f"Using {len(target_languages)} target languages: {', '.join(target_languages)}")

    # Run benchmarks
    try:
        runner = CPUBenchmarkRunner(
            model_ids=model_ids,
            batch_sizes=batch_sizes,
            thread_counts=thread_counts,
            iterations=args.iterations,
            corpus_path=corpus_path,
            db_path=db_path,
            target_languages=target_languages,
            device=args.device,
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
