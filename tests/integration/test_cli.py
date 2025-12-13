"""
Integration tests for CLI flags (CFG-03).

Tests that CLI flags correctly override configuration settings
and are passed to the TranslationEngine.
"""
import argparse
import sys
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.cli import (
    CLIConfigOverrides,
    create_parser,
    main,
    translate_site,
)


class TestCLIParser:
    """Test CLI argument parser creation and parsing."""

    def test_parser_creation(self):
        """Test that parser is created with all expected arguments."""
        parser = create_parser()
        assert parser is not None
        assert parser.prog == "translate-hugo"

    def test_parser_required_args(self):
        """Test that required arguments are enforced."""
        parser = create_parser()

        # Missing --site should fail
        with pytest.raises(SystemExit):
            parser.parse_args([])

    def test_parser_validation_mode_choices(self):
        """Test that validation-mode accepts valid choices."""
        parser = create_parser()

        # Valid choices
        for mode in ["strict", "normal", "lenient", "off"]:
            args = parser.parse_args(["--site", "test", "--validation-mode", mode])
            assert args.validation_mode == mode

        # Invalid choice should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["--site", "test", "--validation-mode", "invalid"])

    def test_parser_terminology_mode_choices(self):
        """Test that terminology-mode accepts valid choices."""
        parser = create_parser()

        # Valid choices
        for mode in ["protect", "validate", "both", "none"]:
            args = parser.parse_args(["--site", "test", "--terminology-mode", mode])
            assert args.terminology_mode == mode

        # Invalid choice should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["--site", "test", "--terminology-mode", "invalid"])

    def test_parser_max_retries(self):
        """Test that max-retries accepts integer values."""
        parser = create_parser()

        args = parser.parse_args(["--site", "test", "--max-retries", "5"])
        assert args.max_retries == 5

        # Non-integer should fail
        with pytest.raises(SystemExit):
            parser.parse_args(["--site", "test", "--max-retries", "invalid"])

    def test_parser_boolean_flags(self):
        """Test boolean flags."""
        parser = create_parser()

        # Test disable-validation
        args = parser.parse_args(["--site", "test", "--disable-validation"])
        assert args.disable_validation is True

        # Test enable-terminology
        args = parser.parse_args(["--site", "test", "--enable-terminology"])
        assert args.enable_terminology is True

        # Test disable-terminology
        args = parser.parse_args(["--site", "test", "--disable-terminology"])
        assert args.disable_terminology is True

        # Test dry-run
        args = parser.parse_args(["--site", "test", "--dry-run"])
        assert args.dry_run is True

        # Test save-rejected
        args = parser.parse_args(["--site", "test", "--save-rejected"])
        assert args.save_rejected is True

    def test_parser_config_paths(self):
        """Test config path overrides."""
        parser = create_parser()

        args = parser.parse_args([
            "--site", "test",
            "--validation-config", "/custom/validation.yaml",
            "--terminology-config", "/custom/terminology.yaml"
        ])
        assert args.validation_config == "/custom/validation.yaml"
        assert args.terminology_config == "/custom/terminology.yaml"


