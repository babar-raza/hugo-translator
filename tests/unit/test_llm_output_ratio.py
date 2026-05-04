"""TC-H2: Per-language LLM output ratio overrides.

Four cases:
  1. test_global_fallback_used_when_no_override — lang='es' uses global 4.0
  2. test_per_language_override_applied — lang='hi' uses 3.0
  3. test_11x_hindi_fails — 11× expansion fails with hi override (3.0)
  4. test_4x_czech_passes_with_override — 4× passes cs (override=5.0)
"""
from __future__ import annotations

import pytest
from unittest.mock import MagicMock, patch


def _make_backend(global_ratio=4.0, overrides=None):
    """Build LLMModelBackend with controlled ratio config."""
    from src.model_runtime.llm_backend import LLMModelBackend

    backend = LLMModelBackend.__new__(LLMModelBackend)
    backend._max_hallucination_ratio = global_ratio
    backend._hallucination_ratio_overrides = overrides or {}
    backend.last_truncation_detected = False
    backend.truncation_count = 0
    backend._terminology_manager = None
    backend._provider = MagicMock()
    # model_info needed by _build_system_prompt
    model_info = MagicMock()
    model_info.system_prompt_template = "Translate from {src_lang_name} to {tgt_lang_name}."
    backend.model_info = model_info
    return backend


class TestLLMOutputRatio:
    def test_global_fallback_used_when_no_override(self):
        """lang='es' → no override → uses global 4.0 ratio."""
        backend = _make_backend(global_ratio=4.0, overrides={"hi": 3.0, "pl": 5.0, "cs": 5.0})
        ratio = backend._hallucination_ratio_overrides.get("es", backend._max_hallucination_ratio)
        assert ratio == 4.0

    def test_per_language_override_applied(self):
        """lang='hi' → override 3.0, not global 4.0."""
        backend = _make_backend(global_ratio=4.0, overrides={"hi": 3.0, "pl": 5.0, "cs": 5.0})
        ratio = backend._hallucination_ratio_overrides.get("hi", backend._max_hallucination_ratio)
        assert ratio == 3.0

    def test_11x_hindi_fails(self):
        """11× Hindi output exceeds 3.0 override → truncated."""
        backend = _make_backend(global_ratio=4.0, overrides={"hi": 3.0})
        input_text = "Save the document"  # 18 chars
        # 11× = 198 chars → exceeds 3.0 × 18 = 54 chars
        result_text = "X" * (len(input_text) * 11)

        backend._provider.generate.return_value = (result_text, 10, 50)

        translations = [""]
        inp, out = backend._translate_single_segment(
            input_text, 0, 1, "en", "hi", None, translations
        )

        assert backend.last_truncation_detected is True, "11× output should trigger truncation for hi:3.0"
        assert len(translations[0]) <= len(input_text) * 3.0 * 1.05, (
            f"Truncated output should be ≤3× input; got {len(translations[0])} chars"
        )

    def test_4x_czech_passes_with_override(self):
        """4× Czech output passes because cs override is 5.0."""
        backend = _make_backend(global_ratio=4.0, overrides={"cs": 5.0})
        input_text = "Save the document"  # 18 chars
        # 4× = 72 chars → within 5.0 × 18 = 90 chars
        result_text = "X" * (len(input_text) * 4)

        backend._provider.generate.return_value = (result_text, 10, 20)

        translations = [""]
        inp, out = backend._translate_single_segment(
            input_text, 0, 1, "en", "cs", None, translations
        )

        assert backend.last_truncation_detected is False, "4× should NOT trigger truncation for cs:5.0"
        assert translations[0] == result_text
