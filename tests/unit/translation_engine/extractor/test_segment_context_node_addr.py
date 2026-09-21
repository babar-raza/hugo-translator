"""
HT-QUALITY-GATES-001 AST-reuse identity fix (2026-09-10): body Segments must
carry their underlying AST node's `node_addr` so segment_translator.py's
legacy-translation reuse map can key on stable node identity instead of
re-normalized, placeholder-protected text (see segment_translator.py's
`_translate_body_ast` and tests/unit/translation_engine/test_segment_translator.py's
`TestASTReuseIdentityFix` for the end-to-end regression coverage).

This is the narrow, single-purpose test for the plumbing itself:
`SegmentContext.node_addr` must equal the exact `ASTNode.node_addr` assigned
by `ASTNode.assign_addresses()` (the same mechanism `TextUnitExtractor`
already relies on for `TextUnit.node_addr`), for every body segment kind
(paragraph, heading, list item).
"""
from unittest.mock import MagicMock

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.parser.ast_nodes import (
    heading_node,
    list_item_node,
    paragraph_node,
    text_node,
)
from src.utils.models import BodyRules


def _make_site_profile():
    profile = MagicMock()
    profile.site_id = "blog.aspose.org"
    profile.body = BodyRules(translate_markdown=True)
    profile.body.preserve_patterns = []
    profile.body.preserve_blocks = []
    profile.body.placeholder_syntax = None
    return profile


class TestBodySegmentNodeAddr:
    def test_paragraph_segment_carries_its_own_node_addr(self):
        ast = [paragraph_node([text_node("Hello world.")])]
        for i, node in enumerate(ast):
            node.assign_addresses(f"body.para[{i}]")

        extractor = SegmentExtractor(_make_site_profile())
        segments = extractor.extract_from_body(ast, "en")

        assert len(segments) == 1
        assert segments[0].context.node_addr == ast[0].node_addr == "body.para[0]"

    def test_heading_segment_carries_its_own_node_addr(self):
        ast = [heading_node(2, [text_node("Introduction")])]
        for i, node in enumerate(ast):
            node.assign_addresses(f"body.heading[{i}]")

        extractor = SegmentExtractor(_make_site_profile())
        segments = extractor.extract_from_body(ast, "en")

        assert len(segments) == 1
        assert segments[0].context.node_addr == ast[0].node_addr == "body.heading[0]"

    def test_list_item_segment_carries_its_own_node_addr(self):
        ast = [list_item_node([text_node("First bullet")])]
        for i, node in enumerate(ast):
            node.assign_addresses(f"body.listitem[{i}]")

        extractor = SegmentExtractor(_make_site_profile())
        segments = extractor.extract_from_body(ast, "en")

        assert len(segments) == 1
        assert segments[0].context.node_addr == ast[0].node_addr == "body.listitem[0]"

    def test_two_sibling_paragraphs_get_distinct_node_addrs(self):
        """The identity that makes the AST-reuse fix work: distinct nodes
        must produce distinct addresses, never colliding regardless of
        their text content."""
        ast = [
            paragraph_node([text_node("`.xlsx`")]),
            paragraph_node([text_node("[Free Support Forum](https://x.example/forum)")]),
        ]
        for i, node in enumerate(ast):
            node.assign_addresses(f"body.para[{i}]")

        extractor = SegmentExtractor(_make_site_profile())
        segments = extractor.extract_from_body(ast, "en")

        assert len(segments) == 2
        addrs = {seg.context.node_addr for seg in segments}
        assert addrs == {"body.para[0]", "body.para[1]"}
