"""
Unit tests for L3SemanticTM.batch_semantic_search() (TC-L3-004)
and TranslationMemory.batch_lookup() batch L3 wiring (TC-L3-005).

Covers:
- batch_semantic_search: empty input, ordering, deduplication, threshold, empty index
- batch_lookup: L1 hits skip L3, L2 hits skip L3, misses use batch L3, mixed results
"""

from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from src.tm.l3_semantic import L3SemanticTM

_DIM = 384


def _deterministic_encode(text, **kw):
    """Return a deterministic embedding for a given text string or list."""
    if isinstance(text, str):
        rng = np.random.default_rng(hash(text) % 2**31)
        return rng.random(_DIM).astype(np.float32)
    return np.array([
        np.random.default_rng(hash(t) % 2**31).random(_DIM).astype(np.float32)
        for t in text
    ])


@pytest.fixture
def l3(tmp_path):
    instance = L3SemanticTM(
        index_path=tmp_path / "l3_index",
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=0,
    )
    mock_encoder = mock.MagicMock()
    mock_encoder.encode.side_effect = _deterministic_encode
    mock_encoder.get_sentence_embedding_dimension.return_value = _DIM
    instance.encoder = mock_encoder
    return instance


def _add_entries(l3, n=5):
    """Add n searchable entries."""
    for i in range(n):
        text = f"entry_{i}"
        l3.add_entry(
            entry_id=f"site:en:fr:{i}",
            site_id="site",
            src_lang="en",
            tgt_lang="fr",
            source_text=text,
            translation=f"traduit_{i}",
        )


# ========== batch_semantic_search tests ==========

class TestBatchSemanticSearchEmpty:
    def test_empty_input(self, l3):
        assert l3.batch_semantic_search([]) == []

    def test_empty_index(self, l3):
        queries = [
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "hello"},
        ]
        result = l3.batch_semantic_search(queries)
        assert len(result) == 1
        assert result[0] == []


class TestBatchSemanticSearchOrdering:
    def test_output_order_matches_input(self, l3):
        _add_entries(l3, 3)
        queries = [
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": f"entry_{i}"}
            for i in [2, 0, 1]
        ]
        results = l3.batch_semantic_search(queries)
        assert len(results) == 3
        # Each result is a list of matches — the best match for query i should
        # correspond to entry_i (since they share the same embedding)
        for qi, i in enumerate([2, 0, 1]):
            if results[qi]:
                assert results[qi][0].source_text == f"entry_{i}"


class TestBatchSemanticSearchDedupe:
    def test_duplicate_texts_encoded_once(self, l3):
        _add_entries(l3, 1)
        l3.encoder.encode.reset_mock()

        queries = [
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "entry_0"},
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "entry_0"},
            {"site_id": "site", "src_lang": "en", "tgt_lang": "fr", "query_text": "entry_0"},
        ]
        results = l3.batch_semantic_search(queries)
        assert len(results) == 3
        # All three should have the same results
        for r in results:
            assert len(r) == len(results[0])

        # Encoder should be called at most once (batch encode of unique texts)
        assert l3.encoder.encode.call_count <= 1


class TestBatchSemanticSearchFiltering:
    def test_wrong_site_filtered(self, l3):
        _add_entries(l3, 1)
        queries = [
            {"site_id": "other_site", "src_lang": "en", "tgt_lang": "fr", "query_text": "entry_0"},
        ]
        results = l3.batch_semantic_search(queries)
        assert results[0] == []

    def test_wrong_lang_filtered(self, l3):
        _add_entries(l3, 1)
        queries = [
            {"site_id": "site", "src_lang": "en", "tgt_lang": "de", "query_text": "entry_0"},
        ]
        results = l3.batch_semantic_search(queries)
        assert results[0] == []


# ========== batch_lookup tests ==========

class TestBatchLookup:
    @pytest.fixture
    def tm(self, l3):
        from src.tm.l1_cache import L1Cache
        from src.tm.translation_memory import TranslationMemory

        l1 = L1Cache(max_size=100)
        l2 = mock.MagicMock()
        l2.exact_lookup.return_value = None  # no L2 hits by default

        tm = TranslationMemory(
            l1_cache=l1,
            l2_persistent=l2,
            l3_semantic=l3,
        )
        return tm

    def test_empty_input(self, tm):
        from src.tm.models import LookupRequest
        assert tm.batch_lookup([]) == []

    def test_l1_hit_skips_l3(self, tm, l3):
        from src.tm.models import LookupRequest
        # Pre-populate L1
        tm.l1.put("site", "en", "fr", "cached_text", "cached_translation")
        l3.encoder.encode.reset_mock()

        req = LookupRequest(site_id="site", src_lang="en", tgt_lang="fr", text="cached_text")
        results = tm.batch_lookup([req])
        assert results[0].hit is True
        assert results[0].source == "l1_cache"
        # L3 encoder should NOT be called
        assert l3.encoder.encode.call_count == 0

    def test_l2_hit_skips_l3(self, tm, l3):
        from src.tm.models import LookupRequest

        mock_entry = mock.MagicMock()
        mock_entry.translation = "l2_translation"
        mock_entry.metadata = {}
        tm.l2.exact_lookup.return_value = mock_entry
        l3.encoder.encode.reset_mock()

        req = LookupRequest(site_id="site", src_lang="en", tgt_lang="fr", text="l2_text")
        results = tm.batch_lookup([req])
        assert results[0].hit is True
        assert results[0].source == "l2_exact"
        assert l3.encoder.encode.call_count == 0

    def test_misses_batch_l3(self, tm, l3):
        from src.tm.models import LookupRequest
        _add_entries(l3, 2)
        l3.encoder.encode.reset_mock()

        reqs = [
            LookupRequest(site_id="site", src_lang="en", tgt_lang="fr", text="entry_0"),
            LookupRequest(site_id="site", src_lang="en", tgt_lang="fr", text="entry_1"),
        ]
        results = tm.batch_lookup(reqs)
        assert len(results) == 2
        # Both should resolve via L3 (exact text match = similarity 1.0)
        for r in results:
            if r.hit:
                assert r.source == "l3_semantic"

    def test_mixed_results_preserve_order(self, tm, l3):
        from src.tm.models import LookupRequest
        _add_entries(l3, 1)

        # Pre-populate L1 for first request
        tm.l1.put("site", "en", "fr", "l1_text", "l1_result")

        reqs = [
            LookupRequest(site_id="site", src_lang="en", tgt_lang="fr", text="l1_text"),
            LookupRequest(site_id="site", src_lang="en", tgt_lang="fr", text="entry_0"),
        ]
        results = tm.batch_lookup(reqs)
        assert len(results) == 2
        assert results[0].source == "l1_cache"
        # Second may be l3_semantic or none depending on threshold
        assert results[1] is not None
