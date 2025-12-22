#!/usr/bin/env python3
"""
Production-optimized benchmarking for large-scale translation.

Goal: Find fastest settings for thousands of .md files × 36 languages.

Tests:
- GPU vs CPU
- Batch size optimization
- FP16 vs FP32 (FP16 recommended)
- CT2 models (1.5x CPU speedup)
- Parallel languages (CPU-safe, GPU-cautious)
- INT8 quantization (experimental, NOT recommended for production)

Safety Monitoring:
- VRAM threshold (80% max)
- RAM threshold (90% max)
- CPU threshold (95% max)
- Auto-abort on threshold violation
"""

import argparse
import psutil
import subprocess
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import List, Optional

PROJECT_ROOT = Path(__file__).parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

# Safety thresholds
VRAM_THRESHOLD_PCT = 80  # 80% of available VRAM
RAM_THRESHOLD_PCT = 90   # 90% of available RAM
CPU_THRESHOLD_PCT = 95   # 95% CPU usage


@dataclass
class BenchmarkConfig:
    """Benchmark configuration."""
    name: str
    model: str
    device: str
    batch_size: Optional[int] = None
    parallel_languages: Optional[int] = None
    load_mode: str = "fp32"
    experimental: bool = False
    description: str = ""


@dataclass
class BenchmarkResult:
    """Results from a single benchmark run."""
    config: BenchmarkConfig
    files_count: int
    languages_count: int

    success: bool = False
    error: Optional[str] = None

    total_duration: float = 0.0
    throughput_files_per_min: float = 0.0
    throughput_file_langs_per_min: float = 0.0

    peak_vram_mb: Optional[float] = None
    peak_ram_mb: Optional[float] = None
    avg_cpu_pct: Optional[float] = None

    safety_abort: bool = False


class SafetyMonitor:
    """Monitor system resources and enforce safety thresholds."""

    def __init__(self):
        self.vram_samples: List[float] = []
        self.ram_samples: List[float] = []
        self.cpu_samples: List[float] = []

    def check_vram(self) -> tuple[bool, str]:
        """Check VRAM usage."""
        try:
            import torch
            if torch.cuda.is_available():
                vram_used = torch.cuda.memory_allocated(0)
                vram_total = torch.cuda.get_device_properties(0).total_memory
                vram_pct = (vram_used / vram_total) * 100
                self.vram_samples.append(vram_used / (1024**2))  # MB

                if vram_pct > VRAM_THRESHOLD_PCT:
                    return False, f"VRAM {vram_pct:.1f}% > {VRAM_THRESHOLD_PCT}%"
        except ImportError:
            pass
        return True, ""

    def check_ram(self) -> tuple[bool, str]:
        """Check RAM usage."""
        ram = psutil.virtual_memory()
        ram_mb = ram.used / (1024**2)
        self.ram_samples.append(ram_mb)

        if ram.percent > RAM_THRESHOLD_PCT:
            return False, f"RAM {ram.percent:.1f}% > {RAM_THRESHOLD_PCT}%"
        return True, ""

    def check_cpu(self) -> tuple[bool, str]:
        """Check CPU usage."""
        cpu_pct = psutil.cpu_percent(interval=0.5)
        self.cpu_samples.append(cpu_pct)

        if cpu_pct > CPU_THRESHOLD_PCT:
            return False, f"CPU {cpu_pct:.1f}% > {CPU_THRESHOLD_PCT}%"
        return True, ""

    def check_all(self) -> tuple[bool, str]:
        """Check all thresholds."""
        ok, msg = self.check_vram()
        if not ok:
            return False, msg

        ok, msg = self.check_ram()
        if not ok:
            return False, msg

        ok, msg = self.check_cpu()
        if not ok:
            return False, msg

        return True, ""

    def get_stats(self) -> dict:
        """Get peak/average stats."""
        return {
            'peak_vram_mb': max(self.vram_samples) if self.vram_samples else None,
            'peak_ram_mb': max(self.ram_samples) if self.ram_samples else None,
            'avg_cpu_pct': sum(self.cpu_samples) / len(self.cpu_samples) if self.cpu_samples else None
        }


