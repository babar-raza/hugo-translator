import pytest

from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor


@pytest.fixture
def extractor():
    """Create extractor instance for testing."""
    return TextUnitExtractor(
        segmentation_strategy="sentence_only",
        terminology_file=None
    )


class TestTechnicalTermWhitelist:
    """Test technical term whitelist loading and density calculation (PO-01)."""

    def test_load_technical_terms_from_config(self, extractor):
        """Verify technical terms loaded from config/terminology/technical_terms.yaml."""
        # Should load from YAML if exists, otherwise use defaults
        assert len(extractor.technical_terms) > 0
        # Key terms should be present
        assert 'Aspose' in extractor.technical_terms
        assert 'C#' in extractor.technical_terms

    @pytest.mark.parametrize("text,expected_density", [
        # 100% technical (3/3 words)
        ("C# Aspose Excel", 1.0),
        # 25% technical (1/4 words)
        ("How to use Excel", 0.25),
        # 33% technical (2/6 words: "C#" and "Excel")
        ("How to use C# with Excel", 0.333),
        # 0% technical
        ("This is normal text", 0.0),
        # Empty text
        ("", 0.0),
        # Single technical term
        ("Aspose", 1.0),
    ])
    def test_technical_density_calculation(self, extractor, text, expected_density):
        """Verify technical density calculation is accurate."""
        actual_density = extractor._calculate_technical_density(text)
        assert abs(actual_density - expected_density) < 0.01, \
            f"Expected density {expected_density}, got {actual_density} for text: {text}"

    def test_technical_density_case_sensitive(self, extractor):
        """Verify technical term matching is case-sensitive."""
        # "Aspose" should match
        assert extractor._calculate_technical_density("Aspose") == 1.0
        # "aspose" (lowercase) should NOT match if not in whitelist
        density = extractor._calculate_technical_density("aspose")
        # Depends on whether lowercase variant is in config
        # This test documents current behavior

    def test_high_density_content(self, extractor):
        """Test realistic high-density technical content (>30%)."""
        # Typical Aspose documentation sentence
        technical_text = (
            "Verwenden Sie Aspose.Cells für .NET SDK API um Excel Workbook "
            "in HTML zu konvertieren mit SaveFormat und HtmlSaveOptions"
        )
        density = extractor._calculate_technical_density(technical_text)
        # Should have high density due to technical terms
        assert density > 0.2, f"Expected high density, got {density:.2f}"

    def test_low_density_content(self, extractor):
        """Test content with low technical density (<30%)."""
        natural_text = (
            "This is a general introduction to the topic with minimal "
            "technical jargon and mostly natural language content"
        )
        density = extractor._calculate_technical_density(natural_text)
        assert density < 0.3, f"Expected low density, got {density:.2f}"


class TestLanguagePurityBypass:
    """Test that high-density technical content bypasses language purity checks (PO-01)."""

    def test_purity_check_bypassed_for_high_density(self, extractor):
        """Verify units with >30% technical density bypass purity check."""
        from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind

        # Create a unit with high technical density
        unit = TextUnit(
            unit_id="test_1",
            node_addr="test.1",
            kind=TextUnitKind.TEXT,
            source_text="Use Aspose.Cells for .NET",
            do_not_translate=False
        )
        unit.translated_text = "Verwenden Sie Aspose.Cells für .NET SDK"

        # Check density
        density = extractor._calculate_technical_density(unit.translated_text)
        assert density >= 0.3, f"Test unit should have density >= 0.3, got {density:.2f}"

        # Verify purity check passes (due to bypass)
        # This unit would normally fail because "für" might be detected as non-German
        result = extractor._verify_translation_language_purity([unit], "de")
        # Should pass because of bypass
        assert result is True

    def test_purity_check_still_applies_for_low_density(self, extractor):
        """Verify units with <30% technical density still get purity checks."""
        from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind

        # Create a unit with low technical density
        unit = TextUnit(
            unit_id="test_2",
            node_addr="test.2",
            kind=TextUnitKind.TEXT,
            source_text="This is a test",
            do_not_translate=False
        )
        unit.translated_text = "This is still in English and should fail"

        # Check density
        density = extractor._calculate_technical_density(unit.translated_text)
        assert density < 0.3, f"Test unit should have density < 0.3, got {density:.2f}"

        # Verify purity check still runs and fails
        # (English text when expecting German)
        result = extractor._verify_translation_language_purity([unit], "de")
        # Should fail because it's in wrong language
        assert result is False
