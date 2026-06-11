"""
Unit tests for L3 Semantic Translation Memory.
"""

from pathlib import Path

import pytest

from src.tm.l3_semantic import L3SemanticTM, SemanticMatch


@pytest.fixture
def temp_index_dir(tmp_path):
    """Temporary directory for FAISS index (pytest-managed, auto-cleaned)."""
    return tmp_path


@pytest.fixture
def semantic_tm(temp_index_dir):
    """Create L3SemanticTM instance."""
    tm = L3SemanticTM(index_path=temp_index_dir, embedding_model="all-MiniLM-L6-v2")
    return tm


class TestL3SemanticTMInitialization:
    """Test L3SemanticTM initialization."""

    def test_initialization(self, temp_index_dir):
        """Test basic initialization."""
        tm = L3SemanticTM(index_path=temp_index_dir)
        assert tm.index is not None
        assert tm.embedding_dim == 384  # all-MiniLM-L6-v2 dimension
        assert len(tm) == 0

    def test_index_directory_created(self, temp_index_dir):
        """Test that index directory is created."""
        tm = L3SemanticTM(index_path=temp_index_dir)
        assert temp_index_dir.exists()
        assert temp_index_dir.is_dir()


class TestAddEntry:
    """Test adding entries to semantic TM."""

    def test_add_single_entry(self, semantic_tm):
        """Test adding a single entry."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )
        assert len(semantic_tm) == 1

    def test_add_entry_with_context(self, semantic_tm):
        """Test adding entry with context."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Home",
            translation="Accueil",
            context="frontmatter.title",
        )
        assert len(semantic_tm) == 1

    def test_add_entry_with_metadata(self, semantic_tm):
        """Test adding entry with metadata."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Welcome",
            translation="Bienvenue",
            metadata={"source_file": "index.md", "confidence": 0.95},
        )
        assert len(semantic_tm) == 1

    def test_add_multiple_entries(self, semantic_tm):
        """Test adding multiple entries."""
        texts = [
            ("Hello", "Bonjour"),
            ("Good morning", "Bonjour"),
            ("Good afternoon", "Bon apres-midi"),
        ]

        for i, (src, tgt) in enumerate(texts):
            semantic_tm.add_entry(
                entry_id=f"entry_{i}",
                site_id="site_1",
                src_lang="en",
                tgt_lang="fr",
                source_text=src,
                translation=tgt,
            )

        assert len(semantic_tm) == 3


class TestSemanticSearch:
    """Test semantic search functionality."""

    def test_exact_match(self, semantic_tm):
        """Test finding exact match."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )

        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hello world",
            k=5,
            threshold=0.75,
        )

        assert len(results) == 1
        assert results[0].entry_id == "entry_1"
        assert results[0].similarity > 0.95  # Very high for exact match
        assert results[0].translation == "Bonjour le monde"

    def test_fuzzy_match(self, semantic_tm):
        """Test fuzzy matching for similar phrases."""
        # Add original
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )

        # Search for similar phrase
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hi world",  # Similar but not exact
            k=5,
            threshold=0.6,  # Lower threshold for fuzzy
        )

        assert len(results) >= 1
        assert results[0].entry_id == "entry_1"
        assert 0.6 <= results[0].similarity < 0.95  # Similar but not exact

    def test_no_match_below_threshold(self, semantic_tm):
        """Test that results below threshold are filtered."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )

        # Search for completely different text
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="The quick brown fox jumps",
            k=5,
            threshold=0.85,  # High threshold
        )

        # Should not match or have low similarity
        assert len(results) == 0 or results[0].similarity < 0.85

    def test_filter_by_site_id(self, semantic_tm):
        """Test filtering by site_id."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        semantic_tm.add_entry(
            entry_id="entry_2",
            site_id="site_2",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Salut",
        )

        # Search site_1
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hello",
            k=5,
            threshold=0.75,
        )

        assert len(results) == 1
        assert results[0].entry_id == "entry_1"
        assert results[0].translation == "Bonjour"

    def test_filter_by_language_pair(self, semantic_tm):
        """Test filtering by language pair."""
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        semantic_tm.add_entry(
            entry_id="entry_2",
            site_id="site_1",
            src_lang="en",
            tgt_lang="es",
            source_text="Hello",
            translation="Hola",
        )

        # Search for en->fr
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hello",
            k=5,
            threshold=0.75,
        )

        assert len(results) == 1
        assert results[0].entry_id == "entry_1"
        assert results[0].translation == "Bonjour"

    def test_top_k_results(self, semantic_tm):
        """Test returning top K results."""
        # Add many similar entries
        greetings = [
            "Hello",
            "Hi",
            "Hey",
            "Good morning",
            "Good day",
            "Greetings",
            "Welcome",
        ]

        for i, greeting in enumerate(greetings):
            semantic_tm.add_entry(
                entry_id=f"entry_{i}",
                site_id="site_1",
                src_lang="en",
                tgt_lang="fr",
                source_text=greeting,
                translation=f"Translation {i}",
            )

        # Search with k=3
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hi there",
            k=3,
            threshold=0.5,
        )

        assert len(results) <= 3

    def test_empty_index_search(self, semantic_tm):
        """Test searching empty index."""
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hello",
            k=5,
            threshold=0.75,
        )

        assert len(results) == 0


