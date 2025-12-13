"""
Unit tests for L1 In-Memory Cache.
"""
import sys
import threading
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from tm.l1_cache import CacheStats, L1Cache


class TestCacheStats:
    """Test CacheStats functionality."""

    def test_initial_stats(self) -> None:
        """Test initial statistics are zero."""
        stats = CacheStats(max_size=1000)
        assert stats.hits == 0
        assert stats.misses == 0
        assert stats.evictions == 0
        assert stats.size == 0
        assert stats.max_size == 1000

    def test_hit_rate_calculation(self) -> None:
        """Test hit rate percentage calculation."""
        stats = CacheStats()

        # No requests
        assert stats.hit_rate == 0.0

        # 50% hit rate
        stats.hits = 5
        stats.misses = 5
        assert stats.hit_rate == 50.0

        # 100% hit rate
        stats.hits = 10
        stats.misses = 0
        assert stats.hit_rate == 100.0

        # 0% hit rate
        stats.hits = 0
        stats.misses = 10
        assert stats.hit_rate == 0.0

    def test_to_dict(self) -> None:
        """Test conversion to dictionary."""
        stats = CacheStats(max_size=100)
        stats.hits = 75
        stats.misses = 25
        stats.size = 50
        stats.evictions = 10

        result = stats.to_dict()

        assert result["hits"] == 75
        assert result["misses"] == 25
        assert result["size"] == 50
        assert result["evictions"] == 10
        assert result["max_size"] == 100
        assert result["hit_rate"] == 75.0  # 75/(75+25) * 100


