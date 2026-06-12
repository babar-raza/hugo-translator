#!/usr/bin/env python3
"""
Benchmark Matrix + E2E Orchestrator.

Orchestrates the complete benchmark and E2E validation pipeline:
1. Create stratified corpus (if needed)
2. Run benchmark matrix (languages × models × devices)
3. Run E2E pipeline on real content
4. Generate final matrix report

Features:
- Checkpoint/resume support for long-running benchmarks
- Configurable subset mode for testing
- Comprehensive reporting
"""

import argparse
import logging
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

logging.basicConfig(level=logging.INFO, format="%(asctime)s - %(levelname)s - %(message)s")
logger = logging.getLogger(__name__)


def run_command(
    script: str,
    args: list[str],
    description: str,
    capture_output: bool = False,
) -> str | None:
    """
    Run a Python script as a subprocess.

    Args:
        script: Path to Python script
        args: Command-line arguments
        description: Human-readable description for logging
        capture_output: Whether to capture and return output

    Returns:
        Output if capture_output=True, None otherwise

    Raises:
        subprocess.CalledProcessError: If command fails
    """
    cmd = [sys.executable, script] + args
    logger.info(f"\n{'=' * 60}")
    logger.info(f"{description}")
    logger.info(f"Command: {' '.join(cmd)}")
    logger.info(f"{'=' * 60}\n")

    result = subprocess.run(
        cmd,
        capture_output=capture_output,
        text=True,
        check=True,
    )

    if capture_output:
        return result.stdout
    return None


def orchestrate(
    run_dir: Path,
    # Corpus options
    content_root: Path | None = None,
    corpus_samples: int = 200,
    # Benchmark matrix options
    benchmark_langs: list[str] | None = None,
    benchmark_models: list[str] | None = None,
    benchmark_devices: list[str] | None = None,
    benchmark_iterations: int = 3,
    # E2E options
    e2e_site: str = "docs.aspose.net",
    e2e_content_root: Path | None = None,
    e2e_output_root: Path | None = None,
    e2e_langs: list[str] | None = None,
    e2e_model_policy: str = "fixed",
    # Control flags
    skip_corpus: bool = False,
    skip_benchmark: bool = False,
    skip_e2e: bool = False,
    skip_report: bool = False,
    resume_benchmark: bool = False,
):
    """
    Orchestrate complete benchmark and E2E pipeline.

    Args:
        run_dir: Directory to store all outputs
        content_root: Root for corpus creation
        corpus_samples: Target samples for stratified corpus
        benchmark_langs: Languages for benchmark matrix (None = all)
        benchmark_models: Models for benchmark matrix (None = all)
        benchmark_devices: Devices for benchmark matrix (None = auto-detect)
        benchmark_iterations: Iterations per benchmark
        e2e_site: Site identifier for E2E
        e2e_content_root: Content root for E2E translation
        e2e_output_root: Output root for E2E translation (git repo)
        e2e_langs: Languages for E2E (None = subset)
        e2e_model_policy: Model selection policy for E2E
        skip_corpus: Skip corpus creation
        skip_benchmark: Skip benchmark matrix
        skip_e2e: Skip E2E pipeline
        skip_report: Skip report generation
        resume_benchmark: Resume benchmark from checkpoint
    """
    run_dir.mkdir(parents=True, exist_ok=True)
    scripts_dir = Path(__file__).parent

    # Paths
    corpus_manifest = Path("data/benchmark_corpus/stratified_manifest.yaml")
    checkpoint_path = run_dir / "benchmark_checkpoint.json"
    benchmark_summary = run_dir / "benchmark_summary.json"
    e2e_report = run_dir / "E2E_REPORT.md"
    final_report = run_dir / "FINAL_MATRIX_REPORT.md"

    # Step 1: Create stratified corpus
    if not skip_corpus:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 1: CREATE STRATIFIED CORPUS")
        logger.info("=" * 60)

        corpus_args = [
            "--output",
            str(corpus_manifest),
            "--target-samples",
            str(corpus_samples),
        ]
        if content_root:
            corpus_args.extend(["--content-root", str(content_root)])

        try:
            run_command(
                script=str(scripts_dir / "create_stratified_corpus.py"),
                args=corpus_args,
                description="Creating stratified benchmark corpus",
            )
        except subprocess.CalledProcessError as e:
            logger.warning(f"Corpus creation failed (continuing with existing): {e}")

    # Step 2: Run benchmark matrix
    if not skip_benchmark:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 2: RUN BENCHMARK MATRIX")
        logger.info("=" * 60)

        matrix_args = [
            "--checkpoint",
            str(checkpoint_path),
            "--output",
            str(benchmark_summary),
            "--iterations",
            str(benchmark_iterations),
        ]

        if benchmark_langs:
            matrix_args.extend(["--langs"] + benchmark_langs)
        if benchmark_models:
            matrix_args.extend(["--models"] + benchmark_models)
        if benchmark_devices:
            matrix_args.extend(["--devices"] + benchmark_devices)
        if resume_benchmark:
            matrix_args.append("--resume")

        run_command(
            script=str(scripts_dir / "benchmark_matrix_runner.py"),
            args=matrix_args,
            description="Running benchmark matrix",
        )

    # Step 3: Run E2E pipeline
    if not skip_e2e and e2e_content_root and e2e_output_root:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 3: RUN E2E PIPELINE")
        logger.info("=" * 60)

        # Default to 2 languages if not specified
        if e2e_langs is None:
            e2e_langs = ["es", "fr"]

        e2e_args = (
            [
                "--site",
                e2e_site,
                "--content-root",
                str(e2e_content_root),
                "--output-root",
                str(e2e_output_root),
                "--langs",
            ]
            + e2e_langs
            + [
                "--model-policy",
                e2e_model_policy,
                "--run-dir",
                str(run_dir),
            ]
        )

        run_command(
            script=str(scripts_dir / "e2e_translation_commit_telemetry.py"),
            args=e2e_args,
            description="Running E2E translation pipeline",
        )

    # Step 4: Generate final report
    if not skip_report:
        logger.info("\n" + "=" * 60)
        logger.info("STEP 4: GENERATE FINAL REPORT")
        logger.info("=" * 60)

        report_args = [
            "--output",
            str(final_report),
        ]

        if benchmark_langs:
            report_args.extend(["--langs"] + benchmark_langs)
        if benchmark_devices:
            report_args.extend(["--device", benchmark_devices[0]])

        run_command(
            script=str(scripts_dir / "generate_matrix_report.py"),
            args=report_args,
            description="Generating final matrix report",
        )

    # Final summary
    logger.info("\n" + "=" * 60)
    logger.info("ORCHESTRATION COMPLETE")
    logger.info("=" * 60)
    logger.info(f"Run directory: {run_dir}")

    if not skip_corpus and corpus_manifest.exists():
        logger.info(f"✓ Corpus manifest: {corpus_manifest}")
    if not skip_benchmark and benchmark_summary.exists():
        logger.info(f"✓ Benchmark summary: {benchmark_summary}")
    if not skip_e2e and e2e_report.exists():
        logger.info(f"✓ E2E report: {e2e_report}")
    if not skip_report and final_report.exists():
        logger.info(f"✓ Final report: {final_report}")

    logger.info("\nNext steps:")
    logger.info(f"1. Review final report: {final_report}")
    logger.info(f"2. Review E2E report: {e2e_report}")
    logger.info("3. Update production config based on recommendations")


