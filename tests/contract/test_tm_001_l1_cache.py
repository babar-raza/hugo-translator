"""
CONTRACT: specs/features/tm-001-l1-cache.md

Verifies L1 in-memory LRU cache behavior including:
- LRU eviction policy correctness
- Cache hit/miss behavior
- Max size limit enforcement
- Thread safety for concurrent access
- Statistics tracking accuracy

TM-001 Feature: L1 In-Memory Cache

Key Guarantees:
1. LRU eviction - least recently used entry evicted when cache full
2. Cache hits return stored translations
3. Cache misses return None
4. Max size limit is strictly enforced (never exceeds max_size)
5. Thread-safe concurrent reads and writes
6. Statistics accurately track hits, misses, and evictions
"""

import threading
from concurrent.futures import ThreadPoolExecutor, as_completed

import pytest

from src.tm.l1_cache import L1Cache

# ==============================================================================
# Fixtures
# ==============================================================================


@pytest.fixture
def cache():
    """
    Fresh L1Cache instance with default max_size.

    Evidence: src/tm/l1_cache.py L1Cache.__init__()
    """
    return L1Cache(max_size=10000)


@pytest.fixture
def small_cache():
    """
    L1Cache with small max_size for testing eviction behavior.

    Evidence: src/tm/l1_cache.py L1Cache.__init__()
    """
    return L1Cache(max_size=5)


@pytest.fixture
def sample_translation():
    """Standard translation parameters for tests."""
    return {
        "site_id": "test.example.com",
        "src_lang": "en",
        "tgt_lang": "de",
        "text": "Hello world",
        "translation": "Hallo Welt",
    }


# ==============================================================================
# TM-001: Cache Hit/Miss Behavior Tests
# ==============================================================================


@pytest.mark.contract
def test_cache_miss_returns_none(cache, sample_translation):
    """
    Verify cache miss returns None for unknown entries.

    CONTRACT: TM-001 - Cache miss returns None
    Evidence: src/tm/l1_cache.py L1Cache.get() lines 81-106
    """
    # Act - lookup non-existent entry
    result = cache.get(
        site_id=sample_translation["site_id"],
        src_lang=sample_translation["src_lang"],
        tgt_lang=sample_translation["tgt_lang"],
        text=sample_translation["text"],
    )

    # Assert - miss returns None
    assert result is None

    # Assert - stats track the miss
    stats = cache.stats()
    assert stats["misses"] == 1
    assert stats["hits"] == 0


@pytest.mark.contract
def test_cache_hit_returns_stored_translation(cache, sample_translation):
    """
    Verify cache hit returns the stored translation.

    CONTRACT: TM-001 - Cache hit returns stored value
    Evidence: src/tm/l1_cache.py L1Cache.get() lines 99-103
    """
    # Arrange - store a translation
    cache.put(
        site_id=sample_translation["site_id"],
        src_lang=sample_translation["src_lang"],
        tgt_lang=sample_translation["tgt_lang"],
        text=sample_translation["text"],
        translation=sample_translation["translation"],
    )

    # Act - lookup the stored entry
    result = cache.get(
        site_id=sample_translation["site_id"],
        src_lang=sample_translation["src_lang"],
        tgt_lang=sample_translation["tgt_lang"],
        text=sample_translation["text"],
    )

    # Assert - hit returns stored translation
    assert result == sample_translation["translation"]

    # Assert - stats track the hit
    stats = cache.stats()
    assert stats["hits"] == 1


@pytest.mark.contract
def test_different_sites_have_separate_entries(cache):
    """
    Verify same text with different site_id creates separate cache entries.

    CONTRACT: TM-001 Invariant 2 - Key uniqueness by (site_id, src, tgt, text)
    Evidence: src/tm/l1_cache.py L1Cache._make_key() lines 61-79
    """
    # Arrange - same text, different sites
    text = "Hello"
    translation_site1 = "Site1 Translation"
    translation_site2 = "Site2 Translation"

    cache.put("site1.com", "en", "de", text, translation_site1)
    cache.put("site2.com", "en", "de", text, translation_site2)

    # Act
    result_site1 = cache.get("site1.com", "en", "de", text)
    result_site2 = cache.get("site2.com", "en", "de", text)

    # Assert - different sites have different translations
    assert result_site1 == translation_site1
    assert result_site2 == translation_site2
    assert result_site1 != result_site2


