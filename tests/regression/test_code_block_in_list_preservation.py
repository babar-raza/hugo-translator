"""
Regression tests for code block preservation inside list items.

Bug fixes covered:
  Bug 1 — hugo_parser.py: _parse_list_item() silently dropped fence/code_block tokens
           (else: i += 1 skipped them without creating AST nodes)
  Bug 2 — text_unit_extractor.py: _collect_text_from_node() had no CODE_BLOCK handler;
           fell through to default recursion over empty children → returned ""
  Bug 3 — text_unit_extractor.py: _has_inline_formatting() didn't include CODE_BLOCK,
           so sentence_only strategy wouldn't fall back to leaf extraction
  Bug 4 — ast_renderer.py: apply_translations() flattening destroyed CODE_BLOCK children
           when a container had a TextUnit in unit_map
"""

import os
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).parent.parent.parent
sys.path.insert(0, str(REPO_ROOT))
os.chdir(str(REPO_ROOT))

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser.ast_nodes import ASTNode, NodeType
from src.translation_engine.parser.hugo_parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def find_nodes(nodes, target_type):
    """Recursively find all nodes of a given type."""
    result = []
    for node in nodes:
        if node.type == target_type:
            result.append(node)
        result.extend(find_nodes(node.children, target_type))
    return result


def make_parser():
    return HugoParser()


def make_extractor(strategy="adaptive"):
    return TextUnitExtractor(segmentation_strategy=strategy)


# ---------------------------------------------------------------------------
# Bug 1: Parser preserves code blocks inside list items
# ---------------------------------------------------------------------------

class TestParserCodeBlockInListItem:

    def test_fenced_code_block_inside_list_item_is_parsed(self):
        """Bug 1: fence token inside list item must produce a CODE_BLOCK AST node."""
        md = """\
- Description of the method

  ```python
  def hello():
      print("world")
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        code_blocks = find_nodes(doc.ast, NodeType.CODE_BLOCK)
        assert len(code_blocks) == 1, (
            "Expected 1 CODE_BLOCK node; parser silently dropped the code block"
        )
        assert "def hello" in code_blocks[0].raw

    def test_code_block_language_preserved(self):
        """Bug 1: language hint (info string) must be preserved on the CODE_BLOCK node."""
        md = """\
- Example

  ```csharp
  var x = new Object();
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        code_blocks = find_nodes(doc.ast, NodeType.CODE_BLOCK)
        assert len(code_blocks) == 1
        lang = code_blocks[0].attrs.get("lang", "") if code_blocks[0].attrs else ""
        assert lang == "csharp", f"Expected lang='csharp', got '{lang}'"

    def test_multiple_code_blocks_in_different_list_items(self):
        """Bug 1: each list item with a code block must produce its own CODE_BLOCK node."""
        md = """\
- First item

  ```python
  code_a()
  ```

- Second item

  ```java
  System.out.println("b");
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        code_blocks = find_nodes(doc.ast, NodeType.CODE_BLOCK)
        assert len(code_blocks) == 2, (
            f"Expected 2 CODE_BLOCK nodes, got {len(code_blocks)}"
        )

    def test_code_block_and_text_both_preserved_in_list_item(self):
        """Bug 1: a list item with text AND a code block must have both as children."""
        md = """\
- Use SaveAs to save:

  ```csharp
  doc.SaveAs("output.docx");
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        list_items = find_nodes(doc.ast, NodeType.LIST_ITEM)
        assert len(list_items) == 1
        item = list_items[0]
        # Must have at least one text/inline child AND one CODE_BLOCK child
        code_blocks = find_nodes([item], NodeType.CODE_BLOCK)
        assert len(code_blocks) == 1, "CODE_BLOCK missing from LIST_ITEM children"
        assert "SaveAs" in code_blocks[0].raw

    def test_indented_code_block_in_list_item(self):
        """Bug 1: 4-space indented code block (code_block token) inside list item."""
        # Note: markdown-it with commonmark preset may or may not produce a code_block
        # token for this structure. We test that parsing doesn't crash.
        md = """\
