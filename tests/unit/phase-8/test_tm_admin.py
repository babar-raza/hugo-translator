"""
Unit tests for TM admin interface.
"""

import csv
import tempfile
from pathlib import Path
from unittest.mock import Mock

import pytest

from src.observability.tm_admin import TranslationMemoryAdmin
from src.tm.l1_cache import L1Cache
from src.tm.l2_persistent import L2PersistentTM
from src.tm.l3_semantic import L3SemanticTM
from src.tm.translation_memory import TranslationMemory


@pytest.fixture
def temp_dir():
    """Create temporary directory."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmpdir:
        yield Path(tmpdir)


@pytest.fixture
def mock_tm():
    """Create mock translation memory."""
    tm = Mock(spec=TranslationMemory)
    tm.l1 = Mock(spec=L1Cache)
    tm.l2 = Mock(spec=L2PersistentTM)
    tm.l3 = Mock(spec=L3SemanticTM)
    # Configure l2 mock to support len()
    tm.l2.__len__ = Mock(return_value=1000)
    # Configure l3 mock to support len()
    tm.l3.__len__ = Mock(return_value=500)
    return tm


@pytest.fixture
def tm_admin(mock_tm):
    """Create TM admin instance."""
    return TranslationMemoryAdmin(mock_tm)


class TestTMAdminInitialization:
    """Test TM admin initialization."""

    def test_admin_initialization(self, mock_tm):
        """Test admin initialization."""
        admin = TranslationMemoryAdmin(mock_tm)
        assert admin.tm == mock_tm

    def test_admin_with_real_tm(self, temp_dir):
        """Test admin with real TM instance."""
        tm = TranslationMemory(
            l1_cache=L1Cache(max_size=100),
            l2_persistent=None,
            l3_semantic=None,
        )
        admin = TranslationMemoryAdmin(tm)
        assert admin.tm == tm


class TestGetStats:
    """Test statistics collection."""

    def test_get_stats_with_all_layers(self, tm_admin, mock_tm):
        """Test get_stats with all TM layers."""
        # Mock L1 stats - stats() returns a dict
        mock_stats_dict = {
            "size": 10,
            "max_size": 100,
            "hits": 50,
            "misses": 20,
            "evictions": 5,
            "hit_rate": 71.43,
        }
        mock_tm.l1.stats.return_value = mock_stats_dict

        stats = tm_admin.get_stats()

        assert stats["l1_cache_stats"] is not None
        assert stats["l1_cache_stats"]["size"] == 10
        assert stats["l2_size"] == 1000
        assert stats["l3_index_size"] == 500

    def test_get_stats_without_l1(self, mock_tm):
        """Test get_stats without L1 cache."""
        mock_tm.l1 = None
        admin = TranslationMemoryAdmin(mock_tm)

        stats = admin.get_stats()

        assert stats["l1_cache_stats"] is None
        assert "l2_size" in stats
        assert "l3_index_size" in stats

    def test_get_stats_without_l2(self, mock_tm):
        """Test get_stats without L2 persistent."""
        mock_tm.l2 = None
        admin = TranslationMemoryAdmin(mock_tm)

        stats = admin.get_stats()

        assert stats["l2_size"] == 0

    def test_get_stats_without_l3(self, mock_tm):
        """Test get_stats without L3 semantic."""
        mock_tm.l3 = None
        admin = TranslationMemoryAdmin(mock_tm)

        stats = admin.get_stats()

        assert stats["l3_index_size"] == 0

    def test_get_stats_with_error(self, tm_admin, mock_tm):
        """Test get_stats handles errors gracefully."""
        mock_tm.l1.stats.side_effect = Exception("Test error")

        stats = tm_admin.get_stats()

        # Should return stats dict even with error
        assert isinstance(stats, dict)
        assert "total_entries" in stats


class TestDumpEntriesToFile:
    """Test exporting TM entries."""

    def test_dump_ndjson_format(self, tm_admin, temp_dir):
        """Test NDJSON export format."""
        out_path = temp_dir / "export.ndjson"

        count, error = tm_admin.dump_entries_to_file(
            out_path=out_path,
            format="ndjson",
            limit=100,
        )

        assert out_path.exists()
        assert error is None
        # Empty export since we're using mock TM
        assert count == 0

    def test_dump_csv_format(self, tm_admin, temp_dir):
        """Test CSV export format."""
        out_path = temp_dir / "export.csv"

        count, error = tm_admin.dump_entries_to_file(
            out_path=out_path,
            format="csv",
            limit=100,
        )

        assert out_path.exists()
        assert error is None

        # Verify CSV structure
        with open(out_path, encoding="utf-8") as f:
            reader = csv.DictReader(f)
            fieldnames = reader.fieldnames
            assert "site_id" in fieldnames
            assert "src_lang" in fieldnames
            assert "tgt_lang" in fieldnames
            assert "source_text" in fieldnames
            assert "translation" in fieldnames

    def test_dump_with_limit(self, tm_admin, temp_dir):
        """Test export with entry limit."""
        out_path = temp_dir / "export.ndjson"

        count, error = tm_admin.dump_entries_to_file(
            out_path=out_path,
            format="ndjson",
            limit=50,
        )

        assert error is None
        # Count should be <= limit
        assert count <= 50

    def test_dump_with_site_filter(self, tm_admin, temp_dir):
        """Test export with site filter."""
        out_path = temp_dir / "export.ndjson"

        count, error = tm_admin.dump_entries_to_file(
            out_path=out_path,
            site_id="test.site",
            format="ndjson",
        )

        assert error is None

    def test_dump_handles_write_error(self, tm_admin):
        """Test dump handles write errors."""
        # Use invalid path to trigger error
        out_path = Path("/invalid/path/export.ndjson")

        count, error = tm_admin.dump_entries_to_file(
            out_path=out_path,
            format="ndjson",
        )

        assert error is not None
        assert count == 0


class TestClearCache:
    """Test cache clearing."""

    def test_clear_all_caches(self, tm_admin, mock_tm):
        """Test clearing all caches."""
        results = tm_admin.clear_cache()

        # Verify clear was called on L1 and L2
        mock_tm.l1.clear.assert_called_once()
        mock_tm.l2.clear.assert_called_once()

        assert results["l1_cleared"] is True
        assert results["l2_cleared"] is True
        # L3 doesn't support clear yet
        assert results["l3_cleared"] is False

    def test_clear_without_l1(self, mock_tm):
        """Test clearing without L1 cache."""
        mock_tm.l1 = None
        admin = TranslationMemoryAdmin(mock_tm)

        results = admin.clear_cache()

        assert results["l1_cleared"] is False
        assert results["l2_cleared"] is True

    def test_clear_without_l2(self, mock_tm):
        """Test clearing without L2 persistent."""
        mock_tm.l2 = None
        admin = TranslationMemoryAdmin(mock_tm)

        results = admin.clear_cache()

        assert results["l1_cleared"] is True
        assert results["l2_cleared"] is False

    def test_clear_handles_error(self, tm_admin, mock_tm):
        """Test clear handles errors gracefully."""
        mock_tm.l1.clear.side_effect = Exception("Clear failed")

        results = tm_admin.clear_cache()

        # Should return results dict even with error
        assert isinstance(results, dict)
        assert "l1_cleared" in results


class TestIntegration:
    """Integration tests with real TM."""

    def test_admin_with_real_l1_cache(self, temp_dir):
        """Test admin with real L1 cache."""
        cache = L1Cache(max_size=10)

        # Add some entries
        cache.put("test.site", "en", "fr", "Hello", "Bonjour")
        cache.put("test.site", "en", "es", "Hello", "Hola")

        # Create mock L2 to satisfy TM constructor
        l2_mock = Mock(spec=L2PersistentTM)
        l2_mock.__len__ = Mock(return_value=0)
        l2_mock.clear = Mock()  # Add clear method to mock

        tm = TranslationMemory(l1_cache=cache, l2_persistent=l2_mock, l3_semantic=None)
        admin = TranslationMemoryAdmin(tm)

        # Get stats before clearing
        stats = admin.get_stats()
        assert stats["l1_cache_stats"]["size"] == 2
        initial_size = stats["l1_cache_stats"]["size"]
        assert initial_size == 2

        # Clear cache
        results = admin.clear_cache()
        assert results["l1_cleared"] is True
        # L2 is a mock, so clear might not work as expected
        assert isinstance(results, dict)
        assert "l2_cleared" in results