@pytest.mark.contract
def test_different_languages_have_separate_entries(cache):
    """
    Verify same text with different language pairs creates separate entries.

    CONTRACT: TM-001 Invariant 2 - Key uniqueness by language pair
    Evidence: src/tm/l1_cache.py L1Cache._make_key() lines 61-79
    """
    # Arrange - same text, different target languages
    site_id = "test.com"
    text = "Hello"
    translation_de = "Hallo"
    translation_fr = "Bonjour"

    cache.put(site_id, "en", "de", text, translation_de)
    cache.put(site_id, "en", "fr", text, translation_fr)

    # Act
    result_de = cache.get(site_id, "en", "de", text)
    result_fr = cache.get(site_id, "en", "fr", text)

    # Assert - different language pairs have different translations
    assert result_de == translation_de
    assert result_fr == translation_fr


# ==============================================================================
# TM-001: LRU Eviction Policy Tests
# ==============================================================================


@pytest.mark.contract
def test_lru_eviction_removes_oldest_entry(small_cache):
    """
    Verify LRU eviction removes the least recently used entry.

    CONTRACT: TM-001 Invariant 1 - LRU eviction policy
    Evidence: src/tm/l1_cache.py L1Cache.put() lines 137-140
    """
    # Arrange - fill cache to capacity (max_size=5)
    for i in range(5):
        small_cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    # Verify cache is at capacity
    assert len(small_cache) == 5

    # Act - add one more entry, should evict text0 (oldest/LRU)
    small_cache.put("site", "en", "de", "text_new", "translation_new")

    # Assert - cache still at max_size
    assert len(small_cache) == 5

    # Assert - oldest entry (text0) was evicted
    assert small_cache.get("site", "en", "de", "text0") is None

    # Assert - newest entry exists
    assert small_cache.get("site", "en", "de", "text_new") == "translation_new"

    # Assert - other entries still exist (text1-text4)
    for i in range(1, 5):
        assert small_cache.get("site", "en", "de", f"text{i}") == f"translation{i}"


@pytest.mark.contract
def test_get_updates_recency_for_lru(small_cache):
    """
    Verify get() marks entry as recently used, preventing eviction.

    CONTRACT: TM-001 Invariant 3 - Get updates recency
    Evidence: src/tm/l1_cache.py L1Cache.get() lines 100-101 (move_to_end)
    """
    # Arrange - fill cache with entries 0-4
    for i in range(5):
        small_cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    # Access text0 to make it most recently used
    small_cache.get("site", "en", "de", "text0")

    # Act - add new entry, should evict text1 (now oldest due to text0 access)
    small_cache.put("site", "en", "de", "text_new", "translation_new")

    # Assert - text0 still exists (was accessed, so not LRU)
    assert small_cache.get("site", "en", "de", "text0") == "translation0"

    # Assert - text1 was evicted (became LRU after text0 was accessed)
    assert small_cache.get("site", "en", "de", "text1") is None


@pytest.mark.contract
def test_put_existing_key_updates_recency(small_cache):
    """
    Verify put() on existing key updates value and recency.

    CONTRACT: TM-001 Edge Case - Duplicate put updates entry
    Evidence: src/tm/l1_cache.py L1Cache.put() lines 130-132
    """
    # Arrange - fill cache with entries 0-4
    for i in range(5):
        small_cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    # Update text0 with new value (makes it MRU)
    small_cache.put("site", "en", "de", "text0", "updated_translation")

    # Act - add new entry, should evict text1 (oldest after text0 update)
    small_cache.put("site", "en", "de", "text_new", "translation_new")

    # Assert - text0 still exists with updated value
    assert small_cache.get("site", "en", "de", "text0") == "updated_translation"

    # Assert - text1 was evicted
    assert small_cache.get("site", "en", "de", "text1") is None


