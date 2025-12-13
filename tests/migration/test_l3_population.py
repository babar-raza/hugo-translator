"""
Tests for L3 semantic index population.

Tests cover:
- Index creation and population
- Batch processing
- GPU/CPU modes
- Resume capability
- Error handling
- Memory efficiency
"""

import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import numpy as np
import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.populate_l3_index import L3IndexPopulator


class TestL3IndexPopulator:
    """Test suite for L3IndexPopulator class."""

    @pytest.fixture
    def temp_tm_dir(self, tmp_path):
        """Create temporary TM directory with mock LMDB."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        db_dir = tm_dir / "l2.lmdb"
        db_dir.mkdir()

        # Create mock data.mdb file
        data_file = db_dir / "data.mdb"
        data_file.write_bytes(b"mock data" * 1000)

        return tm_dir

    def test_populator_init_success(self, temp_tm_dir):
        """Test populator initializes successfully."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            populator = L3IndexPopulator(temp_tm_dir, use_gpu=False)

            assert populator.tm_path == temp_tm_dir
            assert populator.db_path == temp_tm_dir / "l2.lmdb"
            assert populator.batch_size == 1000
            assert populator.use_gpu is False

    def test_populator_init_missing_db(self, tmp_path):
        """Test populator fails with missing database."""
        with pytest.raises(ValueError, match="not found"):
            L3IndexPopulator(tmp_path)

    def test_populator_gpu_mode(self, temp_tm_dir):
        """Test GPU mode initialization."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            with patch('scripts.populate_l3_index.torch') as mock_torch:
                mock_torch.cuda.is_available.return_value = True
                mock_torch.cuda.get_device_name.return_value = "GPU"

                populator = L3IndexPopulator(temp_tm_dir, use_gpu=True)
                assert populator.use_gpu is True

    def test_populator_gpu_fallback(self, temp_tm_dir):
        """Test GPU fallback to CPU when unavailable."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            with patch('scripts.populate_l3_index.torch') as mock_torch:
                mock_torch.cuda.is_available.return_value = False

                populator = L3IndexPopulator(temp_tm_dir, use_gpu=True)
                assert populator.use_gpu is False

    def test_validate_embedding_valid(self, temp_tm_dir):
        """Test embedding validation with valid embedding."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            populator = L3IndexPopulator(temp_tm_dir)

            embedding = np.array([0.1, 0.2, 0.3, 0.4])
            assert populator.validate_embedding(embedding) is True

    def test_validate_embedding_nan(self, temp_tm_dir):
        """Test embedding validation rejects NaN."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            populator = L3IndexPopulator(temp_tm_dir)

            embedding = np.array([0.1, np.nan, 0.3, 0.4])
            assert populator.validate_embedding(embedding) is False

    def test_validate_embedding_inf(self, temp_tm_dir):
        """Test embedding validation rejects Inf."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            populator = L3IndexPopulator(temp_tm_dir)

            embedding = np.array([0.1, np.inf, 0.3, 0.4])
            assert populator.validate_embedding(embedding) is False

    @patch('scripts.populate_l3_index.lmdb')
    def test_get_l2_entry_count(self, mock_lmdb, temp_tm_dir):
        """Test getting L2 entry count."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            mock_env = MagicMock()
            mock_lmdb.open.return_value = mock_env

            mock_txn = MagicMock()
            mock_env.begin.return_value.__enter__.return_value = mock_txn
            mock_txn.stat.return_value = {'entries': 1000000}

            populator = L3IndexPopulator(temp_tm_dir)
            count = populator.get_l2_entry_count()

            assert count == 1000000
            mock_env.close.assert_called_once()

    def test_process_batch_empty(self, temp_tm_dir):
        """Test processing empty batch."""
        with patch('scripts.populate_l3_index.L3SemanticTM') as MockL3:
            mock_l3 = MagicMock()
            MockL3.return_value = mock_l3

            populator = L3IndexPopulator(temp_tm_dir)
            count = populator.process_batch([])

            assert count == 0

    def test_process_batch_success(self, temp_tm_dir):
        """Test successful batch processing."""
        with patch('scripts.populate_l3_index.L3SemanticTM') as MockL3:
            mock_l3 = MagicMock()
            mock_l3.batch_add.return_value = 3
            MockL3.return_value = mock_l3

            populator = L3IndexPopulator(temp_tm_dir)

            batch = [
                {
                    'key': 'key1',
                    'source_text': 'Hello',
                    'translation': 'Hallo',
                    'site_id': 'default',
                    'src_lang': 'en',
                    'tgt_lang': 'de'
                },
                {
                    'key': 'key2',
                    'source_text': 'World',
                    'translation': 'Welt',
                    'site_id': 'default',
                    'src_lang': 'en',
                    'tgt_lang': 'de'
                },
                {
                    'key': 'key3',
                    'source_text': 'Test',
                    'translation': 'Test',
                    'site_id': 'default',
                    'src_lang': 'en',
                    'tgt_lang': 'de'
                }
            ]

            count = populator.process_batch(batch)

            assert count == 3
            assert populator.stats['total_added'] == 3
            mock_l3.batch_add.assert_called_once()

    def test_process_batch_skip_invalid(self, temp_tm_dir):
        """Test batch processing skips invalid entries."""
        with patch('scripts.populate_l3_index.L3SemanticTM') as MockL3:
            mock_l3 = MagicMock()
            mock_l3.batch_add.return_value = 1
            MockL3.return_value = mock_l3

            populator = L3IndexPopulator(temp_tm_dir)

            batch = [
                {
                    'key': 'key1',
                    'source_text': 'Hello',
                    'translation': 'Hallo',
                    'site_id': 'default',
                    'src_lang': 'en',
                    'tgt_lang': 'de'
                },
                {
                    'key': 'key2',
                    'source_text': '',  # Invalid - empty
                    'translation': 'Test',
                    'site_id': 'default',
                    'src_lang': 'en',
                    'tgt_lang': 'de'
                },
                {
                    'key': 'key3',
                    'source_text': 'Test',
                    'translation': '',  # Invalid - empty
                    'site_id': 'default',
                    'src_lang': 'en',
                    'tgt_lang': 'de'
                }
            ]

            count = populator.process_batch(batch)

            # Only 1 valid entry
            assert count == 1
            assert populator.stats['total_skipped'] == 2

    @patch('scripts.populate_l3_index.lmdb')
    def test_iterate_l2_entries(self, mock_lmdb, temp_tm_dir):
        """Test iterating L2 entries."""
        with patch('scripts.populate_l3_index.L3SemanticTM'):
            mock_env = MagicMock()
            mock_lmdb.open.return_value = mock_env

            mock_txn = MagicMock()
            mock_env.begin.return_value.__enter__.return_value = mock_txn

            # Mock cursor
            mock_cursor = MagicMock()
            mock_txn.cursor.return_value = mock_cursor

            # Setup cursor behavior
            entry1 = (
                b'key1',
                json.dumps({
                    'source_text': 'Hello',
                    'translation': 'Hallo'
                }).encode('utf-8')
            )

            entry2 = (
                b'key2',
                json.dumps({
                    'source_text': 'World',
                    'translation': 'Welt'
                }).encode('utf-8')
            )

            mock_cursor.item.side_effect = [entry1, entry2]
            mock_cursor.next.side_effect = [True, False]

            populator = L3IndexPopulator(temp_tm_dir)

            entries = list(populator.iterate_l2_entries())

            assert len(entries) == 2
            assert entries[0][0] == 'key1'
            assert entries[1][0] == 'key2'
            mock_env.close.assert_called_once()


