"""
Unit tests for configuration loading and validation.

Tests cover:
- Loading validation.yaml
- Loading terminology.yaml
- Loading global.yaml with validation_defaults
- Schema validation (invalid configs rejected)
- Site override merging
- Default values
"""
import pytest
import yaml
from pathlib import Path
from pydantic import ValidationError

from src.utils.config_loader import (
    ConfigService,
    ConfigLoadError,
    ConfigValidationError,
)
from src.utils.models import (
    ValidationConfig,
    TerminologyConfig,
    GlobalConfig,
    ValidationMode,
    DecisionRules,
)


@pytest.fixture
def config_root():
    """Return the path to the config directory."""
    return Path(__file__).parent.parent.parent / "config"


@pytest.fixture
def config_service(config_root):
    """Create a ConfigService instance."""
    return ConfigService(config_root)


@pytest.fixture
def test_fixtures_dir(tmp_path):
    """Create a temporary fixtures directory for invalid configs."""
    fixtures_dir = tmp_path / "fixtures"
    fixtures_dir.mkdir()
    return fixtures_dir


class TestValidationConfigLoading:
    """Tests for loading validation.yaml configuration."""

    def test_load_validation_config(self, config_service):
        """Test that validation config loads successfully."""
        config = config_service.get_validation_config()

        assert config is not None
        assert config.version == "1.0"
        assert config.decision_rules is not None
        assert config.retry_strategy is not None
        assert config.validation_modes is not None

    def test_validation_decision_rules(self, config_service):
        """Test that decision rules are loaded with correct values."""
        config = config_service.get_validation_config()

        assert config.decision_rules.reject_on_error_count == 3
        assert config.decision_rules.reject_on_placeholder_error is True
        assert config.decision_rules.reject_on_code_block_error is True
        assert config.decision_rules.reject_on_link_error is True
        assert config.decision_rules.max_retry_attempts == 2
        assert config.decision_rules.retry_on_structure_error is True
        assert config.decision_rules.retry_on_terminology_warning is True
        assert config.decision_rules.accept_warnings is True
        assert config.decision_rules.accept_after_max_retries is True

    def test_validation_retry_strategy(self, config_service):
        """Test that retry strategy is loaded with correct values."""
        config = config_service.get_validation_config()

        assert config.retry_strategy.feedback_mode == "detailed"
        assert config.retry_strategy.vary_temperature is True
        assert config.retry_strategy.temperature_increment == 0.1
        assert config.retry_strategy.max_temperature == 1.0

    def test_validation_modes(self, config_service):
        """Test that validation modes are loaded correctly."""
        config = config_service.get_validation_config()

        # Test strict mode
        assert "strict" in config.validation_modes
        strict = config.validation_modes["strict"]
        assert strict.accept_warnings is False
        assert strict.reject_on_error_count == 1
        assert strict.max_retry_attempts == 1

        # Test normal mode
        assert "normal" in config.validation_modes
        normal = config.validation_modes["normal"]
        assert normal.accept_warnings is True
        assert normal.reject_on_error_count == 3
        assert normal.max_retry_attempts == 2

        # Test lenient mode
        assert "lenient" in config.validation_modes
        lenient = config.validation_modes["lenient"]
        assert lenient.accept_warnings is True
        assert lenient.reject_on_error_count == 5
        assert lenient.max_retry_attempts == 2

    def test_validation_config_caching(self, config_service):
        """Test that validation config is cached properly."""
        config1 = config_service.get_validation_config()
        config2 = config_service.get_validation_config()

        # Should return the same instance due to caching
        assert config1 is config2

    def test_validation_config_reload(self, config_service):
        """Test that validation config can be reloaded."""
        config1 = config_service.get_validation_config()
        config2 = config_service.reload_validation_config()

        # Should be different instances after reload
        assert config1 is not config2
        # But have the same values
        assert config1.version == config2.version