class TestCLIConfigOverrides:
    """Test CLIConfigOverrides class."""

    def test_override_initialization(self):
        """Test that overrides are correctly initialized from args."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-mode", "strict",
            "--max-retries", "5",
            "--dry-run"
        ])

        overrides = CLIConfigOverrides(args)
        assert overrides.validation_mode == "strict"
        assert overrides.max_retries == 5
        assert overrides.dry_run is True
        assert overrides.disable_validation is False

    def test_override_disable_validation(self):
        """Test disable-validation flag."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--disable-validation"])

        overrides = CLIConfigOverrides(args)
        assert overrides.disable_validation is True

    def test_override_terminology_flags(self):
        """Test terminology enable/disable flags."""
        parser = create_parser()

        # Test enable
        args = parser.parse_args(["--site", "test", "--enable-terminology"])
        overrides = CLIConfigOverrides(args)
        assert overrides.enable_terminology is True

        # Test disable
        args = parser.parse_args(["--site", "test", "--disable-terminology"])
        overrides = CLIConfigOverrides(args)
        assert overrides.enable_terminology is False

        # Test neither (should be None)
        args = parser.parse_args(["--site", "test"])
        overrides = CLIConfigOverrides(args)
        assert overrides.enable_terminology is None

    def test_get_engine_overrides_validation_mode(self):
        """Test that validation mode is correctly passed to engine overrides."""
        parser = create_parser()

        # Test strict mode
        args = parser.parse_args(["--site", "test", "--validation-mode", "strict"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["enable_validation"] is True
        assert engine_overrides["validation_mode"] == "strict"

        # Test off mode
        args = parser.parse_args(["--site", "test", "--validation-mode", "off"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["enable_validation"] is False

    def test_get_engine_overrides_disable_validation(self):
        """Test that disable-validation flag disables validation."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--disable-validation"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["enable_validation"] is False

    def test_get_engine_overrides_terminology(self):
        """Test that terminology flags are passed to engine overrides."""
        parser = create_parser()

        # Test enable terminology
        args = parser.parse_args([
            "--site", "test",
            "--enable-terminology",
            "--terminology-mode", "both"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["enable_terminology"] is True
        assert engine_overrides["terminology_mode"] == "both"

    def test_get_engine_overrides_max_retries(self):
        """Test that max-retries is passed to engine overrides."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--max-retries", "5"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["max_retries"] == 5

    def test_get_engine_overrides_dry_run_and_save_rejected(self):
        """Test that dry-run and save-rejected are passed to engine overrides."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--dry-run", "--save-rejected"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["dry_run"] is True
        assert engine_overrides["save_rejected"] is True


class TestCLIIntegration:
    """Integration tests for CLI with mocked dependencies."""

    @patch("src.cli.ConfigService")
    @patch("src.cli.TranslationMemory")
    @patch("src.cli.ModelLoader")
    @patch("src.cli.TranslationEngine")
    def test_cli_validation_mode_override(
        self, mock_engine_class, mock_loader_class, mock_tm_class, mock_config_class
    ):
        """Test that --validation-mode correctly overrides config."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_site_profile.tm_prefs.use_semantic_tm = True
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.translate_directory.return_value = MagicMock(
            total_files=1, success_count=1, failed_count=0
        )
        mock_engine_class.return_value = mock_engine

        # Create args with validation mode override
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-mode", "strict"
        ])

        # Run translate_site
        exit_code = translate_site(args)

        # Verify engine was initialized with correct overrides
        assert mock_engine_class.called
        call_kwargs = mock_engine_class.call_args[1]
        assert call_kwargs["enable_validation"] is True
        assert call_kwargs["validation_mode"] == "strict"
        assert exit_code == 0

    @patch("src.cli.ConfigService")
    @patch("src.cli.TranslationMemory")
    @patch("src.cli.ModelLoader")
    @patch("src.cli.TranslationEngine")
    def test_cli_disable_validation(
        self, mock_engine_class, mock_loader_class, mock_tm_class, mock_config_class
    ):
        """Test that --disable-validation works."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_site_profile.tm_prefs.use_semantic_tm = True
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.translate_directory.return_value = MagicMock(
            total_files=1, success_count=1, failed_count=0
        )
        mock_engine_class.return_value = mock_engine

        # Create args with disable-validation
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--disable-validation"
        ])

        # Run translate_site
        exit_code = translate_site(args)

        # Verify engine was initialized with validation disabled
        assert mock_engine_class.called
        call_kwargs = mock_engine_class.call_args[1]
        assert call_kwargs["enable_validation"] is False
        assert exit_code == 0

    @patch("src.cli.ConfigService")
    @patch("src.cli.TranslationMemory")
    @patch("src.cli.ModelLoader")
    @patch("src.cli.TranslationEngine")
    def test_cli_terminology_flags(
        self, mock_engine_class, mock_loader_class, mock_tm_class, mock_config_class
    ):
        """Test terminology control flags."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_site_profile.tm_prefs.use_semantic_tm = True
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.translate_directory.return_value = MagicMock(
            total_files=1, success_count=1, failed_count=0
        )
        mock_engine_class.return_value = mock_engine

        # Create args with terminology flags
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--enable-terminology",
            "--terminology-mode", "both"
        ])

        # Run translate_site
        exit_code = translate_site(args)

        # Verify engine was initialized with terminology settings
        assert mock_engine_class.called
        call_kwargs = mock_engine_class.call_args[1]
        assert call_kwargs["enable_terminology"] is True
        assert call_kwargs["terminology_mode"] == "both"
        assert exit_code == 0

    @patch("src.cli.ConfigService")
    @patch("src.cli.TranslationMemory")
    @patch("src.cli.ModelLoader")
    @patch("src.cli.TranslationEngine")
    def test_cli_max_retries_override(
        self, mock_engine_class, mock_loader_class, mock_tm_class, mock_config_class
    ):
        """Test that --max-retries overrides config."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_site_profile.tm_prefs.use_semantic_tm = True
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.translate_directory.return_value = MagicMock(
            total_files=1, success_count=1, failed_count=0
        )
        mock_engine_class.return_value = mock_engine

        # Create args with max-retries override
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--max-retries", "5"
        ])

        # Run translate_site
        exit_code = translate_site(args)

        # Verify engine was initialized with max_retries override
        assert mock_engine_class.called
        call_kwargs = mock_engine_class.call_args[1]
        assert call_kwargs["max_retries"] == 5
        assert exit_code == 0

    @patch("src.cli.ConfigService")
    @patch("src.cli.TranslationMemory")
    @patch("src.cli.ModelLoader")
    @patch("src.cli.TranslationEngine")
    def test_config_path_overrides(
        self, mock_engine_class, mock_loader_class, mock_tm_class, mock_config_class
    ):
        """Test custom config path overrides."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_site_profile.tm_prefs.use_semantic_tm = True
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.translate_directory.return_value = MagicMock(
            total_files=1, success_count=1, failed_count=0
        )
        mock_engine_class.return_value = mock_engine

        # Create args with custom config paths
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-config", "/custom/validation.yaml",
            "--terminology-config", "/custom/terminology.yaml"
        ])

        # Run translate_site
        exit_code = translate_site(args)

        # Verify config paths were updated
        assert mock_config.validation_config_path == Path("/custom/validation.yaml")
        assert mock_config.terminology_config_path == Path("/custom/terminology.yaml")
        assert exit_code == 0

    @patch("src.cli.ConfigService")
    @patch("src.cli.TranslationMemory")
    @patch("src.cli.ModelLoader")
    @patch("src.cli.TranslationEngine")
    def test_cli_dry_run_mode(
        self, mock_engine_class, mock_loader_class, mock_tm_class, mock_config_class
    ):
        """Test dry-run mode."""
        # Setup mocks
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_site_profile.tm_prefs.use_semantic_tm = True
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        mock_engine = MagicMock()
        mock_engine.translate_directory.return_value = MagicMock(
            total_files=1, success_count=1, failed_count=0
        )
        mock_engine_class.return_value = mock_engine

        # Create args with dry-run
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--dry-run"
        ])

        # Run translate_site
        exit_code = translate_site(args)

        # Verify engine was initialized with dry_run
        assert mock_engine_class.called
        call_kwargs = mock_engine_class.call_args[1]
        assert call_kwargs["dry_run"] is True
        assert exit_code == 0


