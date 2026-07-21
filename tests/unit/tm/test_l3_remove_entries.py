"""
HT-QUALITY-GATES-001 TC-QG-L3-FIX: L3SemanticTM.remove_entries().

L3's FAISS index (IndexFlatL2, no ID-mapping wrapper) has no built-in
deletion — only add_entry()/batch_add(). A direct-audit cross-check found
16,533 of 27,614 products.aspose.org L3 entries overlap with the (source_
text, tgt_lang) pairs already purged from L2 as poisoned/defective — L3
never had a way to purge them and could still serve poisoned near-matches
via semantic_search() even after the L2 purge.

Verifies:
- remove_entries(predicate) removes exactly the matching entries and
  rebuilds so metadata/vector count stay in sync (count() reflects it).
- Survivors' source_text/translation/entry_id are preserved unchanged.
- Removed entries are genuinely gone from semantic_search() results.
- Survivors remain searchable after the rebuild (proves re-embedding ran,
  not just metadata filtering).
- Returns 0, and does not touch the index, when nothing matches.
- _entry_id_to_positions stays correct after removal (a stale/wrong lookup
  here would be exactly the position-desync bug this design avoids).
"""
from unittest import mock

import numpy as np
import pytest

from src.tm.l3_semantic import L3SemanticTM

_DIM = 384


@pytest.fixture
def l3(tmp_path):
    instance = L3SemanticTM(
        index_path=tmp_path / "l3_index",
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=0,
    )
    mock_encoder = mock.MagicMock()

    # Distinct-but-deterministic vectors per source text so semantic_search
    # can actually distinguish entries (an all-zeros mock, as used by the
    # update_entry tests, would make every entry equidistant and defeat the
    # "survivors remain searchable / removed entries are gone" assertions).
    def _encode(text, convert_to_numpy=True, show_progress_bar=False, batch_size=None):
        if isinstance(text, list):
            return np.array([_vec_for(t) for t in text], dtype=np.float32)
        return _vec_for(text)

    def _vec_for(t):
        rng = np.random.default_rng(abs(hash(t)) % (2**32))
        return rng.random(_DIM, dtype=np.float32)

    mock_encoder.encode.side_effect = _encode
    mock_encoder.get_sentence_embedding_dimension.return_value = _DIM
    instance.encoder = mock_encoder
    return instance


def _add(l3, entry_id, site_id, tgt_lang, source_text, translation="x"):
    l3.add_entry(
        entry_id=entry_id, site_id=site_id, src_lang="en", tgt_lang=tgt_lang,
        source_text=source_text, translation=translation,
    )


class TestRemoveEntries:
    def test_removes_matching_and_keeps_survivors_in_sync(self, l3):
        _add(l3, "e1", "products.aspose.org", "hr", "Aspose.Cells FOSS for .NET", "za .NET")
        _add(l3, "e2", "products.aspose.org", "hr", "Some other text", "translation2")
        _add(l3, "e3", "docs.aspose.org", "hr", "Aspose.Cells FOSS for .NET", "translation3")
        assert l3.count() == 3

        removed = l3.remove_entries(
            lambda m: m["site_id"] == "products.aspose.org"
            and m["tgt_lang"] == "hr"
            and m["source_text"] == "Aspose.Cells FOSS for .NET"
        )

        assert removed == 1
        assert l3.count() == 2
        remaining_ids = {m["entry_id"] for m in l3.metadata}
        assert remaining_ids == {"e2", "e3"}

    def test_survivors_preserve_fields_unchanged(self, l3):
        _add(l3, "keep-1", "site", "fr", "Bonjour le monde", "Hello world")
        _add(l3, "drop-1", "site", "fr", "A supprimer", "To be removed")

        l3.remove_entries(lambda m: m["entry_id"] == "drop-1")

        assert l3.count() == 1
        survivor = l3.metadata[0]
        assert survivor["entry_id"] == "keep-1"
        assert survivor["source_text"] == "Bonjour le monde"
        assert survivor["translation"] == "Hello world"

    def test_removed_entry_not_returned_by_semantic_search(self, l3):
        _add(l3, "bad", "products.aspose.org", "hr", "poisoned source text", "poisoned translation")
        _add(l3, "good", "products.aspose.org", "hr", "clean source text", "clean translation")

        l3.remove_entries(lambda m: m["entry_id"] == "bad")

        results = l3.semantic_search(
            "products.aspose.org", "en", "hr", "poisoned source text", k=5, threshold=0.0
        )
        returned_texts = {r.source_text for r in results}
        assert "poisoned source text" not in returned_texts

    def test_survivors_remain_searchable_after_rebuild(self, l3):
        _add(l3, "good", "products.aspose.org", "hr", "clean source text", "clean translation")
        _add(l3, "bad", "products.aspose.org", "hr", "poisoned source text", "poisoned translation")

        l3.remove_entries(lambda m: m["entry_id"] == "bad")

        results = l3.semantic_search(
            "products.aspose.org", "en", "hr", "clean source text", k=5, threshold=0.0
        )
        assert any(r.entry_id == "good" for r in results)

    def test_no_match_is_noop(self, l3):
        _add(l3, "e1", "site", "fr", "text one", "trans one")
        before = list(l3.metadata)

        removed = l3.remove_entries(lambda m: m["site_id"] == "nonexistent-site")

        assert removed == 0
        assert l3.count() == 1
        assert l3.metadata == before

    def test_entry_id_to_positions_stays_correct_after_removal(self, l3):
        _add(l3, "a", "site", "fr", "text a", "trans a")
        _add(l3, "b", "site", "fr", "text b", "trans b")
        _add(l3, "c", "site", "fr", "text c", "trans c")

        l3.remove_entries(lambda m: m["entry_id"] == "a")

        # update_entry() relies on _entry_id_to_positions -- a stale/wrong
        # mapping after removal would either silently no-op or patch the
        # wrong metadata row.
        assert l3.update_entry("b", "updated trans b") is True
        matches = [m for m in l3.metadata if m["entry_id"] == "b"]
        assert len(matches) == 1
        assert matches[0]["translation"] == "updated trans b"

        # "c" must still resolve to its own row, not "b"'s or a stale index.
        c_matches = [m for m in l3.metadata if m["entry_id"] == "c"]
        assert len(c_matches) == 1
        assert c_matches[0]["translation"] == "trans c"