class TestTerminologyConfigLoading:
    """Tests for loading terminology.yaml configuration."""

    def test_load_terminology_config(self, config_service):
        """Test that terminology config loads successfully."""
        config = config_service.get_terminology_config()

        assert config is not None
        assert config.version == "1.0"
        assert config.global_ is not None
        assert config.site_overrides is not None
        assert config.auto_discovery is not None

    def test_global_exact_matches(self, config_service):
        """Test that global exact matches are loaded correctly."""
        config = config_service.get_terminology_config()

        exact_matches = config.global_.exact_matches
        assert len(exact_matches) >= 4  # At least Aspose, .NET, Java, Python

        # Find and verify Aspose term
        aspose_term = next((t for t in exact_matches if t.term == "Aspose"), None)
        assert aspose_term is not None
        assert aspose_term.category == "company_name"
        assert aspose_term.case_sensitive is True
        assert aspose_term.preserve_mode == "both"
        assert aspose_term.severity == "error"

        # Find and verify .NET term
        dotnet_term = next((t for t in exact_matches if t.term == ".NET"), None)
        assert dotnet_term is not None
        assert dotnet_term.category == "platform"
        assert dotnet_term.severity == "error"

    def test_global_patterns(self, config_service):
        """Test that global patterns are loaded correctly."""
        config = config_service.get_terminology_config()

        patterns = config.global_.patterns
        assert len(patterns) >= 2  # At least Aspose.* and LINQ Engine

        # Find and verify Aspose product pattern
        aspose_pattern = next(
            (p for p in patterns if "Aspose" in p.pattern), None
        )
        assert aspose_pattern is not None
        assert aspose_pattern.category == "product_family"
        assert aspose_pattern.preserve_mode == "protect"
        assert aspose_pattern.severity == "error"

        # Find and verify LINQ Engine pattern
        linq_pattern = next(
            (p for p in patterns if "LINQ Engine" in p.pattern), None
        )
        assert linq_pattern is not None
        assert linq_pattern.category == "plugin_name"
        assert linq_pattern.severity == "error"

    def test_site_overrides(self, config_service):
        """Test that site overrides are loaded correctly."""
        config = config_service.get_terminology_config()

        # Verify reference.aspose.net override exists
        assert "reference.aspose.net" in config.site_overrides
        ref_override = config.site_overrides["reference.aspose.net"]

        assert ref_override.inherit_global is True
        assert len(ref_override.patterns) >= 2  # PascalCase and UPPER_CASE patterns

        # Verify PascalCase pattern
        pascal_pattern = next(
            (p for p in ref_override.patterns if p.category == "pascal_case_identifier"),
            None
        )
        assert pascal_pattern is not None
        assert pascal_pattern.preserve_mode == "protect"
        assert pascal_pattern.severity == "error"

    def test_auto_discovery_disabled(self, config_service):
        """Test that auto-discovery is disabled by default."""
        config = config_service.get_terminology_config()

        assert config.auto_discovery.enabled is False
        assert config.auto_discovery.min_frequency == 3
        assert config.auto_discovery.confidence_threshold == 0.8

    def test_terminology_config_caching(self, config_service):
        """Test that terminology config is cached properly."""
        config1 = config_service.get_terminology_config()
        config2 = config_service.get_terminology_config()

        # Should return the same instance due to caching
        assert config1 is config2

    def test_terminology_config_reload(self, config_service):
        """Test that terminology config can be reloaded."""
        config1 = config_service.get_terminology_config()
        config2 = config_service.reload_terminology_config()

        # Should be different instances after reload
        assert config1 is not config2
        # But have the same values
        assert config1.version == config2.version


class TestGlobalConfigValidationDefaults:
    """Tests for validation_defaults section in global.yaml."""

    def test_load_global_config_with_validation_defaults(self, config_service):
        """Test that global config loads with validation_defaults section."""
        config = config_service.global_config

        assert config is not None
        assert config.validation_defaults is not None

    def test_validation_defaults_mode(self, config_service):
        """Test that validation defaults mode is set correctly."""
        config = config_service.global_config

        assert config.validation_defaults.mode == "normal"

    def test_validation_defaults_decision_rules(self, config_service):
        """Test that validation defaults decision rules are loaded."""
        config = config_service.global_config

        decision_rules = config.validation_defaults.decision_rules
        assert decision_rules.reject_on_error_count == 3
        assert decision_rules.max_retry_attempts == 2
        assert decision_rules.accept_warnings is True

    def test_validation_defaults_validators(self, config_service):
        """Test that validator configurations are loaded."""
        config = config_service.global_config

        validators = config.validation_defaults.validators
        assert "completeness" in validators
        assert validators["completeness"].enabled is True

        assert "language_consistency" in validators
        assert validators["language_consistency"].enabled is True
        assert validators["language_consistency"].confidence_threshold == 0.85

        assert "shortcode_preservation" in validators
        assert validators["shortcode_preservation"].enabled is True

        assert "frontmatter_protection" in validators
        assert validators["frontmatter_protection"].enabled is True

        assert "terminology_preservation" in validators
        assert validators["terminology_preservation"].enabled is True

        assert "file_placement" in validators
        assert validators["file_placement"].enabled is True


