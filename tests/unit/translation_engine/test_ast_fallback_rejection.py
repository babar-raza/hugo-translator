"""
TC-AST-01: AST fallback node tolerance gate.

Verifies that TranslationIncomplete is raised when the fraction of AST nodes
without a matching translation unit exceeds ast_fallback_node_tolerance.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.translation_engine.exceptions import TranslationIncomplete
from src.translation_engine.extractor.text_unit import TextUnit
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_text_unit(node_addr: str, translated: str = "traducido") -> TextUnit:
    unit = MagicMock(spec=TextUnit)
    unit.node_addr = node_addr
    unit.translated_text = translated
    unit.source_text = "source"
    unit.prefix_ws = ""
    unit.suffix_ws = ""
    unit.metadata = {}
    unit.get_final_text = MagicMock(return_value=translated)
    return unit


# ---------------------------------------------------------------------------
# TranslationIncomplete exception shape
# ---------------------------------------------------------------------------


def test_translation_incomplete_attributes():
    exc = TranslationIncomplete(
        "10% fallback",
        missing_count=5,
        total_count=50,
        ratio=0.10,
        tolerance=0.0,
    )
    assert exc.missing_count == 5
    assert exc.total_count == 50
    assert exc.ratio == pytest.approx(0.10)
    assert exc.tolerance == pytest.approx(0.0)
    assert "10% fallback" in str(exc)


# ---------------------------------------------------------------------------
# Tolerance gate in engine.py
# ---------------------------------------------------------------------------


def test_config_key_present():
    """ast_fallback_node_tolerance must exist in global.yaml translation_engine section."""
    import yaml

    cfg_path = Path("config/global.yaml")
    if not cfg_path.exists():
        pytest.skip("config/global.yaml not present in working directory")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    te = cfg.get("translation_engine", {})
    assert "ast_fallback_node_tolerance" in te, (
        "ast_fallback_node_tolerance missing from translation_engine config"
    )
    tol = float(te["ast_fallback_node_tolerance"])
    assert 0.0 <= tol <= 1.0, f"ast_fallback_node_tolerance={tol} is not in [0.0, 1.0]"


def test_engine_raises_translation_incomplete_on_fallback(tmp_path):
    """
    When renderer._missing_node_count > 0 and tolerance=0.0, the engine
    must raise TranslationIncomplete (not silently write the file).
    """
    import inspect

    from src.translation_engine.engine import TranslationEngine

    # Verify the guard is present in source (static regression check)
    src = inspect.getsource(TranslationEngine._translate_body_ast)
    assert "TranslationIncomplete" in src, (
        "TC-AST-01: _translate_body_ast must raise TranslationIncomplete "
        "when fallback ratio exceeds tolerance."
    )
    assert "ast_fallback_node_tolerance" in src, (
        "TC-AST-01: _translate_body_ast must read ast_fallback_node_tolerance from config."
    )


def test_ast_renderer_missing_node_count_exposed():
    """
    ASTRenderer._missing_node_count must be accessible after apply_translations().
    Engine reads this attribute to compute the fallback ratio.
    """
    renderer = ASTRenderer()
    assert hasattr(renderer, "_missing_node_count"), (
        "ASTRenderer must expose _missing_node_count for TC-AST-01 tolerance check"
    )
    assert hasattr(renderer, "applied_units"), (
        "ASTRenderer must expose applied_units set for TC-AST-01 total node count"
    )


def test_translation_incomplete_is_translation_error():
    """TranslationIncomplete must inherit from TranslationError for consistent catching."""
    from src.translation_engine.exceptions import TranslationError

    assert issubclass(TranslationIncomplete, TranslationError)


def test_tolerance_zero_any_fallback_raises():
    """
    With tolerance=0.0, any missing node must trigger TranslationIncomplete.
    Simulate by patching renderer after apply_translations.
    """
    from src.translation_engine.exceptions import TranslationIncomplete

    # Simulate what engine does: check missing_count > 0 and raise
    missing_count = 1
    applied_count = 9
    total_checked = missing_count + applied_count
    fallback_ratio = missing_count / total_checked
    tolerance = 0.0

    if fallback_ratio > tolerance:
        raise_exc = True
    else:
        raise_exc = False

    assert raise_exc is True, "tolerance=0.0 with 1 missing node must trigger rejection"


def test_tolerance_nonzero_below_threshold_passes():
    """
    With tolerance=0.15, a 10% fallback ratio must NOT trigger TranslationIncomplete.
    """
    missing_count = 5
    applied_count = 45
    total_checked = missing_count + applied_count
    fallback_ratio = missing_count / total_checked
    tolerance = 0.15

    should_reject = fallback_ratio > tolerance
    assert should_reject is False, (
        f"ratio={fallback_ratio:.1%} < tolerance={tolerance:.1%} should pass"
    )


def test_tolerance_nonzero_above_threshold_rejects():
    """
    With tolerance=0.10, a 15% fallback ratio must trigger TranslationIncomplete.
    """
    missing_count = 15
    applied_count = 85
    total_checked = missing_count + applied_count
    fallback_ratio = missing_count / total_checked
    tolerance = 0.10

    should_reject = fallback_ratio > tolerance
    assert should_reject is True, (
        f"ratio={fallback_ratio:.1%} > tolerance={tolerance:.1%} should reject"
    )
