"""
CONTRACT: specs/features/tm-002-l2-persistent-store.md

Verifies L2 Persistent Translation Memory behavior including:
- Exact key matching via make_tm_key()
- Corruption detection on lookup (JSON deserialization, is_valid())
- Validation before write (ValueError on invalid entry)
- Atomic writes via LMDB transactions
- Thread-safe operations via RLock
- Context filtering on lookup

TM-002 Feature: L2 Persistent Translation Memory (LMDB-backed)

Key Guarantees:
1. Exact key matching - Key constructed with make_tm_key(site_id, src_lang, tgt_lang, text)
2. Corruption detection - JSON errors and invalid entries return None on lookup
3. Validation before write - Invalid entries raise ValueError
4. Atomic writes - LMDB transaction provides rollback on failure
5. Thread-safe - RLock acquired before LMDB operations
6. Context filtering - Lookup filters by context when specified
"""

import json
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from src.tm.l2_persistent import L2PersistentTM, TranslationEntry
from src.tm.normalization import make_tm_key

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def l2_tm(tmp_path):
    """
    Fresh L2PersistentTM instance with temporary LMDB database.

    Evidence: src/tm/l2_persistent.py L2PersistentTM.__init__() lines 89-112
    """
    tm = L2PersistentTM(db_path=tmp_path / "l2_lmdb", max_size_mb=10)
    yield tm
    tm.close()


@pytest.fixture
def small_l2_tm(tmp_path):
    """
    L2PersistentTM with small max_size for edge case testing.

    Evidence: src/tm/l2_persistent.py L2PersistentTM.__init__()
    """
    tm = L2PersistentTM(db_path=tmp_path / "small_l2_lmdb", max_size_mb=1)
    yield tm
    tm.close()


@pytest.fixture
def sample_entry_params():
    """Standard translation entry parameters for tests."""
    return {
        "site_id": "test.example.com",
        "src_lang": "en",
        "tgt_lang": "de",
        "text": "Hello world",
        "translation": "Hallo Welt",
    }


@pytest.fixture
def sample_entry():
    """Standard TranslationEntry for tests."""
    return TranslationEntry(
        source_text="Hello world",
        translation="Hallo Welt",
        site_id="test.example.com",
        src_lang="en",
        tgt_lang="de",
    )


# ==============================================================================
# TM-002 Invariant 1: Exact Key Matching Tests
# ==============================================================================


@pytest.mark.contract
class TestExactKeyMatching:
    """CONTRACT: TM-002 Invariant 1 - Exact key matching via make_tm_key()"""

    def test_exact_key_matching_returns_stored_entry(self, l2_tm, sample_entry_params):
        """
        INV: Exact key matching must use make_tm_key for lookups.

        Evidence: src/tm/l2_persistent.py lines 135, 222
        """
        # Arrange - store an entry
        l2_tm.store(**sample_entry_params)

        # Act - lookup with exact same parameters
        result = l2_tm.exact_lookup(
            site_id=sample_entry_params["site_id"],
            src_lang=sample_entry_params["src_lang"],
            tgt_lang=sample_entry_params["tgt_lang"],
            text=sample_entry_params["text"],
        )

        # Assert - entry found with correct translation
        assert result is not None
        assert result.translation == sample_entry_params["translation"]
        assert result.source_text == sample_entry_params["text"]

    def test_different_sites_have_separate_entries(self, l2_tm):
        """
        INV: Same text with different site_id creates separate entries.

        Evidence: src/tm/l2_persistent.py make_tm_key includes site_id
        """
        # Arrange - same text, different sites
        text = "Hello"
        l2_tm.store("site1.com", "en", "de", text, "Site1 Translation")
        l2_tm.store("site2.com", "en", "de", text, "Site2 Translation")

        # Act
        result_site1 = l2_tm.exact_lookup("site1.com", "en", "de", text)
        result_site2 = l2_tm.exact_lookup("site2.com", "en", "de", text)

        # Assert - different sites have different translations
        assert result_site1.translation == "Site1 Translation"
        assert result_site2.translation == "Site2 Translation"

    def test_different_languages_have_separate_entries(self, l2_tm):
        """
        INV: Same text with different language pairs creates separate entries.

        Evidence: src/tm/l2_persistent.py make_tm_key includes src_lang, tgt_lang
        """
        # Arrange - same text, different target languages
        text = "Hello"
        l2_tm.store("site.com", "en", "de", text, "Hallo")
        l2_tm.store("site.com", "en", "fr", text, "Bonjour")

        # Act
        result_de = l2_tm.exact_lookup("site.com", "en", "de", text)
        result_fr = l2_tm.exact_lookup("site.com", "en", "fr", text)

        # Assert - different language pairs have different translations
        assert result_de.translation == "Hallo"
        assert result_fr.translation == "Bonjour"

    def test_lookup_miss_returns_none(self, l2_tm):
        """
        INV: Lookup for non-existent key returns None.

        Evidence: src/tm/l2_persistent.py lines 141-142
        """
        # Act - lookup non-existent entry
        result = l2_tm.exact_lookup("nonexistent.com", "en", "de", "Unknown text")

        # Assert - miss returns None
        assert result is None


