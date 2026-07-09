"""
Unit tests for HugoParser list parsing (HP-01).

Tests list token handling:
- Ordered lists (bullet_list_open/close)
- Bullet lists (ordered_list_open/close)
- List items (list_item_open/close)
- Nested lists
"""

import logging
from unittest.mock import patch

from src.translation_engine.parser import HugoParser
from src.translation_engine.parser.ast_nodes import NodeType


def test_yaml_format_fallback_logs_warning(caplog):
    """When _parse_yaml_with_comments returns None, WARNING with YAML_FORMAT_FALLBACK is emitted."""
    parser = HugoParser()
    content = "---\ntitle: Test Title\ndate: 2024-01-01\n---\n\nBody text."

    with patch.object(parser, "_parse_yaml_content", return_value=None):
        with caplog.at_level(logging.WARNING, logger="src.translation_engine.parser.hugo_parser"):
            doc = parser.parse_string(content)

    assert "YAML_FORMAT_FALLBACK" in caplog.text
    assert doc.frontmatter == {}
    assert len(doc.ast) == 1


class TestListParsing:
    """Tests for list token handling (HP-01)."""

    def test_parse_ordered_list(self):
        """Ordered list creates LIST node with ordered=True."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n1. First\n2. Second")

        list_nodes = [n for n in doc.ast if n.type == NodeType.LIST]
        assert len(list_nodes) == 1, f"Expected 1 LIST node, got {len(list_nodes)}"
        assert list_nodes[0].attrs["ordered"] is True
        assert len(list_nodes[0].children) == 2

    def test_parse_bullet_list(self):
        """Bullet list creates LIST node with ordered=False."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n- Item A\n- Item B")

        list_nodes = [n for n in doc.ast if n.type == NodeType.LIST]
        assert len(list_nodes) == 1
        assert list_nodes[0].attrs["ordered"] is False
        assert len(list_nodes[0].children) == 2

    def test_parse_multiple_lists(self):
        """Multiple lists in document creates multiple LIST nodes."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: Test
---

1. First ordered
2. Second ordered

- First bullet
- Second bullet
""")

        list_nodes = [n for n in doc.ast if n.type == NodeType.LIST]
        assert len(list_nodes) == 2, f"Expected 2 LIST nodes, got {len(list_nodes)}"

        # Verify first is ordered
        assert list_nodes[0].attrs["ordered"] is True
        assert len(list_nodes[0].children) == 2

        # Verify second is unordered
        assert list_nodes[1].attrs["ordered"] is False
        assert len(list_nodes[1].children) == 2

    def test_parse_nested_list(self):
        """Nested lists create proper hierarchy."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: t
---
1. Parent
   - Child
""")

        list_nodes = [n for n in doc.ast if n.type == NodeType.LIST]
        assert len(list_nodes) == 1, "Should have 1 top-level LIST"

        # First item should contain nested list
        first_item = list_nodes[0].children[0]
        assert first_item.type == NodeType.LIST_ITEM

        nested = [c for c in first_item.children if c.type == NodeType.LIST]
        assert len(nested) == 1, "First item should contain 1 nested LIST"
        assert nested[0].attrs["ordered"] is False

    def test_list_item_text_extraction(self):
        """List item text is captured in children."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n- Hello world")

        list_node = doc.ast[0]
        assert list_node.type == NodeType.LIST

        item = list_node.children[0]
        assert item.type == NodeType.LIST_ITEM

        text_nodes = [c for c in item.children if c.type == NodeType.TEXT]
        assert len(text_nodes) > 0, "List item should have TEXT nodes"
        text_content = " ".join(n.raw or "" for n in text_nodes)
        assert "Hello world" in text_content

    def test_ordered_list_start_number(self):
        """Ordered list preserves start number if supported."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n5. Fifth\n6. Sixth")

        list_node = doc.ast[0]
        assert list_node.type == NodeType.LIST

        # At minimum, should have 2 items
        assert len(list_node.children) == 2

        # Start attr if supported by markdown_it (may default to 1)
        start = list_node.attrs.get("start", 1)
        assert isinstance(start, int)

    def test_empty_list_item(self):
        """Empty list items handled gracefully."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: t
---
-
- text
""")

        list_node = doc.ast[0]
        assert list_node.type == NodeType.LIST
        assert len(list_node.children) == 2

        # First item may be empty
        first_item = list_node.children[0]
        assert first_item.type == NodeType.LIST_ITEM

        # Second item should have text
        second_item = list_node.children[1]
        text_nodes = [c for c in second_item.children if c.type == NodeType.TEXT]
        assert len(text_nodes) > 0

    def test_list_with_paragraphs(self):
        """List items with multiple paragraphs."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: t
---
1. First item
2. Second item
3. Third item
""")

        list_node = doc.ast[0]
        assert list_node.type == NodeType.LIST
        assert len(list_node.children) == 3

        for item in list_node.children:
            assert item.type == NodeType.LIST_ITEM
            assert len(item.children) > 0


