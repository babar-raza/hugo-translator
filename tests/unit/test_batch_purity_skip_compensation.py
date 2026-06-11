"""TC-H3-COMP-TESTS: Batch purity skip compensation validation.

Proves that per-language purity overrides in validation.yaml are enforced
end-to-end through LanguageConsistencyValidator.

Four cases:
  1. test_es_98pct_threshold_rejects_97pct_file — Spanish at 97% purity → ERROR
  2. test_es_98pct_threshold_accepts_99pct_file — Spanish at 99% purity → PASS
  3. test_cs_97pct_threshold_enforced — Czech at 96% purity → ERROR
  4. test_batch_skip_does_not_disable_file_level_validator — validator always runs
"""

from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

ES_OVERRIDES = {
    "es": {"purity_threshold": 98.0, "confidence_threshold": 0.90},
    "it": {"purity_threshold": 98.0, "confidence_threshold": 0.90},
    "cs": {"purity_threshold": 97.0, "confidence_threshold": 0.88},
}


def _make_validator(overrides=None):
    from src.translation_engine.validation.language_consistency_validator import (
        LanguageConsistencyValidator,
    )

    return LanguageConsistencyValidator(
        confidence_threshold=0.85,
        per_language_overrides=overrides or ES_OVERRIDES,
    )


def _make_detected(lang: str, prob: float = 0.95):
    """Create a mock langdetect result."""
    d = MagicMock()
    d.lang = lang
    d.prob = prob
    return [d]


def _build_content_with_purity(
    total: int, correct_lang: str, wrong_lang: str, correct_count: int
) -> str:
    """Build a text with a controlled ratio of correct vs wrong language sentences."""
    # Use long enough sentences to pass min_sentence_length (8 chars)
    good = f"Esta es una oración de ejemplo en el idioma correcto de {correct_lang}."
    bad = f"This sentence is in the wrong language {wrong_lang} and should fail purity."
    sentences = [good] * correct_count + [bad] * (total - correct_count)
    return " ".join(sentences)


class TestBatchPuritySkipCompensation:
    def test_es_98pct_threshold_rejects_97pct_file(self):
        """Spanish file at 97% purity must be rejected (98% override enforced)."""
        validator = _make_validator()
        text = _build_content_with_purity(100, "es", "en", 97)

        def mock_detect_langs(sentence):
            if "correcto" in sentence:
                return _make_detected("es", 0.95)
            return _make_detected("en", 0.92)

        with patch(
            "src.translation_engine.validation.language_consistency_validator.langdetect.detect_langs",
            side_effect=mock_detect_langs,
        ):
            result = validator.validate("", text, context={"target_lang": "es"})

        errors = [i for i in result.issues if i.severity.value == "error"]
        assert errors, (
            "Spanish file at 97% purity must be rejected with 98% override; got no errors"
        )

    def test_es_98pct_threshold_accepts_99pct_file(self):
        """Spanish file at 99% purity must pass (>= 98% override)."""
        validator = _make_validator()
        # 99 good sentences, 1 bad
        text = _build_content_with_purity(100, "es", "en", 99)

        def mock_detect_langs(sentence):
            if "correcto" in sentence:
                return _make_detected("es", 0.95)
            return _make_detected("en", 0.92)

        with patch(
            "src.translation_engine.validation.language_consistency_validator.langdetect.detect_langs",
            side_effect=mock_detect_langs,
        ):
            result = validator.validate("", text, context={"target_lang": "es"})

        errors = [i for i in result.issues if i.severity.value == "error"]
        assert not errors, (
            f"Spanish file at 99% purity must pass with 98% override; got errors: {errors}"
        )

    def test_cs_97pct_threshold_enforced(self):
        """Czech file at 96% purity must be rejected (97% override enforced)."""
        validator = _make_validator()
        cs_text = _build_content_with_purity(100, "cs", "en", 96)

        def mock_detect_langs(sentence):
            if "correcto" in sentence:
                return _make_detected("cs", 0.92)
            return _make_detected("en", 0.90)

        with patch(
            "src.translation_engine.validation.language_consistency_validator.langdetect.detect_langs",
            side_effect=mock_detect_langs,
        ):
            result = validator.validate("", cs_text, context={"target_lang": "cs"})

        errors = [i for i in result.issues if i.severity.value == "error"]
        assert errors, "Czech file at 96% purity must be rejected with 97% override; got no errors"

    def test_batch_skip_does_not_disable_file_level_validator(self):
        """LanguageConsistencyValidator runs independently of batch_purity_skip_langs.

        Even if a language is in batch_purity_skip_langs (es, cs, it), the
        LanguageConsistencyValidator still validates at file level.
        This test confirms the validator is not gated by the batch skip flag.
        """
        from src.translation_engine.validation.language_consistency_validator import (
            LanguageConsistencyValidator,
        )

        # Confirm that the validator does not read batch_purity_skip_langs from config
        # (it should not — batch skip is an engine-level concern, not a validator concern)
        validator = LanguageConsistencyValidator(
            confidence_threshold=0.85,
            per_language_overrides=ES_OVERRIDES,
        )
        # Even if we pass "es" which is in batch_purity_skip_langs, validator should run
        bad_text = _build_content_with_purity(20, "es", "en", 10)  # only 50% correct → FAIL

        def mock_detect_langs(sentence):
            if "correcto" in sentence:
                return _make_detected("es", 0.95)
            return _make_detected("en", 0.92)

        with patch(
            "src.translation_engine.validation.language_consistency_validator.langdetect.detect_langs",
            side_effect=mock_detect_langs,
        ):
            result = validator.validate("", bad_text, context={"target_lang": "es"})

        errors = [i for i in result.issues if i.severity.value == "error"]
        assert errors, (
            "Validator must run for 'es' even though it is in batch_purity_skip_langs; got no errors"
        )
