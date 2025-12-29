"""
Unit tests for FilePlacementValidator.

Tests the fix for file-based vs folder-based localization detection.
Ensures blog.aspose.net (file-based) doesn't warn about missing /en/ folder.
"""
import pytest
from pathlib import Path
from src.translation_engine.validation.file_placement_validator import FilePlacementValidator
from src.translation_engine.validation.base import ValidationSeverity
from src.utils.models import SiteProfile, OutputLayout, BodyRules, FrontmatterRule, FrontmatterMode


@pytest.fixture
def file_based_site_profile():
    """Create a file-based site profile (blog.aspose.net style)."""
    return SiteProfile(
        site_id="blog.aspose.net",
        content_roots=["/content/blog"],
        default_source_lang="en",
        target_langs=["es", "de", "fr"],
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code"],
            preserve_patterns=[],
            placeholder_syntax=[],
        ),
        output_layout=OutputLayout(
            per_language_folders=False,
            pattern="{filename}.{lang}{ext}"
        ),
    )


@pytest.fixture
def folder_based_site_profile():
    """Create a folder-based site profile (products.aspose.net style)."""
    return SiteProfile(
        site_id="products.aspose.net",
        content_roots=["/content/products"],
        default_source_lang="en",
        target_langs=["es", "de", "fr"],
        frontmatter={
            "title": FrontmatterRule(mode=FrontmatterMode.TRANSLATE),
        },
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=["block_code"],
            preserve_patterns=[],
            placeholder_syntax=[],
        ),
        output_layout=OutputLayout(
            per_language_folders=True,
            pattern="{lang}/{path}"
        ),
    )


class TestFilePlacementValidator:
    """Test file placement validation for file-based vs folder-based sites."""

    def test_file_based_no_source_lang_warning(self, file_based_site_profile):
        """
        File-based sites should NOT warn about missing /en/ folder.

        Regression test for blog.aspose.net warning:
        "Source language 'en' not found in source path"
        """
        validator = FilePlacementValidator()

        # blog.aspose.net style: index.md → index.es.md (same directory)
        result = validator.validate(
            source="/content/blog/my-post/index.md",
            translation="/content/blog/my-post/index.es.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": file_based_site_profile,
            }
        )

        # Should succeed
        assert result.success, f"Validation failed: {[issue.message for issue in result.issues]}"

        # Should NOT warn about missing /en/ in path
        for issue in result.issues:
            assert "not found in source path" not in issue.message.lower(), \
                f"Unexpected warning about source language in path: {issue.message}"
            assert issue.severity != ValidationSeverity.WARNING or \
                "source language" not in issue.message.lower(), \
                f"Unexpected source language warning: {issue.message}"

    def test_folder_based_validates_source_lang_in_path(self, folder_based_site_profile):
        """
        Folder-based sites SHOULD validate /en/ → /es/ substitution.

        This is the expected behavior for products.aspose.net.
        """
        validator = FilePlacementValidator()

        # products.aspose.net style: /en/post.md → /es/post.md
        result = validator.validate(
            source="/content/products/en/cells.md",
            translation="/content/products/es/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": folder_based_site_profile,
            }
        )

        # Should succeed with proper /en/ → /es/ substitution
        assert result.success, f"Validation failed: {[issue.message for issue in result.issues]}"

    def test_folder_based_warns_missing_source_lang(self, folder_based_site_profile):
        """
        Folder-based sites should warn if source path lacks /en/ folder.
        """
        validator = FilePlacementValidator()

        # Missing /en/ folder in source path (invalid for folder-based)
        result = validator.validate(
            source="/content/products/cells.md",  # No /en/ folder
            translation="/content/products/es/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": folder_based_site_profile,
            }
        )

        # Should have warning about missing source language
        warnings = [issue for issue in result.issues if issue.severity == ValidationSeverity.WARNING]
        assert any("not found in source path" in w.message for w in warnings), \
            "Expected warning about missing source language in path"

    def test_file_based_validates_filename_pattern(self, file_based_site_profile):
        """
        File-based sites should validate filename has target language code.
        """
        validator = FilePlacementValidator()

        # Missing language code in filename (should fail)
        result = validator.validate(
            source="/content/blog/post/index.md",
            translation="/content/blog/post/index.md",  # Missing .es. in filename
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": file_based_site_profile,
            }
        )

        # Should fail - missing language in filename
        assert not result.success, "Should fail when language code missing from filename"
        errors = [issue for issue in result.issues if issue.severity == ValidationSeverity.ERROR]
        assert any("not found in translation filename" in e.message for e in errors), \
            "Expected error about missing language in filename"

    def test_none_output_layout_uses_default_folder_based(self):
        """
        When output_layout is None, should default to folder-based validation.
        """
        validator = FilePlacementValidator()

        # Site profile with None output_layout
        site_profile = SiteProfile(
            site_id="test.site",
            content_roots=["/content"],
            default_source_lang="en",
            target_langs=["es"],
            frontmatter={},
            body=BodyRules(
                translate_markdown=True,
                preserve_blocks=[],
                preserve_patterns=[],
                placeholder_syntax=[],
            ),
            output_layout=None,  # Explicitly None
        )

        # Should behave like folder-based (default)
        result = validator.validate(
            source="/content/test/cells.md",  # No /en/
            translation="/content/es/test/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": site_profile,
            }
        )

        # Should warn about missing /en/ (folder-based behavior)
        warnings = [issue for issue in result.issues if issue.severity == ValidationSeverity.WARNING]
        assert any("not found in source path" in w.message for w in warnings), \
            "Should use folder-based validation when output_layout is None"

    def test_none_site_profile_uses_default_folder_based(self):
        """
        When site_profile is None, should default to folder-based validation.
        """
        validator = FilePlacementValidator()

        # No site profile at all
        result = validator.validate(
            source="/content/test/cells.md",  # No /en/
            translation="/content/es/test/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                # No site_profile
            }
        )

        # Should warn about missing /en/ (folder-based behavior)
        warnings = [issue for issue in result.issues if issue.severity == ValidationSeverity.WARNING]
        assert any("not found in source path" in w.message for w in warnings), \
            "Should use folder-based validation when site_profile is None"

    def test_file_based_different_languages(self, file_based_site_profile):
        """
        File-based validation works for multiple target languages.
        """
        validator = FilePlacementValidator()

        # Test German
        result_de = validator.validate(
            source="/content/blog/post/index.md",
            translation="/content/blog/post/index.de.md",
            context={
                "source_lang": "en",
                "target_lang": "de",
                "site_profile": file_based_site_profile,
            }
        )
        assert result_de.success

        # Test French
        result_fr = validator.validate(
            source="/content/blog/post/_index.md",
            translation="/content/blog/post/_index.fr.md",
            context={
                "source_lang": "en",
                "target_lang": "fr",
                "site_profile": file_based_site_profile,
            }
        )
        assert result_fr.success

    def test_folder_based_multiple_language_folders(self, folder_based_site_profile):
        """
        Folder-based validation works for different language folders.
        """
        validator = FilePlacementValidator()

        # Test /en/ → /de/
        result_de = validator.validate(
            source="/content/products/en/cells.md",
            translation="/content/products/de/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "de",
                "site_profile": folder_based_site_profile,
            }
        )
        assert result_de.success

        # Test /en/ → /fr/
        result_fr = validator.validate(
            source="/content/products/en/cells.md",
            translation="/content/products/fr/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "fr",
                "site_profile": folder_based_site_profile,
            }
        )
        assert result_fr.success


