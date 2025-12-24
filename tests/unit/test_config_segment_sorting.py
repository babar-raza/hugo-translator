"""
Unit tests for config-based segment sorting (SR-03 completion, COMP-01).

Tests verify:
- Config loads sort_segments_by_length from YAML
- Default value is False (backward compatibility)
- Config value is accessible through BodyRules
- CLI flag overrides config value (tested in integration)
"""
import pytest
import tempfile
import yaml
from pathlib import Path
from unittest.mock import Mock, MagicMock
import sys

# Add src to path for imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from src.utils.models import BodyRules


def test_config_loads_sort_true():
    """Test that config correctly loads sort_segments_by_length: true."""
    config_data = {
        'sort_segments_by_length': True,
    }

    # Create BodyRules instance from config data
    body_rules = BodyRules(**config_data)

    assert body_rules.sort_segments_by_length is True


def test_config_loads_sort_false():
    """Test that config correctly loads sort_segments_by_length: false."""
    config_data = {
        'sort_segments_by_length': False,
    }

    body_rules = BodyRules(**config_data)

    assert body_rules.sort_segments_by_length is False


def test_config_default_is_false():
    """Test that default value is False (backward compatibility, document order)."""
    # Create BodyRules with no config (all defaults)
    body_rules = BodyRules()

    assert body_rules.sort_segments_by_length is False
    assert hasattr(body_rules, 'sort_segments_by_length')


def test_config_yaml_parsing():
    """Test that YAML parsing works correctly with sort_segments_by_length."""
    yaml_content = """
sort_segments_by_length: true
translate_markdown: true
use_ast_body_reconstruction: false
"""

    config_data = yaml.safe_load(yaml_content)
    body_rules = BodyRules(**config_data)

    assert body_rules.sort_segments_by_length is True
    assert body_rules.translate_markdown is True
    assert body_rules.use_ast_body_reconstruction is False


def test_config_field_description():
    """Test that sort_segments_by_length field has proper description."""
    # Verify field exists and has expected metadata
    assert hasattr(BodyRules, 'sort_segments_by_length')

    # Get field info (pydantic v2 style)
    if hasattr(BodyRules, 'model_fields'):
        # Pydantic v2
        fields = BodyRules.model_fields
        assert 'sort_segments_by_length' in fields
        field_info = fields['sort_segments_by_length']
        assert field_info.default is False
    elif hasattr(BodyRules, '__fields__'):
        # Pydantic v1
        fields = BodyRules.__fields__
        assert 'sort_segments_by_length' in fields
        field_info = fields['sort_segments_by_length']
        assert field_info.default is False


def test_config_with_temp_yaml_file():
    """Test loading sort_segments_by_length from actual YAML file."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.yaml', delete=False) as f:
        yaml_content = {
            'body_rules': {
                'sort_segments_by_length': True,
                'translate_markdown': True,
            }
        }
        yaml.dump(yaml_content, f)
        temp_path = f.name

    try:
        # Load YAML
        with open(temp_path, 'r') as f:
            config = yaml.safe_load(f)

        # Extract body_rules
        body_rules_data = config.get('body_rules', {})
        body_rules = BodyRules(**body_rules_data)

        assert body_rules.sort_segments_by_length is True
        assert body_rules.translate_markdown is True
    finally:
        Path(temp_path).unlink()


def test_config_missing_key_uses_default():
    """Test that missing sort_segments_by_length key uses default (False)."""
    config_data = {
        'translate_markdown': True,
        # sort_segments_by_length not specified
    }

    body_rules = BodyRules(**config_data)

    # Should use default value (False)
    assert body_rules.sort_segments_by_length is False
