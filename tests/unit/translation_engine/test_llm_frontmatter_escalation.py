"""Regression tests for LLM escalation over failed frontmatter segments."""

from types import SimpleNamespace

from src.translation_engine.extractor.segment_extractor import SegmentContextType
from src.translation_engine.segment_translator import SegmentTranslator


def _segment(text: str, context_type=SegmentContextType.FRONTMATTER):
    return SimpleNamespace(
        source_text=text,
        context=SimpleNamespace(context_type=context_type),
    )


def test_llm_escalation_does_not_reuse_unchanged_frontmatter():
    segment = _segment("Spreadsheet Management in Rust with Aspose.Cells FOSS")

    assert not SegmentTranslator._can_reuse_ast_translation(
        segment, segment.source_text, "professionalize_llm"
    )


def test_llm_escalation_keeps_changed_values_but_retranslates_unchanged_body():
    frontmatter = _segment("Spreadsheet Management in Rust with Aspose.Cells FOSS")
    body = _segment("Spreadsheet Management", SegmentContextType.BODY_TEXT)

    assert SegmentTranslator._can_reuse_ast_translation(
        frontmatter, "Správa tabulek v Rustu s Aspose.Cells FOSS", "professionalize_llm"
    )
    assert not SegmentTranslator._can_reuse_ast_translation(
        body, body.source_text, "professionalize_llm"
    )