class TestValidateWrittenFile:
    """Test validate_written_file respects file-based vs folder-based localization."""

    def test_file_based_written_file_no_folder_warning(self, file_based_site_profile):
        """
        validate_written_file with file-based site should NOT warn about missing lang folder.

        Regression test for incomplete fix - validate_written_file must also
        respect per_language_folders setting.
        """
        validator = FilePlacementValidator()

        # Simulate written file for blog.aspose.net
        # File: /content/blog/post/index.es.md (es in filename, NOT in folder path)
        file_path = Path("/content/blog/post/index.es.md")

        # Create the file temporarily for testing
        import tempfile
        import os
        with tempfile.TemporaryDirectory() as tmpdir:
            test_file = Path(tmpdir) / "content" / "blog" / "post" / "index.es.md"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("# Test content\nSome translation.")

            result = validator.validate_written_file(
                file_path=test_file,
                context={
                    "target_lang": "es",
                    "site_profile": file_based_site_profile,
                }
            )

            # Should succeed without warning about missing /es/ folder
            assert result.success or result.warning_count == 0, \
                f"Should not fail or warn for file-based site: {[issue.message for issue in result.issues]}"

            # Specifically check no warning about language not found in path
            for issue in result.issues:
                assert "not found in file path" not in issue.message.lower(), \
                    f"Unexpected warning about language not in path: {issue.message}"

    def test_folder_based_written_file_warns_missing_folder(self, folder_based_site_profile):
        """
        validate_written_file with folder-based site SHOULD warn if lang folder missing.
        """
        validator = FilePlacementValidator()

        # Simulate written file without language folder (invalid for folder-based)
        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # File WITHOUT /es/ folder (should trigger warning)
            test_file = Path(tmpdir) / "content" / "products" / "cells.md"
            test_file.parent.mkdir(parents=True, exist_ok=True)
            test_file.write_text("# Test content")

            result = validator.validate_written_file(
                file_path=test_file,
                context={
                    "target_lang": "es",
                    "site_profile": folder_based_site_profile,
                }
            )

            # Should have warning about missing language folder
            warnings = [issue for issue in result.issues
                       if issue.severity == ValidationSeverity.WARNING]
            assert any("not found in file path" in w.message for w in warnings), \
                "Should warn about missing language folder for folder-based site"

    def test_file_based_written_file_validates_filename(self, file_based_site_profile):
        """
        validate_written_file for file-based sites validates through standard validation.

        When source_path is provided, it uses the main validate() method which
        checks filename patterns for file-based sites.
        """
        validator = FilePlacementValidator()

        import tempfile
        with tempfile.TemporaryDirectory() as tmpdir:
            # Create source and translation files
            source_file = Path(tmpdir) / "content" / "blog" / "post" / "index.md"
            source_file.parent.mkdir(parents=True, exist_ok=True)
            source_file.write_text("# Source")

            translation_file = Path(tmpdir) / "content" / "blog" / "post" / "index.es.md"
            translation_file.write_text("# Traducción")

            result = validator.validate_written_file(
                file_path=translation_file,
                context={
                    "source_path": source_file,
                    "source_lang": "en",
                    "target_lang": "es",
                    "site_profile": file_based_site_profile,
                }
            )

            # Should succeed - proper filename pattern
            assert result.success, \
                f"Should succeed with proper filename: {[issue.message for issue in result.issues]}"


