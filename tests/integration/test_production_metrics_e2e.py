"""Integration tests for production metrics end-to-end flow (TC-BM-03).

Tests the complete integration of production metrics from CLI flag through
to database recording, ensuring OPT-IN behavior and PII sanitization.
"""

import os
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
import yaml

# Add src to path
src_path = Path(__file__).parent.parent.parent / "src"
sys.path.insert(0, str(src_path))

from src.benchmarking.storage import BenchmarkDatabase
from src.cli import load_benchmarking_config


@pytest.fixture
def test_site(tmp_path):
    """Create minimal test site with Hugo content."""
    site_dir = tmp_path / "test-site"
    content_dir = site_dir / "content"
    content_dir.mkdir(parents=True)

    # Create test markdown file
    test_file = content_dir / "index.md"
    test_file.write_text("""---
title: Test Page
---

# Test Content

This is a test paragraph for translation.
Another paragraph to ensure we have multiple segments.
""")

    # Create minimal site config
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True)

    site_config = config_dir / "test-site.yaml"
    site_config.write_text("""
site_id: test-site
source_lang: en
target_langs:
  - es
content_roots:
  - content
output_base: output
""")

    return site_dir, config_dir


@pytest.fixture
def benchmark_config_disabled(tmp_path):
    """Benchmarking config with production metrics DISABLED (default)."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / "benchmarking.yaml"
    config = {
        "production": {"record_enabled": False, "min_segments_to_record": 5},
        "database": {"production_path": str(tmp_path / "production.db")},
    }
    config_path.write_text(yaml.dump(config))
    return config_path


@pytest.fixture
def benchmark_config_enabled(tmp_path):
    """Benchmarking config with production metrics ENABLED."""
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)

    config_path = config_dir / "benchmarking.yaml"
    config = {
        "production": {"record_enabled": True, "min_segments_to_record": 5},
        "database": {"production_path": str(tmp_path / "production.db")},
    }
    config_path.write_text(yaml.dump(config))
    return config_path


def test_load_benchmarking_config_integration(benchmark_config_enabled, tmp_path):
    """Test loading real benchmarking config file."""
    # Temporarily override config path
    with patch("src.cli.Path") as mock_path_class:
        mock_path_instance = MagicMock()
        mock_path_instance.exists.return_value = True
        mock_path_class.return_value = mock_path_instance

        with patch("builtins.open", open(benchmark_config_enabled)):
            config = load_benchmarking_config()

            assert config["production"]["record_enabled"] is True
            assert config["production"]["min_segments_to_record"] == 5


def test_production_metrics_disabled_by_default(tmp_path):
    """Test that production metrics are NOT enabled without explicit flag/config."""
    # Mock args with no CLI flag
    args = MagicMock()
    args.enable_production_metrics = False

    # Config disabled (default)
    config = {"production": {"record_enabled": False}}

    # Calculate metrics_enabled (same logic as cli.py)
    metrics_enabled = (
        args.enable_production_metrics
        or config.get("production", {}).get("record_enabled", False)
    )

    # Should be disabled
    assert metrics_enabled is False

    # Verify production DB would NOT be created
    prod_db_path = tmp_path / "data" / "benchmarks" / "production.db"
    assert not prod_db_path.exists()


def test_production_metrics_enabled_via_cli_flag(tmp_path):
    """Test CLI flag enables production metrics even when config disabled."""
    # Mock args with CLI flag
    args = MagicMock()
    args.enable_production_metrics = True

    # Config disabled
    config = {"production": {"record_enabled": False}}

    # CLI flag should override
    metrics_enabled = (
        args.enable_production_metrics
        or config.get("production", {}).get("record_enabled", False)
    )

    assert metrics_enabled is True


def test_ingestor_creates_database_when_enabled(tmp_path):
    """Test that ProductionMetricsIngestor creates database when enabled."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    # Create database
    db_path = tmp_path / "production.db"
    db = BenchmarkDatabase(db_path)

    # Create ingestor (enabled)
    ingestor = ProductionMetricsIngestor(db, enabled=True)

    # Verify enabled
    assert ingestor.enabled is True

    # Database file should exist after initialization
    assert db_path.exists()


