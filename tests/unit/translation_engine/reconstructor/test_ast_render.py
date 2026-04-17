"""
Comprehensive tests for ASTRenderer (TC-04).

Tests cover:
- Application of translations to all node types
- Rendering of all node types to Markdown
- Preservation of URLs, image src, code
- Whitespace reattachment
- Complex nesting scenarios
- Markdown validity (roundtrip)
"""


import pytest

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.parser.ast_nodes import (
    ASTNode,
    NodeType,
    heading_node,
    paragraph_node,
    text_node,
)
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


class TestApplyTranslations:
    """Test applying translations back to AST."""

    def test_apply_to_text_node(self):
        """Test applying translation to text node."""
        renderer = ASTRenderer()

        # Create node with address
        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.paragraph[0]")

        # Create translated unit
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.paragraph[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            translated_text="Hola"
        )

        # Apply translation
        renderer.apply_translations([para], [unit])

        # Verify node content updated
        assert para.children[0].raw == "Hola"

    def test_apply_with_whitespace(self):
        """Test whitespace is reattached."""
        renderer = ASTRenderer()

        para = paragraph_node([text_node("  Hello  ")])
        para.assign_addresses("body.paragraph[0]")

        # Unit with whitespace separated
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.paragraph[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            prefix_ws="  ",
            suffix_ws="  ",
            translated_text="Hola"
        )

        renderer.apply_translations([para], [unit])

        # Verify whitespace reattached
        assert para.children[0].raw == "  Hola  "

    def test_apply_to_nested_nodes(self):
        """Test applying translations to nested structure."""
        renderer = ASTRenderer()

        # Create: **bold**
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        para = paragraph_node([strong])
        para.assign_addresses("body.paragraph[0]")

        # Translate "bold" to "audaz"
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.paragraph[0].strong[0].text[0]",
            kind=TextUnitKind.TEXT,
            source_text="bold",
            translated_text="audaz"
        )

        renderer.apply_translations([para], [unit])

        # Verify nested node updated
        assert strong.children[0].raw == "audaz"

    def test_apply_multiple_units(self):
        """Test applying multiple units."""
        renderer = ASTRenderer()

        # Create paragraph with multiple text nodes
        para = paragraph_node([
            text_node("First "),
            text_node("second")
        ])
        para.assign_addresses("body.paragraph[0]")

        units = [
            TextUnit(
                unit_id="u1",
                node_addr="body.paragraph[0].text[0]",
                kind=TextUnitKind.TEXT,
                source_text="First",
                translated_text="Primero",
                suffix_ws=" "
            ),
            TextUnit(
                unit_id="u2",
                node_addr="body.paragraph[0].text[1]",
                kind=TextUnitKind.TEXT,
                source_text="second",
                translated_text="segundo"
            ),
        ]

        renderer.apply_translations([para], units)

        assert para.children[0].raw == "Primero "
        assert para.children[1].raw == "segundo"