# ==============================================================================
# TM-002 Invariant 2: Corruption Detection on Lookup Tests
# ==============================================================================


@pytest.mark.contract
class TestCorruptionDetection:
    """CONTRACT: TM-002 Invariant 2 - Corruption detection on lookup"""

    def test_corrupted_json_returns_none(self, l2_tm, sample_entry_params):
        """
        INV: MUST catch JSON deserialization errors and return None.

        Evidence: src/tm/l2_persistent.py lines 144-155
        """
        # Arrange - store valid entry, then corrupt it directly
        l2_tm.store(**sample_entry_params)
        key = make_tm_key(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Corrupt the stored data by writing invalid JSON
        with l2_tm._lock:
            with l2_tm.env.begin(write=True) as txn:
                txn.put(key.encode("utf-8"), b"not valid json {{{")

        # Act - lookup corrupted entry
        result = l2_tm.exact_lookup(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Assert - returns None instead of raising
        assert result is None

    def test_invalid_entry_fields_returns_none(self, l2_tm, sample_entry_params):
        """
        INV: MUST validate entry with is_valid() and return None for invalid.

        Evidence: src/tm/l2_persistent.py lines 157-164
        """
        # Arrange - store entry, then corrupt it with invalid field (empty source_text)
        l2_tm.store(**sample_entry_params)
        key = make_tm_key(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Write entry with empty source_text (fails is_valid)
        invalid_entry_dict = {
            "source_text": "",  # Invalid - empty string
            "translation": "Hallo Welt",
            "site_id": "test.example.com",
            "src_lang": "en",
            "tgt_lang": "de",
            "context": None,
            "timestamp": "2025-01-01T00:00:00",
            "metadata": {},
        }
        with l2_tm._lock:
            with l2_tm.env.begin(write=True) as txn:
                txn.put(key.encode("utf-8"), json.dumps(invalid_entry_dict).encode("utf-8"))

        # Act - lookup invalid entry
        result = l2_tm.exact_lookup(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Assert - returns None for invalid entry
        assert result is None

    def test_missing_required_fields_returns_none(self, l2_tm, sample_entry_params):
        """
        INV: MUST handle KeyError when deserializing entry with missing fields.

        Evidence: src/tm/l2_persistent.py lines 148 (KeyError catch)
        """
        # Arrange - store entry with missing required field
        l2_tm.store(**sample_entry_params)
        key = make_tm_key(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Write entry missing 'translation' field
        incomplete_entry_dict = {
            "source_text": "Hello world",
            # "translation" is missing
            "site_id": "test.example.com",
            "src_lang": "en",
            "tgt_lang": "de",
        }
        with l2_tm._lock:
            with l2_tm.env.begin(write=True) as txn:
                txn.put(key.encode("utf-8"), json.dumps(incomplete_entry_dict).encode("utf-8"))

        # Act - lookup entry with missing field
        result = l2_tm.exact_lookup(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Assert - returns None (KeyError caught)
        assert result is None

    def test_corruption_logs_warning(self, l2_tm, sample_entry_params, caplog):
        """
        INV: Corruption detection MUST log warning message.

        Evidence: src/tm/l2_persistent.py lines 150-154
        """
        import logging

        caplog.set_level(logging.WARNING)

        # Arrange - corrupt an entry
        l2_tm.store(**sample_entry_params)
        key = make_tm_key(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )
        with l2_tm._lock:
            with l2_tm.env.begin(write=True) as txn:
                txn.put(key.encode("utf-8"), b"not valid json")

        # Act
        l2_tm.exact_lookup(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Assert - warning was logged
        assert "Corrupted cache entry detected" in caplog.text


# ==============================================================================
# TM-002 Invariant 3: Validation Before Write Tests
# ==============================================================================


@pytest.mark.contract
class TestValidationBeforeWrite:
    """CONTRACT: TM-002 Invariant 3 - Validation before write"""

    def test_empty_source_text_raises_valueerror(self, l2_tm):
        """
        INV: MUST validate entry with is_valid() before storing.

        Evidence: src/tm/l2_persistent.py lines 214-220
        """
        # Act & Assert - empty source text raises ValueError
        with pytest.raises(ValueError, match="Translation entry failed validation"):
            l2_tm.store(
                site_id="site.com",
                src_lang="en",
                tgt_lang="de",
                text="",  # Empty - invalid
                translation="Some translation",
            )

    def test_empty_translation_raises_valueerror(self, l2_tm):
        """
        INV: MUST reject entry with empty translation.

        Evidence: src/tm/l2_persistent.py lines 61-62 (is_valid check)
        """
        # Act & Assert - empty translation raises ValueError
        with pytest.raises(ValueError, match="Translation entry failed validation"):
            l2_tm.store(
                site_id="site.com",
                src_lang="en",
                tgt_lang="de",
                text="Hello",
                translation="",  # Empty - invalid
            )

    def test_empty_site_id_raises_valueerror(self, l2_tm):
        """
        INV: MUST reject entry with empty site_id.

        Evidence: src/tm/l2_persistent.py lines 63-64 (is_valid check)
        """
        # Act & Assert
        with pytest.raises(ValueError, match="Translation entry failed validation"):
            l2_tm.store(
                site_id="",  # Empty - invalid
                src_lang="en",
                tgt_lang="de",
                text="Hello",
                translation="Hallo",
            )

    def test_empty_src_lang_raises_valueerror(self, l2_tm):
        """
        INV: MUST reject entry with empty src_lang.

        Evidence: src/tm/l2_persistent.py lines 65-66 (is_valid check)
        """
        # Act & Assert
        with pytest.raises(ValueError, match="Translation entry failed validation"):
            l2_tm.store(
                site_id="site.com",
                src_lang="",  # Empty - invalid
                tgt_lang="de",
                text="Hello",
                translation="Hallo",
            )

    def test_empty_tgt_lang_raises_valueerror(self, l2_tm):
        """
        INV: MUST reject entry with empty tgt_lang.

        Evidence: src/tm/l2_persistent.py lines 67-68 (is_valid check)
        """
        # Act & Assert
        with pytest.raises(ValueError, match="Translation entry failed validation"):
            l2_tm.store(
                site_id="site.com",
                src_lang="en",
                tgt_lang="",  # Empty - invalid
                text="Hello",
                translation="Hallo",
            )

    def test_validation_failure_logs_error(self, l2_tm, caplog):
        """
        INV: Validation failure MUST log error message.

        Evidence: src/tm/l2_persistent.py lines 216-219
        """
        import logging

        caplog.set_level(logging.ERROR)

        # Act - attempt to store invalid entry
        with pytest.raises(ValueError):
            l2_tm.store("site.com", "en", "de", "", "translation")

        # Assert - error was logged
        assert "Invalid translation entry rejected" in caplog.text


# ==============================================================================
# TM-002 Invariant 4: Atomic Writes Tests
# ==============================================================================


@pytest.mark.contract
class TestAtomicWrites:
    """CONTRACT: TM-002 Invariant 4 - Atomic writes via LMDB transaction"""

    def test_store_uses_write_transaction(self, l2_tm, sample_entry_params):
        """
        INV: MUST use LMDB transaction with write=True.

        Evidence: src/tm/l2_persistent.py line 228
        """
        # Act - store entry
        result = l2_tm.store(**sample_entry_params)

        # Assert - entry stored successfully
        assert result is True

        # Verify entry exists
        entry = l2_tm.exact_lookup(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )
        assert entry is not None

    def test_batch_store_atomicity(self, l2_tm):
        """
        INV: batch_store MUST be atomic - all entries stored or none.

        Evidence: src/tm/l2_persistent.py lines 280-312
        """
        # Arrange - multiple valid entries
        entries = [
            TranslationEntry(
                source_text=f"Text {i}",
                translation=f"Translation {i}",
                site_id="site.com",
                src_lang="en",
                tgt_lang="de",
            )
            for i in range(5)
        ]

        # Act
        count = l2_tm.batch_store(entries)

        # Assert - all entries stored
        assert count == 5
        assert l2_tm.count() == 5

    def test_batch_store_rolls_back_on_validation_failure(self, l2_tm):
        """
        INV: batch_store MUST validate all entries before transaction.

        Evidence: src/tm/l2_persistent.py lines 270-278
        """
        # Arrange - mix of valid and invalid entries
        entries = [
            TranslationEntry(
                source_text="Valid Text",
                translation="Valid Translation",
                site_id="site.com",
                src_lang="en",
                tgt_lang="de",
            ),
            TranslationEntry(
                source_text="",  # Invalid - empty
                translation="Translation",
                site_id="site.com",
                src_lang="en",
                tgt_lang="de",
            ),
        ]

        # Act & Assert - should raise ValueError
        with pytest.raises(ValueError, match="Entry at index 1 failed validation"):
            l2_tm.batch_store(entries)

        # Assert - no entries stored (atomic rollback)
        assert l2_tm.count() == 0


# ==============================================================================
# TM-002 Invariant 5: Thread-Safe Operations Tests
# ==============================================================================


@pytest.mark.contract
class TestThreadSafety:
    """CONTRACT: TM-002 Invariant 5 - Thread-safe operations via RLock"""

    def test_concurrent_writes_are_thread_safe(self, tmp_path):
        """
        INV: MUST acquire lock before LMDB operations.

        Evidence: src/tm/l2_persistent.py lines 112, 226
        """
        l2_tm = L2PersistentTM(db_path=tmp_path / "concurrent_lmdb", max_size_mb=50)
        num_threads = 8
        entries_per_thread = 50
        errors: list[Exception] = []

        def writer(thread_id: int):
            try:
                for i in range(entries_per_thread):
                    l2_tm.store(
                        f"site{thread_id}.com",
                        "en",
                        "de",
                        f"text{i}",
                        f"translation_{thread_id}_{i}",
                    )
            except Exception as e:
                errors.append(e)

        # Act - concurrent writes from multiple threads
        threads = []
        for t in range(num_threads):
            thread = threading.Thread(target=writer, args=(t,))
            threads.append(thread)
            thread.start()

        for thread in threads:
            thread.join()

        # Assert - no errors occurred
        assert len(errors) == 0, f"Thread errors: {errors}"

        # Assert - all entries stored (8 threads * 50 entries each)
        assert l2_tm.count() == num_threads * entries_per_thread
        l2_tm.close()

    def test_concurrent_reads_and_writes_are_thread_safe(self, tmp_path):
        """
        INV: Mixed concurrent reads and writes must be thread-safe.

        Evidence: src/tm/l2_persistent.py uses RLock for all operations
        """
        l2_tm = L2PersistentTM(db_path=tmp_path / "mixed_lmdb", max_size_mb=50)
        num_operations = 200
        errors: list[Exception] = []

        # Pre-populate
        for i in range(50):
            l2_tm.store("site.com", "en", "de", f"text{i}", f"translation{i}")

        def reader_writer(thread_id: int):
            try:
                for i in range(num_operations):
                    if i % 2 == 0:
                        # Read operation
                        l2_tm.exact_lookup("site.com", "en", "de", f"text{i % 50}")
                    else:
                        # Write operation
                        l2_tm.store(
                            f"site{thread_id}.com",
                            "en",
                            "de",
                            f"text_{thread_id}_{i}",
                            f"trans_{i}",
                        )
            except Exception as e:
                errors.append(e)

        # Act - concurrent mixed operations
        with ThreadPoolExecutor(max_workers=8) as executor:
            futures = [executor.submit(reader_writer, i) for i in range(8)]
            for future in as_completed(futures):
                future.result()

        # Assert - no errors
        assert len(errors) == 0, f"Thread errors: {errors}"
        l2_tm.close()

    def test_rlock_allows_reentrant_access(self, l2_tm, sample_entry_params):
        """
        INV: Uses threading.RLock which allows reentrant locking.

        Evidence: src/tm/l2_persistent.py line 112 - threading.RLock()
        """
        # This test verifies the lock is reentrant by checking
        # that the lock type is indeed RLock
        assert isinstance(l2_tm._lock, type(threading.RLock()))

        # Verify lock can be acquired and released without deadlock
        with l2_tm._lock:
            # Store should work even though we hold the outer lock
            # because RLock allows same thread to acquire again
            # Note: This would deadlock with a regular Lock
            l2_tm.store(**sample_entry_params)

        # Verify entry was stored
        result = l2_tm.exact_lookup(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )
        assert result is not None


# ==============================================================================
# TM-002 Invariant 6: Context Filtering Tests
# ==============================================================================


@pytest.mark.contract
class TestContextFiltering:
    """CONTRACT: TM-002 Invariant 6 - Context filtering on lookup"""

    def test_context_match_returns_entry(self, l2_tm):
        """
        INV: IF context specified and matches, return entry.

        Evidence: src/tm/l2_persistent.py lines 166-168
        """
        # Arrange - store entry with context
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Hallo",
            context="frontmatter.title",
        )

        # Act - lookup with matching context
        result = l2_tm.exact_lookup("site.com", "en", "de", "Hello", context="frontmatter.title")

        # Assert - entry found
        assert result is not None
        assert result.translation == "Hallo"
        assert result.context == "frontmatter.title"

    def test_context_mismatch_returns_none(self, l2_tm):
        """
        INV: IF context specified and does NOT match, return None.

        Evidence: src/tm/l2_persistent.py lines 166-168
        """
        # Arrange - store entry with context "foo"
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Hallo",
            context="foo",
        )

        # Act - lookup with different context "bar"
        result = l2_tm.exact_lookup("site.com", "en", "de", "Hello", context="bar")

        # Assert - returns None (context mismatch)
        assert result is None

    def test_no_context_filter_returns_any_entry(self, l2_tm):
        """
        INV: IF no context specified in lookup, return entry regardless of context.

        Evidence: src/tm/l2_persistent.py lines 166-168 (context check only if specified)
        """
        # Arrange - store entry with context
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Hallo",
            context="some.context",
        )

        # Act - lookup without context filter
        result = l2_tm.exact_lookup("site.com", "en", "de", "Hello")

        # Assert - entry found (no context filter applied)
        assert result is not None
        assert result.translation == "Hallo"

    def test_same_text_different_contexts_uses_same_key(self, l2_tm):
        """
        INV: Context is NOT part of the key - same text overwrites regardless of context.

        Evidence: src/tm/l2_persistent.py - make_tm_key only uses site_id, src_lang, tgt_lang, text
        """
        # Arrange - store same text with different contexts
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Hallo v1",
            context="context1",
        )
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Hallo v2",
            context="context2",
        )

        # Act - lookup without context
        result = l2_tm.exact_lookup("site.com", "en", "de", "Hello")

        # Assert - only one entry exists (second overwrote first)
        assert result is not None
        assert result.translation == "Hallo v2"
        assert result.context == "context2"
        assert l2_tm.count() == 1


# ==============================================================================
# TM-002 Edge Cases: overwrite=False Tests
# ==============================================================================


@pytest.mark.contract
class TestOverwriteBehavior:
    """CONTRACT: TM-002 Edge Case - overwrite=False behavior"""

    def test_overwrite_false_skips_existing(self, l2_tm):
        """
        INV: overwrite=False with existing entry returns False and skips write.

        Evidence: src/tm/l2_persistent.py lines 230-233
        """
        # Arrange - store initial entry
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Original",
        )

        # Act - attempt to store with overwrite=False
        result = l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Updated",
            overwrite=False,
        )

        # Assert - returns False (skipped)
        assert result is False

        # Assert - original value preserved
        entry = l2_tm.exact_lookup("site.com", "en", "de", "Hello")
        assert entry.translation == "Original"

    def test_overwrite_false_stores_new_entry(self, l2_tm):
        """
        INV: overwrite=False with no existing entry stores successfully.

        Evidence: src/tm/l2_persistent.py lines 230-233
        """
        # Act - store new entry with overwrite=False
        result = l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="New text",
            translation="New translation",
            overwrite=False,
        )

        # Assert - returns True (stored)
        assert result is True

        # Assert - entry exists
        entry = l2_tm.exact_lookup("site.com", "en", "de", "New text")
        assert entry.translation == "New translation"

    def test_overwrite_true_updates_existing(self, l2_tm):
        """
        INV: overwrite=True (default) updates existing entry.

        Evidence: src/tm/l2_persistent.py default overwrite=True
        """
        # Arrange - store initial entry
        l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Original",
        )

        # Act - store with overwrite=True (default)
        result = l2_tm.store(
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            text="Hello",
            translation="Updated",
        )

        # Assert - returns True (stored/updated)
        assert result is True

        # Assert - value updated
        entry = l2_tm.exact_lookup("site.com", "en", "de", "Hello")
        assert entry.translation == "Updated"


