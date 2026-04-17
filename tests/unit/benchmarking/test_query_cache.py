"""Unit tests for query result caching.

Tests LRU cache with TTL for benchmark analytics queries.
"""

import time

import pytest

from src.benchmarking.query_cache import QueryCache, make_cache_key


class TestQueryCache:
    """Test QueryCache functionality."""

    def test_initialization(self):
        """Test cache initialization with default and custom parameters."""
        # Default parameters
        cache = QueryCache()
        assert cache.max_size == 100
        assert cache.ttl_seconds == 300

        # Custom parameters
        cache = QueryCache(max_size=50, ttl_seconds=600)
        assert cache.max_size == 50
        assert cache.ttl_seconds == 600

    def test_set_and_get(self):
        """Test basic set and get operations."""
        cache = QueryCache(max_size=10, ttl_seconds=60)

        # Store value
        cache.set("key1", {"data": [1, 2, 3]})

        # Retrieve value
        result = cache.get("key1")
        assert result == {"data": [1, 2, 3]}

    def test_cache_miss(self):
        """Test cache miss returns None."""
        cache = QueryCache()

        # Try to get non-existent key
        result = cache.get("nonexistent")
        assert result is None

    def test_cache_hit_stats(self):
        """Test cache hit/miss statistics."""
        cache = QueryCache()

        # Store value
        cache.set("key1", "value1")

        # Hit
        result = cache.get("key1")
        assert result == "value1"

        # Miss
        result = cache.get("key2")
        assert result is None

        # Check stats
        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5

    def test_ttl_expiration(self):
        """Test TTL expiration removes stale entries."""
        cache = QueryCache(max_size=10, ttl_seconds=0.1)  # 100ms TTL

        # Store value
        cache.set("key1", "value1")

        # Immediate retrieval should succeed
        result = cache.get("key1")
        assert result == "value1"

        # Wait for expiration
        time.sleep(0.15)

        # Should be expired
        result = cache.get("key1")
        assert result is None

        # Check expiration stat
        stats = cache.get_stats()
        assert stats["expirations"] == 1

    def test_lru_eviction(self):
        """Test LRU eviction when cache is full."""
        cache = QueryCache(max_size=3, ttl_seconds=60)

        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # All should be retrievable
        assert cache.get("key1") == "value1"
        assert cache.get("key2") == "value2"
        assert cache.get("key3") == "value3"

        # Add one more (should evict key1 as oldest)
        cache.set("key4", "value4")

        # key1 should be evicted
        assert cache.get("key1") is None
        assert cache.get("key4") == "value4"

        # Check eviction stat
        stats = cache.get_stats()
        assert stats["evictions"] == 1

    def test_lru_update(self):
        """Test LRU updates on access."""
        cache = QueryCache(max_size=3, ttl_seconds=60)

        # Fill cache
        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        # Access key1 (makes it most recently used)
        cache.get("key1")

        # Add key4 (should evict key2 as least recently used)
        cache.set("key4", "value4")

        # key1 should still be there
        assert cache.get("key1") == "value1"
        # key2 should be evicted
        assert cache.get("key2") is None

    def test_update_existing_key(self):
        """Test updating an existing cache entry."""
        cache = QueryCache()

        cache.set("key1", "value1")
        assert cache.get("key1") == "value1"

        # Update value
        cache.set("key1", "value2")
        assert cache.get("key1") == "value2"

        # Should still count as single entry
        stats = cache.get_stats()
        assert stats["size"] == 1

    def test_invalidate(self):
        """Test manual cache invalidation."""
        cache = QueryCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Invalidate key1
        result = cache.invalidate("key1")
        assert result is True
        assert cache.get("key1") is None
        assert cache.get("key2") == "value2"

        # Invalidate non-existent key
        result = cache.invalidate("key3")
        assert result is False

    def test_invalidate_pattern(self):
        """Test pattern-based invalidation."""
        cache = QueryCache()

        cache.set("trends:m2m100:cpu", "data1")
        cache.set("trends:m2m100:cuda", "data2")
        cache.set("trends:nllb:cpu", "data3")
        cache.set("baselines:m2m100:cpu", "data4")

        # Invalidate all trends for m2m100
        count = cache.invalidate_pattern("trends:m2m100")
        assert count == 2

        # Check what remains
        assert cache.get("trends:m2m100:cpu") is None
        assert cache.get("trends:m2m100:cuda") is None
        assert cache.get("trends:nllb:cpu") == "data3"
        assert cache.get("baselines:m2m100:cpu") == "data4"

    def test_clear(self):
        """Test clearing entire cache."""
        cache = QueryCache()

        cache.set("key1", "value1")
        cache.set("key2", "value2")
        cache.set("key3", "value3")

        stats = cache.get_stats()
        assert stats["size"] == 3

        # Clear cache
        cache.clear()

        stats = cache.get_stats()
        assert stats["size"] == 0
        assert cache.get("key1") is None

    def test_cleanup_expired(self):
        """Test manual cleanup of expired entries."""
        cache = QueryCache(ttl_seconds=0.1)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        # Wait for expiration
        time.sleep(0.15)

        # Add fresh entry
        cache.set("key3", "value3")

        # Cleanup expired
        count = cache.cleanup_expired()
        assert count == 2

        # key3 should still be there
        assert cache.get("key3") == "value3"

    def test_get_stats(self):
        """Test comprehensive statistics."""
        cache = QueryCache(max_size=10, ttl_seconds=60)

        cache.set("key1", "value1")
        cache.set("key2", "value2")

        cache.get("key1")  # hit
        cache.get("key3")  # miss

        stats = cache.get_stats()
        assert stats["size"] == 2
        assert stats["max_size"] == 10
        assert stats["hits"] == 1
        assert stats["misses"] == 1
        assert stats["hit_rate"] == 0.5
        assert stats["ttl_seconds"] == 60

    def test_reset_stats(self):
        """Test resetting statistics while keeping data."""
        cache = QueryCache()

        cache.set("key1", "value1")
        cache.get("key1")
        cache.get("key2")

        stats = cache.get_stats()
        assert stats["hits"] == 1
        assert stats["misses"] == 1

        # Reset stats
        cache.reset_stats()

        stats = cache.get_stats()
        assert stats["hits"] == 0
        assert stats["misses"] == 0

        # Data should still be there
        assert cache.get("key1") == "value1"

    def test_thread_safety(self):
        """Test thread-safe operations."""
        import threading

        cache = QueryCache(max_size=100)

        def worker(thread_id):
            for i in range(10):
                key = f"key_{thread_id}_{i}"
                cache.set(key, f"value_{thread_id}_{i}")
                result = cache.get(key)
                assert result == f"value_{thread_id}_{i}"

        # Create multiple threads
        threads = [threading.Thread(target=worker, args=(i,)) for i in range(5)]

        # Start all threads
        for t in threads:
            t.start()

        # Wait for completion
        for t in threads:
            t.join()

        # Verify final state
        stats = cache.get_stats()
        assert stats["size"] <= 100


