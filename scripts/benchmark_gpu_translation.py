"""
Benchmark GPU Translation Performance.

Compares GPU vs CPU translation performance for different models and batch sizes.
"""
import argparse
import logging
import sys
import time
from pathlib import Path
from typing import Dict, List

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch

from src.hardware.gpu_manager import GPUManager
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class TranslationBenchmark:
    """Benchmark translation performance."""

    def __init__(self):
        """Initialize benchmark."""
        self.gpu_manager = GPUManager()
        self.results = []

    def create_test_texts(self, count: int) -> List[str]:
        """
        Create test texts for benchmarking.

        Args:
            count: Number of texts to create

        Returns:
            List of test texts
        """
        texts = [
            "This is a test sentence for translation benchmarking.",
            "Machine translation has improved significantly with deep learning.",
            "GPU acceleration can provide substantial speedups for neural networks.",
            "Translation memory systems help improve consistency and reduce costs.",
            "Natural language processing is a fascinating field of study.",
        ]

        # Repeat to reach desired count
        result = []
        for i in range(count):
            result.append(texts[i % len(texts)])

        return result

    def benchmark_model(
        self,
        model_id: str,
        backend: str,
        hf_model_id: str,
        device: str,
        batch_size: int,
        max_memory_mb: int = None,
    ) -> Dict:
        """
        Benchmark a specific model configuration.

        Args:
            model_id: Model identifier
            backend: Backend type (huggingface or ctranslate2)
            hf_model_id: HuggingFace model ID
            device: Device (cuda or cpu)
            batch_size: Batch size for translation
            max_memory_mb: Maximum GPU memory (MB)

        Returns:
            Dict with benchmark results
        """
        logger.info(f"\nBenchmarking {model_id} on {device} (batch_size={batch_size})")

        # Create registry and loader
        registry = ModelRegistry()
        registry.register_model(
            model_id=model_id,
            backend=backend,
            hf_model_id=hf_model_id,
            model_size_mb=1024,
            languages=["en", "es", "fr", "de"],
        )

        loader = ModelLoader(registry, device=device, max_memory_mb=max_memory_mb)

        try:
            # Load model
            load_start = time.perf_counter()
            model_backend = loader.load_model(model_id)
            load_time = time.perf_counter() - load_start

            logger.info(f"Model loaded in {load_time:.2f}s")

            # GPU memory before translation
            gpu_memory_before = None
            if device.startswith("cuda"):
                gpu_memory_before = self.gpu_manager.get_gpu_memory(0)

            # Create test texts
            texts = self.create_test_texts(batch_size)

            # Warmup (1 iteration)
            logger.info("Warming up...")
            model_backend.translate(texts[:min(2, len(texts))], "en", "es")

            # Clear cache before benchmarking
            if device.startswith("cuda"):
                torch.cuda.empty_cache()

            # Benchmark (multiple iterations)
            num_iterations = 5
            logger.info(f"Running {num_iterations} iterations...")
            translation_times = []

            for i in range(num_iterations):
                # Clear cache before each iteration
                if device.startswith("cuda"):
                    torch.cuda.synchronize()

                start = time.perf_counter()
                translations = model_backend.translate(texts, "en", "es")
                if device.startswith("cuda"):
                    torch.cuda.synchronize()
                end = time.perf_counter()

                translation_time = end - start
                translation_times.append(translation_time)
                logger.info(
                    f"  Iteration {i+1}: {translation_time:.3f}s "
                    f"({batch_size/translation_time:.1f} texts/sec)"
                )

            # GPU memory after translation
            gpu_memory_after = None
            if device.startswith("cuda"):
                gpu_memory_after = self.gpu_manager.get_gpu_memory(0)

            # Calculate statistics
            avg_time = sum(translation_times) / len(translation_times)
            min_time = min(translation_times)
            max_time = max(translation_times)
            throughput = batch_size / avg_time

            result = {
                "model_id": model_id,
                "backend": backend,
                "device": device,
                "batch_size": batch_size,
                "load_time": load_time,
                "avg_translation_time": avg_time,
                "min_translation_time": min_time,
                "max_translation_time": max_time,
                "throughput": throughput,
                "texts_translated": batch_size * num_iterations,
                "gpu_memory_before_mb": (
                    gpu_memory_before.used_mb if gpu_memory_before else None
                ),
                "gpu_memory_after_mb": (
                    gpu_memory_after.used_mb if gpu_memory_after else None
                ),
                "gpu_memory_peak_mb": (
                    max(gpu_memory_before.used_mb, gpu_memory_after.used_mb)
                    if gpu_memory_before and gpu_memory_after
                    else None
                ),
            }

            logger.info(
                f"\nResults for {model_id} on {device}:\n"
                f"  Load time: {load_time:.2f}s\n"
                f"  Avg translation time: {avg_time:.3f}s\n"
                f"  Throughput: {throughput:.1f} texts/sec\n"
            )

            if gpu_memory_before and gpu_memory_after:
                logger.info(
                    f"  GPU memory: {gpu_memory_before.used_mb:.0f}MB -> "
                    f"{gpu_memory_after.used_mb:.0f}MB"
                )

            # Cleanup
            loader.unload_all()
            if device.startswith("cuda"):
                torch.cuda.empty_cache()

            return result

        except Exception as e:
            logger.error(f"Benchmark failed: {e}")
            return {
                "model_id": model_id,
                "device": device,
                "batch_size": batch_size,
                "error": str(e),
            }

    def compare_devices(
        self,
        model_id: str,
        backend: str,
        hf_model_id: str,
        batch_size: int,
        max_memory_mb: int = None,
    ) -> Dict:
        """
        Compare GPU vs CPU performance.

        Args:
            model_id: Model identifier
            backend: Backend type
            hf_model_id: HuggingFace model ID
            batch_size: Batch size
            max_memory_mb: Maximum GPU memory (MB)

        Returns:
            Dict with comparison results
        """
        results = {}

        # Benchmark on GPU if available
        if torch.cuda.is_available():
            logger.info("=" * 70)
            logger.info("BENCHMARKING ON GPU")
            logger.info("=" * 70)
            results["gpu"] = self.benchmark_model(
                model_id, backend, hf_model_id, "cuda", batch_size, max_memory_mb
            )

        # Benchmark on CPU
        logger.info("=" * 70)
        logger.info("BENCHMARKING ON CPU")
        logger.info("=" * 70)
        results["cpu"] = self.benchmark_model(
            model_id, backend, hf_model_id, "cpu", batch_size, None
        )

        # Calculate speedup
        if "gpu" in results and "error" not in results["gpu"] and "error" not in results["cpu"]:
            speedup = results["cpu"]["avg_translation_time"] / results["gpu"]["avg_translation_time"]
            results["speedup"] = speedup

            logger.info("\n" + "=" * 70)
            logger.info("COMPARISON SUMMARY")
            logger.info("=" * 70)
            logger.info(f"GPU throughput: {results['gpu']['throughput']:.1f} texts/sec")
            logger.info(f"CPU throughput: {results['cpu']['throughput']:.1f} texts/sec")
            logger.info(f"GPU Speedup: {speedup:.2f}x")
            logger.info("=" * 70)

        return results

    def generate_report(self, results: Dict, output_path: Path) -> None:
        """
        Generate markdown report.

        Args:
            results: Benchmark results
            output_path: Output file path
        """
        lines = []
        lines.append("# GPU Translation Performance Report")
        lines.append("")
        lines.append(f"**Model**: {results.get('gpu', results.get('cpu', {})).get('model_id', 'N/A')}")
        lines.append(f"**Backend**: {results.get('gpu', results.get('cpu', {})).get('backend', 'N/A')}")
        lines.append(f"**Batch Size**: {results.get('gpu', results.get('cpu', {})).get('batch_size', 'N/A')}")
        lines.append("")

        # GPU results
        if "gpu" in results and "error" not in results["gpu"]:
            gpu = results["gpu"]
            lines.append("## GPU Performance")
            lines.append("")
            lines.append(f"- Device: CUDA")
            lines.append(f"- Load Time: {gpu['load_time']:.2f}s")
            lines.append(f"- Avg Translation Time: {gpu['avg_translation_time']:.3f}s")
            lines.append(f"- Throughput: {gpu['throughput']:.1f} texts/sec")
            lines.append(f"- Texts Translated: {gpu['texts_translated']}")

            if gpu.get("gpu_memory_peak_mb"):
                lines.append(f"- Peak GPU Memory: {gpu['gpu_memory_peak_mb']:.0f}MB")

            lines.append("")

        # CPU results
        if "cpu" in results and "error" not in results["cpu"]:
            cpu = results["cpu"]
            lines.append("## CPU Performance")
            lines.append("")
            lines.append(f"- Device: CPU")
            lines.append(f"- Load Time: {cpu['load_time']:.2f}s")
            lines.append(f"- Avg Translation Time: {cpu['avg_translation_time']:.3f}s")
            lines.append(f"- Throughput: {cpu['throughput']:.1f} texts/sec")
            lines.append(f"- Texts Translated: {cpu['texts_translated']}")
            lines.append("")

        # Comparison
        if "speedup" in results:
            lines.append("## GPU vs CPU Comparison")
            lines.append("")
            lines.append(f"- **GPU Speedup**: {results['speedup']:.2f}x faster than CPU")
            lines.append("")
            lines.append("### Throughput Comparison")
            lines.append("")
            if "gpu" in results and "cpu" in results:
                gpu_throughput = results["gpu"]["throughput"]
                cpu_throughput = results["cpu"]["throughput"]
                lines.append(f"- GPU: {gpu_throughput:.1f} texts/sec")
                lines.append(f"- CPU: {cpu_throughput:.1f} texts/sec")
                lines.append(f"- Improvement: {(gpu_throughput - cpu_throughput):.1f} texts/sec")
            lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")

        if "speedup" in results:
            if results["speedup"] > 3.0:
                lines.append("- Excellent GPU acceleration! Continue using GPU for production.")
            elif results["speedup"] > 1.5:
                lines.append("- Good GPU acceleration. GPU recommended for larger workloads.")
            else:
                lines.append("- Limited GPU speedup. Consider batch size optimization or CPU inference.")

        if "gpu" in results and results["gpu"].get("gpu_memory_peak_mb"):
            peak_mb = results["gpu"]["gpu_memory_peak_mb"]
            if peak_mb > 12288:  # > 12GB
                lines.append("- High memory usage. Consider reducing batch size or using quantized models.")
            elif peak_mb < 4096:  # < 4GB
                lines.append("- Low memory usage. Can potentially increase batch size for better throughput.")

        lines.append("")

        report = "\n".join(lines)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        logger.info(f"\nReport saved to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark GPU Translation Performance")
    parser.add_argument(
        "--model",
        type=str,
        default="m2m100_418m",
        help="Model ID to benchmark (default: m2m100_418m)",
    )
    parser.add_argument(
        "--backend",
        type=str,
        default="huggingface",
        choices=["huggingface", "ctranslate2"],
        help="Backend to use (default: huggingface)",
    )
    parser.add_argument(
        "--hf-model-id",
        type=str,
        default="facebook/m2m100_418M",
        help="HuggingFace model ID (default: facebook/m2m100_418M)",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=16,
        help="Batch size for translation (default: 16)",
    )
    parser.add_argument(
        "--max-memory",
        type=int,
        help="Maximum GPU memory in MB (default: no limit)",
    )
    parser.add_argument(
        "--gpu",
        action="store_true",
        help="Benchmark GPU only",
    )
    parser.add_argument(
        "--cpu",
        action="store_true",
        help="Benchmark CPU only",
    )
    parser.add_argument(
        "--output",
        type=str,
        default="reports/gpu_translation_performance.md",
        help="Output report path (default: reports/gpu_translation_performance.md)",
    )

    args = parser.parse_args()

    # Create benchmark
    benchmark = TranslationBenchmark()

    if args.gpu and not torch.cuda.is_available():
        logger.error("GPU requested but CUDA not available!")
        return 1

    # Run benchmark
    if args.gpu or args.cpu:
        # Single device benchmark
        device = "cuda" if args.gpu else "cpu"
        result = benchmark.benchmark_model(
            args.model,
            args.backend,
            args.hf_model_id,
            device,
            args.batch_size,
            args.max_memory if args.gpu else None,
        )
        results = {device: result}
    else:
        # Compare both devices
        results = benchmark.compare_devices(
            args.model,
            args.backend,
            args.hf_model_id,
            args.batch_size,
            args.max_memory,
        )

    # Generate report
    benchmark.generate_report(results, Path(args.output))

    return 0


if __name__ == "__main__":
    exit(main())
