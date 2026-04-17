"""Tests for terminology protection (HP-04)."""

from pathlib import Path

import pytest

from src.translation_engine.terminology import TerminologyManager


@pytest.fixture
def terminology_manager():
    """Create TerminologyManager with test terms."""
    config_path = Path("config/terminology/protected_terms.yaml")
    if not config_path.exists():
        pytest.skip("Config file not created yet")
    tm = TerminologyManager(str(config_path))
    return tm


class TestTerminologyProtection:
    """Tests for terminology protection (HP-04)."""

    def test_protect_brand_name(self, terminology_manager):
        """Brand names are protected from translation."""
        text = "Use Aspose.Slides for presentations"
        result = terminology_manager.protect(text, site="kb.aspose.net")

        # Should have placeholder
        assert "Aspose.Slides" not in result.protected_text or "TERM_" in result.protected_text

        # Should restore correctly
        restored = terminology_manager.restore(result)
        assert "Aspose.Slides" in restored

    def test_protect_platform_term(self, terminology_manager):
        """Platform terms like .NET Framework are protected."""
        text = "Target .NET Framework 4.0+ or .NET Core 3.1+"
        result = terminology_manager.protect(text, site="kb.aspose.net")
        restored = terminology_manager.restore(result)

        assert ".NET Framework" in restored
        assert ".NET Core" in restored

    def test_protect_version_pattern(self, terminology_manager):
        """Version numbers like 6.0+ are protected."""
        text = "Requires .NET 6.0+ for best performance"
        result = terminology_manager.protect(text, site="kb.aspose.net")
        restored = terminology_manager.restore(result)

        assert "6.0+" in restored

    def test_case_sensitivity_brand(self, terminology_manager):
        """Case-sensitive terms only match exact case."""
        # Lowercase should NOT match (case_sensitive: true)
        text = "aspose.slides is lowercase"
        result = terminology_manager.protect(text, site="kb.aspose.net")

        # Should not be protected (no placeholder)
        assert "aspose.slides" in result.protected_text

    def test_multiple_terms_in_sentence(self, terminology_manager):
        """Multiple terms in same text are all protected."""
        text = "Use Aspose.Slides with .NET Core and Visual Studio"
        result = terminology_manager.protect(text, site="kb.aspose.net")
        restored = terminology_manager.restore(result)

        assert "Aspose.Slides" in restored
        assert ".NET Core" in restored
        assert "Visual Studio" in restored

    def test_technical_term_api_reference(self, terminology_manager):
        """API Reference is protected (case-insensitive)."""
        text = "See the API Reference for details"
        result = terminology_manager.protect(text, site="kb.aspose.net")
        restored = terminology_manager.restore(result)

        assert "API Reference" in restored

    def test_code_construct_saveformat(self, terminology_manager):
        """Code constructs like SaveFormat.Pdf are protected."""
        text = "Use SaveFormat.Pdf for PDF output"
        result = terminology_manager.protect(text, site="kb.aspose.net")
        restored = terminology_manager.restore(result)

        assert "SaveFormat.Pdf" in restored

    def test_config_file_loads(self):
        """Config file loads without errors."""
        config_path = Path("config/terminology/protected_terms.yaml")
        if not config_path.exists():
            pytest.skip("Config file not created yet")

        tm = TerminologyManager(str(config_path))

        # Should have loaded rules
        rules = tm.get_rules()
        assert len(rules) > 0

    def test_get_rules_returns_all_terms(self, terminology_manager):
        """Get rules returns all configured terms."""
        rules = terminology_manager.get_rules()

        # Should have multiple rules (20+ terms)
        assert len(rules) >= 20

        # Check some specific terms exist
        patterns = [rule.pattern if rule.pattern else rule.term for rule in rules]
        assert any("Aspose.Slides" in str(p) for p in patterns)
        assert any(".NET" in str(p) for p in patterns)