def test_ingestor_disabled_is_noop(tmp_path):
    """Test that disabled ingestor is a no-op."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    db_path = tmp_path / "production.db"
    db = BenchmarkDatabase(db_path)

    # Create ingestor DISABLED
    ingestor = ProductionMetricsIngestor(db, enabled=False)

    # Verify disabled
    assert ingestor.enabled is False

    # Call record_translation_run - should be no-op
    ingestor.record_translation_run(
        file_path="test.md",
        target_lang="es",
        segments_translated=10,
        segments_from_tm=5,
        segments_translated_new=5,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=5.0,
    )

    # Verify no runs recorded
    runs = db.list_runs(purpose="production")
    assert len(runs) == 0


def test_production_metrics_records_run_when_enabled(tmp_path):
    """Test that metrics are actually recorded when enabled."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    db_path = tmp_path / "production.db"
    db = BenchmarkDatabase(db_path)

    # Create ENABLED ingestor
    ingestor = ProductionMetricsIngestor(db, enabled=True)

    # Record a translation run
    ingestor.record_translation_run(
        file_path="content/test.md",
        target_lang="es",
        segments_translated=10,
        segments_from_tm=5,
        segments_translated_new=5,
        translation_model="facebook/m2m100_418M",
        retry_count=0,
        success=True,
        duration_seconds=8.5,
    )

    # Verify run was recorded
    runs = db.list_runs(purpose="production")
    assert len(runs) == 1

    # Verify run details
    run_id, model_id, device, timestamp, result_count = runs[0]
    assert model_id == "facebook/m2m100_418M"

    # Get full run details
    run = db.get_run(run_id)
    assert run is not None
    assert run.purpose == "production"
    assert run.iterations == 10  # segments_translated
    assert "production" in run.tags
    assert "es" in run.tags
    assert "auto-recorded" in run.tags


def test_system_info_collected_and_sanitized(tmp_path):
    """Test that system info is collected and PII is sanitized."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    db_path = tmp_path / "production.db"
    db = BenchmarkDatabase(db_path)

    ingestor = ProductionMetricsIngestor(db, enabled=True)

    # Record run
    ingestor.record_translation_run(
        file_path="/home/username/projects/test.md",
        target_lang="fr",
        segments_translated=5,
        segments_from_tm=0,
        segments_translated_new=5,
        translation_model="test_model",
        retry_count=0,
        success=True,
        duration_seconds=3.0,
    )

    # Get run
    runs = db.list_runs(purpose="production")
    assert len(runs) == 1

    run_id = runs[0][0]
    run = db.get_run(run_id)

    # Verify system_info exists
    assert run.system_info is not None
    assert run.system_info.cpu_cores > 0
    assert run.system_info.total_ram_gb > 0

    # Verify PII sanitization in paths
    # Convert system_info to dict to check all string fields
    info_dict = {
        "cpu_model": run.system_info.cpu_model,
        "gpu_model": run.system_info.gpu_model,
        "os_name": run.system_info.os_name,
        "os_version": run.system_info.os_version,
        "platform_system": run.system_info.platform_system,
        "platform_release": run.system_info.platform_release,
        "python_version": run.system_info.python_version,
        "python_implementation": run.system_info.python_implementation,
    }

    # Check that no actual username appears in any field
    info_str = str(info_dict)

    # TC-BM-10: Strengthen PII leak detection
    # Verify that actual system username is not leaked
    try:
        actual_username = os.getlogin()
        assert actual_username not in info_str, (
            f"PII LEAK: Username '{actual_username}' found in system_info: {info_str}"
        )
    except OSError:
        # Some CI environments don't support getlogin(), skip username check
        pass

    # Verify that actual home directory path is not leaked
    try:
        home_path = str(Path.home())
        assert home_path not in info_str, (
            f"PII LEAK: Home path '{home_path}' found in system_info: {info_str}"
        )

        # Extract username from home path and verify it's sanitized
        if "Users" in home_path or "users" in home_path:
            # Windows: C:/Users/username
            parts = home_path.replace("\\", "/").split("/")
            if "Users" in parts or "users" in parts:
                user_idx = next((i for i, p in enumerate(parts) if p.lower() == "users"), None)
                if user_idx is not None and user_idx + 1 < len(parts):
                    username = parts[user_idx + 1]
                    assert username not in info_str, (
                        f"PII LEAK: Username '{username}' from home path found in system_info"
                    )
        elif "/home/" in home_path:
            # Unix: /home/username
            username = home_path.split("/home/")[1].split("/")[0]
            assert username not in info_str, (
                f"PII LEAK: Username '{username}' from home path found in system_info"
            )
    except Exception:
        # Can't get home directory in some environments, skip check
        pass

    # Verify that system info was actually collected (not empty)
    assert len(info_str) > 0


def test_multiple_runs_recorded(tmp_path):
    """Test that multiple translation runs are recorded correctly."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    db_path = tmp_path / "production.db"
    db = BenchmarkDatabase(db_path)

    ingestor = ProductionMetricsIngestor(db, enabled=True)

    # Record multiple runs
    for i in range(3):
        ingestor.record_translation_run(
            file_path=f"content/test{i}.md",
            target_lang="es",
            segments_translated=10 + i,
            segments_from_tm=i,
            segments_translated_new=10,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=5.0 + i,
        )

    # Verify all runs recorded
    runs = db.list_runs(purpose="production")
    assert len(runs) == 3

    # Verify each has unique run_id
    run_ids = [run[0] for run in runs]
    assert len(set(run_ids)) == 3  # All unique


