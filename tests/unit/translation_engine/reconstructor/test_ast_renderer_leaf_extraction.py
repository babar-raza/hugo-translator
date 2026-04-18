"""
TC-MLD-06: Regression tests for AST renderer leaf-extraction false-positive suppression.

Verifies that:
- PARAGRAPH + STRONG with STRONG's TEXT in unit_map → NO AST_FALLBACK, counter stays 0
- PARAGRAPH + STRONG with NO descendant in unit_map → AST_FALLBACK fires, counter = 1
- LIST_ITEM with LINK whose TEXT is in unit_map → NO AST_FALLBACK, counter stays 0
- Mixed: some children translated, some not → only truly-missing containers counted
"""

import logging

import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(ntype: NodeType, raw: str | None, addr: str, children: list[ASTNode] | None = None) -> ASTNode:
    n = ASTNode(type=ntype, raw=raw, children=children or [], attrs={})
    n.node_addr = addr
    return n


def _text(raw: str, addr: str) -> ASTNode:
    return _node(NodeType.TEXT, raw, addr)


def _unit(addr: str, source: str, translation: str) -> TextUnit:
    safe = addr.replace(".", "_").replace("[", "_").replace("]", "_")
    return TextUnit(
        unit_id=f"u_{safe}",
        node_addr=addr,
        kind=TextUnitKind.TEXT,
        source_text=source,
        translated_text=translation,
    )


def _renderer() -> ASTRenderer:
    return ASTRenderer()


# ---------------------------------------------------------------------------
# Test 1: PARAGRAPH with inline STRONG — STRONG's TEXT is in unit_map
#         → leaf-extraction case → counter stays 0, no warning
# ---------------------------------------------------------------------------

def test_paragraph_with_strong_text_in_unit_map_no_fallback(caplog):
    """
    When the STRONG child's TEXT node is in unit_map the container is a
    leaf-extraction case; AST_FALLBACK must NOT fire and counter stays 0.
    """
    # Build AST:  PARAGRAPH[addr=body.paragraph[0]]
    #               └── STRONG[addr=body.paragraph[0].strong[0]]
    #                     └── TEXT[addr=body.paragraph[0].strong[0].text[0]]
    leaf_text = _text("Some bold content here", "body.paragraph[0].strong[0].text[0]")
    strong = _node(NodeType.STRONG, None, "body.paragraph[0].strong[0]", [leaf_text])
    para = _node(NodeType.PARAGRAPH, None, "body.paragraph[0]", [strong])

    # Only the leaf TEXT is in unit_map (leaf-extraction path)
    units = [_unit("body.paragraph[0].strong[0].text[0]", "Some bold content here", "Fettgedruckter Inhalt hier")]

    renderer = _renderer()
    with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
        renderer.apply_translations([para], units)

    assert renderer._missing_node_count == 0, (
        "Counter must stay 0 for leaf-extraction case (STRONG TEXT in unit_map)"
    )
    assert "AST_FALLBACK" not in caplog.text, (
        "No AST_FALLBACK warning expected when descendants are translated"
    )


# ---------------------------------------------------------------------------
# Test 2: PARAGRAPH with inline STRONG — NO descendant in unit_map
#         → true gap → counter = 1, warning fires
# ---------------------------------------------------------------------------

def test_paragraph_with_strong_no_descendant_in_unit_map_fires_fallback(caplog):
    """
    When neither the container nor any descendant is in unit_map it is a
    true extraction gap; AST_FALLBACK MUST fire and counter = 1.
    """
    leaf_text = _text("Some bold content here", "body.paragraph[0].strong[0].text[0]")
    strong = _node(NodeType.STRONG, None, "body.paragraph[0].strong[0]", [leaf_text])
    para = _node(NodeType.PARAGRAPH, None, "body.paragraph[0]", [strong])

    # Unit present but for a DIFFERENT address — simulates extraction gap
    units = [_unit("body.paragraph[99].text[0]", "Unrelated", "Nicht verwandt")]

    renderer = _renderer()
    with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
        renderer.apply_translations([para], units)

    assert renderer._missing_node_count == 1, (
        "Counter must be 1 when no descendant is in unit_map (true gap)"
    )
    assert "AST_FALLBACK" in caplog.text, "AST_FALLBACK warning must fire for true gap"
    assert "no descendants translated" in caplog.text


# ---------------------------------------------------------------------------
# Test 3: LIST_ITEM with LINK whose TEXT is in unit_map
#         → leaf-extraction case → counter stays 0
# ---------------------------------------------------------------------------

def test_list_item_with_link_text_in_unit_map_no_fallback(caplog):
    """
    LIST_ITEM containing a LINK where the LINK's TEXT leaf is in unit_map.
    This mirrors the extractor's behaviour for list items with hyperlinks.
    Counter must stay 0.
    """
    link_text = _text("Click here for details", "body.list[0].listitem[0].link[0].text[0]")
    link = _node(NodeType.LINK, None, "body.list[0].listitem[0].link[0]", [link_text])
    listitem = _node(NodeType.LIST_ITEM, None, "body.list[0].listitem[0]", [link])
    list_node = _node(NodeType.LIST, None, "body.list[0]", [listitem])

    units = [_unit(
        "body.list[0].listitem[0].link[0].text[0]",
        "Click here for details",
        "Hier klicken für Details",
    )]

    renderer = _renderer()
    with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
        renderer.apply_translations([list_node], units)

    assert renderer._missing_node_count == 0, (
        "Counter must stay 0 for LIST_ITEM with LINK TEXT in unit_map"
    )
    assert "AST_FALLBACK" not in caplog.text


# ---------------------------------------------------------------------------
# Test 4: Mixed paragraph — one sibling translated, one not
#         Only the truly-missing container is counted; the translated sibling is not
# ---------------------------------------------------------------------------

def test_mixed_paragraph_only_truly_missing_counted(caplog):
    """
    Two sibling PARAGRAPH nodes at the same level:
      - para[0]: STRONG with TEXT in unit_map (leaf-extraction) → NOT counted
      - para[1]: plain TEXT child that is NOT in unit_map (true gap) → counted

    Expected: counter = 1 (only para[1] is a true gap).
    """
    # para[0]: leaf-extraction case
    leaf0 = _text("Bold text content here", "body.paragraph[0].strong[0].text[0]")
    strong0 = _node(NodeType.STRONG, None, "body.paragraph[0].strong[0]", [leaf0])
    para0 = _node(NodeType.PARAGRAPH, None, "body.paragraph[0]", [strong0])

    # para[1]: plain text, nothing in unit_map → true gap
    leaf1 = _text("Plain text paragraph here", "body.paragraph[1].text[0]")
    para1 = _node(NodeType.PARAGRAPH, None, "body.paragraph[1]", [leaf1])

    units = [
        # Only para[0]'s leaf is in unit_map
        _unit("body.paragraph[0].strong[0].text[0]", "Bold text content here", "Fettgedruckter Text hier"),
        # para[1].text[0] is intentionally NOT included → true gap for para[1]
    ]

    renderer = _renderer()
    with caplog.at_level(logging.WARNING, logger="src.translation_engine.reconstructor.ast_renderer"):
        renderer.apply_translations([para0, para1], units)

    assert renderer._missing_node_count == 1, (
        "Only para[1] (true gap) should be counted; para[0] is leaf-extraction"
    )
    # Confirm the warning is for the correct node
    assert "body.paragraph[1]" in caplog.text
    assert "AST_FALLBACK" in caplog.text
