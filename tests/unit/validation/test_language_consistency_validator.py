"""
Unit tests for LanguageConsistencyValidator.

Tests cover language detection, confidence thresholds, text cleaning,
and edge cases. Ensures deterministic behavior with langdetect seed.
"""

from langdetect import DetectorFactory

from src.translation_engine.validation.base import ValidationSeverity
from src.translation_engine.validation.language_consistency_validator import (
    LanguageConsistencyValidator,
)

# Set seed for deterministic language detection
DetectorFactory.seed = 0


class TestLanguageConsistencyValidator:
    """Test suite for LanguageConsistencyValidator."""

    def test_initialization_default_threshold(self) -> None:
        """Test validator initialization with default confidence threshold."""
        validator = LanguageConsistencyValidator()
        assert validator.confidence_threshold == 0.85

    def test_initialization_custom_threshold(self) -> None:
        """Test validator initialization with custom confidence threshold."""
        validator = LanguageConsistencyValidator(confidence_threshold=0.9)
        assert validator.confidence_threshold == 0.9

    def test_correct_language_detected_german(self) -> None:
        """Test that German text is correctly detected as German."""
        validator = LanguageConsistencyValidator()
        german_text = (
            "Dies ist ein deutscher Text über Softwareentwicklung und "
            "maschinelles Lernen. Die künstliche Intelligenz revolutioniert "
            "die Technologiebranche und ermöglicht neue Anwendungen."
        )
        result = validator.validate("", german_text, {"target_lang": "de"})

        assert result.success is True
        assert result.metadata["target_language"] == "de"
        assert result.metadata["purity_percentage"] == 100.0
        assert result.metadata["correct_language_count"] == result.metadata["total_sentences"]
        assert len([i for i in result.issues if i.severity == ValidationSeverity.ERROR]) == 0

    def test_correct_language_detected_french(self) -> None:
        """Test that French text is correctly detected as French."""
        validator = LanguageConsistencyValidator()
        french_text = (
            "Ceci est un texte français sur le développement de logiciels et "
            "l'apprentissage automatique. L'intelligence artificielle révolutionne "
            "l'industrie technologique et permet de nouvelles applications."
        )
        result = validator.validate("", french_text, {"target_lang": "fr"})

        assert result.success is True
        assert result.metadata["target_language"] == "fr"
        assert result.metadata["purity_percentage"] == 100.0

    def test_correct_language_detected_spanish(self) -> None:
        """Test that Spanish text is correctly detected as Spanish."""
        validator = LanguageConsistencyValidator()
        spanish_text = (
            "Este es un texto en español sobre desarrollo de software y "
            "aprendizaje automático. La inteligencia artificial revoluciona "
            "la industria tecnológica y permite nuevas aplicaciones."
        )
        result = validator.validate("", spanish_text, {"target_lang": "es"})

        assert result.success is True
        assert result.metadata["target_language"] == "es"
        assert result.metadata["purity_percentage"] == 100.0

    def test_wrong_language_detected_english_when_german_expected(self) -> None:
        """Test that English text is detected when German is expected (ERROR)."""
        validator = LanguageConsistencyValidator()
        english_text = (
            "This is an English text about software development and "
            "machine learning. Artificial intelligence is revolutionizing "
            "the technology industry and enabling new applications."
        )
        result = validator.validate("", english_text, {"target_lang": "de"})

        assert result.success is False
        assert result.metadata["target_language"] == "de"
        assert result.metadata["purity_percentage"] < 95.0
        assert result.metadata["correct_language_count"] == 0
        # All wrong-language samples should be detected as English
        assert all(s["detected"] == "en" for s in result.metadata["wrong_language_samples"])
        assert result.error_count == 1

        error_issues = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(error_issues) == 1
        assert "de" in error_issues[0].message

    def test_wrong_language_detected_german_when_french_expected(self) -> None:
        """Test that German text is detected when French is expected (ERROR)."""
        validator = LanguageConsistencyValidator()
        german_text = (
            "Dies ist ein deutscher Text über Softwareentwicklung und "
            "maschinelles Lernen in der modernen Technologiewelt."
        )
        result = validator.validate("", german_text, {"target_lang": "fr"})

        assert result.success is False
        assert result.metadata["target_language"] == "fr"
        assert result.metadata["purity_percentage"] < 95.0
        # Wrong-language samples should be detected as German
        assert any(s["detected"] == "de" for s in result.metadata["wrong_language_samples"])
        assert result.error_count == 1

    def test_low_confidence_handling(self) -> None:
        """Test that mixed-language text produces a purity error."""
        validator = LanguageConsistencyValidator(confidence_threshold=0.95)
        # Mix of languages — half German, half English sentences
        mixed_text = (
            "Das ist ein Text mit some English words gemischt zusammen. "
            "This creates lower confidence in detection results."
        )
        result = validator.validate("", mixed_text, {"target_lang": "de"})

        # Should still return purity metadata
        assert "purity_percentage" in result.metadata
        assert "total_sentences" in result.metadata
        assert "wrong_language_samples" in result.metadata

        # The English sentence should be flagged, causing purity < 100%
        assert result.metadata["purity_percentage"] < 100.0

    def test_no_target_language_specified(self) -> None:
        """Test that missing target language produces WARNING and passes."""
        validator = LanguageConsistencyValidator()
        result = validator.validate("", "Any text here", {})

        assert result.success is True
        assert result.warning_count == 1
        warning = result.issues[0]
        assert warning.severity == ValidationSeverity.WARNING
        assert "No target language specified" in warning.message
        assert warning.location == "context"

    def test_no_target_language_none_context(self) -> None:
        """Test that None context is handled gracefully."""
        validator = LanguageConsistencyValidator()
        result = validator.validate("", "Any text here", None)

        assert result.success is True
        assert result.warning_count == 1
        assert "No target language specified" in result.issues[0].message

    def test_text_too_short(self) -> None:
        """Test that text shorter than 20 characters produces INFO and passes."""
        validator = LanguageConsistencyValidator()
        short_text = "Short"
        result = validator.validate("", short_text, {"target_lang": "de"})

        assert result.success is True
        assert result.info_count == 1
        info = result.issues[0]
        assert info.severity == ValidationSeverity.INFO
        assert "Text too short" in info.message
        assert info.location == "translation"

    def test_text_too_short_after_cleaning(self) -> None:
        """Test that text too short after cleaning produces INFO."""
        validator = LanguageConsistencyValidator()
        # Text that's long but becomes short after cleaning
        text_with_code = "```python\nprint('hello world')\n```"
        result = validator.validate("", text_with_code, {"target_lang": "de"})

        assert result.success is True
        assert result.info_count == 1
        assert "Text too short" in result.issues[0].message

    def test_code_blocks_ignored(self) -> None:
        """Test that code blocks are removed before language detection."""
        validator = LanguageConsistencyValidator()
        text_with_code = """
        Dies ist deutscher Text über Programmierung.
        ```python
        def hello():
            print("This English code should be ignored")
            return "English text in code"
        ```
        Mehr deutscher Text über Softwareentwicklung und künstliche Intelligenz.
        """

        cleaned = validator._clean_text_for_detection(text_with_code)
        assert "English code" not in cleaned
        assert "print" not in cleaned
        assert "deutscher Text" in cleaned

        result = validator.validate("", text_with_code, {"target_lang": "de"})
        # Should detect as German despite English code — all sentences should pass
        assert result.metadata["purity_percentage"] == 100.0

    def test_inline_code_ignored(self) -> None:
        """Test that inline code is removed before language detection."""
        validator = LanguageConsistencyValidator()
        text = "Dies ist ein Text mit `some_english_variable` im Code."

        cleaned = validator._clean_text_for_detection(text)
        assert "some_english_variable" not in cleaned
        assert "Dies ist ein Text" in cleaned

    def test_urls_ignored(self) -> None:
        """Test that URLs are removed before language detection."""
        validator = LanguageConsistencyValidator()
        text = (
            "Dies ist ein deutscher Text. Siehe https://example.com/english/path "
            "für mehr Informationen über Softwareentwicklung."
        )

        cleaned = validator._clean_text_for_detection(text)
        assert "https://example.com" not in cleaned
        assert "deutscher Text" in cleaned

    def test_hugo_shortcodes_ignored(self) -> None:
        """Test that Hugo shortcodes are removed before language detection."""
        validator = LanguageConsistencyValidator()
        text = (
            "Dies ist deutscher Text. {{< figure src=\"image.jpg\" >}} "
            "Mehr deutscher Text über Technologie."
        )

        cleaned = validator._clean_text_for_detection(text)
        assert "{{<" not in cleaned
        assert "figure" not in cleaned
        assert "deutscher Text" in cleaned

    def test_placeholders_ignored(self) -> None:
        """Test that placeholders are removed before language detection."""
        validator = LanguageConsistencyValidator()
        text = (
            "Dies ist ein Text mit {PLACEHOLDER_1} und {TERM_2} sowie "
            "{SHORTCODE_3} im deutschen Kontext."
        )

        cleaned = validator._clean_text_for_detection(text)
        assert "PLACEHOLDER_1" not in cleaned
        assert "TERM_2" not in cleaned
        assert "SHORTCODE_3" not in cleaned
        assert "deutscher Text" in cleaned or "deutschen Kontext" in cleaned

    def test_markdown_links_text_preserved(self) -> None:
        """Test that markdown link text is preserved but URLs removed."""
        validator = LanguageConsistencyValidator()
        text = "Dies ist [deutscher Linktext](https://example.com) im Text."

        cleaned = validator._clean_text_for_detection(text)
        assert "deutscher Linktext" in cleaned
        assert "https://example.com" not in cleaned
        assert "[" not in cleaned
        assert "]" not in cleaned

    def test_whitespace_normalized(self) -> None:
        """Test that excessive whitespace is normalized."""
        validator = LanguageConsistencyValidator()
        text = "Dies   ist    ein\n\nText   mit    viel\tWhitespace."

        cleaned = validator._clean_text_for_detection(text)
        assert "  " not in cleaned  # No double spaces
        assert "\n" not in cleaned
        assert "\t" not in cleaned

    def test_complex_cleaning(self) -> None:
        """Test complex text with multiple elements to clean."""
        validator = LanguageConsistencyValidator()
        text = """
        # German Heading

        Dies ist ein deutscher Artikel über [Softwareentwicklung](https://dev.example.com).

        ```python
        def english_function():
            print("English code to ignore")
        ```

        Der Text enthält `inline_code` und {{< shortcode param="value" >}}.
        Sowie {PLACEHOLDER_1} und mehr deutschen Text.

        Siehe auch https://example.com/english-url für Details.
        """

        cleaned = validator._clean_text_for_detection(text)

        # Should not contain cleaned elements
        assert "english_function" not in cleaned
        assert "English code" not in cleaned
        assert "inline_code" not in cleaned
        assert "shortcode" not in cleaned
        assert "PLACEHOLDER_1" not in cleaned
        assert "https://example.com" not in cleaned

        # Should contain German text
        assert "deutscher" in cleaned or "deutschen" in cleaned
        assert "Softwareentwicklung" in cleaned

    def test_language_detection_exception_handling(self) -> None:
        """Test that language detection exceptions are handled gracefully."""
        validator = LanguageConsistencyValidator()
        # Empty string after cleaning should raise LangDetectException
        text = "   \n\t   "
        result = validator.validate("", text, {"target_lang": "de"})

        assert result.success is True  # Empty text too short
        assert result.info_count == 1
        assert "Text too short" in result.issues[0].message

    def test_deterministic_detection(self) -> None:
        """Test that language detection is deterministic with seed."""
        validator = LanguageConsistencyValidator()
        text = (
            "Dies ist ein deutscher Text über Softwareentwicklung und "
            "künstliche Intelligenz in der modernen Welt."
        )

        # Run detection multiple times
        result1 = validator.validate("", text, {"target_lang": "de"})
        result2 = validator.validate("", text, {"target_lang": "de"})
        result3 = validator.validate("", text, {"target_lang": "de"})

        # All results should be identical
        assert result1.metadata["purity_percentage"] == result2.metadata["purity_percentage"]
        assert result2.metadata["purity_percentage"] == result3.metadata["purity_percentage"]
        assert result1.metadata["correct_language_count"] == result2.metadata["correct_language_count"]
        assert result2.metadata["correct_language_count"] == result3.metadata["correct_language_count"]

    def test_arabic_text_detection(self) -> None:
        """Test that Arabic text is correctly detected."""
        validator = LanguageConsistencyValidator()
        arabic_text = (
            "هذا نص عربي حول تطوير البرمجيات والذكاء الاصطناعي. "
            "تقنية المعلومات تتطور بسرعة كبيرة في العالم الحديث."
        )
        result = validator.validate("", arabic_text, {"target_lang": "ar"})

        assert result.success is True
        assert result.metadata["target_language"] == "ar"
        assert result.metadata["purity_percentage"] == 100.0

    def test_validation_result_structure(self) -> None:
        """Test that ValidationResult has correct structure."""
        validator = LanguageConsistencyValidator()
        german_text = "Dies ist ein deutscher Text über Technologie und Innovation."
        result = validator.validate("", german_text, {"target_lang": "de"})

        # Check result structure
        assert hasattr(result, "success")
        assert hasattr(result, "issues")
        assert hasattr(result, "metadata")

        # Check metadata keys returned by sentence-purity approach
        assert "target_language" in result.metadata
        assert "total_sentences" in result.metadata
        assert "correct_language_count" in result.metadata
        assert "purity_percentage" in result.metadata
        assert "wrong_language_samples" in result.metadata

        # Check types
        assert isinstance(result.success, bool)
        assert isinstance(result.issues, list)
        assert isinstance(result.metadata, dict)

    def test_high_confidence_threshold(self) -> None:
        """Test validator with very high confidence threshold (threshold stored but purity drives result)."""
        validator = LanguageConsistencyValidator(confidence_threshold=0.99)
        german_text = "Dies ist ein deutscher Text."
        result = validator.validate("", german_text, {"target_lang": "de"})

        # Should detect correct language — purity check passes single-sentence German
        assert result.metadata["target_language"] == "de"
        assert "purity_percentage" in result.metadata

    def test_low_confidence_threshold(self) -> None:
        """Test validator with very low confidence threshold."""
        validator = LanguageConsistencyValidator(confidence_threshold=0.5)
        german_text = "Dies ist ein deutscher Text über Softwareentwicklung."
        result = validator.validate("", german_text, {"target_lang": "de"})

        assert result.success is True
        # All sentences should be correctly detected
        assert result.metadata["purity_percentage"] == 100.0

    def test_multiple_languages_mixed(self) -> None:
        """Test detection with mostly German content."""
        validator = LanguageConsistencyValidator()
        # Mostly German with some English
        mixed_text = (
            "Dies ist hauptsächlich deutscher Text mit occasional English words "
            "eingestreut im Kontext von Softwareentwicklung und Technologie. "
            "Die deutsche Sprache dominiert aber in diesem Beispiel."
        )
        result = validator.validate("", mixed_text, {"target_lang": "de"})

        # Should return purity metadata
        assert "purity_percentage" in result.metadata
        assert "total_sentences" in result.metadata

    def test_source_parameter_ignored(self) -> None:
        """Test that source parameter is ignored (signature compatibility)."""
        validator = LanguageConsistencyValidator()
        german_text = "Dies ist ein deutscher Text über Technologie."

        # Source should be ignored
        result1 = validator.validate("English source", german_text, {"target_lang": "de"})
        result2 = validator.validate("", german_text, {"target_lang": "de"})

        # Results should be identical (source ignored)
        assert result1.metadata["purity_percentage"] == result2.metadata["purity_percentage"]
        assert result1.success == result2.success

    def test_context_extensibility(self) -> None:
        """Test that extra context fields don't break validation."""
        validator = LanguageConsistencyValidator()
        german_text = "Dies ist ein deutscher Text über Technologie."

        # Context with extra fields
        context = {
            "target_lang": "de",
            "file_path": "/some/path",
            "extra_field": "extra_value",
        }

        result = validator.validate("", german_text, context)
        assert result.success is True
        assert result.metadata["target_language"] == "de"
        assert result.metadata["purity_percentage"] == 100.0

    def test_validator_name_in_issues(self) -> None:
        """Test that all issues have correct validator name."""
        validator = LanguageConsistencyValidator()

        # Test with wrong language to generate error
        english_text = "This is English text."
        result = validator.validate("", english_text, {"target_lang": "de"})

        for issue in result.issues:
            assert issue.validator == "LanguageConsistencyValidator"

    def test_issue_locations(self) -> None:
        """Test that issues have appropriate location fields."""
        validator = LanguageConsistencyValidator()

        # Test no target language
        result1 = validator.validate("", "text", {})
        assert result1.issues[0].location == "context"

        # Test wrong language (use longer text to avoid "too short" issue)
        result2 = validator.validate("", "This is English text that is long enough for detection", {"target_lang": "de"})
        error = [i for i in result2.issues if i.severity == ValidationSeverity.ERROR][0]
        assert error.location == "translation"

    def test_error_count_correct(self) -> None:
        """Test that error count is correctly calculated."""
        validator = LanguageConsistencyValidator()

        # Correct language - no errors
        german_text = "Dies ist ein deutscher Text über Technologie und Innovation."
        result1 = validator.validate("", german_text, {"target_lang": "de"})
        assert result1.error_count == 0

        # Wrong language - 1 error
        english_text = "This is English text about technology."
        result2 = validator.validate("", english_text, {"target_lang": "de"})
        assert result2.error_count == 1

    def test_passed_based_on_errors_only(self) -> None:
        """Test that success is based on ERROR severity, not warnings."""
        validator = LanguageConsistencyValidator(confidence_threshold=0.95)

        # Correct language but potentially low confidence (warning)
        german_text = "Dies ist ein deutscher Text."
        result = validator.validate("", german_text, {"target_lang": "de"})

        # Should pass even if there are warnings
        if result.warning_count > 0:
            assert result.success is True  # Warnings don't fail validation
