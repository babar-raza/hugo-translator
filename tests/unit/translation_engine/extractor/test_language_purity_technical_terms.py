"""
Test language purity check with technical terms in Arabic.

Issue: Arabic text with Latin script technical terms (e.g., "Azure", "Presentation")
was being detected as Italian by langdetect, causing language purity failures.

Fix:
1. Added "Azure", "Presentation", and other common terms to technical_terms.yaml
2. Added Romance languages (it, es, fr, pt) to Arabic's script-similar languages

Expected behavior:
- Text with ≥25% technical density bypasses language purity check
- Text with <25% technical density but detected as Romance language is accepted
"""

import sys
from unittest.mock import MagicMock

from src.translation_engine.extractor.text_unit import TextUnit, TextUnitKind
from src.translation_engine.extractor.text_unit_extractor import TextUnitExtractor
from src.utils.models import BodyRules, OutputLayout, SiteProfile


def _make_text_unit(unit_id: str, source_text: str, translated_text: str) -> TextUnit:
    """Create a minimal TextUnit for language purity checks."""
    return TextUnit(
        unit_id=unit_id,
        node_addr=f"{unit_id}.t1",
        kind=TextUnitKind.TEXT,
        source_text=source_text,
        translated_text=translated_text,
        do_not_translate=False,
    )


def test_arabic_with_azure_presentation_technical_density():
    """Test that 'Azure Presentation' counts as technical terms in Arabic text."""

    site_profile = SiteProfile(
        site_id="kb.aspose.net",
        content_roots=["/content/kb.aspose.net/slides/en"],
        default_source_lang="en",
        target_langs=["ar"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        )
    )

    extractor = TextUnitExtractor(site_profile=site_profile)

    # Test text: Arabic with "Azure Presentation"
    text = "معالجة Azure Presentation"

    # Calculate technical density
    density = extractor._calculate_technical_density(text)

    # Should have 66% density (2 out of 3 words: "Azure" and "Presentation")
    assert density >= 0.25, f"Expected density ≥0.25, got {density:.2f}. Text: {text}"
    print(f"✅ Technical density for '{text}': {density:.2f} (≥25% threshold)")


def test_arabic_language_purity_with_technical_terms():
    """Test that Arabic text with technical terms bypasses language purity check."""

    site_profile = SiteProfile(
        site_id="kb.aspose.net",
        content_roots=["/content/kb.aspose.net/slides/en"],
        default_source_lang="en",
        target_langs=["ar"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        )
    )

    extractor = TextUnitExtractor(site_profile=site_profile)

    # Create translated units with technical terms
    units = [
        _make_text_unit(
            "unit1",
            "Processing Azure Presentation",
            "معالجة Azure Presentation",
        ),
        _make_text_unit(
            "unit2",
            "Convert Excel to PDF",
            "تحويل Excel إلى PDF",
        ),
        _make_text_unit(
            "unit3",
            "Using Aspose.Slides API",
            "استخدام Aspose.Slides API",
        ),
    ]

    # Run language purity check
    result = extractor._verify_translation_language_purity(units, target_lang="ar")

    # Should pass (either bypassed due to technical density or accepted as script-similar)
    assert result is True, "Language purity check should pass for Arabic text with technical terms"
    print("✅ Language purity check passed for Arabic text with technical terms")


def test_script_similar_languages_arabic_romance():
    """Test that Arabic accepts Romance languages as script-similar."""

    site_profile = SiteProfile(
        site_id="kb.aspose.net",
        content_roots=["/content/kb.aspose.net/slides/en"],
        default_source_lang="en",
        target_langs=["ar"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        )
    )

    extractor = TextUnitExtractor(site_profile=site_profile)

    # Check that Arabic script-similar languages include Romance languages
    script_similar = extractor.script_similar_languages.get('ar', set())

    assert 'it' in script_similar, "Italian should be script-similar to Arabic"
    assert 'es' in script_similar, "Spanish should be script-similar to Arabic"
    assert 'fr' in script_similar, "French should be script-similar to Arabic"
    assert 'pt' in script_similar, "Portuguese should be script-similar to Arabic"
    assert 'fa' in script_similar, "Farsi should be script-similar to Arabic"

    print(f"✅ Arabic script-similar languages: {script_similar}")


def test_arabic_script_ratio_override(monkeypatch):
    """Accept Arabic text with mixed Latin terms when target-script ratio is high."""
    site_profile = SiteProfile(
        site_id="kb.aspose.net",
        content_roots=["/content/kb.aspose.net/slides/en"],
        default_source_lang="en",
        target_langs=["ar"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        )
    )

    extractor = TextUnitExtractor(site_profile=site_profile)

    units = [
        _make_text_unit(
            "unit1",
            "Key Takeaways",
            "الرئيسية Takeaways",
        ),
    ]

    mock_langdetect = MagicMock()
    mock_langdetect.detect = lambda text: "sw"
    mock_langdetect.DetectorFactory = MagicMock()
    mock_langdetect.DetectorFactory.seed = 0
    mock_langdetect.lang_detect_exception = MagicMock()
    mock_langdetect.lang_detect_exception.LangDetectException = Exception
    monkeypatch.setitem(sys.modules, 'langdetect', mock_langdetect)

    result = extractor._verify_translation_language_purity(units, target_lang="ar")

    assert result is True, "Language purity should accept high target-script ratio text"


def test_technical_terms_loaded():
    """Test that Azure and Presentation are in technical terms list."""

    site_profile = SiteProfile(
        site_id="kb.aspose.net",
        content_roots=["/content/kb.aspose.net/slides/en"],
        default_source_lang="en",
        target_langs=["ar"],
        body=BodyRules(translate_markdown=True),
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        )
    )

    extractor = TextUnitExtractor(site_profile=site_profile)

    # Check that technical terms are loaded
    terms_lower = {term.lower() for term in extractor.technical_terms}

    assert 'azure' in terms_lower, "Azure should be in technical terms"
    assert 'presentation' in terms_lower, "Presentation should be in technical terms"
    assert 'excel' in terms_lower, "Excel should be in technical terms"
    assert 'pdf' in terms_lower, "PDF should be in technical terms"

    print(f"✅ Technical terms loaded: {len(extractor.technical_terms)} terms")
    print(f"   Azure: {'azure' in terms_lower}")
    print(f"   Presentation: {'presentation' in terms_lower}")


if __name__ == "__main__":
    test_technical_terms_loaded()
    test_arabic_with_azure_presentation_technical_density()
    test_script_similar_languages_arabic_romance()
    test_arabic_language_purity_with_technical_terms()
    print("\n✅ All language purity tests passed!")
