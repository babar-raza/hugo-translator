"""
TC-AST-03: Regression tests for ancestor-aware missing-node counting in ASTRenderer.

Verifies that STRONG/EMPHASIS nodes inside a Path A full-sentence PARAGRAPH unit
are NOT counted as missing-node gaps, because their content is covered by the
ancestor PARAGRAPH's translation.

Tests:
1. STRONG inside Path A PARAGRAPH -> _missing_node_count == 0
2. STRONG with no ancestor coverage -> _missing_node_count == 1
3. EMPHASIS inside Path A PARAGRAPH -> _missing_node_count == 0
4. Nested PARAGRAPH -> STRONG -> EMPHASIS, all suppressed by ancestor flag
5. Regression: Path B leaf-extraction still suppressed by _has_descendant_in_unit_map

Relates to: plans/healing/AUDIT-20260418-AST-translation-quality.md TC-AST-03
Root cause: barcode/add-barcode-in-asp-dotnet-mvc showed 112 false-positive
STRONG nodes (39.3% of total) because _has_descendant_in_unit_map is
descendant-oriented only; Path A ancestor coverage was not checked.
"""
from __future__ import annotations

import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _node(ntype: NodeType, raw: str | None, addr: str,
          children: list[ASTNode] | None = None) -> ASTNode:
    n = ASTNode(type=ntype, raw=raw, children=children or [], attrs={})
    n.node_addr = addr
    return n


def _text(raw: str, addr: str = "") -> ASTNode:
    """TEXT node. addr='' means no address -- typical for TEXT inside STRONG."""
    n = ASTNode(type=NodeType.TEXT, raw=raw, children=[], attrs={})
    n.node_addr = addr
    return n


def _unit(addr: str, source: str, translation: str = "translated") -> TextUnit:
    safe = addr.replace(".", "_").replace("[", "_").replace("]", "_")
    return TextUnit(
        unit_id=f"u_{safe}",
        node_addr=addr,
        kind=TextUnitKind.TEXT,
        source_text=source,
        translated_text=translation,
    )


def _apply(units: list[TextUnit], ast: list[ASTNode]) -> ASTRenderer:
    """Run apply_translations and return the renderer for inspection."""
    r = ASTRenderer()
    r.apply_translations(ast, units)
    return r


# ---------------------------------------------------------------------------
# Test 1 -- STRONG inside Path A PARAGRAPH not counted as gap
# ---------------------------------------------------------------------------

def test_strong_inside_path_a_paragraph_not_counted_as_gap():
    """
    Path A: PARAGRAPH has a TextUnit (full-sentence extraction).
    STRONG child has no TextUnit -- but ancestor PARAGRAPH IS in unit_map.
    Expected: _missing_node_count == 0.
    """
    strong_text = _text("some bold text")
    strong = _node(NodeType.STRONG, None, "body.paragraph[0].strong[0]",
                   children=[strong_text])
    para = _node(NodeType.PARAGRAPH, "some bold text paragraph sentence",
                 "body.paragraph[0]", children=[strong])

    units = [_unit("body.paragraph[0]", "some bold text paragraph sentence")]
    r = _apply(units, [para])

    assert r._missing_node_count == 0, (
        f"Expected 0 missing nodes (STRONG is inside a Path A PARAGRAPH in unit_map), "
        f"got {r._missing_node_count}"
    )


# ---------------------------------------------------------------------------
# Test 2 -- STRONG with NO ancestor coverage IS counted
# ---------------------------------------------------------------------------

def test_strong_without_ancestor_coverage_counted_as_gap():
    """
    STRONG has no TextUnit AND its parent PARAGRAPH also has no address.
    STRONG has a prose TEXT child (> 5 chars) -> true gap.
    Expected: _missing_node_count == 1.
    """
    strong_text = _text("some bold text")
    strong = _node(NodeType.STRONG, None, "body.paragraph[1].strong[0]",
                   children=[strong_text])
    # PARAGRAPH with no address -- will not be in unit_map
    para = ASTNode(type=NodeType.PARAGRAPH, raw=None, children=[strong], attrs={})
    para.node_addr = ""

    # No units -- STRONG is uncovered with no ancestor coverage
    units: list[TextUnit] = []
    r = _apply(units, [para])

    assert r._missing_node_count == 1, (
        f"Expected 1 missing node (STRONG has no ancestor in unit_map), "
        f"got {r._missing_node_count}"
    )


# ---------------------------------------------------------------------------
# Test 3 -- EMPHASIS inside Path A PARAGRAPH not counted
# ---------------------------------------------------------------------------

def test_emphasis_inside_path_a_paragraph_not_counted():
    """
    Same as test 1 but with EMPHASIS (italic) instead of STRONG.
    """
    em_text = _text("italic text here")
    em = _node(NodeType.EMPHASIS, None, "body.paragraph[2].emphasis[0]",
               children=[em_text])
    para = _node(NodeType.PARAGRAPH, "italic text here in a sentence",
                 "body.paragraph[2]", children=[em])

    units = [_unit("body.paragraph[2]", "italic text here in a sentence")]
    r = _apply(units, [para])

    assert r._missing_node_count == 0, (
        f"EMPHASIS inside Path A PARAGRAPH should not be counted as a gap, "
        f"got {r._missing_node_count}"
    )


