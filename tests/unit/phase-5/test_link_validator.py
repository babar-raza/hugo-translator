"""
Unit tests for link validator.
"""

import pytest

from src.translation_engine.validation import (
    LinkValidator,
    ValidationSeverity,
)


class TestLinkValidator:
    """Test LinkValidator."""

    @pytest.fixture
    def validator(self):
        """Create link validator."""
        return LinkValidator()

    def test_no_links(self, validator):
        """Test with no links."""
        source = "Simple text without links"
        translation = "Texte simple sans liens"

        result = validator.validate(source, translation)

        assert result.success is True
        assert len(result.issues) == 0

    def test_matching_links(self, validator):
        """Test with matching links."""
        source = "Check [this link](https://example.com)"
        translation = "Vérifiez [ce lien](https://example.com)"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_link_count_mismatch(self, validator):
        """Test with link count mismatch."""
        source = "[Link 1](url1) and [Link 2](url2)"
        translation = "[Lien 1](url1)"

        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("link count" in issue.message.lower() for issue in result.issues)

    def test_empty_url(self, validator):
        """Test with empty URL."""
        source = "[Link](url)"
        translation = "[Lien]()"

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count > 0
        assert any("empty url" in issue.message.lower() for issue in result.issues)

    def test_url_with_spaces(self, validator):
        """Test with unencoded spaces in URL."""
        source = "[Link](url)"
        translation = "[Lien](my url with spaces)"

        result = validator.validate(source, translation)

        assert result.warning_count > 0
        assert any("spaces" in issue.message.lower() for issue in result.issues)

    def test_anchor_link(self, validator):
        """Test with anchor link (spaces allowed)."""
        source = "[Link](#section)"
        translation = "[Lien](#section with spaces)"

        result = validator.validate(source, translation)

        # Anchor links with spaces shouldn't trigger "unencoded spaces" warning
        # (but may have URL preservation warnings, which is fine)
        assert not any("unencoded spaces" in issue.message.lower() for issue in result.issues)

    def test_malformed_absolute_url(self, validator):
        """Test with malformed absolute URL."""
        source = "[Link](url)"
        translation = "[Lien](http://)"

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count > 0

    def test_valid_absolute_url(self, validator):
        """Test with valid absolute URL."""
        source = "[Link](https://example.com)"
        translation = "[Lien](https://example.com)"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_url_preservation(self, validator):
        """Test URL preservation checking."""
        source = "[Link 1](url1) and [Link 2](url2)"
        translation = "[Lien 1](url1) et [Lien 2](url3)"

        result = validator.validate(source, translation)

        # Should warn about missing/changed URLs
        assert result.warning_count > 0
        assert any("not found" in issue.message.lower() for issue in result.issues)

    def test_url_translation_allowed(self):
        """Test with URL translation allowed."""
        validator = LinkValidator(allow_url_translation=True)

        source = "[Link](url1)"
        translation = "[Lien](url_translated)"

        result = validator.validate(source, translation)

        # Should have info about new URL, not warning
        infos = result.filter_by_severity(ValidationSeverity.INFO)
        assert len(infos) > 0
        assert any("new url" in issue.message.lower() for issue in infos)

    def test_url_checking_disabled(self):
        """Test with URL checking disabled."""
        validator = LinkValidator(check_url_changes=False)

        source = "[Link](url1)"
        translation = "[Lien](completely_different_url)"

        result = validator.validate(source, translation)

        # Should not check URL changes
        assert not any("not found" in issue.message.lower() for issue in result.issues)

    def test_image_link(self, validator):
        """Test with image link."""
        source = "![Alt text](image.png)"
        translation = "![Texte alternatif](image.png)"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_mixed_links_and_images(self, validator):
        """Test with both links and images."""
        source = """
[Regular link](url1)
![Image](image.png)
[Another link](url2)
"""
        translation = """
[Lien régulier](url1)
![Image](image.png)
[Un autre lien](url2)
"""
        result = validator.validate(source, translation)

        assert result.success is True

    def test_relative_url(self, validator):
        """Test with relative URL."""
        source = "[Link](../other/page.md)"
        translation = "[Lien](../other/page.md)"

        result = validator.validate(source, translation)

        assert result.success is True

    def test_url_with_fragment(self, validator):
        """Test with URL fragment."""
        source = "[Link](https://example.com/page#section)"
        translation = "[Lien](https://example.com/page#section)"

        result = validator.validate(source, translation)

        assert result.success is True


