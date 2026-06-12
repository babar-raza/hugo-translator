#!/usr/bin/env python3
"""
Production Performance Benchmark for Hugo Translation System.

Benchmarks:
- TM lookup performance (L1/L2/L3)
- Single segment translation
- Full file translation
- Memory usage
- Model loading time

Outputs JSON for programmatic comparison.
"""

import argparse
import json
import statistics
import sys
import time
from pathlib import Path

import psutil

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.model_runtime import HardwareDetector
from src.tm import L1Cache, L2PersistentTM, L3SemanticTM, TranslationMemory
from src.translation_engine.extractor import SegmentExtractor
from src.translation_engine.parser import HugoParser
from src.translation_engine.reconstructor import MarkdownReconstructor
from src.utils.models import BodyRules, FrontmatterMode, FrontmatterRule, SiteProfile


def get_memory_usage():
    """Get current memory usage in MB."""
    process = psutil.Process()
    return process.memory_info().rss / 1024 / 1024


def benchmark_tm_lookups(tm: TranslationMemory, iterations: int = 1000) -> dict:
    """
    Benchmark TM lookup performance across all layers.

    Args:
        tm: TranslationMemory instance
        iterations: Number of lookup iterations

    Returns:
        dict with timing statistics
    """
    print(f"\n{'=' * 60}")
    print("TM Lookup Performance Benchmark")
    print(f"{'=' * 60}")

    results = {"iterations": iterations, "layers": {}}

    # L1 Cache (warm cache)
    print("\nL1 Cache Benchmark (warm)...")
    # Populate L1
    for i in range(iterations):
        tm.store("bench-site", "en", "es", f"test {i}", f"prueba {i}")

    # Benchmark L1
    latencies = []
    for i in range(iterations):
        start = time.perf_counter()
        result = tm.lookup("bench-site", "en", "es", f"test {i}")
        latencies.append((time.perf_counter() - start) * 1000)  # Convert to ms

    results["layers"]["L1"] = {
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": statistics.quantiles(latencies, n=20)[18],  # 95th percentile
        "p99_ms": statistics.quantiles(latencies, n=100)[98],  # 99th percentile
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "lookups_per_sec": 1000 / statistics.mean(latencies),
    }

    print(f"  Mean: {results['layers']['L1']['mean_ms']:.3f}ms")
    print(f"  P95: {results['layers']['L1']['p95_ms']:.3f}ms")
    print(f"  Throughput: {results['layers']['L1']['lookups_per_sec']:.0f} lookups/sec")

    # L2 Persistent (cold cache)
    print("\nL2 Persistent Benchmark...")
    # Clear L1, rely on L2
    tm.l1_cache.clear()

    latencies = []
    for i in range(min(100, iterations)):  # Sample 100 for L2
        start = time.perf_counter()
        result = tm.lookup("bench-site", "en", "es", f"test {i}")
        latencies.append((time.perf_counter() - start) * 1000)

    results["layers"]["L2"] = {
        "mean_ms": statistics.mean(latencies),
        "median_ms": statistics.median(latencies),
        "p95_ms": statistics.quantiles(latencies, n=20)[18],
        "p99_ms": statistics.quantiles(latencies, n=100)[98],
        "min_ms": min(latencies),
        "max_ms": max(latencies),
        "lookups_per_sec": 1000 / statistics.mean(latencies),
    }

    print(f"  Mean: {results['layers']['L2']['mean_ms']:.3f}ms")
    print(f"  P95: {results['layers']['L2']['p95_ms']:.3f}ms")
    print(f"  Throughput: {results['layers']['L2']['lookups_per_sec']:.0f} lookups/sec")

    return results


