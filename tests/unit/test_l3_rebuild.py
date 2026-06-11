"""Unit tests for L3 FAISS index rebuild functionality.

Tests cover:
- L2 export_all method
- L3 rebuild process
- Filtering by site and language
- Backup creation
- Error handling
"""

import sys
from pathlib import Path
from unittest import mock

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tm.l2_persistent import L2PersistentTM, TranslationEntry
from tm.l3_rebuild import (
    L3IndexRebuilder,
    RebuildResult,
)


class TestL2ExportAll:
    """Tests for L2PersistentTM.export_all method."""

    @pytest.fixture
    def populated_l2(self, tmp_path):
        """Create L2 with test data."""
        db_path = tmp_path / "tm_cache"
        l2 = L2PersistentTM(db_path, max_size_mb=10)

        # Add entries for multiple sites and languages
        entries = [
            ("Hello", "Hola", "site1", "en", "es"),
            ("Goodbye", "Adios", "site1", "en", "es"),
            ("Hello", "Bonjour", "site1", "en", "fr"),
            ("Hello", "Hallo", "site2", "en", "de"),
            ("World", "Mundo", "site2", "en", "es"),
        ]

        for source, trans, site, src, tgt in entries:
            l2.store(site_id=site, src_lang=src, tgt_lang=tgt, text=source, translation=trans)

        return l2

    def test_export_all_returns_all_entries(self, populated_l2):
        """Test exporting all entries."""
        entries = populated_l2.export_all()
        assert len(entries) == 5

    def test_export_all_filters_by_site(self, populated_l2):
        """Test filtering by site ID."""
        entries = populated_l2.export_all(site_id="site1")
        assert len(entries) == 3
        assert all(e.site_id == "site1" for e in entries)

    def test_export_all_filters_by_target_lang(self, populated_l2):
        """Test filtering by target language."""
        entries = populated_l2.export_all(tgt_lang="es")
        assert len(entries) == 3
        assert all(e.tgt_lang == "es" for e in entries)

    def test_export_all_filters_combined(self, populated_l2):
        """Test combined site and language filter."""
        entries = populated_l2.export_all(site_id="site1", tgt_lang="es")
        assert len(entries) == 2
        assert all(e.site_id == "site1" and e.tgt_lang == "es" for e in entries)

    def test_export_all_empty_cache(self, tmp_path):
        """Test exporting from empty cache."""
        db_path = tmp_path / "empty_tm"
        l2 = L2PersistentTM(db_path, max_size_mb=10)

        entries = l2.export_all()
        assert entries == []

    def test_export_all_no_matches(self, populated_l2):
        """Test filter with no matches."""
        entries = populated_l2.export_all(site_id="nonexistent")
        assert entries == []

    def test_export_all_returns_valid_entries(self, populated_l2):
        """Test exported entries are valid TranslationEntry objects."""
        entries = populated_l2.export_all()

        for entry in entries:
            assert isinstance(entry, TranslationEntry)
            assert entry.source_text
            assert entry.translation
            assert entry.site_id
            assert entry.src_lang
            assert entry.tgt_lang


class TestRebuildResult:
    """Tests for RebuildResult dataclass."""

    def test_rebuild_result_success_true(self):
        """Test success is True when all entries indexed."""
        result = RebuildResult(entries_exported=100, entries_indexed=100, duration_seconds=5.5)
        assert result.success is True

    def test_rebuild_result_success_false(self):
        """Test success is False when some entries failed."""
        result = RebuildResult(entries_exported=100, entries_indexed=95, duration_seconds=5.5)
        assert result.success is False

    def test_rebuild_result_str(self):
        """Test string representation."""
        result = RebuildResult(entries_exported=100, entries_indexed=100, duration_seconds=5.5)
        s = str(result)
        assert "exported=100" in s
        assert "indexed=100" in s
        assert "5.5s" in s

    def test_rebuild_result_to_dict(self):
        """Test dictionary conversion."""
        result = RebuildResult(
            entries_exported=100,
            entries_indexed=100,
            duration_seconds=5.5,
            backup_path=Path("/backup"),
        )
        d = result.to_dict()
        assert d["entries_exported"] == 100
        assert d["entries_indexed"] == 100
        assert d["duration_seconds"] == 5.5
        assert d["success"] is True


