"""
Unit tests for L3SemanticTM query embedding LRU cache (TC-L3-003).

Covers:
- Cache hit avoids encoder.encode() call
- Cache eviction at max size
- Cache cleared on offload_to_cpu()
- Cache populated by semantic_search()
- Cache populated by batch_semantic_search()
"""

from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from src.tm.l3_semantic import L3SemanticTM

_DIM = 384


@pytest.fixture
def l3(tmp_path):
    """L3 with mocked encoder and small cache for eviction tests."""
    instance = L3SemanticTM(
        index_path=tmp_path / "l3_index",
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=0,
    )
    mock_encoder = mock.MagicMock()
    mock_encoder.encode.side_effect = lambda text, **kw: (
        np.random.default_rng(hash(text) % 2**31).random(_DIM).astype(np.float32)
        if isinstance(text, str) else
        np.array([
            np.random.default_rng(hash(t) % 2**31).random(_DIM).astype(np.float32)
            for t in text
        ])
    )
    mock_encoder.get_sentence_embedding_dimension.return_value = _DIM
    instance.encoder = mock_encoder
    instance._query_cache_maxsize = 3  # small for eviction tests
    return instance


def _add_entry(l3, text="hello world", tgt_lang="fr"):
    """Helper to add a searchable entry."""
    l3.add_entry(
        entry_id=f"site:en:{tgt_lang}:{hash(text)}",
        site_id="site",
        src_lang="en",
        tgt_lang=tgt_lang,
        source_text=text,
        translation=f"translated_{text}",
    )


class TestQueryCacheHit:
    def test_cache_hit_skips_encode(self, l3):
        _add_entry(l3)
        l3.encoder.encode.reset_mock()

        # First call — cache miss — should encode
        l3.semantic_search("site", "en", "fr", "hello world")
        assert l3.encoder.encode.call_count == 1

        l3.encoder.encode.reset_mock()
        # Second call — cache hit — should NOT encode
        l3.semantic_search("site", "en", "fr", "hello world")
        assert l3.encoder.encode.call_count == 0

    def test_different_text_encodes(self, l3):
        _add_entry(l3, "text1")
        _add_entry(l3, "text2")
        l3.encoder.encode.reset_mock()

        l3.semantic_search("site", "en", "fr", "text1")
        l3.semantic_search("site", "en", "fr", "text2")
        assert l3.encoder.encode.call_count == 2


class TestQueryCacheEviction:
    def test_eviction_at_maxsize(self, l3):
        _add_entry(l3)
        l3.encoder.encode.reset_mock()

        # Fill cache to maxsize (3)
        for i in range(3):
            l3.semantic_search("site", "en", "fr", f"text_{i}")
        assert len(l3._query_cache) == 3
        assert l3.encoder.encode.call_count == 3

        # One more should evict the oldest
        l3.semantic_search("site", "en", "fr", "text_new")
        assert len(l3._query_cache) == 3
        # "text_0" was the LRU — should be evicted
        assert "text_0" not in l3._query_cache
        assert "text_new" in l3._query_cache


class TestQueryCacheClearOnOffload:
    def test_offload_clears_cache(self, l3):
        _add_entry(l3)
        l3.semantic_search("site", "en", "fr", "hello world")
        assert len(l3._query_cache) > 0

        l3.offload_to_cpu()
        assert len(l3._query_cache) == 0


class TestQueryCacheBatchPopulation:
    def test_batch_search_populates_cache(self, l3):
        _add_entry(l3, "q1")
        _add_entry(l3, "q2")
        l3.encoder.encode.reset_mock()

        queries = [
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "q1"},
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "q2"},
        ]
        l3.batch_semantic_search(queries)

        # Both should be cached now
        assert "q1" in l3._query_cache
        assert "q2" in l3._query_cache

        # Subsequent single search should NOT encode
        l3.encoder.encode.reset_mock()
        l3.semantic_search("site", "en", "fr", "q1")
        assert l3.encoder.encode.call_count == 0

    def test_batch_deduplicates_encoding(self, l3):
        _add_entry(l3)
        l3.encoder.encode.reset_mock()

        queries = [
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "same_text"},
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "same_text"},
        ]
        l3.batch_semantic_search(queries)

        # encoder.encode should be called once with a list of 1 unique text
        assert l3.encoder.encode.call_count == 1