- Item with indented code

        result = compute()
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        # Should parse without error; structure may vary
        assert doc is not None


# ---------------------------------------------------------------------------
# Bug 2 & 3: Extractor preserves code blocks in sentence_only mode
# ---------------------------------------------------------------------------

class TestExtractorCodeBlockPreservation:

    def test_has_inline_formatting_does_not_detect_code_block(self):
        """TC-02: _has_inline_formatting() must return False for a CODE_BLOCK child.
        CODE_BLOCK is block-level content, not inline formatting.
        Use _has_block_content() to detect it instead.
        """
        extractor = make_extractor(strategy="sentence_only")
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="x = 1",
            children=[],
            attrs={"lang": "python"},
            node_id="cb1",
        )
        container = ASTNode(
            type=NodeType.LIST_ITEM,
            children=[code_block],
            node_id="li1",
        )
        assert not extractor._has_inline_formatting(container), (
            "TC-02: _has_inline_formatting() must return False for CODE_BLOCK child "
            "(code block is block-level, not inline formatting)"
        )

    def test_has_block_content_detects_code_block_child(self):
        """TC-02: _has_block_content() must return True when a CODE_BLOCK child is present."""
        extractor = make_extractor(strategy="sentence_only")
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="x = 1",
            children=[],
            attrs={"lang": "python"},
            node_id="cb1",
        )
        container = ASTNode(
            type=NodeType.LIST_ITEM,
            children=[code_block],
            node_id="li1",
        )
        assert extractor._has_block_content(container), (
            "TC-02: _has_block_content() must return True when CODE_BLOCK child is present"
        )

    def test_has_block_content_false_for_inline_only(self):
        """TC-02: _has_block_content() must return False when only inline nodes are present."""
        extractor = make_extractor()
        text_node = ASTNode(type=NodeType.TEXT, raw="hello", children=[], node_id="t1")
        strong_node = ASTNode(type=NodeType.STRONG, children=[text_node], node_id="s1")
        container = ASTNode(type=NodeType.PARAGRAPH, children=[strong_node], node_id="p1")
        assert not extractor._has_block_content(container), (
            "TC-02: _has_block_content() must return False for inline-only children"
        )

    def test_sentence_only_falls_back_when_code_block_child(self):
        """TC-02: _should_extract_full_sentence() must return False for sentence_only
        when the node has a CODE_BLOCK child (via _has_block_content()).
        """
        extractor = make_extractor(strategy="sentence_only")
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="x = 1",
            children=[],
            attrs={"lang": "python"},
            node_id="cb1",
        )
        container = ASTNode(
            type=NodeType.PARAGRAPH,
            children=[code_block],
            node_id="p1",
            node_addr="body.p[0]",
        )
        assert not extractor._should_extract_full_sentence(container), (
            "TC-02: sentence_only must fall back to leaf extraction when CODE_BLOCK child present"
        )

    def test_collect_text_from_node_includes_code_block(self):
        """Bug 2: _collect_text_from_node() must return the fenced block, not empty string."""
        extractor = make_extractor(strategy="sentence_only")
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="def hello():\n    pass",
            children=[],
            attrs={"lang": "python"},
            node_id="cb1",
        )
        result = extractor._collect_text_from_node(code_block)
        assert "def hello" in result, (
            f"CODE_BLOCK content must appear in collected text, got: {result!r}"
        )
        assert "```" in result, "Fenced block markers must be present"

    def test_code_block_unit_is_do_not_translate(self):
        """Code blocks extracted from a list item must be marked do_not_translate=True."""
        md = """\
- Example:

  ```python
  print("hello")
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        extractor = make_extractor(strategy="adaptive")
        # Parser assigns node addresses automatically via assign_addresses()
        plan = extractor.extract_from_ast(doc.ast)

        code_units = [u for u in plan.units if u.kind == TextUnitKind.CODE_SPAN]
        assert len(code_units) >= 1, "Expected at least one code TextUnit"
        for u in code_units:
            assert u.do_not_translate, f"Code unit must be do_not_translate=True: {u}"

    def test_sentence_only_does_not_lose_code_block(self):
        """Bug 2+3: sentence_only extraction on list item with code block must preserve code."""
        md = """\
