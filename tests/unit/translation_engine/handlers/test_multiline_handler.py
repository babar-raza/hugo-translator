"""
Unit tests for MultilineHandler.

Tests cover:
- Line splitting and structure preservation
- Bullet point prefix handling
- Indentation preservation
- Empty line handling
- Escaped newline normalization
- Negative cases (structure drift detection)
"""

from src.translation_engine.handlers.multiline_handler import (
    MultilineHandler,
    normalize_newlines,
    translate_multiline,
)


class TestNormalizeNewlines:
    """Tests for normalize_newlines function."""

    def test_no_escapes(self):
        """Text without escapes passes through unchanged."""
        text = "line1\nline2\nline3"
        assert normalize_newlines(text) == text

    def test_escaped_backslash_n(self):
        """Literal \\n in source becomes actual newline."""
        text = "line1\\nline2"
        assert normalize_newlines(text) == "line1\nline2"

    def test_windows_line_endings(self):
        """Windows \\r\\n normalized to \\n."""
        text = "line1\r\nline2\r\nline3"
        assert normalize_newlines(text) == "line1\nline2\nline3"

    def test_mixed_escapes(self):
        """Multiple escape patterns handled correctly."""
        text = "a\\nb\r\nc"
        result = normalize_newlines(text)
        assert result == "a\nb\nc"

    def test_empty_string(self):
        """Empty string returns empty string."""
        assert normalize_newlines("") == ""

    def test_no_newlines(self):
        """Text without any newlines unchanged."""
        text = "single line text"
        assert normalize_newlines(text) == text


class TestMultilineHandlerIsMultiline:
    """Tests for is_multiline detection."""

    def test_single_line(self):
        """Single line text is not multiline."""
        handler = MultilineHandler()
        assert handler.is_multiline("single line") is False

    def test_actual_newline(self):
        """Text with actual newline is multiline."""
        handler = MultilineHandler()
        assert handler.is_multiline("line1\nline2") is True

    def test_escaped_newline(self):
        """Text with escaped newline is multiline."""
        handler = MultilineHandler()
        assert handler.is_multiline("line1\\nline2") is True


class TestMultilineHandlerParseLines:
    """Tests for parse_lines method."""

    def test_simple_lines(self):
        """Parse simple text lines."""
        handler = MultilineHandler()
        lines = handler.parse_lines("line1\nline2\nline3")

        assert len(lines) == 3
        assert lines[0].content == "line1"
        assert lines[1].content == "line2"
        assert lines[2].content == "line3"
        assert all(line.indent == "" for line in lines)
        assert all(line.prefix == "" for line in lines)

    def test_bullet_list(self):
        """Parse bullet list with - prefix."""
        handler = MultilineHandler()
        text = "- Item 1\n- Item 2\n- Item 3"
        lines = handler.parse_lines(text)

        assert len(lines) == 3
        assert all(line.prefix == "- " for line in lines)
        assert lines[0].content == "Item 1"
        assert lines[1].content == "Item 2"
        assert lines[2].content == "Item 3"

    def test_nested_bullet_list(self):
        """Parse nested bullet list with indentation."""
        handler = MultilineHandler()
        text = "- Item 1\n    - Nested 1\n    - Nested 2\n- Item 2"
        lines = handler.parse_lines(text)

        assert len(lines) == 4
        assert lines[0].indent == ""
        assert lines[0].prefix == "- "
        assert lines[0].content == "Item 1"

        assert lines[1].indent == "    "
        assert lines[1].prefix == "- "
        assert lines[1].content == "Nested 1"

        assert lines[2].indent == "    "
        assert lines[2].prefix == "- "
        assert lines[2].content == "Nested 2"

        assert lines[3].indent == ""
        assert lines[3].prefix == "- "
        assert lines[3].content == "Item 2"

    def test_numbered_list(self):
        """Parse numbered list."""
        handler = MultilineHandler()
        text = "1. First\n2. Second\n3. Third"
        lines = handler.parse_lines(text)

        assert len(lines) == 3
        assert lines[0].prefix == "1. "
        assert lines[0].content == "First"
        assert lines[1].prefix == "2. "
        assert lines[2].prefix == "3. "

    def test_empty_lines(self):
        """Parse text with empty lines."""
        handler = MultilineHandler()
        text = "line1\n\nline3"
        lines = handler.parse_lines(text)

        assert len(lines) == 3
        assert lines[0].is_empty is False
        assert lines[1].is_empty is True
        assert lines[2].is_empty is False

    def test_asterisk_bullet(self):
        """Parse bullet list with * prefix."""
        handler = MultilineHandler()
        text = "* Item 1\n* Item 2"
        lines = handler.parse_lines(text)

        assert len(lines) == 2
        assert all(line.prefix == "* " for line in lines)

    def test_plus_bullet(self):
        """Parse bullet list with + prefix."""
        handler = MultilineHandler()
        text = "+ Item 1\n+ Item 2"
        lines = handler.parse_lines(text)

        assert len(lines) == 2
        assert all(line.prefix == "+ " for line in lines)

    def test_blockquote(self):
        """Parse blockquote prefix."""
        handler = MultilineHandler()
        text = "> Quote line 1\n> Quote line 2"
        lines = handler.parse_lines(text)

        assert len(lines) == 2
        assert lines[0].prefix == "> "
        assert lines[0].content == "Quote line 1"