class TestBatchOperations:
    """Test batch add operations."""

    def test_batch_add_entries(self, semantic_tm):
        """Test adding multiple entries in batch."""
        entries = [
            {
                "entry_id": "entry_1",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "Hello",
                "translation": "Bonjour",
            },
            {
                "entry_id": "entry_2",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "Goodbye",
                "translation": "Au revoir",
            },
            {
                "entry_id": "entry_3",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "Thank you",
                "translation": "Merci",
            },
        ]

        count = semantic_tm.batch_add(entries)
        assert count == 3
        assert len(semantic_tm) == 3

    def test_batch_add_with_context_and_metadata(self, semantic_tm):
        """Test batch add with context and metadata."""
        entries = [
            {
                "entry_id": "entry_1",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "Home",
                "translation": "Accueil",
                "context": "frontmatter.title",
                "metadata": {"file": "index.md"},
            },
            {
                "entry_id": "entry_2",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "About",
                "translation": "� propos",
                "context": "frontmatter.title",
                "metadata": {"file": "about.md"},
            },
        ]

        count = semantic_tm.batch_add(entries)
        assert count == 2

    def test_batch_add_empty_list(self, semantic_tm):
        """Test batch add with empty list."""
        count = semantic_tm.batch_add([])
        assert count == 0
        assert len(semantic_tm) == 0


class TestPersistence:
    """Test index persistence."""

    def test_save_and_load_index(self, temp_index_dir):
        """Test saving and loading index."""
        # Create and populate TM
        tm1 = L3SemanticTM(index_path=temp_index_dir)
        tm1.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello world",
            translation="Bonjour le monde",
        )
        tm1.save_index()

        # Create new instance and load
        tm2 = L3SemanticTM(index_path=temp_index_dir)
        assert len(tm2) == 1

        # Verify data
        results = tm2.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="Hello world",
            k=5,
            threshold=0.75,
        )

        assert len(results) == 1
        assert results[0].entry_id == "entry_1"
        assert results[0].translation == "Bonjour le monde"

    def test_context_manager(self, temp_index_dir):
        """Test context manager saves index."""
        # Use context manager
        with L3SemanticTM(index_path=temp_index_dir) as tm:
            tm.add_entry(
                entry_id="entry_1",
                site_id="site_1",
                src_lang="en",
                tgt_lang="fr",
                source_text="Hello",
                translation="Bonjour",
            )
        # Index should be saved on exit

        # Load in new instance
        tm2 = L3SemanticTM(index_path=temp_index_dir)
        assert len(tm2) == 1

    def test_persistence_files_created(self, temp_index_dir):
        """Test that persistence files are created."""
        tm = L3SemanticTM(index_path=temp_index_dir)
        tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )
        tm.save_index()

        # Check files exist
        assert (temp_index_dir / "index.faiss").exists()
        assert (temp_index_dir / "metadata.pkl").exists()
        assert (temp_index_dir / "config.json").exists()


class TestRebuildIndex:
    """Test index rebuild functionality."""

    def test_rebuild_index(self, semantic_tm):
        """Test rebuilding index from entries."""
        entries = [
            {
                "entry_id": "entry_1",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "Hello",
                "translation": "Bonjour",
            },
            {
                "entry_id": "entry_2",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "Goodbye",
                "translation": "Au revoir",
            },
        ]

        semantic_tm.rebuild_index(entries)
        assert len(semantic_tm) == 2

    def test_rebuild_clears_existing(self, semantic_tm):
        """Test that rebuild clears existing entries."""
        # Add initial entry
        semantic_tm.add_entry(
            entry_id="old_entry",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Old text",
            translation="Vieux texte",
        )
        assert len(semantic_tm) == 1

        # Rebuild with new entries
        new_entries = [
            {
                "entry_id": "entry_1",
                "site_id": "site_1",
                "src_lang": "en",
                "tgt_lang": "fr",
                "source_text": "New text",
                "translation": "Nouveau texte",
            }
        ]

        semantic_tm.rebuild_index(new_entries)
        assert len(semantic_tm) == 1

        # Old entry should be gone
        results = semantic_tm.semantic_search(
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            query_text="New text",
            k=5,
            threshold=0.75,
        )

        assert len(results) == 1
        assert results[0].entry_id == "entry_1"


class TestClearAndCount:
    """Test clear and count operations."""

    def test_count(self, semantic_tm):
        """Test count method."""
        assert semantic_tm.count() == 0

        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        assert semantic_tm.count() == 1

    def test_len(self, semantic_tm):
        """Test __len__ method."""
        assert len(semantic_tm) == 0

        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        assert len(semantic_tm) == 1

    def test_clear(self, semantic_tm):
        """Test clearing index."""
        # Add entries
        semantic_tm.add_entry(
            entry_id="entry_1",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            source_text="Hello",
            translation="Bonjour",
        )

        assert len(semantic_tm) == 1

        # Clear
        semantic_tm.clear()
        assert len(semantic_tm) == 0


class TestSemanticMatch:
    """Test SemanticMatch dataclass."""

    def test_to_dict(self):
        """Test converting SemanticMatch to dict."""
        match = SemanticMatch(
            entry_id="entry_1",
            similarity=0.95,
            source_text="Hello",
            translation="Bonjour",
            site_id="site_1",
            src_lang="en",
            tgt_lang="fr",
            context="frontmatter.title",
            metadata={"file": "index.md"},
        )

        match_dict = match.to_dict()
        assert match_dict["entry_id"] == "entry_1"
        assert match_dict["similarity"] == 0.95
        assert match_dict["source_text"] == "Hello"
        assert match_dict["translation"] == "Bonjour"
        assert match_dict["context"] == "frontmatter.title"
