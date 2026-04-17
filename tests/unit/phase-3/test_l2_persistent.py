"""
Unit tests for L2 Persistent Translation Memory.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from tm.l2_persistent import L2PersistentTM, TranslationEntry
from tm.normalization import hash_text, make_tm_key, normalize_text


class TestNormalization:
    """Test text normalization utilities."""

    def test_normalize_whitespace(self) -> None:
        """Test whitespace normalization."""
        assert normalize_text("  hello   world  ") == "hello world"
        assert normalize_text("hello\n\nworld") == "hello world"
        assert normalize_text("hello\t\tworld") == "hello world"

    def test_normalize_unicode(self) -> None:
        """Test Unicode NFC normalization."""
        # These should be normalized to same form
        text1 = "café"  # é as single character
        text2 = "café"  # é as e + combining accent
        assert normalize_text(text1) == normalize_text(text2)

    def test_hash_text(self) -> None:
        """Test text hashing."""
        hash1 = hash_text("Hello World")
        hash2 = hash_text("  Hello   World  ")  # Same after normalization
        hash3 = hash_text("Different")

        assert hash1 == hash2  # Normalized to same
        assert hash1 != hash3  # Different text

    def test_make_tm_key(self) -> None:
        """Test TM key generation."""
        key = make_tm_key("site1", "en", "es", "Hello")
        assert key.startswith("site1:en:es:")
        assert len(key.split(":")) == 4


class TestTranslationEntry:
    """Test TranslationEntry model."""

    def test_entry_creation(self) -> None:
        """Test creating translation entry."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hola",
            site_id="site1",
            src_lang="en",
            tgt_lang="es",
        )

        assert entry.source_text == "Hello"
        assert entry.translation == "Hola"
        assert entry.timestamp is not None

    def test_entry_with_context(self) -> None:
        """Test entry with context."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hola",
            site_id="site1",
            src_lang="en",
            tgt_lang="es",
            context="frontmatter.title",
        )

        assert entry.context == "frontmatter.title"

    def test_entry_serialization(self) -> None:
        """Test to_dict and from_dict."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hola",
            site_id="site1",
            src_lang="en",
            tgt_lang="es",
            metadata={"source_file": "test.md"},
        )

        # Serialize
        data = entry.to_dict()
        assert data["source_text"] == "Hello"
        assert data["metadata"]["source_file"] == "test.md"

        # Deserialize
        entry2 = TranslationEntry.from_dict(data)
        assert entry2.source_text == entry.source_text
        assert entry2.translation == entry.translation