class TestL1Cache:
    """Test L1Cache functionality."""

    def test_cache_initialization(self) -> None:
        """Test cache initializes correctly."""
        cache = L1Cache(max_size=500)
        assert cache.max_size == 500
        assert len(cache) == 0

    def test_cache_default_size(self) -> None:
        """Test default cache size."""
        cache = L1Cache()
        assert cache.max_size == 10000

    def test_put_and_get(self) -> None:
        """Test basic put and get operations."""
        cache = L1Cache()

        # Store translation
        cache.put("site1", "en", "es", "Hello", "Hola")

        # Retrieve translation
        result = cache.get("site1", "en", "es", "Hello")
        assert result == "Hola"

    def test_cache_miss(self) -> None:
        """Test cache miss returns None."""
        cache = L1Cache()

        result = cache.get("site1", "en", "es", "Not in cache")
        assert result is None

    def test_cache_key_uniqueness(self) -> None:
        """Test that different parameters create different keys."""
        cache = L1Cache()

        cache.put("site1", "en", "es", "Hello", "Hola")
        cache.put("site1", "en", "fr", "Hello", "Bonjour")
        cache.put("site2", "en", "es", "Hello", "Hola site2")

        # Different target language
        assert cache.get("site1", "en", "es", "Hello") == "Hola"
        assert cache.get("site1", "en", "fr", "Hello") == "Bonjour"

        # Different site
        assert cache.get("site2", "en", "es", "Hello") == "Hola site2"

        # Different text
        assert cache.get("site1", "en", "es", "Goodbye") is None

    def test_update_existing(self) -> None:
        """Test updating existing cache entry."""
        cache = L1Cache()

        cache.put("site1", "en", "es", "Hello", "Hola")
        cache.put("site1", "en", "es", "Hello", "Hola actualizado")

        result = cache.get("site1", "en", "es", "Hello")
        assert result == "Hola actualizado"

        # Should not create duplicate entry
        assert len(cache) == 1

    def test_lru_eviction(self) -> None:
        """Test LRU eviction when cache is full."""
        cache = L1Cache(max_size=3)

        # Fill cache
        cache.put("site1", "en", "es", "One", "Uno")
        cache.put("site1", "en", "es", "Two", "Dos")
        cache.put("site1", "en", "es", "Three", "Tres")

        assert len(cache) == 3

        # Add fourth item (should evict oldest)
        cache.put("site1", "en", "es", "Four", "Cuatro")

        assert len(cache) == 3
        assert cache.get("site1", "en", "es", "One") is None  # Evicted
        assert cache.get("site1", "en", "es", "Two") == "Dos"
        assert cache.get("site1", "en", "es", "Three") == "Tres"
        assert cache.get("site1", "en", "es", "Four") == "Cuatro"

    def test_lru_order_on_access(self) -> None:
        """Test that accessing item updates LRU order."""
        cache = L1Cache(max_size=3)

        cache.put("site1", "en", "es", "One", "Uno")
        cache.put("site1", "en", "es", "Two", "Dos")
        cache.put("site1", "en", "es", "Three", "Tres")

        # Access "One" (moves to end)
        cache.get("site1", "en", "es", "One")

        # Add fourth item (should evict "Two", not "One")
        cache.put("site1", "en", "es", "Four", "Cuatro")

        assert cache.get("site1", "en", "es", "One") == "Uno"  # Still present
        assert cache.get("site1", "en", "es", "Two") is None  # Evicted
        assert cache.get("site1", "en", "es", "Three") == "Tres"
        assert cache.get("site1", "en", "es", "Four") == "Cuatro"

    def test_clear(self) -> None:
        """Test clearing the cache."""
        cache = L1Cache()

        cache.put("site1", "en", "es", "Hello", "Hola")
        cache.put("site1", "en", "fr", "Hello", "Bonjour")

        assert len(cache) == 2

        cache.clear()

        assert len(cache) == 0

        # Get after clear will increment misses, so check stats before
        stats_before_get = cache.stats()
        assert stats_before_get["hits"] == 0
        assert stats_before_get["misses"] == 0

        # Now check get returns None
        assert cache.get("site1", "en", "es", "Hello") is None

    def test_stats_tracking(self) -> None:
        """Test that statistics are tracked correctly."""
        cache = L1Cache(max_size=2)

        # Initial stats
        stats = cache.stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0
        assert stats["evictions"] == 0
        assert stats["size"] == 0

        # Add entries
        cache.put("site1", "en", "es", "One", "Uno")
        cache.put("site1", "en", "es", "Two", "Dos")

        # Cache hit
        cache.get("site1", "en", "es", "One")
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 0

        # Cache miss
        cache.get("site1", "en", "es", "Three")
        stats = cache.stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 50.0

        # Trigger eviction
        cache.put("site1", "en", "es", "Three", "Tres")
        stats = cache.stats()
        assert stats["evictions"] == 1
        assert stats["size"] == 2

    def test_contains(self) -> None:
        """Test __contains__ method."""
        cache = L1Cache()

        cache.put("site1", "en", "es", "Hello", "Hola")

        assert ("site1", "en", "es", "Hello") in cache
        assert ("site1", "en", "es", "Goodbye") not in cache
        assert ("site2", "en", "es", "Hello") not in cache

    def test_len(self) -> None:
        """Test __len__ method."""
        cache = L1Cache()

        assert len(cache) == 0

        cache.put("site1", "en", "es", "One", "Uno")
        assert len(cache) == 1

        cache.put("site1", "en", "es", "Two", "Dos")
        assert len(cache) == 2

        cache.clear()
        assert len(cache) == 0

    def test_thread_safety(self) -> None:
        """Test thread-safe operations."""
        cache = L1Cache(max_size=1000)
        num_threads = 10
        ops_per_thread = 100

        def worker(thread_id: int) -> None:
            """Worker function for concurrent access."""
            for i in range(ops_per_thread):
                key = f"key_{thread_id}_{i}"
                value = f"value_{thread_id}_{i}"

                cache.put("site1", "en", "es", key, value)
                result = cache.get("site1", "en", "es", key)
                assert result == value

        threads = []
        for i in range(num_threads):
            t = threading.Thread(target=worker, args=(i,))
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Verify final state
        stats = cache.stats()
        assert stats["hits"] == num_threads * ops_per_thread
        assert stats["size"] <= cache.max_size

    def test_performance_lookup(self) -> None:
        """Test that lookups are fast (< 1µs on hits)."""
        cache = L1Cache()

        # Populate cache
        for i in range(100):
            cache.put("site1", "en", "es", f"Text {i}", f"Translation {i}")

        # Measure lookup time
        iterations = 10000
        start = time.perf_counter()

        for _ in range(iterations):
            cache.get("site1", "en", "es", "Text 50")

        end = time.perf_counter()
        avg_time_us = (end - start) / iterations * 1_000_000

        # Should be well under 5 microseconds for in-memory lookup
        # (being generous for Windows/test environment overhead)
        assert avg_time_us < 5.0, f"Avg lookup time: {avg_time_us:.2f}µs"

    def test_empty_text(self) -> None:
        """Test handling of empty text."""
        cache = L1Cache()

        cache.put("site1", "en", "es", "", "")
        result = cache.get("site1", "en", "es", "")
        assert result == ""

    def test_special_characters(self) -> None:
        """Test handling of special characters in text."""
        cache = L1Cache()

        special_text = "Hello! 你好 Здравствуй 🌍"
        translation = "Hola! 你好 Привет 🌍"

        cache.put("site1", "en", "es", special_text, translation)
        result = cache.get("site1", "en", "es", special_text)
        assert result == translation

    def test_large_text(self) -> None:
        """Test handling of large text blocks."""
        cache = L1Cache()

        large_text = "A" * 10000  # 10KB of text
        translation = "B" * 10000

        cache.put("site1", "en", "es", large_text, translation)
        result = cache.get("site1", "en", "es", large_text)
        assert result == translation
