#!/usr/bin/env python3
"""
Benchmark different CLI settings to find optimal configuration for large-scale translation.

Tests combinations of:
- batch-size
- parallel-languages
- load-mode (fp16 vs fp32)
- directory vs file-by-file translation
"""

import argparse
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""

    config_name: str
    batch_size: int | None
    parallel_languages: int | None
    load_mode: str
    translation_mode: str  # "file" or "directory"

    files_count: int
    languages_count: int
    total_duration: float
    throughput_files_per_min: float
    throughput_file_langs_per_min: float  # files × langs per minute

    success: bool
    error: str | None = None

    # GPU metrics
    peak_vram_mb: int | None = None
    avg_gpu_util: float | None = None


class CLIBenchmarker:
    """Benchmarks different CLI configurations."""

    def __init__(self, test_corpus_size: int = 5, target_langs: list[str] = None):
        self.test_corpus_size = test_corpus_size
        self.target_langs = target_langs or ["de", "fr"]
        self.cli_path = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"
        self.results: list[BenchmarkResult] = []

        # Collect test corpus
        self.corpus = self._collect_corpus()

    def _collect_corpus(self) -> list[Path]:
        """Collect test files from kb.aspose.net."""
        kb_slides = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en")

        if not kb_slides.exists():
            raise RuntimeError(f"Corpus path not found: {kb_slides}")

        files = sorted(kb_slides.rglob("*.md"))[: self.test_corpus_size]
        print(f"Test corpus: {len(files)} files")
        return files

    def run_benchmark(
        self,
        config_name: str,
        batch_size: int | None = None,
        parallel_languages: int | None = None,
        load_mode: str = "fp32",
        use_directory: bool = False,
    ) -> BenchmarkResult:
        """Run a single benchmark configuration."""

        print(f"\n{'=' * 80}")
        print(f"Benchmarking: {config_name}")
        print(f"  Batch size: {batch_size or 'auto'}")
        print(f"  Parallel langs: {parallel_languages or 'disabled'}")
        print(f"  Load mode: {load_mode}")
        print(f"  Mode: {'directory' if use_directory else 'file-by-file'}")
        print(f"{'=' * 80}")

        start_time = time.perf_counter()

        try:
            if use_directory:
                success = self._run_directory_translation(batch_size, parallel_languages, load_mode)
            else:
                success = self._run_file_translation(batch_size, parallel_languages, load_mode)

            duration = time.perf_counter() - start_time

            # Calculate throughput
            total_file_langs = len(self.corpus) * len(self.target_langs)
            throughput_files = (len(self.corpus) / duration) * 60  # files/min
            throughput_file_langs = (total_file_langs / duration) * 60  # file-langs/min

            result = BenchmarkResult(
                config_name=config_name,
                batch_size=batch_size,
                parallel_languages=parallel_languages,
                load_mode=load_mode,
                translation_mode="directory" if use_directory else "file",
                files_count=len(self.corpus),
                languages_count=len(self.target_langs),
                total_duration=duration,
                throughput_files_per_min=throughput_files,
                throughput_file_langs_per_min=throughput_file_langs,
                success=success,
            )

            print(f"\n[OK] Completed in {duration:.1f}s")
            print(f"  Throughput: {throughput_files:.2f} files/min")
            print(f"  Throughput: {throughput_file_langs:.2f} file-langs/min")

            return result

        except Exception as e:
            duration = time.perf_counter() - start_time

            result = BenchmarkResult(
                config_name=config_name,
                batch_size=batch_size,
                parallel_languages=parallel_languages,
                load_mode=load_mode,
                translation_mode="directory" if use_directory else "file",
                files_count=len(self.corpus),
                languages_count=len(self.target_langs),
                total_duration=duration,
                throughput_files_per_min=0,
                throughput_file_langs_per_min=0,
                success=False,
                error=str(e),
            )

            print(f"\n[FAIL] Failed: {e}")

            return result

    def _run_file_translation(
        self, batch_size: int | None, parallel_languages: int | None, load_mode: str
    ) -> bool:
        """Run file-by-file translation."""

        for file_path in self.corpus:
            cmd = (
                [
                    str(self.cli_path),
                    "-m",
                    "src.cli",
                    "--site",
                    "kb.aspose.net",
                    "--input",
                    str(file_path),
                    "--target-langs",
                ]
                + self.target_langs
                + ["--device", "cuda", "--load-mode", load_mode, "--force-retranslate"]
            )

            if batch_size:
                cmd.extend(["--batch-size", str(batch_size)])

            if parallel_languages:
                cmd.extend(["--parallel-languages", str(parallel_languages)])

            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=600,
                encoding="utf-8",
                errors="replace",
            )

            if result.returncode != 0:
                print(f"  [X] Failed: {file_path.name}")
                return False

            print(f"  [+] {file_path.name}")

        return True

    def _run_directory_translation(
        self, batch_size: int | None, parallel_languages: int | None, load_mode: str
    ) -> bool:
        """Run directory-level translation."""

        # Create temp directory with just our test files
        import shutil

        temp_dir = PROJECT_ROOT / "temp_benchmark_corpus"
        temp_dir.mkdir(exist_ok=True)

        try:
            # Copy test files to temp dir
            for file_path in self.corpus:
                shutil.copy2(file_path, temp_dir / file_path.name)

            cmd = (
                [
                    str(self.cli_path),
                    "-m",
                    "src.cli",
                    "--site",
                    "kb.aspose.net",
                    "--input",
                    str(temp_dir),
                    "--target-langs",
                ]
                + self.target_langs
                + ["--device", "cuda", "--load-mode", load_mode, "--force-retranslate"]
            )

            if batch_size:
                cmd.extend(["--batch-size", str(batch_size)])

            if parallel_languages:
                cmd.extend(["--parallel-languages", str(parallel_languages)])

            result = subprocess.run(
                cmd,
                cwd=str(PROJECT_ROOT),
                capture_output=True,
                timeout=1200,
                encoding="utf-8",
                errors="replace",
            )

            return result.returncode == 0

        finally:
            # Cleanup
            if temp_dir.exists():
                shutil.rmtree(temp_dir)

    def generate_report(self) -> str:
        """Generate benchmark report."""

        if not self.results:
            return "No benchmark results"

        # Sort by throughput (file-langs/min)
        sorted_results = sorted(
            self.results, key=lambda r: r.throughput_file_langs_per_min, reverse=True
        )

        report = f"""# CLI Settings Benchmark Report

**Generated**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Test Corpus**: {self.test_corpus_size} files
**Target Languages**: {", ".join(self.target_langs)} ({len(self.target_langs)} languages)
**Total Translations**: {self.test_corpus_size * len(self.target_langs)} file-language pairs

---

## Results Summary

**Best Configuration**: {sorted_results[0].config_name}
- **Throughput**: {sorted_results[0].throughput_file_langs_per_min:.2f} file-langs/min
- **Settings**:
  - Batch size: {sorted_results[0].batch_size or "auto"}
  - Parallel languages: {sorted_results[0].parallel_languages or "disabled"}
  - Load mode: {sorted_results[0].load_mode}
  - Translation mode: {sorted_results[0].translation_mode}

---

## All Configurations (Sorted by Throughput)

| Rank | Config | Batch | Parallel | Load | Mode | Duration | Files/min | File-langs/min | Status |
|------|--------|-------|----------|------|------|----------|-----------|----------------|--------|
"""

        for i, result in enumerate(sorted_results, 1):
            status = "OK" if result.success else "FAIL"
            batch = str(result.batch_size) if result.batch_size else "auto"
            parallel = str(result.parallel_languages) if result.parallel_languages else "0"

            report += f"| {i} | {result.config_name} | {batch} | {parallel} | {result.load_mode} | {result.translation_mode} | {result.total_duration:.1f}s | {result.throughput_files_per_min:.2f} | {result.throughput_file_langs_per_min:.2f} | {status} |\n"

        report += f"""
---

## Recommendations for Production

Based on {self.test_corpus_size} files × {len(self.target_langs)} languages = {self.test_corpus_size * len(self.target_langs)} translations:

### For Thousands of Files × 36 Languages

**Optimal Settings** (from {sorted_results[0].config_name}):
```bash
python -m src.cli \\
  --site kb.aspose.net \\
  --input /path/to/files \\
  --target-langs [36 languages] \\
  --device cuda \\
  --batch-size {sorted_results[0].batch_size or "auto"} \\
  --parallel-languages {sorted_results[0].parallel_languages or "0"} \\
  --load-mode {sorted_results[0].load_mode} \\
  --force-retranslate
```

**Expected Performance**:
- Throughput: ~{sorted_results[0].throughput_file_langs_per_min:.0f} file-language pairs/minute
- For 1,000 files × 36 languages = 36,000 translations:
  - Time: {36000 / sorted_results[0].throughput_file_langs_per_min / 60:.1f} hours
  - With GPU: RTX 4090 16GB VRAM

**Key Insights**:
"""

        # Add insights based on results
        if any(r.parallel_languages and r.parallel_languages > 0 for r in self.results):
            parallel_results = [
                r for r in self.results if r.parallel_languages and r.parallel_languages > 0
            ]
            sequential_results = [
                r for r in self.results if not r.parallel_languages or r.parallel_languages == 0
            ]

            if parallel_results and sequential_results:
                best_parallel = max(parallel_results, key=lambda r: r.throughput_file_langs_per_min)
                best_sequential = max(
                    sequential_results, key=lambda r: r.throughput_file_langs_per_min
                )

                speedup = (
                    best_parallel.throughput_file_langs_per_min
                    / best_sequential.throughput_file_langs_per_min
                )
                report += f"- **Parallel languages**: {speedup:.1f}x faster than sequential\n"

        if len(set(r.load_mode for r in self.results)) > 1:
            fp16_results = [r for r in self.results if r.load_mode == "fp16"]
            fp32_results = [r for r in self.results if r.load_mode == "fp32"]

            if fp16_results and fp32_results:
                best_fp16 = max(fp16_results, key=lambda r: r.throughput_file_langs_per_min)
                best_fp32 = max(fp32_results, key=lambda r: r.throughput_file_langs_per_min)

                speedup = (
                    best_fp16.throughput_file_langs_per_min
                    / best_fp32.throughput_file_langs_per_min
                )
                report += f"- **FP16 vs FP32**: {speedup:.1f}x throughput improvement\n"

        report += """
---

**Report generated by**: scripts/benchmark_cli_settings.py
"""

        return report


