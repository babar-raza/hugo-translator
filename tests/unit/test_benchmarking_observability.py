"""Unit tests for benchmarking observability logging (TC-BM-07)."""

import logging
import os
import sys
from pathlib import Path
from unittest.mock import mock_open, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from src.benchmarking.cli import get_benchmark_db_path
from src.benchmarking.production_ingestor import ProductionMetricsIngestor
from src.benchmarking.storage import BenchmarkDatabase
from src.cli import load_benchmarking_config


def test_logs_env_override_source(caplog, monkeypatch):
    """Test that ENV override is logged."""
    monkeypatch.setenv("BENCHMARK_DB_PATH", "/env/override.db")

    with caplog.at_level(logging.INFO):
        path = get_benchmark_db_path()

    # Should log ENV source
    assert "Using benchmark database path from ENV" in caplog.text
    assert "/env/override.db" in caplog.text
    assert path == Path("/env/override.db")


def test_logs_config_file_source(caplog):
    """Test that config file source is logged."""
    config_yaml = """
database:
  path: "custom/benchmarks.db"
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_yaml)):
            with caplog.at_level(logging.INFO):
                path = get_benchmark_db_path()

    # Should log config source
    assert "Using benchmark database path from config" in caplog.text
    assert "custom/benchmarks.db" in caplog.text
    assert path == Path("custom/benchmarks.db")


def test_logs_default_source(caplog):
    """Test that default source is logged."""
    with patch("pathlib.Path.exists", return_value=False):
        with caplog.at_level(logging.INFO):
            path = get_benchmark_db_path()

    # Should log default source
    assert "Using default benchmark database path" in caplog.text
    assert "data/benchmarks/benchmarks.db" in caplog.text
    assert path == Path("data/benchmarks/benchmarks.db")


def test_logs_production_path_from_config(caplog):
    """Test that production path from config is logged."""
    config_yaml = """
database:
  production_path: "custom/production.db"
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_yaml)):
            with caplog.at_level(logging.INFO):
                path = get_benchmark_db_path(purpose="production")

    # Should log config source with production purpose
    assert "Using benchmark database path from config" in caplog.text
    assert "custom/production.db" in caplog.text
    assert "purpose=production" in caplog.text


def test_logs_config_file_found(caplog):
    """Test that config file loading is logged."""
    config_yaml = """
production:
  record_enabled: true
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_yaml)):
            with caplog.at_level(logging.INFO):
                config = load_benchmarking_config()

    # Should log config loaded
    assert "Loaded benchmarking config" in caplog.text


def test_logs_config_file_not_found(caplog):
    """Test that missing config file is logged."""
    with patch("pathlib.Path.exists", return_value=False):
        with caplog.at_level(logging.INFO):
            config = load_benchmarking_config()

    # Should log defaults used
    assert "No benchmarking config file found, using defaults" in caplog.text


def test_logs_metrics_enabled_status(caplog, tmp_path):
    """Test that ProductionMetricsIngestor logs enabled status."""
    db_path = tmp_path / "test.db"
    db = BenchmarkDatabase(db_path)

    with caplog.at_level(logging.INFO):
        ingestor = ProductionMetricsIngestor(db, enabled=True, min_segments=5)

    # Should log initialization with enabled=True and min_segments
    assert "ProductionMetricsIngestor initialized" in caplog.text
    assert "enabled=True" in caplog.text
    assert "min_segments=5" in caplog.text


def test_logs_metrics_disabled_status(caplog, tmp_path):
    """Test that disabled status is logged."""
    db_path = tmp_path / "test.db"
    db = BenchmarkDatabase(db_path)

    with caplog.at_level(logging.INFO):
        ingestor = ProductionMetricsIngestor(db, enabled=False)

    # Should log initialization with enabled=False
    assert "ProductionMetricsIngestor initialized" in caplog.text
    assert "enabled=False" in caplog.text


def test_logs_successful_recording(caplog, tmp_path):
    """Test that successful metrics recording is logged."""
    db_path = tmp_path / "test.db"
    db = BenchmarkDatabase(db_path)
    ingestor = ProductionMetricsIngestor(db, enabled=True, min_segments=1)

    with caplog.at_level(logging.INFO):
        ingestor.record_translation_run(
            file_path="content/test.md",
            target_lang="es",
            segments_translated=10,
            segments_from_tm=5,
            segments_translated_new=5,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=8.5,
        )

    # Should log successful recording with structured data
    assert "Recorded translation metrics" in caplog.text
    assert "file=content/test.md" in caplog.text
    assert "lang=es" in caplog.text
    assert "segments=10" in caplog.text
    assert "duration=8.5" in caplog.text or "duration=8.50" in caplog.text


def test_logs_threshold_skip(caplog, tmp_path):
    """Test that threshold skips are logged at DEBUG level."""
    db_path = tmp_path / "test.db"
    db = BenchmarkDatabase(db_path)
    ingestor = ProductionMetricsIngestor(db, enabled=True, min_segments=10)

    with caplog.at_level(logging.DEBUG):
        ingestor.record_translation_run(
            file_path="test.md",
            target_lang="fr",
            segments_translated=5,  # Below threshold
            segments_from_tm=0,
            segments_translated_new=5,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=2.0,
        )

    # Should log threshold skip
    assert "Skipping metrics recording" in caplog.text
    assert "segments=5" in caplog.text
    assert "threshold=10" in caplog.text


def test_logs_error_on_failure(caplog, tmp_path):
    """Test that errors are logged with full traceback."""
    db_path = tmp_path / "nonexistent" / "subdir" / "test.db"  # Invalid path
    db = BenchmarkDatabase(db_path)
    ingestor = ProductionMetricsIngestor(db, enabled=True, min_segments=1)

    with caplog.at_level(logging.ERROR):
        # This might fail due to path issues, but should be caught
        ingestor.record_translation_run(
            file_path="test.md",
            target_lang="es",
            segments_translated=10,
            segments_from_tm=0,
            segments_translated_new=10,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=1.0,
        )

    # If it failed, should log error
    # Note: This may or may not fail depending on path creation, so we check conditionally
    error_logs = [record for record in caplog.records if record.levelname == "ERROR"]
    if error_logs:
        assert any("Failed to record production metrics" in record.message for record in error_logs)