def benchmark_segment_translation(parser, extractor, reconstructor, iterations: int = 100) -> dict:
    """
    Benchmark single segment translation time.

    Args:
        parser: HugoParser instance
        extractor: SegmentExtractor instance
        reconstructor: MarkdownReconstructor instance
        iterations: Number of iterations

    Returns:
        dict with timing statistics
    """
    print(f"\n{'=' * 60}")
    print("Segment Translation Benchmark")
    print(f"{'=' * 60}")

    sample_text = """---
title: Test
---

# Heading

This is a test paragraph with multiple sentences. It should be translated completely.
"""

    # Parse once
    doc = parser.parse_string(sample_text)
    segments = extractor.extract_all(doc)

    print(f"Document has {len(segments)} segments")

    # Benchmark parse time
    parse_times = []
    for _ in range(iterations):
        start = time.perf_counter()
        doc = parser.parse_string(sample_text)
        parse_times.append((time.perf_counter() - start) * 1000)

    # Benchmark extraction time
    extract_times = []
    for _ in range(iterations):
        doc = parser.parse_string(sample_text)
        start = time.perf_counter()
        segments = extractor.extract_all(doc)
        extract_times.append((time.perf_counter() - start) * 1000)

    # Benchmark reconstruction time (with mock translations)
    reconstruct_times = []
    for _ in range(iterations):
        doc = parser.parse_string(sample_text)
        segments = extractor.extract_all(doc)
        translations = {seg.id: f"[ES] {seg.source_text}" for seg in segments}
        start = time.perf_counter()
        translated = reconstructor.reconstruct_document(doc, translations, "es")
        reconstruct_times.append((time.perf_counter() - start) * 1000)

    results = {
        "iterations": iterations,
        "segment_count": len(segments),
        "parse": {
            "mean_ms": statistics.mean(parse_times),
            "median_ms": statistics.median(parse_times),
            "p95_ms": statistics.quantiles(parse_times, n=20)[18],
        },
        "extract": {
            "mean_ms": statistics.mean(extract_times),
            "median_ms": statistics.median(extract_times),
            "p95_ms": statistics.quantiles(extract_times, n=20)[18],
        },
        "reconstruct": {
            "mean_ms": statistics.mean(reconstruct_times),
            "median_ms": statistics.median(reconstruct_times),
            "p95_ms": statistics.quantiles(reconstruct_times, n=20)[18],
        },
        "total_pipeline": {
            "mean_ms": statistics.mean(parse_times)
            + statistics.mean(extract_times)
            + statistics.mean(reconstruct_times),
        },
    }

    print(f"  Parse: {results['parse']['mean_ms']:.3f}ms (p95: {results['parse']['p95_ms']:.3f}ms)")
    print(
        f"  Extract: {results['extract']['mean_ms']:.3f}ms (p95: {results['extract']['p95_ms']:.3f}ms)"
    )
    print(
        f"  Reconstruct: {results['reconstruct']['mean_ms']:.3f}ms (p95: {results['reconstruct']['p95_ms']:.3f}ms)"
    )
    print(f"  Total Pipeline: {results['total_pipeline']['mean_ms']:.3f}ms")

    return results


def benchmark_file_sizes(parser, extractor, reconstructor) -> dict:
    """
    Benchmark translation time for files of different sizes.

    Args:
        parser: HugoParser instance
        extractor: SegmentExtractor instance
        reconstructor: MarkdownReconstructor instance

    Returns:
        dict with results by file size
    """
    print(f"\n{'=' * 60}")
    print("File Size Benchmark")
    print(f"{'=' * 60}")

    results = {}

    # Small file (~10 segments)
    small_file = """---
title: Small Test
---

# Small File

This is a small test file with about 10 segments to translate.

## Section 1

Content here.

## Section 2

More content.
"""

    # Medium file (~50 segments)
    medium_file = """---
title: Medium Test
---

# Medium File

""" + "\n\n".join([f"## Section {i}\n\nThis is paragraph {i} with content." for i in range(25)])

    # Large file (~100 segments)
    large_file = """---
title: Large Test
---

# Large File

""" + "\n\n".join([f"## Section {i}\n\nThis is paragraph {i} with content." for i in range(50)])

    for size_name, content in [
        ("small", small_file),
        ("medium", medium_file),
        ("large", large_file),
    ]:
        doc = parser.parse_string(content)
        segments = extractor.extract_all(doc)
        translations = {seg.id: f"[ES] {seg.source_text}" for seg in segments}

        # Time full translation
        times = []
        for _ in range(10):  # 10 iterations
            start = time.perf_counter()
            doc = parser.parse_string(content)
            segments = extractor.extract_all(doc)
            translations = {seg.id: f"[ES] {seg.source_text}" for seg in segments}
            translated = reconstructor.reconstruct_document(doc, translations, "es")
            times.append((time.perf_counter() - start) * 1000)

        results[size_name] = {
            "segment_count": len(segments),
            "mean_ms": statistics.mean(times),
            "median_ms": statistics.median(times),
            "p95_ms": statistics.quantiles(times, n=20)[18],
            "ms_per_segment": statistics.mean(times) / len(segments),
        }

        print(
            f"  {size_name.capitalize()} ({len(segments)} segments): {results[size_name]['mean_ms']:.2f}ms ({results[size_name]['ms_per_segment']:.2f}ms/segment)"
        )

    return results