class TestCLIHelp:
    """Test CLI help text."""

    def test_help_displays(self):
        """Test that --help displays without error."""
        parser = create_parser()

        # This should not raise an exception
        try:
            with pytest.raises(SystemExit) as exc_info:
                parser.parse_args(["--help"])
            # Help exits with 0
            assert exc_info.value.code == 0
        except Exception as e:
            pytest.fail(f"Help should not raise exception: {e}")

    def test_help_contains_validation_flags(self):
        """Test that help text contains validation flags."""
        parser = create_parser()

        # Get help text
        help_text = parser.format_help()

        # Check for validation flags
        assert "--validation-mode" in help_text
        assert "--disable-validation" in help_text
        assert "--validation-config" in help_text
        assert "--max-retries" in help_text

    def test_help_contains_terminology_flags(self):
        """Test that help text contains terminology flags."""
        parser = create_parser()

        # Get help text
        help_text = parser.format_help()

        # Check for terminology flags
        assert "--enable-terminology" in help_text
        assert "--disable-terminology" in help_text
        assert "--terminology-mode" in help_text
        assert "--terminology-config" in help_text

    def test_help_contains_output_flags(self):
        """Test that help text contains output control flags."""
        parser = create_parser()

        # Get help text
        help_text = parser.format_help()

        # Check for output flags
        assert "--dry-run" in help_text
        assert "--save-rejected" in help_text