class TestLinkValidatorRegexUnificationAndDuplicateSeverity:
    """VA-04 (TC-APT-105 audit)."""

    @pytest.fixture
    def validator(self):
        return LinkValidator()

    def test_empty_alt_image_counts_the_same_as_structure_validator(self, validator):
        """A legitimate empty-alt image (`![](image.png)`) must be counted
        by LinkValidator -- confirming the shared, permit-empty regex is in
        effect (the old StructureValidator-only regex required non-empty
        anchor text and would have silently missed this)."""
        source = "See the diagram: ![](diagram.png)"
        translation = "Voir le diagramme : ![](diagram.png)"

        result = validator.validate(source, translation)

        assert result.success is True
        assert not any("count mismatch" in issue.message for issue in result.issues)

    def test_genuine_duplicate_link_is_error_severity(self, validator):
        """TC-APT-105's exact reported shape: the same link duplicated in
        the translation, appearing more times than in source, must be
        ERROR severity (not the generic WARNING count-mismatch), so it
        drives decision_engine's critical-failure path on its own."""
        source = (
            "- **[API Reference](https://reference.aspose.org/cells/go/)**: "
            "Full class and method documentation"
        )
        translation = (
            "- **[API Reference](https://reference.aspose.org/cells/go/)**:"
            "**[API Reference](https://reference.aspose.org/cells/go/)**: "
            "Vollstaendige Klassen- und Methodendokumentation"
        )

        result = validator.validate(source, translation)

        assert result.success is False
        error_issues = [i for i in result.issues if i.severity == ValidationSeverity.ERROR]
        assert len(error_issues) == 1
        assert "reference.aspose.org/cells/go" in error_issues[0].message
        assert error_issues[0].details["extra_occurrences"] == 1

    def test_missing_link_stays_warning_not_error(self, validator):
        """A link present in source but dropped from the translation is a
        DIFFERENT defect shape (a deficit, not a duplicate) and must remain
        WARNING, per this validator's existing, deliberate false-positive-
        avoidance history -- the new duplicate check must not affect it."""
        source = "See [Installation](../installation/) and [API](../api/)"
        translation = "Voir [Installation](../installation/)"

        result = validator.validate(source, translation)

        assert not any(i.severity == ValidationSeverity.ERROR for i in result.issues)
        assert any(i.severity == ValidationSeverity.WARNING for i in result.issues)

    def test_added_link_not_in_source_stays_warning_not_error(self, validator):
        """A URL that appears in translation but never in source at all
        (extra_urls, not a duplicate of an existing one) must remain
        WARNING/INFO via the existing _check_url_preservation path -- the
        new duplicate check only fires for a URL exceeding its OWN source
        count, never for a URL with zero source occurrences."""
        source = "See [Installation](../installation/)"
        translation = "Voir [Installation](../installation/) et [Extra](../extra/)"

        result = validator.validate(source, translation)

        assert not any(i.severity == ValidationSeverity.ERROR for i in result.issues)

    def test_same_url_legitimately_repeated_equally_is_not_flagged(self, validator):
        """A URL genuinely appearing twice in BOTH source and translation
        (e.g. a nav link repeated at top and bottom) must never be flagged
        -- only an INCREASE beyond the source's own count is a defect."""
        source = "[Docs](https://x/) ... later ... [Docs](https://x/)"
        translation = "[Documentation](https://x/) ... plus tard ... [Documentation](https://x/)"

        result = validator.validate(source, translation)

        assert not any(i.severity == ValidationSeverity.ERROR for i in result.issues)
