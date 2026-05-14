"""
Integration tests for CLI flags (CFG-03).

Tests that CLI flags correctly override configuration settings
and are passed to the TranslationEngine.
"""
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.cli import (
    CLIConfigOverrides,
    create_parser,
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

        # Test force-accept
        args = parser.parse_args(["--site", "test", "--force-accept"])
        assert args.force_accept is True

        # Test strict-reject
        args = parser.parse_args(["--site", "test", "--strict-reject"])
        assert args.strict_reject is True

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

    def test_get_engine_overrides_force_accept(self):
        """Test that force-accept disables validation."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--force-accept"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["enable_validation"] is False

    def test_get_engine_overrides_strict_reject(self):
        """Test that strict-reject sets strict mode and zero retries."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--strict-reject"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["validation_mode"] == "strict"
        assert engine_overrides["max_retries"] == 0

    def test_strict_reject_overrides_max_retries(self):
        """Test that strict-reject overrides any max-retries setting."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--strict-reject", "--max-retries", "5"])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        # strict-reject should force max_retries to 0
        assert engine_overrides["max_retries"] == 0
        assert engine_overrides["validation_mode"] == "strict"


class TestCLIIntegration:
    """Integration tests for CLI with mocked dependencies.

    translate_site() dispatches each target language to a subprocess via Popen
    (process-isolation for model state). Tests mock Popen to verify that CLI
    flags are correctly forwarded to the per-language subprocess command.
    Engine kwargs are verified via TestCLIConfigOverrides for the unit layer.
    """

    def _setup_mocks(self, mock_config_class, mock_popen, mock_get_lock):
        """Configure common mocks for translate_site integration tests."""
        mock_config = MagicMock()
        mock_config.global_config.tm_data_dir = "/tmp/tm"
        mock_config.global_config.model_cache_dir = "/tmp/models"
        mock_site_profile = MagicMock()
        mock_site_profile.content_roots = ["/content"]
        mock_site_profile.target_langs = ["de", "es"]
        mock_config.get_site_profile.return_value = mock_site_profile
        mock_config_class.return_value = mock_config

        # Mock site lock to succeed immediately
        mock_lock = MagicMock()
        mock_lock.acquire.return_value = True
        mock_lock._locked = True
        mock_get_lock.return_value = mock_lock

        # Mock Popen: each call returns a process that exits 0 immediately
        def _make_proc(*args, **kwargs):
            mock_pipe = MagicMock()
            mock_pipe.readline.return_value = ""  # EOF on first read
            proc = MagicMock()
            proc.stdout = mock_pipe
            proc.stderr = mock_pipe
            proc.wait.return_value = 0
            return proc

        mock_popen.side_effect = _make_proc
        return mock_config

    def _get_subprocess_cmd(self, mock_popen):
        """Return the command list passed to the first Popen call."""
        assert mock_popen.called, "Expected subprocess.Popen to be called"
        return mock_popen.call_args_list[0][0][0]

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_validation_mode_override(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that --validation-mode is forwarded to per-language subprocess."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--validation-mode", "strict"])
        exit_code = translate_site(args)

        assert exit_code == 0
        cmd = self._get_subprocess_cmd(mock_popen)
        assert "--validation-mode" in cmd
        assert "strict" in cmd

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_disable_validation(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that --disable-validation is forwarded to per-language subprocess."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--disable-validation"])
        exit_code = translate_site(args)

        assert exit_code == 0
        cmd = self._get_subprocess_cmd(mock_popen)
        assert "--disable-validation" in cmd

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_terminology_flags(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that --enable-terminology is forwarded to per-language subprocess."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--enable-terminology",
            "--terminology-mode", "both"
        ])
        exit_code = translate_site(args)

        assert exit_code == 0
        cmd = self._get_subprocess_cmd(mock_popen)
        assert "--enable-terminology" in cmd

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_max_retries_override(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that translate_site dispatches subprocesses when --max-retries provided."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--max-retries", "5"])
        exit_code = translate_site(args)

        # --max-retries applies in single-lang mode; multi-lang mode still dispatches
        assert exit_code == 0
        assert mock_popen.called

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_config_path_overrides(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that config path overrides are applied on the parent ConfigService."""
        mock_config = self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-config", "/custom/validation.yaml",
            "--terminology-config", "/custom/terminology.yaml"
        ])
        exit_code = translate_site(args)

        # apply_to_config_service() sets these on the parent's config_service mock
        assert mock_config.validation_config_path == Path("/custom/validation.yaml")
        assert mock_config.terminology_config_path == Path("/custom/terminology.yaml")
        assert exit_code == 0

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_dry_run_mode(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that --dry-run is forwarded to per-language subprocess."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--dry-run"])
        exit_code = translate_site(args)

        assert exit_code == 0
        cmd = self._get_subprocess_cmd(mock_popen)
        assert "--dry-run" in cmd

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_force_accept(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that --force-accept is forwarded to per-language subprocess."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--force-accept"])
        exit_code = translate_site(args)

        assert exit_code == 0
        cmd = self._get_subprocess_cmd(mock_popen)
        assert "--force-accept" in cmd

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_strict_reject(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that --strict-reject is forwarded to per-language subprocess."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--strict-reject"])
        exit_code = translate_site(args)

        assert exit_code == 0
        cmd = self._get_subprocess_cmd(mock_popen)
        assert "--strict-reject" in cmd

    @patch("src.translation_engine.engine.get_site_lock")
    @patch("subprocess.Popen")
    @patch("src.utils.config_loader.ConfigService")
    def test_cli_save_rejected(
        self, mock_config_class, mock_popen, mock_get_lock
    ):
        """Test that translate_site dispatches subprocesses when --save-rejected provided."""
        self._setup_mocks(mock_config_class, mock_popen, mock_get_lock)

        parser = create_parser()
        args = parser.parse_args(["--site", "test", "--save-rejected"])
        exit_code = translate_site(args)

        # --save-rejected applies in single-lang mode; multi-lang mode still dispatches
        assert exit_code == 0
        assert mock_popen.called