def main():
    parser = argparse.ArgumentParser(
        description="Orchestrate benchmark matrix + E2E validation",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  # Full run (all languages, all models, cuda)
  python scripts/orchestrate_benchmark_e2e.py --run-dir runs/full_matrix

  # Test run (3 languages, 3 models, cuda)
  python scripts/orchestrate_benchmark_e2e.py \\
    --run-dir runs/test_matrix \\
    --benchmark-langs es fr de \\
    --benchmark-models m2m100_418m opus_en_es opus_en_fr \\
    --e2e-langs es fr

  # Resume interrupted benchmark
  python scripts/orchestrate_benchmark_e2e.py \\
    --run-dir runs/resumed \\
    --resume-benchmark
        """,
    )

    # Run directory
    parser.add_argument("--run-dir", type=Path, help="Run directory (default: auto-generated)")

    # Corpus options
    parser.add_argument("--content-root", type=Path, help="Content root for corpus creation")
    parser.add_argument(
        "--corpus-samples", type=int, default=200, help="Target samples for stratified corpus"
    )

    # Benchmark matrix options
    parser.add_argument(
        "--benchmark-langs", nargs="+", help="Languages for benchmark (default: all)"
    )
    parser.add_argument("--benchmark-models", nargs="+", help="Models for benchmark (default: all)")
    parser.add_argument(
        "--benchmark-devices",
        nargs="+",
        choices=["cpu", "cuda"],
        help="Devices for benchmark (default: auto-detect)",
    )
    parser.add_argument(
        "--benchmark-iterations", type=int, default=3, help="Iterations per benchmark"
    )

    # E2E options
    parser.add_argument("--e2e-site", default="docs.aspose.net", help="Site identifier for E2E")
    parser.add_argument("--e2e-content-root", type=Path, help="Content root for E2E translation")
    parser.add_argument(
        "--e2e-output-root", type=Path, help="Output root for E2E translation (git repo)"
    )
    parser.add_argument("--e2e-langs", nargs="+", help="Languages for E2E (default: es, fr)")
    parser.add_argument(
        "--e2e-model-policy",
        default="fixed",
        choices=["fixed", "benchmark-best", "fallback-chain"],
        help="Model selection policy for E2E",
    )

    # Control flags
    parser.add_argument("--skip-corpus", action="store_true", help="Skip corpus creation")
    parser.add_argument("--skip-benchmark", action="store_true", help="Skip benchmark matrix")
    parser.add_argument("--skip-e2e", action="store_true", help="Skip E2E pipeline")
    parser.add_argument("--skip-report", action="store_true", help="Skip report generation")
    parser.add_argument(
        "--resume-benchmark", action="store_true", help="Resume benchmark from checkpoint"
    )

    args = parser.parse_args()

    # Set default run directory
    if args.run_dir is None:
        timestamp = datetime.now(UTC).strftime("%Y%m%d_%H%M%S")
        args.run_dir = Path(f"runs/orchestrated_{timestamp}")

    # Run orchestration
    orchestrate(
        run_dir=args.run_dir,
        content_root=args.content_root,
        corpus_samples=args.corpus_samples,
        benchmark_langs=args.benchmark_langs,
        benchmark_models=args.benchmark_models,
        benchmark_devices=args.benchmark_devices,
        benchmark_iterations=args.benchmark_iterations,
        e2e_site=args.e2e_site,
        e2e_content_root=args.e2e_content_root,
        e2e_output_root=args.e2e_output_root,
        e2e_langs=args.e2e_langs,
        e2e_model_policy=args.e2e_model_policy,
        skip_corpus=args.skip_corpus,
        skip_benchmark=args.skip_benchmark,
        skip_e2e=args.skip_e2e,
        skip_report=args.skip_report,
        resume_benchmark=args.resume_benchmark,
    )


if __name__ == "__main__":
    main()
