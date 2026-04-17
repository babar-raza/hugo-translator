"""Unit tests for content hash tracking configuration."""

from pathlib import Path

import yaml


def test_global_yaml_valid_syntax():
    """Verify global.yaml has valid syntax."""
    config_file = Path("config/global.yaml")
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "features" in config
    assert "content_hash_tracking" in config


def test_content_hash_feature_flag():
    """Verify feature flag exists and has correct default."""
    config_file = Path("config/global.yaml")
    with open(config_file) as f:
        config = yaml.safe_load(f)

    assert "enable_content_hash_tracking" in config["features"]
    # Initially opt-in (false), later change to true
    assert config["features"]["enable_content_hash_tracking"] is False


def test_content_hash_config_section():
    """Verify content_hash_tracking section has all required fields."""
    config_file = Path("config/global.yaml")
    with open(config_file) as f:
        config = yaml.safe_load(f)

    cht_config = config["content_hash_tracking"]

    assert cht_config["enabled"] is False
    assert cht_config["hash_algorithm"] == "md5"
    assert cht_config["metadata_file"] == ".translation_metadata.json"
    assert cht_config["in_memory_cache_size"] == 1000
    assert cht_config["update_metadata_on_skip"] is True
    assert cht_config["validate_output_integrity"] is False
    assert cht_config["fallback_to_mtime"] is True
    assert cht_config["fast_path_mtime_check"] is True