class ProductionBenchmarker:
    """Production-optimized benchmarking."""

    def __init__(self, corpus_size: int = 5, target_langs: List[str] = None):
        self.corpus_size = corpus_size
        self.target_langs = target_langs or ["de", "fr"]
        self.cli_path = PROJECT_ROOT / ".venv" / "Scripts" / "python.exe"

        # Collect corpus
        self.corpus = self._collect_corpus()

        # Results storage
        self.results: List[BenchmarkResult] = []

    def _collect_corpus(self) -> List[Path]:
        """Collect test files."""
        kb_slides = Path("D:/onedrive/Documents/GitHub/aspose.net/content/kb.aspose.net/slides/en")

        if not kb_slides.exists():
            raise RuntimeError(f"Corpus not found: {kb_slides}")

        files = sorted(kb_slides.rglob("*.md"))[:self.corpus_size]
        print(f"Corpus: {len(files)} files × {len(self.target_langs)} languages = {len(files) * len(self.target_langs)} translations")
        return files

    def run_benchmark(self, config: BenchmarkConfig) -> BenchmarkResult:
        """Run a single benchmark with safety monitoring."""

        exp_tag = " [EXPERIMENTAL - NOT FOR PRODUCTION]" if config.experimental else ""
        print(f"\n{'='*80}")
        print(f"Config: {config.name}{exp_tag}")
        print(f"  {config.description}")
        print(f"  Model: {config.model}")
        print(f"  Device: {config.device}")
        print(f"  Batch: {config.batch_size or 'auto'}")
        print(f"  Parallel langs: {config.parallel_languages or 'disabled'}")
        print(f"  Load mode: {config.load_mode}")
        print(f"{'='*80}")

        result = BenchmarkResult(
            config=config,
            files_count=len(self.corpus),
            languages_count=len(self.target_langs)
        )

        monitor = SafetyMonitor()

        # Pre-check
        ok, msg = monitor.check_all()
        if not ok:
            print(f"[ABORT] Pre-check failed: {msg}")
            result.error = f"Safety threshold violated: {msg}"
            result.safety_abort = True
            return result

        start_time = time.perf_counter()

        try:
            # Run translations
            for i, file_path in enumerate(self.corpus, 1):
                # Safety check before each file
                ok, msg = monitor.check_all()
                if not ok:
                    print(f"\n[ABORT] Safety threshold violated: {msg}")
                    result.error = f"Safety abort after {i-1}/{len(self.corpus)} files: {msg}"
                    result.safety_abort = True
                    result.total_duration = time.perf_counter() - start_time
                    return result

                # Build command
                cmd = [
                    str(self.cli_path),
                    "-m", "src.cli",
                    "--site", "kb.aspose.net",
                    "--input", str(file_path),
                    "--target-langs"] + self.target_langs + [
                    "--model", config.model,
                    "--device", config.device,
                    "--load-mode", config.load_mode,
                    "--force-retranslate"
                ]

                if config.batch_size:
                    cmd.extend(["--batch-size", str(config.batch_size)])

                if config.parallel_languages:
                    cmd.extend(["--parallel-languages", str(config.parallel_languages)])

                # Run translation
                proc_result = subprocess.run(
                    cmd,
                    cwd=str(PROJECT_ROOT),
                    capture_output=True,
                    timeout=600,
                    encoding='utf-8',
                    errors='replace'
                )

                if proc_result.returncode != 0:
                    print(f"  [X] File {i}/{len(self.corpus)} failed: {file_path.name}")
                    result.error = f"Translation failed on file {i}: {file_path.name}"
                    result.total_duration = time.perf_counter() - start_time
                    return result

                print(f"  [+] File {i}/{len(self.corpus)}: {file_path.name}")

            # Success!
            result.success = True
            result.total_duration = time.perf_counter() - start_time

            # Calculate throughput
            total_translations = len(self.corpus) * len(self.target_langs)
            result.throughput_files_per_min = (len(self.corpus) / result.total_duration) * 60
            result.throughput_file_langs_per_min = (total_translations / result.total_duration) * 60

            # Get resource stats
            stats = monitor.get_stats()
            result.peak_vram_mb = stats['peak_vram_mb']
            result.peak_ram_mb = stats['peak_ram_mb']
            result.avg_cpu_pct = stats['avg_cpu_pct']

            print(f"\n[OK] Completed in {result.total_duration:.1f}s")
            print(f"  Throughput: {result.throughput_files_per_min:.2f} files/min")
            print(f"  Throughput: {result.throughput_file_langs_per_min:.2f} file-langs/min")
            if result.peak_vram_mb:
                print(f"  Peak VRAM: {result.peak_vram_mb:.0f} MB")
            print(f"  Peak RAM: {result.peak_ram_mb:.0f} MB")
            print(f"  Avg CPU: {result.avg_cpu_pct:.1f}%")

        except Exception as e:
            result.error = str(e)
            result.total_duration = time.perf_counter() - start_time
            print(f"\n[FAIL] Exception: {e}")

        return result

    def generate_report(self) -> str:
        """Generate production-focused report."""

        if not self.results:
            return "No results"

        # Separate production and experimental
        production = [r for r in self.results if not r.config.experimental and r.success]
        experimental = [r for r in self.results if r.config.experimental]
        failed = [r for r in self.results if not r.success]

        # Sort by throughput
        production.sort(key=lambda r: r.throughput_file_langs_per_min, reverse=True)
        experimental.sort(key=lambda r: r.throughput_file_langs_per_min, reverse=True)

        report = f"""# Production-Optimized Benchmarking Report

**Date**: {datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
**Goal**: Find fastest settings for thousands of .md files × 36 languages
**Test**: {self.corpus_size} files × {len(self.target_langs)} languages = {self.corpus_size * len(self.target_langs)} translations

**Safety Thresholds**:
- VRAM: {VRAM_THRESHOLD_PCT}% max
- RAM: {RAM_THRESHOLD_PCT}% max
- CPU: {CPU_THRESHOLD_PCT}% max

---

## Executive Summary

"""

        if production:
            best = production[0]
            report += f"""**Best Production Configuration**: {best.config.name}
- **Throughput**: {best.throughput_file_langs_per_min:.2f} file-langs/min
- **Model**: {best.config.model}
- **Device**: {best.config.device}
- **Batch size**: {best.config.batch_size or 'auto'}
- **Load mode**: {best.config.load_mode}
- **Parallel languages**: {best.config.parallel_languages or 'disabled'}

**Estimated Time for Full Production** (1,000 files × 36 languages = 36,000 translations):
- **Duration**: {36000 / best.throughput_file_langs_per_min / 60:.1f} hours
- **Peak VRAM**: {best.peak_vram_mb:.0f} MB (if GPU)
- **Peak RAM**: {best.peak_ram_mb:.0f} MB

"""
        else:
            report += "**No successful production configurations**\n\n"

        report += """---

## Production-Ready Results (Sorted by Throughput)

| Rank | Config | Model | Device | Batch | Parallel | Load | Duration | File-langs/min | Peak VRAM | Peak RAM | CPU |
|------|--------|-------|--------|-------|----------|------|----------|----------------|-----------|----------|-----|
"""

        for i, r in enumerate(production, 1):
            vram = f"{r.peak_vram_mb:.0f}MB" if r.peak_vram_mb else "N/A"
            ram = f"{r.peak_ram_mb:.0f}MB" if r.peak_ram_mb else "N/A"
            cpu = f"{r.avg_cpu_pct:.0f}%" if r.avg_cpu_pct else "N/A"

            report += f"| {i} | {r.config.name} | {r.config.model} | {r.config.device} | {r.config.batch_size or 'auto'} | {r.config.parallel_languages or '0'} | {r.config.load_mode} | {r.total_duration:.1f}s | {r.throughput_file_langs_per_min:.2f} | {vram} | {ram} | {cpu} |\n"

        if experimental:
            report += f"""

---

## Experimental Results (NOT RECOMMENDED FOR PRODUCTION)

**Warning**: INT8 quantization may degrade translation quality. Use only for testing.

| Config | Model | Device | File-langs/min | Status |
|--------|-------|--------|----------------|--------|
"""
            for r in experimental:
                status = "OK" if r.success else f"FAIL: {r.error}"
                throughput = f"{r.throughput_file_langs_per_min:.2f}" if r.success else "N/A"
                report += f"| {r.config.name} | {r.config.model} | {r.config.device} | {throughput} | {status} |\n"

        if failed:
            report += f"""

---

## Failed Configurations

| Config | Device | Error |
|--------|--------|-------|
"""
            for r in failed:
                error = r.error[:80] + "..." if r.error and len(r.error) > 80 else r.error
                report += f"| {r.config.name} | {r.config.device} | {error} |\n"

        if production:
            best = production[0]
            report += f"""

---

## Recommended Production Command

```bash
python -m src.cli \\
  --site kb.aspose.net \\
  --input /path/to/files \\
  --target-langs [36 languages] \\
  --model {best.config.model} \\
  --device {best.config.device} \\
  --batch-size {best.config.batch_size or 'auto'} \\
  --load-mode {best.config.load_mode} \\
  --force-retranslate
```

**Performance Estimate**:
- Small site (100 files × 36 langs = 3,600 translations): {3600 / best.throughput_file_langs_per_min / 60:.1f} hours
- Medium site (500 files × 36 langs = 18,000 translations): {18000 / best.throughput_file_langs_per_min / 60:.1f} hours
- Large site (1,000 files × 36 langs = 36,000 translations): {36000 / best.throughput_file_langs_per_min / 60:.1f} hours

**Key Insights**:
"""
            # Compare GPU vs CPU if both tested
            gpu_results = [r for r in production if r.config.device == "cuda"]
            cpu_results = [r for r in production if r.config.device == "cpu"]

            if gpu_results and cpu_results:
                best_gpu = max(gpu_results, key=lambda r: r.throughput_file_langs_per_min)
                best_cpu = max(cpu_results, key=lambda r: r.throughput_file_langs_per_min)
                speedup = best_gpu.throughput_file_langs_per_min / best_cpu.throughput_file_langs_per_min
                report += f"- GPU is {speedup:.1f}x faster than CPU\n"

            # Compare FP16 vs FP32 if both tested
            fp16_results = [r for r in production if r.config.load_mode == "fp16"]
            fp32_results = [r for r in production if r.config.load_mode == "fp32"]

            if fp16_results and fp32_results:
                best_fp16 = max(fp16_results, key=lambda r: r.throughput_file_langs_per_min)
                best_fp32 = max(fp32_results, key=lambda r: r.throughput_file_langs_per_min)
                speedup = best_fp16.throughput_file_langs_per_min / best_fp32.throughput_file_langs_per_min
                report += f"- FP16 is {speedup:.1f}x faster than FP32\n"

        report += f"""

---

**Generated by**: scripts/benchmark_production_optimized.py
"""

        return report


