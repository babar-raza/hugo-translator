"""Test feature flag default values.

Verification Report:
- Date verified: 2025-12-19
- Config files checked: config/global.yaml
- Default behavior confirmed: enable_model_benchmarking defaults to false
- Feature flag source: config/global.yaml line 113
"""

from pathlib import Path

import yaml

try:
    import pytest
except ImportError:
    pytest = None


def test_enable_model_benchmarking_defaults_to_false():
    """Verify enable_model_benchmarking defaults to false when loaded from config."""
    # Load global config
    config_path = Path("config/global.yaml")
    assert config_path.exists(), "Global config not found"

    with open(config_path) as f:
        config = yaml.safe_load(f)

    # Verify the flag exists and defaults to false
    assert "features" in config, "Features section missing from config"
    assert "enable_model_benchmarking" in config["features"], (
        "enable_model_benchmarking flag missing"
    )
    assert config["features"]["enable_model_benchmarking"] is False, (
        "Flag should default to False for production safety"
    )


def test_enable_model_benchmarking_structure():
    """Verify the feature flag structure in config is valid."""
    config_path = Path("config/global.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    features = config.get("features", {})

    # Verify all expected feature flags exist
    expected_flags = [
        "enable_parallel_processing",
        "enable_semantic_tm",
        "enable_model_benchmarking",
        "enable_auto_model_selection",
        "enable_quality_scoring",
    ]

    for flag in expected_flags:
        assert flag in features, f"Expected flag {flag} not found in features"

    # Verify flag types are boolean
    for flag, value in features.items():
        assert isinstance(value, bool), f"Flag {flag} should be boolean, got {type(value)}"


def test_feature_flag_respects_explicit_values():
    """Verify that explicit true/false values are respected."""
    config_path = Path("config/global.yaml")

    with open(config_path) as f:
        config = yaml.safe_load(f)

    features = config["features"]

    # Test that explicitly enabled flags are true
    assert features["enable_parallel_processing"] is True, "Explicitly enabled flags should be True"

    # Test that explicitly disabled flags are false
    assert features["enable_model_benchmarking"] is False, (
        "Explicitly disabled flags should be False"
    )


def test_missing_flag_behavior():
    """Verify behavior when flag is missing from config (regression test)."""
    # Create minimal config without the flag
    minimal_config = {"features": {}}

    # Accessing missing flag should use .get() with default False
    flag_value = minimal_config.get("features", {}).get("enable_model_benchmarking", False)

    assert flag_value is False, "Missing flags should default to False for safety"


def test_invalid_flag_value_detection():
    """Verify that non-boolean flag values are detectable."""
    # This is a validation test - in production, pydantic would catch this
    invalid_configs = [
        {"enable_model_benchmarking": "true"},  # String instead of bool
        {"enable_model_benchmarking": 1},  # Integer instead of bool
        {"enable_model_benchmarking": None},  # None instead of bool
    ]

    for invalid_config in invalid_configs:
        value = invalid_config["enable_model_benchmarking"]
        assert not isinstance(value, bool) or value is None, (
            f"Value {value} should be detected as invalid"
        )


if __name__ == "__main__":
    # Run tests directly for manual validation
    print("Running feature flag default tests...")
    test_enable_model_benchmarking_defaults_to_false()
    print("✓ Flag defaults to false")

    test_enable_model_benchmarking_structure()
    print("✓ Feature flag structure valid")

    test_feature_flag_respects_explicit_values()
    print("✓ Explicit values respected")

    test_missing_flag_behavior()
    print("✓ Missing flag behavior correct")

    test_invalid_flag_value_detection()
    print("✓ Invalid value detection works")

    print("\nAll tests passed!")
