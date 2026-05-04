"""File-level review cache for validation results.

Caches validation outcomes keyed by hash(source_body + translated_body + target_lang).
When the same source+translation pair is seen again, the cached decision is returned
without re-running the full validation suite.

Cache is stored as a JSON file and invalidated automatically when content changes
(different hash = cache miss).

Config: ``review_cache.enabled`` in global.yaml (default: false).
"""
from __future__ import annotations

import hashlib
import json
import logging
import threading
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# Default location — caller can override via constructor
_DEFAULT_CACHE_PATH = Path("data/cache/review_cache.json")

# Max entries before oldest are evicted (LRU-style by timestamp)
_DEFAULT_MAX_ENTRIES = 10_000


class ReviewCache:
    """Thread-safe, JSON-backed validation review cache."""

    def __init__(
        self,
        cache_path: Path | str | None = None,
        max_entries: int = _DEFAULT_MAX_ENTRIES,
        max_age_days: int = 0,
    ) -> None:
        self._path = Path(cache_path) if cache_path else _DEFAULT_CACHE_PATH
        self._max_entries = max_entries
        self._max_age_days = max_age_days  # 0 = no expiration
        self._lock = threading.Lock()
        self._cache: dict[str, dict[str, Any]] = {}
        self._dirty = False
        self._load()

    # ── public API ──────────────────────────────────────────────────

    @staticmethod
    def make_key(source_body: str, translated_body: str, target_lang: str) -> str:
        """Deterministic cache key from content + language."""
        digest = hashlib.sha256(
            (source_body + "\x00" + translated_body + "\x00" + target_lang).encode("utf-8", errors="replace")
        ).hexdigest()[:32]
        return digest

    def get(self, key: str) -> dict[str, Any] | None:
        """Return cached entry or None on miss/expired."""
        with self._lock:
            entry = self._cache.get(key)
            if entry is None:
                return None
            # TTL check: skip expired entries
            if self._max_age_days > 0:
                created = entry.get("created", 0)
                if time.time() - created > self._max_age_days * 86400:
                    del self._cache[key]
                    self._dirty = True
                    return None
            entry["last_hit"] = time.time()
            self._dirty = True
            return entry

    def put(
        self,
        key: str,
        decision: str,
        error_count: int = 0,
        warning_count: int = 0,
        decision_reason: str = "",
    ) -> None:
        """Store a validation outcome."""
        with self._lock:
            self._cache[key] = {
                "decision": decision,
                "error_count": error_count,
                "warning_count": warning_count,
                "decision_reason": decision_reason,
                "created": time.time(),
                "last_hit": time.time(),
            }
            self._dirty = True
            if len(self._cache) > self._max_entries:
                self._evict_oldest()

    def save(self) -> None:
        """Persist to disk (no-op if clean)."""
        with self._lock:
            if not self._dirty:
                return
            self._write()
            self._dirty = False

    def clear(self) -> None:
        """Drop all entries."""
        with self._lock:
            self._cache.clear()
            self._dirty = True

    @property
    def size(self) -> int:
        with self._lock:
            return len(self._cache)

    # ── internal ────────────────────────────────────────────────────

    def _load(self) -> None:
        if not self._path.exists():
            return
        try:
            data = json.loads(self._path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                self._cache = data
        except Exception as exc:
            logger.warning("Review cache load failed (%s), starting fresh: %s", self._path, exc)
            self._cache = {}

    def _write(self) -> None:
        try:
            self._path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self._path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self._cache, separators=(",", ":")), encoding="utf-8")
            tmp.replace(self._path)
        except Exception as exc:
            logger.warning("Review cache write failed: %s", exc)

    def _evict_oldest(self) -> None:
        """Remove oldest 10% of entries by last_hit timestamp."""
        evict_count = max(1, len(self._cache) // 10)
        sorted_keys = sorted(
            self._cache,
            key=lambda k: self._cache[k].get("last_hit", 0),
        )
        for k in sorted_keys[:evict_count]:
            del self._cache[k]
