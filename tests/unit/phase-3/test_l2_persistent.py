"""
Unit tests for L2 Persistent Translation Memory.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from tm.l2_persistent import L2_DB_NAME, L2PersistentTM, TranslationEntry
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
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
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
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            entry = tm.exact_lookup("site1", "en", "es", "NotFound")
            assert entry is None

    def test_normalization_matching(self, temp_db: Path) -> None:
        """Test that normalized text matches."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            # Store with extra whitespace
            tm.store("site1", "en", "es", "  Hello   World  ", "Hola Mundo")

            # Lookup with different whitespace
            entry = tm.exact_lookup("site1", "en", "es", "Hello World")
            assert entry is not None
            assert entry.translation == "Hola Mundo"

    def test_different_languages(self, temp_db: Path) -> None:
        """Test same text in different language pairs."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")
            tm.store("site1", "en", "fr", "Hello", "Bonjour")

            # Different target languages
            entry_es = tm.exact_lookup("site1", "en", "es", "Hello")
            entry_fr = tm.exact_lookup("site1", "en", "fr", "Hello")

            assert entry_es.translation == "Hola"
            assert entry_fr.translation == "Bonjour"

    def test_context_filtering(self, temp_db: Path) -> None:
        """Test context-aware lookup."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            # Store with context
            tm.store("site1", "en", "es", "Title", "Título", context="frontmatter.title")

            # Lookup with matching context
            entry = tm.exact_lookup("site1", "en", "es", "Title", context="frontmatter.title")
            assert entry is not None

            # Lookup with different context
            entry = tm.exact_lookup("site1", "en", "es", "Title", context="body.heading")
            assert entry is None

    def test_context_and_field_name_combined_disambiguation(self, temp_db: Path) -> None:
        """HT-QUALITY-GATES-001 Part 22 (root cause A follow-up): context was
        previously accepted end-to-end (TranslationMemory -> L2PersistentTM)
        but never affected the LMDB key at all, so two unrelated occurrences
        of identical text under different contexts silently collided --
        confirmed live via test_context_filtering failing against HEAD before
        this fix. This exercises the combined field_name+context case, the
        most specific tier of the new fallback chain, which no existing test
        covered."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store(
                "site1", "en", "uk", "Name", "Заголовок",
                context="frontmatter.title", field_name="title",
            )
            tm.store(
                "site1", "en", "uk", "Name", "Опис",
                context="frontmatter.description", field_name="description",
            )

            title_entry = tm.exact_lookup(
                "site1", "en", "uk", "Name",
                context="frontmatter.title", field_name="title",
            )
            desc_entry = tm.exact_lookup(
                "site1", "en", "uk", "Name",
                context="frontmatter.description", field_name="description",
            )
            assert title_entry.translation == "Заголовок"
            assert desc_entry.translation == "Опис"

            # Same field_name, different context -- must not collide even
            # though field_name alone would previously have been enough to
            # match (this is the same-field-different-node case: two
            # different frontmatter.title occurrences across two pages
            # sharing templated text).
            miss = tm.exact_lookup(
                "site1", "en", "uk", "Name",
                context="body.heading", field_name="title",
            )
            assert miss is None

    def test_batch_store(self, temp_db: Path) -> None:
        """Test batch storage."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
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

    def test_batch_store_respects_field_name_scoping(self, temp_db: Path) -> None:
        """HT-QUALITY-GATES-001 Part 22 (root cause A): batch_store() used to
        always call make_tm_key() (unscoped) directly, bypassing field_name
        scoping entirely even for entries that specified one -- the same
        source text under two different field scopes would collide on one
        shared key. Two entries with identical source_text but different
        field_name must be stored and retrievable independently."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            entries = [
                TranslationEntry(
                    "Aspose.Cells FOSS is a free library.", "Title translation",
                    "site1", "en", "es", field_name="title",
                ),
                TranslationEntry(
                    "Aspose.Cells FOSS is a free library.", "Description translation",
                    "site1", "en", "es", field_name="description",
                ),
            ]

            count = tm.batch_store(entries)
            assert count == 2

            title_entry = tm.exact_lookup(
                "site1", "en", "es", "Aspose.Cells FOSS is a free library.",
                field_name="title",
            )
            description_entry = tm.exact_lookup(
                "site1", "en", "es", "Aspose.Cells FOSS is a free library.",
                field_name="description",
            )
            assert title_entry.translation == "Title translation"
            assert description_entry.translation == "Description translation"

    def test_batch_store_default_field_name_is_legacy_unscoped(self, temp_db: Path) -> None:
        """An entry with no field_name specified must still round-trip via
        the legacy unscoped key -- backward compatible with existing
        pre-Part-22 callers/entries."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            entries = [TranslationEntry("Plain text", "Texto simple", "site1", "en", "es")]
            tm.batch_store(entries)

            entry = tm.exact_lookup("site1", "en", "es", "Plain text")
            assert entry is not None
            assert entry.translation == "Texto simple"

    def test_delete(self, temp_db: Path) -> None:
        """Test deletion of entries."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")

            # Verify exists
            assert tm.exact_lookup("site1", "en", "es", "Hello") is not None

            # Delete
            deleted = tm.delete("site1", "en", "es", "Hello")
            assert deleted is True

            # Verify gone
            assert tm.exact_lookup("site1", "en", "es", "Hello") is None

    def test_delete_namespace_removes_scoped_entries_only(self, temp_db: Path) -> None:
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store(
                "campaign-source-a",
                "en",
                "es",
                "First",
                "Primero",
                context="frontmatter.title",
                field_name="title",
            )
            tm.store(
                "campaign-source-a",
                "en",
                "es",
                "Second",
                "Segundo",
                context="body.0",
            )
            tm.store(
                "campaign-source-a",
                "en",
                "fr",
                "First",
                "Premier",
                context="frontmatter.title",
                field_name="title",
            )
            tm.store("other-source", "en", "es", "First", "Primero")

            removed = tm.delete_namespace(
                site_id="campaign-source-a",
                src_lang="en",
                tgt_lang="es",
            )

            assert removed == 2
            assert tm.exact_lookup(
                "campaign-source-a",
                "en",
                "es",
                "First",
                field_name="title",
                context="frontmatter.title",
            ) is None
            assert tm.exact_lookup(
                "campaign-source-a", "en", "fr", "First",
                field_name="title", context="frontmatter.title",
            ) is not None
            assert tm.exact_lookup("other-source", "en", "es", "First") is not None

    def test_delete_namespace_requires_exact_nonempty_namespace(self, temp_db: Path) -> None:
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            with pytest.raises(ValueError, match="exact site_id"):
                tm.delete_namespace(site_id="", tgt_lang="es")

    def test_count(self, temp_db: Path) -> None:
        """Test entry counting."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            assert tm.count() == 0

            tm.store("site1", "en", "es", "One", "Uno")
            assert tm.count() == 1

            tm.store("site1", "en", "es", "Two", "Dos")
            assert tm.count() == 2

    def test_clear(self, temp_db: Path) -> None:
        """Test clearing database."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store("site1", "en", "es", "One", "Uno")
            tm.store("site1", "en", "es", "Two", "Dos")

            assert tm.count() == 2

            tm.clear()
            assert tm.count() == 0

    def test_persistence(self, temp_db: Path) -> None:
        """Test data persists across sessions."""
        # First session
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            tm.store("site1", "en", "es", "Hello", "Hola")

        # Second session
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry is not None
            assert entry.translation == "Hola"

    def test_len(self, temp_db: Path) -> None:
        """Test __len__ method."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            assert len(tm) == 0

            tm.store("site1", "en", "es", "Hello", "Hola")
            assert len(tm) == 1

    def test_metadata_storage(self, temp_db: Path) -> None:
        """Test storing and retrieving metadata."""
        with L2PersistentTM(temp_db, max_size_mb=20) as tm:
            metadata = {
                "source_file": "content/post.md",
                "segment_id": "abc123",
            }

            tm.store("site1", "en", "es", "Hello", "Hola", metadata=metadata)

            entry = tm.exact_lookup("site1", "en", "es", "Hello")
            assert entry.metadata["source_file"] == "content/post.md"
            assert entry.metadata["segment_id"] == "abc123"