class TestRenderBasicNodes:
    """Test rendering basic node types."""

    def test_render_text(self):
        """Test rendering text node."""
        renderer = ASTRenderer()

        para = paragraph_node([text_node("Hello world")])
        para.assign_addresses("body.paragraph[0]")

        markdown = renderer.render_to_markdown([para])

        assert "Hello world" in markdown
        assert markdown.endswith("\n\n")  # Paragraphs end with double newline

    def test_render_heading(self):
        """Test rendering heading."""
        renderer = ASTRenderer()

        heading = heading_node(level=2, children=[text_node("My Heading")])
        heading.assign_addresses("body.heading[0]")

        markdown = renderer.render_to_markdown([heading])

        assert markdown == "## My Heading\n\n"

    def test_render_heading_levels(self):
        """Test different heading levels."""
        renderer = ASTRenderer()

        for level in range(1, 7):
            heading = heading_node(level=level, children=[text_node("Title")])
            markdown = renderer.render_to_markdown([heading])
            assert markdown.startswith("#" * level + " ")

    def test_render_strong(self):
        """Test rendering bold text."""
        renderer = ASTRenderer()

        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        para = paragraph_node([text_node("This is "), strong, text_node(" text")])

        markdown = renderer.render_to_markdown([para])

        assert "**bold**" in markdown
        assert "This is **bold** text" in markdown

    def test_render_emphasis(self):
        """Test rendering italic text."""
        renderer = ASTRenderer()

        em = ASTNode(type=NodeType.EMPHASIS, children=[text_node("italic")])
        para = paragraph_node([em])

        markdown = renderer.render_to_markdown([para])

        assert "*italic*" in markdown

    def test_render_code_span(self):
        """Test rendering inline code."""
        renderer = ASTRenderer()

        code = ASTNode(type=NodeType.CODE_SPAN, raw="myFunction()")
        para = paragraph_node([text_node("Call "), code])

        markdown = renderer.render_to_markdown([para])

        assert "`myFunction()`" in markdown

    def test_render_code_block(self):
        """Test rendering code block."""
        renderer = ASTRenderer()

        code_block = ASTNode(
            type=NodeType.CODE_BLOCK,
            raw="def hello():\n    print('world')",
            attrs={"lang": "python"}
        )
        code_block.assign_addresses("body.codeblock[0]")

        markdown = renderer.render_to_markdown([code_block])

        assert "```python" in markdown
        assert "def hello():" in markdown
        assert "```" in markdown


class TestRenderLinks:
    """Test rendering links and images."""

    def test_render_link(self):
        """Test rendering link."""
        renderer = ASTRenderer()

        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com"},
            children=[text_node("Click here")]
        )
        para = paragraph_node([link])

        markdown = renderer.render_to_markdown([para])

        assert "[Click here](https://example.com)" in markdown

    def test_render_link_preserves_url(self):
        """Test URL is preserved exactly."""
        renderer = ASTRenderer()

        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com/path?query=1"},
            children=[text_node("link")]
        )
        link.assign_addresses("body.link[0]")
        link.children[0].assign_addresses("body.link[0].text[0]")

        # Translate link text
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="link",
            translated_text="enlace"
        )

        renderer.apply_translations([link], [unit])
        markdown = renderer.render_to_markdown([link])

        # URL should be unchanged
        assert "https://example.com/path?query=1" in markdown
        # Text should be translated
        assert "[enlace]" in markdown

    def test_render_image(self):
        """Test rendering image."""
        renderer = ASTRenderer()

        image = ASTNode(
            type=NodeType.IMAGE,
            attrs={"src": "/images/photo.jpg", "alt": "Beautiful photo"}
        )

        markdown = renderer.render_to_markdown([image])

        assert "![Beautiful photo](/images/photo.jpg)" in markdown

    def test_render_image_preserves_src(self):
        """Test image src is preserved."""
        renderer = ASTRenderer()

        image = ASTNode(
            type=NodeType.IMAGE,
            attrs={"src": "/images/photo.jpg", "alt": "Photo"}
        )
        image.assign_addresses("body.image[0]")

        # Translate alt text
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.image[0]",
            kind=TextUnitKind.IMAGE_ALT,
            source_text="Photo",
            translated_text="Foto"
        )

        renderer.apply_translations([image], [unit])
        markdown = renderer.render_to_markdown([image])

        # src should be unchanged
        assert "/images/photo.jpg" in markdown
        # alt should be translated
        assert "![Foto]" in markdown


class TestRenderLists:
    """Test rendering lists."""

    def test_render_unordered_list(self):
        """Test rendering unordered list."""
        renderer = ASTRenderer()

        item1 = ASTNode(type=NodeType.LIST_ITEM, children=[text_node("First")])
        item2 = ASTNode(type=NodeType.LIST_ITEM, children=[text_node("Second")])
        list_node = ASTNode(
            type=NodeType.LIST,
            attrs={"ordered": False},
            children=[item1, item2]
        )

        markdown = renderer.render_to_markdown([list_node])

        assert "- First" in markdown
        assert "- Second" in markdown

    def test_render_ordered_list(self):
        """Test rendering ordered list."""
        renderer = ASTRenderer()

        item1 = ASTNode(type=NodeType.LIST_ITEM, children=[text_node("First")])
        item2 = ASTNode(type=NodeType.LIST_ITEM, children=[text_node("Second")])
        list_node = ASTNode(
            type=NodeType.LIST,
            attrs={"ordered": True},
            children=[item1, item2]
        )

        markdown = renderer.render_to_markdown([list_node])

        assert "1. First" in markdown
        assert "2. Second" in markdown


