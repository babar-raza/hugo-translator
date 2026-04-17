"""Query result caching for benchmark analytics.

Implements LRU (Least Recently Used) cache with TTL (Time-To-Live) for
frequently accessed analytics queries. Reduces database load and improves
dashboard response time.

Features:
- LRU eviction policy with configurable max size
- TTL-based cache invalidation
- Thread-safe operations
- Cache hit/miss metrics
- Telemetry integration

Example:
    cache = QueryCache(max_size=100, ttl_seconds=300)

    # Try to get cached result
    result = cache.get("trends:m2m100:cpu:daily")
    if result is None:
        # Cache miss - query database
        result = query_database()
        cache.set("trends:m2m100:cpu:daily", result)

    # Check metrics
    stats = cache.get_stats()
    print(f"Hit rate: {stats['hit_rate']:.2%}")
"""

import logging
import threading
import time
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class CacheEntry:
    """Single cache entry with TTL."""
    value: Any
    expires_at: float  # Unix timestamp


class QueryCache:
    """LRU cache with TTL for query results.

    Thread-safe cache implementation with:
    - LRU eviction: Least recently used entries evicted when cache is full
    - TTL expiration: Entries expire after configured time
    - Metrics tracking: Hit/miss counts, hit rate, evictions

    Example:
        cache = QueryCache(max_size=100, ttl_seconds=300)

        # Store result
        cache.set("query_key", {"data": [1, 2, 3]})

        # Retrieve result
        result = cache.get("query_key")
        if result:
            print("Cache hit!")
        else:
            print("Cache miss")

        # View statistics
        stats = cache.get_stats()
        print(f"Hit rate: {stats['hit_rate']:.2%}")
    """

    def __init__(self, max_size: int = 100, ttl_seconds: int = 300):
        """Initialize query cache.

        Args:
            max_size: Maximum number of entries to store (LRU eviction)
            ttl_seconds: Time-to-live for cached entries in seconds
        """
        self.max_size = max_size
        self.ttl_seconds = ttl_seconds

        # OrderedDict maintains insertion order for LRU
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._lock = threading.Lock()

        # Metrics
        self._hits = 0
        self._misses = 0
        self._evictions = 0
        self._expirations = 0

        logger.info(
            f"QueryCache initialized: max_size={max_size}, ttl={ttl_seconds}s"
        )

    def get(self, key: str) -> Any | None:
        """Retrieve cached value.

        Args:
            key: Cache key

        Returns:
            Cached value if found and not expired, None otherwise
        """
        with self._lock:
            if key not in self._cache:
                self._misses += 1
                logger.debug(f"Cache miss: {key}")
                return None

            entry = self._cache[key]

            # Check if expired
            if time.time() > entry.expires_at:
                # Remove expired entry
                del self._cache[key]
                self._expirations += 1
                self._misses += 1
                logger.debug(f"Cache expired: {key}")
                return None

            # Move to end (most recently used)
            self._cache.move_to_end(key)
            self._hits += 1
            logger.debug(f"Cache hit: {key}")
            return entry.value

    def set(self, key: str, value: Any) -> None:
        """Store value in cache.

        Args:
            key: Cache key
            value: Value to cache
        """
        with self._lock:
            # Calculate expiration time
            expires_at = time.time() + self.ttl_seconds

            # Check if key already exists
            if key in self._cache:
                # Update existing entry and move to end
                self._cache[key] = CacheEntry(value, expires_at)
                self._cache.move_to_end(key)
                logger.debug(f"Cache updated: {key}")
            else:
                # Add new entry
                self._cache[key] = CacheEntry(value, expires_at)

                # Evict oldest entry if cache is full
                if len(self._cache) > self.max_size:
                    evicted_key = next(iter(self._cache))
                    del self._cache[evicted_key]
                    self._evictions += 1
                    logger.debug(f"Cache evicted (LRU): {evicted_key}")

                logger.debug(f"Cache stored: {key}")

    def invalidate(self, key: str) -> bool:
        """Invalidate a specific cache entry.

        Args:
            key: Cache key to invalidate

        Returns:
            True if entry was removed, False if not found
        """
        with self._lock:
            if key in self._cache:
                del self._cache[key]
                logger.debug(f"Cache invalidated: {key}")
                return True
            return False

    def invalidate_pattern(self, pattern: str) -> int:
        """Invalidate all cache entries matching a pattern.

        Args:
            pattern: Pattern to match (simple prefix matching)

        Returns:
            Number of entries invalidated
        """
        with self._lock:
            keys_to_remove = [k for k in self._cache.keys() if k.startswith(pattern)]
            for key in keys_to_remove:
                del self._cache[key]

            count = len(keys_to_remove)
            if count > 0:
                logger.info(f"Cache invalidated {count} entries matching: {pattern}")
            return count

    def clear(self) -> None:
        """Clear all cache entries."""
        with self._lock:
            count = len(self._cache)
            self._cache.clear()
            logger.info(f"Cache cleared: {count} entries removed")

    def cleanup_expired(self) -> int:
        """Remove all expired entries.

        Returns:
            Number of expired entries removed
        """
        with self._lock:
            current_time = time.time()
            expired_keys = [
                k for k, v in self._cache.items()
                if current_time > v.expires_at
            ]

            for key in expired_keys:
                del self._cache[key]
                self._expirations += 1

            count = len(expired_keys)
            if count > 0:
                logger.debug(f"Cache cleanup: {count} expired entries removed")
            return count

    def get_stats(self) -> dict[str, Any]:
        """Get cache statistics.

        Returns:
            Dictionary with cache metrics:
            - size: Current number of entries
            - max_size: Maximum capacity
            - hits: Total cache hits
            - misses: Total cache misses
            - hit_rate: Cache hit rate (0.0 to 1.0)
            - evictions: Number of LRU evictions
            - expirations: Number of TTL expirations
        """
        with self._lock:
            total_requests = self._hits + self._misses
            hit_rate = self._hits / total_requests if total_requests > 0 else 0.0

            return {
                "size": len(self._cache),
                "max_size": self.max_size,
                "hits": self._hits,
                "misses": self._misses,
                "hit_rate": hit_rate,
                "evictions": self._evictions,
                "expirations": self._expirations,
                "ttl_seconds": self.ttl_seconds,
            }

    def reset_stats(self) -> None:
        """Reset cache statistics (but keep cached data)."""
        with self._lock:
            self._hits = 0
            self._misses = 0
            self._evictions = 0
            self._expirations = 0
            logger.debug("Cache statistics reset")


def make_cache_key(*args, **kwargs) -> str:
    """Generate cache key from arguments.

    Args:
        *args: Positional arguments
        **kwargs: Keyword arguments

    Returns:
        Cache key string

    Example:
        key = make_cache_key("trends", model_id="m2m100", device="cpu")
        # Returns: "trends:model_id=m2m100:device=cpu"
    """
    parts = [str(arg) for arg in args]

    for k, v in sorted(kwargs.items()):
        if v is not None:
            parts.append(f"{k}={v}")

    return ":".join(parts)
