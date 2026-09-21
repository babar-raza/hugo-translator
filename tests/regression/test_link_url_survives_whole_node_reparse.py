"""TC-APT-076: a link's URL must survive when its enclosing paragraph is
re-parsed from translated text.

_apply_to_node() re-parses a PARAGRAPH's translated text back into AST nodes
whenever the paragraph has inline formatting (STRONG/EMPHASIS/LINK/CODE_SPAN/
IMAGE/LINE_BREAK), via _reparse_inline_markdown() -> _parse_inline_tokens_to_ast().
That path uses markdown_it to tokenize the translated markdown and pulls the
`href` off each `link_open` token.

Root cause: markdown-it-py 4.x's `Token.attrs` is a dict (hugo_parser.py's own
`_get_attr()` already handles this dual-format case). _parse_inline_tokens_to_ast
iterated it as a list of (key, value) tuples instead: `for attr in token.attrs`
over a dict yields its KEYS (plain strings), so `attr[0]` was the first
CHARACTER of "href", never equal to the string "href" -- the url was always "".
Reproduced directly against the installed markdown-it-py 4.0.0 before this fix:
a whole-node paragraph "In the [introduction post](url), we covered great new
features." rendered as "In the [introduction post](), we covered ...".

This was invisible to every existing unit test because link-bearing paragraphs
have always been leaf-split by a separate, independent gate
(_has_technical_content in text_unit_extractor.py), so this reparse path's LINK
branch was never exercised in production. TC-APT-076 is the plan to remove
that gate now that this is fixed; do not remove it without re-running an
identity round-trip proof across real pages first (plan card, evidence_path
data/summaries/fp-tc-apt-076-falsified-20260905.json).
"""

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _paragraph_with_link():
    link = ASTNode(
        type=NodeType.LINK,
        children=[
            ASTNode(
                type=NodeType.TEXT,
                raw="introduction post",
                children=[],
                attrs={},
                node_addr="body.paragraph[0].link[0].text[0]",
            )
        ],
        attrs={"url": "/blog/3d/java/introducing-3d-foss-java/"},
        node_addr="body.paragraph[0].link[0]",
    )
    before = ASTNode(
        type=NodeType.TEXT,
        raw="In the ",
        children=[],
        attrs={},
        node_addr="body.paragraph[0].text[0]",
    )
    after = ASTNode(
        type=NodeType.TEXT,
        raw=", we covered great new features.",
        children=[],
        attrs={},
        node_addr="body.paragraph[0].text[1]",
    )
    return ASTNode(
        type=NodeType.PARAGRAPH,
        children=[before, link, after],
        attrs={},
        node_addr="body.paragraph[0]",
    )


def test_link_url_survives_identity_translation_of_a_whole_node_paragraph():
    paragraph = _paragraph_with_link()
    source_text = "In the [introduction post{PLACEHOLDER_0}, we covered great new features."
    placeholder_map = {"{PLACEHOLDER_0}": "](/blog/3d/java/introducing-3d-foss-java/)"}

    unit = TextUnit(unit_id="u1", node_addr="body.paragraph[0]", source_text=source_text, kind=TextUnitKind.TEXT)
    unit.translated_text = source_text  # identity: proves round-trip neutrality
    unit.metadata = {"placeholder_map": placeholder_map}

    renderer = ASTRenderer()
    renderer.unit_map = {"body.paragraph[0]": unit}
    renderer._apply_to_node(paragraph)
    rendered = renderer._render_node(paragraph)

    assert rendered == (
        "In the [introduction post](/blog/3d/java/introducing-3d-foss-java/), "
        "we covered great new features.\n\n"
    )


def test_parse_inline_tokens_to_ast_extracts_url_from_dict_attrs():
    """Pins the exact mechanism, independent of the paragraph-level plumbing above."""
    renderer = ASTRenderer()
    nodes = renderer._reparse_inline_markdown(
        "See [the docs](https://example.invalid/path) for more.", "addr"
    )
    link_nodes = [n for n in nodes if n.type == NodeType.LINK]
    assert len(link_nodes) == 1
    assert link_nodes[0].attrs["url"] == "https://example.invalid/path"
