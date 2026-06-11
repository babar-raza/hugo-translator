"""
Comprehensive tests for migration verification functionality.

Tests cover:
- Database integrity checks
- Entry validation (structure and content)
- Migration monitoring
- Statistics collection
- Error handling and edge cases
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

# Import modules to test
from scripts.monitor_migration import MigrationMonitor
from scripts.verify_migration import MigrationVerifier


class TestMigrationMonitor:
    """Test suite for MigrationMonitor class."""

    @pytest.fixture
    def temp_tm_dir(self, tmp_path):
        """Create temporary TM directory with mock LMDB."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        db_dir = tm_dir / "l2.lmdb"
        db_dir.mkdir()

        # Create mock data.mdb file
        data_file = db_dir / "data.mdb"
        data_file.write_bytes(b"mock data" * 1000000)  # ~9MB file

        return tm_dir

    def test_monitor_init_success(self, temp_tm_dir):
        """Test monitor initializes successfully with valid path."""
        monitor = MigrationMonitor(temp_tm_dir)

        assert monitor.tm_path == temp_tm_dir
        assert monitor.db_path == temp_tm_dir / "l2.lmdb"
        assert monitor.expected_entries == 6_097_941

    def test_monitor_init_custom_expected(self, temp_tm_dir):
        """Test monitor with custom expected entries."""
        monitor = MigrationMonitor(temp_tm_dir, expected_entries=1_000_000)

        assert monitor.expected_entries == 1_000_000

    def test_monitor_init_missing_db(self, tmp_path):
        """Test monitor fails with missing database."""
        with pytest.raises(ValueError, match="Database not found"):
            MigrationMonitor(tmp_path)

    def test_calculate_progress_zero_percent(self, temp_tm_dir):
        """Test progress calculation at 0%."""
        monitor = MigrationMonitor(temp_tm_dir, expected_entries=1000)
        progress = monitor.calculate_progress(0)

        assert progress["current"] == 0
        assert progress["expected"] == 1000
        assert progress["percentage"] == 0.0
        assert progress["remaining"] == 1000
        assert progress["is_complete"] is False

    def test_calculate_progress_fifty_percent(self, temp_tm_dir):
        """Test progress calculation at 50%."""
        monitor = MigrationMonitor(temp_tm_dir, expected_entries=1000)
        progress = monitor.calculate_progress(500)

        assert progress["current"] == 500
        assert progress["expected"] == 1000
        assert progress["percentage"] == 50.0
        assert progress["remaining"] == 500
        assert progress["is_complete"] is False

    def test_calculate_progress_complete(self, temp_tm_dir):
        """Test progress calculation at completion (>95%)."""
        monitor = MigrationMonitor(temp_tm_dir, expected_entries=1000)
        progress = monitor.calculate_progress(970)

        assert progress["current"] == 970
        assert progress["percentage"] == 97.0
        assert progress["remaining"] == 30
        assert progress["is_complete"] is True

    def test_calculate_progress_over_100(self, temp_tm_dir):
        """Test progress calculation over 100%."""
        monitor = MigrationMonitor(temp_tm_dir, expected_entries=1000)
        progress = monitor.calculate_progress(1100)

        assert progress["current"] == 1100
        assert progress["percentage"] == 110.0
        assert progress["remaining"] == 0  # No negative remaining
        assert progress["is_complete"] is True

    @patch("scripts.monitor_migration.lmdb")
    def test_get_db_stats_success(self, mock_lmdb, temp_tm_dir):
        """Test successful database statistics retrieval."""
        # Mock LMDB environment
        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env

        # Mock statistics
        mock_env.stat.return_value = {
            "entries": 1000000,
            "psize": 4096,
            "branch_pages": 1000,
            "leaf_pages": 5000,
            "overflow_pages": 100,
        }

        mock_env.info.return_value = {
            "map_size": 10 * 1024 * 1024 * 1024,  # 10GB
            "last_pgno": 6100,
            "last_txnid": 1000000,
            "max_readers": 126,
            "num_readers": 1,
        }

        monitor = MigrationMonitor(temp_tm_dir)
        stats = monitor.get_db_stats()

        assert stats["entries"] == 1000000
        assert stats["page_size"] == 4096
        assert stats["total_pages"] == 6100
        assert stats["map_size"] == 10 * 1024 * 1024 * 1024
        assert "timestamp" in stats
        assert "file_size" in stats

        mock_env.close.assert_called_once()