- Call the method:

  ```csharp
  doc.Save("file.docx");
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        extractor = make_extractor(strategy="sentence_only")
        # Parser assigns node addresses automatically via assign_addresses()
        plan = extractor.extract_from_ast(doc.ast)

        # The code block content must appear in at least one unit's source_text
        all_source = " ".join(u.source_text or "" for u in plan.units)
        assert "doc.Save" in all_source, (
            "Code block content lost during sentence_only extraction"
        )


# ---------------------------------------------------------------------------
# Bug 4: Reconstruction preserves CODE_BLOCK children
# ---------------------------------------------------------------------------

class TestReconstructorCodeBlockPreservation:

    def setup_method(self):
        self.renderer = ASTRenderer()

    def _make_code_block_node(self, code, lang="python", node_id="cb1"):
        return ASTNode(
            type=NodeType.CODE_BLOCK,
            raw=code,
            children=[],
            attrs={"lang": lang},
            node_id=node_id,
            node_addr=f"body.list[0].item[0].{node_id}",
        )

    def _make_text_node(self, text, node_id="t1", addr="body.list[0].item[0].t1"):
        return ASTNode(
            type=NodeType.TEXT,
            raw=text,
            children=[],
            attrs={},
            node_id=node_id,
            node_addr=addr,
        )

    def test_list_item_with_code_block_not_flattened(self):
        """Bug 4: apply_translations must not destroy CODE_BLOCK children of a LIST_ITEM."""
        code_block = self._make_code_block_node("x = 1\n")
        text_node = self._make_text_node("Call the method:", addr="body.list[0].item[0].t1")

        list_item = ASTNode(
            type=NodeType.LIST_ITEM,
            children=[text_node, code_block],
            node_id="li1",
            node_addr="body.list[0].item[0]",
        )

        # Create a TextUnit for the LIST_ITEM as if full-sentence extraction was used
        li_unit = TextUnit(
            unit_id="u1",
            node_addr="body.list[0].item[0]",
            kind=TextUnitKind.LIST_ITEM_TEXT,
            source_text="Call the method:",
            do_not_translate=False,
        )
        li_unit.translated_text = "Appeler la méthode:"

        # Create a TextUnit for the code block (do_not_translate)
        cb_unit = TextUnit(
            unit_id="u2",
            node_addr="body.list[0].item[0].cb1",
            kind=TextUnitKind.CODE_SPAN,
            source_text="x = 1\n",
            do_not_translate=True,
        )

        self.renderer.apply_translations([list_item], [li_unit, cb_unit])

        # The CODE_BLOCK child must still be present
        code_blocks_after = find_nodes([list_item], NodeType.CODE_BLOCK)
        assert len(code_blocks_after) == 1, (
            "CODE_BLOCK child was destroyed by apply_translations() flattening"
        )
        assert "x = 1" in code_blocks_after[0].raw

    def test_paragraph_with_code_block_not_flattened(self):
        """Bug 4: CODE_BLOCK child of PARAGRAPH must survive apply_translations()."""
        code_block = self._make_code_block_node("result = 42\n", node_id="cb2")
        code_block.node_addr = "body.p[0].cb2"

        text_node = self._make_text_node("Example:", addr="body.p[0].t1")

        paragraph = ASTNode(
            type=NodeType.PARAGRAPH,
            children=[text_node, code_block],
            node_id="p1",
            node_addr="body.p[0]",
        )

        para_unit = TextUnit(
            unit_id="pu1",
            node_addr="body.p[0]",
            kind=TextUnitKind.TEXT,
            source_text="Example:",
            do_not_translate=False,
        )
        para_unit.translated_text = "Exemple:"

        cb_unit = TextUnit(
            unit_id="pu2",
            node_addr="body.p[0].cb2",
            kind=TextUnitKind.CODE_SPAN,
            source_text="result = 42\n",
            do_not_translate=True,
        )

        self.renderer.apply_translations([paragraph], [para_unit, cb_unit])

        code_blocks_after = find_nodes([paragraph], NodeType.CODE_BLOCK)
        assert len(code_blocks_after) == 1, (
            "CODE_BLOCK child was destroyed by PARAGRAPH flattening"
        )
        assert "42" in code_blocks_after[0].raw


# ---------------------------------------------------------------------------
# End-to-end: parse → extract → render (no translation)
# ---------------------------------------------------------------------------

class TestEndToEndCodeBlockInList:

    def test_round_trip_code_block_in_list_item(self):
        """End-to-end: code block inside list item survives parse → render unchanged."""
        md = """\
- Description:

  ```python
  def greet(name):
      return f"Hello, {name}"
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)

        renderer = ASTRenderer()
        # No translations applied — just render as-is
        output = renderer.render_to_markdown(doc.ast)

        assert "def greet" in output, "Code content lost in round-trip render"
        assert "```python" in output, "Fenced block markers lost in render"

    def test_round_trip_multiple_list_items_with_code(self):
        """End-to-end: multiple list items each with code blocks all survive."""
        md = """\
- First method:

  ```csharp
  doc.Save();
  ```

- Second method:

  ```csharp
  doc.Load("file.docx");
  ```
"""
        parser = make_parser()
        doc = parser.parse_string(md)
        renderer = ASTRenderer()
        output = renderer.render_to_markdown(doc.ast)

        assert "doc.Save" in output
        assert "doc.Load" in output
        assert output.count("```csharp") == 2


