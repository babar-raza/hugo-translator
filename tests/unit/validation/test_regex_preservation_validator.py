"""
Unit tests for RegexPreservationValidator (SHORTCODE-007 Prompt 6).

Tests post-translation validation of preserve_patterns.
"""

from src.translation_engine.validation.regex_preservation_validator import (
    RegexPreservationValidator,
    ShortcodePreservationValidator,
)


class TestRegexPreservationValidator:
    """Test regex preservation validation."""

    def test_no_patterns_always_passes(self):
        """No preserve_patterns means validation always passes."""
        validator = RegexPreservationValidator(preserve_patterns=[])

        result = validator.validate(source="Any source text", translation="Any translated text")

        assert result.success

    def test_pattern_preserved_count_match(self):
        """Pattern preserved when count matches (non-strict mode)."""
        validator = RegexPreservationValidator(
            preserve_patterns=[r"SaveFormat\.\w+"], strict_mode=False
        )

        result = validator.validate(
            source="Use SaveFormat.Pdf for output.",
            translation="Verwenden Sie SaveFormat.Pdf für die Ausgabe.",
        )

        assert result.success

    def test_pattern_not_preserved_count_mismatch(self):
        """Pattern not preserved when count differs."""
        validator = RegexPreservationValidator(preserve_patterns=[r"SaveFormat\.\w+"])

        result = validator.validate(
            source="Use SaveFormat.Pdf and SaveFormat.Docx.",
            translation="Verwenden Sie das Speicherformat.",  # Lost both patterns
        )

        assert not result.success
        assert result.error_count == 1
        assert "count mismatch" in result.issues[0].message

    def test_pattern_preserved_strict_mode(self):
        """Strict mode requires exact string matches."""
        validator = RegexPreservationValidator(preserve_patterns=[r"Aspose\.\w+"], strict_mode=True)

        result = validator.validate(
            source="Aspose.Words and Aspose.Slides",
            translation="Aspose.Words and Aspose.Slides",  # Exact match
        )

        assert result.success

    def test_pattern_not_preserved_strict_mode(self):
        """Strict mode fails if exact strings don't match."""
        validator = RegexPreservationValidator(preserve_patterns=[r"Aspose\.\w+"], strict_mode=True)

        result = validator.validate(
            source="Aspose.Words",
            translation="Aspose.Cells",  # Different product name (count matches but string differs)
        )

        assert not result.success
        assert result.error_count == 1

    def test_multiple_patterns(self):
        """Multiple preserve_patterns validated independently."""
        validator = RegexPreservationValidator(
            preserve_patterns=[r"SaveFormat\.\w+", r"https?://[^\s]+"]
        )

        result = validator.validate(
            source="Use SaveFormat.Pdf from https://example.com",
            translation="Verwenden Sie SaveFormat.Pdf von https://example.com",
        )

        assert result.success

    def test_invalid_regex_pattern(self):
        """Invalid regex pattern produces warning (not error)."""
        validator = RegexPreservationValidator(
            preserve_patterns=[r"[invalid(regex"]  # Unclosed bracket
        )

        result = validator.validate(source="Test", translation="Test")

        # Validation should succeed (invalid pattern is skipped with warning)
        assert result.success
        assert result.warning_count == 1
        assert "Invalid regex pattern" in result.issues[0].message

    def test_context_override_patterns(self):
        """Context can override default preserve_patterns."""
        validator = RegexPreservationValidator(preserve_patterns=[r"default"])

        result = validator.validate(
            source="Has override pattern",
            translation="Has override pattern",
            context={"preserve_patterns": [r"override"]},
        )

        # Should use context patterns (which match), not default
        assert result.success


class TestShortcodePreservationValidator:
    """Test Hugo shortcode preservation (SHORTCODE-007)."""

    def test_shortcode_angle_bracket_preserved(self):
        """{{< shortcode >}} syntax preserved."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source="Text {{< sections >}} more", translation="Text {{< sections >}} more"
        )

        assert result.success

    def test_shortcode_percent_preserved(self):
        """{{% shortcode %}} syntax preserved."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source="Text {{% steps %}} more", translation="Text {{% steps %}} more"
        )

        assert result.success

    def test_shortcode_comment_preserved(self):
        """{{/* comment */}} syntax preserved."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source="Text {{/* note */}} more", translation="Text {{/* note */}} more"
        )

        assert result.success

    def test_shortcode_with_parameters_preserved(self):
        """Shortcodes with parameters preserved."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source='Text {{< callout type="info" >}} more',
            translation='Text {{< callout type="info" >}} more',
        )

        assert result.success

    def test_shortcode_lost_in_translation(self):
        """Validation fails if shortcode is lost."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source="Text {{< sections >}} more",
            translation="Text more",  # Shortcode lost
        )

        assert not result.success
        assert result.error_count >= 1

    def test_shortcode_count_mismatch(self):
        """Validation fails if shortcode count differs."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source="{{< a >}} and {{< b >}}",
            translation="{{< a >}}",  # Only one preserved
        )

        assert not result.success

    def test_multiple_shortcodes_preserved(self):
        """Multiple shortcodes all preserved."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(
            source="Start {{< callout >}} middle {{< ref >}} end",
            translation="Start {{< callout >}} middle {{< ref >}} end",
        )

        assert result.success

    def test_shortcode_strict_mode_enforced(self):
        """ShortcodePreservationValidator uses strict mode (exact matches)."""
        validator = ShortcodePreservationValidator()

        # Strict mode should be enabled
        assert validator.strict_mode

        # Different shortcodes with same count should fail
        result = validator.validate(
            source="{{< sections >}}",
            translation="{{< callout >}}",  # Different shortcode
        )

        assert not result.success

    def test_metadata_includes_shortcode_007_check(self):
        """Metadata includes SHORTCODE-007 indicator."""
        validator = ShortcodePreservationValidator()

        result = validator.validate(source="{{< test >}}", translation="{{< test >}}")

        assert result.metadata.get("shortcode_007_check") is True
        assert result.metadata.get("validator_type") == "shortcode_preservation"


class TestRegexPreservationIntegration:
    """Integration tests for regex preservation in translation pipeline."""

    def test_shortcode_preservation_in_full_paragraph(self):
        """Shortcodes preserved in translated paragraph."""
        validator = ShortcodePreservationValidator()

        source = (
            "This is an introduction paragraph. {{< sections >}} This is the conclusion paragraph."
        )

        # Simulated translation (shortcode preserved, text translated)
        translation = "Dies ist ein Einleitungsabsatz. {{< sections >}} Dies ist der Schlussabsatz."

        result = validator.validate(source, translation)

        assert result.success

    def test_technical_terms_preserved(self):
        """Technical terms (SaveFormat.Pdf, Aspose.Words) preserved."""
        validator = RegexPreservationValidator(
            preserve_patterns=[r"SaveFormat\.\w+", r"Aspose\.\w+"], strict_mode=True
        )

        source = "Use Aspose.Words to convert to SaveFormat.Pdf format."
        translation = "Verwenden Sie Aspose.Words zum Konvertieren in SaveFormat.Pdf Format."

        result = validator.validate(source, translation)

        assert result.success

    def test_urls_preserved(self):
        """URLs preserved in translation."""
        validator = RegexPreservationValidator(
            preserve_patterns=[r"https?://[^\s]+"], strict_mode=True
        )

        source = "See https://example.com/docs for more info."
        translation = "Siehe https://example.com/docs für weitere Informationen."

        result = validator.validate(source, translation)

        assert result.success
