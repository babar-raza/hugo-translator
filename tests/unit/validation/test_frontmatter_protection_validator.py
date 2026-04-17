"""
Unit tests for FrontmatterProtectionValidator.

Tests cover:
- PASSTHROUGH field validation (unchanged fields)
- IGNORE field validation (fields not in output)
- COMPUTED field validation (valid computed values)
- Frontmatter extraction and parsing
- Error handling for malformed YAML
- 100% code coverage
"""


import pytest

from src.translation_engine.validation.base import ValidationSeverity
from src.translation_engine.validation.frontmatter_protection_validator import (
    FrontmatterProtectionValidator,
)
from src.utils.models import (
    BodyRules,
    FrontmatterMode,
    FrontmatterRule,
    SiteProfile,
)


class TestFrontmatterProtectionValidator:
    """Test suite for FrontmatterProtectionValidator."""

    @pytest.fixture
    def basic_site_profile(self) -> SiteProfile:
        """Create a basic site profile for testing."""
        return SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["de", "es"],
            frontmatter={
                "url": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
                "date": FrontmatterRule(mode=FrontmatterMode.PASSTHROUGH),
                "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
                "draft": FrontmatterRule(mode=FrontmatterMode.IGNORE),
                "lastmod": FrontmatterRule(mode=FrontmatterMode.COMPUTED),
                "slug": FrontmatterRule(mode=FrontmatterMode.COMPUTED),
            },
            body=BodyRules(
                translate_markdown=True,
                preserve_blocks=["block_code"],
            ),
        )

    @pytest.fixture
    def validator(self, basic_site_profile: SiteProfile) -> FrontmatterProtectionValidator:
        """Create a validator instance."""
        return FrontmatterProtectionValidator(basic_site_profile)

    def test_passthrough_unchanged(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that PASSTHROUGH fields unchanged passes validation."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_passthrough_modified(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that modified PASSTHROUGH field produces ERROR."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/seite
date: 2024-01-01
title: Testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True  # Validation runs, but has errors
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "url" in error.message
        assert "PASSTHROUGH" in error.message
        assert "modified" in error.message.lower()
        assert error.location == "frontmatter.url"

    def test_passthrough_missing(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that missing PASSTHROUGH field produces ERROR."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
date: 2024-01-01
title: Testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "url" in error.message
        assert "PASSTHROUGH" in error.message
        assert "missing" in error.message.lower()

    def test_passthrough_date_changed(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that changed date PASSTHROUGH field produces ERROR."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-02
title: Testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "date" in error.message
        assert "PASSTHROUGH" in error.message
        assert "modified" in error.message.lower()

    def test_ignore_field_present(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that IGNORE field in output produces WARNING."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
draft: true
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
draft: true
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 1

        warning = result.filter_by_severity(ValidationSeverity.WARNING)[0]
        assert "draft" in warning.message
        assert "IGNORE" in warning.message
        assert "should not be present" in warning.message

    def test_ignore_field_absent(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that IGNORE field not in output passes validation."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
draft: true
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_computed_field_valid_lastmod(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that valid COMPUTED lastmod field passes validation."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
lastmod: 2024-01-15T10:30:00
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_computed_field_valid_lastmod_with_timezone(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that valid COMPUTED lastmod field with timezone passes validation."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
lastmod: 2024-01-15T10:30:00+0000
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0

    def test_computed_field_invalid_lastmod_format(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that invalid COMPUTED lastmod format produces WARNING."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
lastmod: not-a-date
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 1

        warning = result.filter_by_severity(ValidationSeverity.WARNING)[0]
        assert "lastmod" in warning.message
        assert "datetime format" in warning.message.lower()

    def test_computed_field_invalid_lastmod_type(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that invalid COMPUTED lastmod type produces ERROR."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
lastmod: 12345
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "lastmod" in error.message
        assert "must be a datetime" in error.message

    def test_computed_field_valid_slug(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that valid COMPUTED slug field passes validation."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
slug: testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_computed_field_invalid_slug_format(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that invalid COMPUTED slug format produces WARNING."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
slug: Test Seite!
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 1

        warning = result.filter_by_severity(ValidationSeverity.WARNING)[0]
        assert "slug" in warning.message
        assert "invalid slug format" in warning.message.lower()

    def test_computed_field_invalid_slug_type(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that invalid COMPUTED slug type produces ERROR."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
slug: 12345
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "slug" in error.message
        assert "must be a string" in error.message

    def test_computed_field_optional(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that missing COMPUTED field is allowed (optional)."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content here"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
---
Inhalt hier"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_missing_frontmatter_source(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that missing frontmatter in source produces ERROR."""
        source = """Content without frontmatter"""

        translation = """---
title: Testseite
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "No frontmatter found" in error.message
        assert "source" in error.message

    def test_missing_frontmatter_translation(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that missing frontmatter in translation produces ERROR."""
        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """Content without frontmatter"""

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "No frontmatter found" in error.message
        assert "translation" in error.message

    def test_malformed_yaml_source(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that malformed YAML in source produces ERROR."""
        source = """---
url: /test/page
title: Test Page
  invalid: indentation
---
Content"""

        translation = """---
url: /test/page
title: Testseite
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "Invalid" in error.message
        assert "YAML" in error.message
        assert "source" in error.message

    def test_malformed_yaml_translation(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that malformed YAML in translation produces ERROR."""
        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
url: /test/page
title: Testseite
  invalid: indentation
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "Invalid" in error.message
        assert "YAML" in error.message
        assert "translation" in error.message

    def test_non_dict_frontmatter_source(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that non-dict frontmatter in source produces ERROR."""
        source = """---
- item1
- item2
---
Content"""

        translation = """---
title: Testseite
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "must be a dictionary" in error.message
        assert "source" in error.message

    def test_non_dict_frontmatter_translation(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that non-dict frontmatter in translation produces ERROR."""
        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
- item1
- item2
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is False
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "must be a dictionary" in error.message
        assert "translation" in error.message

    def test_empty_frontmatter(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that empty frontmatter is handled gracefully."""
        source = """---
---
Content"""

        translation = """---
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0

    def test_multiple_passthrough_violations(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that multiple PASSTHROUGH violations are all reported."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content"""

        translation = """---
url: /different/page
date: 2024-01-02
title: Testseite
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.error_count == 2

        errors = result.filter_by_severity(ValidationSeverity.ERROR)
        error_fields = [e.location for e in errors]
        assert "frontmatter.url" in error_fields
        assert "frontmatter.date" in error_fields

    def test_custom_validator_name(self, basic_site_profile: SiteProfile) -> None:
        """Test that custom validator name is used."""
        validator = FrontmatterProtectionValidator(
            basic_site_profile, name="CustomFrontmatterValidator"
        )

        source = """---
url: /test/page
---
Content"""

        translation = """---
url: /different/page
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.error_count == 1
        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert error.validator == "CustomFrontmatterValidator"

    def test_context_preserved(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that context is passed through validation."""
        source = """---
url: /test/page
date: 2024-01-01
title: Test Page
---
Content"""

        translation = """---
url: /test/page
date: 2024-01-01
title: Testseite
---
Inhalt"""

        context = {"file_path": "/content/test.md", "target_lang": "de"}
        result = validator.validate(source, translation, context)

        assert result.success is True

    def test_computed_permalink_valid(self, basic_site_profile: SiteProfile) -> None:
        """Test that valid COMPUTED permalink field passes validation."""
        # Add permalink to frontmatter rules
        basic_site_profile.frontmatter["permalink"] = FrontmatterRule(
            mode=FrontmatterMode.COMPUTED
        )
        validator = FrontmatterProtectionValidator(basic_site_profile)

        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
url: /test/page
title: Testseite
permalink: /de/test/page
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_computed_permalink_invalid_format(self, basic_site_profile: SiteProfile) -> None:
        """Test that invalid COMPUTED permalink format produces WARNING."""
        basic_site_profile.frontmatter["permalink"] = FrontmatterRule(
            mode=FrontmatterMode.COMPUTED
        )
        validator = FrontmatterProtectionValidator(basic_site_profile)

        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
url: /test/page
title: Testseite
permalink: not-a-url
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 1

        warning = result.filter_by_severity(ValidationSeverity.WARNING)[0]
        assert "permalink" in warning.message
        assert "valid URL" in warning.message

    def test_computed_permalink_invalid_type(self, basic_site_profile: SiteProfile) -> None:
        """Test that invalid COMPUTED permalink type produces ERROR."""
        basic_site_profile.frontmatter["permalink"] = FrontmatterRule(
            mode=FrontmatterMode.COMPUTED
        )
        validator = FrontmatterProtectionValidator(basic_site_profile)

        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
url: /test/page
title: Testseite
permalink: 12345
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 1

        error = result.filter_by_severity(ValidationSeverity.ERROR)[0]
        assert "permalink" in error.message
        assert "must be a string" in error.message

    def test_passthrough_field_not_in_source(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that PASSTHROUGH field not in source doesn't cause errors."""
        source = """---
title: Test Page
---
Content"""

        translation = """---
title: Testseite
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0

    def test_lastmod_date_only_format(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that lastmod with date-only format is valid."""
        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
url: /test/page
title: Testseite
lastmod: 2024-01-15
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_slug_with_hyphens(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that slug with hyphens is valid."""
        source = """---
url: /test/page
title: Test Page
---
Content"""

        translation = """---
url: /test/page
title: Testseite
slug: test-seite-de
---
Inhalt"""

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0
        assert result.warning_count == 0

    def test_frontmatter_with_windows_line_endings(
        self, validator: FrontmatterProtectionValidator
    ) -> None:
        """Test that frontmatter with Windows line endings is parsed correctly."""
        source = "---\r\nurl: /test/page\r\ndate: 2024-01-01\r\n---\r\nContent"
        translation = "---\r\nurl: /test/page\r\ndate: 2024-01-01\r\n---\r\nInhalt"

        result = validator.validate(source, translation)

        assert result.success is True
        assert result.error_count == 0

    def test_error_details_included(self, validator: FrontmatterProtectionValidator) -> None:
        """Test that error details include expected and actual values."""
        source = """---
url: /test/page
date: 2024-01-01
---
Content"""

        translation = """---
url: /different/page
date: 2024-01-02
---
Inhalt"""

        result = validator.validate(source, translation)

        errors = result.filter_by_severity(ValidationSeverity.ERROR)
        for error in errors:
            assert error.details is not None
            assert "field" in error.details
            assert "mode" in error.details
            if "expected" in error.details:
                assert "actual" in error.details
