#!/usr/bin/env python3
"""
Analyze benchmark results and recommend optimal production settings.

Reads benchmark reports and provides:
1. Best configuration for production
2. Performance comparison (GPU vs CPU, FP16 vs FP32, etc.)
3. Resource usage analysis
4. Production-scale estimates
"""

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

PROJECT_ROOT = Path(__file__).parent.parent


@dataclass
class BenchmarkConfig:
    """Parsed benchmark configuration."""
    name: str
    model: str = ""
    device: str = ""
    batch_size: int | None = None
    parallel_langs: int | None = None
    load_mode: str = ""

    duration: float = 0.0
    throughput_file_langs_per_min: float = 0.0

    peak_vram_mb: float | None = None
    peak_ram_mb: float | None = None
    avg_cpu_pct: float | None = None

    success: bool = True
    experimental: bool = False


class BenchmarkAnalyzer:
    """Analyze benchmark results from markdown reports."""

    def __init__(self, report_path: Path):
        self.report_path = report_path
        self.report_text = report_path.read_text(encoding='utf-8')
        self.configs: list[BenchmarkConfig] = []

    def parse_report(self):
        """Parse benchmark report markdown."""
        # Find the results table
        table_match = re.search(
            r'\| Rank \| Config.*?\n\|[-\s|]+\n((?:\|.*?\n)+)',
            self.report_text,
            re.MULTILINE
        )

        if not table_match:
            print("Warning: Could not find results table in report")
            return

        table_rows = table_match.group(1).strip().split('\n')

        for row in table_rows:
            parts = [p.strip() for p in row.split('|')[1:-1]]  # Skip empty first/last

            if len(parts) < 9:
                continue

            try:
                config = BenchmarkConfig(
                    name=parts[1],
                    model=parts[2] if len(parts) > 2 else "",
                    device=parts[3] if len(parts) > 3 else "",
                    batch_size=int(parts[4]) if parts[4] != 'auto' else None,
                    parallel_langs=int(parts[5]) if parts[5] != '0' else None,
                    load_mode=parts[6] if len(parts) > 6 else "",
                    duration=float(parts[7].replace('s', '')) if len(parts) > 7 else 0.0,
                    throughput_file_langs_per_min=float(parts[9]) if len(parts) > 9 else 0.0,
                    success=parts[-1] == 'OK' if len(parts) > 10 else True
                )

                # Try to parse resource usage if present
                if len(parts) > 10:
                    vram = parts[10]
                    if 'MB' in vram and vram != 'N/A':
                        config.peak_vram_mb = float(vram.replace('MB', ''))

                    if len(parts) > 11:
                        ram = parts[11]
                        if 'MB' in ram and ram != 'N/A':
                            config.peak_ram_mb = float(ram.replace('MB', ''))

                    if len(parts) > 12:
                        cpu = parts[12]
                        if '%' in cpu and cpu != 'N/A':
                            config.avg_cpu_pct = float(cpu.replace('%', ''))

                self.configs.append(config)

            except (ValueError, IndexError) as e:
                print(f"Warning: Could not parse row: {row[:50]}... ({e})")
                continue

    def get_best_production_config(self) -> BenchmarkConfig | None:
        """Get the best production-ready configuration."""
        production_configs = [c for c in self.configs if c.success and not c.experimental]

        if not production_configs:
            return None

        # Sort by throughput
        return max(production_configs, key=lambda c: c.throughput_file_langs_per_min)

    def compare_gpu_vs_cpu(self) -> dict:
        """Compare GPU vs CPU performance."""
        gpu_configs = [c for c in self.configs if c.device == 'cuda' and c.success]
        cpu_configs = [c for c in self.configs if c.device == 'cpu' and c.success]

        if not gpu_configs or not cpu_configs:
            return {}

        best_gpu = max(gpu_configs, key=lambda c: c.throughput_file_langs_per_min)
        best_cpu = max(cpu_configs, key=lambda c: c.throughput_file_langs_per_min)

        speedup = best_gpu.throughput_file_langs_per_min / best_cpu.throughput_file_langs_per_min

        return {
            'best_gpu': best_gpu,
            'best_cpu': best_cpu,
            'speedup': speedup
        }

    def compare_fp16_vs_fp32(self) -> dict:
        """Compare FP16 vs FP32 performance."""
        fp16_configs = [c for c in self.configs if c.load_mode == 'fp16' and c.success]
        fp32_configs = [c for c in self.configs if c.load_mode == 'fp32' and c.success]

        if not fp16_configs or not fp32_configs:
            return {}

        best_fp16 = max(fp16_configs, key=lambda c: c.throughput_file_langs_per_min)
        best_fp32 = max(fp32_configs, key=lambda c: c.throughput_file_langs_per_min)

        speedup = best_fp16.throughput_file_langs_per_min / best_fp32.throughput_file_langs_per_min

        return {
            'best_fp16': best_fp16,
            'best_fp32': best_fp32,
            'speedup': speedup
        }

    def generate_recommendation(self) -> str:
        """Generate production recommendations."""
        best = self.get_best_production_config()

        if not best:
            return "# No successful production configurations found"

        gpu_cpu = self.compare_gpu_vs_cpu()
        fp_comp = self.compare_fp16_vs_fp32()

        report = f"""# Benchmark Analysis & Production Recommendations

## Best Production Configuration

**Configuration**: {best.name}
- **Model**: {best.model}
- **Device**: {best.device}
- **Batch Size**: {best.batch_size or 'auto'}
- **Load Mode**: {best.load_mode}
- **Parallel Languages**: {best.parallel_langs or 'disabled'}

**Performance**:
- **Throughput**: {best.throughput_file_langs_per_min:.2f} file-langs/min
- **Duration**: {best.duration:.1f}s (test run)

**Resource Usage**:
"""
        if best.peak_vram_mb:
            report += f"- **Peak VRAM**: {best.peak_vram_mb:.0f} MB\n"
        if best.peak_ram_mb:
            report += f"- **Peak RAM**: {best.peak_ram_mb:.0f} MB\n"
        if best.avg_cpu_pct:
            report += f"- **Avg CPU**: {best.avg_cpu_pct:.1f}%\n"

        report += f"""

---

## Production Command

```bash
python -m src.cli \\
  --site kb.aspose.net \\
  --input /path/to/files \\
  --target-langs [36 languages] \\
  --model {best.model} \\
  --device {best.device} \\
  --batch-size {best.batch_size or 'auto'} \\
  --load-mode {best.load_mode} \\
  --force-retranslate
```

---

## Production-Scale Estimates

Based on {best.throughput_file_langs_per_min:.2f} file-langs/min:

| Scale | Files | Languages | Total Translations | Est. Time |
|-------|-------|-----------|-------------------|-----------|
| Small | 100 | 36 | 3,600 | {3600 / best.throughput_file_langs_per_min / 60:.1f} hours |
| Medium | 500 | 36 | 18,000 | {18000 / best.throughput_file_langs_per_min / 60:.1f} hours |
| Large | 1,000 | 36 | 36,000 | {36000 / best.throughput_file_langs_per_min / 60:.1f} hours |
| X-Large | 5,000 | 36 | 180,000 | {180000 / best.throughput_file_langs_per_min / 60:.1f} hours |

---

## Performance Comparisons

"""

        if gpu_cpu:
            speedup = gpu_cpu['speedup']
            report += f"""### GPU vs CPU

- **Best GPU**: {gpu_cpu['best_gpu'].name} ({gpu_cpu['best_gpu'].throughput_file_langs_per_min:.2f} file-langs/min)
- **Best CPU**: {gpu_cpu['best_cpu'].name} ({gpu_cpu['best_cpu'].throughput_file_langs_per_min:.2f} file-langs/min)
- **GPU Speedup**: {speedup:.2f}x faster than CPU

**Recommendation**: {'Use GPU for production' if speedup > 1.5 else 'GPU advantage minimal'}

"""

        if fp_comp:
            speedup = fp_comp['speedup']
            report += f"""### FP16 vs FP32

- **Best FP16**: {fp_comp['best_fp16'].name} ({fp_comp['best_fp16'].throughput_file_langs_per_min:.2f} file-langs/min)
- **Best FP32**: {fp_comp['best_fp32'].name} ({fp_comp['best_fp32'].throughput_file_langs_per_min:.2f} file-langs/min)
- **FP16 Speedup**: {speedup:.2f}x faster than FP32

**Recommendation**: {'Use FP16 for production (significant speedup)' if speedup > 1.3 else 'FP16 advantage minimal'}

"""

        report += """---

## All Tested Configurations (Ranked)

| Rank | Config | Device | Load | Batch | Throughput |
|------|--------|--------|------|-------|------------|
"""

        ranked = sorted(self.configs, key=lambda c: c.throughput_file_langs_per_min, reverse=True)
        for i, cfg in enumerate(ranked[:10], 1):  # Top 10
            report += f"| {i} | {cfg.name} | {cfg.device} | {cfg.load_mode} | {cfg.batch_size or 'auto'} | {cfg.throughput_file_langs_per_min:.2f} |\n"

        report += f"""

---

## Next Steps

1. **Validate Quality**: Run VAL-01-A with optimal settings:
   ```bash
   python scripts/validate_corpus_cli.py \\
     --corpus-size 50 \\
     --target-lang de \\
     --device {best.device} \\
     --model {best.model} \\
     --batch-size {best.batch_size or 'auto'} \\
     --load-mode {best.load_mode}
   ```

2. **Test on Small Batch**: Translate 10-20 files with all 36 languages

3. **Monitor Resources**: Watch VRAM/RAM usage during first production run

4. **Scale to Full Production**: Use validated settings for full deployment

---

**Generated by**: scripts/analyze_benchmark_results.py
**Source Report**: {self.report_path.name}
"""

        return report


