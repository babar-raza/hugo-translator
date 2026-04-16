from unittest.mock import Mock

from src.utils.models import GlobalConfig
from src.translation_engine.engine import TranslationEngine


class _DummyConfigService:
    def get_config(self):
        return {
            "adaptive_batching": {"enabled": False},
            "language_detection": {"provider": "none"},
            "autonomous_recovery": {"oom_retry": {"enabled": False}},
        }


class _StubDetector:
    def detect(self, text):
        return ("fr", 0.99)


def _make_engine() -> TranslationEngine:
    return TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=False,
        enable_telemetry=False,
    )


def test_engine_initializes_legacy_detector_alias():
    engine = _make_engine()

    assert hasattr(engine, "detector")
    assert engine.detector is engine.fasttext_detector


def test_get_language_detector_prefers_fasttext_without_legacy_attr():
    engine = _make_engine()
    engine.fasttext_detector = _StubDetector()

    # Simulate older instances/state that do not carry self.detector
    if hasattr(engine, "detector"):
        delattr(engine, "detector")

    resolved = engine._get_language_detector()
    assert isinstance(resolved, _StubDetector)


def test_get_language_detector_falls_back_to_legacy_alias():
    engine = _make_engine()
    engine.fasttext_detector = None
    engine.detector = _StubDetector()

    resolved = engine._get_language_detector()
    assert isinstance(resolved, _StubDetector)


def test_batch_purity_skip_langs_wired_from_dict_config():
    engine = _make_engine()
    engine.config.global_config = {
        "translation_engine": {"batch_purity_skip_langs": ["cs"]},
    }

    assert engine._load_batch_purity_skip_langs() == ["cs"]


def test_batch_purity_skip_langs_wired_from_pydantic_config():
    engine = _make_engine()
    engine.config.global_config = GlobalConfig(
        translation_engine={"batch_purity_skip_langs": ["hr"]},
    )

    assert engine._load_batch_purity_skip_langs() == ["hr"]


def test_batch_purity_skip_langs_absent_is_empty():
    engine = _make_engine()
    engine.config.global_config = GlobalConfig()

    assert engine._load_batch_purity_skip_langs() == []