def benchmark_memory_usage(tm, parser, extractor) -> dict:
    """
    Benchmark memory usage during operations.

    Args:
        tm: TranslationMemory instance
        parser: HugoParser instance
        extractor: SegmentExtractor instance

    Returns:
        dict with memory usage stats
    """
    print(f"\n{'=' * 60}")
    print("Memory Usage Benchmark")
    print(f"{'=' * 60}")

    baseline_memory = get_memory_usage()
    print(f"  Baseline: {baseline_memory:.1f}MB")

    # Add many TM entries
    for i in range(10000):
        tm.store("bench-site", "en", "es", f"segment {i}", f"segmento {i}")

    tm_memory = get_memory_usage()
    print(f"  After 10k TM entries: {tm_memory:.1f}MB (+{tm_memory - baseline_memory:.1f}MB)")

    # Parse many documents
    sample = "---\ntitle: Test\n---\n\n# Heading\n\nContent."
    for i in range(1000):
        doc = parser.parse_string(sample)
        segments = extractor.extract_all(doc)

    parse_memory = get_memory_usage()
    print(f"  After 1k parses: {parse_memory:.1f}MB (+{parse_memory - tm_memory:.1f}MB)")

    peak_memory = parse_memory

    return {
        "baseline_mb": baseline_memory,
        "with_tm_mb": tm_memory,
        "after_parsing_mb": parse_memory,
        "peak_mb": peak_memory,
        "tm_overhead_mb": tm_memory - baseline_memory,
    }


def main():
    """Run all benchmarks."""
    parser = argparse.ArgumentParser(description="Production performance benchmarks")
    parser.add_argument("--output", type=Path, required=True, help="Output JSON file")
    parser.add_argument("--iterations", type=int, default=100, help="Number of iterations")
    parser.add_argument("--tm-iterations", type=int, default=1000, help="TM lookup iterations")

    args = parser.parse_args()

    print("=" * 60)
    print("HUGO TRANSLATION SYSTEM - PRODUCTION BENCHMARK")
    print("=" * 60)

    # Detect hardware
    hw_detector = HardwareDetector()
    hw_info = hw_detector.detect()

    print("\nHardware:")
    print(f"  Device: {hw_info.recommended_device}")
    print(f"  CPUs: {hw_info.cpu_count}")
    print(f"  RAM: {hw_info.total_ram_gb:.1f}GB")
    if hw_info.gpu_available:
        print(f"  GPU: {hw_info.gpu_name} ({hw_info.gpu_memory_gb:.1f}GB VRAM)")

    # Initialize components
    print("\nInitializing components...")
    project_root = Path(__file__).parent.parent
    tm_path = project_root / "data" / "tm" / "benchmark"
    tm_path.mkdir(parents=True, exist_ok=True)

    l1 = L1Cache(max_size=10000)
    l2 = L2PersistentTM(db_path=str(tm_path / "l2.lmdb"), max_size_mb=100)
    l3 = L3SemanticTM(
        index_path=str(tm_path / "l3_faiss"),
        embedding_model="sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2",
        use_gpu=False,
    )
    tm = TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)

    parser_obj = HugoParser()

    site_profile = SiteProfile(
        site_id="benchmark",
        content_roots=["content"],
        default_source_lang="en",
        target_langs=["es"],
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        },
        body=BodyRules(translate_markdown=True),
    )

    extractor = SegmentExtractor(site_profile)
    reconstructor = MarkdownReconstructor(site_profile)

    # Run benchmarks
    results = {
        "timestamp": time.strftime("%Y-%m-%d %H:%M:%S"),
        "hardware": {
            "device": hw_info.recommended_device,
            "cpu_count": hw_info.cpu_count,
            "ram_gb": hw_info.total_ram_gb,
            "gpu_available": hw_info.gpu_available,
            "gpu_name": hw_info.gpu_name if hw_info.gpu_available else None,
        },
        "benchmarks": {},
    }

    results["benchmarks"]["tm_lookups"] = benchmark_tm_lookups(tm, iterations=args.tm_iterations)
    results["benchmarks"]["segment_translation"] = benchmark_segment_translation(
        parser_obj, extractor, reconstructor, iterations=args.iterations
    )
    results["benchmarks"]["file_sizes"] = benchmark_file_sizes(parser_obj, extractor, reconstructor)
    results["benchmarks"]["memory_usage"] = benchmark_memory_usage(tm, parser_obj, extractor)

    # Write results
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with open(args.output, "w") as f:
        json.dump(results, f, indent=2)

    print(f"\n{'=' * 60}")
    print("BENCHMARK COMPLETE")
    print(f"{'=' * 60}")
    print(f"Results saved to: {args.output}")

    # Cleanup
    l2.close()

    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n\nBenchmark interrupted by user.")
        sys.exit(1)
    except Exception as e:
        print(f"\n\nERROR: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)