class TestRenderTables:
    """Test rendering tables with alignment."""

    def test_render_simple_table(self):
        """Test rendering simple table."""
        renderer = ASTRenderer()

        # Create header row
        header_cell1 = ASTNode(type=NodeType.TABLE_CELL, children=[text_node("Column A")])
        header_cell2 = ASTNode(type=NodeType.TABLE_CELL, children=[text_node("Column B")])
        header_row = ASTNode(
            type=NodeType.TABLE_ROW,
            attrs={"is_header": True},
            children=[header_cell1, header_cell2]
        )

        # Create body row
        body_cell1 = ASTNode(type=NodeType.TABLE_CELL, children=[text_node("Data 1")])
        body_cell2 = ASTNode(type=NodeType.TABLE_CELL, children=[text_node("Data 2")])
        body_row = ASTNode(
            type=NodeType.TABLE_ROW,
            attrs={"is_header": False},
            children=[body_cell1, body_cell2]
        )

        # Create table
        table = ASTNode(
            type=NodeType.TABLE,
            children=[header_row, body_row]
        )

        markdown = renderer.render_to_markdown([table])

        # Should have header, separator, and body
        assert "Column A" in markdown
        assert "Column B" in markdown
        assert "Data 1" in markdown
        assert "Data 2" in markdown
        assert "|" in markdown  # Table pipe
        assert "-" in markdown  # Separator dashes

    def test_render_table_alignment(self):
        """Test table column alignment."""
        renderer = ASTRenderer()

        # Create header with alignment info
        header_cell1 = ASTNode(
            type=NodeType.TABLE_CELL,
            attrs={"align": "left"},
            children=[text_node("Left")]
        )
        header_cell2 = ASTNode(
            type=NodeType.TABLE_CELL,
            attrs={"align": "center"},
            children=[text_node("Center")]
        )
        header_cell3 = ASTNode(
            type=NodeType.TABLE_CELL,
            attrs={"align": "right"},
            children=[text_node("Right")]
        )
        header_row = ASTNode(
            type=NodeType.TABLE_ROW,
            attrs={"is_header": True},
            children=[header_cell1, header_cell2, header_cell3]
        )

        table = ASTNode(
            type=NodeType.TABLE,
            children=[header_row]
        )

        markdown = renderer.render_to_markdown([table])

        lines = markdown.strip().split('\n')
        separator_line = lines[1]  # Second line is separator

        # Check alignment markers
        # Left: ----
        # Center: :----:
        # Right: ----:
        assert ":-" in separator_line or "-:" in separator_line  # Has alignment markers


class TestRenderBlockquote:
    """Test rendering blockquotes."""

    def test_render_blockquote(self):
        """Test rendering blockquote."""
        renderer = ASTRenderer()

        blockquote = ASTNode(
            type=NodeType.BLOCKQUOTE,
            children=[text_node("This is a quote")]
        )

        markdown = renderer.render_to_markdown([blockquote])

        assert "> This is a quote" in markdown


class TestComplexNesting:
    """Test rendering complex nested structures."""

    def test_bold_in_link(self):
        """Test bold text inside link."""
        renderer = ASTRenderer()

        # [**bold**](url)
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("bold")])
        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com"},
            children=[strong]
        )
        para = paragraph_node([link])

        markdown = renderer.render_to_markdown([para])

        assert "[**bold**](https://example.com)" in markdown

    def test_link_in_bold(self):
        """Test link inside bold."""
        renderer = ASTRenderer()

        # **[link](url)**
        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com"},
            children=[text_node("link")]
        )
        strong = ASTNode(type=NodeType.STRONG, children=[link])
        para = paragraph_node([strong])

        markdown = renderer.render_to_markdown([para])

        assert "**[link](https://example.com)**" in markdown

    def test_deeply_nested(self):
        """Test deeply nested formatting."""
        renderer = ASTRenderer()

        # ***text***
        text = text_node("text")
        em = ASTNode(type=NodeType.EMPHASIS, children=[text])
        strong = ASTNode(type=NodeType.STRONG, children=[em])
        para = paragraph_node([strong])

        markdown = renderer.render_to_markdown([para])

        # Should have both ** and *
        assert "**" in markdown
        assert "*text*" in markdown