def main():
    parser = argparse.ArgumentParser(description="Production-optimized benchmarking")
    parser.add_argument("--corpus-size", type=int, default=5, help="Number of test files")
    parser.add_argument("--languages", nargs="+", default=["de", "fr"], help="Target languages")
    parser.add_argument("--quick", action="store_true", help="Quick test (4 configs)")
    parser.add_argument("--full", action="store_true", help="Full test (all configs)")

    args = parser.parse_args()

    benchmarker = ProductionBenchmarker(
        corpus_size=args.corpus_size,
        target_langs=args.languages
    )

    # Define configurations based on completion summary insights
    if args.quick:
        configs = [
            BenchmarkConfig(
                name="gpu-fp32-baseline",
                model="m2m100_418m",
                device="cuda",
                load_mode="fp32",
                description="GPU baseline with FP32"
            ),
            BenchmarkConfig(
                name="gpu-fp16-recommended",
                model="m2m100_418m",
                device="cuda",
                load_mode="fp16",
                description="GPU with FP16 (faster, lower memory)"
            ),
            BenchmarkConfig(
                name="gpu-fp16-batch64",
                model="m2m100_418m",
                device="cuda",
                batch_size=64,
                load_mode="fp16",
                description="GPU with FP16 + batch size optimization"
            ),
            BenchmarkConfig(
                name="cpu-ct2-optimized",
                model="m2m100_418m_ct2",
                device="cpu",
                batch_size=64,
                description="CPU with CT2 model (1.5x speedup from completion summary)"
            ),
        ]
    elif args.full:
        configs = [
            # GPU configurations
            BenchmarkConfig(
                name="gpu-fp32-baseline",
                model="m2m100_418m",
                device="cuda",
                load_mode="fp32",
                description="GPU baseline"
            ),
            BenchmarkConfig(
                name="gpu-fp16",
                model="m2m100_418m",
                device="cuda",
                load_mode="fp16",
                description="GPU with FP16"
            ),
            BenchmarkConfig(
                name="gpu-fp16-batch32",
                model="m2m100_418m",
                device="cuda",
                batch_size=32,
                load_mode="fp16",
                description="GPU FP16 + batch 32"
            ),
            BenchmarkConfig(
                name="gpu-fp16-batch64",
                model="m2m100_418m",
                device="cuda",
                batch_size=64,
                load_mode="fp16",
                description="GPU FP16 + batch 64"
            ),
            BenchmarkConfig(
                name="gpu-fp16-batch128",
                model="m2m100_418m",
                device="cuda",
                batch_size=128,
                load_mode="fp16",
                description="GPU FP16 + batch 128"
            ),

            # CPU configurations
            BenchmarkConfig(
                name="cpu-baseline",
                model="m2m100_418m",
                device="cpu",
                description="CPU baseline (HuggingFace)"
            ),
            BenchmarkConfig(
                name="cpu-ct2",
                model="m2m100_418m_ct2",
                device="cpu",
                description="CPU with CT2 (1.5x speedup expected)"
            ),
            BenchmarkConfig(
                name="cpu-ct2-batch64",
                model="m2m100_418m_ct2",
                device="cpu",
                batch_size=64,
                description="CPU CT2 + batch 64"
            ),
            BenchmarkConfig(
                name="cpu-parallel2",
                model="m2m100_418m",
                device="cpu",
                parallel_languages=2,
                description="CPU with parallel languages (safe on CPU)"
            ),

            # Experimental (INT8 - not recommended)
            BenchmarkConfig(
                name="cpu-ct2-int8",
                model="m2m100_418m_ct2_int8",
                device="cpu",
                load_mode="int8",
                experimental=True,
                description="INT8 quantization (quality degradation, NOT for production)"
            ),
        ]
    else:
        # Default: balanced test
        configs = [
            BenchmarkConfig(
                name="gpu-fp16-batch64",
                model="m2m100_418m",
                device="cuda",
                batch_size=64,
                load_mode="fp16",
                description="GPU optimized (recommended)"
            ),
            BenchmarkConfig(
                name="cpu-ct2-batch64",
                model="m2m100_418m_ct2",
                device="cpu",
                batch_size=64,
                description="CPU optimized (CT2 model)"
            ),
        ]

    print(f"Running {len(configs)} configurations...")
    print(f"Safety thresholds: VRAM {VRAM_THRESHOLD_PCT}%, RAM {RAM_THRESHOLD_PCT}%, CPU {CPU_THRESHOLD_PCT}%\n")

    # Run benchmarks
    for config in configs:
        result = benchmarker.run_benchmark(config)
        benchmarker.results.append(result)

        # Small delay between runs
        time.sleep(2)

    # Generate report
    report = benchmarker.generate_report()

    report_dir = PROJECT_ROOT / "reports"
    report_dir.mkdir(exist_ok=True)
    report_path = report_dir / f"benchmark_production_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"
    report_path.write_text(report, encoding='utf-8')

    print(f"\n{'='*80}")
    print(f"Benchmark complete!")
    print(f"Report: {report_path}")
    print(f"{'='*80}\n")
    print(report)

    return 0


if __name__ == "__main__":
    sys.exit(main())