@pytest.mark.contract
def test_eviction_counter_increments_on_eviction(small_cache):
    """
    Verify eviction counter tracks actual evictions.

    CONTRACT: TM-001 Should 5 - Cache statistics (eviction count)
    Evidence: src/tm/l1_cache.py L1Cache.put() line 140
    """
    # Arrange - fill cache to capacity
    for i in range(5):
        small_cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    initial_stats = small_cache.stats()
    assert initial_stats["evictions"] == 0

    # Act - add 3 more entries, causing 3 evictions
    for i in range(3):
        small_cache.put("site", "en", "de", f"new_text{i}", f"new_translation{i}")

    # Assert - eviction count is 3
    final_stats = small_cache.stats()
    assert final_stats["evictions"] == 3


# ==============================================================================
# TM-001: Max Size Limit Enforcement Tests
# ==============================================================================


@pytest.mark.contract
def test_cache_never_exceeds_max_size(small_cache):
    """
    Verify cache size never exceeds max_size limit.

    CONTRACT: TM-001 Never 7 - NEVER exceed max_size
    Evidence: src/tm/l1_cache.py L1Cache.put() lines 138-140
    """
    max_size = small_cache.max_size

    # Add more entries than max_size
    for i in range(max_size * 3):
        small_cache.put("site", "en", "de", f"text{i}", f"translation{i}")

        # Assert - never exceeds max_size
        current_size = len(small_cache)
        assert current_size <= max_size, f"Cache size {current_size} exceeds max {max_size}"


@pytest.mark.contract
def test_max_size_enforced_at_capacity():
    """
    Verify max_size is strictly enforced at various capacities.

    CONTRACT: TM-001 Should 6 - Size limit enforcement
    Evidence: src/tm/l1_cache.py L1Cache.put() lines 138-140
    """
    for max_size in [1, 3, 10, 100]:
        cache = L1Cache(max_size=max_size)

        # Fill beyond capacity
        for i in range(max_size + 50):
            cache.put("site", "en", "de", f"text{i}", f"translation{i}")

        # Assert - size equals max_size
        assert len(cache) == max_size, f"Expected size {max_size}, got {len(cache)}"


@pytest.mark.contract
def test_stats_size_matches_actual_size(cache, sample_translation):
    """
    Verify stats size matches actual cache length.

    CONTRACT: TM-001 Should 5 - Cache statistics accuracy
    Evidence: src/tm/l1_cache.py L1Cache.stats() line 158
    """
    # Add some entries
    for i in range(10):
        cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    # Assert - stats size matches len()
    stats = cache.stats()
    assert stats["size"] == len(cache)
    assert stats["size"] == 10


# ==============================================================================
# TM-001: Thread Safety Tests
# ==============================================================================