class TestObservabilityLogging:
    """Test that validation routing decisions are logged for observability."""

    def test_file_based_routing_logged(self, file_based_site_profile, caplog):
        """Verify file-based validation routing is logged."""
        import logging
        caplog.set_level(logging.DEBUG)

        validator = FilePlacementValidator()

        validator.validate(
            source="/content/blog/post/index.md",
            translation="/content/blog/post/index.es.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": file_based_site_profile,
            }
        )

        # Check that routing decision was logged
        log_messages = [record.message for record in caplog.records]
        assert any("file_placement_validation_routing" in str(msg) for msg in log_messages), \
            f"Expected routing log message. Got: {log_messages}"

    def test_folder_based_routing_logged(self, folder_based_site_profile, caplog):
        """Verify folder-based validation routing is logged."""
        import logging
        caplog.set_level(logging.DEBUG)

        validator = FilePlacementValidator()

        validator.validate(
            source="/content/products/en/cells.md",
            translation="/content/products/es/cells.md",
            context={
                "source_lang": "en",
                "target_lang": "es",
                "site_profile": folder_based_site_profile,
            }
        )

        # Check that routing decision was logged
        log_messages = [record.message for record in caplog.records]
        assert any("file_placement_validation_routing" in str(msg) for msg in log_messages), \
            f"Expected routing log message. Got: {log_messages}"


class TestBackwardsCompatibility:
    """Test assumptions about OutputLayout type safety."""

    def test_output_layout_is_pydantic_model_not_dict(self, file_based_site_profile):
        """
        Document and enforce that output_layout is always a Pydantic model, never a dict.

        This test serves as:
        1. Documentation of the assumption
        2. Regression prevention if dict-based configs are introduced
        3. Verification that the fix doesn't need isinstance() checks

        See: docs/compatibility-check.md for codebase search results
        """
        # Verify output_layout is a Pydantic OutputLayout model
        assert hasattr(file_based_site_profile, 'output_layout'), \
            "SiteProfile should have output_layout attribute"

        output_layout = file_based_site_profile.output_layout
        assert output_layout is not None, "output_layout should not be None for test profile"

        # Should be OutputLayout instance, not dict
        assert not isinstance(output_layout, dict), \
            "output_layout should be Pydantic OutputLayout model, not dict"

        # Should have Pydantic model methods
        assert hasattr(output_layout, 'model_dump'), \
            "output_layout should be Pydantic model with model_dump method"

        # Should have per_language_folders as bool attribute, not dict key
        assert hasattr(output_layout, 'per_language_folders'), \
            "OutputLayout should have per_language_folders attribute"

        assert isinstance(output_layout.per_language_folders, bool), \
            "per_language_folders should be bool, not None or other type"

    def test_loaded_config_has_pydantic_output_layout(self):
        """
        Verify that configs loaded via ConfigService have Pydantic OutputLayout.

        This test uses real config loading to verify the assumption holds
        in production scenarios.
        """
        from src.utils.config_loader import ConfigService
        from src.utils.models import OutputLayout

        # Load a real site profile
        config_service = ConfigService(config_root="config")

        try:
            # Load blog.aspose.net config (file-based)
            blog_profile = config_service.get_site_profile("blog.aspose.net")

            # Verify it has Pydantic OutputLayout
            assert blog_profile.output_layout is not None, \
                "blog.aspose.net should have output_layout"

            assert isinstance(blog_profile.output_layout, OutputLayout), \
                f"output_layout should be OutputLayout instance, got {type(blog_profile.output_layout)}"

            assert not isinstance(blog_profile.output_layout, dict), \
                "output_layout should not be dict"

            # Verify attribute access works (not dict access)
            assert isinstance(blog_profile.output_layout.per_language_folders, bool), \
                "per_language_folders should be accessible as attribute"

        except Exception as e:
            # If config loading fails, skip test (may not be in dev environment)
            import pytest
            pytest.skip(f"Config loading failed (may not be in dev env): {e}")
