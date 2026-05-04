"""
Unit tests for cache integrity safeguards (T204: federated-splashing-panda).

Tests validation, error handling, and corruption detection in L2PersistentTM.
"""
import json
import tempfile
import threading
from unittest.mock import patch

import pytest

from src.tm.l2_persistent import L2PersistentTM, TranslationEntry


class TestTranslationEntryValidation:
    """Test TranslationEntry validation."""

    def test_valid_entry_passes_validation(self):
        """Test that a valid entry passes validation."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="test",
            src_lang="en",
            tgt_lang="de",
        )

        assert entry.is_valid() is True

    def test_empty_source_text_fails_validation(self):
        """Test that empty source_text fails validation."""
        entry = TranslationEntry(
            source_text="",
            translation="Hallo",
            site_id="test",
            src_lang="en",
            tgt_lang="de",
        )

        assert entry.is_valid() is False

    def test_empty_translation_fails_validation(self):
        """Test that empty translation fails validation."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="",
            site_id="test",
            src_lang="en",
            tgt_lang="de",
        )

        assert entry.is_valid() is False

    def test_empty_site_id_fails_validation(self):
        """Test that empty site_id fails validation."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="",
            src_lang="en",
            tgt_lang="de",
        )

        assert entry.is_valid() is False

    def test_invalid_context_type_fails_validation(self):
        """Test that invalid context type fails validation."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="test",
            src_lang="en",
            tgt_lang="de",
            context=123,  # Invalid: should be string
        )

        assert entry.is_valid() is False

    def test_invalid_metadata_type_fails_validation(self):
        """Test that invalid metadata type fails validation."""
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="test",
            src_lang="en",
            tgt_lang="de",
            metadata="invalid",  # Invalid: should be dict
        )

        assert entry.is_valid() is False


class TestAtomicWrites:
    """Test atomic write operations."""

    def test_atomic_write_succeeds(self):
        """Test that atomic write succeeds with valid entry."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Store valid entry
            result = tm.store(
                site_id="test",
                src_lang="en",
                tgt_lang="de",
                text="Hello",
                translation="Hallo",
            )

            assert result is True

            # Verify stored
            entry = tm.exact_lookup(
                site_id="test",
                src_lang="en",
                tgt_lang="de",
                text="Hello",
            )

            assert entry is not None
            assert entry.translation == "Hallo"

            tm.close()

    def test_invalid_entry_rejected(self):
        """Test that invalid entry is rejected before write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Attempt to store invalid entry (empty translation)
            with pytest.raises(ValueError, match="failed validation"):
                tm.store(
                    site_id="test",
                    src_lang="en",
                    tgt_lang="de",
                    text="Hello",
                    translation="",  # Invalid: empty translation
                )

            # Verify nothing was stored
            entry = tm.exact_lookup(
                site_id="test",
                src_lang="en",
                tgt_lang="de",
                text="Hello",
            )

            assert entry is None

            tm.close()


class TestCorruptionDetection:
    """Test corruption detection on read."""

    def test_corrupted_json_detected_on_read(self):
        """Test that corrupted JSON is detected and skipped on read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Manually insert corrupted data
            from src.tm.normalization import make_tm_key
            key = make_tm_key("test", "en", "de", "Hello")
            key_bytes = key.encode("utf-8")

            with tm._lock:
                with tm.env.begin(write=True) as txn:
                    # Write invalid JSON
                    txn.put(key_bytes, b"invalid json data")

            # Attempt to lookup should return None (corrupted entry skipped)
            entry = tm.exact_lookup(
                site_id="test",
                src_lang="en",
                tgt_lang="de",
                text="Hello",
            )

            assert entry is None

            tm.close()

    def test_invalid_entry_detected_on_read(self):
        """Test that invalid entry (failed validation) is detected on read."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Manually insert entry with missing required fields
            from src.tm.normalization import make_tm_key
            key = make_tm_key("test", "en", "de", "Hello")
            key_bytes = key.encode("utf-8")

            invalid_entry = {
                "source_text": "Hello",
                "translation": "",  # Invalid: empty translation
                "site_id": "test",
                "src_lang": "en",
                "tgt_lang": "de",
                "context": None,
                "metadata": {},
                "timestamp": "2025-01-01T00:00:00+00:00",
            }

            with tm._lock:
                with tm.env.begin(write=True) as txn:
                    txn.put(key_bytes, json.dumps(invalid_entry).encode("utf-8"))

            # Attempt to lookup should return None (invalid entry skipped)
            entry = tm.exact_lookup(
                site_id="test",
                src_lang="en",
                tgt_lang="de",
                text="Hello",
            )

            assert entry is None

            tm.close()


