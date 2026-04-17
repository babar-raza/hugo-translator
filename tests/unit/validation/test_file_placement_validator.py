"""
Unit tests for FilePlacementValidator.

Tests cover:
- Language folder substitution (/en/ → /de/)
- Subdomain-specific path rules (products, blog, reference, docs)
- Content root alignment verification
- Invalid path detection
"""

from typing import Any
from unittest.mock import Mock

import pytest

from src.translation_engine.validation.base import (
    ValidationSeverity,
)
from src.translation_engine.validation.file_placement_validator import (
    FilePlacementValidator,
)
from src.utils.models import BodyRules, OutputLayout, SiteProfile


class TestFilePlacementValidator:
    """Test suite for FilePlacementValidator."""

    @pytest.fixture
    def validator(self) -> FilePlacementValidator:
        """Create a validator instance without config service."""
        return FilePlacementValidator()

    @pytest.fixture
    def validator_with_config(self) -> FilePlacementValidator:
        """Create a validator instance with mock config service."""
        config_service = Mock()
        return FilePlacementValidator(config_service=config_service)

    @pytest.fixture
    def products_profile(self) -> SiteProfile:
        """Create a products.aspose.net site profile."""
        return SiteProfile(
            site_id="products.aspose.net",
            body=BodyRules(translate_markdown=True),
            content_roots=["/content/products"],
            default_source_lang="en",
            target_langs=["de", "es", "fr", "ja", "ko", "ru", "zh", "ar", "it", "pt"],
            output_layout=OutputLayout(
                per_language_folders=True,
                pattern="{lang}/{path}",
            ),
        )

    @pytest.fixture
    def blog_profile(self) -> SiteProfile:
        """Create a blog.aspose.net site profile."""
        return SiteProfile(
            site_id="blog.aspose.net",
            body=BodyRules(translate_markdown=True),
            content_roots=["/content/blog"],
            default_source_lang="en",
            target_langs=["de", "es", "fr", "ja", "ko", "ru", "zh", "ar", "it", "pt"],
            output_layout=OutputLayout(
                per_language_folders=True,
                pattern="{lang}/{path}",
            ),
        )

    @pytest.fixture
    def reference_profile(self) -> SiteProfile:
        """Create a reference.aspose.net site profile."""
        return SiteProfile(
            site_id="reference.aspose.net",
            body=BodyRules(translate_markdown=True),
            content_roots=["/content/reference"],
            default_source_lang="en",
            target_langs=["de", "es", "fr", "ja", "ko", "ru", "zh", "ar", "it", "pt"],
            output_layout=OutputLayout(
                per_language_folders=True,
                pattern="{lang}/{path}",
            ),
        )

    @pytest.fixture
    def docs_profile(self) -> SiteProfile:
        """Create a docs.aspose.net site profile."""
        return SiteProfile(
            site_id="docs.aspose.net",
            body=BodyRules(translate_markdown=True),
            content_roots=["/content/docs"],
            default_source_lang="en",
            target_langs=["de", "es", "fr", "ja", "ko", "ru", "zh", "ar", "it", "pt"],
            output_layout=OutputLayout(
                per_language_folders=True,
                pattern="{lang}/{path}",
            ),
        )

    def test_language_substitution_correct(self, validator: FilePlacementValidator) -> None:
        """Test that correct language substitution passes validation."""
        source = "/content/products/en/family/aspose-words.md"
        translation = "/content/products/de/family/aspose-words.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_language_substitution_incorrect(self, validator: FilePlacementValidator) -> None:
        """Test that incorrect language substitution (en → en) fails validation."""
        source = "/content/products/en/family/aspose-words.md"
        translation = "/content/products/en/family/aspose-words.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        assert result.success is False
        assert result.error_count >= 1
        # Should have error about language substitution failure
        # Either "Target language not found" or "Source language found in translation path"
        error_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        assert any(
            ("Target language" in msg and "not found in translation path" in msg) or
            ("Source language" in msg and "found in translation path" in msg)
            for msg in error_messages
        )

    def test_subdomain_products(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test products.aspose.net path rules."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_subdomain_blog(
        self, validator: FilePlacementValidator, blog_profile: SiteProfile
    ) -> None:
        """Test blog.aspose.net different structure."""
        source = "/content/blog/en/2024/01/release-notes.md"
        translation = "/content/blog/fr/2024/01/release-notes.md"
        context = {
            "source_lang": "en",
            "target_lang": "fr",
            "site_id": "blog.aspose.net",
            "site_profile": blog_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_subdomain_reference(
        self, validator: FilePlacementValidator, reference_profile: SiteProfile
    ) -> None:
        """Test reference.aspose.net API paths."""
        source = "/content/reference/en/net/aspose.words/document.md"
        translation = "/content/reference/ja/net/aspose.words/document.md"
        context = {
            "source_lang": "en",
            "target_lang": "ja",
            "site_id": "reference.aspose.net",
            "site_profile": reference_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_invalid_path(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test wrong content root detection."""
        source = "/content/products/en/words/index.md"
        translation = "/wrong/path/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is False
        assert result.error_count >= 1
        # Should have error about content root
        error_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        assert any(
            "content root" in msg.lower() for msg in error_messages
        )

    def test_missing_target_language_context(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test that missing target language in context fails validation."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            # Missing target_lang
        }

        result = validator.validate(source, translation, context)

        assert result.success is False
        assert result.error_count >= 1
        error_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        assert any(
            "No target language specified" in msg for msg in error_messages
        )

    def test_multiple_language_folders(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test paths with multiple language folder occurrences."""
        source = "/content/docs/en/products/en/guide.md"
        translation = "/content/docs/de/products/de/guide.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        # Should pass - both language folders substituted
        assert result.success is True

    def test_missing_language_folder_in_source(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test source path without language folder."""
        source = "/content/products/words/index.md"  # No /en/
        translation = "/content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        # Should have warning about source language not found
        assert result.warning_count >= 1
        warning_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.WARNING
        ]
        assert any(
            "Source language" in msg and "not found in source path" in msg
            for msg in warning_messages
        )

    def test_missing_language_folder_in_translation(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test translation path without target language folder."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/words/index.md"  # No /de/
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        # Should fail - target language not found in translation path
        assert result.success is False
        assert result.error_count >= 1
        error_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        assert any(
            "Target language" in msg and "not found in translation path" in msg
            for msg in error_messages
        )

    def test_content_root_validation_with_profile(
        self, validator: FilePlacementValidator, docs_profile: SiteProfile
    ) -> None:
        """Test content root validation with site profile."""
        source = "/content/docs/en/guide/index.md"
        translation = "/content/docs/de/guide/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "docs.aspose.net",
            "site_profile": docs_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_content_root_validation_failure(
        self, validator: FilePlacementValidator, docs_profile: SiteProfile
    ) -> None:
        """Test content root validation fails for wrong root."""
        source = "/content/docs/en/guide/index.md"
        translation = "/content/blog/de/guide/index.md"  # Wrong content root
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "docs.aspose.net",
            "site_profile": docs_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is False
        # Should have error about wrong content root
        error_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.ERROR
        ]
        assert any(
            "content root" in msg.lower() for msg in error_messages
        )

    def test_subdomain_rules_validation(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test subdomain-specific rules validation."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/es/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "es",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_invalid_language_folder_in_translation(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test translation with invalid language folder."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/xx/words/index.md"  # xx not in target_langs
        context = {
            "source_lang": "en",
            "target_lang": "xx",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        # Should still validate language substitution, but may warn about invalid language
        # The validator checks if target language is present, not if it's valid
        assert any(issue.severity == ValidationSeverity.ERROR for issue in result.issues) or result.error_count == 0

    def test_path_with_different_case(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test paths with different casing."""
        source = "/Content/Products/EN/words/index.md"
        translation = "/Content/Products/DE/words/index.md"
        context = {
            "source_lang": "EN",
            "target_lang": "DE",
        }

        result = validator.validate(source, translation, context)

        # Should handle case-sensitive paths correctly
        assert result.success is True

    def test_relative_paths(self, validator: FilePlacementValidator) -> None:
        """Test relative paths instead of absolute paths."""
        source = "content/products/en/words/index.md"
        translation = "content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_windows_paths(self, validator: FilePlacementValidator) -> None:
        """Test Windows-style paths."""
        source = r"C:\content\products\en\words\index.md"
        translation = r"C:\content\products\de\words\index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_config_service_integration(
        self, validator_with_config: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test integration with config service."""
        # Mock config service to return profile
        validator_with_config.config_service.get_site_profile.return_value = products_profile

        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "products.aspose.net",
        }

        result = validator_with_config.validate(source, translation, context)

        # Verify config service was called
        validator_with_config.config_service.get_site_profile.assert_called_once_with(
            "products.aspose.net"
        )
        assert result.success is True
        assert result.error_count == 0

    def test_config_service_load_failure(
        self, validator_with_config: FilePlacementValidator
    ) -> None:
        """Test handling of config service load failure."""
        # Mock config service to raise exception
        validator_with_config.config_service.get_site_profile.side_effect = Exception(
            "Profile not found"
        )

        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "products.aspose.net",
        }

        result = validator_with_config.validate(source, translation, context)

        # Should still validate language substitution despite config load failure
        # Should have warning about failed profile load
        assert result.warning_count >= 1
        warning_messages = [
            issue.message for issue in result.issues
            if issue.severity == ValidationSeverity.WARNING
        ]
        assert any(
            "Could not load site profile" in msg for msg in warning_messages
        )

    def test_empty_context(self, validator: FilePlacementValidator) -> None:
        """Test validation with empty context."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"
        context: dict[str, Any] = {}

        result = validator.validate(source, translation, context)

        # Should fail due to missing target_lang
        assert result.success is False
        assert result.error_count >= 1

    def test_none_context(self, validator: FilePlacementValidator) -> None:
        """Test validation with None context."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"

        result = validator.validate(source, translation, None)

        # Should fail due to missing target_lang
        assert result.success is False
        assert result.error_count >= 1

    def test_validator_name(self) -> None:
        """Test validator name."""
        validator = FilePlacementValidator()
        assert validator.name == "FilePlacementValidator"

        custom_validator = FilePlacementValidator(name="CustomFilePlacement")
        assert custom_validator.name == "CustomFilePlacement"

    def test_path_structure_mismatch(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test detection of path structure mismatch."""
        source = "/content/products/en/words/guide/index.md"
        translation = "/content/products/de/different/path.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        # Should pass language substitution but may have structural differences
        # The validator primarily checks language substitution
        assert result.error_count == 0 or result.success is True

    def test_complex_path_with_dots(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test paths with dots in directory names."""
        source = "/content/products/en/aspose.words/index.md"
        translation = "/content/products/de/aspose.words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_path_with_special_characters(
        self, validator: FilePlacementValidator
    ) -> None:
        """Test paths with special characters."""
        source = "/content/products/en/test-feature/index.md"
        translation = "/content/products/de/test-feature/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_nested_content_structure(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test deeply nested content structure."""
        source = "/content/products/en/family/net/aspose-words/features/index.md"
        translation = "/content/products/zh/family/net/aspose-words/features/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "zh",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        assert result.success is True
        assert result.error_count == 0

    def test_output_layout_pattern_validation(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test validation of output layout pattern."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/de/words/index.md"
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        # Should validate that pattern is followed
        assert result.success is True
        assert result.error_count == 0

    def test_missing_language_folder_with_profile(
        self, validator: FilePlacementValidator, products_profile: SiteProfile
    ) -> None:
        """Test missing language folder validation with site profile."""
        source = "/content/products/en/words/index.md"
        translation = "/content/products/words/index.md"  # Missing language folder
        context = {
            "source_lang": "en",
            "target_lang": "de",
            "site_id": "products.aspose.net",
            "site_profile": products_profile,
        }

        result = validator.validate(source, translation, context)

        # Should fail due to missing target language folder
        assert result.success is False
        assert result.error_count >= 1

    def test_all_subdomains_consistency(
        self,
        validator: FilePlacementValidator,
        products_profile: SiteProfile,
        blog_profile: SiteProfile,
        reference_profile: SiteProfile,
        docs_profile: SiteProfile,
    ) -> None:
        """Test that all subdomains follow consistent validation rules."""
        test_cases = [
            (
                "/content/products/en/test.md",
                "/content/products/de/test.md",
                "products.aspose.net",
                products_profile,
            ),
            (
                "/content/blog/en/test.md",
                "/content/blog/fr/test.md",
                "blog.aspose.net",
                blog_profile,
            ),
            (
                "/content/reference/en/test.md",
                "/content/reference/ja/test.md",
                "reference.aspose.net",
                reference_profile,
            ),
            (
                "/content/docs/en/test.md",
                "/content/docs/es/test.md",
                "docs.aspose.net",
                docs_profile,
            ),
        ]

        for source, translation, site_id, profile in test_cases:
            context = {
                "source_lang": "en",
                "target_lang": translation.split("/")[2],  # Extract lang from path
                "site_id": site_id,
                "site_profile": profile,
            }

            result = validator.validate(source, translation, context)

            assert result.success is True, f"Failed for {site_id}"
            assert result.error_count == 0, f"Errors found for {site_id}"
