"""
Integration tests for write gate 41 (HT-QUALITY-GATES-001 Phase 8, Tier A
#4): homoglyph substitution in code spans/identifiers -- a Cyrillic/Greek
confusable character visually identical to an ASCII Latin letter appearing
inside an inline code span or fenced code block. No homoglyph/confusable-
character detection existed anywhere in this codebase before this gate.

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


class TestGateHomoglyphInCode:
    def test_cyrillic_o_in_inline_code_span_is_flagged(self):
        en = "---\ntitle: Test\n---\nCall `foo()` to start.\n"
        tr = "---\ntitle: Test\n---\nLlame a `fоo()` para comenzar.\n"  # Cyrillic о
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_homoglyph_in_code(en, tr, Path("test.md"), result)

        assert result.passed is False
        assert "U+043E" in result.error

    def test_clean_ascii_code_span_is_silent(self):
        en = "---\ntitle: Test\n---\nCall `foo()` to start.\n"
        tr = "---\ntitle: Test\n---\nLlame a `foo()` para comenzar.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_homoglyph_in_code(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_homoglyph_inside_fenced_code_block_is_flagged(self):
        en = "---\ntitle: Test\n---\nExample:\n\n```python\nfoo()\n```\n"
        tr = "---\ntitle: Test\n---\nEjemplo:\n\n```python\nfоo()\n```\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_homoglyph_in_code(en, tr, Path("test.md"), result)

        assert result.passed is False

    def test_cyrillic_prose_outside_code_is_not_this_gates_concern(self):
        """Non-Latin PROSE is Gate 2/4's job (language detection/purity) --
        this gate only cares about code-span/fenced-block context, where a
        homoglyph is always wrong (code is never translated)."""
        en = "---\ntitle: Test\n---\nThis is a normal English sentence.\n"
        tr = "---\ntitle: Test\n---\nЭто нормальное предложение на русском языке.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_homoglyph_in_code(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_greek_uppercase_alpha_is_flagged(self):
        en = "---\ntitle: Test\n---\nUse `Alpha()`.\n"
        tr = "---\ntitle: Test\n---\nUse `Αlpha()`.\n"  # Greek capital alpha
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_homoglyph_in_code(en, tr, Path("test.md"), result)

        assert result.passed is False

    def test_no_code_spans_at_all_is_a_no_op(self):
        en = "---\ntitle: Test\n---\nJust plain prose, no code here.\n"
        tr = "---\ntitle: Test\n---\nSolo prosa simple, sin codigo aqui.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_homoglyph_in_code(en, tr, Path("test.md"), result)

        assert result.passed is True