# ==============================================================================
# TM-002: TranslationEntry Validation Tests
# ==============================================================================


@pytest.mark.contract
class TestTranslationEntryValidation:
    """CONTRACT: TM-002 - TranslationEntry.is_valid() behavior"""

    def test_valid_entry_passes_validation(self):
        """
        INV: Entry with all required fields passes validation.

        Evidence: src/tm/l2_persistent.py lines 51-78
        """
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
        )
        assert entry.is_valid() is True

    def test_valid_entry_with_optional_fields(self):
        """
        INV: Entry with valid optional fields passes validation.

        Evidence: src/tm/l2_persistent.py lines 70-76
        """
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
            context="frontmatter.title",
            metadata={"quality": 0.95},
            timestamp="2025-01-01T00:00:00Z",
        )
        assert entry.is_valid() is True

    def test_empty_source_text_fails_validation(self):
        """
        INV: Empty source_text fails validation.

        Evidence: src/tm/l2_persistent.py lines 59-60
        """
        entry = TranslationEntry(
            source_text="",
            translation="Hallo",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
        )
        assert entry.is_valid() is False

    def test_empty_translation_fails_validation(self):
        """
        INV: Empty translation fails validation.

        Evidence: src/tm/l2_persistent.py lines 61-62
        """
        entry = TranslationEntry(
            source_text="Hello",
            translation="",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
        )
        assert entry.is_valid() is False

    def test_invalid_context_type_fails_validation(self):
        """
        INV: Non-string context (when not None) fails validation.

        Evidence: src/tm/l2_persistent.py lines 71-72
        """
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
        )
        entry.context = 123  # Invalid type
        assert entry.is_valid() is False

    def test_invalid_metadata_type_fails_validation(self):
        """
        INV: Non-dict metadata (when not None) fails validation.

        Evidence: src/tm/l2_persistent.py lines 73-74
        """
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
        )
        entry.metadata = "not a dict"  # Invalid type
        assert entry.is_valid() is False

    def test_auto_timestamp_on_creation(self):
        """
        INV: Timestamp auto-set if not provided.

        Evidence: src/tm/l2_persistent.py lines 37-38
        """
        entry = TranslationEntry(
            source_text="Hello",
            translation="Hallo",
            site_id="site.com",
            src_lang="en",
            tgt_lang="de",
        )
        assert entry.timestamp is not None
        assert isinstance(entry.timestamp, str)