# ---------------------------------------------------------------------------
# Test 4 -- Nested PARAGRAPH -> STRONG -> EMPHASIS all suppressed
# ---------------------------------------------------------------------------

def test_nested_formatting_inside_covered_paragraph():
    """
    PARAGRAPH (in unit_map) -> STRONG (not in unit_map) -> EMPHASIS (not in unit_map).
    The ancestor_in_unit_map flag must propagate through STRONG to EMPHASIS.
    Expected: _missing_node_count == 0 for both STRONG and EMPHASIS.
    """
    em_text = _text("nested italic")
    em = _node(NodeType.EMPHASIS, None, "body.paragraph[3].strong[0].emphasis[0]",
               children=[em_text])
    strong = _node(NodeType.STRONG, None, "body.paragraph[3].strong[0]",
                   children=[em])
    para = _node(NodeType.PARAGRAPH, "nested bold italic sentence here",
                 "body.paragraph[3]", children=[strong])

    units = [_unit("body.paragraph[3]", "nested bold italic sentence here")]
    r = _apply(units, [para])

    assert r._missing_node_count == 0, (
        f"Neither STRONG nor EMPHASIS should be counted as gaps when ancestor PARAGRAPH "
        f"is in unit_map, got {r._missing_node_count}"
    )


# ---------------------------------------------------------------------------
# Test 5 -- Path B leaf-extraction still suppressed by descendant check (TC-MLD-06)
# ---------------------------------------------------------------------------

def test_path_b_leaf_extraction_still_suppressed():
    """
    TC-MLD-06 regression: PATH B container (not in unit_map, TEXT children ARE in
    unit_map) must still be suppressed by _has_descendant_in_unit_map -- even with
    the new ancestor_in_unit_map flag added by TC-AST-03.

    STRONG NOT in unit_map.
    TEXT leaf IS in unit_map (Path B -- TEXT has its own address).
    Expected: _missing_node_count == 0 (leaf-extraction suppresses the STRONG).
    """
    text_leaf = _text("leaf text long enough here")
    text_leaf.node_addr = "body.paragraph[4].strong[0].text[0]"
    strong = _node(NodeType.STRONG, None, "body.paragraph[4].strong[0]",
                   children=[text_leaf])
    para = _node(NodeType.PARAGRAPH, None, "body.paragraph[4]",
                 children=[strong])

    # Only the TEXT leaf is in unit_map, not STRONG or PARAGRAPH
    units = [_unit("body.paragraph[4].strong[0].text[0]", "leaf text long enough here")]
    r = _apply(units, [para])

    assert r._missing_node_count == 0, (
        f"Path B leaf-extraction STRONG should not be counted as a gap "
        f"(_has_descendant_in_unit_map should suppress it), got {r._missing_node_count}"
    )


# ---------------------------------------------------------------------------
# Test 6 -- Mixed: one covered PARAGRAPH, one uncovered PARAGRAPH in same AST
# ---------------------------------------------------------------------------

def test_mixed_covered_and_uncovered_paragraphs():
    """
    Two PARAGRAPHs in the same AST:
      - PARAGRAPH[5]: in unit_map (Path A). Its STRONG child is suppressed by ancestor flag.
      - PARAGRAPH[6]: NOT in unit_map. Its STRONG child has prose > 5 chars — TRUE gap.

    Expected: _missing_node_count == 1 (only the uncovered STRONG counts).

    This validates that tolerance 0.0 is safe: covered nodes are not inflating
    the count, while real gaps are still detected.
    """
    # Covered paragraph (Path A)
    strong_covered = _node(NodeType.STRONG, None,
                           "body.paragraph[5].strong[0]",
                           children=[_text("covered bold text")])
    para_covered = _node(NodeType.PARAGRAPH, "covered bold text sentence",
                         "body.paragraph[5]", children=[strong_covered])

    # Uncovered paragraph — no unit, STRONG child is a true gap
    strong_uncovered = _node(NodeType.STRONG, None,
                             "body.paragraph[6].strong[0]",
                             children=[_text("uncovered bold text")])
    para_uncovered = ASTNode(type=NodeType.PARAGRAPH, raw=None,
                             children=[strong_uncovered], attrs={})
    para_uncovered.node_addr = ""  # not addressable → not in unit_map

    units = [_unit("body.paragraph[5]", "covered bold text sentence")]
    r = _apply(units, [para_covered, para_uncovered])

    assert r._missing_node_count == 1, (
        f"Expected exactly 1 missing node (the STRONG in the uncovered PARAGRAPH), "
        f"got {r._missing_node_count}"
    )
