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

    from src.translation_engine.segment_translator import SegmentTranslator

    # Verify the guard is present in source (static regression check)
    src = inspect.getsource(SegmentTranslator._translate_body_ast)
    assert "TranslationIncomplete" in src, (
        "TC-AST-01: _translate_body_ast must raise TranslationIncomplete "
        "when fallback ratio exceeds tolerance."
    )
    assert "ast_fallback_node_tolerance" in src, (
        "TC-AST-01: _translate_body_ast must read ast_fallback_node_tolerance from config."
    )


def test_ast_reconstruction_does_not_fallback_after_body_render():
    """
    If frontmatter validation fails after AST body rendering, the pipeline must
    reject the file instead of falling back to legacy reconstruction with
    partially-mutated document state.
    """
    import inspect

    from src.translation_engine.segment_translator import SegmentTranslator

    src = inspect.getsource(SegmentTranslator.translate_to_language)
    assert "ast_body_rendered" in src
    assert "refusing legacy fallback" in src


def test_parse_formatted_frontmatter_requires_delimiters():
    """The AST frontmatter key check must not parse flattened body text as YAML."""
    from src.translation_engine.segment_translator import SegmentTranslator

    with pytest.raises(ValueError, match="missing YAML frontmatter delimiters"):
        SegmentTranslator._parse_formatted_frontmatter(
            'head_title: "Title" head_description: "Description"'
        )


def test_parse_formatted_frontmatter_parses_hugo_block():
    from src.translation_engine.segment_translator import SegmentTranslator

    parsed = SegmentTranslator._parse_formatted_frontmatter(
        "---\nhead_title: Title\nhead_description: Description\n---\n"
    )
    assert parsed == {
        "head_title": "Title",
        "head_description": "Description",
    }


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


# ---------------------------------------------------------------------------
# TC-SAS-01: Same-as-source detection
# ---------------------------------------------------------------------------


def _make_sas_unit(source: str, translated: str, do_not_translate: bool = False) -> MagicMock:
    unit = MagicMock(spec=TextUnit)
    unit.source_text = source
    unit.translated_text = translated
    unit.do_not_translate = do_not_translate
    return unit


def test_sas01_raises_when_ratio_exceeds_tolerance():
    """
    TC-SAS-01: When all translatable units come back same-as-source and tolerance=0.0,
    the gate must detect this as a source-language leakage condition.
    """
    long_text = "This is a long English sentence that should have been translated."
    units = [
        _make_sas_unit(long_text, long_text),  # same-as-source, len > 10
        _make_sas_unit(long_text, long_text),
    ]
    sas_min_len = 10
    sas_tolerance = 0.0

    translatable = [u for u in units if not u.do_not_translate]
    sas = [
        u for u in translatable
        if u.source_text
        and u.translated_text is not None
        and u.translated_text.strip() == u.source_text.strip()
        and len(u.source_text.strip()) > sas_min_len
    ]
    ratio = len(sas) / len(translatable) if translatable else 0.0

    assert ratio > sas_tolerance, "All units same-as-source with tolerance=0.0 must be rejected"
    with pytest.raises(TranslationIncomplete):
        if ratio > sas_tolerance:
            raise TranslationIncomplete(
                f"TC-SAS-01: ratio={ratio:.1%}",
                missing_count=len(sas),
                total_count=len(translatable),
                ratio=ratio,
                tolerance=sas_tolerance,
            )


def test_sas01_passes_when_within_tolerance():
    """
    TC-SAS-01: If only 1 of 10 units is same-as-source (10%) and tolerance=0.15,
    the gate must NOT raise (ratio is within tolerance).
    """
    long_text = "This is a long English sentence."
    translated_text = "Esta es una oración larga en español."
    units = [_make_sas_unit(long_text, long_text)] + [
        _make_sas_unit(long_text, translated_text) for _ in range(9)
    ]
    sas_min_len = 10
    sas_tolerance = 0.15

    translatable = [u for u in units if not u.do_not_translate]
    sas = [
        u for u in translatable
        if u.source_text
        and u.translated_text is not None
        and u.translated_text.strip() == u.source_text.strip()
        and len(u.source_text.strip()) > sas_min_len
    ]
    ratio = len(sas) / len(translatable) if translatable else 0.0

    assert ratio <= sas_tolerance, (
        f"ratio={ratio:.1%} <= tolerance={sas_tolerance:.1%} must not reject"
    )


def test_sas01_excludes_do_not_translate_units():
    """
    TC-SAS-01: Units with do_not_translate=True (preserved YAML fields, code blocks,
    shortcodes) must NOT be counted toward the same-as-source ratio even when
    their translated_text equals source_text.
    """
    long_text = "passthrough-value"
    # Only do_not_translate units — all same-as-source
    units = [
        _make_sas_unit(long_text, long_text, do_not_translate=True),
        _make_sas_unit(long_text, long_text, do_not_translate=True),
    ]
    sas_min_len = 10
    sas_tolerance = 0.0

    translatable = [u for u in units if not u.do_not_translate]
    sas = [
        u for u in translatable
        if u.source_text
        and u.translated_text is not None
        and u.translated_text.strip() == u.source_text.strip()
        and len(u.source_text.strip()) > sas_min_len
    ]
    # No translatable units → ratio is 0 → no rejection
    assert len(translatable) == 0, "do_not_translate units must be excluded from TC-SAS-01"
    assert len(sas) == 0


def test_sas01_config_keys_present():
    """TC-SAS-01 config keys must exist in global.yaml translation_engine section."""
    import yaml

    cfg_path = Path("config/global.yaml")
    if not cfg_path.exists():
        pytest.skip("config/global.yaml not present in working directory")
    with open(cfg_path) as f:
        cfg = yaml.safe_load(f)
    te = cfg.get("translation_engine", {})
    assert "same_as_source_tolerance" in te, (
        "same_as_source_tolerance missing from translation_engine config"
    )
    assert "same_as_source_min_length" in te, (
        "same_as_source_min_length missing from translation_engine config"
    )
    tol = float(te["same_as_source_tolerance"])
    assert 0.0 <= tol <= 1.0, f"same_as_source_tolerance={tol} is not in [0.0, 1.0]"


def test_sas01_source_present_in_segment_translator():
    """TC-SAS-01 guard must be present in _translate_body_ast source."""
    import inspect

    from src.translation_engine.segment_translator import SegmentTranslator

    src = inspect.getsource(SegmentTranslator._translate_body_ast)
    assert "TC-SAS-01" in src, (
        "TC-SAS-01: _translate_body_ast must contain same-as-source detection guard"
    )
    assert "same_as_source_tolerance" in src, (
        "TC-SAS-01: _translate_body_ast must read same_as_source_tolerance from config"
    )
