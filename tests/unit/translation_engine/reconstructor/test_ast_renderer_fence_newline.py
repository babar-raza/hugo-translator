"""
TC-HT-004: idempotent fence-closing-newline handling + widened block-level
child preservation during paragraph flatten/reparse.
"""
from __future__ import annotations

import pytest

from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer
from src.translation_engine.reconstructor.markdown_reconstructor import MarkdownReconstructor


class TestAstRendererFenceIdempotent:
    """ASTRenderer.CODE_BLOCK rendering must not introduce a spurious blank
    line when the source code already ends with a newline."""

    def test_code_without_trailing_newline_gets_one(self):
        renderer = ASTRenderer()
        code_block = ASTNode(type=NodeType.CODE_BLOCK, raw="print(1)", attrs={"lang": "python"})
        code_block.assign_addresses("body.codeblock[0]")
        markdown = renderer.render_to_markdown([code_block])
        assert "```python\nprint(1)\n```" in markdown
        # No spurious double-blank-line before the closing fence.
        assert "\n\n```" not in markdown.split("print(1)")[1][:5]

    def test_code_with_trailing_newline_not_doubled(self):
        """The common case (code already ends in \\n) must not gain a
        spurious blank line before the closing fence."""
        renderer = ASTRenderer()
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK, raw="print(1)\nprint(2)\n", attrs={"lang": "python"}
        )
        code_block.assign_addresses("body.codeblock[0]")
        markdown = renderer.render_to_markdown([code_block])
        assert "print(2)\n```" in markdown
        assert "print(2)\n\n```" not in markdown  # no spurious blank line


class TestMarkdownReconstructorFenceIdempotent:
    def test_code_without_trailing_newline_gets_one(self):
        reconstructor = MarkdownReconstructor.__new__(MarkdownReconstructor)
        node = ASTNode(type=NodeType.CODE_BLOCK, raw="print(1)", attrs={"lang": "python"})
        result = reconstructor._reconstruct_node(node, {})
        assert result == "```python\nprint(1)\n```"

    def test_code_with_trailing_newline_not_doubled(self):
        reconstructor = MarkdownReconstructor.__new__(MarkdownReconstructor)
        node = ASTNode(
            type=NodeType.CODE_BLOCK, raw="print(1)\nprint(2)\n", attrs={"lang": "python"}
        )
        result = reconstructor._reconstruct_node(node, {})
        assert result == "```python\nprint(1)\nprint(2)\n```"
        assert "\n\n```" not in result  # no spurious blank line


class TestBlockLevelChildPreservation:
    """Paragraph flatten/reparse must preserve ALL block-level children, not
    just CODE_BLOCK/LIST (TC-HT-004 widens the filter)."""

    def test_blockquote_survives_flatten(self):
        from src.translation_engine.reconstructor.ast_renderer import _BLOCK_LEVEL_TYPES

        assert NodeType.BLOCKQUOTE in _BLOCK_LEVEL_TYPES
        assert NodeType.TABLE in _BLOCK_LEVEL_TYPES
        assert NodeType.THEMATIC_BREAK in _BLOCK_LEVEL_TYPES
        assert NodeType.CODE_BLOCK in _BLOCK_LEVEL_TYPES
        assert NodeType.LIST in _BLOCK_LEVEL_TYPES
