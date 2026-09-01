"""
Integration tests for write gate 44 (independent-verification finding,
HT-QUALITY-GATES-001 Phase 8): SEO title/description SERP-length sanity.
No SEO field anywhere in this codebase (extraction, prompting, validation)
had any length/SERP-convention awareness before this gate -- a short
English title/description could balloon in translation with nothing
anywhere noticing.

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


class TestGateSeoLengthSanity:
    def test_ballooned_head_title_is_flagged(self):
        en = "---\ntitle: Test\nhead_title: \"PDF Merge Guide\"\n---\nBody.\n"
        tr = (
            "---\ntitle: Test\nhead_title: \"Guia completa y detallada paso a paso "
            "para combinar y fusionar archivos PDF facilmente\"\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_length_sanity(en, tr, Path("test.md"), result)

        assert result.passed is False
        assert "head_title" in result.error

    def test_ballooned_seotitle_is_flagged(self):
        en = "---\ntitle: Test\nseoTitle: \"PDF Merge Guide\"\n---\nBody.\n"
        tr = (
            "---\ntitle: Test\nseoTitle: \"Guia completa y detallada paso a paso "
            "para combinar y fusionar archivos PDF facilmente\"\n---\nCuerpo.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_length_sanity(en, tr, Path("test.md"), result)

        assert result.passed is False
        assert "seoTitle" in result.error

    def test_comparable_length_translation_is_silent(self):
        en = "---\ntitle: Test\nhead_title: \"Getting Started with PDF\"\n---\nBody.\n"
        tr = (
            "---\ntitle: Test\nhead_title: \"Erste Schritte mit PDF\"\n---\nKörper.\n"
        )
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_length_sanity(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_naturally_longer_target_language_is_not_flagged_below_threshold(self):
        """Some target languages are naturally more verbose than English --
        only a real, large ratio (>= +15 chars AND >= 1.5x) should flag, to
        keep this low-false-positive for ordinary translation-length drift."""
        en = "---\ntitle: Test\nhead_title: \"PDF Tools\"\n---\nBody.\n"
        tr = "---\ntitle: Test\nhead_title: \"Outils de PDF Avances\"\n---\nCorps.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_length_sanity(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_no_head_title_or_seotitle_field_is_a_no_op(self):
        en = "---\ntitle: Test\n---\nBody.\n"
        tr = "---\ntitle: Test\n---\nCuerpo.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_length_sanity(en, tr, Path("test.md"), result)

        assert result.passed is True

    def test_empty_translated_field_is_a_different_gates_concern(self):
        en = "---\ntitle: Test\nhead_title: \"PDF Merge Guide\"\n---\nBody.\n"
        tr = "---\ntitle: Test\nhead_title: \"\"\n---\nCuerpo.\n"
        gate = _make_gate()
        result = WriteGateResult(passed=True)
        gate._gate_seo_length_sanity(en, tr, Path("test.md"), result)

        assert result.passed is True
