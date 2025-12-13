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
        assert not any(
            "unencoded spaces" in issue.message.lower()
            for issue in result.issues
        )

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
        assert not any(
            "not found" in issue.message.lower() for issue in result.issues
        )

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
