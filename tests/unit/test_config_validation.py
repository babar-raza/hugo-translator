"""
Unit tests for validation configuration and CLI overrides.

Tests cover:
- Site profile validation schema and loading
- CLI validation flag overrides
- Validation mode precedence (CLI > Profile > Global)
- Validation config merging
- Validator-specific settings
"""

from pathlib import Path
from unittest.mock import Mock

import pytest

from src.cli import CLIConfigOverrides, create_parser
from src.utils.config_loader import ConfigService


@pytest.fixture
def config_root():
    """Return the path to the config directory."""
    return Path(__file__).parent.parent.parent / "config"


@pytest.fixture
def config_service(config_root):
    """Create a ConfigService instance."""
    return ConfigService(config_root)


class TestSiteProfileValidationSchema:
    """Tests for validation configuration in site profiles."""

    def test_products_profile_has_validation_config(self, config_service):
        """Test that products.aspose.net profile has validation configuration."""
        profile = config_service.get_site_profile("products.aspose.net")

        assert profile.validation is not None
        assert hasattr(profile.validation, "enabled")
        assert hasattr(profile.validation, "validation_mode")
        assert hasattr(profile.validation, "validators")

    def test_products_validation_mode(self, config_service):
        """Test that products.aspose.net has normal validation mode."""
        profile = config_service.get_site_profile("products.aspose.net")

        assert profile.validation.enabled is True
        assert profile.validation.validation_mode == "normal"

    def test_products_validators_config(self, config_service):
        """Test that products.aspose.net has validator-specific settings."""
        profile = config_service.get_site_profile("products.aspose.net")

        validators = profile.validation.validators

        # Check all required validators are configured
        assert "completeness" in validators
        assert validators["completeness"]["enabled"] is True

        assert "language_consistency" in validators
        assert validators["language_consistency"]["enabled"] is True
        assert validators["language_consistency"]["confidence_threshold"] == 0.85

        assert "shortcode_preservation" in validators
        assert validators["shortcode_preservation"]["enabled"] is True

        assert "frontmatter_protection" in validators
        assert validators["frontmatter_protection"]["enabled"] is True

        assert "terminology_preservation" in validators
        assert validators["terminology_preservation"]["enabled"] is True
        assert validators["terminology_preservation"]["validation_mode"] == "strict"

        assert "file_placement" in validators
        assert validators["file_placement"]["enabled"] is True

    def test_products_post_write_validation(self, config_service):
        """Test that products.aspose.net has post-write validation enabled."""
        profile = config_service.get_site_profile("products.aspose.net")

        assert profile.validation.post_write_validation is True

    def test_kb_profile_has_validation_config(self, config_service):
        """Test that kb.aspose.net profile has validation configuration."""
        profile = config_service.get_site_profile("kb.aspose.net")

        assert profile.validation is not None
        assert profile.validation.enabled is True
        assert profile.validation.validation_mode == "normal"

    def test_kb_validators_config(self, config_service):
        """Test that kb.aspose.net has validator-specific settings."""
        profile = config_service.get_site_profile("kb.aspose.net")

        validators = profile.validation.validators

        # Check validators are configured with appropriate modes
        assert "completeness" in validators
        assert "language_consistency" in validators
        assert "terminology_preservation" in validators
        assert validators["terminology_preservation"]["validation_mode"] == "normal"


