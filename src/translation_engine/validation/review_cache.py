"""File-level review cache for validation results.

Caches validation outcomes keyed by:
  SHA256(source_body + translated_body + target_lang + config_fingerprint + schema_version)

The config_fingerprint is a SHA256 digest of the validation-relevant config (purity thresholds,
skip-langs, confidence threshold, etc.).  When any of those values change, all prior cache
entries automatically become misses — preventing stale ACCEPT decisions from being served after
a validator rule tightening.

Cache is stored as a JSON file.  ``make_key()`` requires the caller to supply the
``config_fingerprint`` (see ``ReviewCache.compute_config_fingerprint()`` for the helper).

Config: ``review_cache.enabled`` in global.yaml (default: false).

TC-M1B: config fingerprint added 2026-06-11 (ethereal-sauteeing-brook sprint 2).
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

# Increment when the cache entry schema changes to auto-invalidate all prior entries.
_CACHE_SCHEMA_VERSION = "2"  # v2: config_fingerprint added (TC-M1B)


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
    def make_key(
        source_body: str,
        translated_body: str,
        target_lang: str,
        config_fingerprint: str = "",
    ) -> str:
        """Deterministic cache key from content + language + validation config fingerprint.

        ``config_fingerprint`` must be produced by ``compute_config_fingerprint()``.
        When it is absent or empty (e.g., legacy callers) the resulting key differs from
        any fingerprint-bearing key, so old entries are automatically treated as misses.
        The schema version is always included so a future schema change auto-invalidates.
        """
        digest = hashlib.sha256(
            (
                source_body
                + "\x00"
                + translated_body
                + "\x00"
                + target_lang
                + "\x00"
                + config_fingerprint
                + "\x00"
                + _CACHE_SCHEMA_VERSION
            ).encode("utf-8", errors="replace")
        ).hexdigest()[:32]
        return digest

    @staticmethod
    def compute_config_fingerprint(translation_engine_cfg: dict) -> str:
        """Compute a short fingerprint of validation-relevant config fields.

        Only includes keys that, if changed, should invalidate existing cache entries:
        purity thresholds, skip-langs list, confidence threshold, and enabled flags.
        Changes to non-validation keys (e.g., batch size, GPU settings) do NOT
        invalidate the cache.

        Args:
            translation_engine_cfg: The ``translation_engine`` section of global.yaml.
        Returns:
            8-char hex digest that changes when any validation rule changes.
        """
        relevant: dict = {
            "purity_threshold_overrides": translation_engine_cfg.get(
                "purity_threshold_overrides", {}
            ),
            "min_file_purity_percentage": translation_engine_cfg.get(
                "min_file_purity_percentage", None
            ),
            "language_detection_confidence_threshold": translation_engine_cfg.get(
                "language_detection_confidence_threshold", None
            ),
            "batch_purity_skip_langs": sorted(
                translation_engine_cfg.get("batch_purity_skip_langs", [])
            ),
            "llm_output_ratio_overrides": translation_engine_cfg.get(
                "llm_output_ratio_overrides", {}
            ),
            "max_llm_output_to_input_ratio": translation_engine_cfg.get(
                "max_llm_output_to_input_ratio", None
            ),
        }
        payload = json.dumps(relevant, sort_keys=True, separators=(",", ":"))
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:8]

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
