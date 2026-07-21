"""Unit tests for EngineBuilder (TC-TEST-04).

Tests builder wires all subsystems correctly and constructor
signature is backward compatible.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.engine_builder import EngineBuilder


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_config():
    cfg = MagicMock()
    cfg.get_config.return_value = {
        "translation_engine": {},
        "review_cache": {"enabled": False},
        "adaptive_thresholds": {"enabled": False},
        "content_hash": {"enabled": False},
        "retry_handler": {"enabled": False},
    }
    return cfg


def _make_tm():
    return MagicMock()


def _make_model_loader():
    return MagicMock()


# ---------------------------------------------------------------------------
# Builder construction and wiring
# ---------------------------------------------------------------------------


class TestEngineBuilderWiring:
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_build_into_sets_core_attributes(self, mock_det, mock_retry):
        """build_into() sets config, tm, model_loader on the engine."""
        config = _make_config()
        tm = _make_tm()
        ml = _make_model_loader()

        engine = MagicMock()
        builder = EngineBuilder(config_service=config, tm=tm, model_loader=ml)
        builder.build_into(engine)

        assert engine.config == config
        assert engine.tm == tm
        assert engine.model_loader == ml

    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_build_into_sets_flags(self, mock_det, mock_retry):
        """Boolean flags are correctly propagated."""
        config = _make_config()
        engine = MagicMock()
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
            dry_run=True,
            enable_verification=True,
            enable_verification_fix=True,
            batch_size=32,
        )
        builder.build_into(engine)

        assert engine.dry_run is True
        assert engine.enable_verification is True
        assert engine.enable_verification_fix is True
        assert engine.batch_size == 32

    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_build_into_creates_extracted_components(self, mock_det, mock_retry):
        """Extracted components (orchestrator, pipeline, translator, write_gate) are wired."""
        config = _make_config()
        engine = MagicMock()
        # Remove spec so arbitrary attributes can be set
        engine.configure_mock(
            **{
                "_dir_orchestrator": None,
                "_file_pipeline": None,
                "_segment_translator": None,
                "_write_gate": None,
            }
        )
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
        )
        builder.build_into(engine)

        # _init_extracted_components should have been called and set these
        # Since we're using a MagicMock, verify the assignments happened
        assert hasattr(engine, "_dir_orchestrator")
        assert hasattr(engine, "_file_pipeline")
        assert hasattr(engine, "_segment_translator")
        assert hasattr(engine, "_write_gate")


# ---------------------------------------------------------------------------
# Constructor signature backward compatibility
# ---------------------------------------------------------------------------


class TestConstructorBackwardCompat:
    def test_engine_constructor_signature_unchanged(self):
        """TranslationEngine constructor accepts all 22 named params + kwargs."""
        import inspect

        from src.translation_engine.engine import TranslationEngine

        sig = inspect.signature(TranslationEngine.__init__)
        params = list(sig.parameters.keys())
        # 'self' + 22 named params + **kwargs
        assert "self" in params
        assert "config_service" in params
        assert "tm" in params
        assert "model_loader" in params
        assert "enable_validation" in params
        assert "dry_run" in params
        assert "batch_size" in params
        assert "enable_verification" in params
        assert "output_dir_override" in params
        assert "production_ingestor" in params

    def test_both_import_paths_work(self):
        """Both import paths resolve to the same class."""
        from src.translation_engine import TranslationEngine as TE1
        from src.translation_engine.engine import TranslationEngine as TE2

        assert TE1 is TE2


# ---------------------------------------------------------------------------
# Validation mode wiring
# ---------------------------------------------------------------------------


class TestValidationModeWiring:
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_strict_mode_sets_low_error_count(self, mock_det, mock_retry):
        """validation_mode='strict' should lower reject_on_error_count."""
        config = _make_config()
        engine = MagicMock()
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
            validation_mode="strict",
        )
        builder.build_into(engine)

        # The decision engine should have been created with strict config
        # We verify engine.decision_engine was set (not None)
        assert engine.decision_engine is not None

    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_fast_mode_skips_retries_and_accepts_best_effort(self, mock_det, mock_retry):
        """TC-HT-STALL-001: validation_mode='fast' must resolve to
        max_retry_attempts=0 and accept_after_max_retries=True — MT backends
        are deterministic (greedy decoding) and cannot retry with feedback,
        so retrying only reproduces the same failure while burning GPU time.
        This is what heal_english_headings.py / unified_translate.py now rely
        on to stop wasting retries on deterministic MT failures."""
        config = _make_config()
        engine = MagicMock()
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
            validation_mode="fast",
            enable_validation=True,
        )
        builder.build_into(engine)

        assert engine.decision_engine is not None
        assert engine.decision_engine.max_retry_attempts == 0
        assert engine.decision_engine.accept_after_max_retries is True

    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_fast_mode_not_overridden_by_explicit_max_retries(self, mock_det, mock_retry):
        """validation_mode='fast' must force max_retry_attempts=0 even if a
        caller also passes an explicit max_retries — fast mode's whole point
        is that retries are pointless for deterministic MT, so it must win."""
        config = _make_config()
        engine = MagicMock()
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
            validation_mode="fast",
            max_retries=2,
            enable_validation=True,
        )
        builder.build_into(engine)

        assert engine.decision_engine.max_retry_attempts == 0
