"""
Unit tests for InlineFormatProtector (HP-05).

Tests inline markdown formatting protection and restoration during translation.
"""

import pytest

from src.translation_engine.extractor.inline_format_protector import (
    InlineFormatProtector,
    ProtectedInlineSegment,
)


class TestInlineFormatProtector:
    """Tests for inline format protection (HP-05)."""

    @pytest.fixture
    def protector(self):
        """Create fresh protector instance."""
        return InlineFormatProtector()

    # === BOLD PROTECTION ===

    def test_protect_bold_asterisk(self, protector):
        """Bold markers pass through unchanged (V2: MT models handle them well)."""
        text = "**bold text**"
        result = protector.protect(text)

        # V2: Bold markers are NOT protected (MT models preserve them)
        assert result.protected == text
        assert "**" in result.protected
        assert "bold text" in result.protected

    def test_protect_bold_underscore(self, protector):
        """Bold with underscores passes through unchanged (V2)."""
        text = "__bold text__"
        result = protector.protect(text)

        # V2: Bold markers are NOT protected
        assert result.protected == text
        assert "__" in result.protected

    def test_restore_bold(self, protector):
        """Bold markers preserved through translation cycle (V2)."""
        original = "**File Size Reduction**"
        protected = protector.protect(original)

        # Simulate translation - bold markers pass through unchanged
        translated = protected.protected.replace(
            "File Size Reduction", "Dateigr\u00f6\u00dfe Reduzierung"
        )
        restored = protector.restore(protected, translated)

        assert "**Dateigr\u00f6\u00dfe Reduzierung**" in restored

    def test_bold_in_sentence(self, protector):
        """Bold within sentence is handled correctly (V2: unchanged)."""
        text = "1. **File Size Reduction**: PPTX files are smaller"
        result = protector.protect(text)
        restored = protector.restore(result, result.protected)

        # V2: Text unchanged through protect/restore cycle
        assert "**File Size Reduction**" in restored
        assert ": PPTX files are smaller" in restored

    # === LINK PROTECTION ===

    def test_protect_link(self, protector):
        """Links pass through unchanged (V2: MT models handle markdown)."""
        text = "[Documentation](https://docs.aspose.net/)"
        result = protector.protect(text)

        # V2: Link structure preserved as-is (protection disabled)
        assert result.protected == text
        assert "[Documentation]" in result.protected
        assert "(https://docs.aspose.net/)" in result.protected

    def test_restore_link_preserves_url(self, protector):
        """Link URL preserved through translation cycle (V2)."""
        original = "[See Documentation](https://docs.aspose.net/slides/)"
        protected = protector.protect(original)

        # Simulate translation of link text only
        translated = protected.protected.replace("See Documentation", "Siehe Dokumentation")
        restored = protector.restore(protected, translated)

        # V2: URL preserved (MT models trained on markdown syntax)
        assert "[Siehe Dokumentation]" in restored
        assert "(https://docs.aspose.net/slides/)" in restored

    def test_link_url_not_translated(self, protector):
        """Link URL should never be modified (V2)."""
        original = "[Link](https://example.com/path?query=value#anchor)"
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Link unchanged through cycle
        assert "https://example.com/path?query=value#anchor" in restored

    def test_multiple_links(self, protector):
        """Multiple links preserved through cycle (V2)."""
        text = "[Link1](https://a.com) and [Link2](https://b.com)"
        result = protector.protect(text)
        restored = protector.restore(result, result.protected)

        # V2: Both links unchanged
        assert "[Link1](https://a.com)" in restored
        assert "[Link2](https://b.com)" in restored

    def test_link_with_title(self, protector):
        """Link with title attribute is handled (V2: unchanged)."""
        text = '[Link](https://example.com "Title")'
        result = protector.protect(text)

        # V2: Link with title unchanged
        assert result.protected == text

    # === INLINE CODE PROTECTION ===

    def test_protect_inline_code(self, protector):
        """Inline code content protected with single-token placeholder (V2)."""
        text = "Use `SaveFormat.Pptx` here"
        result = protector.protect(text)

        # V2: Uses ⟦CODE####⟧ format, backticks preserved
        assert "⟦CODE" in result.protected
        assert "⟧" in result.protected
        assert "`" in result.protected  # Backticks preserved
        assert "SaveFormat.Pptx" not in result.protected  # Content replaced with token

    def test_restore_inline_code(self, protector):
        """Inline code content restored from token (V2)."""
        original = "`code`"
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Token replaced back with original content
        assert restored == "`code`"

    def test_inline_code_not_translated(self, protector):
        """Code content is preserved exactly (V2: protected as token)."""
        original = "Use `Presentation.Save()` method"
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Code content restored unchanged
        assert "`Presentation.Save()`" in restored

    # === ITALIC PROTECTION ===

    def test_protect_italic(self, protector):
        """Italic markers pass through unchanged (V2: MT models handle them)."""
        text = "*italic text*"
        result = protector.protect(text)

        # V2: Italic markers are NOT protected
        assert result.protected == text
        assert "*" in result.protected
        assert "italic text" in result.protected

    def test_restore_italic(self, protector):
        """Italic markers preserved through cycle (V2)."""
        original = "*emphasis*"
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Text unchanged
        assert restored == "*emphasis*"

    # === IMAGE PROTECTION ===

    def test_protect_image(self, protector):
        """Image source protected with single-token placeholder (V2)."""
        text = "![Alt text](https://example.com/image.png)"
        result = protector.protect(text)

        # V2: Uses ⟦IMG####⟧ format for source only
        assert "⟦IMG" in result.protected
        assert "⟧" in result.protected
        assert "![Alt text]" in result.protected  # Alt text unchanged
        assert "https://example.com/image.png" not in result.protected  # Source replaced with token

    def test_restore_image(self, protector):
        """Image source restored from token (V2)."""
        original = "![Screenshot](https://example.com/screenshot.png)"
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Token replaced back with original source
        assert "![Screenshot](https://example.com/screenshot.png)" in restored

    # === BOLD-ITALIC PROTECTION ===

    def test_protect_bold_italic(self, protector):
        """Bold-italic (***text***) passes through unchanged (V2)."""
        text = "***important***"
        result = protector.protect(text)

        # V2: Bold-italic markers are NOT protected
        assert result.protected == text
        assert "***" in result.protected

    def test_restore_bold_italic(self, protector):
        """Bold-italic preserved through cycle (V2)."""
        original = "***important***"
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Text unchanged
        assert "***important***" in restored

    # === MIXED FORMATTING ===

    def test_mixed_bold_and_link(self, protector):
        """Both bold and links handled correctly (V2: unchanged)."""
        text = "**Important**: See [docs](https://example.com)"
        result = protector.protect(text)

        # V2: Both bold and links pass through unchanged
        assert "**Important**" in result.protected
        assert "[docs](https://example.com)" in result.protected

    def test_restoration_order(self, protector):
        """Mixed formatting restores correctly (V2)."""
        original = "1. **File Size**: See [API](https://api.example.com) reference"
        protected = protector.protect(original)

        # Simulate translation
        translated = protected.protected.replace("File Size", "Dateigr\u00f6\u00dfe").replace(
            "reference", "Referenz"
        )
        restored = protector.restore(protected, translated)

        # V2: Both preserved through translation
        assert "**Dateigr\u00f6\u00dfe**" in restored
        assert "[API](https://api.example.com)" in restored

    def test_complex_document_structure(self, protector):
        """Complex document with multiple formatting types (V2)."""
        original = """
**Bold title**

Here is some *italic* text and a [link](https://example.com).

Use `code` for technical terms.
"""
        protected = protector.protect(original)
        restored = protector.restore(protected, protected.protected)

        # V2: Bold/italic/links unchanged, code content protected
        assert "**Bold title**" in restored
        assert "*italic*" in restored
        assert "[link](https://example.com)" in restored
        assert "`code`" in restored

    # === EDGE CASES ===

    def test_no_formatting(self, protector):
        """Text without formatting passes through unchanged."""
        text = "Plain text without any formatting"
        result = protector.protect(text)

        assert result.protected == text
        assert result.original == text

    def test_empty_string(self, protector):
        """Empty string handled gracefully."""
        result = protector.protect("")
        assert result.protected == ""

    def test_has_inline_formatting_detection(self, protector):
        """Detection of inline formatting works."""
        assert protector.has_inline_formatting("**bold**")
        assert protector.has_inline_formatting("[link](url)")
        assert protector.has_inline_formatting("`code`")
        assert protector.has_inline_formatting("*italic*")
        assert not protector.has_inline_formatting("plain text")

    def test_reset_clears_state(self, protector):
        """Reset clears internal state (V2: use code which is tokenized)."""
        # V2: Use inline code which IS tokenized (not links which are unchanged)
        protector.protect("text with `inline_code` here")
        assert protector._counter > 0

        protector.reset()
        assert protector._counter == 0

    def test_nested_formatting(self, protector):
        """Nested formatting is handled (V2: unchanged)."""
        # Bold link text
        text = "[**bold link**](https://example.com)"
        result = protector.protect(text)
        restored = protector.restore(result, result.protected)

        # V2: Nested formatting unchanged
        assert "**bold link**" in restored
        assert "(https://example.com)" in restored

    def test_adjacent_formatting(self, protector):
        """Adjacent formatting elements are handled (V2: unchanged)."""
        text = "**bold** and *italic*"
        result = protector.protect(text)
        restored = protector.restore(result, result.protected)

        # V2: Both unchanged
        assert "**bold**" in restored
        assert "*italic*" in restored


class TestProtectedInlineSegment:
    """Tests for ProtectedInlineSegment dataclass."""

    def test_dataclass_creation(self):
        """ProtectedInlineSegment can be created (V2 format)."""
        segment = ProtectedInlineSegment(
            original="**bold**",
            protected="**bold**",  # V2: Bold unchanged
            placeholder_map={},
            url_map={},
        )
        assert segment.original == "**bold**"
        assert segment.protected == "**bold**"

    def test_url_map_storage(self):
        """URL map stores image URLs correctly (V2: links unchanged)."""
        # V2: Images use token placeholders, links don't
        segment = ProtectedInlineSegment(
            original="![alt](https://example.com/img.png)",
            protected="![alt](⟦IMG0000⟧)",
            url_map={"⟦IMG0000⟧": "https://example.com/img.png"},
        )
        assert segment.url_map["⟦IMG0000⟧"] == "https://example.com/img.png"