class TestConcurrentWrites:
    """Test concurrent write safety."""

    def test_concurrent_writes_safe(self):
        """Test that concurrent writes from multiple threads are safe."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Number of concurrent threads
            num_threads = 5
            entries_per_thread = 10

            def write_entries(thread_id):
                """Write entries from a thread."""
                for i in range(entries_per_thread):
                    tm.store(
                        site_id="test",
                        src_lang="en",
                        tgt_lang="de",
                        text=f"Thread{thread_id}_Entry{i}",
                        translation=f"Translation{thread_id}_{i}",
                    )

            # Create and start threads
            threads = []
            for i in range(num_threads):
                thread = threading.Thread(target=write_entries, args=(i,))
                threads.append(thread)
                thread.start()

            # Wait for all threads to complete
            for thread in threads:
                thread.join()

            # Verify all entries were stored
            expected_count = num_threads * entries_per_thread
            actual_count = tm.count()

            assert actual_count == expected_count

            # Verify data integrity by reading some entries
            for i in range(num_threads):
                entry = tm.exact_lookup(
                    site_id="test",
                    src_lang="en",
                    tgt_lang="de",
                    text=f"Thread{i}_Entry0",
                )
                assert entry is not None
                assert entry.translation == f"Translation{i}_0"

            tm.close()


class TestBatchIntegrity:
    """Test batch store integrity safeguards."""

    def test_batch_store_validates_all_entries(self):
        """Test that batch_store validates all entries before write."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Create batch with one invalid entry
            entries = [
                TranslationEntry(
                    source_text="Hello1",
                    translation="Hallo1",
                    site_id="test",
                    src_lang="en",
                    tgt_lang="de",
                ),
                TranslationEntry(
                    source_text="Hello2",
                    translation="",  # Invalid: empty translation
                    site_id="test",
                    src_lang="en",
                    tgt_lang="de",
                ),
                TranslationEntry(
                    source_text="Hello3",
                    translation="Hallo3",
                    site_id="test",
                    src_lang="en",
                    tgt_lang="de",
                ),
            ]

            # Batch store should fail due to invalid entry
            with pytest.raises(ValueError, match="failed validation"):
                tm.batch_store(entries)

            # Verify nothing was stored (atomic rollback)
            count = tm.count()
            assert count == 0

            tm.close()

    def test_batch_store_succeeds_with_valid_entries(self):
        """Test that batch_store succeeds with all valid entries."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Create batch with all valid entries
            entries = [
                TranslationEntry(
                    source_text=f"Hello{i}",
                    translation=f"Hallo{i}",
                    site_id="test",
                    src_lang="en",
                    tgt_lang="de",
                )
                for i in range(10)
            ]

            # Batch store should succeed
            count = tm.batch_store(entries)

            assert count == 10

            # Verify all entries stored
            assert tm.count() == 10

            # Verify one entry
            entry = tm.exact_lookup(
                site_id="test",
                src_lang="en",
                tgt_lang="de",
                text="Hello0",
            )

            assert entry is not None
            assert entry.translation == "Hallo0"

            tm.close()


class TestErrorHandling:
    """Test error handling and rollback."""

    def test_serialization_error_raises_runtime_error(self):
        """Test that JSON serialization error raises RuntimeError."""
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L2PersistentTM(db_path=tmpdir, max_size_mb=20)

            # Create entry with unserializable metadata
            with pytest.raises(RuntimeError, match="Failed to serialize"):
                # Patch json.dumps to raise TypeError
                with patch('src.tm.l2_persistent.json.dumps', side_effect=TypeError("Cannot serialize")):
                    tm.store(
                        site_id="test",
                        src_lang="en",
                        tgt_lang="de",
                        text="Hello",
                        translation="Hallo",
                    )

            # Verify nothing was stored (automatic rollback)
            count = tm.count()
            assert count == 0

            tm.close()
