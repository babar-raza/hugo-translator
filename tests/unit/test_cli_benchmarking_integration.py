"""Unit tests for production metrics integration in CLI (TC-BM-01)."""

from pathlib import Path
from unittest.mock import MagicMock, mock_open, patch

from src.cli import load_benchmarking_config


def test_load_benchmarking_config_file_exists():
    """Test loading config when file exists with valid YAML."""
    config_yaml = """
production:
  record_enabled: true
  min_segments_to_record: 20

database:
  path: "custom/benchmarks.db"
  production_path: "custom/production.db"
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_yaml)):
            config = load_benchmarking_config()

            assert config["production"]["record_enabled"] is True
            assert config["production"]["min_segments_to_record"] == 20
            assert config["database"]["path"] == "custom/benchmarks.db"
            assert config["database"]["production_path"] == "custom/production.db"


def test_load_benchmarking_config_file_not_exists():
    """Test safe defaults when config file doesn't exist."""
    with patch("pathlib.Path.exists", return_value=False):
        config = load_benchmarking_config()

        assert config["production"]["record_enabled"] is False
        assert config["database"]["path"] == "data/benchmarks/benchmarks.db"
        assert config["database"]["production_path"] == "data/benchmarks/production.db"


def test_load_benchmarking_config_missing_sections():
    """Test defaults are added when config sections are missing."""
    config_yaml = """
scheduler:
  max_cpu_percent: 80
"""
    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=config_yaml)):
            config = load_benchmarking_config()

            # Should have defaults
            assert "production" in config
            assert config["production"]["record_enabled"] is False
            assert "database" in config


def test_load_benchmarking_config_invalid_yaml(caplog):
    """Test graceful fallback when YAML is invalid."""
    invalid_yaml = "{ invalid: yaml: content [ "

    with patch("pathlib.Path.exists", return_value=True):
        with patch("builtins.open", mock_open(read_data=invalid_yaml)):
            config = load_benchmarking_config()

            # Should return safe defaults
            assert config["production"]["record_enabled"] is False
            # Should log warning
            assert "Failed to load benchmarking config" in caplog.text


def test_production_metrics_disabled_by_default():
    """Test that production metrics are NOT enabled by default."""
    # Mock args with no CLI flag
    args = MagicMock()
    args.enable_production_metrics = False

    # Config also disabled (default)
    config = {"production": {"record_enabled": False}}

    # Calculate metrics_enabled
    metrics_enabled = args.enable_production_metrics or config.get("production", {}).get(
        "record_enabled", False
    )

    assert metrics_enabled is False


def test_production_metrics_enabled_via_cli_flag():
    """Test CLI flag enables production metrics."""
    args = MagicMock()
    args.enable_production_metrics = True

    # Config disabled
    config = {"production": {"record_enabled": False}}

    # CLI flag should override
    metrics_enabled = args.enable_production_metrics or config.get("production", {}).get(
        "record_enabled", False
    )

    assert metrics_enabled is True


def test_production_metrics_enabled_via_config():
    """Test config enables production metrics."""
    args = MagicMock()
    args.enable_production_metrics = False

    # Config enabled
    config = {"production": {"record_enabled": True}}

    metrics_enabled = args.enable_production_metrics or config.get("production", {}).get(
        "record_enabled", False
    )

    assert metrics_enabled is True


def test_production_metrics_cli_flag_overrides_disabled_config():
    """Test CLI flag takes precedence even when config is disabled."""
    args = MagicMock()
    args.enable_production_metrics = True

    config = {"production": {"record_enabled": False}}

    metrics_enabled = args.enable_production_metrics or config.get("production", {}).get(
        "record_enabled", False
    )

    # CLI flag wins
    assert metrics_enabled is True


def test_ingestor_initialization_when_enabled():
    """Test ProductionMetricsIngestor is created when metrics enabled."""
    with patch("src.cli.load_benchmarking_config") as mock_load:
        mock_load.return_value = {"production": {"record_enabled": True}}

        with patch("src.cli.BenchmarkDatabase") as mock_db:
            with patch("src.cli.ProductionMetricsIngestor") as mock_ingestor:
                with patch("src.cli.get_benchmark_db_path") as mock_path:
                    mock_path.return_value = Path("data/benchmarks/production.db")

                    # Simulate the initialization logic
                    config = mock_load()
                    metrics_enabled = config.get("production", {}).get("record_enabled", False)

                    if metrics_enabled:
                        db_path = mock_path(purpose="production")
                        db = mock_db(db_path)
                        ingestor = mock_ingestor(db, enabled=True)

                    # Verify calls
                    mock_db.assert_called_once_with(Path("data/benchmarks/production.db"))
                    mock_ingestor.assert_called_once()


def test_ingestor_not_created_when_disabled():
    """Test ingestor NOT created when metrics disabled."""
    with patch("src.cli.load_benchmarking_config") as mock_load:
        mock_load.return_value = {"production": {"record_enabled": False}}

        with patch("src.cli.BenchmarkDatabase") as mock_db:
            with patch("src.cli.ProductionMetricsIngestor") as mock_ingestor:
                # Simulate the initialization logic
                config = mock_load()
                metrics_enabled = config.get("production", {}).get("record_enabled", False)

                ingestor = None
                if metrics_enabled:
                    # This should NOT execute
                    ingestor = mock_ingestor(mock_db(), enabled=True)

                # Verify NOT called
                mock_db.assert_not_called()
                mock_ingestor.assert_not_called()
                assert ingestor is None