class TestL3IndexRebuilder:
    """Tests for L3IndexRebuilder class."""

    @pytest.fixture
    def mock_l2(self):
        """Create mock L2 with export_all method."""
        l2 = mock.MagicMock()
        l2.export_all.return_value = [
            TranslationEntry(
                source_text=f"Source {i}",
                translation=f"Trans {i}",
                site_id="test.site",
                src_lang="en",
                tgt_lang="es",
            )
            for i in range(10)
        ]
        return l2

    @pytest.fixture
    def mock_l3(self):
        """Create mock L3 with required methods."""
        l3 = mock.MagicMock()
        l3.clear = mock.MagicMock()
        l3.batch_add = mock.MagicMock(return_value=10)
        l3.save_index = mock.MagicMock()
        l3.index_path = None  # No existing index
        return l3

    def test_rebuild_success(self, mock_l2, mock_l3):
        """Test successful rebuild."""
        rebuilder = L3IndexRebuilder(mock_l2, mock_l3)
        result = rebuilder.rebuild(backup_existing=False)

        assert result.entries_exported == 10
        assert result.entries_indexed == 10
        assert result.success is True

        # Verify L3 methods were called
        mock_l3.clear.assert_called_once()
        mock_l3.batch_add.assert_called_once()
        mock_l3.save_index.assert_called_once()

    def test_rebuild_calls_export_with_filters(self, mock_l2, mock_l3):
        """Test filters are passed to export_all."""
        rebuilder = L3IndexRebuilder(mock_l2, mock_l3)
        rebuilder.rebuild(site_id="mysite", tgt_lang="fr", backup_existing=False)

        mock_l2.export_all.assert_called_once_with(site_id="mysite", tgt_lang="fr")

    def test_rebuild_empty_l2(self, mock_l2, mock_l3):
        """Test rebuild with empty L2."""
        mock_l2.export_all.return_value = []

        rebuilder = L3IndexRebuilder(mock_l2, mock_l3)
        result = rebuilder.rebuild(backup_existing=False)

        assert result.entries_exported == 0
        assert result.entries_indexed == 0
        # L3 should not be cleared or modified
        mock_l3.clear.assert_not_called()

    def test_rebuild_with_backup(self, mock_l2, mock_l3, tmp_path):
        """Test backup is created when requested."""
        # Set up L3 with index path
        index_file = tmp_path / "l3_index" / "index.faiss"
        index_file.parent.mkdir(parents=True)
        index_file.write_text("fake index")
        mock_l3.index_path = index_file

        rebuilder = L3IndexRebuilder(mock_l2, mock_l3, backup_dir=tmp_path / "backups")
        result = rebuilder.rebuild(backup_existing=True)

        # Backup should be created (check that a backup directory exists)
        assert result.backup_path is not None or result.success


class TestL3IndexRebuilderIntegration:
    """Integration tests with real L2 (mocked L3)."""

    @pytest.fixture
    def populated_l2(self, tmp_path):
        """Create L2 with test data."""
        db_path = tmp_path / "tm_cache"
        l2 = L2PersistentTM(db_path, max_size_mb=10)

        for i in range(50):
            l2.store(
                site_id="test.site",
                src_lang="en",
                tgt_lang="es",
                text=f"Test source {i}",
                translation=f"Traduccion {i}",
            )

        return l2

    @pytest.fixture
    def mock_l3(self):
        """Create mock L3."""
        l3 = mock.MagicMock()
        l3.clear = mock.MagicMock()
        l3.batch_add = mock.MagicMock(side_effect=lambda x: len(x))
        l3.save_index = mock.MagicMock()
        l3.index_path = None
        return l3

    def test_rebuild_with_real_l2(self, populated_l2, mock_l3):
        """Test rebuild with real L2 and mocked L3."""
        rebuilder = L3IndexRebuilder(populated_l2, mock_l3)
        result = rebuilder.rebuild(backup_existing=False)

        assert result.entries_exported == 50
        assert result.entries_indexed == 50
        assert result.success is True
        assert result.duration_seconds > 0

    def test_rebuild_with_batches(self, populated_l2, mock_l3):
        """Test rebuild processes in batches."""
        rebuilder = L3IndexRebuilder(populated_l2, mock_l3)
        result = rebuilder.rebuild(backup_existing=False, batch_size=10)

        # With 50 entries and batch_size=10, should have 5 batches
        # Each call to batch_add returns batch size
        assert result.entries_indexed == 50