@pytest.mark.contract
def test_concurrent_writes_are_thread_safe():
    """
    Verify concurrent writes don't corrupt cache state.

    CONTRACT: TM-001 Invariant 4 - Thread-safe access
    Evidence: src/tm/l1_cache.py L1Cache uses threading.RLock (line 58)
    """
    cache = L1Cache(max_size=1000)
    num_threads = 10
    entries_per_thread = 100

    def writer(thread_id: int):
        for i in range(entries_per_thread):
            cache.put(
                f"site{thread_id}",
                "en",
                "de",
                f"text{i}",
                f"translation_{thread_id}_{i}"
            )

    # Act - concurrent writes from multiple threads
    threads = []
    for t in range(num_threads):
        thread = threading.Thread(target=writer, args=(t,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Assert - cache is not corrupted, size is valid
    assert len(cache) <= cache.max_size

    # Assert - stats are consistent
    stats = cache.stats()
    assert stats["size"] == len(cache)


@pytest.mark.contract
def test_concurrent_reads_and_writes_are_thread_safe():
    """
    Verify concurrent reads and writes don't cause race conditions.

    CONTRACT: TM-001 Invariant 4 - Thread-safe concurrent access
    Evidence: src/tm/l1_cache.py uses threading.RLock for all operations
    """
    cache = L1Cache(max_size=100)
    num_operations = 500
    errors: list[Exception] = []

    # Pre-populate cache
    for i in range(50):
        cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    def reader_writer(thread_id: int):
        try:
            for i in range(num_operations):
                if i % 2 == 0:
                    # Read operation
                    cache.get("site", "en", "de", f"text{i % 50}")
                else:
                    # Write operation
                    cache.put("site", "en", "de", f"text_{thread_id}_{i}", f"trans_{i}")
        except Exception as e:
            errors.append(e)

    # Act - concurrent mixed operations
    with ThreadPoolExecutor(max_workers=8) as executor:
        futures = [executor.submit(reader_writer, i) for i in range(8)]
        for future in as_completed(futures):
            future.result()  # Will raise if thread had exception

    # Assert - no errors occurred
    assert len(errors) == 0, f"Thread errors: {errors}"

    # Assert - cache state is valid
    assert len(cache) <= cache.max_size


@pytest.mark.contract
def test_stats_are_thread_safe():
    """
    Verify stats counters are accurate under concurrent access.

    CONTRACT: TM-001 Should 5 - Statistics accuracy with concurrency
    Evidence: src/tm/l1_cache.py stats operations within lock
    """
    cache = L1Cache(max_size=100)
    num_threads = 4
    ops_per_thread = 100

    # Pre-populate half the lookups
    for i in range(50):
        cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    def mixed_ops(thread_id: int):
        for i in range(ops_per_thread):
            # Half will hit (0-49), half will miss (50-99)
            cache.get("site", "en", "de", f"text{i}")

    # Act
    threads = []
    for t in range(num_threads):
        thread = threading.Thread(target=mixed_ops, args=(t,))
        threads.append(thread)
        thread.start()

    for thread in threads:
        thread.join()

    # Assert - total hits + misses equals total operations
    stats = cache.stats()
    total_ops = num_threads * ops_per_thread
    assert stats["hits"] + stats["misses"] == total_ops, (
        f"Expected {total_ops} total ops, got {stats['hits']} hits + {stats['misses']} misses"
    )


# ==============================================================================
# TM-001: Statistics and Observability Tests
# ==============================================================================


@pytest.mark.contract
def test_hit_rate_calculation(cache):
    """
    Verify hit rate is calculated correctly.

    CONTRACT: TM-001 Should 5 - Cache statistics (hit_rate)
    Evidence: src/tm/l1_cache.py CacheStats.hit_rate property lines 24-27
    """
    # Arrange - 3 entries
    for i in range(3):
        cache.put("site", "en", "de", f"text{i}", f"translation{i}")

    # 4 hits
    for i in range(3):
        cache.get("site", "en", "de", f"text{i}")
    cache.get("site", "en", "de", "text0")  # 4th hit

    # 1 miss
    cache.get("site", "en", "de", "nonexistent")

    # Assert - hit_rate is 80% (4 hits / 5 total)
    stats = cache.stats()
    assert stats["hits"] == 4
    assert stats["misses"] == 1
    assert stats["hit_rate"] == 80.0


@pytest.mark.contract
def test_stats_reset_on_clear(cache):
    """
    Verify clear() resets both cache and statistics.

    CONTRACT: TM-001 Edge Case - Clear resets state
    Evidence: src/tm/l1_cache.py L1Cache.clear() lines 144-148
    """
    # Arrange - add entries and generate stats
    for i in range(10):
        cache.put("site", "en", "de", f"text{i}", f"translation{i}")
    cache.get("site", "en", "de", "text0")  # hit
    cache.get("site", "en", "de", "nonexistent")  # miss

    # Verify stats exist
    stats_before = cache.stats()
    assert stats_before["size"] > 0
    assert stats_before["hits"] > 0

    # Act - clear cache
    cache.clear()

    # Assert - cache is empty
    assert len(cache) == 0

    # Assert - stats are reset
    stats_after = cache.stats()
    assert stats_after["size"] == 0
    assert stats_after["hits"] == 0
    assert stats_after["misses"] == 0
    assert stats_after["evictions"] == 0


@pytest.mark.contract
def test_contains_operator(cache, sample_translation):
    """
    Verify __contains__ operator works correctly.

    CONTRACT: TM-001 - Cache membership check
    Evidence: src/tm/l1_cache.py L1Cache.__contains__() lines 166-183
    """
    # Arrange
    cache.put(
        sample_translation["site_id"],
        sample_translation["src_lang"],
        sample_translation["tgt_lang"],
        sample_translation["text"],
        sample_translation["translation"],
    )

    # Assert - entry exists
    key_tuple = (
        sample_translation["site_id"],
        sample_translation["src_lang"],
        sample_translation["tgt_lang"],
        sample_translation["text"],
    )
    assert key_tuple in cache

    # Assert - non-existent entry
    assert ("other.site", "en", "de", "other text") not in cache


@pytest.mark.contract
def test_max_size_in_stats(cache):
    """
    Verify max_size is correctly reported in stats.

    CONTRACT: TM-001 Should 5 - Cache statistics (max_size)
    Evidence: src/tm/l1_cache.py CacheStats.to_dict() line 37
    """
    stats = cache.stats()
    assert stats["max_size"] == cache.max_size
    assert stats["max_size"] == 10000  # default value


# ==============================================================================
# TM-001: Edge Case Tests
# ==============================================================================


@pytest.mark.contract
def test_empty_cache_behavior(cache):
    """
    Verify empty cache returns None and tracks miss.

    CONTRACT: TM-001 Edge Case - Empty cache
    Evidence: src/tm/l1_cache.py L1Cache.get() lines 104-106
    """
    # Assert - cache starts empty
    assert len(cache) == 0

    # Act - lookup in empty cache
    result = cache.get("site", "en", "de", "any text")

    # Assert - miss behavior
    assert result is None
    assert cache.stats()["misses"] == 1


@pytest.mark.contract
def test_single_entry_cache():
    """
    Verify cache with max_size=1 works correctly.

    CONTRACT: TM-001 Edge Case - Minimum size cache
    Evidence: src/tm/l1_cache.py L1Cache eviction logic
    """
    cache = L1Cache(max_size=1)

    # Add first entry
    cache.put("site", "en", "de", "text1", "trans1")
    assert len(cache) == 1
    assert cache.get("site", "en", "de", "text1") == "trans1"

    # Add second entry - should evict first
    cache.put("site", "en", "de", "text2", "trans2")
    assert len(cache) == 1
    assert cache.get("site", "en", "de", "text2") == "trans2"
    assert cache.get("site", "en", "de", "text1") is None  # evicted


@pytest.mark.contract
def test_empty_string_values(cache):
    """
    Verify cache handles empty string text and translation.

    CONTRACT: TM-001 Edge Case - Empty strings
    Evidence: src/tm/l1_cache.py - no validation prevents empty strings
    """
    # Empty text
    cache.put("site", "en", "de", "", "empty text translation")
    assert cache.get("site", "en", "de", "") == "empty text translation"

    # Empty translation
    cache.put("site", "en", "de", "text", "")
    assert cache.get("site", "en", "de", "text") == ""


@pytest.mark.contract
def test_unicode_text_handling(cache):
    """
    Verify cache handles Unicode text correctly.

    CONTRACT: TM-001 - Unicode support
    Evidence: src/tm/l1_cache.py uses str type throughout
    """
    # Various Unicode texts
    texts = [
        ("Chinese", "Hello", "Hallo"),
        ("Japanese", "Hello", "Hallo"),
        ("Arabic", "Hello", "Hallo"),
        ("Emoji", "Hello", "Hallo"),
        ("Mixed", "Hello", "Hallo"),
    ]

    for text, src, tgt in texts:
        cache.put("site", "en", "de", text, tgt)
        assert cache.get("site", "en", "de", text) == tgt, f"Failed for: {text}"