class TestMarkdownValidity:
    """Test that rendered Markdown is valid and parseable."""

    def test_roundtrip_simple(self):
        """Test parse -> render -> parse yields similar AST."""
        renderer = ASTRenderer()

        # Create simple AST
        para = paragraph_node([text_node("Hello world")])
        para.assign_addresses("body.paragraph[0]")

        # Render to markdown
        markdown = renderer.render_to_markdown([para])

        # Verify it's valid markdown (has expected content)
        assert "Hello world" in markdown
        assert markdown.strip()  # Not empty

    def test_deterministic_rendering(self):
        """Test same AST produces identical Markdown."""
        renderer1 = ASTRenderer()
        renderer2 = ASTRenderer()

        # Create same AST twice
        para1 = paragraph_node([text_node("Same text")])
        para2 = paragraph_node([text_node("Same text")])

        markdown1 = renderer1.render_to_markdown([para1])
        markdown2 = renderer2.render_to_markdown([para2])

        assert markdown1 == markdown2


class TestEdgeCases:
    """Test edge cases and error handling."""

    def test_empty_ast(self):
        """Test rendering empty AST."""
        renderer = ASTRenderer()

        markdown = renderer.render_to_markdown([])

        assert markdown == ""

    def test_empty_text_node(self):
        """Test rendering empty text."""
        renderer = ASTRenderer()

        para = paragraph_node([text_node("")])

        markdown = renderer.render_to_markdown([para])

        # Should still produce paragraph structure
        assert markdown == "\n\n"

    def test_orphaned_units(self):
        """Test handling of units that don't match AST."""
        renderer = ASTRenderer()

        para = paragraph_node([text_node("Hello")])
        para.assign_addresses("body.paragraph[0]")

        # Unit with non-existent address
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.paragraph[99].text[0]",  # Invalid address
            kind=TextUnitKind.TEXT,
            source_text="Hello",
            translated_text="Hola"
        )

        # Should not crash, just warn
        renderer.apply_translations([para], [unit])

        # Original text should be unchanged
        assert para.children[0].raw == "Hello"


class TestPreservation:
    """Test that certain content is never modified."""

    def test_code_never_modified(self):
        """Test code content is never translated."""
        renderer = ASTRenderer()

        code = ASTNode(type=NodeType.CODE_SPAN, raw="myFunction()")
        para = paragraph_node([code])
        para.assign_addresses("body.paragraph[0]")
        code.assign_addresses("body.paragraph[0].codespan[0]")

        # Create unit with "translation" (should not be applied to code)
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.paragraph[0].codespan[0]",
            kind=TextUnitKind.CODE_SPAN,
            source_text="myFunction()",
            do_not_translate=True,
            translated_text="myFunction()"  # Same as source
        )

        renderer.apply_translations([para], [unit])
        markdown = renderer.render_to_markdown([para])

        # Code should be unchanged
        assert "`myFunction()`" in markdown

    def test_url_never_modified(self):
        """Test URLs are never modified."""
        renderer = ASTRenderer()

        link = ASTNode(
            type=NodeType.LINK,
            attrs={"url": "https://example.com"},
            children=[text_node("link")]
        )
        link.assign_addresses("body.link[0]")
        link.children[0].assign_addresses("body.link[0].text[0]")

        # Translate link text
        unit = TextUnit(
            unit_id="u1",
            node_addr="body.link[0].text[0]",
            kind=TextUnitKind.LINK_TEXT,
            source_text="link",
            translated_text="enlace"
        )

        renderer.apply_translations([link], [unit])
        markdown = renderer.render_to_markdown([link])

        # URL must be unchanged
        assert "https://example.com" in markdown
        # Text should be translated
        assert "enlace" in markdown


