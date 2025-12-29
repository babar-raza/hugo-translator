"""
End-to-End Integration Tests for Source File Filtering

Tests the complete workflow of filtering source files from translated files
in file-based localization scenarios (blog.aspose.net pattern).

Validates:
- Directory translation skips already-translated files
- Single file translation rejects translated files
- No double-language files created (e.g., index.es.da.md)
- Correct output pattern used
"""

import pytest
import sys
import shutil
from pathlib import Path
from unittest.mock import MagicMock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.translation_engine.engine import TranslationEngine
from src.utils.config_loader import ConfigService
from src.utils.models import SiteProfile, OutputLayout, BodyRules, FrontmatterMode


@pytest.fixture
def blog_site_profile():
    """Create a site profile mimicking blog.aspose.net."""
    return SiteProfile(
        site_id="test-blog.test",
        content_roots=["content"],
        default_source_lang="en",
        target_langs=["da", "fr"],
        output_layout=OutputLayout(
            per_language_folders=False,
            pattern="{filename}.{lang}{ext}"
        ),
        frontmatter={},
        body=BodyRules(
            translate_markdown=True,
            preserve_blocks=[],
            preserve_patterns=[],
            placeholder_syntax=[]
        )
    )


@pytest.fixture
def test_fixtures_dir():
    """Get path to blog filtering test fixtures."""
    return Path(__file__).parent.parent / "fixtures" / "blog_filtering_test"


@pytest.fixture
def mock_translation_engine(blog_site_profile):
    """
    Create a TranslationEngine with mocked translation to avoid loading heavy models.

    This allows us to test the filtering logic without actual translation overhead.
    """
    config_service = MagicMock()
    config_service.get_site_profile.return_value = blog_site_profile

    # Create engine with mocked components
    engine = TranslationEngine(
        config_service=config_service,
        tm=None,
        model_loader=None
    )

    # Mock the actual translation method to return simple fake translations
    original_translate_file = engine.translate_file

    def mock_translate(file_path, target_lang, **kwargs):
        """Mock translation that just adds language suffix to content."""
        from src.translation_engine.models import TranslationResult

        # Call original to get filtering logic, but mock the actual translation
        with patch.object(engine, '_translate_content') as mock_content:
            mock_content.return_value = f"[TRANSLATED TO {target_lang.upper()}]"
            return original_translate_file(file_path, target_lang, **kwargs)

    engine.translate_file = mock_translate

    return engine