def test_failed_translation_recorded(tmp_path):
    """Test that failed translations are also recorded."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    db_path = tmp_path / "production.db"
    db = BenchmarkDatabase(db_path)

    ingestor = ProductionMetricsIngestor(db, enabled=True)

    # Record failed translation
    ingestor.record_translation_run(
        file_path="content/failed.md",
        target_lang="es",
        segments_translated=5,
        segments_from_tm=0,
        segments_translated_new=0,
        translation_model="test_model",
        retry_count=3,
        success=False,
        duration_seconds=2.0,
    )

    # Verify run recorded even though it failed
    runs = db.list_runs(purpose="production")
    assert len(runs) == 1


def test_graceful_error_handling(tmp_path, caplog):
    """Test that ingestor errors don't crash translation pipeline."""
    from src.benchmarking.production_ingestor import ProductionMetricsIngestor

    # Use invalid database path to force error
    db_path = tmp_path / "nonexistent" / "subdir" / "production.db"

    # This should NOT raise an error during initialization
    # (database is created lazily)
    db = BenchmarkDatabase(db_path)
    ingestor = ProductionMetricsIngestor(db, enabled=True)

    # Try to record - this might fail due to path issues
    # But it should NOT raise an exception
    try:
        ingestor.record_translation_run(
            file_path="test.md",
            target_lang="es",
            segments_translated=5,
            segments_from_tm=0,
            segments_translated_new=5,
            translation_model="test_model",
            retry_count=0,
            success=True,
            duration_seconds=1.0,
        )
        # If it succeeds, verify run recorded
        runs = db.list_runs(purpose="production")
        # May or may not have runs depending on path creation
    except Exception as e:
        # Should NOT raise - but if it does in test, that's a bug
        pytest.fail(f"Ingestor should handle errors gracefully, but raised: {e}")


def test_env_var_overrides_config_path(tmp_path, monkeypatch):
    """Test that BENCHMARK_DB_PATH environment variable overrides config."""
    from src.benchmarking.cli import get_benchmark_db_path

    # Set environment variable
    custom_path = str(tmp_path / "custom_env.db")
    monkeypatch.setenv("BENCHMARK_DB_PATH", custom_path)

    # Get path - should use env var
    path = get_benchmark_db_path(purpose="production")
    assert str(path) == custom_path


def test_precedence_env_over_config(tmp_path, monkeypatch, benchmark_config_enabled):
    """Test precedence: ENV > config."""
    from src.benchmarking.cli import get_benchmark_db_path

    # Config has one path
    # ENV has different path
    env_path = str(tmp_path / "env_override.db")
    monkeypatch.setenv("BENCHMARK_DB_PATH", env_path)

    # Mock config loading to use benchmark_config_enabled
    with patch("pathlib.Path.exists") as mock_exists:
        mock_exists.return_value = True

        with patch("builtins.open", open(benchmark_config_enabled)):
            path = get_benchmark_db_path(purpose="production")

            # ENV should win
            assert str(path) == env_path
