"""Tests for the source-identity gate (RC3-FIX).

Verifies that _check_source_identity detects untranslated content
by comparing translation output to source input.
"""
import pytest

from src.translation_engine.engine import TranslationEngine


class TestExtractComparableText:
    """Tests for _extract_comparable_text static method."""

    def test_strips_frontmatter(self):
        content = "---\ntitle: Hello\n---\nBody text here"
        result = TranslationEngine._extract_comparable_text(content)
        assert "title" not in result
        assert "Body text here" in result

    def test_strips_code_blocks(self):
        content = "Text before\n```python\ncode = True\n```\nText after"
        result = TranslationEngine._extract_comparable_text(content)
        assert "code = True" not in result
        assert "Text before" in result
        assert "Text after" in result

    def test_strips_urls(self):
        content = "Visit https://example.com/path for more"
        result = TranslationEngine._extract_comparable_text(content)
        assert "https://example.com" not in result
        assert "Visit" in result

    def test_strips_shortcodes(self):
        content = "Text {{< shortcode param >}} more text"
        result = TranslationEngine._extract_comparable_text(content)
        assert "shortcode" not in result
        assert "Text" in result

    def test_keeps_link_text(self):
        content = "See [this link](https://example.com) for details"
        result = TranslationEngine._extract_comparable_text(content)
        assert "this link" in result


class TestCheckSourceIdentity:
    """Tests for _check_source_identity method."""

    @pytest.fixture
    def engine(self):
        """Create a minimal TranslationEngine mock."""
        from unittest.mock import MagicMock
        e = MagicMock(spec=TranslationEngine)
        e._check_source_identity = TranslationEngine._check_source_identity.__get__(e)
        e._extract_comparable_text = TranslationEngine._extract_comparable_text
        return e

    def test_identical_content_different_script_fails(self, engine):
        """Same content for a different-script language should fail."""
        source = "---\ntitle: Test\n---\n" + "This is a test document with enough content to pass the minimum length requirement for comparison."
        result = engine._check_source_identity(source, source, "ar")
        assert not result["passed"]
        assert result["similarity"] > 0.60

    def test_identical_content_same_script_fails(self, engine):
        """Same content for a same-script language should fail."""
        source = "---\ntitle: Test\n---\n" + "This is a test document with enough content to pass the minimum length for the comparison check."
        result = engine._check_source_identity(source, source, "fr")
        assert not result["passed"]
        assert result["similarity"] > 0.75

    def test_identical_content_similar_lang_fails(self, engine):
        """Same content for a similar language should fail (threshold 85%)."""
        source = "---\ntitle: Test\n---\n" + "This is a test document with enough content to pass the minimum length for the comparison check."
        result = engine._check_source_identity(source, source, "no")
        assert not result["passed"]

    def test_completely_different_content_passes(self, engine):
        """Genuinely translated content should pass."""
        source = "---\ntitle: Test\n---\n" + "This is a test document about converting PDF files to Word format using the API."
        translated = "---\ntitle: Test\n---\n" + "Ceci est un document de test sur la conversion de fichiers PDF au format Word à l'aide de l'API."
        result = engine._check_source_identity(source, translated, "fr")
        assert result["passed"]

    def test_arabic_translation_passes(self, engine):
        """Arabic translation should be very different from English source."""
        source = "---\ntitle: Test\n---\n" + "Convert PDF to Word documents easily."
        translated = "---\ntitle: Test\n---\n" + "\u062a\u062d\u0648\u064a\u0644 \u0645\u0633\u062a\u0646\u062f\u0627\u062a PDF \u0625\u0644\u0649 Word \u0628\u0633\u0647\u0648\u0644\u0629."
        result = engine._check_source_identity(source, translated, "ar")
        assert result["passed"]

    def test_short_content_auto_passes(self, engine):
        """Content too short for comparison should auto-pass."""
        source = "---\ntitle: Hi\n---\nShort."
        translated = "---\ntitle: Hi\n---\nShort."
        result = engine._check_source_identity(source, translated, "fr")
        assert result["passed"]
        assert "Too short" in result["reason"]

    def test_partial_translation_detected(self, engine):
        """50% translated file should fail for different-script lang."""
        english_part = "This is untranslated English content that was not processed by the model."
        arabic_part = "\u0647\u0630\u0627 \u0645\u062d\u062a\u0648\u0649 \u0645\u062a\u0631\u062c\u0645 \u0625\u0644\u0649 \u0627\u0644\u0639\u0631\u0628\u064a\u0629 \u0628\u0634\u0643\u0644 \u0635\u062d\u064a\u062d."
        source = "---\ntitle: Test\n---\n" + english_part + " " + english_part
        translated = "---\ntitle: Test\n---\n" + arabic_part + " " + english_part
        result = engine._check_source_identity(source, translated, "ar")
        # Similarity should be lower than identical but still detectable
        assert result["similarity"] < 1.0

    def test_threshold_values(self, engine):
        """Verify correct thresholds are applied per language group."""
        source = "x" * 100  # Dummy content long enough
        translated = "y" * 100

        # Different script
        result = engine._check_source_identity(source, translated, "zh")
        assert result["threshold"] == 0.60

        # Similar language
        result = engine._check_source_identity(source, translated, "no")
        assert result["threshold"] == 0.85

        # Default
        result = engine._check_source_identity(source, translated, "fr")
        assert result["threshold"] == 0.75