def main():
    parser = argparse.ArgumentParser(description="Benchmark CLI settings for optimal translation")
    parser.add_argument(
        "--corpus-size", type=int, default=5, help="Number of test files (default: 5)"
    )
    parser.add_argument(
        "--languages", nargs="+", default=["de", "fr"], help="Target languages to test"
    )
    parser.add_argument("--quick", action="store_true", help="Quick benchmark (fewer configs)")

    args = parser.parse_args()

    benchmarker = CLIBenchmarker(test_corpus_size=args.corpus_size, target_langs=args.languages)

    # Define benchmark configurations
    if args.quick:
        configs = [
            ("baseline", None, None, "fp32", False),
            ("batch-64", 64, None, "fp32", False),
            ("parallel-2", None, 2, "fp32", False),
            ("fp16", None, None, "fp16", False),
        ]
    else:
        configs = [
            # Baseline
            ("baseline", None, None, "fp32", False),
            # Batch size variations
            ("batch-32", 32, None, "fp32", False),
            ("batch-64", 64, None, "fp32", False),
            ("batch-128", 128, None, "fp32", False),
            # Parallel languages
            ("parallel-2", None, 2, "fp32", False),
            ("parallel-4", None, 4, "fp32", False),
            # FP16 precision
            ("fp16-baseline", None, None, "fp16", False),
            ("fp16-batch-64", 64, None, "fp16", False),
            ("fp16-parallel-2", None, 2, "fp16", False),
            # Combined optimizations
            ("optimal-combo", 64, 2, "fp16", False),
            ("aggressive", 128, 4, "fp16", False),
        ]

    print(f"Running {len(configs)} benchmark configurations...")
    print(
        f"Test: {args.corpus_size} files × {len(args.languages)} languages = {args.corpus_size * len(args.languages)} translations\n"
    )

    # Run all benchmarks
    for config in configs:
        result = benchmarker.run_benchmark(*config)
        benchmarker.results.append(result)

    # Generate and save report
    report = benchmarker.generate_report()

    report_path = (
        PROJECT_ROOT
        / "reports"
        / f"benchmark_cli_settings_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    )
    report_path.write_text(report, encoding="utf-8")

    print(f"\n{'=' * 80}")
    print("Benchmark complete!")
    print(f"Report: {report_path}")
    print(f"{'=' * 80}")
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
