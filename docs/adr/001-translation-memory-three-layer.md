# ADR-001: Three-Layer Translation Memory

- **Status:** Accepted
- **Date:** 2025-12-24
- **Decision Makers:** Translation System Team

## Context

The translation system processes thousands of Hugo Markdown files across multiple languages. Many files share identical or similar content (e.g., product documentation with boilerplate sections, API references with repeated patterns). Without caching, every file segment is sent to the MT model, resulting in:

- Redundant GPU/CPU compute for identical text
- Latency proportional to total content volume rather than unique content
- No benefit from previous translation runs

A single-layer cache would either be too slow (disk-only) or too volatile (memory-only). Similar content that differs by a few words would be cache misses in an exact-match system.

## Decision

Implement a three-layer Translation Memory with distinct access patterns:

- **L1 (In-Memory Cache):** LRU cache with configurable max size (default 10,000 entries). Sub-millisecond lookups for hot translations within a single process lifetime. Evicts least-recently-used entries when full.

- **L2 (Persistent Store):** LMDB-backed key-value store with ACID guarantees. Survives process restarts. Exact-match lookups by `(source_text, src_lang, tgt_lang)` composite key. WAL mode for concurrent read safety on Windows.

- **L3 (Semantic Index):** FAISS vector index using sentence-transformer embeddings. Finds similar (not identical) source text with configurable similarity threshold. Optional — degrades gracefully if GPU unavailable or model not loaded.

Lookup order: L1 → L2 → L3 → MT model. Each cache miss at a higher layer populates the layer on return.

## Consequences

**Positive:**
- 90%+ cache hit rates in production (measured across docs.aspose.net)
- Millisecond lookups for repeated content vs seconds for MT inference
- L2 persistence means translation work compounds across runs
- L3 fuzzy matching reduces MT calls for near-duplicate content

**Negative:**
- L3 requires a sentence-transformer model (~80MB GPU memory)
- LMDB files grow over time (configurable max_size_mb, default 1536MB)
- Three-layer complexity increases debugging surface
- L3 FAISS index requires periodic sync from L2 (async, documented in l3-sync-strategy.md)

## References

- Full architecture: [docs/architecture/translation-memory.md](../architecture/translation-memory.md)
- L3 sync strategy: [docs/architecture/l3-sync-strategy.md](../architecture/l3-sync-strategy.md)
- Implementation: `src/tm/l1_cache.py`, `src/tm/l2_persistent.py`, `src/tm/l3_semantic.py`
- Contract tests: `tests/contract/test_tm_001_l1_cache.py`, `test_tm_002_l2_persistent.py`, `test_tm_003_l3_semantic.py`
