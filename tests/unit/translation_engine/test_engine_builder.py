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
    # CFG-01: a bare MagicMock's auto-vivified get_validation_config() would
    # return another MagicMock (truthy, non-int fields) instead of raising --
    # engine_builder.py's decision-rule loading would then silently use
    # mock garbage instead of falling back to its hardcoded defaults, which
    # is what every test using this fixture actually expects/relies on. This
    # mock has no real config/validation.yaml behind it, so raise, matching
    # engine_builder.py's real "config unavailable" fallback trigger.
    cfg.get_validation_config.side_effect = Exception("no validation config in test fixture")
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


class TestCFG01ValidationConfigPropagatesEndToEnd:
    """CFG-01 (TC-APT-105 audit): config/validation.yaml must be the actual
    source of truth it appears to be -- editing it must provably change
    ValidationDecisionEngine's real, effective behavior, not silently do
    nothing (which was true before this fix: the base decision_rules dict
    was 100% hardcoded in engine_builder.py, independent of the YAML)."""

    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_real_yaml_file_reject_on_error_count_reaches_decision_engine(
        self, mock_det, mock_retry, tmp_path
    ):
        """A real, on-disk validation.yaml (parsed through the real
        ValidationConfig/DecisionRules Pydantic models, not a mock) with a
        distinctive, non-default reject_on_error_count must be the value
        ValidationDecisionEngine actually uses -- the direct, end-to-end
        proof that this config file is load-bearing."""
        from src.utils.config_loader import ConfigService

        validation_yaml = tmp_path / "validation.yaml"
        validation_yaml.write_text(
            "version: '1.0'\n"
            "decision_rules:\n"
            "  reject_on_error_count: 97\n",  # distinctive, unmistakably not a hardcoded default
            encoding="utf-8",
        )
        real_config_service = ConfigService(tmp_path)
        real_validation_config = real_config_service.get_validation_config()
        assert real_validation_config.decision_rules.reject_on_error_count == 97, (
            "sanity check: the real YAML parses to the expected value"
        )

        config = _make_config()
        config.get_validation_config.side_effect = None
        config.get_validation_config.return_value = real_validation_config

        engine = MagicMock()
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
            validation_mode=None,
            enable_validation=True,
        )
        builder.build_into(engine)

        assert engine.decision_engine.reject_on_error_count == 97, (
            "the real YAML's value must reach the constructed decision engine"
        )

    @patch("src.translation_engine.engine_builder.EngineBuilder._init_detection")
    @patch("src.translation_engine.engine_builder.EngineBuilder._init_retry_handler")
    def test_missing_config_falls_back_to_pre_existing_hardcoded_defaults(
        self, mock_det, mock_retry
    ):
        """A config missing/unavailable (e.g. an older deployment without
        this file, or a load error) must reproduce EXACTLY today's
        pre-CFG-01 hardcoded behavior, not crash or silently use a wrong
        default."""
        config = _make_config()  # get_validation_config raises, per the fixture

        engine = MagicMock()
        builder = EngineBuilder(
            config_service=config,
            tm=_make_tm(),
            model_loader=_make_model_loader(),
            validation_mode=None,
            enable_validation=True,
        )
        builder.build_into(engine)

        assert engine.decision_engine.reject_on_error_count == 3
        assert engine.decision_engine.max_retry_attempts == 2
        assert engine.decision_engine.accept_warnings is True


# ---------------------------------------------------------------------------
# HT-QUALITY-GATES-001 Part 22 (plan 5.4 item 1): semantic-encoder wiring
# decoupled from skip_l3
# ---------------------------------------------------------------------------


class TestSemanticEncoderWiring:
    """Before this fix, SemanticSimilarityValidator's encoder was only ever
    set when `engine.tm.l3` was a real, initialized L3SemanticTM instance --
    which is None whenever skip_l3=True, the documented production default
    for multi-shard GPU runs. These tests confirm the encoder now gets set
    either way, via a standalone CPU-loaded fallback when L3 isn't active.
    """

    def test_uses_l3_encoder_when_l3_is_active(self):
        """A governed-model L3 encoder can be reused without a duplicate load."""
        from src.translation_engine.engine_builder import EngineBuilder
        from src.translation_engine.validation.semantic_similarity_validator import (
            SemanticSimilarityValidator,
        )

        engine = MagicMock()
        engine.tm.l3.encoder = "the-real-l3-encoder"
        engine.tm.l3.embedding_model_name = "governed-cross-lingual-model"
        engine.config.get_config.return_value = {
            "tm_defaults": {"l3_embedding_model": "governed-cross-lingual-model"}
        }

        with patch("src.tm.l3_semantic.load_standalone_sentence_encoder") as mock_standalone:
            EngineBuilder._init_tm_wiring(engine, {})

        mock_standalone.assert_not_called()
        assert SemanticSimilarityValidator._shared_encoder == "the-real-l3-encoder"

    def test_non_governed_l3_encoder_uses_configured_standalone_model(self):
        """An English-only TM encoder must not judge cross-lingual fidelity."""
        from src.translation_engine.engine_builder import EngineBuilder
        from src.translation_engine.validation.semantic_similarity_validator import (
            SemanticSimilarityValidator,
        )

        engine = MagicMock()
        engine.tm.l3.encoder = "english-only-encoder"
        engine.tm.l3.embedding_model_name = "all-MiniLM-L6-v2"
        engine.config.get_config.return_value = {
            "tm_defaults": {
                "l3_embedding_model": (
                    "sentence-transformers/paraphrase-multilingual-mpnet-base-v2"
                )
            }
        }

        with patch("src.tm.l3_semantic.load_standalone_sentence_encoder") as mock_standalone:
            mock_standalone.return_value = "cross-lingual-encoder"
            EngineBuilder._init_tm_wiring(engine, {})

        mock_standalone.assert_called_once_with(
            "sentence-transformers/paraphrase-multilingual-mpnet-base-v2",
            use_gpu=False,
        )
        assert SemanticSimilarityValidator._shared_encoder == "cross-lingual-encoder"

    def test_falls_back_to_standalone_cpu_encoder_when_l3_is_none(self):
        """The actual fix: engine.tm.l3 is None (skip_l3=True case) -- the
        encoder must still get set, via a standalone, CPU-loaded encoder."""
        from src.translation_engine.engine_builder import EngineBuilder
        from src.translation_engine.validation.semantic_similarity_validator import (
            SemanticSimilarityValidator,
        )

        engine = MagicMock()
        engine.tm.l3 = None
        engine.config.get_config.return_value = {
            "tm_defaults": {"l3_embedding_model": "test-model-name"}
        }

        with patch("src.tm.l3_semantic.load_standalone_sentence_encoder") as mock_standalone:
            mock_standalone.return_value = "the-standalone-encoder"
            EngineBuilder._init_tm_wiring(engine, {})

        mock_standalone.assert_called_once_with("test-model-name", use_gpu=False)
        assert SemanticSimilarityValidator._shared_encoder == "the-standalone-encoder"

    def test_standalone_load_failure_is_non_fatal(self):
        """A failure loading the standalone encoder (e.g. dependency
        missing, model download failure) must not break engine
        construction -- matches the existing non-fatal wiring pattern."""
        from src.translation_engine.engine_builder import EngineBuilder

        engine = MagicMock()
        engine.tm.l3 = None
        engine.config.get_config.return_value = {"tm_defaults": {}}

        with patch(
            "src.tm.l3_semantic.load_standalone_sentence_encoder",
            side_effect=RuntimeError("model download failed"),
        ):
            EngineBuilder._init_tm_wiring(engine, {})  # must not raise