class TestMakeCacheKey:
    """Test cache key generation."""

    def test_basic_key(self):
        """Test basic key generation from args."""
        key = make_cache_key("trends", "m2m100", "cpu")
        assert key == "trends:m2m100:cpu"

    def test_kwargs_key(self):
        """Test key generation with kwargs (sorted alphabetically)."""
        key = make_cache_key("trends", model_id="m2m100", device="cpu")
        # kwargs are sorted alphabetically: device < model_id
        assert key == "trends:device=cpu:model_id=m2m100"

    def test_mixed_args_kwargs(self):
        """Test key generation with mixed args and kwargs."""
        key = make_cache_key("trends", "daily", model_id="m2m100", device="cpu")
        assert key == "trends:daily:device=cpu:model_id=m2m100"

    def test_none_values_excluded(self):
        """Test that None values are excluded from key."""
        key = make_cache_key("trends", model_id="m2m100", device=None, window="daily")
        assert "device" not in key
        assert "model_id=m2m100" in key
        assert "window=daily" in key

    def test_sorted_kwargs(self):
        """Test that kwargs are sorted for consistent keys."""
        key1 = make_cache_key("trends", model_id="m2m100", device="cpu", window="daily")
        key2 = make_cache_key("trends", window="daily", device="cpu", model_id="m2m100")
        assert key1 == key2


@pytest.fixture
def cache():
    """Provide a fresh QueryCache instance for tests."""
    return QueryCache(max_size=10, ttl_seconds=60)


class TestQueryCacheIntegration:
    """Integration tests for QueryCache with realistic usage."""

    def test_analytics_query_caching(self, cache):
        """Test caching analytics query results."""
        # Simulate analytics query result
        query_result = {
            "model_id": "m2m100_418m",
            "device": "cpu",
            "trends": [
                {"date": "2024-01-01", "throughput": 85.0},
                {"date": "2024-01-02", "throughput": 87.0},
            ]
        }

        # Generate cache key
        cache_key = make_cache_key(
            "get_performance_trends",
            model_id="m2m100_418m",
            device="cpu",
            time_window="daily"
        )

        # First access - cache miss
        result = cache.get(cache_key)
        assert result is None

        # Store result
        cache.set(cache_key, query_result)

        # Second access - cache hit
        result = cache.get(cache_key)
        assert result == query_result

        stats = cache.get_stats()
        assert stats["hit_rate"] == 0.5  # 1 hit, 1 miss

    def test_model_comparison_caching(self, cache):
        """Test caching model comparison results."""
        models = ["m2m100_418m", "nllb_200_distilled_600m"]
        device = "cpu"

        comparison_result = {
            "models": models,
            "device": device,
            "avg_throughput": {"m2m100_418m": 85.0, "nllb_200_distilled_600m": 120.0}
        }

        cache_key = make_cache_key(
            "get_model_comparison",
            models="|".join(sorted(models)),
            device=device
        )

        cache.set(cache_key, comparison_result)
        result = cache.get(cache_key)
        assert result == comparison_result

    def test_cache_invalidation_on_new_data(self, cache):
        """Test invalidating cache when new benchmark data arrives."""
        # Cache some results for m2m100
        cache.set("trends:m2m100:cpu:daily", {"data": "old"})
        cache.set("trends:m2m100:cuda:daily", {"data": "old"})
        cache.set("baselines:m2m100:cpu:monthly", {"data": "old"})

        # New benchmark run arrives for m2m100
        # Invalidate all cached queries for this model
        count = cache.invalidate_pattern("trends:m2m100:")
        assert count == 2

        # Trends should be invalidated
        assert cache.get("trends:m2m100:cpu:daily") is None
        # Baselines should remain
        assert cache.get("baselines:m2m100:cpu:monthly") is not None
