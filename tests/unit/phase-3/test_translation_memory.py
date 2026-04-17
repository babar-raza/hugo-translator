"""
Unit tests for Unified Translation Memory Interface.
"""
from pathlib import Path

import pytest

from src.tm import (
    L1Cache,
    L2PersistentTM,
    L3SemanticTM,
    LookupRequest,
    TranslationEntry,
    TranslationMemory,
)


@pytest.fixture
def temp_tm_dir(tmp_path):
    """Temporary directory for TM storage (pytest-managed, auto-cleaned)."""
    return tmp_path


@pytest.fixture
def tm_components(temp_tm_dir):
    """Create TM components."""
    l1 = L1Cache(max_size=100)
    l2 = L2PersistentTM(db_path=temp_tm_dir / "l2.lmdb")
    l3 = L3SemanticTM(index_path=temp_tm_dir / "l3_index")
    return l1, l2, l3


@pytest.fixture
def tm_with_l3(tm_components):
    """Create TM with all 3 layers."""
    l1, l2, l3 = tm_components
    return TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=l3)


@pytest.fixture
def tm_without_l3(temp_tm_dir):
    """Create TM without L3 (semantic disabled)."""
    l1 = L1Cache(max_size=100)
    l2 = L2PersistentTM(db_path=temp_tm_dir / "l2.lmdb")
    return TranslationMemory(l1_cache=l1, l2_persistent=l2, l3_semantic=None)


class TestTranslationMemoryInitialization:
    """Test TM initialization."""

    def test_init_with_all_layers(self, tm_with_l3):
        """Test initialization with all 3 layers."""
        assert tm_with_l3.l1 is not None
        assert tm_with_l3.l2 is not None
        assert tm_with_l3.l3 is not None

    def test_init_without_l3(self, tm_without_l3):
        """Test initialization without L3."""
        assert tm_without_l3.l1 is not None
        assert tm_without_l3.l2 is not None
        assert tm_without_l3.l3 is None


class TestLayeredLookup:
    """Test layered lookup strategy."""

    def test_l1_cache_hit(self, tm_with_l3):
        """Test L1 cache hit (fastest path)."""
        # Populate L1 cache
        tm_with_l3.l1.put("site1", "en", "fr", "Hello", "Bonjour")

        # Lookup should hit L1
        result = tm_with_l3.lookup("site1", "en", "fr", "Hello")

        assert result.hit is True
        assert result.translation == "Bonjour"
        assert result.source == "l1_cache"
        assert result.confidence == 1.0

    def test_l2_exact_match(self, tm_with_l3):
        """Test L2 exact match (L1 miss)."""
        # Store in L2 only
        tm_with_l3.l2.store("site1", "en", "fr", "Hello", "Bonjour")

        # Lookup should hit L2
        result = tm_with_l3.lookup("site1", "en", "fr", "Hello")

        assert result.hit is True
        assert result.translation == "Bonjour"
        assert result.source == "l2_exact"
        assert result.confidence == 1.0

        # L1 should now be populated
        cached = tm_with_l3.l1.get("site1", "en", "fr", "Hello")
        assert cached == "Bonjour"

    def test_l3_semantic_match(self, tm_with_l3):
        """Test L3 semantic match (L1 and L2 miss)."""
        # Store in L3 only
        tm_with_l3.l3.add_entry(
            entry_id="entry_1",
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )

        # Lookup similar text
        result = tm_with_l3.lookup(
            "site1", "en", "fr", "Hello world", semantic_threshold=0.75
        )

        assert result.hit is True
        assert result.translation == "Bonjour le monde"
        assert result.source == "l3_semantic"
        assert result.confidence > 0.75
        assert len(result.candidates) >= 1

        # L1 should now be populated
        cached = tm_with_l3.l1.get("site1", "en", "fr", "Hello world")
        assert cached == "Bonjour le monde"

    def test_no_match(self, tm_with_l3):
        """Test when no match found in any layer."""
        result = tm_with_l3.lookup("site1", "en", "fr", "Nonexistent text")

        assert result.hit is False
        assert result.translation is None
        assert result.source == "none"
        assert result.confidence == 0.0

    def test_exact_preferred_over_semantic(self, tm_with_l3):
        """Test that exact match is preferred over semantic."""
        # Store exact in L2
        tm_with_l3.l2.store("site1", "en", "fr", "Hello", "Bonjour exact")

        # Store semantic in L3
        tm_with_l3.l3.add_entry(
            entry_id="entry_1",
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour semantic",
        )

        # Lookup should return exact match
        result = tm_with_l3.lookup("site1", "en", "fr", "Hello")

        assert result.hit is True
        assert result.translation == "Bonjour exact"
        assert result.source == "l2_exact"