def main():
    parser = argparse.ArgumentParser(description="Analyze benchmark results")
    parser.add_argument("--report", type=str, help="Path to benchmark report")
    parser.add_argument("--latest", action="store_true", help="Use latest benchmark report")

    args = parser.parse_args()

    if args.latest:
        # Find latest benchmark report
        reports_dir = PROJECT_ROOT / "reports"
        benchmark_reports = sorted(reports_dir.glob("benchmark_*.md"), key=lambda p: p.stat().st_mtime, reverse=True)

        if not benchmark_reports:
            print("Error: No benchmark reports found in reports/")
            return 1

        report_path = benchmark_reports[0]
        print(f"Using latest report: {report_path.name}")
    elif args.report:
        report_path = Path(args.report)
        if not report_path.exists():
            print(f"Error: Report not found: {report_path}")
            return 1
    else:
        print("Error: Specify --report or --latest")
        return 1

    # Analyze
    analyzer = BenchmarkAnalyzer(report_path)
    analyzer.parse_report()

    if not analyzer.configs:
        print("Error: No configurations parsed from report")
        return 1

    print(f"Parsed {len(analyzer.configs)} configurations")

    # Generate recommendation
    recommendation = analyzer.generate_recommendation()

    # Save to file
    output_path = PROJECT_ROOT / "reports" / "BENCHMARK_ANALYSIS.md"
    output_path.write_text(recommendation, encoding='utf-8')

    print(f"\nAnalysis saved to: {output_path}")
    print("\n" + "="*80)
    print(recommendation)

    return 0


if __name__ == "__main__":
    sys.exit(main())
