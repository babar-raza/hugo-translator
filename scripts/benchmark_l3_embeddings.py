"""
Benchmark L3 Semantic Embeddings Performance.

Compares GPU vs CPU performance for semantic embedding generation.
"""
import argparse
import logging
import sys
import tempfile
import time
from pathlib import Path

# Add parent directory to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent))

import torch

from src.tm.l3_semantic import L3SemanticTM

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


class L3Benchmark:
    """Benchmark L3 semantic embeddings."""

    def create_test_entries(self, count: int) -> list[dict]:
        """
        Create test entries for benchmarking.

        Args:
            count: Number of entries to create

        Returns:
            List of test entries
        """
        texts = [
            "This is a test sentence for translation benchmarking.",
            "Machine translation has improved significantly with deep learning.",
            "GPU acceleration provides substantial speedups for neural networks.",
            "Translation memory systems help improve consistency.",
            "Natural language processing is a fascinating field.",
            "Semantic search enables finding similar content.",
            "Vector embeddings capture semantic meaning.",
            "FAISS provides efficient similarity search.",
            "Batch processing improves throughput.",
            "GPU memory management is critical for performance.",
        ]

        entries = []
        for i in range(count):
            entries.append({
                "entry_id": f"test{i}",
                "site_id": "benchmark_site",
                "src_lang": "en",
                "tgt_lang": "es",
                "source_text": texts[i % len(texts)] + f" [{i}]",
                "translation": f"Translation {i}",
            })

        return entries

    def benchmark_embeddings(
        self,
        use_gpu: bool,
        batch_size: int,
        num_entries: int,
    ) -> dict:
        """
        Benchmark embedding generation.

        Args:
            use_gpu: Whether to use GPU
            batch_size: Batch size (informational)
            num_entries: Number of entries to encode

        Returns:
            Dict with benchmark results
        """
        device = "cuda" if use_gpu and torch.cuda.is_available() else "cpu"
        logger.info(f"\nBenchmarking L3 embeddings on {device}")
        logger.info(f"  Entries: {num_entries}")

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create L3 TM
            init_start = time.perf_counter()
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=use_gpu,
            )
            init_time = time.perf_counter() - init_start

            logger.info(f"  Initialized in {init_time:.2f}s")

            # Create test entries
            entries = self.create_test_entries(num_entries)

            # Warmup
            logger.info("  Warming up...")
            tm.batch_add(entries[:min(10, num_entries)])
            tm.clear()

            # Benchmark batch encoding
            logger.info("  Benchmarking batch encoding...")
            start = time.perf_counter()
            count = tm.batch_add(entries)
            if device == "cuda":
                torch.cuda.synchronize()
            encoding_time = time.perf_counter() - start

            logger.info(f"  Encoded {count} entries in {encoding_time:.3f}s")
            logger.info(f"  Throughput: {count/encoding_time:.1f} entries/sec")

            # Benchmark search
            logger.info("  Benchmarking semantic search...")
            search_times = []
            num_searches = 10

            for i in range(num_searches):
                query = f"Test query {i}"
                start = time.perf_counter()
                matches = tm.semantic_search(
                    site_id="benchmark_site",
                    src_lang="en",
                    tgt_lang="es",
                    query_text=query,
                    k=10,
                    threshold=0.5,
                )
                if device == "cuda":
                    torch.cuda.synchronize()
                search_time = time.perf_counter() - start
                search_times.append(search_time)

            avg_search_time = sum(search_times) / len(search_times)
            logger.info(f"  Avg search time: {avg_search_time*1000:.2f}ms")

            result = {
                "device": device,
                "num_entries": num_entries,
                "init_time": init_time,
                "encoding_time": encoding_time,
                "throughput": count / encoding_time,
                "avg_search_time": avg_search_time,
                "searches_per_sec": 1.0 / avg_search_time,
            }

            return result

    def compare_devices(self, batch_size: int, num_entries: int) -> dict:
        """
        Compare GPU vs CPU performance.

        Args:
            batch_size: Batch size
            num_entries: Number of entries

        Returns:
            Dict with comparison results
        """
        results = {}

        # GPU benchmark
        if torch.cuda.is_available():
            logger.info("=" * 70)
            logger.info("BENCHMARKING ON GPU")
            logger.info("=" * 70)
            results["gpu"] = self.benchmark_embeddings(True, batch_size, num_entries)
        else:
            logger.info("CUDA not available, skipping GPU benchmark")

        # CPU benchmark
        logger.info("=" * 70)
        logger.info("BENCHMARKING ON CPU")
        logger.info("=" * 70)
        results["cpu"] = self.benchmark_embeddings(False, batch_size, num_entries)

        # Calculate speedup
        if "gpu" in results:
            encoding_speedup = results["cpu"]["encoding_time"] / results["gpu"]["encoding_time"]
            search_speedup = results["cpu"]["avg_search_time"] / results["gpu"]["avg_search_time"]

            results["encoding_speedup"] = encoding_speedup
            results["search_speedup"] = search_speedup

            logger.info("\n" + "=" * 70)
            logger.info("COMPARISON SUMMARY")
            logger.info("=" * 70)
            logger.info(f"GPU encoding throughput: {results['gpu']['throughput']:.1f} entries/sec")
            logger.info(f"CPU encoding throughput: {results['cpu']['throughput']:.1f} entries/sec")
            logger.info(f"Encoding speedup: {encoding_speedup:.2f}x")
            logger.info(f"Search speedup: {search_speedup:.2f}x")
            logger.info("=" * 70)

        return results

    def generate_report(self, results: dict, output_path: Path) -> None:
        """
        Generate markdown report.

        Args:
            results: Benchmark results
            output_path: Output file path
        """
        lines = []
        lines.append("# L3 Semantic Embeddings GPU Performance Report")
        lines.append("")
        lines.append(f"**Entries Encoded**: {results.get('gpu', results.get('cpu', {})).get('num_entries', 'N/A')}")
        lines.append("")

        # GPU results
        if "gpu" in results:
            gpu = results["gpu"]
            lines.append("## GPU Performance")
            lines.append("")
            lines.append("- Device: CUDA")
            lines.append(f"- Initialization Time: {gpu['init_time']:.2f}s")
            lines.append(f"- Encoding Time: {gpu['encoding_time']:.3f}s")
            lines.append(f"- Encoding Throughput: {gpu['throughput']:.1f} entries/sec")
            lines.append(f"- Avg Search Time: {gpu['avg_search_time']*1000:.2f}ms")
            lines.append(f"- Search Throughput: {gpu['searches_per_sec']:.1f} searches/sec")
            lines.append("")

        # CPU results
        if "cpu" in results:
            cpu = results["cpu"]
            lines.append("## CPU Performance")
            lines.append("")
            lines.append("- Device: CPU")
            lines.append(f"- Initialization Time: {cpu['init_time']:.2f}s")
            lines.append(f"- Encoding Time: {cpu['encoding_time']:.3f}s")
            lines.append(f"- Encoding Throughput: {cpu['throughput']:.1f} entries/sec")
            lines.append(f"- Avg Search Time: {cpu['avg_search_time']*1000:.2f}ms")
            lines.append(f"- Search Throughput: {cpu['searches_per_sec']:.1f} searches/sec")
            lines.append("")

        # Comparison
        if "encoding_speedup" in results:
            lines.append("## GPU vs CPU Comparison")
            lines.append("")
            lines.append(f"- **Encoding Speedup**: {results['encoding_speedup']:.2f}x faster on GPU")
            lines.append(f"- **Search Speedup**: {results['search_speedup']:.2f}x faster on GPU")
            lines.append("")

        # Recommendations
        lines.append("## Recommendations")
        lines.append("")

        if "encoding_speedup" in results:
            if results["encoding_speedup"] > 3.0:
                lines.append("- Excellent GPU acceleration for embeddings! Use GPU for TM indexing.")
            elif results["encoding_speedup"] > 1.5:
                lines.append("- Good GPU speedup. Recommended for large TM datasets.")
            else:
                lines.append("- Limited speedup. CPU may be sufficient for smaller datasets.")

            if results["search_speedup"] > 2.0:
                lines.append("- GPU provides significant search speedup. Consider FAISS GPU index.")

        lines.append("")

        report = "\n".join(lines)

        output_path.parent.mkdir(parents=True, exist_ok=True)
        output_path.write_text(report, encoding="utf-8")
        logger.info(f"\nReport saved to: {output_path}")


def main():
    """Main entry point."""
    parser = argparse.ArgumentParser(description="Benchmark L3 Semantic Embeddings")
    parser.add_argument(
        "--batch-size",
        type=int,
        default=100,
        help="Number of entries to encode (default: 100)",
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
        default="reports/l3_gpu_performance.md",
        help="Output report path",
    )

    args = parser.parse_args()

    # Create benchmark
    benchmark = L3Benchmark()

    if args.gpu and not torch.cuda.is_available():
        logger.error("GPU requested but CUDA not available!")
        return 1

    # Run benchmark
    if args.gpu or args.cpu:
        use_gpu = args.gpu
        result = benchmark.benchmark_embeddings(use_gpu, 32, args.batch_size)
        results = {"gpu" if use_gpu else "cpu": result}
    else:
        results = benchmark.compare_devices(32, args.batch_size)

    # Generate report
    benchmark.generate_report(results, Path(args.output))

    return 0


if __name__ == "__main__":
    exit(main())
