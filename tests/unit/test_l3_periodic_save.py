"""Unit tests for L3 Semantic TM periodic save functionality (RES-04).

Tests cover:
- Periodic save triggering based on save_interval
- Save counter tracking
- Async save mode
- Save statistics reporting
- ThreadPoolExecutor cleanup
- batch_add periodic save integration
"""

import sys
import time
from unittest import mock

import pytest

# Mock heavy dependencies before importing the module
sys.modules['faiss'] = mock.MagicMock()
sys.modules['numpy'] = mock.MagicMock()
sys.modules['sentence_transformers'] = mock.MagicMock()

# Create proper mock for numpy array operations
np_mock = sys.modules['numpy']
np_mock.array = mock.MagicMock(return_value=mock.MagicMock())
np_mock.float32 = 'float32'

# Create mock for SentenceTransformer
st_mock = sys.modules['sentence_transformers']
mock_encoder = mock.MagicMock()
mock_encoder.encode.return_value = mock.MagicMock()
mock_encoder.get_sentence_embedding_dimension.return_value = 384
st_mock.SentenceTransformer.return_value = mock_encoder

# Create mock for faiss
faiss_mock = sys.modules['faiss']
mock_index = mock.MagicMock()
mock_index.ntotal = 0
mock_index.add = mock.MagicMock()
faiss_mock.IndexFlatL2.return_value = mock_index
faiss_mock.write_index = mock.MagicMock()
faiss_mock.read_index = mock.MagicMock(return_value=mock_index)

# Now import the module under test
from src.tm.l3_semantic import L3SemanticTM, SemanticMatch


class TestPeriodicSaveConfiguration:
    """Tests for periodic save configuration."""

    @pytest.fixture
    def index_path(self, tmp_path):
        """Create temporary index path."""
        return tmp_path / "l3_index"

    def test_default_save_interval(self, index_path):
        """Test default save_interval is 100."""
        tm = L3SemanticTM(index_path)
        assert tm.save_interval == 100

    def test_custom_save_interval(self, index_path):
        """Test custom save_interval."""
        tm = L3SemanticTM(index_path, save_interval=50)
        assert tm.save_interval == 50

    def test_disabled_save_interval(self, index_path):
        """Test save_interval=0 disables periodic saves."""
        tm = L3SemanticTM(index_path, save_interval=0)
        assert tm.save_interval == 0

    def test_default_async_save(self, index_path):
        """Test async_save is disabled by default."""
        tm = L3SemanticTM(index_path)
        assert tm.async_save is False
        assert tm._executor is None

    def test_async_save_creates_executor(self, index_path):
        """Test async_save=True creates ThreadPoolExecutor."""
        tm = L3SemanticTM(index_path, async_save=True)
        assert tm.async_save is True
        assert tm._executor is not None
        # Cleanup
        tm._executor.shutdown(wait=False)

    def test_save_timeout_default(self, index_path):
        """Test default save_timeout."""
        tm = L3SemanticTM(index_path)
        assert tm.save_timeout == 5.0

    def test_custom_save_timeout(self, index_path):
        """Test custom save_timeout."""
        tm = L3SemanticTM(index_path, save_timeout=10.0)
        assert tm.save_timeout == 10.0


class TestAdditionCounters:
    """Tests for addition counter tracking."""

    @pytest.fixture
    def tm(self, tmp_path):
        """Create TM instance with low save_interval for testing."""
        return L3SemanticTM(tmp_path / "l3_index", save_interval=5)

    def test_initial_counters(self, tm):
        """Test counters are zero initially."""
        assert tm._additions_since_save == 0
        assert tm._total_additions == 0
        assert tm._save_failures == 0

    def test_add_entry_increments_counters(self, tm):
        """Test add_entry increments counters."""
        tm.add_entry(
            entry_id="e1",
            site_id="site1",
            src_lang="en",
            tgt_lang="ja",
            source_text="Hello",
            translation="こんにちは"
        )
        assert tm._additions_since_save == 1
        assert tm._total_additions == 1

    def test_multiple_adds_increment_counters(self, tm):
        """Test multiple adds accumulate in counters."""
        for i in range(3):
            tm.add_entry(
                entry_id=f"e{i}",
                site_id="site1",
                src_lang="en",
                tgt_lang="ja",
                source_text=f"Text {i}",
                translation=f"Translation {i}"
            )
        assert tm._additions_since_save == 3
        assert tm._total_additions == 3