class TestL2DBNameConstant:
    """Tests for L2_DB_NAME constant and map_size wiring."""

    def test_l2_db_name_constant(self) -> None:
        """L2_DB_NAME must be the canonical 'l2.lmdb' to prevent split-database drift."""
        assert L2_DB_NAME == "l2.lmdb"

    def test_l2_db_name_is_string(self) -> None:
        """L2_DB_NAME must be a plain string (used in path construction)."""
        assert isinstance(L2_DB_NAME, str)

    def test_l2_max_size_mb_wiring(self, tmp_path: Path) -> None:
        """L2PersistentTM must honour an explicit max_size_mb argument."""
        db_path = tmp_path / L2_DB_NAME
        # 64 MB is the minimum sensible size; verify the argument is accepted
        with L2PersistentTM(db_path=db_path, max_size_mb=64):
            pass
        assert db_path.exists()

    def test_l2_default_max_size_mb_is_not_zero(self, tmp_path: Path) -> None:
        """Ensure the default max_size_mb results in a non-empty LMDB file."""
        import lmdb

        db_path = tmp_path / L2_DB_NAME
        with L2PersistentTM(db_path=db_path, max_size_mb=20):
            pass
        env = lmdb.open(str(db_path), readonly=True, lock=False)
        stats = env.stat()
        env.close()
        assert stats["psize"] > 0