# ---------------------------------------------------------------------------
# TC-05: Bug 2 test isolation — _collect_text_from_node() tested independently
# ---------------------------------------------------------------------------

class TestBug2Isolation:

    def test_collect_text_code_block_direct_not_empty(self):
        """TC-05/Bug 2: _collect_text_from_node(CODE_BLOCK) must not return empty string.
        This test directly exercises the Bug 2 fix path (independent of Bug 3 guard).
        If Bug 2 fix is reverted, this test fails.
        """
        extractor = make_extractor()
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="x = 42",
            children=[],
            attrs={"lang": "python"},
            node_id="cb1",
        )
        result = extractor._collect_text_from_node(code_block)
        assert result != "", (
            "Bug 2 regression: _collect_text_from_node(CODE_BLOCK) returned empty string"
        )
        assert "x = 42" in result

    def test_collect_text_container_with_code_block_child_includes_content(self):
        """TC-05/Bug 2: _collect_text_from_node() on a container with CODE_BLOCK child
        must include the fenced block content — tests the full-sentence collection path.
        """
        extractor = make_extractor()
        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="result = compute(x)",
            children=[],
            attrs={"lang": "python"},
            node_id="cb1",
        )
        text_node = ASTNode(
            type=NodeType.TEXT,
            raw="Example output:",
            children=[],
            node_id="t1",
        )
        paragraph = ASTNode(
            type=NodeType.PARAGRAPH,
            children=[text_node, code_block],
            node_id="p1",
        )
        collected = extractor._collect_text_from_node(paragraph)
        assert "result = compute" in collected, (
            f"Bug 2: CODE_BLOCK content missing from container collection; got: {collected!r}"
        )
        assert "```" in collected, f"Bug 2: Fenced markers missing; got: {collected!r}"
        assert "Example output" in collected, (
            f"Bug 2: TEXT sibling missing from collection; got: {collected!r}"
        )


# ---------------------------------------------------------------------------
# TC-07: Trailing-newline format consistency
# ---------------------------------------------------------------------------

class TestTrailingNewline:

    def test_collect_text_code_block_has_trailing_newlines(self):
        """TC-07: _collect_text_from_node(CODE_BLOCK) must end with \\n\\n to match renderer."""
        extractor = make_extractor()
        node = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="x=1",
            attrs={"lang": "py"},
            children=[],
            node_id="cb1",
        )
        result = extractor._collect_text_from_node(node)
        assert result.endswith("\n\n"), (
            f"TC-07: Expected trailing \\n\\n, got: {result!r}"
        )