class TestL2PersistentTM:
    """Test L2 Persistent TM functionality."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Path:
        """Create temporary database directory."""
        return tmp_path / "test_tm_db"

    def test_initialization(self, temp_db: Path) -> None:
        """Test TM initialization."""
        with L2PersistentTM(temp_db, max_size_mb=100) as tm:
            assert tm.db_path == temp_db
            assert temp_db.exists()

    def test_store_and_lookup(self, temp_db: Path) -> None:
        """Test basic store and lookup."""
        with L2PersistentTM(temp_db) as tm:
            # Store translation
            key = tm.store("site1", "en", "es", "Hello", "Hola")
            assert key is not None

            # Lookup
            entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry is not None
            assert entry.translation == "Hola"
            assert entry.source_text == "Hello"

    def test_lookup_miss(self, temp_db: Path) -> None:
        """Test lookup of non-existent entry."""
        with L2PersistentTM(temp_db) as tm:
            entry = tm.exact_lookup("site1", "en", "es", "NotFound")
            assert entry is None

    def test_normalization_matching(self, temp_db: Path) -> None:
        """Test that normalized text matches."""
        with L2PersistentTM(temp_db) as tm:
            # Store with extra whitespace
            tm.store("site1", "en", "es", "  Hello   World  ", "Hola Mundo")

            # Lookup with different whitespace
            entry = tm.exact_lookup("site1", "en", "es", "Hello World")
            assert entry is not None
            assert entry.translation == "Hola Mundo"

    def test_different_languages(self, temp_db: Path) -> None:
        """Test same text in different language pairs."""
        with L2PersistentTM(temp_db) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")
            tm.store("site1", "en", "fr", "Hello", "Bonjour")

            # Different target languages
            entry_es = tm.exact_lookup("site1", "en", "es", "Hello")
            entry_fr = tm.exact_lookup("site1", "en", "fr", "Hello")

            assert entry_es.translation == "Hola"
            assert entry_fr.translation == "Bonjour"

    def test_context_filtering(self, temp_db: Path) -> None:
        """Test context-aware lookup."""
        with L2PersistentTM(temp_db) as tm:
            # Store with context
            tm.store("site1", "en", "es", "Title", "Título", context="frontmatter.title")

            # Lookup with matching context
            entry = tm.exact_lookup("site1", "en", "es", "Title", context="frontmatter.title")
            assert entry is not None

            # Lookup with different context
            entry = tm.exact_lookup("site1", "en", "es", "Title", context="body.heading")
            assert entry is None

    def test_batch_store(self, temp_db: Path) -> None:
        """Test batch storage."""
        with L2PersistentTM(temp_db) as tm:
            entries = [
                TranslationEntry("One", "Uno", "site1", "en", "es"),
                TranslationEntry("Two", "Dos", "site1", "en", "es"),
                TranslationEntry("Three", "Tres", "site1", "en", "es"),
            ]

            count = tm.batch_store(entries)
            assert count == 3

            # Verify stored
            assert tm.exact_lookup("site1", "en", "es", "One").translation == "Uno"
            assert tm.exact_lookup("site1", "en", "es", "Two").translation == "Dos"
            assert tm.exact_lookup("site1", "en", "es", "Three").translation == "Tres"

    def test_delete(self, temp_db: Path) -> None:
        """Test deletion of entries."""
        with L2PersistentTM(temp_db) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")

            # Verify exists
            assert tm.exact_lookup("site1", "en", "es", "Hello") is not None

            # Delete
            deleted = tm.delete("site1", "en", "es", "Hello")
            assert deleted is True

            # Verify gone
            assert tm.exact_lookup("site1", "en", "es", "Hello") is None

    def test_count(self, temp_db: Path) -> None:
        """Test entry counting."""
        with L2PersistentTM(temp_db) as tm:
            assert tm.count() == 0

            tm.store("site1", "en", "es", "One", "Uno")
            assert tm.count() == 1

            tm.store("site1", "en", "es", "Two", "Dos")
            assert tm.count() == 2

    def test_clear(self, temp_db: Path) -> None:
        """Test clearing database."""
        with L2PersistentTM(temp_db) as tm:
            tm.store("site1", "en", "es", "One", "Uno")
            tm.store("site1", "en", "es", "Two", "Dos")

            assert tm.count() == 2

            tm.clear()
            assert tm.count() == 0

    def test_persistence(self, temp_db: Path) -> None:
        """Test data persists across sessions."""
        # First session
        with L2PersistentTM(temp_db) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")

        # Second session
        with L2PersistentTM(temp_db) as tm:
            entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry is not None
            assert entry.translation == "Hola"

    def test_len(self, temp_db: Path) -> None:
        """Test __len__ method."""
        with L2PersistentTM(temp_db) as tm:
            assert len(tm) == 0

            tm.store("site1", "en", "es", "Hello", "Hola")
            assert len(tm) == 1

    def test_metadata_storage(self, temp_db: Path) -> None:
        """Test storing and retrieving metadata."""
        with L2PersistentTM(temp_db) as tm:
            metadata = {
                "source_file": "content/post.md",
                "segment_id": "abc123",
            }

            tm.store("site1", "en", "es", "Hello", "Hola", metadata=metadata)

            entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry.metadata["source_file"] == "content/post.md"
            assert entry.metadata["segment_id"] == "abc123"
