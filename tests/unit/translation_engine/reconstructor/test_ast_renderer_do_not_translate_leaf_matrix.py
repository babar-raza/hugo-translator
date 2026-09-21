"""TD-01 (TC-APT-105 audit): reconstructor tests must assert rendered
OUTPUT CONTENT, not just a diagnostic counter.

The closest pre-existing test to TC-APT-105's real shape
(`test_list_item_with_link_text_in_unit_map_no_fallback` in
test_ast_renderer_leaf_extraction.py) has two gaps: (1) its AST shape is
one level shallower than the real bug (LIST_ITEM > LINK > TEXT, not
LIST_ITEM > STRONG > LINK > TEXT) and uses a plain TextUnitKind.TEXT unit
instead of LINK_TEXT with do_not_translate=True; (2) more importantly, its
ONLY assertions are `renderer._missing_node_count == 0` and the absence of
an "AST_FALLBACK" log line -- it never inspects `render_to_markdown()`'s
actual output. Even a test built with the exact right AST shape would not
have caught TC-APT-105 under that assertion style, because the bug lived
entirely in what gets duplicated inside the rendered string, which no
counter or log line reflects.

This file exercises `ASTRenderer.apply_translations` + `render_to_markdown`
directly (unlike the RC-01 regression test in test_segment_translator.py,
which covers the AST-reuse-map bug one layer up) across a small matrix of
container type x do_not_translate leaf count x ordinary leaf count, always
asserting the actual rendered markdown string -- proving the renderer
itself handles every combination correctly, independent of whatever
upstream mechanism populated each unit's translated_text.
"""
import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


def _node(ntype, raw, addr, children=None, attrs=None):
    n = ASTNode(type=ntype, raw=raw, children=children or [], attrs=attrs or {})
    n.node_addr = addr
    return n


def _text_node(raw, addr):
    return _node(NodeType.TEXT, raw, addr)


def _unit(addr, source, translation, *, kind=TextUnitKind.TEXT, do_not_translate=False):
    safe = addr.replace(".", "_").replace("[", "_").replace("]", "_")
    return TextUnit(
        unit_id=f"u_{safe}",
        node_addr=addr,
        kind=kind,
        source_text=source,
        translated_text=translation,
        do_not_translate=do_not_translate,
    )


def _render(root: ASTNode, units: list[TextUnit]) -> str:
    renderer = ASTRenderer()
    renderer.apply_translations([root], units)
    return renderer.render_to_markdown([root])


# ---------------------------------------------------------------------------
# LIST_ITEM matrix -- the real TC-APT-105 container shape
# (LIST_ITEM > STRONG > LINK > TEXT, plus a sibling ordinary TEXT leaf)
# ---------------------------------------------------------------------------


def _list_item_case(*, protected_text: str | None, ordinary_text: str | None):
    """Build LIST_ITEM > [STRONG > LINK > TEXT]? , [TEXT]? matching the real
    reported shape's addressing (protected leaf under strong[0].link[0].text[0],
    ordinary sibling under text[0] or text[1] depending on which is present)."""
    children = []
    units = []
    if protected_text is not None:
        addr = "body.list[0].listitem[0].strong[0].link[0].text[0]"
        leaf = _text_node(protected_text, addr)
        link = _node(NodeType.LINK, None, "body.list[0].listitem[0].strong[0].link[0]", [leaf])
        strong = _node(NodeType.STRONG, None, "body.list[0].listitem[0].strong[0]", [link])
        children.append(strong)
        units.append(
            _unit(addr, protected_text, protected_text, kind=TextUnitKind.LINK_TEXT, do_not_translate=True)
        )
    if ordinary_text is not None:
        idx = len(children)
        addr = f"body.list[0].listitem[0].text[{idx}]"
        leaf = _text_node(ordinary_text, addr)
        children.append(leaf)
        units.append(_unit(addr, ordinary_text, f"[translated] {ordinary_text}"))
    listitem = _node(NodeType.LIST_ITEM, None, "body.list[0].listitem[0]", children)
    list_node = _node(NodeType.LIST, None, "body.list[0]", [listitem])
    return list_node, units


class TestListItemOutputContentMatrix:
    def test_protected_plus_ordinary_renders_each_exactly_once(self):
        """The exact TC-APT-105 shape: protected leaf renders verbatim,
        ordinary sibling renders its own translation, neither duplicated."""
        root, units = _list_item_case(
            protected_text="API Reference", ordinary_text=": Full class docs"
        )
        output = _render(root, units)

        assert output.count("API Reference") == 1, f"protected leaf duplicated: {output!r}"
        assert output.count("[translated] : Full class docs") == 1, (
            f"ordinary sibling not rendered correctly: {output!r}"
        )
        assert "API Reference" not in output.replace("API Reference", "", 1), (
            "no second occurrence of the protected text anywhere in output"
        )

    def test_protected_only_renders_once_no_sibling(self):
        root, units = _list_item_case(protected_text="API Reference", ordinary_text=None)
        output = _render(root, units)

        assert output.count("API Reference") == 1

    def test_ordinary_only_renders_once_no_protected_sibling(self):
        root, units = _list_item_case(protected_text=None, ordinary_text="Full class docs")
        output = _render(root, units)

        assert output.count("[translated] Full class docs") == 1

    def test_two_ordinary_siblings_each_render_once(self):
        """Regression guard: a container with two ordinary leaves (no
        protected leaf at all) must render both, exactly once each --
        proving the matrix isn't accidentally only sensitive to the
        do_not_translate case."""
        addr_a = "body.list[0].listitem[0].text[0]"
        addr_b = "body.list[0].listitem[0].text[1]"
        leaf_a = _text_node("First part", addr_a)
        leaf_b = _text_node("Second part", addr_b)
        listitem = _node(NodeType.LIST_ITEM, None, "body.list[0].listitem[0]", [leaf_a, leaf_b])
        list_node = _node(NodeType.LIST, None, "body.list[0]", [listitem])
        units = [
            _unit(addr_a, "First part", "[translated] First part"),
            _unit(addr_b, "Second part", "[translated] Second part"),
        ]

        output = _render(list_node, units)

        assert output.count("[translated] First part") == 1
        assert output.count("[translated] Second part") == 1


# ---------------------------------------------------------------------------
# PARAGRAPH matrix -- same protected+ordinary combination, different
# container type, proving the assertion pattern isn't LIST_ITEM-specific.
# ---------------------------------------------------------------------------


class TestParagraphOutputContentMatrix:
    def test_protected_link_plus_ordinary_text_in_paragraph(self):
        addr_link_text = "body.paragraph[0].strong[0].link[0].text[0]"
        addr_ordinary = "body.paragraph[0].text[0]"
        protected_leaf = _text_node("Aspose.Cells", addr_link_text)
        link = _node(NodeType.LINK, None, "body.paragraph[0].strong[0].link[0]", [protected_leaf])
        strong = _node(NodeType.STRONG, None, "body.paragraph[0].strong[0]", [link])
        ordinary_leaf = _text_node(" is a library.", addr_ordinary)
        paragraph = _node(NodeType.PARAGRAPH, None, "body.paragraph[0]", [strong, ordinary_leaf])

        units = [
            _unit(addr_link_text, "Aspose.Cells", "Aspose.Cells", kind=TextUnitKind.LINK_TEXT, do_not_translate=True),
            _unit(addr_ordinary, " is a library.", " est une bibliotheque."),
        ]

        output = _render(paragraph, units)

        assert output.count("Aspose.Cells") == 1
        assert output.count(" est une bibliotheque.") == 1