class TestCLIValidationFlags:
    """Tests for CLI validation flag parsing and application."""

    def test_validation_mode_flag_parsing(self):
        """Test that --validation-mode flag is parsed correctly."""
        parser = create_parser()

        # Test each validation mode
        for mode in ["strict", "normal", "lenient", "off"]:
            args = parser.parse_args(["--site", "test.site", "--validation-mode", mode])
            assert args.validation_mode == mode

    def test_disable_validation_flag(self):
        """Test that --disable-validation flag is parsed correctly."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--disable-validation"])

        assert args.disable_validation is True

    def test_validation_config_flag(self):
        """Test that --validation-config flag is parsed correctly."""
        parser = create_parser()
        args = parser.parse_args(
            ["--site", "test.site", "--validation-config", "/path/to/custom-validation.yaml"]
        )

        assert args.validation_config == "/path/to/custom-validation.yaml"

    def test_max_retries_flag(self):
        """Test that --max-retries flag is parsed correctly."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--max-retries", "5"])

        assert args.max_retries == 5

    def test_cli_overrides_disable_validation(self):
        """Test that CLIConfigOverrides correctly handles --disable-validation."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--disable-validation"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["enable_validation"] is False

    def test_cli_overrides_validation_mode_off(self):
        """Test that CLIConfigOverrides handles --validation-mode off."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--validation-mode", "off"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["enable_validation"] is False

    def test_cli_overrides_validation_mode_strict(self):
        """Test that CLIConfigOverrides handles --validation-mode strict."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--validation-mode", "strict"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["enable_validation"] is True
        assert engine_overrides["validation_mode"] == "strict"

    def test_cli_overrides_max_retries(self):
        """Test that CLIConfigOverrides handles --max-retries."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--max-retries", "3"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["max_retries"] == 3

    def test_cli_overrides_validation_config_path(self):
        """Test that CLIConfigOverrides handles --validation-config."""
        parser = create_parser()
        args = parser.parse_args(
            ["--site", "test.site", "--validation-config", "/custom/validation.yaml"]
        )

        overrides = CLIConfigOverrides(args)

        # Create mock config service
        mock_service = Mock()
        overrides.apply_to_config_service(mock_service)

        assert mock_service.validation_config_path == Path("/custom/validation.yaml")

    def test_cli_overrides_dry_run(self):
        """Test that CLIConfigOverrides handles --dry-run."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--dry-run"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["dry_run"] is True

    def test_cli_overrides_save_rejected(self):
        """Test that CLIConfigOverrides handles --save-rejected."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--save-rejected"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        assert engine_overrides["save_rejected"] is True


