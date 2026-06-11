"""
Unit tests for L3SemanticTM.update_entry() (Stage 2B fix).

Covers:
- update_entry() patches translation in-place in metadata list
- update_entry() updates all positions for the same entry_id (if duplicated by legacy adds)
- update_entry() returns False when entry_id not found
- update_entry() also applies new_metadata when provided
- add_entry() populates _entry_id_to_positions so update_entry() can find the entry
- Translation memory store with skip_l3=True does not call add_entry()
"""

from pathlib import Path
from unittest import mock

import numpy as np
import pytest

from src.tm.l3_semantic import L3SemanticTM

_DIM = 384  # embedding dimension used by the fixture


@pytest.fixture
def l3(tmp_path):
    """
    Create an L3SemanticTM with a real FAISS index but a mocked SentenceTransformer.

    The mock encoder returns a deterministic zero-vector with the correct shape so
    that faiss.index.add() succeeds regardless of which test runs first in the suite.
    Instance-level patching avoids fragile sys.modules injection that breaks when
    faiss/numpy are already imported earlier in the test session.
    """
    instance = L3SemanticTM(
        index_path=tmp_path / "l3_index",
        embedding_model="all-MiniLM-L6-v2",
        use_gpu=False,
        save_interval=0,  # disable periodic saves in unit tests
    )
    mock_encoder = mock.MagicMock()
    mock_encoder.encode.return_value = np.zeros(_DIM, dtype=np.float32)
    mock_encoder.get_sentence_embedding_dimension.return_value = _DIM
    instance.encoder = mock_encoder
    return instance


class TestUpdateEntry:
    def test_update_entry_returns_false_when_not_found(self, l3):
        """update_entry returns False for unknown entry_id."""
        result = l3.update_entry("nonexistent-id", "New translation")
        assert result is False

    def test_add_then_update_patches_translation(self, l3):
        """After add_entry(), update_entry() changes the translation in metadata."""
        entry_id = "site:en:fr:12345"
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        result = l3.update_entry(entry_id, "Salut")
        assert result is True

        # Find the entry in metadata and verify translation was updated
        matches = [m for m in l3.metadata if m.get("entry_id") == entry_id]
        assert len(matches) == 1
        assert matches[0]["translation"] == "Salut"

    def test_update_entry_does_not_change_source_text(self, l3):
        """update_entry() must not change source_text or embedding-related fields."""
        entry_id = "site:en:de:99"
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="de",
            source_text="Goodbye",
            translation="Auf Wiedersehen",
        )

        l3.update_entry(entry_id, "Tschüss")

        entry = next(m for m in l3.metadata if m["entry_id"] == entry_id)
        assert entry["source_text"] == "Goodbye"

    def test_update_entry_applies_new_metadata(self, l3):
        """new_metadata dict is merged into the existing metadata sub-dict."""
        entry_id = "site:en:ar:77"
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="ar",
            source_text="World",
            translation="عالم",
        )

        extra = {"improved_by": "tm_improvement_worker", "score": 0.95}
        result = l3.update_entry(entry_id, "دنيا", new_metadata=extra)
        assert result is True

        entry = next(m for m in l3.metadata if m["entry_id"] == entry_id)
        assert entry["translation"] == "دنيا"
        assert entry["metadata"]["improved_by"] == "tm_improvement_worker"
        assert entry["metadata"]["score"] == 0.95

    def test_update_patches_all_positions_for_same_entry_id(self, l3):
        """
        If the same entry_id appears at multiple positions (legacy duplicate adds),
        update_entry() patches all of them.
        """
        entry_id = "site:en:fr:dup"
        # Add twice (simulating old append-only behaviour)
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="fr",
            source_text="Cat",
            translation="Chat",
        )
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="fr",
            source_text="Cat",
            translation="Minou",
        )

        result = l3.update_entry(entry_id, "Félin")
        assert result is True

        matches = [m for m in l3.metadata if m["entry_id"] == entry_id]
        assert len(matches) == 2
        for m in matches:
            assert m["translation"] == "Félin"

    def test_entry_id_to_positions_populated_on_add(self, l3):
        """_entry_id_to_positions is populated after add_entry()."""
        entry_id = "site:en:es:55"
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="es",
            source_text="Dog",
            translation="Perro",
        )
        assert entry_id in l3._entry_id_to_positions
        assert len(l3._entry_id_to_positions[entry_id]) == 1

    def test_no_vector_added_on_update(self, l3):
        """update_entry() must NOT grow the FAISS index — vectors stay unchanged."""
        entry_id = "site:en:it:33"
        l3.add_entry(
            entry_id=entry_id,
            site_id="site",
            src_lang="en",
            tgt_lang="it",
            source_text="Bird",
            translation="Uccello",
        )
        ntotal_before = l3.index.ntotal

        l3.update_entry(entry_id, "Volatile")

        # Index size must not change after an in-place metadata update
        assert l3.index.ntotal == ntotal_before


class TestSkipL3Flag:
    """Tests for translation_memory.store(skip_l3=True)."""

    def test_skip_l3_prevents_add_entry_call(self, tmp_path):
        """When skip_l3=True, tm.store() must not call l3.add_entry()."""
        # Import here to avoid circular-dependency issues in module-level mocking
        from unittest.mock import MagicMock, patch

        from src.tm.translation_memory import TranslationMemory

        mock_l3 = MagicMock()
        mock_l3.add_entry = MagicMock()

        mock_l2 = MagicMock()
        mock_l2.store.return_value = True  # simulate successful L2 write

        mock_l1 = MagicMock()
        mock_override = MagicMock()
        mock_override.should_update_cache.return_value = True

        tm = TranslationMemory.__new__(TranslationMemory)
        tm.l1 = mock_l1
        tm.l2 = mock_l2
        tm.l3 = mock_l3
        tm.override = mock_override
        tm.improvement_queue = None

        tm.store(
            site_id="site",
            src_lang="en",
            tgt_lang="fr",
            text="Hello",
            translation="Salut",
            force_update=True,
            skip_l3=True,
        )

        mock_l3.add_entry.assert_not_called()

    def test_without_skip_l3_calls_add_entry(self, tmp_path):
        """When skip_l3=False (default), tm.store() calls l3.add_entry()."""
        from unittest.mock import MagicMock

        from src.tm.translation_memory import TranslationMemory

        mock_l3 = MagicMock()
        mock_l3.add_entry = MagicMock()

        mock_l2 = MagicMock()
        mock_l2.store.return_value = True

        mock_l1 = MagicMock()
        mock_override = MagicMock()
        mock_override.should_update_cache.return_value = True

        tm = TranslationMemory.__new__(TranslationMemory)
        tm.l1 = mock_l1
        tm.l2 = mock_l2
        tm.l3 = mock_l3
        tm.override = mock_override
        tm.improvement_queue = None

        tm.store(
            site_id="site",
            src_lang="en",
            tgt_lang="fr",
            text="Hello",
            translation="Salut",
            force_update=True,
            skip_l3=False,
        )

        mock_l3.add_entry.assert_called_once()