class TestCLIFlagCombinations:
    """Test combinations of CLI flags."""

    def test_validation_mode_with_max_retries(self):
        """Test validation mode with max-retries."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-mode", "strict",
            "--max-retries", "3"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["validation_mode"] == "strict"
        assert engine_overrides["max_retries"] == 3

    def test_dry_run_with_save_rejected(self):
        """Test dry-run combined with save-rejected."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--dry-run",
            "--save-rejected"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["dry_run"] is True
        assert engine_overrides["save_rejected"] is True

    def test_strict_reject_with_save_rejected(self):
        """Test strict-reject combined with save-rejected for debugging."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--strict-reject",
            "--save-rejected"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["validation_mode"] == "strict"
        assert engine_overrides["max_retries"] == 0
        assert engine_overrides["save_rejected"] is True

    def test_validation_mode_with_terminology(self):
        """Test validation mode combined with terminology settings."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-mode", "lenient",
            "--enable-terminology",
            "--terminology-mode", "both"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["validation_mode"] == "lenient"
        assert engine_overrides["enable_terminology"] is True
        assert engine_overrides["terminology_mode"] == "both"

    def test_force_accept_overrides_validation_mode(self):
        """Test that force-accept disables validation even with validation-mode set."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--force-accept",
            "--validation-mode", "strict"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        # force-accept should disable validation regardless
        assert engine_overrides["enable_validation"] is False

    def test_dry_run_with_all_validation_flags(self):
        """Test dry-run with comprehensive validation configuration."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--dry-run",
            "--validation-mode", "strict",
            "--max-retries", "2",
            "--save-rejected"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["dry_run"] is True
        assert engine_overrides["validation_mode"] == "strict"
        assert engine_overrides["max_retries"] == 2
        assert engine_overrides["save_rejected"] is True

    def test_all_flags_together(self):
        """Test a realistic combination of all major flags."""
        parser = create_parser()
        args = parser.parse_args([
            "--site", "test",
            "--validation-mode", "normal",
            "--enable-terminology",
            "--terminology-mode", "validate",
            "--max-retries", "3",
            "--save-rejected",
            "--validation-config", "/custom/validation.yaml",
            "--terminology-config", "/custom/terminology.yaml"
        ])
        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()
        assert engine_overrides["validation_mode"] == "normal"
        assert engine_overrides["enable_terminology"] is True
        assert engine_overrides["terminology_mode"] == "validate"
        assert engine_overrides["max_retries"] == 3
        assert engine_overrides["save_rejected"] is True
        assert overrides.validation_config_path == "/custom/validation.yaml"
        assert overrides.terminology_config_path == "/custom/terminology.yaml"


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

    def test_help_contains_force_accept_and_strict_reject(self):
        """Test that help text contains force-accept and strict-reject flags."""
        parser = create_parser()

        # Get help text
        help_text = parser.format_help()

        # Check for new validation flags
        assert "--force-accept" in help_text
        assert "--strict-reject" in help_text
