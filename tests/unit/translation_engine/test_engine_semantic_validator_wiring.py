"""
TC-QG-004 (HT-QUALITY-GATES-001): SemanticSimilarityValidator must actually
be present in a real, production-path-constructed engine's ValidationSuite.

Root cause this heals: config/validation.yaml declared
`semantic_similarity.enabled: true` (with a comment claiming it "detects
semantic drift before write"), and engine_builder.py's _init_tm_wiring()
already wired the validator's shared encoder on every engine build — but the
validator itself was never instantiated into the running ValidationSuite.
The only code path that would have included it, ValidationSuite.from_config(),
was never called anywhere in src/cli.py or any worker module. Net effect:
every blocking gate in production was structural/statistical; none checked
translation meaning. tests/unit/validation/test_semantic_similarity_validator.py's
10 tests all instantiate the validator directly in isolation, so this exact
wiring gap had zero regression protection before this file existed.

This test constructs a real TranslationEngine via the real production
constructor path (same as test_engine_detector_wiring.py's pattern) — not a
mock, not from_config() directly — and asserts the validator ends up in
`engine.validation_suite.validators`. This is the specific regression
control against the wiring gap recurring silently.
"""
from pathlib import Path
from unittest.mock import Mock

import yaml

from src.translation_engine.engine import TranslationEngine
from src.translation_engine.validation.semantic_similarity_validator import (
    SemanticSimilarityValidator,
)


class _DummyConfigService:
    def get_config(self):
        return {
            "adaptive_batching": {"enabled": False},
            "language_detection": {"provider": "none"},
            "autonomous_recovery": {"oom_retry": {"enabled": False}},
        }


def _validators_of(engine) -> list:
    assert engine.validation_suite is not None, "enable_validation=True must produce a suite"
    return engine.validation_suite.validators


def test_semantic_validator_present_via_real_repo_config():
    """Uses the REAL config/validation.yaml (semantic_similarity.enabled: true
    as of this session) via the real production construction path — no mocking
    of the config-loading step itself."""
    engine = TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
    )

    validators = _validators_of(engine)
    assert any(isinstance(v, SemanticSimilarityValidator) for v in validators), (
        "SemanticSimilarityValidator must be present in the production "
        "ValidationSuite when config/validation.yaml's semantic_similarity."
        "enabled is true — TC-QG-004 regression."
    )


def test_semantic_validator_absent_when_config_disabled(tmp_path, monkeypatch):
    """When validation.yaml explicitly disables it and validation_mode is not
    'strict', the validator must NOT be added (proves this isn't unconditional)."""
    fake_config = {
        "validators": {
            "semantic_similarity": {"enabled": False},
        }
    }
    config_path = tmp_path / "validation.yaml"
    config_path.write_text(yaml.dump(fake_config), encoding="utf-8")

    import src.translation_engine.validation.validation_suite as vs_module

    original_load = vs_module.ValidationSuite.load_semantic_similarity_validator

    def _patched(config_path_arg=None, force_enable=False):
        return original_load(config_path=config_path, force_enable=force_enable)

    monkeypatch.setattr(
        vs_module.ValidationSuite, "load_semantic_similarity_validator", staticmethod(_patched)
    )

    engine = TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
    )

    validators = _validators_of(engine)
    assert not any(isinstance(v, SemanticSimilarityValidator) for v in validators)


def test_semantic_validator_force_enabled_by_strict_mode(tmp_path, monkeypatch):
    """validation_mode='strict' must enable it even when validation.yaml says
    disabled — the documented ("enable via --validation-mode strict or by
    setting enabled: true") contract that was never implemented."""
    fake_config = {
        "validators": {
            "semantic_similarity": {"enabled": False},
        }
    }
    config_path = tmp_path / "validation.yaml"
    config_path.write_text(yaml.dump(fake_config), encoding="utf-8")

    import src.translation_engine.validation.validation_suite as vs_module

    original_load = vs_module.ValidationSuite.load_semantic_similarity_validator

    def _patched(config_path_arg=None, force_enable=False):
        return original_load(config_path=config_path, force_enable=force_enable)

    monkeypatch.setattr(
        vs_module.ValidationSuite, "load_semantic_similarity_validator", staticmethod(_patched)
    )

    engine = TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
        validation_mode="strict",
    )

    validators = _validators_of(engine)
    assert any(isinstance(v, SemanticSimilarityValidator) for v in validators)


def test_explicit_validation_suite_is_not_mutated():
    """A caller-supplied validation_suite= must be respected as-is, not
    silently appended to."""
    from src.translation_engine.validation.validation_suite import ValidationSuite

    custom_suite = ValidationSuite(validators=[])

    engine = TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
        validation_suite=custom_suite,
    )

    assert engine.validation_suite is custom_suite
    assert engine.validation_suite.validators == []


def test_semantic_validator_not_duplicated_if_already_present():
    """If a passed-in suite already has one (e.g. via from_config()), the
    default-path auto-add logic must not run at all (validation_suite= was
    not None) — belt-and-suspenders no-duplicate check."""
    from src.translation_engine.validation.validation_suite import ValidationSuite

    pre_built = SemanticSimilarityValidator(warn_threshold=0.5, error_threshold=0.3)
    custom_suite = ValidationSuite(validators=[pre_built])

    engine = TranslationEngine(
        config_service=_DummyConfigService(),
        tm=Mock(),
        model_loader=Mock(),
        enable_validation=True,
        enable_telemetry=False,
        validation_suite=custom_suite,
    )

    semantic_validators = [v for v in engine.validation_suite.validators if isinstance(v, SemanticSimilarityValidator)]
    assert len(semantic_validators) == 1
    assert semantic_validators[0] is pre_built
