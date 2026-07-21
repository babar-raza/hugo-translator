"""TC-HT-LEGACY-LINK-001: legacy-path segment extraction must not silently
delete links or bold/italic formatting.

Root cause: SegmentExtractor._extract_text_from_children() had explicit
branches for TEXT, CODE_SPAN, SOFT_BREAK, LINE_BREAK, INLINE_HTML, but LINK,
STRONG, and EMPHASIS fell into the generic "elif child.children:" branch,
which recurses into inner text only -- discarding the URL and [...](...)
syntax for links, and the **/* markers for bold/italic, entirely. This is
still live, reachable production code: the legacy (non-AST) reconstruction
path is used whenever AST rendering throws before body rendering completes,
regardless of site profile config (segment_translator.py's fallback), not
merely a tests-only escape hatch.
"""

from src.translation_engine.extractor.segment_extractor import SegmentExtractor
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType, link_node, text_node
from src.utils.models import BodyRules


def _make_site_profile():
    from unittest.mock import MagicMock

    profile = MagicMock()
    profile.site_id = "reference.aspose.org"
    profile.body = BodyRules(translate_markdown=True)
    profile.body.preserve_patterns = []
    profile.body.preserve_blocks = []
    profile.body.placeholder_syntax = None
    return profile


def _extractor():
    return SegmentExtractor(_make_site_profile())


class TestLinkPreservedNotDeleted:
    def test_link_url_and_syntax_survive_extraction(self):
        children = [
            text_node("See the "),
            link_node(url="https://example.com/docs/x", children=[text_node("docs")]),
            text_node(" for details."),
        ]
        result = _extractor()._extract_text_from_children(children)
        assert result == "See the [docs](https://example.com/docs/x) for details."

    def test_relative_link_url_survives(self):
        children = [link_node(url="../../developer-guide/core-management/", children=[text_node("Core Management")])]
        result = _extractor()._extract_text_from_children(children)
        assert result == "[Core Management](../../developer-guide/core-management/)"

    def test_link_with_no_url_does_not_crash(self):
        """Defensive: a LINK node with attrs=None or missing url must not raise."""
        node = link_node(url="", children=[text_node("bare")])
        node.attrs = None
        result = _extractor()._extract_text_from_children([node])
        assert result == "[bare]()"


class TestBoldItalicPreservedNotStripped:
    def test_bold_markers_survive_extraction(self):
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("important")])
        children = [text_node("This is "), strong, text_node(" text.")]
        result = _extractor()._extract_text_from_children(children)
        assert result == "This is **important** text."

    def test_italic_markers_survive_extraction(self):
        emphasis = ASTNode(type=NodeType.EMPHASIS, children=[text_node("emphasized")])
        children = [text_node("This is "), emphasis, text_node(" text.")]
        result = _extractor()._extract_text_from_children(children)
        assert result == "This is *emphasized* text."


class TestPlainTextUnaffected:
    def test_plain_text_extraction_unchanged(self):
        children = [text_node("Just plain text, no formatting.")]
        result = _extractor()._extract_text_from_children(children)
        assert result == "Just plain text, no formatting."