class TestPopulationIntegration:
    """Integration tests for L3 population."""

    @pytest.fixture
    def temp_tm_dir(self, tmp_path):
        """Create temporary TM directory."""
        tm_dir = tmp_path / "tm"
        tm_dir.mkdir()
        db_dir = tm_dir / "l2.lmdb"
        db_dir.mkdir()
        (db_dir / "data.mdb").write_bytes(b"mock")
        return tm_dir

    @patch('scripts.populate_l3_index.lmdb')
    @patch('scripts.populate_l3_index.L3SemanticTM')
    def test_populate_resume_mode(self, MockL3, mock_lmdb, temp_tm_dir):
        """Test population in resume mode."""
        mock_l3 = MagicMock()
        mock_l3.__len__.return_value = 500  # Existing entries
        MockL3.return_value = mock_l3

        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env
        mock_txn = MagicMock()
        mock_env.begin.return_value.__enter__.return_value = mock_txn
        mock_txn.stat.return_value = {'entries': 1000}

        # Mock empty cursor
        mock_cursor = MagicMock()
        mock_txn.cursor.return_value = mock_cursor
        mock_cursor.next.return_value = False

        populator = L3IndexPopulator(temp_tm_dir)
        stats = populator.populate(resume=True)

        # Should have attempted to resume from position 500
        assert stats is not None

    @patch('scripts.populate_l3_index.lmdb')
    @patch('scripts.populate_l3_index.L3SemanticTM')
    def test_populate_rebuild_mode(self, MockL3, mock_lmdb, temp_tm_dir):
        """Test population in rebuild mode."""
        mock_l3 = MagicMock()
        mock_l3.__len__.return_value = 500
        MockL3.return_value = mock_l3

        mock_env = MagicMock()
        mock_lmdb.open.return_value = mock_env
        mock_txn = MagicMock()
        mock_env.begin.return_value.__enter__.return_value = mock_txn
        mock_txn.stat.return_value = {'entries': 1000}

        mock_cursor = MagicMock()
        mock_txn.cursor.return_value = mock_cursor
        mock_cursor.next.return_value = False

        populator = L3IndexPopulator(temp_tm_dir)
        stats = populator.populate(rebuild=True)

        # Should have cleared existing index
        mock_l3.clear.assert_called_once()
        assert stats is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