class TestInvalidConfigRejection:
    """Tests for rejecting invalid configurations."""

    def test_invalid_yaml_rejected(self, test_fixtures_dir):
        """Test that invalid YAML is rejected with clear error."""
        # Create an invalid YAML file
        invalid_yaml = test_fixtures_dir / "invalid.yaml"
        invalid_yaml.write_text("invalid: yaml: content: [unclosed")

        # Create a config service pointing to the test fixtures
        with pytest.raises(ConfigLoadError):
            service = ConfigService(test_fixtures_dir)

    def test_empty_validation_config_rejected(self, test_fixtures_dir):
        """Test that empty validation config is rejected."""
        # Create an empty validation config
        empty_config_dir = test_fixtures_dir / "config"
        empty_config_dir.mkdir()
        validation_yaml = empty_config_dir / "validation.yaml"
        validation_yaml.write_text("")

        service = ConfigService(empty_config_dir)
        with pytest.raises(ConfigValidationError, match="empty"):
            service.get_validation_config()

    def test_missing_required_fields_rejected(self, test_fixtures_dir):
        """Test that configs with missing required fields are rejected."""
        # Create a terminology config missing required fields
        config_dir = test_fixtures_dir / "config"
        config_dir.mkdir()
        terminology_yaml = config_dir / "terminology.yaml"
        terminology_yaml.write_text("""
version: "1.0"
global:
  exact_matches:
    - term: "Test"
      # Missing category field (required)
""")

        service = ConfigService(config_dir)
        with pytest.raises(ConfigValidationError):
            service.get_terminology_config()

    def test_type_mismatch_rejected(self, test_fixtures_dir):
        """Test that type mismatches are detected and rejected."""
        # Create a validation config with wrong types
        config_dir = test_fixtures_dir / "config"
        config_dir.mkdir()
        validation_yaml = config_dir / "validation.yaml"
        validation_yaml.write_text("""
version: "1.0"
decision_rules:
  reject_on_error_count: "three"  # Should be int, not string
  max_retry_attempts: 2
""")

        service = ConfigService(config_dir)
        with pytest.raises(ConfigValidationError):
            service.get_validation_config()

    def test_out_of_range_values_rejected(self, test_fixtures_dir):
        """Test that out-of-range values are rejected."""
        config_dir = test_fixtures_dir / "config"
        config_dir.mkdir()
        validation_yaml = config_dir / "validation.yaml"
        validation_yaml.write_text("""
version: "1.0"
decision_rules:
  reject_on_error_count: 0  # Should be >= 1
  max_retry_attempts: 2
retry_strategy:
  temperature_increment: 0.6  # Should be <= 0.5
""")

        service = ConfigService(config_dir)
        with pytest.raises(ConfigValidationError):
            service.get_validation_config()


class TestSiteOverrideMerging:
    """Tests for site-specific override merging."""

    def test_site_inherits_global_terminology(self, config_service):
        """Test that site overrides inherit global terminology when configured."""
        config = config_service.get_terminology_config()

        # reference.aspose.net should inherit global rules
        ref_override = config.site_overrides["reference.aspose.net"]
        assert ref_override.inherit_global is True

        # This means the site should have both global and site-specific patterns
        # Global patterns are in config.global_.patterns
        # Site-specific patterns are in ref_override.patterns
        assert len(config.global_.patterns) >= 2
        assert len(ref_override.patterns) >= 2


class TestDefaultValues:
    """Tests for default values in configurations."""

    def test_validation_config_default_values(self):
        """Test that ValidationConfig has sensible defaults."""
        config = ValidationConfig()

        assert config.version == "1.0"
        assert config.decision_rules is not None
        assert config.decision_rules.reject_on_error_count == 3
        assert config.decision_rules.max_retry_attempts == 2
        assert config.retry_strategy is not None
        assert config.retry_strategy.feedback_mode == "detailed"

    def test_terminology_config_default_values(self):
        """Test that TerminologyConfig has sensible defaults."""
        config = TerminologyConfig()

        assert config.version == "1.0"
        assert config.global_ is not None
        assert config.global_.exact_matches == []
        assert config.global_.patterns == []
        assert config.auto_discovery is not None
        assert config.auto_discovery.enabled is False

    def test_decision_rules_defaults(self):
        """Test that DecisionRules has sensible defaults."""
        rules = DecisionRules()

        assert rules.reject_on_error_count == 3
        assert rules.reject_on_placeholder_error is True
        assert rules.reject_on_code_block_error is True
        assert rules.reject_on_link_error is True
        assert rules.max_retry_attempts == 2
        assert rules.accept_warnings is True

    def test_validation_mode_defaults(self):
        """Test that ValidationMode has sensible defaults."""
        mode = ValidationMode()

        assert mode.accept_warnings is True
        assert mode.reject_on_error_count == 3
        assert mode.max_retry_attempts == 2