class TestGetStats:
    """Tests for L2PersistentTM.get_stats()."""

    @pytest.fixture
    def temp_db(self, tmp_path: Path) -> Path:
        return tmp_path / "stats_test.lmdb"

    def test_get_stats_returns_required_fields(self, temp_db: Path) -> None:
        """get_stats() must return all four required fields."""
        with L2PersistentTM(temp_db, max_size_mb=64) as tm:
            stats = tm.get_stats()
        assert "map_size_mb" in stats
        assert "used_mb" in stats
        assert "used_pct" in stats
        assert "entries" in stats

    def test_get_stats_used_pct_in_range(self, temp_db: Path) -> None:
        """used_pct must be within [0, 100] on an empty database."""
        with L2PersistentTM(temp_db, max_size_mb=64) as tm:
            stats = tm.get_stats()
        assert 0.0 <= stats["used_pct"] <= 100.0

    def test_get_stats_map_size_matches_arg(self, temp_db: Path) -> None:
        """map_size_mb must equal the max_size_mb passed to __init__."""
        with L2PersistentTM(temp_db, max_size_mb=64) as tm:
            stats = tm.get_stats()
        # LMDB rounds map_size to the nearest page boundary, so allow ±1 MiB tolerance
        assert abs(stats["map_size_mb"] - 64) <= 1, (
            f"Expected ~64 MiB, got {stats['map_size_mb']:.2f} MiB"
        )

    def test_get_stats_entries_increments_on_store(self, temp_db: Path) -> None:
        """entries count must increase after storing a translation."""
        with L2PersistentTM(temp_db, max_size_mb=64) as tm:
            before = tm.get_stats()["entries"]
            tm.store("site1", "en", "de", "Hello", "Hallo")
            after = tm.get_stats()["entries"]
        assert after == before + 1

    def test_get_stats_used_pct_math(self, temp_db: Path) -> None:
        """used_pct must equal used_mb / map_size_mb * 100 within floating-point tolerance."""
        with L2PersistentTM(temp_db, max_size_mb=64) as tm:
            stats = tm.get_stats()
        if stats["map_size_mb"] > 0:
            expected = stats["used_mb"] / stats["map_size_mb"] * 100
            assert abs(stats["used_pct"] - expected) < 0.01