# ==============================================================================
# TM-002: Database Operations Tests
# ==============================================================================


@pytest.mark.contract
class TestDatabaseOperations:
    """CONTRACT: TM-002 - Additional database operation behaviors"""

    def test_count_returns_correct_value(self, l2_tm):
        """
        INV: count() returns accurate entry count.

        Evidence: src/tm/l2_persistent.py lines 335-344
        """
        # Initially empty
        assert l2_tm.count() == 0

        # Add entries
        for i in range(5):
            l2_tm.store("site.com", "en", "de", f"text{i}", f"trans{i}")

        # Assert count
        assert l2_tm.count() == 5

    def test_clear_removes_all_entries(self, l2_tm):
        """
        INV: clear() removes all entries from database.

        Evidence: src/tm/l2_persistent.py lines 346-351
        """
        # Arrange - add entries
        for i in range(5):
            l2_tm.store("site.com", "en", "de", f"text{i}", f"trans{i}")
        assert l2_tm.count() == 5

        # Act
        l2_tm.clear()

        # Assert
        assert l2_tm.count() == 0

    def test_delete_removes_specific_entry(self, l2_tm, sample_entry_params):
        """
        INV: delete() removes specific entry by key.

        Evidence: src/tm/l2_persistent.py lines 314-333
        """
        # Arrange
        l2_tm.store(**sample_entry_params)
        assert l2_tm.count() == 1

        # Act
        result = l2_tm.delete(
            sample_entry_params["site_id"],
            sample_entry_params["src_lang"],
            sample_entry_params["tgt_lang"],
            sample_entry_params["text"],
        )

        # Assert
        assert result is True
        assert l2_tm.count() == 0
        assert (
            l2_tm.exact_lookup(
                sample_entry_params["site_id"],
                sample_entry_params["src_lang"],
                sample_entry_params["tgt_lang"],
                sample_entry_params["text"],
            )
            is None
        )

    def test_delete_nonexistent_returns_false(self, l2_tm):
        """
        INV: delete() returns False for non-existent entry.

        Evidence: src/tm/l2_persistent.py lines 327
        """
        result = l2_tm.delete("nonexistent.com", "en", "de", "no such text")
        assert result is False

    def test_len_returns_count(self, l2_tm):
        """
        INV: __len__ returns same as count().

        Evidence: src/tm/l2_persistent.py lines 405-407
        """
        for i in range(3):
            l2_tm.store("site.com", "en", "de", f"text{i}", f"trans{i}")

        assert len(l2_tm) == l2_tm.count()
        assert len(l2_tm) == 3

    def test_context_manager_closes_db(self, tmp_path):
        """
        INV: Context manager properly closes database.

        Evidence: src/tm/l2_persistent.py lines 397-403
        """
        with L2PersistentTM(db_path=tmp_path / "ctx_lmdb", max_size_mb=10) as tm:
            tm.store("site.com", "en", "de", "Hello", "Hallo")
            assert tm.count() == 1

        # After context exit, db should be closed
        # Re-opening should work and preserve data
        tm2 = L2PersistentTM(db_path=tmp_path / "ctx_lmdb", max_size_mb=10)
        assert tm2.count() == 1
        tm2.close()

    def test_db_directory_auto_created(self, tmp_path):
        """
        INV: Database directory auto-created if not exists.

        Evidence: src/tm/l2_persistent.py lines 97-98
        """
        deep_path = tmp_path / "deep" / "nested" / "path" / "lmdb"
        assert not deep_path.exists()

        tm = L2PersistentTM(db_path=deep_path, max_size_mb=10)
        assert deep_path.exists()
        tm.close()