class TestConfigYAMLValidity:
    """Tests for YAML validity of configuration files."""

    def test_validation_yaml_is_valid(self, config_root):
        """Test that validation.yaml is valid YAML."""
        validation_path = config_root / "validation.yaml"

        with open(validation_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert "version" in data
        assert "decision_rules" in data
        assert "retry_strategy" in data
        assert "validation_modes" in data

    def test_terminology_yaml_is_valid(self, config_root):
        """Test that terminology.yaml is valid YAML."""
        terminology_path = config_root / "terminology.yaml"

        with open(terminology_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert "version" in data
        assert "global" in data
        assert "site_overrides" in data
        assert "auto_discovery" in data

    def test_global_yaml_has_validation_defaults(self, config_root):
        """Test that global.yaml has validation_defaults section."""
        global_path = config_root / "global.yaml"

        with open(global_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert "validation_defaults" in data
        assert "mode" in data["validation_defaults"]
        assert "decision_rules" in data["validation_defaults"]
        assert "validators" in data["validation_defaults"]

    def test_global_yaml_has_validation_section(self, config_root):
        """Test that global.yaml has top-level validation section."""
        global_path = config_root / "global.yaml"

        with open(global_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert "validation" in data
        assert data["validation"]["enabled"] is True
        assert data["validation"]["config_file"] == "config/validation.yaml"
        assert data["validation"]["mode"] == "normal"

    def test_global_yaml_has_terminology_section(self, config_root):
        """Test that global.yaml has top-level terminology section."""
        global_path = config_root / "global.yaml"

        with open(global_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert "terminology" in data
        assert data["terminology"]["enabled"] is True
        assert data["terminology"]["config_file"] == "config/terminology.yaml"
        assert data["terminology"]["preserve_mode"] == "BOTH"

    def test_global_yaml_has_telemetry_validation_metrics(self, config_root):
        """Test that global.yaml has telemetry.validation_metrics."""
        global_path = config_root / "global.yaml"

        with open(global_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        assert data is not None
        assert "telemetry" in data
        assert data["telemetry"]["validation_metrics"] is True


class TestConfigLoaderMerging:
    """Tests for ConfigLoader merging global + profile-specific settings."""

    def test_loads_validation_config(self, config_service):
        """Test that ConfigLoader loads validation config."""
        config = config_service.get_validation_config()
        assert config is not None
        assert config.version == "1.0"

    def test_loads_terminology_config(self, config_service):
        """Test that ConfigLoader loads terminology config."""
        config = config_service.get_terminology_config()
        assert config is not None
        assert config.version == "1.0"

    def test_merges_profile_validation_overrides(self, config_service):
        """Test that profile-specific validation overrides are merged with global."""
        # Load a site profile that has validation overrides
        profile = config_service.get_site_profile("products.aspose.net")

        # Get merged config
        merged = config_service.get_merged_validation_config(profile)

        assert merged is not None
        assert "enabled" in merged
        assert "mode" in merged
        assert "validators" in merged

        # Verify that profile overrides are applied
        if profile.validation and profile.validation.validation_mode:
            assert merged["mode"] == profile.validation.validation_mode

    def test_merges_profile_terminology_overrides(self, config_service):
        """Test that profile-specific terminology overrides are merged with global."""
        # Load a site profile that has terminology overrides
        profile = config_service.get_site_profile("products.aspose.net")

        # Get merged config
        merged = config_service.get_merged_terminology_config(profile)

        assert merged is not None
        assert "enabled" in merged
        assert "preserve_mode" in merged
        assert "global_terms" in merged
        assert "site_specific_terms" in merged

        # Verify inheritance behavior
        if profile.terminology and profile.terminology.inherit_global:
            # Should have global terms
            assert len(merged["global_terms"]["exact_matches"]) > 0 or \
                   len(merged["global_terms"]["patterns"]) > 0

    def test_profile_overrides_global_validation_mode(self, config_service):
        """Test that profile validation mode overrides global mode."""
        profile = config_service.get_site_profile("products.aspose.net")
        merged = config_service.get_merged_validation_config(profile)

        # If profile has a validation mode set, it should override global
        if profile.validation and profile.validation.validation_mode:
            assert merged["mode"] == profile.validation.validation_mode
        else:
            # Otherwise should use global default
            assert merged["mode"] == config_service.global_config.validation.mode

    def test_site_specific_terms_added_to_merged_config(self, config_service):
        """Test that site-specific terminology terms are added to merged config."""
        profile = config_service.get_site_profile("products.aspose.net")
        merged = config_service.get_merged_terminology_config(profile)

        # If profile has custom terms, they should be in the merged config
        if profile.terminology and profile.terminology.custom_terms:
            assert len(merged["site_specific_terms"]) > 0
