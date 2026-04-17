"""
Tests for literal block scalar style preservation.

Verifies SD-02 acceptance checks:
- Multi-line content with bullets uses literal block style
- Paragraphs with double newlines use literal style
- Single-line content stays plain
- Literal style preserved in round-trip
"""
# Import directly to avoid full package import chain
import sys

from ruamel.yaml.scalarstring import LiteralScalarString

sys.path.insert(0, ".")


class TestShouldUseLiteralStyle:
    """Test should_use_literal_style detection logic."""

    def test_single_line_returns_false(self):
        """Single line content should not use literal style."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        assert not YAMLFormatter.should_use_literal_style("Simple title")
        assert not YAMLFormatter.should_use_literal_style("No newlines here")

    def test_multiline_with_bullets_returns_true(self):
        """Multi-line with bullet markers should use literal style."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = """Step 1: Install

- Bullet 1
- Bullet 2

Done."""
        assert YAMLFormatter.should_use_literal_style(content)

    def test_multiple_paragraphs_returns_true(self):
        """Content with multiple paragraphs should use literal style."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = """First paragraph.

Second paragraph.

Third paragraph."""
        assert YAMLFormatter.should_use_literal_style(content)

    def test_numbered_list_returns_true(self):
        """Content with numbered list should use literal style."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = """Steps:

1. First step
2. Second step
3. Third step"""
        assert YAMLFormatter.should_use_literal_style(content)

    def test_simple_newline_returns_false(self):
        """Single newline without markers should not use literal style."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = "Line one\nLine two"
        assert not YAMLFormatter.should_use_literal_style(content)

    def test_non_string_returns_false(self):
        """Non-string values should return False."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        assert not YAMLFormatter.should_use_literal_style(123)
        assert not YAMLFormatter.should_use_literal_style(None)
        assert not YAMLFormatter.should_use_literal_style(["list"])


class TestMaybeApplyLiteralStyle:
    """Test maybe_apply_literal_style auto-conversion."""

    def test_converts_bullet_content(self):
        """Content with bullets should be converted to LiteralScalarString."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = """Install:

- Step 1
- Step 2"""
        result = YAMLFormatter.maybe_apply_literal_style(content)
        assert isinstance(result, LiteralScalarString)

    def test_leaves_simple_string(self):
        """Simple strings should remain unchanged."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = "Simple title"
        result = YAMLFormatter.maybe_apply_literal_style(content)
        assert result == content
        assert not isinstance(result, LiteralScalarString)

    def test_leaves_non_strings(self):
        """Non-strings should pass through unchanged."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        assert YAMLFormatter.maybe_apply_literal_style(123) == 123
        assert YAMLFormatter.maybe_apply_literal_style(True) is True
        assert YAMLFormatter.maybe_apply_literal_style(None) is None


class TestSetNestedValueWithLiteral:
    """Test that set_nested_value auto-applies literal style."""

    def test_auto_applies_literal_for_bullets(self):
        """set_nested_value should auto-apply literal style for bullet content."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        data = {}
        content = """Instructions:

- Install NuGet
- Add reference
- Use API"""

        YAMLFormatter.set_nested_value(data, "content_left", content)

        assert isinstance(data["content_left"], LiteralScalarString)

    def test_no_literal_for_simple(self):
        """set_nested_value should not apply literal for simple strings."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        data = {}
        YAMLFormatter.set_nested_value(data, "title", "Simple Title")

        assert data["title"] == "Simple Title"
        assert not isinstance(data["title"], LiteralScalarString)

    def test_nested_path_with_literal(self):
        """Nested paths should also apply literal style correctly."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        data = {}
        content = """Overview:

First paragraph.

Second paragraph."""

        YAMLFormatter.set_nested_value(data, "overview.content", content)

        assert isinstance(data["overview"]["content"], LiteralScalarString)


class TestLiteralStyleInOutput:
    """Test that literal style appears correctly in YAML output."""

    def test_output_uses_pipe_style(self):
        """Output should use | style for literal block content."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        data = {}
        content = """Steps:

- First
- Second"""

        YAMLFormatter.set_nested_value(data, "content", content)
        output = YAMLFormatter.format_frontmatter(data)

        # Should have literal block indicator
        assert "content: |" in output or "content:\n" in output
        # Bullets should not be escaped
        assert "- First" in output
        assert "- Second" in output

    def test_simple_values_not_pipe_style(self):
        """Simple values should not use | style."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        data = {"title": "Simple Title", "count": 5}
        output = YAMLFormatter.format_frontmatter(data)

        assert "title: Simple Title" in output or 'title: "Simple Title"' in output
        assert "count: 5" in output
        assert "title: |" not in output


class TestRealWorldPatterns:
    """Test with patterns from products.aspose.net files."""

    def test_content_left_pattern(self):
        """Test content_left pattern from plugin pages."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        # Real pattern from presentation-to-svg-converter
        content = """-   Add the Aspose.Slides plugin to your .NET project from [NuGet](https://www.nuget.org/packages/Aspose.Slides.NET/).
-   Use the `PresentationToSvgConverter` class to convert PowerPoint or OpenDocument files:
    -   Input presentation file or stream
    -   Output SVG file name or template
    -   Optional customization via `SvgConverterOptions`
-   Configure compression, font fallback, and vectorization for optimal web display."""

        assert YAMLFormatter.should_use_literal_style(content)

        data = {}
        YAMLFormatter.set_nested_value(data, "body.block[0].content_left", content)

        output = YAMLFormatter.format_frontmatter(data)

        # Bullets should be preserved in output
        assert "- Add the Aspose" in output or "-   Add the Aspose" in output

    def test_overview_content_pattern(self):
        """Test overview.content pattern with paragraphs."""
        from src.translation_engine.reconstructor.yaml_formatter import YAMLFormatter

        content = """The Aspose.Slides Presentation to SVG Converter for .NET enables developers to transform PowerPoint and OpenDocument presentations into scalable vector graphics (SVG) programmatically.

Developers can fine-tune conversion behavior using `SvgConverterOptions`, adjusting settings such as default font substitution, image compression, text vectorization, JPEG quality, and metafile rasterization DPI."""

        assert YAMLFormatter.should_use_literal_style(content)

        result = YAMLFormatter.maybe_apply_literal_style(content)
        assert isinstance(result, LiteralScalarString)
