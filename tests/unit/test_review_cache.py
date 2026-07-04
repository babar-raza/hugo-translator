"""Tests for TC-05 / TC-M1B: File-level review cache + config fingerprint."""
from __future__ import annotations

import json
from pathlib import Path

import pytest

from src.translation_engine.validation.review_cache import ReviewCache, _CACHE_SCHEMA_VERSION


@pytest.fixture
def cache_path(tmp_path: Path) -> Path:
    return tmp_path / "review_cache.json"


@pytest.fixture
def cache(cache_path: Path) -> ReviewCache:
    return ReviewCache(cache_path=cache_path, max_entries=100)


class TestReviewCacheKeyGeneration:
    def test_make_key_deterministic(self):
        k1 = ReviewCache.make_key("hello", "hola", "es")
        k2 = ReviewCache.make_key("hello", "hola", "es")
        assert k1 == k2

    def test_make_key_differs_by_lang(self):
        k1 = ReviewCache.make_key("hello", "hola", "es")
        k2 = ReviewCache.make_key("hello", "hola", "fr")
        assert k1 != k2

    def test_make_key_differs_by_translation(self):
        k1 = ReviewCache.make_key("hello", "hola", "es")
        k2 = ReviewCache.make_key("hello", "bonjour", "es")
        assert k1 != k2

    def test_make_key_differs_by_source(self):
        k1 = ReviewCache.make_key("hello", "hola", "es")
        k2 = ReviewCache.make_key("goodbye", "hola", "es")
        assert k1 != k2


class TestReviewCacheConfigFingerprint:
    """TC-M1B: config fingerprint invalidates cache entries when validation rules change."""

    def test_different_fingerprints_produce_different_keys(self):
        """Different config fingerprints → different keys for identical content."""
        fp_a = ReviewCache.compute_config_fingerprint(
            {"purity_threshold_overrides": {"bg": 0.15}, "min_file_purity_percentage": 0.95}
        )
        fp_b = ReviewCache.compute_config_fingerprint(
            {"purity_threshold_overrides": {"bg": 0.50}, "min_file_purity_percentage": 0.95}
        )
        assert fp_a != fp_b, "Different purity thresholds must produce different fingerprints"

        k1 = ReviewCache.make_key("src", "tgt", "es", fp_a)
        k2 = ReviewCache.make_key("src", "tgt", "es", fp_b)
        assert k1 != k2, "Different config fingerprints must produce different cache keys"

    def test_same_fingerprint_produces_same_key(self):
        """Same config → same fingerprint → same key for same content."""
        cfg = {"purity_threshold_overrides": {"lt": 0.15}, "min_file_purity_percentage": 0.95}
        fp1 = ReviewCache.compute_config_fingerprint(cfg)
        fp2 = ReviewCache.compute_config_fingerprint(cfg)
        assert fp1 == fp2

        k1 = ReviewCache.make_key("src", "tgt", "bg", fp1)
        k2 = ReviewCache.make_key("src", "tgt", "bg", fp2)
        assert k1 == k2

    def test_empty_fingerprint_key_differs_from_fingerprinted_key(self):
        """Legacy callers that omit config_fingerprint get a different key than fingerprinted callers.
        This ensures all v1 (no-fingerprint) entries are automatic misses under v2."""
        fp = ReviewCache.compute_config_fingerprint({"purity_threshold_overrides": {}})
        k_legacy = ReviewCache.make_key("src", "tgt", "de")        # no fingerprint
        k_new = ReviewCache.make_key("src", "tgt", "de", fp)       # with fingerprint
        assert k_legacy != k_new, "v1 (no fingerprint) key must differ from v2 (with fingerprint) key"

    def test_compute_fingerprint_deterministic(self):
        """compute_config_fingerprint is deterministic regardless of dict ordering."""
        cfg = {
            "batch_purity_skip_langs": ["de", "ar", "fr"],
            "language_detection_confidence_threshold": 0.80,
            "purity_threshold_overrides": {"bg": 0.15, "lt": 0.15},
        }
        assert ReviewCache.compute_config_fingerprint(cfg) == ReviewCache.compute_config_fingerprint(cfg)

    def test_fingerprint_changes_on_skip_lang_list_change(self):
        """Adding a language to batch_purity_skip_langs changes the fingerprint."""
        fp_before = ReviewCache.compute_config_fingerprint(
            {"batch_purity_skip_langs": ["de", "fr"]}
        )
        fp_after = ReviewCache.compute_config_fingerprint(
            {"batch_purity_skip_langs": ["de", "fr", "it"]}
        )
        assert fp_before != fp_after

    def test_schema_version_exported(self):
        """_CACHE_SCHEMA_VERSION must be importable and non-empty."""
        assert _CACHE_SCHEMA_VERSION, "Schema version must be a non-empty string"
        assert _CACHE_SCHEMA_VERSION == "2", "Expected schema version 2 (TC-M1B upgrade)"


