#!/usr/bin/env python3
"""
Benchmark Matrix Runner with Checkpoint/Resume Support.

Runs comprehensive benchmarks across:
- Languages: All 36 target languages or subset
- Models: All registered models or subset
- Devices: CPU, CUDA, or both

Features:
- Checkpoint/resume for interrupted runs
- Filters specialized models by supported language pairs
- Stores results in benchmark database
- Progress tracking and ETA estimation
"""

import argparse
import json
import logging
import sys
import time
from dataclasses import asdict, dataclass, field
from datetime import UTC, datetime
from pathlib import Path

import yaml

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.benchmarking.runner import BenchmarkRunner
from src.model_runtime.hardware import HardwareDetector
from src.model_runtime.registry import ModelRegistry

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


@dataclass
class MatrixCheckpoint:
    """Checkpoint for resumable matrix runs."""

    matrix_id: str
    started_at: str
    total_jobs: int
    completed_jobs: list[str] = field(default_factory=list)
    failed_jobs: list[str] = field(default_factory=list)
    checkpoint_path: str | None = None

    def save(self, path: Path):
        """Save checkpoint to disk."""
        path.parent.mkdir(parents=True, exist_ok=True)
        with open(path, "w", encoding="utf-8") as f:
            json.dump(asdict(self), f, indent=2)
        logger.info(
            f"Saved checkpoint: {len(self.completed_jobs)}/{self.total_jobs} jobs completed"
        )

    @classmethod
    def load(cls, path: Path) -> "MatrixCheckpoint":
        """Load checkpoint from disk."""
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
        return cls(**data)


def load_target_languages() -> list[str]:
    """Load target languages from config/target_languages.yaml."""
    config_path = Path("config/target_languages.yaml")
    if not config_path.exists():
        logger.warning(f"Target languages config not found: {config_path}")
        return ["es", "fr", "de", "ru", "zh", "ja"]  # Fallback

    with open(config_path, encoding="utf-8") as f:
        config = yaml.safe_load(f)

    languages = [lang["iso_code"] for lang in config.get("languages", [])]
    logger.info(f"Loaded {len(languages)} target languages from config")
    return languages


def filter_models_by_language_pair(models: list[dict], src_lang: str, tgt_lang: str) -> list[dict]:
    """
    Filter models by supported language pairs.

    Args:
        models: List of model definitions from registry
        src_lang: Source language code (e.g., 'en')
        tgt_lang: Target language code (e.g., 'es')

    Returns:
        Filtered list of models that support this language pair
    """
    supported_models = []

    for model in models:
        supported_pairs = model.supported_pairs

        # If 'all', model supports all language pairs
        if supported_pairs == "all":
            supported_models.append(model)
            continue

        # Check if (src_lang, tgt_lang) in supported pairs
        if isinstance(supported_pairs, list):
            for pair in supported_pairs:
                # Pairs are tuples in ModelInfo
                if isinstance(pair, (list, tuple)) and len(pair) == 2:
                    if pair[0] == src_lang and pair[1] == tgt_lang:
                        supported_models.append(model)
                        break

    return supported_models


def generate_matrix_jobs(
    languages: list[str],
    models: list[dict],
    devices: list[str],
    src_lang: str = "en",
) -> list[dict]:
    """
    Generate benchmark jobs for the matrix.

    Args:
        languages: List of target language codes
        models: List of model definitions
        devices: List of devices ('cpu', 'cuda')
        src_lang: Source language (default: 'en')

    Returns:
        List of job dictionaries with keys: job_id, model_id, device, src_lang, tgt_lang
    """
    jobs = []

    for tgt_lang in languages:
        # Filter models by language pair support
        supported_models = filter_models_by_language_pair(models, src_lang, tgt_lang)

        for model in supported_models:
            model_id = model.model_id

            for device in devices:
                # Skip GPU if model is CPU-optimal and we have many jobs
                optimal_device = model.optimal_device
                if device == "cuda" and optimal_device == "cpu" and len(languages) > 10:
                    # Skip GPU benchmarking for CPU-optimal models in large matrices
                    logger.debug(f"Skipping GPU benchmark for CPU-optimal model: {model_id}")
                    continue

                job_id = f"{model_id}_{device}_{src_lang}_{tgt_lang}"
                jobs.append(
                    {
                        "job_id": job_id,
                        "model_id": model_id,
                        "device": device,
                        "src_lang": src_lang,
                        "tgt_lang": tgt_lang,
                    }
                )

    logger.info(f"Generated {len(jobs)} benchmark jobs")
    return jobs


