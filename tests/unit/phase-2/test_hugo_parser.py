"""
Unit tests for Hugo Markdown Parser.
"""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from translation_engine.parser import HugoDocument, HugoParser, NodeType


class TestHugoParserBasic:
    """Test basic Hugo parser functionality."""

    def test_parser_initialization(self) -> None:
        """Test parser can be initialized."""
        parser = HugoParser()
        assert parser is not None
        assert parser.md is not None

    def test_parse_empty_string(self) -> None:
        """Test parsing empty content."""
        parser = HugoParser()
        doc = parser.parse_string("")

        assert isinstance(doc, HugoDocument)
        assert doc.frontmatter == {}
        assert doc.ast == []

    def test_parse_simple_text(self) -> None:
        """Test parsing simple text without frontmatter."""
        parser = HugoParser()
        content = "Hello, World!"
        doc = parser.parse_string(content)

        assert doc.frontmatter == {}
        assert len(doc.ast) == 1
        assert doc.ast[0].type == NodeType.PARAGRAPH


class TestFrontmatterParsing:
    """Test frontmatter extraction."""

    def test_parse_frontmatter_simple(self) -> None:
        """Test parsing simple frontmatter."""
        parser = HugoParser()
        content = """---
title: Test Page
description: A test page
---

Content here.
"""
        doc = parser.parse_string(content)

        assert doc.frontmatter["title"] == "Test Page"
        assert doc.frontmatter["description"] == "A test page"
        assert len(doc.ast) == 1

    def test_parse_frontmatter_complex(self) -> None:
        """Test parsing complex frontmatter."""
        parser = HugoParser()
        content = """---
title: Complex Page
tags:
  - tag1
  - tag2
metadata:
  author: John Doe
  date: 2024-01-01
---

Body content.
"""
        doc = parser.parse_string(content)

        assert doc.frontmatter["title"] == "Complex Page"
        assert doc.frontmatter["tags"] == ["tag1", "tag2"]
        assert doc.frontmatter["metadata"]["author"] == "John Doe"

    def test_parse_no_frontmatter(self) -> None:
        """Test parsing content without frontmatter."""
        parser = HugoParser()
        content = "Just plain content."
        doc = parser.parse_string(content)

        assert doc.frontmatter == {}


class TestMarkdownParsing:
    """Test Markdown body parsing."""

    def test_parse_heading(self) -> None:
        """Test parsing headings."""
        parser = HugoParser()
        content = "# Heading 1\n## Heading 2"
        doc = parser.parse_string(content)

        assert len(doc.ast) == 2
        assert doc.ast[0].type == NodeType.HEADING
        assert doc.ast[0].attrs["level"] == 1
        assert doc.ast[1].type == NodeType.HEADING
        assert doc.ast[1].attrs["level"] == 2

    def test_parse_paragraph(self) -> None:
        """Test parsing paragraphs."""
        parser = HugoParser()
        content = "This is a paragraph.\n\nThis is another paragraph."
        doc = parser.parse_string(content)

        assert len(doc.ast) == 2
        assert all(node.type == NodeType.PARAGRAPH for node in doc.ast)

    def test_parse_code_block(self) -> None:
        """Test parsing code blocks."""
        parser = HugoParser()
        content = """```python
def hello():
    print("Hello")
```"""
        doc = parser.parse_string(content)

        assert len(doc.ast) == 1
        assert doc.ast[0].type == NodeType.CODE_BLOCK
        assert doc.ast[0].attrs.get("lang") == "python"
        assert "def hello()" in doc.ast[0].raw

    def test_parse_inline_code(self) -> None:
        """Test parsing inline code."""
        parser = HugoParser()
        content = "This has `inline code` in it."
        doc = parser.parse_string(content)

        assert len(doc.ast) == 1
        assert doc.ast[0].type == NodeType.PARAGRAPH
        children = doc.ast[0].children
        assert any(child.type == NodeType.CODE_SPAN for child in children)


class TestComplexContent:
    """Test parsing complex content."""

    def test_parse_sample_fixture(self, test_data_dir: Path) -> None:
        """Test parsing the sample fixture file."""
        parser = HugoParser()
        fixture_path = test_data_dir.parent / "fixtures" / "sample_content" / "simple.md"

        if not fixture_path.exists():
            pytest.skip(f"Fixture not found: {fixture_path}")

        doc = parser.parse_file(fixture_path)

        # Check frontmatter
        assert "title" in doc.frontmatter
        assert doc.frontmatter["title"] == "Simple Test Page"
        assert doc.frontmatter["draft"] is False

        # Check AST structure
        assert len(doc.ast) > 0

        # Check for headings
        headings = [node for node in doc.ast if node.type == NodeType.HEADING]
        assert len(headings) >= 2

        # Check for code block
        code_blocks = [node for node in doc.ast if node.type == NodeType.CODE_BLOCK]
        assert len(code_blocks) >= 1

    def test_parse_mixed_content(self) -> None:
        """Test parsing mixed content types."""
        parser = HugoParser()
        content = """---
title: Mixed Content
---

# Introduction

This is a paragraph with **bold** text.

## Code

Here's some code:

```go
func main() {
    fmt.Println("Hello")
}
```

And more text after.
"""
        doc = parser.parse_string(content)

        assert doc.frontmatter["title"] == "Mixed Content"
        assert len(doc.ast) > 3

        # Check variety of node types
        node_types = {node.type for node in doc.ast}
        assert NodeType.HEADING in node_types
        assert NodeType.PARAGRAPH in node_types
        assert NodeType.CODE_BLOCK in node_types


class TestNodeIDs:
    """Test node ID generation."""

    def test_nodes_have_unique_ids(self) -> None:
        """Test that all nodes get unique IDs."""
        parser = HugoParser()
        content = "# Heading\n\nParagraph one.\n\nParagraph two."
        doc = parser.parse_string(content)

        node_ids = []
        for node in doc.ast:
            assert node.node_id is not None
            node_ids.append(node.node_id)

        # All IDs should be unique
        assert len(node_ids) == len(set(node_ids))


class TestDocumentConversion:
    """Test document conversion methods."""

    def test_to_dict(self) -> None:
        """Test converting document to dictionary."""
        parser = HugoParser()
        content = """---
title: Test
---

Hello world.
"""
        doc = parser.parse_string(content)
        doc_dict = doc.to_dict()

        assert "frontmatter" in doc_dict
        assert "ast" in doc_dict
        assert doc_dict["frontmatter"]["title"] == "Test"
        assert isinstance(doc_dict["ast"], list)


class TestErrorHandling:
    """Test error handling."""

    def test_file_not_found(self) -> None:
        """Test parsing non-existent file raises error."""
        parser = HugoParser()

        with pytest.raises(FileNotFoundError):
            parser.parse_file(Path("/nonexistent/file.md"))

    def test_malformed_frontmatter(self) -> None:
        """Test malformed frontmatter is handled gracefully."""
        parser = HugoParser()
        content = """---
title: Test
bad yaml here: [
---

Content.
"""
        # Should not raise, should treat as no frontmatter
        doc = parser.parse_string(content)
        assert isinstance(doc, HugoDocument)