class TestPeriodicSaveTrigger:
    """Tests for periodic save triggering."""

    @pytest.fixture
    def tm(self, tmp_path):
        """Create TM instance with low save_interval."""
        return L3SemanticTM(tmp_path / "l3_index", save_interval=3)

    def test_save_triggered_at_interval(self, tm):
        """Test save is triggered when reaching save_interval."""
        with mock.patch.object(tm, '_trigger_save') as mock_trigger:
            # Add entries up to interval
            for i in range(3):
                tm.add_entry(
                    entry_id=f"e{i}",
                    site_id="site1",
                    src_lang="en",
                    tgt_lang="ja",
                    source_text=f"Text {i}",
                    translation=f"Translation {i}"
                )
            # Should have triggered save
            mock_trigger.assert_called_once()

    def test_save_not_triggered_before_interval(self, tm):
        """Test save is not triggered before reaching interval."""
        with mock.patch.object(tm, '_trigger_save') as mock_trigger:
            # Add fewer than interval
            for i in range(2):
                tm.add_entry(
                    entry_id=f"e{i}",
                    site_id="site1",
                    src_lang="en",
                    tgt_lang="ja",
                    source_text=f"Text {i}",
                    translation=f"Translation {i}"
                )
            mock_trigger.assert_not_called()

    def test_save_disabled_with_zero_interval(self, tmp_path):
        """Test periodic save disabled when interval is 0."""
        tm = L3SemanticTM(tmp_path / "l3_index", save_interval=0)
        with mock.patch.object(tm, '_trigger_save') as mock_trigger:
            for i in range(10):
                tm.add_entry(
                    entry_id=f"e{i}",
                    site_id="site1",
                    src_lang="en",
                    tgt_lang="ja",
                    source_text=f"Text {i}",
                    translation=f"Translation {i}"
                )
            mock_trigger.assert_not_called()


class TestBatchAddPeriodicSave:
    """Tests for batch_add periodic save integration."""

    @pytest.fixture
    def tm(self, tmp_path):
        """Create TM instance with save_interval."""
        return L3SemanticTM(tmp_path / "l3_index", save_interval=5)

    def test_batch_add_updates_counters(self, tm):
        """Test batch_add updates addition counters."""
        entries = [
            {
                "entry_id": f"e{i}",
                "site_id": "site1",
                "src_lang": "en",
                "tgt_lang": "ja",
                "source_text": f"Text {i}",
                "translation": f"Translation {i}"
            }
            for i in range(3)
        ]
        tm.batch_add(entries)
        assert tm._additions_since_save == 3
        assert tm._total_additions == 3

    def test_batch_add_triggers_save(self, tm):
        """Test batch_add triggers save when exceeding interval."""
        with mock.patch.object(tm, '_trigger_save') as mock_trigger:
            entries = [
                {
                    "entry_id": f"e{i}",
                    "site_id": "site1",
                    "src_lang": "en",
                    "tgt_lang": "ja",
                    "source_text": f"Text {i}",
                    "translation": f"Translation {i}"
                }
                for i in range(6)  # Exceeds interval of 5
            ]
            tm.batch_add(entries)
            mock_trigger.assert_called_once()


class TestSaveStats:
    """Tests for get_save_stats functionality."""

    @pytest.fixture
    def tm(self, tmp_path):
        """Create TM instance."""
        return L3SemanticTM(
            tmp_path / "l3_index",
            save_interval=10,
            async_save=False
        )

    def test_initial_stats(self, tm):
        """Test initial save statistics."""
        stats = tm.get_save_stats()
        assert stats["total_additions"] == 0
        assert stats["additions_since_save"] == 0
        assert stats["save_failures"] == 0
        assert stats["last_save_time"] is None
        assert stats["save_interval"] == 10
        assert stats["async_save"] is False

    def test_stats_after_additions(self, tm):
        """Test stats after adding entries."""
        for i in range(5):
            tm.add_entry(
                entry_id=f"e{i}",
                site_id="site1",
                src_lang="en",
                tgt_lang="ja",
                source_text=f"Text {i}",
                translation=f"Translation {i}"
            )
        stats = tm.get_save_stats()
        assert stats["total_additions"] == 5
        assert stats["additions_since_save"] == 5


