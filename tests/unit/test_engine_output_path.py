"""
Unit tests for TranslationEngine._get_output_path() method.

Tests SR-02 implementation: output_dir_override parameter and path resolution logic.
"""

import pytest
from pathlib import Path
from unittest.mock import MagicMock, Mock
from src.translation_engine.engine import TranslationEngine


class TestEngineOutputPath:
    """Test suite for _get_output_path() method covering all code paths."""

    @pytest.fixture
    def mock_dependencies(self):
        """Create mock dependencies for TranslationEngine initialization."""
        config_service = MagicMock()
        tm = MagicMock()
        model_loader = MagicMock()
        return config_service, tm, model_loader

    @pytest.fixture
    def mock_site_profile_basic(self):
        """Create basic mock site profile with minimal config."""
        profile = MagicMock()
        profile.default_source_lang = "en"
        profile.output_layout = None
        profile.output_dir = None
        return profile

    @pytest.fixture
    def mock_site_profile_hugo(self):
        """Create mock site profile with Hugo sibling folder pattern."""
        profile = MagicMock()
        profile.default_source_lang = "en"

        output_layout = MagicMock()
        output_layout.per_language_folders = True
        output_layout.pattern = None
        profile.output_layout = output_layout
        profile.output_dir = None
        return profile

    @pytest.fixture
    def mock_site_profile_file_based(self):
        """Create mock site profile with file-based localization pattern."""
        profile = MagicMock()
        profile.default_source_lang = "en"

        output_layout = MagicMock()
        output_layout.per_language_folders = False
        output_layout.pattern = "{filename}.{lang}{ext}"
        profile.output_layout = output_layout
        profile.output_dir = None
        return profile

    @pytest.fixture
    def mock_site_profile_custom_output_dir(self):
        """Create mock site profile with custom output_dir."""
        profile = MagicMock()
        profile.default_source_lang = "en"
        profile.output_layout = None
        profile.output_dir = "custom_output"
        return profile

    # ==================== SR-02: CLI Override Tests ====================

    def test_output_path_with_override_absolute(self, mock_dependencies, mock_site_profile_basic):
        """CLI override with absolute path takes precedence over site profile."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/tmp/custom")
        )

        result = engine._get_output_path(
            source_path=Path("/src/en/file.md"),
            target_lang="de",
            site_profile=mock_site_profile_basic
        )

        assert result == Path("/tmp/custom/de/file.md")

    def test_output_path_with_override_relative(self, mock_dependencies, mock_site_profile_basic):
        """CLI override with relative path works correctly."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("output/translations")
        )

        result = engine._get_output_path(
            source_path=Path("content/en/article.md"),
            target_lang="fr",
            site_profile=mock_site_profile_basic
        )

        assert result == Path("output/translations/fr/article.md")

    def test_output_path_with_override_windows_path(self, mock_dependencies, mock_site_profile_basic):
        """CLI override with Windows-style path works correctly."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("C:/Temp/output")
        )

        result = engine._get_output_path(
            source_path=Path("D:/content/en/file.md"),
            target_lang="es",
            site_profile=mock_site_profile_basic
        )

        assert result == Path("C:/Temp/output/es/file.md")

    def test_output_path_precedence_cli_over_hugo_profile(self, mock_dependencies, mock_site_profile_hugo):
        """CLI override takes precedence over Hugo sibling folder pattern."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/cli/override")
        )

        # Source path with /en/ pattern that would normally trigger Hugo replacement
        result = engine._get_output_path(
            source_path=Path("/content/en/articles/test.md"),
            target_lang="de",
            site_profile=mock_site_profile_hugo
        )

        # Should use CLI override, NOT Hugo pattern
        assert result == Path("/cli/override/de/test.md")
        assert "/content/de/" not in str(result)

    def test_output_path_precedence_cli_over_file_based_profile(
        self, mock_dependencies, mock_site_profile_file_based
    ):
        """CLI override takes precedence over file-based localization pattern."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/tmp/output")
        )

        result = engine._get_output_path(
            source_path=Path("/content/article.md"),
            target_lang="ja",
            site_profile=mock_site_profile_file_based
        )

        # Should use CLI override, NOT file-based pattern
        assert result == Path("/tmp/output/ja/article.md")
        assert "article.ja.md" not in str(result)

    # ==================== Site Profile Tests (No Override) ====================

    def test_output_path_without_override_hugo_sibling_pattern_forward_slash(
        self, mock_dependencies, mock_site_profile_hugo
    ):
        """Hugo sibling folder pattern with forward slash (Unix-style paths)."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("/content/en/articles/test.md"),
            target_lang="de",
            site_profile=mock_site_profile_hugo
        )

        assert result == Path("/content/de/articles/test.md")

    def test_output_path_without_override_hugo_sibling_pattern_backslash(
        self, mock_dependencies, mock_site_profile_hugo
    ):
        """Hugo sibling folder pattern with backslash (Windows-style paths)."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("D:\\content\\en\\articles\\test.md"),
            target_lang="fr",
            site_profile=mock_site_profile_hugo
        )

        expected = Path("D:\\content\\fr\\articles\\test.md")
        assert result == expected

    def test_output_path_without_override_hugo_pattern_ending_with_lang(
        self, mock_dependencies, mock_site_profile_hugo
    ):
        """Hugo pattern where path ends with language folder (no trailing separator)."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("/content/en"),
            target_lang="de",
            site_profile=mock_site_profile_hugo
        )

        assert result == Path("/content/de")

    def test_output_path_without_override_file_based_pattern(
        self, mock_dependencies, mock_site_profile_file_based
    ):
        """File-based localization with pattern substitution."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("/content/articles/index.md"),
            target_lang="es",
            site_profile=mock_site_profile_file_based
        )

        # Pattern: "{filename}.{lang}{ext}" -> "index.es.md"
        assert result == Path("/content/articles/index.es.md")

    def test_output_path_without_override_fallback_default(
        self, mock_dependencies, mock_site_profile_basic
    ):
        """Fallback to default output directory when no specific config."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("file.md"),
            target_lang="de",
            site_profile=mock_site_profile_basic
        )

        # Default fallback: output/{lang}/{filename}
        assert result == Path("output/de/file.md")

    def test_output_path_without_override_fallback_custom_output_dir(
        self, mock_dependencies, mock_site_profile_custom_output_dir
    ):
        """Fallback uses custom output_dir from site profile."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("article.md"),
            target_lang="ja",
            site_profile=mock_site_profile_custom_output_dir
        )

        assert result == Path("custom_output/ja/article.md")

    # ==================== Edge Cases ====================

    def test_output_path_with_override_none_uses_site_profile(
        self, mock_dependencies, mock_site_profile_hugo
    ):
        """Explicitly passing None for override uses site profile logic."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("/content/en/test.md"),
            target_lang="de",
            site_profile=mock_site_profile_hugo
        )

        # Should use Hugo pattern, not override
        assert result == Path("/content/de/test.md")

    def test_output_path_preserves_filename(self, mock_dependencies, mock_site_profile_basic):
        """Output path preserves original filename in all cases."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/output")
        )

        filenames = ["simple.md", "with-dashes.md", "with_underscores.md", "123numeric.md"]

        for filename in filenames:
            result = engine._get_output_path(
                source_path=Path(f"/content/{filename}"),
                target_lang="de",
                site_profile=mock_site_profile_basic
            )

            assert result.name == filename, f"Filename {filename} not preserved"

    def test_output_path_with_multiple_language_codes(self, mock_dependencies, mock_site_profile_basic):
        """Output path works correctly with various language codes."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/tmp/output")
        )

        langs = ["de", "fr", "es", "ja", "zh", "ar", "pt", "ru"]

        for lang in langs:
            result = engine._get_output_path(
                source_path=Path("file.md"),
                target_lang=lang,
                site_profile=mock_site_profile_basic
            )

            assert result == Path(f"/tmp/output/{lang}/file.md")

    def test_output_path_with_dict_output_layout(self, mock_dependencies):
        """Handle output_layout as dict (legacy format) with per_language_folders."""
        config_service, tm, model_loader = mock_dependencies

        profile = MagicMock()
        profile.default_source_lang = "en"
        # Dict-based output_layout (legacy format)
        profile.output_layout = {"per_language_folders": True}
        profile.output_dir = None

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        result = engine._get_output_path(
            source_path=Path("/content/en/test.md"),
            target_lang="de",
            site_profile=profile
        )

        assert result == Path("/content/de/test.md")

    # ==================== Integration with SR-02b (Logging) ====================

    def test_output_path_with_override_logs_correctly(
        self, mock_dependencies, mock_site_profile_basic, caplog
    ):
        """Verify logging when CLI override is used (SR-02b validation)."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=Path("/tmp/custom")
        )

        with caplog.at_level("INFO"):
            result = engine._get_output_path(
                source_path=Path("file.md"),
                target_lang="de",
                site_profile=mock_site_profile_basic
            )

        # Check that override log message appears
        assert "Using CLI output override" in caplog.text
        assert str(result) in caplog.text

    def test_output_path_without_override_logs_site_profile(
        self, mock_dependencies, mock_site_profile_basic, caplog
    ):
        """Verify logging when site profile fallback is used (SR-02b validation)."""
        config_service, tm, model_loader = mock_dependencies

        engine = TranslationEngine(
            config_service=config_service,
            tm=tm,
            model_loader=model_loader,
            output_dir_override=None
        )

        with caplog.at_level("INFO"):
            result = engine._get_output_path(
                source_path=Path("file.md"),
                target_lang="de",
                site_profile=mock_site_profile_basic
            )

        # Check that site profile log message appears
        assert "Using site profile output" in caplog.text
        assert str(result) in caplog.text