class TestSourceFileFilteringE2E:
    """Integration tests for source file filtering end-to-end workflow."""

    def test_filter_source_files_excludes_translated(
        self,
        tmp_path,
        test_fixtures_dir,
        blog_site_profile
    ):
        """
        Test that _filter_source_files correctly excludes already-translated files.

        Given a directory with:
        - index.md (source)
        - index.es.md (translated)
        - tutorial.md (source)
        - _index.md (source)

        When filtering for file-based localization with target langs [da, fr]

        Then only source files should be included in result.
        """
        # Setup: Copy fixtures to tmp directory
        test_input = tmp_path / "input"
        shutil.copytree(test_fixtures_dir, test_input)

        # Get all markdown files
        all_files = list(test_input.glob("*.md"))

        # Create minimal engine to test filtering
        config_service = MagicMock()
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        # Filter files using the method under test
        filtered_files = engine._filter_source_files(
            files=all_files,
            site_profile=blog_site_profile,
            target_langs=["da", "fr"]
        )

        # Extract just filenames for easier assertion
        filtered_names = {f.name for f in filtered_files}
        all_names = {f.name for f in all_files}

        # Assert: Only source files included
        assert "index.md" in filtered_names, "Source file index.md should be included"
        assert "tutorial.md" in filtered_names, "Source file tutorial.md should be included"
        assert "_index.md" in filtered_names, "Source file _index.md should be included"

        # Assert: Translated file excluded
        if "index.es.md" in all_names:
            assert "index.es.md" not in filtered_names, \
                "Translated file index.es.md should be excluded"

        # Assert: Expected count (3 source files if fixture has README)
        expected_sources = {"index.md", "tutorial.md", "_index.md"}
        assert filtered_names >= expected_sources, \
            f"Expected at least {expected_sources}, got {filtered_names}"


    def test_directory_translation_skips_existing_translations(
        self,
        tmp_path,
        test_fixtures_dir,
        blog_site_profile
    ):
        """
        Test that directory translation skips already-translated files.

        This test validates the key bug fix: preventing double-language files
        like index.es.da.md from being created.

        Given a directory with source files and existing translations
        When translating to additional languages
        Then existing translations should be skipped
        And no double-language files should be created.
        """
        # Setup: Copy fixtures to tmp directory
        test_input = tmp_path / "input"
        shutil.copytree(test_fixtures_dir, test_input)

        # Verify fixture has expected files
        assert (test_input / "index.md").exists(), "Missing source file"
        assert (test_input / "index.es.md").exists(), "Missing translated file"
        assert (test_input / "tutorial.md").exists(), "Missing source file"

        # Create engine with minimal config
        config_service = MagicMock()
        config_service.get_site_profile.return_value = blog_site_profile

        # We need to mock the actual translation to avoid loading models
        # But we want to test the filtering logic, so we'll check what files
        # would be processed
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        # Get files that would be translated
        markdown_files = list(test_input.glob("*.md"))
        files_to_translate = engine._filter_source_files(
            files=markdown_files,
            site_profile=blog_site_profile,
            target_langs=["da", "fr"]
        )

        file_names = {f.name for f in files_to_translate}

        # Assert: Source files included
        assert "index.md" in file_names
        assert "tutorial.md" in file_names
        assert "_index.md" in file_names

        # Assert: Translated file excluded (key assertion)
        assert "index.es.md" not in file_names, \
            "index.es.md should be skipped to prevent index.es.da.md creation"

        # Additional assertion: Verify no README.md included (if it exists)
        # README files are typically documentation, not content
        if (test_input / "README.md").exists():
            # README might be included depending on filtering rules
            # This is acceptable as long as translated files are excluded
            pass


    def test_single_file_translation_rejects_translated_file(
        self,
        tmp_path,
        test_fixtures_dir,
        blog_site_profile
    ):
        """
        Test that attempting to translate an already-translated file is rejected.

        Given a file with language code in name (e.g., index.es.md)
        When attempting to translate it
        Then translation should be rejected with clear error message.
        """
        # Setup: Copy a translated file
        test_file = tmp_path / "index.es.md"
        source_file = test_fixtures_dir / "index.es.md"
        shutil.copy(source_file, test_file)

        # Create engine
        config_service = MagicMock()
        config_service.get_site_profile.return_value = blog_site_profile

        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        # Attempt to translate the file
        # The safety check should reject it early, before any actual translation
        result = engine.translate_file(
            site_id="test-blog.test",
            file_path=test_file,
            target_langs=["da", "fr"],
            force=False
        )

        # Assert: Translation rejected
        assert result.success is False, "Translation of translated file should fail"
        assert len(result.errors) > 0, "Should have error message"

        # Assert: Error message is clear and actionable
        error_text = " ".join(result.errors).lower()
        assert "already-translated" in error_text or "refusing to translate" in error_text, \
            f"Error should mention already-translated file: {result.errors}"
        assert "index.es.md" in error_text, \
            f"Error should mention the problematic filename: {result.errors}"


    def test_no_double_language_files_created(
        self,
        tmp_path,
        test_fixtures_dir,
        blog_site_profile
    ):
        """
        Test the core bug fix: verify no double-language files are created.

        This is a critical regression test for the original issue where
        index.es.md was being translated to index.es.da.md.

        Given a directory with index.es.md
        When filtering files for translation to [da, fr]
        Then index.es.md should NOT be in the list
        And therefore index.es.da.md cannot be created.
        """
        # Setup
        test_input = tmp_path / "input"
        shutil.copytree(test_fixtures_dir, test_input)

        # Create engine
        config_service = MagicMock()
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        # Get all files including translated ones
        all_files = sorted(test_input.glob("*.md"))
        all_names = [f.name for f in all_files]

        # Filter to get files that would be translated
        filtered_files = engine._filter_source_files(
            files=all_files,
            site_profile=blog_site_profile,
            target_langs=["da", "fr"]
        )

        filtered_names = [f.name for f in filtered_files]

        # Assert: No translated files in the list
        for filename in all_names:
            if ".es." in filename or ".da." in filename or ".fr." in filename:
                assert filename not in filtered_names, \
                    f"Translated file {filename} should be filtered out"

        # Assert: Only source files (no language code before extension)
        for filename in filtered_names:
            # Check that filename doesn't match pattern: *.{lang}.md
            stem = Path(filename).stem
            # If stem ends with a language code, it's a translated file
            for lang in ["es", "da", "fr", "de", "pt", "zh", "ar"]:
                assert not stem.endswith(f".{lang}"), \
                    f"File {filename} appears to be translated (ends with .{lang})"


    def test_filtering_with_case_insensitive_extensions(
        self,
        tmp_path,
        blog_site_profile
    ):
        """
        Test that filtering works with case-insensitive file extensions.

        Validates: index.ES.MD and index.es.md are both detected as translated.
        """
        # Create test files with various cases
        (tmp_path / "index.md").write_text("Source")
        (tmp_path / "index.ES.MD").write_text("Spanish")
        (tmp_path / "tutorial.es.MD").write_text("Spanish")
        (tmp_path / "guide.Es.Md").write_text("Spanish")

        config_service = MagicMock()
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        all_files = list(tmp_path.glob("*.[Mm][Dd]"))
        filtered = engine._filter_source_files(
            files=all_files,
            site_profile=blog_site_profile,
            target_langs=["es", "da"]
        )

        filtered_names = {f.name for f in filtered}

        # Only index.md should be included (all others have language codes)
        assert "index.md" in filtered_names
        assert "index.ES.MD" not in filtered_names
        assert "tutorial.es.MD" not in filtered_names
        assert "guide.Es.Md" not in filtered_names


    def test_filtering_respects_target_languages(
        self,
        tmp_path,
        blog_site_profile
    ):
        """
        Test that filtering uses both default language codes and target_langs.

        Files with target language codes should be filtered even if not in
        the default language list.
        """
        # Create files
        (tmp_path / "index.md").write_text("Source")
        (tmp_path / "index.customlang.md").write_text("Custom language")
        (tmp_path / "tutorial.md").write_text("Source")

        config_service = MagicMock()
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        all_files = list(tmp_path.glob("*.md"))

        # Filter with custom target language
        filtered = engine._filter_source_files(
            files=all_files,
            site_profile=blog_site_profile,
            target_langs=["customlang", "da"]
        )

        filtered_names = {f.name for f in filtered}

        # index.customlang.md should be filtered because customlang is in target_langs
        assert "index.md" in filtered_names
        assert "tutorial.md" in filtered_names
        assert "index.customlang.md" not in filtered_names, \
            "File with custom target language should be filtered"


