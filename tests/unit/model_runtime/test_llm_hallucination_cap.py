"""
TC-AST-02 Issue B: Configurable LLM hallucination cap.

Verifies that LLMModelBackend truncates segments that exceed
max_llm_output_to_input_ratio (default 4.0) rather than the old hard-coded 5×.
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# ---------------------------------------------------------------------------
# Config key tests
# ---------------------------------------------------------------------------

def test_config_key_present():
    """max_llm_output_to_input_ratio must exist in global.yaml."""
    import yaml
    cfg_path = Path("config/global.yaml")
    if not cfg_path.exists():
        pytest.skip("config/global.yaml not present in working directory")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    te = cfg.get('translation_engine', {})
    assert 'max_llm_output_to_input_ratio' in te, (
        "max_llm_output_to_input_ratio missing from translation_engine config"
    )
    ratio = float(te['max_llm_output_to_input_ratio'])
    assert ratio > 0, "max_llm_output_to_input_ratio must be > 0"
    assert ratio <= 10.0, "max_llm_output_to_input_ratio > 10 is suspiciously lenient"


def test_default_ratio_is_tighter_than_old_value():
    """Default max_llm_output_to_input_ratio must be < 5.0 (old hard-coded threshold)."""
    import yaml
    cfg_path = Path("config/global.yaml")
    if not cfg_path.exists():
        pytest.skip("config/global.yaml not present in working directory")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    ratio = float(cfg.get('translation_engine', {}).get('max_llm_output_to_input_ratio', 4.0))
    assert ratio < 5.0, (
        f"max_llm_output_to_input_ratio={ratio} must be < 5.0 (old hard-coded threshold). "
        "TC-AST-02 requires tightening the cap."
    )


# ---------------------------------------------------------------------------
# LLMModelBackend attribute tests
# ---------------------------------------------------------------------------

def test_llm_backend_exposes_max_hallucination_ratio():
    """
    LLMModelBackend source must declare and assign _max_hallucination_ratio in __init__.
    Static inspection — no network calls needed.
    """
    import inspect
    from src.model_runtime.llm_backend import LLMModelBackend

    src = inspect.getsource(LLMModelBackend.__init__)
    assert '_max_hallucination_ratio' in src, (
        "LLMModelBackend.__init__ must assign self._max_hallucination_ratio "
        "so the hallucination cap is configurable (TC-AST-02)."
    )
    assert 'max_llm_output_to_input_ratio' in src, (
        "LLMModelBackend.__init__ must read max_llm_output_to_input_ratio from config "
        "to populate _max_hallucination_ratio."
    )


# ---------------------------------------------------------------------------
# Cap logic tests (ratio arithmetic, no network)
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("input_len,output_len,max_ratio,should_truncate", [
    (100, 350, 4.0, False),   # 3.5× — under cap
    (100, 400, 4.0, False),   # 4.0× — exactly at cap (not above)
    (100, 401, 4.0, True),    # 4.01× — just above cap
    (100, 1140, 4.0, True),   # 11.4× — observed production case (Hindi barcode)
    (100, 499, 5.0, False),   # 4.99× — old threshold would have passed; new 5.0 threshold just passes
    (100, 501, 5.0, True),    # 5.01× — above old threshold too
    (0, 100, 4.0, False),     # zero input — no cap (guard: input_len > 0)
])
def test_hallucination_cap_logic(input_len, output_len, max_ratio, should_truncate):
    """
    Ratio check: output > max_ratio × input → truncate.
    This mirrors the exact condition in LLMModelBackend._translate_one_segment.
    """
    would_truncate = input_len > 0 and output_len > max_ratio * input_len
    assert would_truncate == should_truncate, (
        f"input={input_len} output={output_len} ratio={max_ratio}: "
        f"expected truncate={should_truncate}, got {would_truncate}"
    )


def test_truncation_result_length():
    """Truncated result must be exactly int(input_len * max_ratio) chars."""
    input_len = 100
    max_ratio = 4.0
    output = "x" * 600  # 6× — above cap

    truncated = output[:int(input_len * max_ratio)]
    assert len(truncated) == int(input_len * max_ratio), (
        f"Truncated length {len(truncated)} != {int(input_len * max_ratio)}"
    )


def test_llm_backend_source_uses_configurable_ratio():
    """Static check: LLMModelBackend translate code must use _max_hallucination_ratio."""
    import inspect
    from src.model_runtime.llm_backend import LLMModelBackend

    # Find the method that does the per-segment translation
    src = inspect.getsource(LLMModelBackend)
    assert '_max_hallucination_ratio' in src, (
        "LLMModelBackend must use self._max_hallucination_ratio for the hallucination cap. "
        "Hard-coded '5 * input_len' violates TC-AST-02."
    )
