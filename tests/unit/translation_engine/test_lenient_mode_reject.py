"""
TC-VFY-03 / TC-MLD-05: Regression test — lenient validation mode must NOT set
accept_after_max_retries=True.

Root cause (RC-1): engine.py previously overrode accept_after_max_retries to True in
lenient mode, causing blog.aspose.net to write wrong-language files to disk after all
validation retries were exhausted. This test locks in the fix so the regression cannot
be reintroduced silently.
"""

from unittest.mock import Mock

from src.translation_engine.engine import TranslationEngine
from src.translation_engine.validation.validation_suite import ValidationSuite


class _DummyConfigService:
    def get_config(self):
        return {
            "adaptive_batching": {"enabled": False},
            "language_detection": {"provider": "none"},
            "autonomous_recovery": {"oom_retry": {"enabled": False}},
        }


def _make_engine_lenient() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
        validation_mode="lenient",
    )


def _make_engine_normal() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
        validation_mode="normal",
    )


def _make_engine_strict() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
        validation_mode="strict",
    )


class TestLenientModeDoesNotAcceptAfterMaxRetries:
    """TC-MLD-05: Lenient mode must not set accept_after_max_retries=True."""

    def test_lenient_mode_accept_after_max_retries_is_false(self):
        """RC-1 regression: lenient mode must NOT override accept_after_max_retries to True."""
        engine = _make_engine_lenient()
        assert engine.decision_engine is not None
        assert engine.decision_engine.accept_after_max_retries is False, (
            "Lenient mode must not set accept_after_max_retries=True. "
            "This was RC-1 — the primary cause of mixed-language contamination on blog.aspose.net."
        )

    def test_lenient_mode_has_relaxed_error_count(self):
        """Lenient mode should still use the relaxed reject_on_error_count=5."""
        engine = _make_engine_lenient()
        assert engine.decision_engine.reject_on_error_count == 5

    def test_lenient_mode_accepts_warnings(self):
        """Lenient mode should still accept translations with warnings."""
        engine = _make_engine_lenient()
        assert engine.decision_engine.accept_warnings is True

    def test_normal_mode_accept_after_max_retries_is_false(self):
        """Normal mode must also not accept after max retries."""
        engine = _make_engine_normal()
        assert engine.decision_engine.accept_after_max_retries is False

    def test_strict_mode_accept_after_max_retries_is_false(self):
        """Strict mode must also not accept after max retries."""
        engine = _make_engine_strict()
        assert engine.decision_engine.accept_after_max_retries is False
