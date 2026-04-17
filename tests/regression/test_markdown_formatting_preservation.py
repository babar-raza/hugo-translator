"""
Regression tests for markdown formatting preservation.

These tests ensure that bold, italic, links, headings, and lists are preserved
during AST-based translation, addressing Phase 6 markdown fidelity failures.
"""
import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.translation_engine.parser import HugoParser
from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


class TestBoldItalicPreservation:
    """Test that bold and italic spans are preserved correctly."""

    def test_single_bold_span_preserved(self):
        """Test that a single bold span is preserved."""
        source = "This is **bold text** in a paragraph."

        # Parse
        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        # Extract units
        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        # Simulate translation (keep same text for structure test)
        for unit in units:
            unit.translated_text = unit.source_text

        # Apply and render
        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Should preserve bold
        assert "**bold text**" in output, f"Bold not preserved. Output: {output}"
        assert output.count("**") == 2, f"Bold marker count mismatch. Output: {output}"

    def test_multiple_bold_spans_preserved(self):
        """Test that multiple bold spans in same paragraph are preserved."""
        source = "This has **first bold** and **second bold** text."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Should preserve both bold spans
        assert "**first bold**" in output
        assert "**second bold**" in output
        assert output.count("**") == 4  # 2 pairs

    def test_single_italic_span_preserved(self):
        """Test that a single italic span is preserved."""
        source = "This is *italic text* in a paragraph."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Should preserve italic
        assert "*italic text*" in output
        assert output.count("*") >= 2  # At least the italic markers

    def test_bold_and_italic_together(self):
        """Test that bold and italic can coexist in same paragraph."""
        source = "This has **bold** and *italic* text."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Should preserve both
        assert "**bold**" in output
        assert "*italic*" in output


class TestHeadingLevelPreservation:
    """Test that heading levels are preserved correctly."""

    def test_h2_level_preserved(self):
        """Test that H2 heading level is preserved."""
        source = "## Heading Level 2\n\nSome content."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Should be H2, not H3 or other
        assert "## Heading Level 2" in output
        assert "### Heading Level 2" not in output

    def test_h3_level_preserved(self):
        """Test that H3 heading level is preserved."""
        source = "### Heading Level 3\n\nSome content."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Should be H3, not accidentally downgraded to H2
        assert "### Heading Level 3" in output
        # Verify no line starts with exactly "## " (H2 marker) — note "###" starts with "##",
        # so substring check is wrong; check line-level prefix instead.
        assert not any(line.startswith("## Heading Level 3") for line in output.splitlines())
        assert "#### Heading Level 3" not in output

    def test_multiple_heading_levels_preserved(self):
        """Test that multiple heading levels are all preserved."""
        source = """## Level 2 Heading

Content here.

### Level 3 Heading

More content.

#### Level 4 Heading

Even more content.
"""

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # All levels should be preserved
        assert "## Level 2 Heading" in output
        assert "### Level 3 Heading" in output
        assert "#### Level 4 Heading" in output


class TestLinkPreservation:
    """Test that links are preserved correctly."""

    def test_inline_link_preserved(self):
        """Test that inline link is preserved."""
        source = "Check out [this link](https://example.com) for more info."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Link should be preserved
        assert "[this link](https://example.com)" in output

    def test_multiple_links_preserved(self):
        """Test that multiple links are preserved."""
        source = "Visit [site one](https://one.com) and [site two](https://two.com)."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Both links should be preserved
        assert "[site one](https://one.com)" in output
        assert "[site two](https://two.com)" in output
        # Count [ and ] to ensure structure
        assert output.count("[") == 2
        assert output.count("]") == 2

    def test_link_with_bold_text_preserved(self):
        """Test that link with bold text is preserved."""
        source = "Click [**bold link**](https://example.com) here."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Link with bold should be preserved
        assert "[**bold link**](https://example.com)" in output


class TestListPreservation:
    """Test that list structures are preserved correctly."""

    def test_simple_unordered_list_preserved(self):
        """Test that simple unordered list is preserved."""
        source = """- Item 1
- Item 2
- Item 3
"""

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # List items should be preserved
        assert "- Item 1" in output
        assert "- Item 2" in output
        assert "- Item 3" in output

    def test_nested_list_structure_preserved(self):
        """Test that nested list structure is preserved."""
        source = """- Level 1 Item
  - Level 2 Item
    - Level 3 Item
"""

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Nested structure should be preserved (check for indentation)
        assert "- Level 1 Item" in output
        assert "  - Level 2 Item" in output or "    - Level 2 Item" in output


class TestComplexFormattingPreservation:
    """Test complex scenarios with multiple formatting types."""

    def test_paragraph_with_mixed_formatting(self):
        """Test paragraph with bold, italic, and links together."""
        source = "This has **bold**, *italic*, and [a link](https://example.com) all together."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # All formatting should be preserved
        assert "**bold**" in output
        assert "*italic*" in output
        assert "[a link](https://example.com)" in output

    def test_heading_with_bold_text(self):
        """Test that heading with bold text is preserved."""
        source = "## Heading with **Bold** Text\n\nContent."

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Heading level and bold should both be preserved
        assert "## Heading with **Bold** Text" in output or "##Heading with **Bold** Text" in output


class TestPhase6RegressionCases:
    """Test specific cases from Phase 6 failures."""

    def test_cells_getting_started_structure(self):
        """Test structure preservation for cells getting-started case."""
        # Simplified version of the actual failure case
        source = """## System Requirements

Before diving in, make sure you have:

* A Windows machine
* .NET Framework 4.0

## Installation

To start using the library:

1. Download the latest version
2. Install the DLL
3. Select the framework

## Supported Formats

The library supports [various formats](supported-file-formats) including:

* Excel files (.xls, .xlsx)
* HTML documents (.html)
"""

        parser = HugoParser()
        doc = parser.parse_string(source)
        ast = doc.ast

        extractor = TextUnitExtractor()
        units = extractor.extract_from_ast(ast).units

        for unit in units:
            unit.translated_text = unit.source_text

        renderer = ASTRenderer()
        renderer.apply_translations(ast, units)
        output = renderer.render_to_markdown(ast)

        # Critical checks from Phase 6 failure
        # 1. Heading levels must be preserved (not H2 → H3)
        assert "## System Requirements" in output, "H2 heading converted to H3!"
        assert "### System Requirements" not in output, "H2 heading incorrectly became H3!"

        assert "## Installation" in output
        assert "### Installation" not in output

        assert "## Supported Formats" in output
        assert "### Supported Formats" not in output

        # 2. Links must be preserved (not lost)
        assert "[various formats](supported-file-formats)" in output, "Link was lost!"

        # 3. List structures should be preserved
        assert "* A Windows machine" in output or "- A Windows machine" in output
        assert "1. Download the latest version" in output


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