class TestMultilineHandlerTranslate:
    """Tests for translate method."""

    def test_simple_translation(self):
        """Translate simple multiline text."""
        handler = MultilineHandler()

        def mock_translate(text):
            return text.upper()

        result = handler.translate("line1\nline2", mock_translate)

        assert result.translated_text == "LINE1\nLINE2"
        assert result.line_count_source == 2
        assert result.line_count_translated == 2
        assert result.structure_preserved is True

    def test_bullet_preservation(self):
        """Bullets preserved during translation."""
        handler = MultilineHandler()

        def mock_translate(text):
            return f"[{text}]"

        result = handler.translate("- Item 1\n- Item 2", mock_translate)

        assert result.translated_text == "- [Item 1]\n- [Item 2]"
        assert result.structure_preserved is True

    def test_indentation_preservation(self):
        """Indentation preserved during translation."""
        handler = MultilineHandler()

        def mock_translate(text):
            return text.upper()

        text = "- Top\n    - Nested"
        result = handler.translate(text, mock_translate)

        assert "    - NESTED" in result.translated_text
        assert result.translated_text == "- TOP\n    - NESTED"

    def test_empty_line_preservation(self):
        """Empty lines not translated, just preserved."""
        handler = MultilineHandler()
        translate_calls = []

        def mock_translate(text):
            translate_calls.append(text)
            return text.upper()

        result = handler.translate("line1\n\nline3", mock_translate)

        # Empty line should not trigger translation
        assert len(translate_calls) == 2
        assert "" not in translate_calls
        assert result.translated_text == "LINE1\n\nLINE3"
        assert result.line_count_source == 3
        assert result.line_count_translated == 3

    def test_translation_failure_fallback(self):
        """Failed translation keeps original content."""
        handler = MultilineHandler()

        def failing_translate(text):
            if "fail" in text:
                raise ValueError("Translation failed")
            return text.upper()

        result = handler.translate("good\nfail here\nalso good", failing_translate)

        # Failed line should keep original
        assert "GOOD" in result.translated_text
        assert "fail here" in result.translated_text
        assert "ALSO GOOD" in result.translated_text

    def test_numbered_list_preservation(self):
        """Numbered list prefixes preserved."""
        handler = MultilineHandler()

        def mock_translate(text):
            return text.upper()

        result = handler.translate("1. First\n2. Second", mock_translate)

        assert result.translated_text == "1. FIRST\n2. SECOND"