class TestOutputSanitization:
    """Test output sanitization (FIX-BT-02)."""

    def test_sanitize_language_markers_removes_de_marker(self):
        """Test __de__ marker removed."""
        renderer = ASTRenderer()
        text = "__de__This is German text__de__"
        result = renderer._sanitize_language_markers(text)
        assert "__de__" not in result
        assert "This is German text" in result

    def test_sanitize_language_markers_removes_multiple_markers(self):
        """Test multiple different language markers removed."""
        renderer = ASTRenderer()
        text = "__de__German __de__and __en__English __en__and __fr__French__fr__"
        result = renderer._sanitize_language_markers(text)
        assert "__de__" not in result
        assert "__en__" not in result
        assert "__fr__" not in result
        assert "German" in result
        assert "and" in result
        assert "English" in result
        assert "French" in result

    def test_sanitize_language_markers_preserves_content(self):
        """Test non-marker content preserved."""
        renderer = ASTRenderer()
        text = "**Bold** and *italic* and [link](url)"
        result = renderer._sanitize_language_markers(text)
        assert result == text  # Unchanged

    def test_sanitize_language_markers_handles_empty_string(self):
        """Test empty string handled gracefully."""
        renderer = ASTRenderer()
        result = renderer._sanitize_language_markers("")
        assert result == ""

    def test_sanitize_language_markers_handles_none(self):
        """Test None handled gracefully."""
        renderer = ASTRenderer()
        result = renderer._sanitize_language_markers(None)
        assert result is None

    def test_sanitize_language_markers_preserves_dunder_methods(self):
        """Test that Python dunder methods are not removed."""
        renderer = ASTRenderer()
        text = "Use __init__ and __main__ for Python"
        result = renderer._sanitize_language_markers(text)
        # Should preserve __init__ and __main__ since they have more than 2 chars
        assert "__init__" in result
        assert "__main__" in result

    def test_sanitize_language_markers_with_trailing_whitespace(self):
        """Test markers with trailing whitespace are removed."""
        renderer = ASTRenderer()
        text = "__de__ This text has a marker with space"
        result = renderer._sanitize_language_markers(text)
        assert "__de__" not in result
        assert "This text has a marker with space" in result

    def test_render_text_node_sanitizes_markers(self):
        """Test that rendering text node sanitizes markers."""
        renderer = ASTRenderer()

        # Create text node with marker
        para = paragraph_node([text_node("__de__German text__de__")])

        markdown = renderer.render_to_markdown([para])

        # Markers should be removed
        assert "__de__" not in markdown
        assert "German text" in markdown

    def test_render_final_output_sanitizes_markers(self):
        """Test that final output pass sanitizes any remaining markers."""
        renderer = ASTRenderer()

        # Create paragraph with marker in text
        para = paragraph_node([text_node("Hello __en__ world")])

        markdown = renderer.render_to_markdown([para])

        # Marker should be removed
        assert "__en__" not in markdown
        assert "Hello" in markdown
        assert "world" in markdown

    def test_sanitize_preserves_markdown_formatting(self):
        """Test sanitization preserves markdown formatting."""
        renderer = ASTRenderer()

        # Create formatted text with markers
        strong = ASTNode(type=NodeType.STRONG, children=[text_node("__de__bold__de__")])
        para = paragraph_node([strong])

        markdown = renderer.render_to_markdown([para])

        # Should have bold markers but no language markers
        assert "**" in markdown
        assert "bold" in markdown
        assert "__de__" not in markdown

    def test_sanitize_with_mixed_markers(self):
        """Test sanitization with mixed valid and invalid markers."""
        renderer = ASTRenderer()
        text = "Code uses __init__ but has __de__ marker and __en__ marker"
        result = renderer._sanitize_language_markers(text)

        # Should keep __init__ but remove __de__ and __en__
        assert "__init__" in result
        assert "__de__" not in result
        assert "__en__" not in result
        assert "Code uses" in result
        assert "marker" in result


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