class TestStore:
    """Test storing translations."""

    def test_store_single(self, tm_with_l3):
        """Test storing single translation."""
        entry_id = tm_with_l3.store(
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            text="Hello",
            translation="Bonjour",
        )

        assert entry_id is not None

        # Should be in L1
        assert tm_with_l3.l1.get("site1", "en", "fr", "Hello") == "Bonjour"

        # Should be in L2
        l2_entry = tm_with_l3.l2.exact_lookup("site1", "en", "fr", "Hello")
        assert l2_entry is not None
        assert l2_entry.translation == "Bonjour"

        # Should be in L3
        assert len(tm_with_l3.l3) == 1

    def test_store_with_context(self, tm_with_l3):
        """Test storing with context."""
        tm_with_l3.store(
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            text="Home",
            translation="Accueil",
            context="frontmatter.title",
        )

        # Should be retrievable
        result = tm_with_l3.lookup("site1", "en", "fr", "Home")
        assert result.hit is True
        assert result.translation == "Accueil"

    def test_store_with_metadata(self, tm_with_l3):
        """Test storing with metadata."""
        tm_with_l3.store(
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            text="Hello",
            translation="Bonjour",
            metadata={"source_file": "index.md", "confidence": 0.95},
        )

        # Metadata should be preserved in L2
        l2_entry = tm_with_l3.l2.exact_lookup("site1", "en", "fr", "Hello")
        assert l2_entry.metadata["source_file"] == "index.md"
        assert l2_entry.metadata["confidence"] == 0.95


class TestBatchOperations:
    """Test batch operations."""

    def test_batch_lookup(self, tm_with_l3):
        """Test batch lookup."""
        # Store some translations
        tm_with_l3.store("site1", "en", "fr", "Hello", "Bonjour")
        tm_with_l3.store("site1", "en", "fr", "Goodbye", "Au revoir")
        tm_with_l3.store("site1", "en", "fr", "Thank you", "Merci")

        # Batch lookup
        requests = [
            LookupRequest("site1", "en", "fr", "Hello"),
            LookupRequest("site1", "en", "fr", "Goodbye"),
            LookupRequest("site1", "en", "fr", "Unknown"),
        ]

        results = tm_with_l3.batch_lookup(requests)

        assert len(results) == 3
        assert results[0].hit is True
        assert results[0].translation == "Bonjour"
        assert results[1].hit is True
        assert results[1].translation == "Au revoir"
        assert results[2].hit is False

    def test_batch_store(self, tm_with_l3):
        """Test batch store."""
        entries = [
            TranslationEntry(
                source_text="Hello",
                translation="Bonjour",
                site_id="site1",
                src_lang="en",
                tgt_lang="fr",
            ),
            TranslationEntry(
                source_text="Goodbye",
                translation="Au revoir",
                site_id="site1",
                src_lang="en",
                tgt_lang="fr",
            ),
            TranslationEntry(
                source_text="Thank you",
                translation="Merci",
                site_id="site1",
                src_lang="en",
                tgt_lang="fr",
            ),
        ]

        count = tm_with_l3.batch_store(entries)
        assert count == 3

        # Should be in L2
        assert len(tm_with_l3.l2) == 3

        # Should be in L3
        assert len(tm_with_l3.l3) == 3


