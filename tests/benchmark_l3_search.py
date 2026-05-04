"""
Benchmark for L3 semantic search performance (TC-L3-008).

Measures:
- Cold single semantic_search
- Warm (cached) semantic_search
- batch_semantic_search with unique texts
- batch_semantic_search with duplicate texts
"""

import statistics
import time
from pathlib import Path
from unittest import mock

import numpy as np

from src.tm.l3_semantic import L3SemanticTM

_DIM = 384
_N_ENTRIES = 100
_N_QUERIES = 25
_WARMUP = 3


def _deterministic_encode(text, **kw):
    if isinstance(text, str):
        rng = np.random.default_rng(hash(text) % 2**31)
        return rng.random(_DIM).astype(np.float32)
    return np.array([
        np.random.default_rng(hash(t) % 2**31).random(_DIM).astype(np.float32)
        for t in text
    ])


def setup_l3(tmp_dir):
    instance = L3SemanticTM(
        index_path=tmp_dir,
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=0,
    )
    mock_encoder = mock.MagicMock()
    mock_encoder.encode.side_effect = _deterministic_encode
    mock_encoder.get_sentence_embedding_dimension.return_value = _DIM
    instance.encoder = mock_encoder

    for i in range(_N_ENTRIES):
        instance.add_entry(
            entry_id=f"site:en:fr:{i}",
            site_id="site", src_lang="en", tgt_lang="fr",
            source_text=f"entry text number {i}",
            translation=f"traduction numero {i}",
        )
    return instance


def bench_cold_single(l3):
    """Cold single searches (cache empty)."""
    l3._query_cache.clear()
    times = []
    for i in range(_N_QUERIES):
        t0 = time.perf_counter()
        l3.semantic_search("site", "en", "fr", f"query cold {i}")
        times.append((time.perf_counter() - t0) * 1000)
    return times


def bench_warm_single(l3):
    """Warm single searches (cache populated)."""
    # Pre-populate cache
    for i in range(_N_QUERIES):
        l3.semantic_search("site", "en", "fr", f"query warm {i}")
    l3.encoder.encode.reset_mock()

    times = []
    for i in range(_N_QUERIES):
        t0 = time.perf_counter()
        l3.semantic_search("site", "en", "fr", f"query warm {i}")
        times.append((time.perf_counter() - t0) * 1000)

    encode_calls = l3.encoder.encode.call_count
    return times, encode_calls


def bench_batch_unique(l3):
    """Batch search with all unique texts."""
    l3._query_cache.clear()
    queries = [
        {"site_id": "site", "src_lang": "en", "tgt_lang": "fr",
         "query_text": f"batch unique {i}", "k": 5, "threshold": 0.75}
        for i in range(_N_QUERIES)
    ]
    t0 = time.perf_counter()
    results = l3.batch_semantic_search(queries)
    elapsed = (time.perf_counter() - t0) * 1000
    return elapsed, len(results)


def bench_batch_duplicate(l3):
    """Batch search with repeated text."""
    l3._query_cache.clear()
    queries = [
        {"site_id": "site", "src_lang": "en", "tgt_lang": "fr",
         "query_text": "same text repeated", "k": 5, "threshold": 0.75}
        for _ in range(_N_QUERIES)
    ]
    l3.encoder.encode.reset_mock()
    t0 = time.perf_counter()
    results = l3.batch_semantic_search(queries)
    elapsed = (time.perf_counter() - t0) * 1000
    encode_calls = l3.encoder.encode.call_count
    return elapsed, len(results), encode_calls


def main():
    import tempfile
    tmp = tempfile.mkdtemp(prefix="l3_bench_")
    l3 = setup_l3(tmp)

    print(f"Benchmark: L3 semantic search (mock encoder, {_N_ENTRIES} entries, {_N_QUERIES} queries)")
    print(f"Model: all-MiniLM-L6-v2 (mocked), Device: CPU (mock), Index: IndexFlatL2")
    print("=" * 70)

    # Cold single
    cold_times = bench_cold_single(l3)
    print(f"\n1. Cold single semantic_search ({_N_QUERIES} queries):")
    print(f"   avg: {statistics.mean(cold_times):.3f} ms")
    print(f"   p95: {sorted(cold_times)[int(len(cold_times)*0.95)]:.3f} ms")
    print(f"   cache path: NO (cold)")

    # Warm single
    warm_times, warm_encodes = bench_warm_single(l3)
    print(f"\n2. Warm single semantic_search ({_N_QUERIES} queries):")
    print(f"   avg: {statistics.mean(warm_times):.3f} ms")
    print(f"   p95: {sorted(warm_times)[int(len(warm_times)*0.95)]:.3f} ms")
    print(f"   encoder.encode calls: {warm_encodes} (should be 0)")
    print(f"   cache path: YES")

    # Batch unique
    batch_u_ms, batch_u_n = bench_batch_unique(l3)
    print(f"\n3. batch_semantic_search ({_N_QUERIES} unique queries):")
    print(f"   total: {batch_u_ms:.3f} ms")
    print(f"   per-query: {batch_u_ms/_N_QUERIES:.3f} ms")
    print(f"   batch path: YES")

    # Batch duplicate
    batch_d_ms, batch_d_n, batch_d_enc = bench_batch_duplicate(l3)
    print(f"\n4. batch_semantic_search ({_N_QUERIES} duplicate queries):")
    print(f"   total: {batch_d_ms:.3f} ms")
    print(f"   per-query: {batch_d_ms/_N_QUERIES:.3f} ms")
    print(f"   encoder.encode calls: {batch_d_enc} (should be 1)")
    print(f"   batch path: YES, deduplicated")

    # Speedup comparison
    print("\n" + "=" * 70)
    cold_total = sum(cold_times)
    print(f"Speedup: warm vs cold: {cold_total/sum(warm_times):.1f}x")
    print(f"Speedup: batch-unique vs cold-serial: {cold_total/batch_u_ms:.1f}x")
    print(f"Speedup: batch-dupe vs cold-serial: {cold_total/batch_d_ms:.1f}x")


if __name__ == "__main__":
    main()