def run_matrix_benchmark(
    languages: list[str] | None = None,
    models: list[str] | None = None,
    devices: list[str] | None = None,
    src_lang: str = "en",
    corpus_filter: str = "tiny",
    corpus_source: str = "json",
    batch_sizes: list[int] | None = None,
    iterations: int = 3,
    checkpoint_path: Path | None = None,
    resume: bool = False,
    db_path: Path | None = None,
) -> dict:
    """
    Run benchmark matrix with checkpoint/resume support.

    Args:
        languages: Target languages to benchmark (None = all)
        models: Model IDs to benchmark (None = all)
        devices: Devices to test ('cpu', 'cuda', or both)
        src_lang: Source language (default: 'en')
        corpus_filter: Corpus size filter
        corpus_source: Corpus source ('json' or 'markdown')
        batch_sizes: Batch sizes to test (default: [4, 8, 16])
        iterations: Iterations per benchmark
        checkpoint_path: Path to checkpoint file
        resume: Whether to resume from checkpoint
        db_path: Path to benchmark database

    Returns:
        Dictionary with run summary
    """
    # Initialize registry and database
    registry = ModelRegistry()
    db_path = db_path or Path("data/benchmarks/benchmarks.db")
    runner = BenchmarkRunner(registry=registry, db_path=db_path)

    # Set defaults
    if languages is None:
        languages = load_target_languages()
    if devices is None:
        devices = ["cuda"] if HardwareDetector().has_cuda else ["cpu"]
    if batch_sizes is None:
        batch_sizes = [4, 8, 16]

    # Get all models or filter by IDs
    all_models = registry.list_models()
    if models is not None:
        all_models = [m for m in all_models if m.model_id in models]

    logger.info("Matrix configuration:")
    logger.info(f"  Languages: {len(languages)}")
    logger.info(f"  Models: {len(all_models)}")
    logger.info(f"  Devices: {devices}")
    logger.info(f"  Source language: {src_lang}")

    # Generate matrix jobs
    jobs = generate_matrix_jobs(
        languages=languages,
        models=all_models,
        devices=devices,
        src_lang=src_lang,
    )

    # Load or create checkpoint
    matrix_id = f"matrix_{datetime.now(UTC).strftime('%Y%m%d_%H%M%S')}"
    checkpoint = None

    if resume and checkpoint_path and checkpoint_path.exists():
        logger.info(f"Resuming from checkpoint: {checkpoint_path}")
        checkpoint = MatrixCheckpoint.load(checkpoint_path)
        completed_job_ids = set(checkpoint.completed_jobs)
        jobs = [job for job in jobs if job["job_id"] not in completed_job_ids]
        logger.info(f"Resuming with {len(jobs)} remaining jobs")
    else:
        checkpoint = MatrixCheckpoint(
            matrix_id=matrix_id,
            started_at=datetime.now(UTC).isoformat(),
            total_jobs=len(jobs),
            checkpoint_path=str(checkpoint_path) if checkpoint_path else None,
        )

    # Run benchmarks
    start_time = time.time()
    results_summary = {
        "matrix_id": matrix_id,
        "started_at": checkpoint.started_at,
        "completed_jobs": 0,
        "failed_jobs": 0,
        "total_duration_seconds": 0,
        "results": [],
    }

    for i, job in enumerate(jobs):
        job_id = job["job_id"]
        logger.info(f"\n{'=' * 60}")
        logger.info(f"Job {i + 1}/{len(jobs)}: {job_id}")
        logger.info(f"{'=' * 60}")

        try:
            # Run benchmark
            run_result = runner.run_benchmark(
                model_id=job["model_id"],
                device=job["device"],
                batch_sizes=batch_sizes,
                iterations=iterations,
                corpus_filter=corpus_filter,
                corpus_source=corpus_source,
                src_lang=job["src_lang"],
                tgt_lang=job["tgt_lang"],
                purpose="matrix_benchmark",
                tags=[f"matrix:{matrix_id}", f"lang:{job['tgt_lang']}"],
            )

            # Mark as completed
            checkpoint.completed_jobs.append(job_id)
            results_summary["completed_jobs"] += 1
            results_summary["results"].append(
                {
                    "job_id": job_id,
                    "run_id": run_result.run_id,
                    "status": "success",
                }
            )

            logger.info(f"✓ Completed job: {job_id}")

        except Exception as e:
            logger.error(f"✗ Failed job {job_id}: {e}")
            checkpoint.failed_jobs.append(job_id)
            results_summary["failed_jobs"] += 1
            results_summary["results"].append(
                {
                    "job_id": job_id,
                    "status": "failed",
                    "error": str(e),
                }
            )

        # Save checkpoint after each job
        if checkpoint_path:
            checkpoint.save(checkpoint_path)

    # Final summary
    results_summary["total_duration_seconds"] = time.time() - start_time
    results_summary["completed_at"] = datetime.now(UTC).isoformat()

    logger.info(f"\n{'=' * 60}")
    logger.info("MATRIX BENCHMARK COMPLETE")
    logger.info(f"{'=' * 60}")
    logger.info(f"Total jobs: {checkpoint.total_jobs}")
    logger.info(f"Completed: {results_summary['completed_jobs']}")
    logger.info(f"Failed: {results_summary['failed_jobs']}")
    logger.info(f"Duration: {results_summary['total_duration_seconds']:.1f}s")

    return results_summary