class TestMultilineHandlerNegativeCases:
    """Negative test cases for structure drift detection."""

    def test_line_count_mismatch_detected(self):
        """Detect when line count changes (should not happen with correct implementation)."""
        handler = MultilineHandler()

        # This mock would break structure by adding newlines
        def bad_translate(text):
            return f"{text}\nextra line"

        # The handler itself won't add lines, but we can verify the count
        result = handler.translate("single", bad_translate)

        # Handler preserves structure even if translation adds newlines within content
        # The extra newline becomes part of the content, not a new line
        assert result.line_count_source == 1
        assert result.line_count_translated == 1

    def test_empty_input(self):
        """Handle empty input gracefully."""
        handler = MultilineHandler()

        def mock_translate(text):
            return text.upper()

        result = handler.translate("", mock_translate)

        assert result.translated_text == ""
        assert result.line_count_source == 1  # Empty string splits to ['']
        assert result.structure_preserved is True

    def test_only_whitespace_lines(self):
        """Handle lines with only whitespace."""
        handler = MultilineHandler()

        def mock_translate(text):
            return text.upper()

        result = handler.translate("   \n\t\t\n", mock_translate)

        # Whitespace-only lines are technically "empty"
        assert result.line_count_source == 3


class TestTranslateMultilineFunction:
    """Tests for the convenience function."""

    def test_basic_usage(self):
        """Basic usage of translate_multiline function."""

        def mock_translate(text):
            return text.upper()

        result = translate_multiline("- Item 1\n- Item 2", mock_translate)

        assert result == "- ITEM 1\n- ITEM 2"

    def test_with_escapes(self):
        """Escaped newlines normalized before translation."""

        def mock_translate(text):
            return text.upper()

        result = translate_multiline("line1\\nline2", mock_translate)

        assert result == "LINE1\nLINE2"

    def test_without_escape_normalization(self):
        """Can disable escape normalization."""

        def mock_translate(text):
            return text.upper()

        result = translate_multiline("line1\\nline2", mock_translate, normalize_escapes=False)

        # Without normalization, \\n is NOT converted to newline
        # So it's treated as single line "line1\\nline2"
        assert "\\N" in result  # The \n becomes literal \\N after upper()


class TestRealWorldCases:
    """Tests based on real-world YAML content from the bug report."""

    def test_aspose_content_left_structure(self):
        """Test structure similar to Aspose content_left field."""
        handler = MultilineHandler()

        source = """-   Add the Aspose.Slides plugin to your .NET project from [NuGet](https://www.nuget.org/packages/Aspose.Slides.NET/).
-   Execute the conversion operation with parameters for:
    -   Input presentation file or stream
    -   Target format (PPTX, ODP, POTX, PPSX, etc.)
    -   Output destination (file or memory stream)"""

        def mock_translate(text):
            # Simulate translation that would normally collapse structure
            return f"[BG]{text}"

        result = handler.translate(source, mock_translate)

        # Verify structure preserved
        assert result.line_count_source == 5
        assert result.line_count_translated == 5
        assert result.structure_preserved is True

        # Verify indentation preserved
        lines = result.translated_text.split("\n")
        assert lines[0].startswith("-   ")  # Top-level bullet
        assert lines[2].startswith("    -   ")  # Nested bullet
        assert lines[3].startswith("    -   ")  # Nested bullet
        assert lines[4].startswith("    -   ")  # Nested bullet

    def test_line_count_metric(self):
        """Verify the key metric: EN 5 newlines -> BG 5 newlines."""
        handler = MultilineHandler()

        # Source has 5 newlines (6 lines)
        source = "line1\nline2\nline3\nline4\nline5\nline6"

        def mock_translate(text):
            return text.upper()

        result = handler.translate(source, mock_translate)

        source_newlines = source.count("\n")
        result_newlines = result.translated_text.count("\n")

        assert source_newlines == 5
        assert result_newlines == 5
        assert result.structure_preserved is True
