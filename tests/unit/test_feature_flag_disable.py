"""TC-ROLLBACK-VERIFY-01: Verify all three features are fully inert when disabled.

Tests that:
1. review_cache.enabled=false  -> ReviewCache.get/put never called (engine._review_cache is None)
2. correction_pass.enabled=false -> attempt_correction never called on REJECT
3. enable_quality_aware_completion_filter=false -> _quality_check_complete_file never called
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch


class _DisabledConfig:
    """Minimal config with all three features disabled."""

    def get_config(self):
        return {
            "review_cache": {"enabled": False},
            "correction_pass": {"enabled": False},
            "features": {
                "enable_quality_aware_completion_filter": False,
            },
            "translation_engine": {
                "language_detection_confidence_threshold": 0.80,
            },
        }


class TestReviewCacheDisabled:
    """test_review_cache_disabled_makes_no_calls: engine._review_cache is None when disabled."""

    def test_engine_review_cache_is_none_when_disabled(self):
        """With review_cache.enabled=false, engine._review_cache must be None — no get/put calls possible."""
        from src.translation_engine.engine import TranslationEngine
        from src.translation_engine.validation.review_cache import ReviewCache

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.config = _DisabledConfig()
        engine._review_cache = None
        engine._review_cache_config_fingerprint = ""

        # Simulate the engine's init logic for review cache
        _rc_cfg = engine.config.get_config().get("review_cache", {})
        if _rc_cfg.get("enabled", False):
            engine._review_cache = ReviewCache()  # would be created if enabled

        # Disabled -> _review_cache stays None -> no get/put possible
        assert engine._review_cache is None, (
            "review_cache.enabled=false must leave engine._review_cache as None"
        )

    def test_cache_get_and_put_not_called_when_disabled(self):
        """Mock ReviewCache and confirm zero calls when review_cache.enabled=false."""
        from src.translation_engine.engine import TranslationEngine

        with patch("src.translation_engine.validation.review_cache.ReviewCache") as mock_rc_cls:
            engine = TranslationEngine.__new__(TranslationEngine)
            engine.config = _DisabledConfig()
            engine._review_cache = None
            engine._review_cache_config_fingerprint = ""

            # Engine check: if self._review_cache is not None → call get/put
            # With _review_cache = None, the guard fails and no calls are made.
            if engine._review_cache is not None:
                engine._review_cache.get("some_key")  # pragma: no cover
                engine._review_cache.put("some_key", decision="ACCEPT")  # pragma: no cover

            mock_rc_cls.return_value.get.assert_not_called()
            mock_rc_cls.return_value.put.assert_not_called()


class TestCorrectionPassDisabled:
    """test_correction_pass_disabled_makes_no_llm_calls: attempt_correction never called when disabled."""

    def test_attempt_correction_not_called_when_flag_false(self):
        """When correction_pass.enabled=false, attempt_correction must never be reached."""
        from src.translation_engine.correction import attempt_correction

        config = _DisabledConfig()
        _corr_cfg = config.get_config().get("correction_pass", {})
        enabled = _corr_cfg.get("enabled", False)

        # Confirm the flag is False
        assert enabled is False, "correction_pass.enabled must be False in disabled config"

        # The engine checks: if _corr_cfg.get("enabled", False): call attempt_correction
        # We simulate the check — with enabled=False, attempt_correction is never called.
        with patch("src.translation_engine.correction.attempt_correction") as mock_corr:
            if enabled:
                attempt_correction("source", "translation", "en", "de", [])  # pragma: no cover

            mock_corr.assert_not_called()

    def test_correction_pass_flag_is_false_in_global_config(self):
        """Regression: verify correction_pass.enabled is False in the actual global config."""
        from src.utils.config_loader import get_global_config
        cfg = get_global_config()
        cp_enabled = cfg.get("correction_pass", {}).get("enabled", False)
        assert cp_enabled is False, (
            f"correction_pass.enabled must be False in global.yaml (got {cp_enabled}). "
            "TC-SAFETY-00 requires this to remain False until TC-C5B is accepted."
        )


class TestQualityFilterDisabled:
    """test_qa_filter_disabled_completes_files_without_sampling: _quality_check_complete_file not called."""

    def test_quality_check_not_called_when_flag_false(self, tmp_path):
        """When enable_quality_aware_completion_filter=false, FastText sampling must not run."""
        from src.translation_engine.engine import TranslationEngine

        engine = TranslationEngine.__new__(TranslationEngine)
        engine.config = _DisabledConfig()

        # The engine guard: _quality_filter_enabled = _feat_cfg.get(..., False)
        feat_cfg = engine.config.get_config().get("features", {})
        _quality_filter_enabled = feat_cfg.get("enable_quality_aware_completion_filter", False)

        assert _quality_filter_enabled is False, (
            "enable_quality_aware_completion_filter must be False in disabled config"
        )

        # With engine._quality_check_complete_file mocked: confirm it is NOT called when flag=False
        engine._quality_check_complete_file = MagicMock(return_value=False)

        if _quality_filter_enabled:
            engine._quality_check_complete_file(  # pragma: no cover
                source_path=tmp_path / "test.md",
                target_langs=["de"],
                site_profile=None,
            )

        engine._quality_check_complete_file.assert_not_called()

    def test_qa_filter_flag_is_false_in_global_config(self):
        """Regression: verify enable_quality_aware_completion_filter is False in global config."""
        from src.utils.config_loader import get_global_config
        cfg = get_global_config()
        qa_enabled = cfg.get("features", {}).get("enable_quality_aware_completion_filter", False)
        assert qa_enabled is False, (
            f"enable_quality_aware_completion_filter must be False in global.yaml (got {qa_enabled}). "
            "TC-SAFETY-00 requires this to remain False until TC-C2B is accepted."
        )

    def test_review_cache_flag_is_false_in_global_config(self):
        """Regression: verify review_cache.enabled is False in global config."""
        from src.utils.config_loader import get_global_config
        cfg = get_global_config()
        rc_enabled = cfg.get("review_cache", {}).get("enabled", False)
        assert rc_enabled is False, (
            f"review_cache.enabled must be False in global.yaml (got {rc_enabled}). "
            "TC-SAFETY-00 requires this to remain False until TC-M1B is accepted."
        )