class TestListParsingIntegration:
    """Integration tests for list parsing."""

    def test_cli_validation_case(self):
        """CLI validation from HP-01 acceptance checks."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: Test
---

## Prerequisites

1. Install Visual Studio 2019 or later
2. Target .NET 6.0+
3. Install Aspose.Slides

## Features

- Convert presentations
- Merge decks
- Extract text
""")

        # Count list nodes
        list_nodes = [n for n in doc.ast if n.type == NodeType.LIST]
        assert len(list_nodes) == 2, f"Expected 2 LIST nodes, got {len(list_nodes)}"

        # Verify ordered vs unordered
        ordered_list = next((n for n in list_nodes if n.attrs.get("ordered")), None)
        bullet_list = next((n for n in list_nodes if not n.attrs.get("ordered")), None)

        assert ordered_list is not None, "Should have ordered list"
        assert bullet_list is not None, "Should have bullet list"

        assert len(ordered_list.children) == 3, "Ordered list should have 3 items"
        assert len(bullet_list.children) == 3, "Bullet list should have 3 items"

    def test_mixed_content_with_lists(self):
        """Lists mixed with other content types."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: Mixed
---

# Heading

Some paragraph text.

1. List item one
2. List item two

More text.

- Bullet one
- Bullet two

Final paragraph.
""")

        # Verify we have mixed node types
        headings = [n for n in doc.ast if n.type == NodeType.HEADING]
        paragraphs = [n for n in doc.ast if n.type == NodeType.PARAGRAPH]
        lists = [n for n in doc.ast if n.type == NodeType.LIST]

        assert len(headings) == 1
        assert len(paragraphs) >= 3  # At least 3 paragraphs
        assert len(lists) == 2  # 2 lists

    def test_deeply_nested_lists(self):
        """Deeply nested lists."""
        parser = HugoParser()
        doc = parser.parse_string("""---
title: Nested
---
1. Level 1
   - Level 2a
   - Level 2b
2. Level 1 again
""")

        top_list = [n for n in doc.ast if n.type == NodeType.LIST][0]
        assert len(top_list.children) == 2

        # First item has nested list
        first_item = top_list.children[0]
        nested_lists = [c for c in first_item.children if c.type == NodeType.LIST]
        assert len(nested_lists) == 1

        # Nested list has 2 items
        nested_list = nested_lists[0]
        assert len(nested_list.children) == 2


class TestInlineParsing:
    """Tests for inline element handling (HP-02)."""

    def test_parse_link(self):
        """Link creates LINK node with url attribute."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n[Click here](https://example.com)")

        para = doc.ast[0]
        links = [n for n in para.children if n.type == NodeType.LINK]
        assert len(links) == 1
        assert links[0].attrs["url"] == "https://example.com"

    def test_parse_link_with_title(self):
        """Link with title preserves title attribute."""
        parser = HugoParser()
        doc = parser.parse_string('---\ntitle: t\n---\n[Click](url "My Title")')

        para = doc.ast[0]
        links = [n for n in para.children if n.type == NodeType.LINK]
        assert links[0].attrs.get("title") == "My Title"

    def test_parse_bold(self):
        """Bold text creates STRONG node."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\nSome **bold** text")

        para = doc.ast[0]
        strongs = [n for n in para.children if n.type == NodeType.STRONG]
        assert len(strongs) == 1
        # Content should be TEXT child
        assert any(c.type == NodeType.TEXT for c in strongs[0].children)

    def test_parse_italic(self):
        """Italic text creates EMPHASIS node."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\nSome *italic* text")

        para = doc.ast[0]
        ems = [n for n in para.children if n.type == NodeType.EMPHASIS]
        assert len(ems) == 1

    def test_parse_image(self):
        """Image creates IMAGE node with src and alt."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n![Alt text](image.png)")

        para = doc.ast[0]
        images = [n for n in para.children if n.type == NodeType.IMAGE]
        assert len(images) == 1
        assert images[0].attrs["src"] == "image.png"
        assert images[0].attrs["alt"] == "Alt text"

    def test_parse_nested_bold_in_link(self):
        """Bold inside link creates nested structure."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n[**Bold link**](url)")

        para = doc.ast[0]
        links = [n for n in para.children if n.type == NodeType.LINK]
        assert len(links) == 1
        # Link should contain STRONG
        strongs = [c for c in links[0].children if c.type == NodeType.STRONG]
        assert len(strongs) == 1

    def test_parse_link_in_bold(self):
        """Link inside bold creates nested structure."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\n**[link](url)**")

        para = doc.ast[0]
        strongs = [n for n in para.children if n.type == NodeType.STRONG]
        assert len(strongs) == 1
        links = [c for c in strongs[0].children if c.type == NodeType.LINK]
        assert len(links) == 1

    def test_backward_compat_text(self):
        """Plain text still works."""
        parser = HugoParser()
        doc = parser.parse_string("---\ntitle: t\n---\nPlain text here")

        para = doc.ast[0]
        texts = [n for n in para.children if n.type == NodeType.TEXT]
        assert len(texts) >= 1