def main():
    parser = argparse.ArgumentParser(description="Run benchmark matrix with checkpoint/resume")
    parser.add_argument("--langs", nargs="+", help="Target languages (default: all)")
    parser.add_argument("--models", nargs="+", help="Model IDs to benchmark (default: all)")
    parser.add_argument("--devices", nargs="+", choices=["cpu", "cuda"], help="Devices to test")
    parser.add_argument("--src-lang", default="en", help="Source language (default: en)")
    parser.add_argument("--corpus", default="tiny", help="Corpus filter (tiny/small/medium)")
    parser.add_argument(
        "--corpus-source", default="json", choices=["json", "markdown"], help="Corpus source"
    )
    parser.add_argument(
        "--batch-sizes", nargs="+", type=int, default=[4, 8, 16], help="Batch sizes"
    )
    parser.add_argument("--iterations", type=int, default=3, help="Iterations per benchmark")
    parser.add_argument("--checkpoint", type=Path, help="Checkpoint file path")
    parser.add_argument("--resume", action="store_true", help="Resume from checkpoint")
    parser.add_argument("--db-path", type=Path, help="Benchmark database path")
    parser.add_argument("--output", type=Path, help="Output summary JSON path")

    args = parser.parse_args()

    # Set default checkpoint path if not provided
    if args.checkpoint is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        args.checkpoint = Path(f"runs/matrix_{timestamp}/checkpoint.json")

    # Run matrix benchmark
    summary = run_matrix_benchmark(
        languages=args.langs,
        models=args.models,
        devices=args.devices,
        src_lang=args.src_lang,
        corpus_filter=args.corpus,
        corpus_source=args.corpus_source,
        batch_sizes=args.batch_sizes,
        iterations=args.iterations,
        checkpoint_path=args.checkpoint,
        resume=args.resume,
        db_path=args.db_path,
    )

    # Write summary to output file
    if args.output:
        args.output.parent.mkdir(parents=True, exist_ok=True)
        with open(args.output, "w", encoding="utf-8") as f:
            json.dump(summary, f, indent=2)
        logger.info(f"Wrote summary to {args.output}")


if __name__ == "__main__":
    main()
