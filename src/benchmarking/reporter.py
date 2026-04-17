"""
Benchmark Reporter - Formats benchmark results as Markdown or JSON.

Provides reusable formatting utilities for CLI and scripts to generate
human-readable reports and machine-parseable JSON outputs.
"""
import json
from typing import Any

from .storage import BenchmarkRun


class BenchmarkReporter:
    """
    Formats benchmark results for different output formats.

    Supports:
    - Markdown tables with system info and performance metrics
    - JSON output for scripting and automation
    - Summary statistics and comparisons
    """

    @staticmethod
    def format_markdown(run: BenchmarkRun) -> str:
        """
        Format a benchmark run as Markdown report.

        Args:
            run: BenchmarkRun to format

        Returns:
            Formatted Markdown string
        """
        lines = []

        # Header
        lines.append(f"# Benchmark Run: {run.run_id}")
        lines.append("")
        lines.append(f"**Timestamp:** {run.timestamp_utc}")
        lines.append(f"**Model:** {run.model_id}")
        lines.append(f"**Device:** {run.device}")
        lines.append(f"**Purpose:** {run.purpose}")
        if run.tags:
            lines.append(f"**Tags:** {', '.join(run.tags)}")
        lines.append("")

        # Configuration
        lines.append("## Configuration")
        lines.append("")
        lines.append(f"- **Batch Sizes:** {', '.join(map(str, run.batch_sizes))}")
        lines.append(f"- **Iterations:** {run.iterations}")
        lines.append(f"- **Corpus Category:** {run.corpus_category or 'N/A'}")
        lines.append(f"- **Total Duration:** {run.total_duration_seconds:.2f}s")
        lines.append(f"- **Total Samples:** {len(run.results)}")
        lines.append("")

        # System Information
        lines.append("## System Information")
        lines.append("")
        si = run.system_info
        lines.append(f"- **CPU:** {si.cpu_model} ({si.cpu_cores} cores)")
        lines.append(f"- **RAM:** {si.total_ram_gb:.1f} GB")
        if si.gpu_model:
            vram = f" ({si.gpu_memory_gb:.1f} GB VRAM)" if si.gpu_memory_gb else ""
            lines.append(f"- **GPU:** {si.gpu_model}{vram}")
        lines.append(f"- **OS:** {si.os_name} {si.os_version}")
        lines.append(f"- **Python:** {si.python_version}")
        if si.torch_version:
            lines.append(f"- **PyTorch:** {si.torch_version}")
        lines.append("")

        # Performance Results
        lines.append("## Performance Results")
        lines.append("")

        if run.results:
            # Calculate aggregate metrics
            throughputs = [r.throughput_tokens_per_sec for r in run.results]
            durations = [r.duration_seconds for r in run.results]
            total_tokens_in = sum(r.tokens_input for r in run.results)
            total_tokens_out = sum(r.tokens_output for r in run.results)

            avg_throughput = sum(throughputs) / len(throughputs)
            min_throughput = min(throughputs)
            max_throughput = max(throughputs)
            avg_duration = sum(durations) / len(durations)

            lines.append("### Summary Statistics")
            lines.append("")
            lines.append(f"- **Average Throughput:** {avg_throughput:.2f} tokens/sec")
            lines.append(f"- **Min Throughput:** {min_throughput:.2f} tokens/sec")
            lines.append(f"- **Max Throughput:** {max_throughput:.2f} tokens/sec")
            lines.append(f"- **Average Sample Duration:** {avg_duration:.3f}s")
            lines.append(f"- **Total Input Tokens:** {total_tokens_in:,}")
            lines.append(f"- **Total Output Tokens:** {total_tokens_out:,}")
            lines.append("")

            # Per-batch-size breakdown
            lines.append("### Performance by Batch Size")
            lines.append("")
            lines.append("| Batch Size | Samples | Avg Throughput (tokens/sec) | Avg Duration (s) |")
            lines.append("|------------|---------|----------------------------|------------------|")

            # Group results by batch size
            by_batch = {}
            for result in run.results:
                bs = result.batch_size
                if bs not in by_batch:
                    by_batch[bs] = []
                by_batch[bs].append(result)

            for batch_size in sorted(by_batch.keys()):
                batch_results = by_batch[batch_size]
                batch_throughputs = [r.throughput_tokens_per_sec for r in batch_results]
                batch_durations = [r.duration_seconds for r in batch_results]
                batch_avg_throughput = sum(batch_throughputs) / len(batch_throughputs)
                batch_avg_duration = sum(batch_durations) / len(batch_durations)

                lines.append(
                    f"| {batch_size:10} | {len(batch_results):7} | "
                    f"{batch_avg_throughput:26.2f} | {batch_avg_duration:16.3f} |"
                )

            lines.append("")

            # Error summary
            errors = [r for r in run.results if r.errors]
            if errors:
                lines.append("### Errors")
                lines.append("")
                lines.append(f"**Total Errors:** {len(errors)}")
                lines.append("")
                for result in errors[:10]:  # Show first 10 errors
                    lines.append(f"- **Sample {result.sample_id}:** {', '.join(result.errors)}")
                if len(errors) > 10:
                    lines.append(f"- _(and {len(errors) - 10} more errors)_")
                lines.append("")
        else:
            lines.append("_No results available_")
            lines.append("")

        # Metadata
        if run.metadata:
            lines.append("## Metadata")
            lines.append("")
            for key, value in run.metadata.items():
                lines.append(f"- **{key}:** {value}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_json(run: BenchmarkRun, indent: int = 2) -> str:
        """
        Format a benchmark run as JSON.

        Args:
            run: BenchmarkRun to format
            indent: JSON indentation level

        Returns:
            Formatted JSON string
        """
        return json.dumps(run.to_dict(), indent=indent)

    @staticmethod
    def format_comparison_markdown(comparison: dict[str, Any]) -> str:
        """
        Format benchmark comparison as Markdown table.

        Args:
            comparison: Comparison data from BenchmarkDatabase.compare_runs()

        Returns:
            Formatted Markdown string
        """
        lines = []

        metric = comparison.get("metric", "unknown")
        runs = comparison.get("runs", [])

        if "error" in comparison:
            return f"**Error:** {comparison['error']}"

        if not runs:
            return "**No runs to compare**"

        lines.append(f"# Benchmark Comparison: {metric}")
        lines.append("")
        lines.append("| Run ID | Model | Device | Timestamp | Count | Avg | Min | Max |")
        lines.append("|--------|-------|--------|-----------|-------|-----|-----|-----|")

        for run_data in runs:
            run_id = run_data["run_id"][:8]
            model_id = run_data["model_id"]
            device = run_data["device"]
            timestamp = run_data["timestamp"][:10]
            count = run_data["count"]
            avg = run_data["avg"]
            min_val = run_data["min"]
            max_val = run_data["max"]

            lines.append(
                f"| {run_id} | {model_id} | {device} | {timestamp} | "
                f"{count:5} | {avg:7.2f} | {min_val:7.2f} | {max_val:7.2f} |"
            )

        lines.append("")

        # Add delta analysis if comparing exactly 2 runs
        if len(runs) == 2:
            lines.append("## Delta Analysis")
            lines.append("")

            baseline = runs[0]
            comparison_run = runs[1]

            delta_avg = comparison_run["avg"] - baseline["avg"]
            pct_change = (delta_avg / baseline["avg"] * 100) if baseline["avg"] != 0 else 0

            direction = "improvement" if delta_avg > 0 else "regression"
            if metric in ["duration_seconds"]:
                # Lower is better for duration
                direction = "improvement" if delta_avg < 0 else "regression"

            lines.append(f"- **Baseline:** {baseline['run_id'][:8]} ({baseline['model_id']})")
            lines.append(f"- **Comparison:** {comparison_run['run_id'][:8]} ({comparison_run['model_id']})")
            lines.append(f"- **Delta:** {delta_avg:+.2f} ({pct_change:+.1f}%)")
            lines.append(f"- **Result:** {direction.capitalize()}")
            lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_recommendation_markdown(recommendation: dict[str, Any]) -> str:
        """
        Format model recommendation as Markdown.

        Args:
            recommendation: Recommendation data (from ModelRecommender.recommend())

        Returns:
            Formatted Markdown string
        """
        lines = []

        lines.append("# Model Recommendation")
        lines.append("")
        lines.append(f"**Model ID:** {recommendation['model_id']}")
        lines.append(f"**Backend:** {recommendation['backend']}")
        lines.append(f"**Device:** {recommendation['device']}")
        lines.append(f"**Confidence:** {recommendation['confidence']}")
        lines.append("")

        if recommendation.get("expected_throughput"):
            lines.append(f"**Expected Throughput:** ~{recommendation['expected_throughput']:.1f} tokens/sec")

        if recommendation.get("expected_memory_mb"):
            lines.append(f"**Expected Memory:** ~{recommendation['expected_memory_mb']:.0f} MB")

        lines.append("")
        lines.append("## Rationale")
        lines.append("")
        lines.append(recommendation["rationale"])
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def format_run_list_markdown(runs: list[tuple], title: str = "Benchmark Runs") -> str:
        """
        Format list of benchmark runs as Markdown table.

        Args:
            runs: List of tuples (run_id, model_id, device, timestamp, result_count)
            title: Table title

        Returns:
            Formatted Markdown string
        """
        lines = []

        lines.append(f"# {title}")
        lines.append("")

        if not runs:
            lines.append("_No runs found_")
            lines.append("")
            return "\n".join(lines)

        lines.append("| Run ID | Model | Device | Timestamp | Samples |")
        lines.append("|--------|-------|--------|-----------|---------|")

        for run_id, model_id, device, timestamp, result_count in runs:
            run_id_short = run_id[:8]
            timestamp_short = timestamp[:19].replace("T", " ")
            lines.append(
                f"| {run_id_short} | {model_id} | {device} | {timestamp_short} | {result_count:7} |"
            )

        lines.append("")
        lines.append(f"**Total:** {len(runs)} run(s)")
        lines.append("")

        return "\n".join(lines)
