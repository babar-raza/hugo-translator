"""
Integration tests for write gate 39 (HT-QUALITY-GATES-001 Phase 8, Tier A
#8): en-dash/hyphen numeric-range collapse -- e.g. "18-22" becoming "1822"
in translation. No digit-dash-digit separator check existed anywhere in
this codebase before this gate.

Ships "warn" per this registry's established rollout convention.
"""
from pathlib import Path
from unittest.mock import MagicMock

from src.translation_engine.write_gate import WriteGateEvaluator, WriteGateResult


def _make_gate() -> WriteGateEvaluator:
    config = MagicMock()
    config.get_config.return_value = {"translation_engine": {}}
    return WriteGateEvaluator(
        detector=None, similarity_tracker=None, config=config, force_accept=True,
    )


class TestGateDashRangeCollapsed:
    def test_ascii_hyphen_range_collapsed_is_flagged(self):
        en = "---\ntitle: Sample\n---\nSupported in versions 18-22 of the product.\n"
        tr = "---\ntitle: Sample\n---\nSoportado en las versiones 1822 del producto.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_dash_range_collapsed(en, tr, Path("test.md"), result)

        assert result.passed is False
        assert "18-22" in result.error
        assert "1822" in result.error

    def test_en_dash_range_collapsed_is_flagged(self):
        en = "---\ntitle: Sample\n---\nPages 5–10 cover this topic.\n"
        tr = "---\ntitle: Sample\n---\nLas paginas 510 cubren este tema.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_dash_range_collapsed(en, tr, Path("test.md"), result)

        assert result.passed is False

    def test_preserved_dash_range_is_silent(self):
        en = "---\ntitle: Sample\n---\nSupported in versions 18-22 of the product.\n"
        tr = "---\ntitle: Sample\n---\nSoportado en las versiones 18-22 del producto.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_dash_range_collapsed(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_range_reworded_as_prose_is_silent(self):
        """Negative control: a legitimately different (word-based) range
        rendering must not be flagged just because it doesn't literally
        preserve the dash character."""
        en = "---\ntitle: Sample\n---\nSupported in versions 18-22 of the product.\n"
        tr = "---\ntitle: Sample\n---\nSoportado de la version 18 a la 22 del producto.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_dash_range_collapsed(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_no_dash_ranges_in_source_is_a_no_op(self):
        en = "---\ntitle: Sample\n---\nNo numeric ranges here at all.\n"
        tr = "---\ntitle: Sample\n---\nNo hay rangos numericos aqui.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_dash_range_collapsed(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_range_inside_code_fence_is_ignored(self):
        """Code content is never translated and must not trigger this
        check even if it happens to contain a digit-dash-digit shape."""
        en = "---\ntitle: Sample\n---\nSee the example below:\n\n```python\nrange(18-22)\n```\n"
        tr = "---\ntitle: Sample\n---\nVea el ejemplo abajo:\n\n```python\nrange(18-22)\n```\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_dash_range_collapsed(en, tr, Path("test.md"), result)

        assert result.passed is True