class TestValidationConfigPrecedence:
    """Tests for validation config precedence: CLI > Profile > Global."""

    def test_cli_overrides_profile_validation_mode(self, config_service):
        """Test that CLI validation mode overrides profile setting."""
        parser = create_parser()

        # Profile has "normal", CLI specifies "strict"
        args = parser.parse_args(["--site", "products.aspose.net", "--validation-mode", "strict"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        # CLI should override profile
        assert engine_overrides["validation_mode"] == "strict"

    def test_cli_disable_overrides_profile_enabled(self, config_service):
        """Test that CLI --disable-validation overrides profile enabled setting."""
        parser = create_parser()

        # Profile has validation enabled, CLI disables it
        args = parser.parse_args(["--site", "products.aspose.net", "--disable-validation"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        # CLI should override profile
        assert engine_overrides["enable_validation"] is False

    def test_profile_overrides_global_when_no_cli(self, config_service):
        """Test that profile settings are used when no CLI override."""
        # Load profile with validation config
        profile = config_service.get_site_profile("products.aspose.net")

        # Profile should have its own validation mode
        assert profile.validation.validation_mode == "normal"

    def test_cli_max_retries_overrides_config(self):
        """Test that CLI --max-retries overrides config setting."""
        parser = create_parser()

        args = parser.parse_args(["--site", "products.aspose.net", "--max-retries", "5"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        # CLI should override any config value
        assert engine_overrides["max_retries"] == 5


class TestValidationModeDocumentation:
    """Tests to verify validation mode behaviors are documented."""

    def test_validation_modes_exist_in_config(self, config_service):
        """Test that all validation modes are defined in validation.yaml."""
        validation_config = config_service.get_validation_config()

        assert "strict" in validation_config.validation_modes
        assert "normal" in validation_config.validation_modes
        assert "lenient" in validation_config.validation_modes

    def test_strict_mode_settings(self, config_service):
        """Test strict mode settings (reject on any error)."""
        validation_config = config_service.get_validation_config()
        strict = validation_config.validation_modes["strict"]

        assert strict.accept_warnings is False
        assert strict.reject_on_error_count == 1
        assert strict.max_retry_attempts == 1

    def test_normal_mode_settings(self, config_service):
        """Test normal mode settings (balanced validation)."""
        validation_config = config_service.get_validation_config()
        normal = validation_config.validation_modes["normal"]

        assert normal.accept_warnings is True
        assert normal.reject_on_error_count == 3
        assert normal.max_retry_attempts == 2

    def test_lenient_mode_settings(self, config_service):
        """Test lenient mode settings (permissive validation)."""
        validation_config = config_service.get_validation_config()
        lenient = validation_config.validation_modes["lenient"]

        assert lenient.accept_warnings is True
        assert lenient.reject_on_error_count == 5
        assert lenient.max_retry_attempts == 2

    def test_off_mode_handled_by_cli(self):
        """Test that 'off' mode disables validation entirely."""
        parser = create_parser()
        args = parser.parse_args(["--site", "test.site", "--validation-mode", "off"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        # 'off' mode should disable validation
        assert engine_overrides["enable_validation"] is False


class TestValidatorSpecificSettings:
    """Tests for validator-specific configuration settings."""

    def test_language_consistency_threshold_configurable(self, config_service):
        """Test that language_consistency confidence_threshold is configurable."""
        profile = config_service.get_site_profile("products.aspose.net")

        lc_config = profile.validation.validators["language_consistency"]
        assert "confidence_threshold" in lc_config
        assert lc_config["confidence_threshold"] == 0.85

    def test_terminology_preservation_mode_configurable(self, config_service):
        """Test that terminology_preservation validation_mode is configurable."""
        products_profile = config_service.get_site_profile("products.aspose.net")
        kb_profile = config_service.get_site_profile("kb.aspose.net")

        # Products should have strict terminology
        products_term = products_profile.validation.validators["terminology_preservation"]
        assert products_term["validation_mode"] == "strict"

        # KB should have normal terminology
        kb_term = kb_profile.validation.validators["terminology_preservation"]
        assert kb_term["validation_mode"] == "normal"

    def test_all_validators_can_be_enabled_disabled(self, config_service):
        """Test that each validator has an enabled flag."""
        profile = config_service.get_site_profile("products.aspose.net")

        required_validators = [
            "completeness",
            "language_consistency",
            "shortcode_preservation",
            "frontmatter_protection",
            "terminology_preservation",
            "file_placement",
        ]

        for validator_name in required_validators:
            assert validator_name in profile.validation.validators
            assert "enabled" in profile.validation.validators[validator_name]


class TestConfigLoadingEndToEnd:
    """End-to-end tests for config loading with CLI overrides."""

    def test_load_site_profile_with_validation(self, config_service):
        """Test loading site profile with validation configuration."""
        profile = config_service.get_site_profile("products.aspose.net")

        assert profile is not None
        assert profile.site_id == "products.aspose.net"
        assert profile.validation is not None
        assert profile.validation.enabled is True

    def test_merge_cli_and_profile_settings(self, config_service):
        """Test that CLI overrides are merged with profile settings."""
        parser = create_parser()
        args = parser.parse_args(
            ["--site", "products.aspose.net", "--validation-mode", "strict", "--max-retries", "1"]
        )

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        # CLI overrides should be present
        assert engine_overrides["validation_mode"] == "strict"
        assert engine_overrides["max_retries"] == 1
        assert engine_overrides["enable_validation"] is True

    def test_config_without_cli_overrides(self, config_service):
        """Test config loading without CLI overrides uses profile defaults."""
        parser = create_parser()
        args = parser.parse_args(["--site", "products.aspose.net"])

        overrides = CLIConfigOverrides(args)
        engine_overrides = overrides.get_engine_overrides()

        # Should use profile/global defaults
        assert "validation_mode" not in engine_overrides  # No override
        assert overrides.validation_mode is None  # CLI didn't specify

    def test_validation_config_path_override(self, config_service):
        """Test that custom validation config path can be specified."""
        parser = create_parser()
        args = parser.parse_args(
            ["--site", "products.aspose.net", "--validation-config", "./custom-validation.yaml"]
        )

        overrides = CLIConfigOverrides(args)

        assert overrides.validation_config_path == "./custom-validation.yaml"

        # Verify it can be applied to config service
        mock_service = Mock()
        overrides.apply_to_config_service(mock_service)
        assert mock_service.validation_config_path == Path("./custom-validation.yaml")
