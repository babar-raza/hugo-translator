"""Unit tests for benchmarking config validation (TC-BM-06)."""

import logging

import pytest

# Import the validation function
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from src.cli import validate_benchmarking_config


def test_valid_config_passes_through():
    """Test that valid config is returned unchanged."""
    config = {
        "production": {
            "record_enabled": True,
            "min_segments_to_record": 5,
        },
        "database": {
            "path": "custom/benchmarks.db",
            "production_path": "custom/production.db",
        },
    }

    validated = validate_benchmarking_config(config)

    assert validated["production"]["record_enabled"] is True
    assert validated["production"]["min_segments_to_record"] == 5
    assert validated["database"]["path"] == "custom/benchmarks.db"
    assert validated["database"]["production_path"] == "custom/production.db"


def test_invalid_record_enabled_type_uses_default(caplog):
    """Test invalid type for record_enabled uses default False."""
    config = {
        "production": {
            "record_enabled": "yes",  # Should be bool
        }
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # Should use default
    assert validated["production"]["record_enabled"] is False
    # Should log warning
    assert "Invalid type for production.record_enabled" in caplog.text


def test_invalid_min_segments_type_uses_default(caplog):
    """Test invalid type for min_segments_to_record uses default."""
    config = {
        "production": {
            "min_segments_to_record": "10",  # Should be int
        }
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # Should use default
    assert validated["production"]["min_segments_to_record"] == 1
    # Should log warning
    assert "Invalid type for production.min_segments_to_record" in caplog.text


def test_negative_min_segments_rejected(caplog):
    """Test negative min_segments_to_record is rejected."""
    config = {
        "production": {
            "min_segments_to_record": -5,
        }
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # Should use default
    assert validated["production"]["min_segments_to_record"] == 1
    # Should log warning
    assert "Invalid value for production.min_segments_to_record" in caplog.text


def test_zero_min_segments_rejected(caplog):
    """Test zero min_segments_to_record is rejected."""
    config = {
        "production": {
            "min_segments_to_record": 0,
        }
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # Should use default (minimum 1)
    assert validated["production"]["min_segments_to_record"] == 1
    # Should log warning
    assert "Invalid value for production.min_segments_to_record" in caplog.text


def test_missing_min_segments_gets_default():
    """Test missing min_segments_to_record gets default value."""
    config = {
        "production": {
            "record_enabled": True,
            # min_segments_to_record missing
        }
    }

    validated = validate_benchmarking_config(config)

    # Should add default
    assert validated["production"]["min_segments_to_record"] == 1


def test_invalid_database_path_type_uses_default(caplog):
    """Test invalid type for database.path uses default."""
    config = {
        "database": {
            "path": 12345,  # Should be str
        }
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # Should use default
    assert validated["database"]["path"] == "data/benchmarks/benchmarks.db"
    # Should log warning
    assert "Invalid type for database.path" in caplog.text


def test_invalid_production_path_type_uses_default(caplog):
    """Test invalid type for database.production_path uses default."""
    config = {
        "database": {
            "production_path": ["not", "a", "string"],  # Should be str
        }
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # Should use default
    assert validated["database"]["production_path"] == "data/benchmarks/production.db"
    # Should log warning
    assert "Invalid type for database.production_path" in caplog.text


def test_empty_config_returns_with_defaults():
    """Test empty config gets populated with defaults."""
    config = {}

    validated = validate_benchmarking_config(config)

    # Should still work, just no validation needed
    assert validated == {}


def test_multiple_invalid_values_all_corrected(caplog):
    """Test that multiple invalid values are all corrected."""
    config = {
        "production": {
            "record_enabled": "true",  # Invalid type
            "min_segments_to_record": -10,  # Invalid value
        },
        "database": {
            "path": 123,  # Invalid type
            "production_path": None,  # Invalid type
        },
    }

    with caplog.at_level(logging.WARNING):
        validated = validate_benchmarking_config(config)

    # All should be corrected
    assert validated["production"]["record_enabled"] is False
    assert validated["production"]["min_segments_to_record"] == 1
    assert validated["database"]["path"] == "data/benchmarks/benchmarks.db"
    assert validated["database"]["production_path"] == "data/benchmarks/production.db"

    # Should have 4 warnings
    warnings = [record for record in caplog.records if record.levelname == "WARNING"]
    assert len(warnings) == 4
