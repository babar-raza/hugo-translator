"""Unit tests for benchmarking configuration (TC-BM-02)."""

import os
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest
import yaml

from src.benchmarking.cli import get_benchmark_db_path


def test_default_path_when_no_config():
    """Test default path returned when config file doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        path = get_benchmark_db_path()
        assert path == Path("data/benchmarks/benchmarks.db")


def test_default_production_path_when_no_config():
    """Test default production path when config doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        path = get_benchmark_db_path(purpose="production")
        assert path == Path("data/benchmarks/production.db")


def test_config_path_for_benchmark():
    """Test path from config for benchmark purpose."""
    config_content = """
database:
  path: "custom/benchmark.db"
  production_path: "custom/production.db"
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_content)):
            path = get_benchmark_db_path()
            assert path == Path("custom/benchmark.db")


def test_config_path_for_production():
    """Test path from config for production purpose."""
    config_content = """
database:
  path: "custom/benchmark.db"
  production_path: "custom/production.db"
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_content)):
            path = get_benchmark_db_path(purpose="production")
            assert path == Path("custom/production.db")


def test_env_override_takes_precedence():
    """Test environment variable overrides config and defaults."""
    config_content = """
database:
  path: "config/benchmark.db"
"""
    with patch.dict(os.environ, {"BENCHMARK_DB_PATH": "/env/override.db"}):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_content)):
                path = get_benchmark_db_path()
                assert path == Path("/env/override.db")


def test_env_override_for_production():
    """Test env var overrides production path too."""
    with patch.dict(os.environ, {"BENCHMARK_DB_PATH": "/env/prod.db"}):
        path = get_benchmark_db_path(purpose="production")
        assert path == Path("/env/prod.db")


def test_precedence_order():
    """Test precedence: ENV > config > default."""
    config_content = """
database:
  path: "config/path.db"
"""

    # With ENV set: ENV wins
    with patch.dict(os.environ, {"BENCHMARK_DB_PATH": "/env/path.db"}):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_content)):
                path = get_benchmark_db_path()
                assert path == Path("/env/path.db")

    # Without ENV, config exists: config wins
    with patch.dict(os.environ, {}, clear=True):
        with patch("pathlib.Path.exists", return_value=True):
            with patch("builtins.open", mock_open(read_data=config_content)):
                path = get_benchmark_db_path()
                assert path == Path("config/path.db")

    # Without ENV, no config: default wins
    with patch.dict(os.environ, {}, clear=True):
        with patch("pathlib.Path.exists", return_value=False):
            path = get_benchmark_db_path()
            assert path == Path("data/benchmarks/benchmarks.db")


def test_config_missing_database_section():
    """Test fallback to defaults when database section missing in config."""
    config_content = """
production:
  record_enabled: false
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_content)):
            path = get_benchmark_db_path()
            assert path == Path("data/benchmarks/benchmarks.db")


def test_config_with_empty_database_section():
    """Test fallback when database section exists but is empty."""
    config_content = """
database:
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_content)):
            path = get_benchmark_db_path()
            assert path == Path("data/benchmarks/benchmarks.db")


def test_invalid_yaml_fallback_to_default(caplog):
    """Test graceful fallback when YAML is invalid."""
    invalid_yaml = "{ invalid yaml content [ "

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            path = get_benchmark_db_path()
            assert path == Path("data/benchmarks/benchmarks.db")
            # Should log warning
            assert "Failed to load benchmarking config" in caplog.text
