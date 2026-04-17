"""
Tests for centralized feature flag system (PR-02).

Tests verify:
1. Loading flags from config/global.yaml
2. Default values when config is missing
3. Environment variable overrides
4. Singleton pattern
5. Reload functionality
6. Dict-like access methods
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest
import yaml

from src.feature_flags import (
    FeatureFlags,
    feature_enabled,
    get_feature_flags,
    reset_feature_flags,
)


@pytest.fixture(autouse=True)
def reset_flags():
    """Reset global feature flags before each test."""
    reset_feature_flags()
    yield
    reset_feature_flags()


@pytest.fixture
def temp_config():
    """Create a temporary config file for testing."""
    with tempfile.NamedTemporaryFile(mode="w", suffix=".yaml", delete=False) as f:
        config_path = f.name
        yield config_path
    Path(config_path).unlink(missing_ok=True)


class TestFeatureFlagsBasics:
    """Test basic feature flag loading and access."""

    def test_load_from_actual_config(self):
        """Verify flags can be loaded from real config/global.yaml."""
        flags = FeatureFlags()

        # These flags are in the actual config/global.yaml
        assert isinstance(flags.is_enabled("enable_parallel_processing"), bool)
        assert isinstance(flags.is_enabled("enable_semantic_tm"), bool)
        assert isinstance(flags.is_enabled("enable_model_benchmarking"), bool)

    def test_default_flags_when_config_missing(self, temp_config):
        """Verify default flags are used when config file is missing."""
        # Point to non-existent file
        Path(temp_config).unlink()

        flags = FeatureFlags(config_path=temp_config)

        # Should use default values
        assert flags.is_enabled("enable_parallel_processing") is True
        assert flags.is_enabled("enable_semantic_tm") is True
        assert flags.is_enabled("enable_model_benchmarking") is False

    def test_is_enabled_returns_bool(self):
        """Verify is_enabled() always returns bool."""
        flags = FeatureFlags()

        result = flags.is_enabled("enable_parallel_processing")
        assert isinstance(result, bool)

    def test_is_disabled_inverse_of_is_enabled(self):
        """Verify is_disabled() is the inverse of is_enabled()."""
        flags = FeatureFlags()

        flag_name = "enable_parallel_processing"
        assert flags.is_enabled(flag_name) != flags.is_disabled(flag_name)

    def test_default_parameter_for_undefined_flag(self):
        """Verify default parameter works for undefined flags."""
        flags = FeatureFlags()

        # Undefined flag with default=True
        assert flags.is_enabled("nonexistent_flag", default=True) is True

        # Undefined flag with default=False
        assert flags.is_enabled("nonexistent_flag", default=False) is False

    def test_get_method_alias(self):
        """Verify get() method is alias for is_enabled()."""
        flags = FeatureFlags()

        flag_name = "enable_semantic_tm"
        assert flags.get(flag_name) == flags.is_enabled(flag_name)


class TestCustomConfig:
    """Test loading from custom config files."""

    def test_load_from_custom_config(self, temp_config):
        """Verify flags can be loaded from custom config file."""
        # Create custom config
        config = {
            "features": {
                "custom_feature_1": True,
                "custom_feature_2": False,
                "enable_parallel_processing": False,  # Override default
            }
        }

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        flags = FeatureFlags(config_path=temp_config)

        assert flags.is_enabled("custom_feature_1") is True
        assert flags.is_enabled("custom_feature_2") is False
        assert flags.is_enabled("enable_parallel_processing") is False

    def test_handle_invalid_yaml(self, temp_config):
        """Verify graceful handling of invalid YAML config."""
        # Write invalid YAML
        with open(temp_config, "w") as f:
            f.write("invalid: yaml: content:\n  - broken")

        # Should fall back to defaults without crashing
        flags = FeatureFlags(config_path=temp_config)

        # Should have default values
        assert flags.is_enabled("enable_parallel_processing") is True

    def test_handle_missing_features_section(self, temp_config):
        """Verify handling when config file lacks 'features' section."""
        # Config without features section
        config = {"system": {"name": "Test"}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        flags = FeatureFlags(config_path=temp_config)

        # Should fall back to defaults
        assert flags.is_enabled("enable_parallel_processing") is True


class TestEnvironmentOverrides:
    """Test environment variable override functionality."""

    def test_env_override_enabled(self, temp_config):
        """Verify environment variable can enable a flag."""
        # Create config with flag disabled
        config = {"features": {"test_feature": False}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        # Set environment variable to override
        with patch.dict(os.environ, {"FEATURE_FLAG_TEST_FEATURE": "true"}):
            flags = FeatureFlags(config_path=temp_config)

            # Should be overridden to True
            assert flags.is_enabled("test_feature") is True

    def test_env_override_disabled(self, temp_config):
        """Verify environment variable can disable a flag."""
        # Create config with flag enabled
        config = {"features": {"test_feature": True}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        # Set environment variable to override
        with patch.dict(os.environ, {"FEATURE_FLAG_TEST_FEATURE": "false"}):
            flags = FeatureFlags(config_path=temp_config)

            # Should be overridden to False
            assert flags.is_enabled("test_feature") is False

    def test_env_override_case_insensitive(self, temp_config):
        """Verify environment variable override is case-insensitive for flag name."""
        config = {"features": {"enable_model_benchmarking": False}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        # Uppercase env var should match lowercase flag name
        with patch.dict(os.environ, {"FEATURE_FLAG_ENABLE_MODEL_BENCHMARKING": "true"}):
            flags = FeatureFlags(config_path=temp_config)

            assert flags.is_enabled("enable_model_benchmarking") is True

    def test_env_override_truthy_values(self, temp_config):
        """Verify various truthy values work for environment override."""
        config = {"features": {"test_feature": False}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        truthy_values = ["true", "True", "TRUE", "1", "yes", "Yes", "on", "On"]

        for value in truthy_values:
            with patch.dict(os.environ, {"FEATURE_FLAG_TEST_FEATURE": value}):
                flags = FeatureFlags(config_path=temp_config)
                assert flags.is_enabled("test_feature") is True, f"Failed for value: {value}"
                reset_feature_flags()

    def test_env_override_falsy_values(self, temp_config):
        """Verify various falsy values work for environment override."""
        config = {"features": {"test_feature": True}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        falsy_values = ["false", "False", "FALSE", "0", "no", "No", "off", "Off"]

        for value in falsy_values:
            with patch.dict(os.environ, {"FEATURE_FLAG_TEST_FEATURE": value}):
                flags = FeatureFlags(config_path=temp_config)
                assert flags.is_enabled("test_feature") is False, f"Failed for value: {value}"
                reset_feature_flags()


class TestSingletonPattern:
    """Test global singleton functionality."""

    def test_get_feature_flags_returns_same_instance(self):
        """Verify get_feature_flags() returns singleton instance."""
        flags1 = get_feature_flags()
        flags2 = get_feature_flags()

        # Should be the same object
        assert flags1 is flags2

    def test_reset_clears_singleton(self):
        """Verify reset_feature_flags() clears singleton."""
        flags1 = get_feature_flags()

        reset_feature_flags()

        flags2 = get_feature_flags()

        # Should be different objects after reset
        assert flags1 is not flags2

    def test_convenience_function(self):
        """Verify feature_enabled() convenience function works."""
        flags = get_feature_flags()

        flag_name = "enable_parallel_processing"

        # Convenience function should match direct access
        assert feature_enabled(flag_name) == flags.is_enabled(flag_name)


class TestReloadFunctionality:
    """Test configuration reload functionality."""

    def test_reload_picks_up_config_changes(self, temp_config):
        """Verify reload() picks up configuration changes."""
        # Initial config
        config = {"features": {"test_feature": False}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        flags = FeatureFlags(config_path=temp_config)
        assert flags.is_enabled("test_feature") is False

        # Update config file
        config["features"]["test_feature"] = True
        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        # Reload
        flags.reload()

        # Should pick up new value
        assert flags.is_enabled("test_feature") is True

    def test_reload_picks_up_new_env_overrides(self, temp_config):
        """Verify reload() picks up new environment overrides."""
        config = {"features": {"test_feature": False}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        flags = FeatureFlags(config_path=temp_config)
        assert flags.is_enabled("test_feature") is False

        # Add environment override
        os.environ["FEATURE_FLAG_TEST_FEATURE"] = "true"

        # Reload
        flags.reload()

        # Should pick up environment override
        assert flags.is_enabled("test_feature") is True

        # Cleanup
        del os.environ["FEATURE_FLAG_TEST_FEATURE"]


class TestGetAllFlags:
    """Test get_all() method."""

    def test_get_all_returns_dict(self):
        """Verify get_all() returns dictionary."""
        flags = FeatureFlags()

        all_flags = flags.get_all()

        assert isinstance(all_flags, dict)
        assert len(all_flags) > 0

    def test_get_all_returns_copy(self):
        """Verify get_all() returns a copy (not modifiable)."""
        flags = FeatureFlags()

        all_flags = flags.get_all()

        # Modify the returned dict
        all_flags["new_flag"] = True

        # Should not affect original flags
        assert "new_flag" not in flags.get_all()

    def test_get_all_includes_defaults(self, temp_config):
        """Verify get_all() includes default flags."""
        # Empty config
        config = {"features": {}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        flags = FeatureFlags(config_path=temp_config)
        all_flags = flags.get_all()

        # Should be empty (no defaults in empty config scenario)
        # But when config is missing, defaults are used
        Path(temp_config).unlink()
        flags2 = FeatureFlags(config_path=temp_config)
        all_flags2 = flags2.get_all()

        # Should have default flags
        assert "enable_parallel_processing" in all_flags2
        assert "enable_semantic_tm" in all_flags2


class TestRealWorldScenarios:
    """Test real-world usage scenarios."""

    def test_ast_translation_flag(self):
        """Verify AST translation flag works as expected."""
        flags = get_feature_flags()

        # Should have a value (True or False, both valid)
        ast_enabled = flags.is_enabled("use_ast_translation", default=False)
        assert isinstance(ast_enabled, bool)

    def test_multiple_flags_check(self):
        """Verify checking multiple flags in sequence."""
        flags = get_feature_flags()

        # Check multiple flags
        parallel = flags.is_enabled("enable_parallel_processing")
        semantic_tm = flags.is_enabled("enable_semantic_tm")
        benchmarking = flags.is_enabled("enable_model_benchmarking")

        assert isinstance(parallel, bool)
        assert isinstance(semantic_tm, bool)
        assert isinstance(benchmarking, bool)

    def test_gradual_rollout_scenario(self, temp_config):
        """Simulate gradual rollout scenario."""
        # Start with feature disabled
        config = {"features": {"new_feature": False}}

        with open(temp_config, "w") as f:
            yaml.safe_dump(config, f)

        flags = FeatureFlags(config_path=temp_config)
        assert flags.is_enabled("new_feature") is False

        # Enable for canary deployment via env var
        with patch.dict(os.environ, {"FEATURE_FLAG_NEW_FEATURE": "true"}):
            flags.reload()
            assert flags.is_enabled("new_feature") is True

        # Rollback by removing env var
        flags.reload()
        assert flags.is_enabled("new_feature") is False


class TestBackwardsCompatibility:
    """Test backwards compatibility with existing feature flag tests."""

    def test_compatible_with_test_feature_flag_defaults(self):
        """Verify compatibility with existing test_feature_flag_defaults.py."""
        # Load from real config
        flags = get_feature_flags()

        # Should have these flags from config/global.yaml
        assert "enable_parallel_processing" in flags.get_all()
        assert "enable_semantic_tm" in flags.get_all()
        assert "enable_model_benchmarking" in flags.get_all()

        # enable_model_benchmarking should default to false (production safety)
        assert flags.is_enabled("enable_model_benchmarking") is False

    def test_compatible_with_test_feature_flag_toggle(self):
        """Verify compatibility with existing test_feature_flag_toggle.py."""
        flags = get_feature_flags()

        # Should be able to check all expected flags
        expected_flags = [
            "enable_parallel_processing",
            "enable_semantic_tm",
            "enable_model_benchmarking",
            "enable_auto_model_selection",
            "enable_quality_scoring",
        ]

        for flag in expected_flags:
            # Should not raise exception
            value = flags.is_enabled(flag)
            assert isinstance(value, bool)