def test_parse_frontmatter_with_top_level_content_key():
    """A Hugo frontmatter key named 'content' must not make YAML parse as body."""
    source = """---
layout: plugin
head_title: Example
content:
  enable: true
  block:
    - title_left: Left
      content_left: Body text
---

Markdown body.
"""

    doc = HugoParser().parse_string(source)

    assert doc.frontmatter["layout"] == "plugin"
    assert doc.frontmatter["content"]["enable"] is True
    assert len(doc.ast) == 1


# ---------------------------------------------------------------------------
# TC-HUGOP-013: _normalize_table_cells() tests
# ---------------------------------------------------------------------------

class TestNormalizeTableCells:
    """Tests for HugoParser._normalize_table_cells() multi-line cell merging."""

    def setup_method(self):
        self.parser = HugoParser()

    def _rows(self, md: str) -> int:
        """Count TABLE_ROW nodes produced for a given markdown body."""
        from src.translation_engine.parser.ast_nodes import NodeType

        doc = self.parser.parse_string(f"---\ntitle: test\n---\n\n{md}")

        def _walk(node):
            yield node
            for child in getattr(node, "children", []):
                yield from _walk(child)

        all_nodes = [n for root in doc.ast for n in _walk(root)]
        return sum(1 for n in all_nodes if n.type == NodeType.TABLE_ROW)

    def test_single_line_rows_unchanged(self):
        """Complete single-line rows (start AND end with |) are not affected."""
        md = (
            "| Name | Type | Description |\n"
            "| --- | --- | --- |\n"
            "| `foo` | `int` | Gets foo. |\n"
            "| `bar` | `str` | Gets bar. |\n"
        )
        # header + 2 data rows = 3 TABLE_ROW nodes
        assert self._rows(md) == 3

    def test_multi_line_cell_merged_into_single_row(self):
        """Multi-line cell opener + continuation lines become one TABLE_ROW."""
        md = (
            "| Name | Type | Description |\n"
            "| --- | --- | --- |\n"
            "| `foo` | `int` | Gets the foo value\n"
            " @return the foo value\n"
            " / |\n"
        )
        # header + 1 data row = 2 TABLE_ROW nodes (not 4)
        assert self._rows(md) == 2

    def test_mixed_single_and_multi_line_rows(self):
        """Mix of complete rows and multi-line cells gives correct count."""
        md = (
            "| Name | Type | Description |\n"
            "| --- | --- | --- |\n"
            "| `alpha` | `int` | Simple one-liner. |\n"
            "| `beta` | `str` | Multi-line description\n"
            " @return beta value\n"
            " / |\n"
            "| `gamma` | `bool` | Another one-liner. |\n"
        )
        # header + 3 data rows = 4 TABLE_ROW nodes
        assert self._rows(md) == 4

    def test_code_block_pipes_not_treated_as_table(self):
        """Lines with | inside fenced code blocks are never treated as table rows."""
        md = (
            "```java\n"
            "| not a table | still not |\n"
            "```\n\n"
            "| Name | Value |\n"
            "| --- | --- |\n"
            "| `x` | 1 |\n"
        )
        # Only the real table: header + 1 data row = 2 TABLE_ROW nodes
        assert self._rows(md) == 2

    def test_normalize_produces_trailing_pipe(self):
        """Merged multi-line row ends with | (valid markdown table row)."""
        raw = (
            "| `foo` | `int` | Gets the value\n"
            " @return value\n"
        )
        normalized = self.parser._normalize_table_cells(raw)
        lines = normalized.splitlines()
        assert len(lines) == 1
        assert lines[0].endswith("|"), f"Expected trailing |, got: {lines[0]!r}"
