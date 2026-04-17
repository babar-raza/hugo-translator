"""
TC-MLD-01: Regression tests for AST renderer missing-node detection.

Verifies that:
- Nodes with an address but no matching TextUnit log AST_FALLBACK WARNING
- _missing_node_count incremented for prose nodes, not for CODE_BLOCK/INLINE_HTML
- _missing_node_count resets on each apply_translations() call
- CODE_BLOCK nodes without translation units do NOT count as missing
"""

import logging

import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import (
    ASTNode,
    NodeType,
    paragraph_node,
    text_node,
    heading_node,
)
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _para_with_addr(text_content: str, addr: str) -> ASTNode:
    """Create a paragraph node with assigned address and text child."""
    child = text_node(text_content)
    para = paragraph_node([child])
    para.node_addr = addr
    child.node_addr = f"{addr}.text[0]"
    return para


def _code_node(code_content: str, addr: str) -> ASTNode:
    """Create a code block node with address."""
    node = ASTNode(type=NodeType.CODE_BLOCK, raw=code_content, children=[], attrs={})
    node.node_addr = addr
    return node


def _unit_for(addr: str, source: str, translation: str) -> TextUnit:
    """Create a TextUnit for a given node address."""
    return TextUnit(
        unit_id=f"u_{addr.replace('.', '_').replace('[', '_').replace(']', '_')}",
        node_addr=addr,
        kind=TextUnitKind.TEXT,
        source_text=source,
        translated_text=translation,
    )


class TestMissingNodeWarning:
    """AST_FALLBACK warning and _missing_node_count counter."""

    def test_missing_node_logs_warning(self, caplog):
        """Node with address not in unit_map logs AST_FALLBACK WARNING."""
        renderer = ASTRenderer()
        para = _para_with_addr("This English text was not translated.", "body.para[0]")

        with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
            renderer.apply_translations([para], units=[])

        assert "AST_FALLBACK" in caplog.text
        assert "body.para[0]" in caplog.text

    def test_missing_node_increments_counter(self):
        """_missing_node_count is incremented for prose paragraph nodes with no unit."""
        renderer = ASTRenderer()
        para = _para_with_addr("This paragraph has no translation.", "body.para[0]")

        renderer.apply_translations([para], units=[])

        assert renderer._missing_node_count == 1

    def test_multiple_missing_nodes_counted(self):
        """Multiple missing prose nodes each increment the counter."""
        renderer = ASTRenderer()
        paras = [
            _para_with_addr("First untranslated paragraph.", f"body.para[{i}]")
            for i in range(3)
        ]

        renderer.apply_translations(paras, units=[])

        assert renderer._missing_node_count == 3

    def test_counter_resets_on_each_call(self):
        """Counter resets to 0 at the start of each apply_translations() call."""
        renderer = ASTRenderer()
        para = _para_with_addr("Untranslated content here.", "body.para[0]")

        renderer.apply_translations([para], units=[])
        assert renderer._missing_node_count == 1

        # Second call — counter should reset, not accumulate
        renderer.apply_translations([para], units=[])
        assert renderer._missing_node_count == 1, "Counter should reset, not accumulate across calls"

    def test_code_block_not_counted(self, caplog):
        """CODE_BLOCK nodes without translation units do NOT count as missing."""
        renderer = ASTRenderer()
        code = _code_node("print('hello world')", "body.code[0]")

        with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
            renderer.apply_translations([code], units=[])

        assert renderer._missing_node_count == 0
        assert "AST_FALLBACK" not in caplog.text

    def test_node_with_unit_not_counted(self):
        """Paragraph node that HAS a matching TextUnit (at paragraph level) does NOT increment counter."""
        renderer = ASTRenderer()
        # Unit maps to the PARAGRAPH address directly (the paragraph IS the translatable unit)
        para = _para_with_addr("Hello world", "body.para[0]")
        unit = _unit_for("body.para[0]", "Hello world", "Hola mundo")

        renderer.apply_translations([para], units=[unit])

        assert renderer._missing_node_count == 0

    def test_short_text_node_not_counted(self):
        """Nodes whose children have < 5 chars of text are not flagged (too short to detect)."""
        renderer = ASTRenderer()
        # Single short word — not worth flagging
        child = text_node("OK")
        para = paragraph_node([child])
        para.node_addr = "body.para[0]"
        child.node_addr = "body.para[0].text[0]"

        renderer.apply_translations([para], units=[])

        # "OK" has 2 chars < 5 threshold — should not count as missing
        assert renderer._missing_node_count == 0

    def test_error_log_on_nonzero_count(self, caplog):
        """apply_translations logs ERROR when _missing_node_count > 0."""
        renderer = ASTRenderer()
        para = _para_with_addr("Some untranslated text here.", "body.para[0]")

        with caplog.at_level(logging.ERROR, logger="src.translation_engine.reconstructor.ast_renderer"):
            renderer.apply_translations([para], units=[])

        assert any(
            "AST reconstruction" in rec.message and "no translation unit" in rec.message
            for rec in caplog.records
            if rec.levelno == logging.ERROR
        )
