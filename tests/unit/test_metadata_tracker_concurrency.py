"""
Unit tests for MetadataTracker Redis locking (CHH-02).

Tests concurrent metadata updates with Redis coordination.
"""

import json
import threading
import time
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.utils.metadata_tracker import MetadataTracker


class TestMetadataTrackerConcurrency:
    """Test Redis locking for concurrent metadata updates."""

    def test_save_without_redis__direct_write(self, tmp_path):
        """Without Redis client, save() performs direct write."""
        metadata_file = tmp_path / ".translation_metadata.json"
        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="test-site",
            redis_client=None,  # No Redis
        )

        # Create fake data
        tracker._loaded = True
        tracker._data = {}

        # Save should succeed
        tracker.save()

        # Verify file created
        assert metadata_file.exists()
        data = json.loads(metadata_file.read_text())
        assert data["schema_version"] == "1.0"
        assert data["site_id"] == "test-site"

    def test_save_with_redis__uses_lock(self, tmp_path):
        """With Redis client, save() acquires distributed lock."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Mock Redis client
        redis_mock = MagicMock()
        lock_mock = MagicMock()
        redis_mock.lock.return_value = lock_mock

        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="test-site",
            redis_client=redis_mock,
            lock_timeout=30,
        )

        # Create fake data
        tracker._loaded = True
        tracker._data = {}

        # Save
        tracker.save()

        # Verify Redis lock was used
        redis_mock.lock.assert_called_once()
        lock_key, kwargs = redis_mock.lock.call_args
        assert f"metadata_lock:{metadata_file}" in str(lock_key)
        assert kwargs["timeout"] == 30
        assert kwargs["blocking_timeout"] == 30

        # Verify context manager was entered
        lock_mock.__enter__.assert_called_once()
        lock_mock.__exit__.assert_called_once()

    def test_redis_lock_timeout__falls_back_to_direct_write(self, tmp_path):
        """If Redis lock times out, fallback to direct write with warning."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Mock Redis client that raises timeout
        redis_mock = MagicMock()
        lock_mock = MagicMock()
        lock_mock.__enter__.side_effect = Exception("Lock timeout")
        redis_mock.lock.return_value = lock_mock

        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="test-site",
            redis_client=redis_mock,
            lock_timeout=5,
        )

        # Create fake data
        tracker._loaded = True
        tracker._data = {}

        # Save should still succeed (fallback)
        with patch("src.utils.metadata_tracker.logger") as logger_mock:
            tracker.save()

            # Verify warning logged
            assert logger_mock.warning.called
            warning_msg = logger_mock.warning.call_args[0][0]
            assert "Redis lock failed" in warning_msg
            assert "falling back" in warning_msg

        # Verify file still created
        assert metadata_file.exists()

    def test_concurrent_saves_with_redis__no_data_loss(self, tmp_path):
        """Multiple threads saving concurrently don't corrupt data."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Real file lock simulation
        file_lock = threading.Lock()

        def mock_lock_context(key, **kwargs):
            """Mock Redis lock that actually uses threading.Lock."""
            class MockLock:
                def __enter__(self):
                    file_lock.acquire()
                    return self

                def __exit__(self, *args):
                    file_lock.release()

            return MockLock()

        # Mock Redis client
        redis_mock = MagicMock()
        redis_mock.lock.side_effect = mock_lock_context

        # Create trackers for 3 concurrent workers
        trackers = []
        for i in range(3):
            tracker = MetadataTracker(
                metadata_file=metadata_file,
                hash_algorithm="md5",
                site_id=f"worker-{i}",
                redis_client=redis_mock,
            )
            tracker._loaded = True
            tracker._data = {}
            trackers.append(tracker)

        # Concurrent saves
        errors = []

        def save_with_error_capture(tracker):
            try:
                tracker.save()
            except Exception as e:
                errors.append(e)

        threads = [
            threading.Thread(target=save_with_error_capture, args=(tracker,))
            for tracker in trackers
        ]

        for t in threads:
            t.start()

        for t in threads:
            t.join()

        # No errors
        assert len(errors) == 0, f"Concurrent saves failed: {errors}"

        # File should exist and be valid JSON
        assert metadata_file.exists()
        data = json.loads(metadata_file.read_text())
        assert data["schema_version"] == "1.0"

    def test_graceful_degradation__redis_unavailable(self, tmp_path):
        """If Redis unavailable, log warning and continue with direct write."""
        metadata_file = tmp_path / ".translation_metadata.json"

        # Redis client is None (simulating Redis not configured)
        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="test-site",
            redis_client=None,
        )

        tracker._loaded = True
        tracker._data = {}

        # Should succeed without Redis
        with patch("src.utils.metadata_tracker.logger") as logger_mock:
            tracker.save()

            # Should NOT log Redis warning (Redis wasn't expected)
            for call in logger_mock.warning.call_args_list:
                assert "Redis" not in str(call)

        assert metadata_file.exists()

    def test_lock_key_includes_file_path(self, tmp_path):
        """Redis lock key includes metadata file path for isolation."""
        metadata_file = tmp_path / "site1" / ".translation_metadata.json"
        metadata_file.parent.mkdir(parents=True)

        redis_mock = MagicMock()
        lock_mock = MagicMock()
        redis_mock.lock.return_value = lock_mock

        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="site1",
            redis_client=redis_mock,
        )

        tracker._loaded = True
        tracker._data = {}
        tracker.save()

        # Verify lock key contains file path
        lock_key = redis_mock.lock.call_args[0][0]
        assert "metadata_lock:" in lock_key
        assert str(metadata_file) in lock_key

    def test_custom_lock_timeout_respected(self, tmp_path):
        """Custom lock_timeout parameter is passed to Redis lock."""
        metadata_file = tmp_path / ".translation_metadata.json"

        redis_mock = MagicMock()
        lock_mock = MagicMock()
        redis_mock.lock.return_value = lock_mock

        # Custom timeout
        custom_timeout = 60

        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="test-site",
            redis_client=redis_mock,
            lock_timeout=custom_timeout,
        )

        tracker._loaded = True
        tracker._data = {}
        tracker.save()

        # Verify custom timeout used
        kwargs = redis_mock.lock.call_args[1]
        assert kwargs["timeout"] == custom_timeout
        assert kwargs["blocking_timeout"] == custom_timeout

    def test_debug_logging_on_lock_acquire_release(self, tmp_path):
        """Debug logs emitted when acquiring and releasing lock."""
        metadata_file = tmp_path / ".translation_metadata.json"

        redis_mock = MagicMock()
        lock_mock = MagicMock()
        redis_mock.lock.return_value = lock_mock

        tracker = MetadataTracker(
            metadata_file=metadata_file,
            hash_algorithm="md5",
            site_id="test-site",
            redis_client=redis_mock,
        )

        tracker._loaded = True
        tracker._data = {}

        with patch("src.utils.metadata_tracker.logger") as logger_mock:
            tracker.save()

            # Check debug logs
            debug_calls = [str(call) for call in logger_mock.debug.call_args_list]
            assert any("Acquired Redis lock" in call for call in debug_calls)
            assert any("Released Redis lock" in call for call in debug_calls)
