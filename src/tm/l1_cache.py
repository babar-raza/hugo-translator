"""
L1 In-Memory Translation Cache.

Fast LRU cache for translation lookups within a worker's lifetime.
"""
import hashlib
import threading
from collections import OrderedDict
from dataclasses import dataclass
from typing import Any, Dict, Optional


@dataclass
class CacheStats:
    """Statistics for cache performance."""

    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size: int = 0
    max_size: int = 0

    @property
    def hit_rate(self) -> float:
        """Calculate hit rate as percentage."""
        total = self.hits + self.misses
        return (self.hits / total * 100) if total > 0 else 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary."""
        return {
            "hits": self.hits,
            "misses": self.misses,
            "evictions": self.evictions,
            "size": self.size,
            "max_size": self.max_size,
            "hit_rate": round(self.hit_rate, 2),
        }


class L1Cache:
    """
    LRU cache for fast translation lookups.

    Thread-safe in-memory cache using LRU eviction policy.
    Optimized for sub-microsecond lookups on cache hits.
    """

    def __init__(self, max_size: int = 10000):
        """
        Initialize L1 cache.

        Args:
            max_size: Maximum number of entries (default: 10,000)
        """
        self.max_size = max_size
        self._cache: OrderedDict[str, str] = OrderedDict()
        self._lock = threading.RLock()
        self._stats = CacheStats(max_size=max_size)

    def _make_key(
        self, site_id: str, src_lang: str, tgt_lang: str, text: str
    ) -> str:
        """
        Create cache key from lookup parameters.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text

        Returns:
            Cache key (hash of parameters)
        """
        # Create deterministic key
        key_data = f"{site_id}:{src_lang}:{tgt_lang}:{text}"
        # Use MD5 for speed (not security-critical)
        return hashlib.md5(key_data.encode()).hexdigest()

    def get(
        self, site_id: str, src_lang: str, tgt_lang: str, text: str
    ) -> Optional[str]:
        """
        Retrieve cached translation.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text to translate

        Returns:
            Cached translation if found, None otherwise
        """
        key = self._make_key(site_id, src_lang, tgt_lang, text)

        with self._lock:
            if key in self._cache:
                # Move to end (most recently used)
                self._cache.move_to_end(key)
                self._stats.hits += 1
                return self._cache[key]
            else:
                self._stats.misses += 1
                return None

    def put(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        translation: str,
    ) -> None:
        """
        Store translation in cache.

        Args:
            site_id: Site identifier
            src_lang: Source language code
            tgt_lang: Target language code
            text: Source text
            translation: Translated text
        """
        key = self._make_key(site_id, src_lang, tgt_lang, text)

        with self._lock:
            # Update existing entry
            if key in self._cache:
                self._cache[key] = translation
                self._cache.move_to_end(key)
            else:
                # Add new entry
                self._cache[key] = translation

                # Evict oldest if over limit
                if len(self._cache) > self.max_size:
                    self._cache.popitem(last=False)  # Remove oldest
                    self._stats.evictions += 1

            self._stats.size = len(self._cache)

    def clear(self) -> None:
        """Empty the cache and reset statistics."""
        with self._lock:
            self._cache.clear()
            self._stats = CacheStats(max_size=self.max_size)

    def stats(self) -> Dict[str, Any]:
        """
        Get cache statistics.

        Returns:
            Dictionary with hits, misses, hit_rate, size, etc.
        """
        with self._lock:
            self._stats.size = len(self._cache)
            return self._stats.to_dict()

    def __len__(self) -> int:
        """Return current cache size."""
        with self._lock:
            return len(self._cache)

    def __contains__(self, key_tuple: tuple) -> bool:
        """
        Check if translation exists in cache.

        Args:
            key_tuple: (site_id, src_lang, tgt_lang, text)

        Returns:
            True if cached, False otherwise
        """
        if len(key_tuple) != 4:
            return False

        site_id, src_lang, tgt_lang, text = key_tuple
        key = self._make_key(site_id, src_lang, tgt_lang, text)

        with self._lock:
            return key in self._cache