class TestMigrationVerifier:
    """Test suite for MigrationVerifier class."""

    @pytest.fixture
    def temp_tm_dir(self, tmp_path):
        """Create temporary TM directory with mock LMDB."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        db_dir = tm_dir / "l2.lmdb"
        db_dir.mkdir()

        # Create mock data.mdb file
        data_file = db_dir / "data.mdb"
        data_file.write_bytes(b"mock data" * 1000000)  # ~9MB file

        return tm_dir

    def test_verifier_init_success(self, temp_tm_dir):
        """Test verifier initializes successfully with valid path."""
        verifier = MigrationVerifier(temp_tm_dir)

        assert verifier.tm_path == temp_tm_dir
        assert verifier.db_path == temp_tm_dir / "l2.lmdb"
        assert verifier.expected_entries == 6_097_941
        assert verifier.sample_size == 500

    def test_verifier_init_custom_params(self, temp_tm_dir):
        """Test verifier with custom parameters."""
        verifier = MigrationVerifier(temp_tm_dir, expected_entries=1_000_000, sample_size=100)

        assert verifier.expected_entries == 1_000_000
        assert verifier.sample_size == 100

    def test_verifier_init_missing_db(self, tmp_path):
        """Test verifier fails with missing database."""
        with pytest.raises(ValueError, match="Database not found"):
            MigrationVerifier(tmp_path)

    def test_validate_entry_success(self, temp_tm_dir):
        """Test validation of valid entry."""
        verifier = MigrationVerifier(temp_tm_dir)

        # Create valid entry
        entry_data = {
            "source_text": "Hello world",
            "translation": "Hallo Welt",
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
            "context": None,
            "timestamp": "2024-01-01T00:00:00Z",
            "metadata": {},
        }

        key = b"default:en:de:hello_world"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is True
        assert error_msg is None

    def test_validate_entry_invalid_utf8_key(self, temp_tm_dir):
        """Test validation fails with invalid UTF-8 key."""
        verifier = MigrationVerifier(temp_tm_dir)

        key = b"\xff\xfe invalid utf8"
        value = b'{"source_text": "test"}'

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "not valid UTF-8" in error_msg

    def test_validate_entry_invalid_utf8_value(self, temp_tm_dir):
        """Test validation fails with invalid UTF-8 value."""
        verifier = MigrationVerifier(temp_tm_dir)

        key = b"valid:key"
        value = b"\xff\xfe invalid utf8"

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "not valid UTF-8" in error_msg

    def test_validate_entry_invalid_json(self, temp_tm_dir):
        """Test validation fails with invalid JSON."""
        verifier = MigrationVerifier(temp_tm_dir)

        key = b"valid:key"
        value = b"not valid json {"

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "Invalid JSON" in error_msg

    def test_validate_entry_missing_required_field(self, temp_tm_dir):
        """Test validation fails with missing required field."""
        verifier = MigrationVerifier(temp_tm_dir)

        # Missing 'translation' field
        entry_data = {
            "source_text": "Hello",
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "Missing required field" in error_msg

    def test_validate_entry_empty_source_text(self, temp_tm_dir):
        """Test validation fails with empty source text."""
        verifier = MigrationVerifier(temp_tm_dir)

        entry_data = {
            "source_text": "   ",  # Only whitespace
            "translation": "Test",
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "empty" in error_msg.lower()

    def test_validate_entry_empty_translation(self, temp_tm_dir):
        """Test validation fails with empty translation."""
        verifier = MigrationVerifier(temp_tm_dir)

        entry_data = {
            "source_text": "Test",
            "translation": "",  # Empty
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "empty" in error_msg.lower()

    def test_validate_entry_wrong_type(self, temp_tm_dir):
        """Test validation fails with wrong field type."""
        verifier = MigrationVerifier(temp_tm_dir)

        entry_data = {
            "source_text": 123,  # Should be string
            "translation": "Test",
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "must be string" in error_msg

    def test_validate_entry_invalid_language_codes(self, temp_tm_dir):
        """Test validation fails with invalid language codes."""
        verifier = MigrationVerifier(temp_tm_dir)

        entry_data = {
            "source_text": "Test",
            "translation": "Test",
            "site_id": "default",
            "src_lang": "e",  # Too short
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)

        assert is_valid is False
        assert "language code" in error_msg.lower()

    @patch("scripts.verify_migration.lmdb")
    def test_get_db_info_success(self, mock_lmdb, temp_tm_dir):
        """Test successful database info retrieval."""
        # Mock LMDB environment
        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env

        mock_env.stat.return_value = {
            "entries": 5000000,
            "psize": 4096,
            "branch_pages": 2000,
            "leaf_pages": 10000,
            "overflow_pages": 500,
        }

        mock_env.info.return_value = {
            "map_size": 8 * 1024 * 1024 * 1024,  # 8GB
            "last_txnid": 5000000,
        }

        verifier = MigrationVerifier(temp_tm_dir)
        db_info = verifier.get_db_info()

        assert db_info["entries"] == 5000000
        assert db_info["page_size"] == 4096
        assert db_info["total_pages"] == 12500
        assert db_info["map_size"] == 8 * 1024 * 1024 * 1024
        assert "file_size" in db_info

        mock_env.close.assert_called_once()

    @patch("scripts.verify_migration.lmdb")
    def test_sample_entries_empty_db(self, mock_lmdb, temp_tm_dir):
        """Test sampling from empty database."""
        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env

        mock_txn = MagicMock()
        mock_env.begin.return_value.__enter__.return_value = mock_txn
        mock_txn.stat.return_value = {"entries": 0}

        verifier = MigrationVerifier(temp_tm_dir)
        samples = verifier.sample_entries(100)

        assert len(samples) == 0
        mock_env.close.assert_called_once()

    @patch("scripts.verify_migration.lmdb")
    def test_sample_entries_success(self, mock_lmdb, temp_tm_dir):
        """Test successful entry sampling."""
        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env

        mock_txn = MagicMock()
        mock_env.begin.return_value.__enter__.return_value = mock_txn
        mock_txn.stat.return_value = {"entries": 10}

        # Mock cursor
        mock_cursor = MagicMock()
        mock_txn.cursor.return_value = mock_cursor

        # Simulate cursor iteration
        mock_cursor.first.return_value = True
        mock_cursor.next.return_value = True
        mock_cursor.item.return_value = (b"key1", b"value1")

        verifier = MigrationVerifier(temp_tm_dir)
        samples = verifier.sample_entries(5)

        # Should attempt to sample up to 5 entries
        assert isinstance(samples, list)
        mock_env.close.assert_called_once()

    @patch("scripts.verify_migration.lmdb")
    def test_verify_database_incomplete(self, mock_lmdb, temp_tm_dir):
        """Test verification detects incomplete migration."""
        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env

        # Return low entry count (< 95% of expected)
        mock_env.stat.return_value = {
            "entries": 1000,  # Much less than expected 6M
            "psize": 4096,
            "branch_pages": 100,
            "leaf_pages": 500,
            "overflow_pages": 10,
        }

        mock_env.info.return_value = {
            "map_size": 1024 * 1024 * 1024,
            "last_txnid": 1000,
        }

        # Mock sampling to return no entries
        mock_txn = MagicMock()
        mock_env.begin.return_value.__enter__.return_value = mock_txn
        mock_txn.stat.return_value = {"entries": 0}

        verifier = MigrationVerifier(temp_tm_dir, expected_entries=10000)
        db_info = verifier.verify_database()

        # Should have warning about incomplete migration
        assert len(verifier.warnings) > 0
        assert any("incomplete" in w.lower() for w in verifier.warnings)
        assert verifier.stats["completion_percentage"] < 95.0

    def test_generate_markdown_report(self, temp_tm_dir, tmp_path):
        """Test markdown report generation."""
        verifier = MigrationVerifier(temp_tm_dir)

        # Set up some test statistics
        verifier.stats["total_entries"] = 1000
        verifier.stats["file_size_mb"] = 100
        verifier.stats["completion_percentage"] = 98.5
        verifier.stats["sampled_entries"] = 50
        verifier.stats["valid_entries"] = 50
        verifier.stats["invalid_entries"] = 0
        verifier.stats["validation_rate"] = 100.0

        db_info = {
            "entries": 1000,
            "page_size": 4096,
            "total_pages": 1000,
            "map_size": 1024 * 1024 * 1024,
            "last_txnid": 1000,
        }

        output_path = tmp_path / "report.md"
        verifier.generate_markdown_report(output_path, db_info)

        # Check report was created
        assert output_path.exists()

        # Check report content
        content = output_path.read_text(encoding="utf-8")
        assert "Migration Verification Report" in content
        assert "Total Entries" in content
        assert "1,000" in content
        assert "98.5" in content

    def test_generate_markdown_report_with_errors(self, temp_tm_dir, tmp_path):
        """Test markdown report includes errors."""
        verifier = MigrationVerifier(temp_tm_dir)

        # Add some errors
        verifier.errors = ["Error 1", "Error 2", "Error 3"]
        verifier.warnings = ["Warning 1"]

        verifier.stats["total_entries"] = 1000
        verifier.stats["file_size_mb"] = 100
        verifier.stats["completion_percentage"] = 98.5
        verifier.stats["sampled_entries"] = 50
        verifier.stats["valid_entries"] = 47
        verifier.stats["invalid_entries"] = 3
        verifier.stats["validation_rate"] = 94.0

        db_info = {
            "entries": 1000,
            "page_size": 4096,
            "total_pages": 1000,
            "map_size": 1024 * 1024 * 1024,
            "last_txnid": 1000,
        }

        output_path = tmp_path / "report.md"
        verifier.generate_markdown_report(output_path, db_info)

        content = output_path.read_text(encoding="utf-8")
        assert "## Warnings" in content
        assert "Warning 1" in content
        assert "## Errors" in content
        assert "Error 1" in content


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_monitor_with_zero_expected_entries(self, tmp_path):
        """Test monitor handles zero expected entries."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        (tm_dir / "l2.lmdb").mkdir()
        (tm_dir / "l2.lmdb" / "data.mdb").write_bytes(b"test")

        # Should not raise division by zero
        monitor = MigrationMonitor(tm_dir, expected_entries=1)
        progress = monitor.calculate_progress(0)
        assert progress["percentage"] == 0.0

    def test_verifier_with_special_characters(self, tmp_path):
        """Test verifier handles special characters in entries."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        (tm_dir / "l2.lmdb").mkdir()
        (tm_dir / "l2.lmdb" / "data.mdb").write_bytes(b"test")

        verifier = MigrationVerifier(tm_dir)

        # Entry with special characters
        entry_data = {
            "source_text": "Hello 世界 🌍",
            "translation": "Hallo 世界 🌍",
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data, ensure_ascii=False).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)
        assert is_valid is True

    def test_verifier_with_large_entry(self, tmp_path):
        """Test verifier handles large entries."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        (tm_dir / "l2.lmdb").mkdir()
        (tm_dir / "l2.lmdb" / "data.mdb").write_bytes(b"test")

        verifier = MigrationVerifier(tm_dir)

        # Very large text entry
        entry_data = {
            "source_text": "A" * 10000,
            "translation": "B" * 10000,
            "site_id": "default",
            "src_lang": "en",
            "tgt_lang": "de",
        }

        key = b"test:key"
        value = json.dumps(entry_data).encode("utf-8")

        is_valid, error_msg = verifier.validate_entry(key, value)
        assert is_valid is True


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