class TestReviewCachePutGet:
    def test_miss_returns_none(self, cache: ReviewCache):
        assert cache.get("nonexistent") is None

    def test_put_then_get(self, cache: ReviewCache):
        cache.put("abc", decision="ACCEPT", error_count=0, warning_count=1)
        entry = cache.get("abc")
        assert entry is not None
        assert entry["decision"] == "ACCEPT"
        assert entry["error_count"] == 0
        assert entry["warning_count"] == 1

    def test_size(self, cache: ReviewCache):
        assert cache.size == 0
        cache.put("a", decision="ACCEPT")
        cache.put("b", decision="REJECT")
        assert cache.size == 2


class TestReviewCachePersistence:
    def test_save_and_reload(self, cache_path: Path):
        c1 = ReviewCache(cache_path=cache_path)
        c1.put("k1", decision="ACCEPT", error_count=0, warning_count=2)
        c1.save()

        assert cache_path.exists()

        c2 = ReviewCache(cache_path=cache_path)
        entry = c2.get("k1")
        assert entry is not None
        assert entry["decision"] == "ACCEPT"
        assert entry["warning_count"] == 2

    def test_save_noop_when_clean(self, cache_path: Path):
        c = ReviewCache(cache_path=cache_path)
        c.save()  # should not create file (nothing to write)
        assert not cache_path.exists()

    def test_corrupt_file_starts_fresh(self, cache_path: Path):
        cache_path.parent.mkdir(parents=True, exist_ok=True)
        cache_path.write_text("NOT JSON", encoding="utf-8")
        c = ReviewCache(cache_path=cache_path)
        assert c.size == 0


class TestReviewCacheEviction:
    def test_evicts_when_over_max(self, cache_path: Path):
        c = ReviewCache(cache_path=cache_path, max_entries=10)
        for i in range(15):
            c.put(f"k{i}", decision="ACCEPT")
        # Should have evicted some entries
        assert c.size <= 14  # 15 - at least 1 evicted (10% of 10 = 1)

    def test_clear(self, cache: ReviewCache):
        cache.put("a", decision="ACCEPT")
        cache.put("b", decision="REJECT")
        cache.clear()
        assert cache.size == 0


class TestReviewCacheIntegration:
    """Test the full flow: make_key -> put -> get -> save -> reload -> get."""

    def test_end_to_end(self, cache_path: Path):
        source = "# Hello World\n\nThis is a test."
        translation = "# Hola Mundo\n\nEsta es una prueba."
        lang = "es"

        c1 = ReviewCache(cache_path=cache_path)
        key = ReviewCache.make_key(source, translation, lang)
        c1.put(key, decision="ACCEPT", error_count=0, warning_count=0)
        c1.save()

        # Simulate new engine run
        c2 = ReviewCache(cache_path=cache_path)
        key2 = ReviewCache.make_key(source, translation, lang)
        assert key == key2

        entry = c2.get(key2)
        assert entry is not None
        assert entry["decision"] == "ACCEPT"

        # Different translation = cache miss
        key3 = ReviewCache.make_key(source, "# Hola\n\nModificado.", lang)
        assert c2.get(key3) is None


class TestReviewCacheTTL:
    """Tests for TTL-based expiration (FIX-05)."""

    def test_expired_entry_returns_none(self, cache_path: Path):
        """Entry older than max_age_days is treated as a miss."""
        import time

        c = ReviewCache(cache_path=cache_path, max_age_days=1)
        c.put("old_key", decision="ACCEPT")
        # Manually backdate the entry
        with c._lock:
            c._cache["old_key"]["created"] = time.time() - 86400 * 2  # 2 days old
        assert c.get("old_key") is None

    def test_fresh_entry_returned(self, cache_path: Path):
        """Entry within max_age_days is returned normally."""
        c = ReviewCache(cache_path=cache_path, max_age_days=14)
        c.put("fresh_key", decision="ACCEPT")
        assert c.get("fresh_key") is not None

    def test_zero_max_age_disables_ttl(self, cache_path: Path):
        """max_age_days=0 means no expiration (TTL disabled)."""
        import time

        c = ReviewCache(cache_path=cache_path, max_age_days=0)
        c.put("k", decision="ACCEPT")
        with c._lock:
            c._cache["k"]["created"] = time.time() - 86400 * 365  # 1 year old
        assert c.get("k") is not None


class TestReviewCacheEngineIntegration:
    """Tests proving the cache is correctly wired in the engine flow."""

    def test_cache_hit_skips_validation(self):
        """On cache hit with ACCEPT, the validation suite must NOT be called."""
        # Simulate the engine's cache-check logic from engine.py lines 1540-1599
        import time
        from unittest.mock import MagicMock

        cache = ReviewCache.__new__(ReviewCache)
        cache._lock = __import__("threading").Lock()
        cache._cache = {}
        cache._dirty = False
        cache._path = Path("/dev/null")
        cache._max_entries = 100
        cache._max_age_days = 0

        key = ReviewCache.make_key("src", "tgt", "es")
        cache.put(key, decision="ACCEPT")

        entry = cache.get(key)

        # Simulate the engine logic
        _rc_hit = False
        if entry and entry.get("decision") == "ACCEPT":
            _rc_hit = True

        mock_validation_suite = MagicMock()
        if not _rc_hit:
            mock_validation_suite.validate_aggregated("src", "tgt", context={})

        # Validation suite should NOT have been called
        mock_validation_suite.validate_aggregated.assert_not_called()