class TestFilteringObservabilityE2E:
    """Test observability features like logging in integration scenarios."""

    def test_filtering_logs_summary(
        self,
        tmp_path,
        test_fixtures_dir,
        blog_site_profile,
        caplog
    ):
        """
        Test that filtering operations log a summary.

        Validates observability requirement: users should see what was filtered.
        """
        import logging

        # Setup
        test_input = tmp_path / "input"
        shutil.copytree(test_fixtures_dir, test_input)

        config_service = MagicMock()
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        all_files = list(test_input.glob("*.md"))

        # Filter with logging enabled
        with caplog.at_level(logging.INFO):
            filtered = engine._filter_source_files(
                files=all_files,
                site_profile=blog_site_profile,
                target_langs=["da", "fr"]
            )

        # Assert: Summary log present
        log_text = caplog.text.lower()

        # Should log something about filtering
        if len(all_files) != len(filtered):
            # Only logs if files were actually filtered
            assert "filtering" in log_text or "skipped" in log_text, \
                f"Expected filtering summary in logs: {caplog.text}"


    def test_high_filter_rate_warning(
        self,
        tmp_path,
        blog_site_profile,
        caplog
    ):
        """
        Test that unusually high filter rates trigger a warning.

        This helps users identify configuration issues (e.g., wrong directory).
        """
        import logging

        # Create scenario with high filter rate: 50 translated, 2 source
        for i in range(50):
            (tmp_path / f"file{i}.es.md").write_text("Translated")

        (tmp_path / "index.md").write_text("Source")
        (tmp_path / "tutorial.md").write_text("Source")

        config_service = MagicMock()
        engine = TranslationEngine(
            config_service=config_service,
            tm=None,
            model_loader=None
        )

        all_files = list(tmp_path.glob("*.md"))

        # Filter with logging
        with caplog.at_level(logging.WARNING):
            filtered = engine._filter_source_files(
                files=all_files,
                site_profile=blog_site_profile,
                target_langs=["es", "da"]
            )

        # Assert: Warning logged
        log_text = caplog.text.lower()

        # Should warn about high filter rate
        assert "warning" in log_text or "filtered" in log_text, \
            f"Expected warning for high filter rate: {caplog.text}"

        # Should mention the percentage
        assert "%" in caplog.text, \
            "Warning should include percentage of filtered files"
