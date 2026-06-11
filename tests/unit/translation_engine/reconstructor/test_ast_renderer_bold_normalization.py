"""
Unit tests for AST Renderer bold marker normalization (FIX-BOLD-01).

Tests the post-translation normalization that fixes corrupted bold markers
from MT models like m2m100_418m.
"""

import pytest

from src.translation_engine.reconstructor.ast_renderer import ASTRenderer


class TestBoldMarkerNormalization:
    """Tests for _normalize_bold_markers method (FIX-BOLD-01)."""

    @pytest.fixture
    def renderer(self):
        """Create fresh renderer instance."""
        return ASTRenderer()

    # === PATTERN 1: Heading-like text with single asterisks ===

    def test_normalize_heading_bold_corruption(self, renderer):
        """Fix most common corruption: * Text* → **Text**"""
        corrupted = "* Extrato de texto*"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Extrato de texto**"

    def test_normalize_heading_bold_with_spaces(self, renderer):
        """Fix corruption with spaces: * Text * → **Text**"""
        corrupted = "* Apresentação de Merging *"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Apresentação de Merging**"

    def test_normalize_multiple_headings(self, renderer):
        """Fix multiple corrupted headings in same text."""
        corrupted = """
        * Conversão de formato*
        * Extrato de texto*
        * Exportação PDF*
        """
        normalized = renderer._normalize_bold_markers(corrupted)

        assert "**Conversão de formato**" in normalized
        assert "**Extrato de texto**" in normalized
        assert "**Exportação PDF**" in normalized

    # === PATTERN 2: Asymmetric opening ===

    def test_normalize_asymmetric_opening_with_space(self, renderer):
        """Fix asymmetric opening: * text** → **text**"""
        corrupted = "* Apresentação **"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Apresentação**"

    def test_normalize_asymmetric_opening_multi_space(self, renderer):
        """Fix asymmetric with multiple spaces: *  text ** → **text**"""
        corrupted = "*  Conversão de Apresentação  **"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Conversão de Apresentação**"

    # === PATTERN 3: Asymmetric closing ===

    def test_normalize_asymmetric_closing(self, renderer):
        """Fix asymmetric closing: **text * → **text**"""
        corrupted = "**Exportação HTML *"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Exportação HTML**"

    def test_normalize_asymmetric_closing_with_space(self, renderer):
        """Fix asymmetric closing with space: ** text  * → **text**"""
        corrupted = "** Imagem  *"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Imagem**"

    # === PATTERN 4: Three asterisks corruption ===

    def test_normalize_three_asterisks_opening(self, renderer):
        """Fix three asterisks at start: ***text* → **text**"""
        corrupted = "***Texto*"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Texto**"

    def test_normalize_three_asterisks_closing(self, renderer):
        """Fix three asterisks at end: *text*** → **text**"""
        corrupted = "*Formato***"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert normalized == "**Formato**"

    # === EDGE CASES ===

    def test_preserve_valid_bold(self, renderer):
        """Don't modify already correct bold markers."""
        valid = "**Apresentação de Conversão**"
        normalized = renderer._normalize_bold_markers(valid)

        assert normalized == valid

    def test_preserve_italic_single_asterisk(self, renderer):
        """Don't modify legitimate italic (single asterisk)."""
        # Only normalize when text looks like a heading (starts with capital)
        valid = "This is *italic* text"
        normalized = renderer._normalize_bold_markers(valid)

        # Should NOT be changed because "italic" doesn't start with capital
        assert normalized == valid

    def test_preserve_bold_italic_combined(self, renderer):
        """Don't modify valid bold-italic ***text***"""
        valid = "***bold and italic***"
        normalized = renderer._normalize_bold_markers(valid)

        assert normalized == valid

    def test_empty_text(self, renderer):
        """Handle empty text gracefully."""
        assert renderer._normalize_bold_markers("") == ""
        assert renderer._normalize_bold_markers(None) == None

    def test_no_asterisks(self, renderer):
        """Handle text without asterisks gracefully."""
        text = "Plain text without formatting"
        normalized = renderer._normalize_bold_markers(text)

        assert normalized == text

    def test_preserve_asterisk_in_middle(self, renderer):
        """Don't modify asterisks that aren't formatting markers."""
        text = "Code uses * for multiplication"
        normalized = renderer._normalize_bold_markers(text)

        assert normalized == text

    # === REAL-WORLD CASES FROM COMMIT ===

    def test_real_world_text_extraction(self, renderer):
        """Fix actual corruption from commit: Extrato de texto"""
        corrupted = "### * Extrato de texto*"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert "**Extrato de texto**" in normalized

    def test_real_world_presentation_merging(self, renderer):
        """Fix actual corruption from commit: Apresentação de Merging"""
        corrupted = "### *Apresentação de Merging*"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert "**Apresentação de Merging**" in normalized

    def test_real_world_format_conversion(self, renderer):
        """Fix actual corruption: Conversão de formato de apresentação"""
        corrupted = "### * Conversão de formato de apresentação*"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert "**Conversão de formato de apresentação**" in normalized

    # === COMPLEX SCENARIOS ===

    def test_mixed_valid_and_corrupted(self, renderer):
        """Fix corrupted while preserving valid bold."""
        text = "**Valid Bold** and * Corrupted Bold* in same text"
        normalized = renderer._normalize_bold_markers(text)

        assert "**Valid Bold**" in normalized
        assert "**Corrupted Bold**" in normalized

    def test_multiple_paragraphs(self, renderer):
        """Handle multiple paragraphs with mixed formatting."""
        text = """
        Paragraph 1 with * Corrupted Title*.

        Paragraph 2 with **valid** bold.

        Paragraph 3 with * Another Corrupted Title* section.
        """
        normalized = renderer._normalize_bold_markers(text)

        # Capitalized text that looks like headings should be normalized
        assert "**Corrupted Title**" in normalized
        assert "**valid**" in normalized
        assert "**Another Corrupted Title**" in normalized

    def test_non_english_characters(self, renderer):
        """Handle non-English characters in corrupted bold."""
        corrupted = "* Présentation de Conversão* with accents"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert "**Présentation de Conversão**" in normalized

    def test_portuguese_unicode_uppercase(self, renderer):
        """Handle Portuguese Unicode uppercase (Ú, É, etc.) in corrupted bold."""
        # Real-world case: "Latest Articles" → "* Últimos artigos*"
        corrupted = "## * Últimos artigos*"
        normalized = renderer._normalize_bold_markers(corrupted)

        assert "**Últimos artigos**" in normalized