class TestStatistics:
    """Test statistics collection."""

    def test_stats_initial(self, tm_with_l3):
        """Test initial stats."""
        stats = tm_with_l3.stats()

        assert stats.l1_size == 0
        assert stats.l2_size == 0
        assert stats.l3_size == 0
        assert stats.total_lookups == 0
        assert stats.total_hits == 0
        assert stats.overall_hit_rate == 0.0

    def test_stats_after_operations(self, tm_with_l3):
        """Test stats after operations."""
        # Store some translations
        tm_with_l3.store("site1", "en", "fr", "Hello", "Bonjour")
        tm_with_l3.store("site1", "en", "fr", "Goodbye", "Au revoir")

        # Do some lookups
        tm_with_l3.lookup("site1", "en", "fr", "Hello")  # Hit
        tm_with_l3.lookup("site1", "en", "fr", "Goodbye")  # Hit
        tm_with_l3.lookup("site1", "en", "fr", "Unknown")  # Miss

        stats = tm_with_l3.stats()

        assert stats.l1_size == 2  # 2 stored
        assert stats.l2_size == 2  # 2 stored
        assert stats.l3_size == 2  # 2 stored
        assert stats.total_lookups == 3  # 3 lookups
        assert stats.total_hits == 2  # 2 hits
        assert stats.overall_hit_rate == 2 / 3  # 66.7%

    def test_stats_to_dict(self, tm_with_l3):
        """Test stats to_dict."""
        stats = tm_with_l3.stats()
        stats_dict = stats.to_dict()

        assert isinstance(stats_dict, dict)
        assert "l1_size" in stats_dict
        assert "l2_size" in stats_dict
        assert "overall_hit_rate" in stats_dict


class TestSemanticControl:
    """Test semantic search control."""

    def test_semantic_disabled_in_lookup(self, tm_with_l3):
        """Test disabling semantic in individual lookup."""
        # Store only in L3
        tm_with_l3.l3.add_entry(
            entry_id="entry_1",
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        # Lookup with semantic disabled
        result = tm_with_l3.lookup("site1", "en", "fr", "Hello", use_semantic=False)

        assert result.hit is False  # Should not hit L3

    def test_semantic_threshold(self, tm_with_l3):
        """Test semantic threshold filtering."""
        # Store in L3
        tm_with_l3.l3.add_entry(
            entry_id="entry_1",
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )

        # Lookup with very high threshold
        result = tm_with_l3.lookup(
            "site1",
            "en",
            "fr",
            "Different text completely unrelated",
            use_semantic=True,
            semantic_threshold=0.95,
        )

        # Should not match due to high threshold
        assert result.hit is False

    def test_tm_without_l3_layer(self, tm_without_l3):
        """Test TM without L3 layer."""
        # Store in L2
        tm_without_l3.store("site1", "en", "fr", "Hello", "Bonjour")

        # Lookup should work (will hit L1 cache since store populated it)
        result = tm_without_l3.lookup("site1", "en", "fr", "Hello")
        assert result.hit is True
        # Could be L1 or L2 depending on store implementation
        assert result.source in ["l1_cache", "l2_exact"]

        # Stats should show L3 size as 0
        stats = tm_without_l3.stats()
        assert stats.l3_size == 0


class TestClearAndClose:
    """Test clear and close operations."""

    def test_clear(self, tm_with_l3):
        """Test clearing all layers."""
        # Store some data
        tm_with_l3.store("site1", "en", "fr", "Hello", "Bonjour")
        tm_with_l3.lookup("site1", "en", "fr", "Hello")

        # Clear
        tm_with_l3.clear()

        # All layers should be empty
        assert len(tm_with_l3.l1) == 0
        assert len(tm_with_l3.l2) == 0
        assert len(tm_with_l3.l3) == 0

        # Stats should be reset
        stats = tm_with_l3.stats()
        assert stats.total_lookups == 0
        assert stats.total_hits == 0

    def test_close(self, tm_with_l3):
        """Test closing resources."""
        # Store some data
        tm_with_l3.store("site1", "en", "fr", "Hello", "Bonjour")

        # Close
        tm_with_l3.close()

        # L2 should be closed (we can't test this directly, but it shouldn't error)

    def test_close_without_l3(self, tm_without_l3):
        """Test closing when L3 is None."""
        tm_without_l3.close()  # Should not error


class TestLookupResult:
    """Test LookupResult model."""

    def test_lookup_result_to_dict(self, tm_with_l3):
        """Test LookupResult to_dict."""
        # Store and lookup to get a result with candidates
        tm_with_l3.l3.add_entry(
            entry_id="entry_1",
            site_id="site1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        result = tm_with_l3.lookup("site1", "en", "fr", "Hello", use_semantic=True)

        result_dict = result.to_dict()
        assert isinstance(result_dict, dict)
        assert result_dict["hit"] is True
        assert result_dict["translation"] == "Bonjour"
        assert result_dict["source"] == "l3_semantic"
        assert "candidates" in result_dict