class TestDoSave:
    """Tests for _do_save method."""

    @pytest.fixture
    def tm(self, tmp_path):
        """Create TM instance."""
        return L3SemanticTM(tmp_path / "l3_index", save_interval=5)

    def test_do_save_resets_counter(self, tm):
        """Test _do_save resets additions_since_save."""
        tm._additions_since_save = 10
        tm._total_additions = 10

        with mock.patch.object(tm, 'save_index'):
            result = tm._do_save()

        assert result is True
        assert tm._additions_since_save == 0
        assert tm._total_additions == 10  # Total preserved

    def test_do_save_updates_last_save_time(self, tm):
        """Test _do_save updates last_save_time."""
        assert tm._last_save_time is None

        with mock.patch.object(tm, 'save_index'):
            tm._do_save()

        assert tm._last_save_time is not None
        assert tm._last_save_time <= time.time()

    def test_do_save_handles_error(self, tm):
        """Test _do_save handles save errors."""
        tm._additions_since_save = 10

        with mock.patch.object(tm, 'save_index', side_effect=Exception("Save failed")):
            result = tm._do_save()

        assert result is False
        assert tm._save_failures == 1
        assert tm._additions_since_save == 10  # Not reset on failure


class TestTriggerSave:
    """Tests for _trigger_save method."""

    @pytest.fixture
    def tm(self, tmp_path):
        """Create TM instance."""
        return L3SemanticTM(tmp_path / "l3_index", save_interval=5)

    def test_trigger_save_sync(self, tm):
        """Test synchronous save trigger."""
        with mock.patch.object(tm, '_do_save', return_value=True) as mock_do:
            result = tm._trigger_save()
            mock_do.assert_called_once()
            assert result is True

    def test_trigger_save_avoids_concurrent(self, tm):
        """Test concurrent saves are avoided."""
        # Acquire the save lock
        tm._save_lock.acquire()
        try:
            result = tm._trigger_save()
            assert result is False
        finally:
            tm._save_lock.release()


class TestContextManager:
    """Tests for context manager cleanup."""

    def test_exit_saves_index(self, tmp_path):
        """Test __exit__ saves index."""
        tm = L3SemanticTM(tmp_path / "l3_index")
        with mock.patch.object(tm, 'save_index') as mock_save:
            tm.__exit__(None, None, None)
            mock_save.assert_called_once()

    def test_exit_shuts_down_executor(self, tmp_path):
        """Test __exit__ shuts down executor."""
        tm = L3SemanticTM(tmp_path / "l3_index", async_save=True)
        executor = tm._executor
        assert executor is not None

        with mock.patch.object(tm, 'save_index'):
            tm.__exit__(None, None, None)

        assert tm._executor is None

    def test_context_manager_usage(self, tmp_path):
        """Test using TM as context manager."""
        with mock.patch.object(L3SemanticTM, 'save_index'):
            with L3SemanticTM(tmp_path / "l3_index") as tm:
                tm.add_entry(
                    entry_id="e1",
                    site_id="site1",
                    src_lang="en",
                    tgt_lang="ja",
                    source_text="Hello",
                    translation="こんにちは"
                )
            # save_index should be called on exit


class TestSemanticMatchDataclass:
    """Tests for SemanticMatch dataclass."""

    def test_to_dict(self):
        """Test SemanticMatch.to_dict()."""
        match = SemanticMatch(
            entry_id="e1",
            similarity=0.95,
            source_text="Hello",
            translation="こんにちは",
            site_id="site1",
            src_lang="en",
            tgt_lang="ja"
        )
        result = match.to_dict()
        assert result["entry_id"] == "e1"
        assert result["similarity"] == 0.95
        assert result["source_text"] == "Hello"
        assert result["translation"] == "こんにちは"

    def test_optional_fields(self):
        """Test SemanticMatch with optional fields."""
        match = SemanticMatch(
            entry_id="e1",
            similarity=0.9,
            source_text="Test",
            translation="テスト",
            site_id="site1",
            src_lang="en",
            tgt_lang="ja",
            context="Greeting",
            metadata={"source": "manual"}
        )
        result = match.to_dict()
        assert result["context"] == "Greeting"
        assert result["metadata"] == {"source": "manual"}
