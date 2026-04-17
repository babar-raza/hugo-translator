"""
Tests for Benchmark CLI module.

Validates argument parsing, command execution, storage interactions,
and error handling for all CLI commands.
"""
import argparse
import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from src.benchmarking.cli import (
    cmd_aggregate,
    cmd_archive,
    cmd_compare,
    cmd_export,
    cmd_list,
    cmd_migrate,
    cmd_recommend,
    cmd_report,
    cmd_retention,
    cmd_run,
    get_benchmark_db_path,
    main,
)
from src.benchmarking.storage import BenchmarkResult, BenchmarkRun, SystemInfo
from src.model_runtime.recommender import ModelRecommendation


@pytest.fixture
def mock_registry():
    """Mock ModelRegistry."""
    registry = MagicMock()
    registry.models = {
        "opus_en_fr": MagicMock(
            model_id="opus_en_fr",
            backend="opus",
            model_size_mb=100,
            min_ram_gb=0.5,
            optimal_device="cpu",
        )
    }
    return registry


@pytest.fixture
def mock_db():
    """Mock BenchmarkDatabase."""
    db = MagicMock()
    return db


@pytest.fixture
def sample_run():
    """Sample benchmark run for testing."""
    system_info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=8,
        total_ram_gb=16.0,
        os_name="Linux",
        os_version="5.10",
        python_version="3.10.0",
    )

    results = [
        BenchmarkResult(
            sample_id="sample1",
            model_id="opus_en_fr",
            device="cpu",
            batch_size=8,
            duration_seconds=1.5,
            tokens_input=100,
            tokens_output=110,
            throughput_tokens_per_sec=140.0,
        ),
        BenchmarkResult(
            sample_id="sample2",
            model_id="opus_en_fr",
            device="cpu",
            batch_size=8,
            duration_seconds=1.6,
            tokens_input=105,
            tokens_output=115,
            throughput_tokens_per_sec=137.5,
        ),
    ]

    return BenchmarkRun(
        run_id="test123",
        model_id="opus_en_fr",
        device="cpu",
        batch_sizes=[8],
        iterations=1,
        corpus_category="tiny",
        purpose="test",
        tags=["test"],
        system_info=system_info,
        results=results,
        total_duration_seconds=10.0,
    )


class TestCmdRun:
    """Tests for 'run' command."""

    def test_run_success(self, mock_registry, sample_run, tmp_path):
        """Test successful benchmark run."""
        args = argparse.Namespace(
            model="opus_en_fr",
            device="cpu",
            batch_sizes="8",
            iterations=1,
            corpus="tiny",
            purpose="test",
            tags="test",
            save_to_db=str(tmp_path / "test.db"),
            max_samples=None,
            registry="config/model_registry.yaml",
            verbose=False,
        )

        with patch("src.benchmarking.cli.ModelRegistry", return_value=mock_registry):
            with patch("src.benchmarking.cli.BenchmarkRunner") as MockRunner:
                mock_runner = MockRunner.return_value
                mock_runner.run_benchmark.return_value = sample_run

                result = cmd_run(args)

                assert result == 0
                mock_runner.run_benchmark.assert_called_once()

    def test_run_invalid_batch_sizes(self, mock_registry):
        """Test run with invalid batch sizes."""
        args = argparse.Namespace(
            model="opus_en_fr",
            device="cpu",
            batch_sizes="invalid",
            iterations=1,
            corpus="tiny",
            purpose="test",
            tags=None,
            save_to_db=None,
            max_samples=None,
            registry="config/model_registry.yaml",
            verbose=False,
        )

        result = cmd_run(args)
        assert result == 1

    def test_run_missing_registry(self):
        """Test run with missing registry file."""
        args = argparse.Namespace(
            model="opus_en_fr",
            device="cpu",
            batch_sizes="8",
            iterations=1,
            corpus="tiny",
            purpose="test",
            tags=None,
            save_to_db=None,
            max_samples=None,
            registry="nonexistent.yaml",
            verbose=False,
        )

        result = cmd_run(args)
        assert result == 1

    def test_run_benchmark_failure(self, mock_registry, tmp_path):
        """Test run when benchmark execution fails."""
        args = argparse.Namespace(
            model="opus_en_fr",
            device="cpu",
            batch_sizes="8",
            iterations=1,
            corpus="tiny",
            purpose="test",
            tags=None,
            save_to_db=str(tmp_path / "test.db"),
            max_samples=None,
            registry="config/model_registry.yaml",
            verbose=False,
        )

        with patch("src.benchmarking.cli.ModelRegistry", return_value=mock_registry):
            with patch("src.benchmarking.cli.BenchmarkRunner") as MockRunner:
                mock_runner = MockRunner.return_value
                mock_runner.run_benchmark.side_effect = RuntimeError("Benchmark failed")

                result = cmd_run(args)
                assert result == 1


class TestCmdList:
    """Tests for 'list' command."""

    def test_list_success(self, mock_db, tmp_path):
        """Test successful listing of runs."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            model=None,
            device=None,
            limit=10,
            offset=0,
            format="markdown",
            verbose=False,
        )

        mock_db.list_runs.return_value = [
            ("run1", "opus_en_fr", "cpu", "2025-12-19T10:00:00", 10),
            ("run2", "m2m100_418m", "cpu", "2025-12-19T11:00:00", 5),
        ]

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_list(args)

            assert result == 0
            mock_db.list_runs.assert_called_once_with(
                model_id=None,
                device=None,
                limit=10,
                offset=0,
            )

    def test_list_json_format(self, mock_db, tmp_path):
        """Test listing with JSON format."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            model=None,
            device=None,
            limit=5,
            offset=0,
            format="json",
            verbose=False,
        )

        mock_db.list_runs.return_value = [
            ("run1", "opus_en_fr", "cpu", "2025-12-19T10:00:00", 10),
        ]

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_list(args)

            assert result == 0

    def test_list_missing_db(self):
        """Test list when database doesn't exist."""
        args = argparse.Namespace(
            db="nonexistent.db",
            model=None,
            device=None,
            limit=10,
            offset=0,
            format="markdown",
            verbose=False,
        )

        result = cmd_list(args)
        assert result == 1

    def test_list_with_filters(self, mock_db, tmp_path):
        """Test listing with model and device filters."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            model="opus_en_fr",
            device="cpu",
            limit=10,
            offset=0,
            format="markdown",
            verbose=False,
        )

        mock_db.list_runs.return_value = [
            ("run1", "opus_en_fr", "cpu", "2025-12-19T10:00:00", 10),
        ]

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_list(args)

            assert result == 0
            mock_db.list_runs.assert_called_once_with(
                model_id="opus_en_fr",
                device="cpu",
                limit=10,
                offset=0,
            )


class TestCmdReport:
    """Tests for 'report' command."""

    def test_report_success(self, mock_db, sample_run, tmp_path):
        """Test successful report generation."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            run="test123",
            db=str(db_path),
            format="markdown",
            verbose=False,
        )

        mock_db.get_run.return_value = sample_run

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_report(args)

            assert result == 0
            mock_db.get_run.assert_called_once_with("test123")

    def test_report_json_format(self, mock_db, sample_run, tmp_path):
        """Test report with JSON format."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            run="test123",
            db=str(db_path),
            format="json",
            verbose=False,
        )

        mock_db.get_run.return_value = sample_run

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_report(args)

            assert result == 0

    def test_report_run_not_found(self, mock_db, tmp_path):
        """Test report when run doesn't exist."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            run="nonexistent",
            db=str(db_path),
            format="markdown",
            verbose=False,
        )

        mock_db.get_run.return_value = None

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_report(args)

            assert result == 1

    def test_report_missing_db(self):
        """Test report when database doesn't exist."""
        args = argparse.Namespace(
            run="test123",
            db="nonexistent.db",
            format="markdown",
            verbose=False,
        )

        result = cmd_report(args)
        assert result == 1


class TestCmdCompare:
    """Tests for 'compare' command."""

    def test_compare_success(self, mock_db, tmp_path):
        """Test successful comparison."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            runs="run1,run2",
            db=str(db_path),
            metric="throughput_tokens_per_sec",
            format="markdown",
            verbose=False,
        )

        mock_db.compare_runs.return_value = {
            "metric": "throughput_tokens_per_sec",
            "runs": [
                {
                    "run_id": "run1",
                    "model_id": "opus_en_fr",
                    "device": "cpu",
                    "timestamp": "2025-12-19T10:00:00",
                    "avg": 140.0,
                    "min": 137.5,
                    "max": 142.5,
                    "count": 10,
                },
                {
                    "run_id": "run2",
                    "model_id": "m2m100_418m",
                    "device": "cpu",
                    "timestamp": "2025-12-19T11:00:00",
                    "avg": 130.0,
                    "min": 125.0,
                    "max": 135.0,
                    "count": 10,
                },
            ],
        }

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_compare(args)

            assert result == 0
            mock_db.compare_runs.assert_called_once_with(["run1", "run2"], metric="throughput_tokens_per_sec")

    def test_compare_insufficient_runs(self):
        """Test compare with less than 2 runs."""
        args = argparse.Namespace(
            runs="run1",
            db="test.db",
            metric="throughput_tokens_per_sec",
            format="markdown",
            verbose=False,
        )

        result = cmd_compare(args)
        assert result == 1

    def test_compare_missing_db(self):
        """Test compare when database doesn't exist."""
        args = argparse.Namespace(
            runs="run1,run2",
            db="nonexistent.db",
            metric="throughput_tokens_per_sec",
            format="markdown",
            verbose=False,
        )

        result = cmd_compare(args)
        assert result == 1

    def test_compare_json_format(self, mock_db, tmp_path):
        """Test comparison with JSON output."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            runs="run1,run2",
            db=str(db_path),
            metric="duration_seconds",
            format="json",
            verbose=False,
        )

        mock_db.compare_runs.return_value = {
            "metric": "duration_seconds",
            "runs": [],
        }

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            result = cmd_compare(args)

            assert result == 0


class TestCmdRecommend:
    """Tests for 'recommend' command."""

    def test_recommend_success(self, mock_registry):
        """Test successful model recommendation."""
        args = argparse.Namespace(
            target_throughput=None,
            max_memory_gb=4.0,
            device="cpu",
            db=None,
            registry="config/model_registry.yaml",
            format="markdown",
            verbose=False,
        )

        mock_recommendation = ModelRecommendation(
            model_id="opus_en_fr",
            backend="opus",
            device="cpu",
            expected_throughput=15.0,
            expected_memory_mb=120.0,
            confidence="medium",
            rationale="Heuristic-based: CPU-optimized selection",
        )

        with patch("src.benchmarking.cli.ModelRegistry", return_value=mock_registry):
            with patch("src.benchmarking.cli.ModelRecommender") as MockRecommender:
                mock_recommender = MockRecommender.return_value
                mock_recommender.recommend.return_value = mock_recommendation

                result = cmd_recommend(args)

                assert result == 0
                mock_recommender.recommend.assert_called_once()

    def test_recommend_with_benchmark_db(self, mock_registry, tmp_path):
        """Test recommendation with benchmark database."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            target_throughput=10.0,
            max_memory_gb=4.0,
            device="cpu",
            db=str(db_path),
            registry="config/model_registry.yaml",
            format="json",
            verbose=False,
        )

        mock_recommendation = ModelRecommendation(
            model_id="opus_en_fr",
            backend="opus",
            device="cpu",
            expected_throughput=15.0,
            expected_memory_mb=120.0,
            confidence="high",
            rationale="Based on benchmark data",
        )

        with patch("src.benchmarking.cli.ModelRegistry", return_value=mock_registry):
            with patch("src.benchmarking.cli.BenchmarkDatabase") as MockDB:
                with patch("src.benchmarking.cli.ModelRecommender") as MockRecommender:
                    mock_recommender = MockRecommender.return_value
                    mock_recommender.recommend.return_value = mock_recommendation

                    result = cmd_recommend(args)

                    assert result == 0

    def test_recommend_missing_registry(self):
        """Test recommendation with missing registry."""
        args = argparse.Namespace(
            target_throughput=None,
            max_memory_gb=None,
            device=None,
            db=None,
            registry="nonexistent.yaml",
            format="markdown",
            verbose=False,
        )

        result = cmd_recommend(args)
        assert result == 1

    def test_recommend_no_suitable_model(self, mock_registry):
        """Test recommendation when no model fits constraints."""
        args = argparse.Namespace(
            target_throughput=1000.0,
            max_memory_gb=0.001,
            device="cpu",
            db=None,
            registry="config/model_registry.yaml",
            format="markdown",
            verbose=False,
        )

        with patch("src.benchmarking.cli.ModelRegistry", return_value=mock_registry):
            with patch("src.benchmarking.cli.ModelRecommender") as MockRecommender:
                mock_recommender = MockRecommender.return_value
                mock_recommender.recommend.side_effect = ValueError("No suitable models")

                result = cmd_recommend(args)

                assert result == 1


class TestMainCLI:
    """Tests for main CLI entry point."""

    def test_main_no_command(self):
        """Test main with no command specified."""
        with patch("sys.argv", ["cli.py"]):
            result = main()
            assert result == 1

    def test_main_help(self):
        """Test main with --help flag."""
        with patch("sys.argv", ["cli.py", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_main_run_command(self, mock_registry, tmp_path):
        """Test main with run command."""
        sample_run = BenchmarkRun(
            run_id="test",
            model_id="opus_en_fr",
            device="cpu",
            batch_sizes=[8],
            iterations=1,
            corpus_category="tiny",
            purpose="test",
            tags=[],
            system_info=SystemInfo(
                cpu_model="Test",
                cpu_cores=8,
                total_ram_gb=16.0,
                os_name="Linux",
                os_version="5.10",
                python_version="3.10",
            ),
            results=[],
            total_duration_seconds=10.0,
        )

        with patch("sys.argv", [
            "cli.py",
            "run",
            "--model", "opus_en_fr",
            "--device", "cpu",
            "--batch-sizes", "8",
            "--corpus", "tiny",
            "--registry", "config/model_registry.yaml",
        ]):
            with patch("src.benchmarking.cli.ModelRegistry", return_value=mock_registry):
                with patch("src.benchmarking.cli.BenchmarkRunner") as MockRunner:
                    mock_runner = MockRunner.return_value
                    mock_runner.run_benchmark.return_value = sample_run

                    result = main()
                    assert result == 0


class TestArgumentParsing:
    """Tests for argument parsing edge cases."""

    def test_parse_multiple_batch_sizes(self):
        """Test parsing comma-separated batch sizes."""
        batch_sizes_str = "8,16,32"
        batch_sizes = [int(bs.strip()) for bs in batch_sizes_str.split(',')]
        assert batch_sizes == [8, 16, 32]

    def test_parse_tags(self):
        """Test parsing comma-separated tags."""
        tags_str = "baseline, gpu, smoke"
        tags = [tag.strip() for tag in tags_str.split(',')]
        assert tags == ["baseline", "gpu", "smoke"]

    def test_parse_run_ids(self):
        """Test parsing comma-separated run IDs."""
        run_ids_str = "run1, run2, run3"
        run_ids = [rid.strip() for rid in run_ids_str.split(',')]
        assert run_ids == ["run1", "run2", "run3"]


@pytest.mark.benchmarking
class TestCLIIntegrationReadiness:
    """Tests verifying CLI is ready for integration testing."""

    def test_all_commands_have_help(self):
        """Verify all commands have help text."""
        commands = ["run", "list", "report", "compare", "recommend"]
        for command in commands:
            with patch("sys.argv", ["cli.py", command, "--help"]):
                with pytest.raises(SystemExit) as exc_info:
                    main()
                assert exc_info.value.code == 0

    def test_error_messages_on_missing_db(self):
        """Verify helpful error messages when DB missing."""
        # List command
        args_list = argparse.Namespace(
            db="nonexistent.db",
            model=None,
            device=None,
            limit=10,
            offset=0,
            format="markdown",
            verbose=False,
        )
        assert cmd_list(args_list) == 1

        # Report command
        args_report = argparse.Namespace(
            run="test",
            db="nonexistent.db",
            format="markdown",
            verbose=False,
        )
        assert cmd_report(args_report) == 1

        # Compare command
        args_compare = argparse.Namespace(
            runs="run1,run2",
            db="nonexistent.db",
            metric="throughput_tokens_per_sec",
            format="markdown",
            verbose=False,
        )
        assert cmd_compare(args_compare) == 1

    def test_json_output_parseable(self, mock_db, sample_run, tmp_path):
        """Verify JSON output is valid JSON."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            run="test123",
            db=str(db_path),
            format="json",
            verbose=False,
        )

        mock_db.get_run.return_value = sample_run

        with patch("src.benchmarking.cli.BenchmarkDatabase", return_value=mock_db):
            with patch("builtins.print") as mock_print:
                result = cmd_report(args)

                assert result == 0
                # Verify printed output is valid JSON
                printed_output = mock_print.call_args[0][0]
                parsed = json.loads(printed_output)
                assert parsed["run_id"] == "test123"


class TestGetBenchmarkDbPath:
    """Tests for get_benchmark_db_path function."""

    def test_env_var_takes_precedence(self, monkeypatch):
        """Test BENCHMARK_DB_PATH env var overrides config and default."""
        monkeypatch.setenv("BENCHMARK_DB_PATH", "/custom/path/benchmark.db")

        result = get_benchmark_db_path()

        assert result == Path("/custom/path/benchmark.db")

    def test_env_var_with_production_purpose(self, monkeypatch):
        """Test env var takes precedence even for production purpose."""
        monkeypatch.setenv("BENCHMARK_DB_PATH", "/custom/prod.db")

        result = get_benchmark_db_path(purpose="production")

        assert result == Path("/custom/prod.db")

    def test_config_fallback(self, monkeypatch):
        """Test config file path resolution when env not set."""
        monkeypatch.delenv("BENCHMARK_DB_PATH", raising=False)

        mock_config = {"database": {"path": "config/custom.db"}}
        with patch("src.benchmarking.cli._load_benchmarking_yaml", return_value=mock_config):
            result = get_benchmark_db_path()

        assert result == Path("config/custom.db")

    def test_production_path_from_config(self, monkeypatch):
        """Test production path from config."""
        monkeypatch.delenv("BENCHMARK_DB_PATH", raising=False)

        mock_config = {"database": {"production_path": "data/production.db"}}
        with patch("src.benchmarking.cli._load_benchmarking_yaml", return_value=mock_config):
            result = get_benchmark_db_path(purpose="production")

        assert result == Path("data/production.db")

    def test_default_path_when_no_config(self, monkeypatch):
        """Test default path when config doesn't exist."""
        monkeypatch.delenv("BENCHMARK_DB_PATH", raising=False)

        with patch("src.benchmarking.cli._load_benchmarking_yaml", return_value=None):
            result = get_benchmark_db_path()

        assert result == Path("data/benchmarks/benchmarks.db")

    def test_default_production_path(self, monkeypatch):
        """Test default production path when config doesn't exist."""
        monkeypatch.delenv("BENCHMARK_DB_PATH", raising=False)

        with patch("src.benchmarking.cli._load_benchmarking_yaml", return_value=None):
            result = get_benchmark_db_path(purpose="production")

        assert result == Path("data/benchmarks/production.db")


class TestCmdMigrate:
    """Tests for 'migrate' command."""

    def test_migrate_list_shows_versions(self, tmp_path):
        """Test --list shows available migrations."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            list=True,
            to=None,
            rollback=None,
            dry_run=False,
            verbose=False,
        )

        mock_manager = MagicMock()
        mock_manager.list_migrations.return_value = [
            {"version": 8, "description": "Analytics tables", "applied": True, "current": True},
            {"version": 9, "description": "Query indices", "applied": False, "current": False},
        ]
        mock_manager.get_current_version.return_value = 8

        with patch("src.benchmarking.cli.MigrationManager", return_value=mock_manager):
            result = cmd_migrate(args)

            assert result == 0
            mock_manager.list_migrations.assert_called_once()
            mock_manager.get_current_version.assert_called_once()

    def test_migrate_to_version(self, tmp_path):
        """Test migration to specific version."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            list=False,
            to=9,
            rollback=None,
            dry_run=False,
            verbose=False,
        )

        mock_manager = MagicMock()

        with patch("src.benchmarking.cli.MigrationManager", return_value=mock_manager):
            result = cmd_migrate(args)

            assert result == 0
            mock_manager.migrate_to.assert_called_once_with(9, dry_run=False)

    def test_migrate_dry_run(self, tmp_path):
        """Test --dry-run doesn't modify database."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            list=False,
            to=9,
            rollback=None,
            dry_run=True,
            verbose=False,
        )

        mock_manager = MagicMock()

        with patch("src.benchmarking.cli.MigrationManager", return_value=mock_manager):
            result = cmd_migrate(args)

            assert result == 0
            mock_manager.migrate_to.assert_called_once_with(9, dry_run=True)

    def test_migrate_rollback(self, tmp_path):
        """Test rollback to previous version."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            list=False,
            to=None,
            rollback=7,
            dry_run=False,
            verbose=False,
        )

        mock_manager = MagicMock()

        with patch("src.benchmarking.cli.MigrationManager", return_value=mock_manager):
            result = cmd_migrate(args)

            assert result == 0
            mock_manager.rollback_to.assert_called_once_with(7, dry_run=False)

    def test_migrate_no_action_specified(self, tmp_path):
        """Test error when no action specified."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            list=False,
            to=None,
            rollback=None,
            dry_run=False,
            verbose=False,
        )

        mock_manager = MagicMock()

        with patch("src.benchmarking.cli.MigrationManager", return_value=mock_manager):
            result = cmd_migrate(args)

            assert result == 1

    def test_migrate_failure(self, tmp_path):
        """Test migration failure handling."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            list=False,
            to=9,
            rollback=None,
            dry_run=False,
            verbose=False,
        )

        mock_manager = MagicMock()
        mock_manager.migrate_to.side_effect = Exception("Migration failed")

        with patch("src.benchmarking.cli.MigrationManager", return_value=mock_manager):
            result = cmd_migrate(args)

            assert result == 1


class TestCmdAggregate:
    """Tests for 'aggregate' command."""

    def test_aggregate_all_models(self, tmp_path):
        """Test --all aggregation."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            all=True,
            model=None,
            device=None,
            lookback_days=90,
            baseline=False,
            type="weekly",
            verbose=False,
        )

        mock_aggregator = MagicMock()
        mock_aggregator.aggregate_all.return_value = 150

        with patch("src.benchmarking.cli.TimeSeriesAggregator", return_value=mock_aggregator):
            result = cmd_aggregate(args)

            assert result == 0
            mock_aggregator.aggregate_all.assert_called_once_with(lookback_days=90)

    def test_aggregate_specific_model(self, tmp_path):
        """Test --model --device aggregation."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            all=False,
            model="m2m100_418m",
            device="cpu",
            lookback_days=30,
            baseline=False,
            type="weekly",
            verbose=False,
        )

        mock_aggregator = MagicMock()
        mock_aggregator.aggregate_model.return_value = 25

        with patch("src.benchmarking.cli.TimeSeriesAggregator", return_value=mock_aggregator):
            result = cmd_aggregate(args)

            assert result == 0
            mock_aggregator.aggregate_model.assert_called_once_with(
                model_id="m2m100_418m",
                device="cpu",
                lookback_days=30
            )

    def test_aggregate_creates_baseline(self, tmp_path):
        """Test --baseline flag."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            all=False,
            model="m2m100_418m",
            device="cpu",
            lookback_days=90,
            baseline=True,
            type="weekly",
            verbose=False,
        )

        mock_aggregator = MagicMock()
        mock_aggregator.create_baseline.return_value = "baseline_123"

        with patch("src.benchmarking.cli.TimeSeriesAggregator", return_value=mock_aggregator):
            result = cmd_aggregate(args)

            assert result == 0
            mock_aggregator.create_baseline.assert_called_once_with(
                model_id="m2m100_418m",
                device="cpu",
                baseline_type="weekly",
                days_back=90
            )

    def test_aggregate_baseline_requires_model_device(self, tmp_path):
        """Test --baseline requires --model and --device."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            all=False,
            model=None,
            device=None,
            lookback_days=90,
            baseline=True,
            type="weekly",
            verbose=False,
        )

        mock_aggregator = MagicMock()

        with patch("src.benchmarking.cli.TimeSeriesAggregator", return_value=mock_aggregator):
            result = cmd_aggregate(args)

            assert result == 1

    def test_aggregate_baseline_insufficient_data(self, tmp_path):
        """Test baseline returns None when insufficient data."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            all=False,
            model="m2m100_418m",
            device="cpu",
            lookback_days=90,
            baseline=True,
            type="weekly",
            verbose=False,
        )

        mock_aggregator = MagicMock()
        mock_aggregator.create_baseline.return_value = None

        with patch("src.benchmarking.cli.TimeSeriesAggregator", return_value=mock_aggregator):
            result = cmd_aggregate(args)

            assert result == 1

    def test_aggregate_no_action_specified(self, tmp_path):
        """Test error when no action specified."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            all=False,
            model=None,
            device=None,
            lookback_days=90,
            baseline=False,
            type="weekly",
            verbose=False,
        )

        mock_aggregator = MagicMock()

        with patch("src.benchmarking.cli.TimeSeriesAggregator", return_value=mock_aggregator):
            result = cmd_aggregate(args)

            assert result == 1


class TestCmdRetention:
    """Tests for 'retention' command."""

    def test_retention_status(self, tmp_path):
        """Test --status shows retention policy status."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            status=True,
            run=False,
            dry_run=False,
            policies=None,
            vacuum=False,
            verbose=False,
        )

        mock_engine = MagicMock()
        mock_engine.get_retention_status.return_value = {
            "total_policies": 3,
            "enabled_policies": 2,
            "disabled_policies": 1,
            "policies": [
                {
                    "name": "benchmark_results_90d",
                    "enabled": True,
                    "retention_days": 90,
                    "table": "benchmark_results",
                    "rows_total": 1000,
                    "rows_to_delete": 100,
                    "last_cleanup": "2025-12-01T10:00:00",
                }
            ]
        }

        with patch("src.benchmarking.cli.RetentionEngine", return_value=mock_engine):
            result = cmd_retention(args)

            assert result == 0
            mock_engine.get_retention_status.assert_called_once()

    def test_retention_dry_run(self, tmp_path):
        """Test --dry-run shows what would be deleted."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            status=False,
            run=True,
            dry_run=True,
            policies=None,
            vacuum=False,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.policy_name = "benchmark_results_90d"
        mock_result.dry_run = True
        mock_result.rows_deleted = 100
        mock_result.error = None

        mock_engine = MagicMock()
        mock_engine.execute_retention.return_value = [mock_result]

        with patch("src.benchmarking.cli.RetentionEngine", return_value=mock_engine):
            result = cmd_retention(args)

            assert result == 0
            mock_engine.execute_retention.assert_called_once_with(policy_names=None, dry_run=True)

    def test_retention_apply_policy(self, tmp_path):
        """Test actual retention policy application."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            status=False,
            run=True,
            dry_run=False,
            policies="benchmark_results_90d",
            vacuum=False,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.policy_name = "benchmark_results_90d"
        mock_result.dry_run = False
        mock_result.rows_deleted = 50
        mock_result.error = None

        mock_engine = MagicMock()
        mock_engine.execute_retention.return_value = [mock_result]

        with patch("src.benchmarking.cli.RetentionEngine", return_value=mock_engine):
            result = cmd_retention(args)

            assert result == 0
            mock_engine.execute_retention.assert_called_once_with(
                policy_names=["benchmark_results_90d"],
                dry_run=False
            )

    def test_retention_with_vacuum(self, tmp_path):
        """Test --vacuum after retention."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            status=False,
            run=True,
            dry_run=False,
            policies=None,
            vacuum=True,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.policy_name = "benchmark_results_90d"
        mock_result.dry_run = False
        mock_result.rows_deleted = 50
        mock_result.error = None

        mock_engine = MagicMock()
        mock_engine.execute_retention.return_value = [mock_result]
        mock_engine.vacuum_database.return_value = 1024000

        with patch("src.benchmarking.cli.RetentionEngine", return_value=mock_engine):
            result = cmd_retention(args)

            assert result == 0
            mock_engine.vacuum_database.assert_called_once()

    def test_retention_missing_db(self):
        """Test retention with missing database."""
        args = argparse.Namespace(
            db="nonexistent.db",
            status=True,
            run=False,
            dry_run=False,
            policies=None,
            vacuum=False,
            verbose=False,
        )

        result = cmd_retention(args)
        assert result == 1

    def test_retention_no_action_specified(self, tmp_path):
        """Test error when no action specified."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            status=False,
            run=False,
            dry_run=False,
            policies=None,
            vacuum=False,
            verbose=False,
        )

        mock_engine = MagicMock()

        with patch("src.benchmarking.cli.RetentionEngine", return_value=mock_engine):
            result = cmd_retention(args)

            assert result == 1


class TestCmdExport:
    """Tests for 'export' command."""

    def test_export_csv(self, tmp_path):
        """Test CSV export format."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        output_path = tmp_path / "export"

        args = argparse.Namespace(
            db=str(db_path),
            format="csv",
            output=str(output_path),
            compress=False,
            pretty=False,
            start_date=None,
            end_date=None,
            model=None,
            device=None,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.format = "csv"
        mock_result.output_path = str(output_path)
        mock_result.tables_exported = ["benchmark_runs", "benchmark_results"]
        mock_result.rows_exported = 500
        mock_result.file_size_bytes = 10240
        mock_result.compressed = False
        mock_result.duration_seconds = 1.5

        mock_exporter = MagicMock()
        mock_exporter.export_csv.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkExporter", return_value=mock_exporter):
            result = cmd_export(args)

            assert result == 0
            mock_exporter.export_csv.assert_called_once()

    def test_export_json(self, tmp_path):
        """Test JSON export format."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        output_path = tmp_path / "export.json"

        args = argparse.Namespace(
            db=str(db_path),
            format="json",
            output=str(output_path),
            compress=False,
            pretty=True,
            start_date=None,
            end_date=None,
            model=None,
            device=None,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.format = "json"
        mock_result.output_path = str(output_path)
        mock_result.tables_exported = ["benchmark_runs", "benchmark_results"]
        mock_result.rows_exported = 500
        mock_result.file_size_bytes = 20480
        mock_result.compressed = False
        mock_result.duration_seconds = 2.0

        mock_exporter = MagicMock()
        mock_exporter.export_json.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkExporter", return_value=mock_exporter):
            result = cmd_export(args)

            assert result == 0
            mock_exporter.export_json.assert_called_once()

    def test_export_sqlite(self, tmp_path):
        """Test SQLite backup export."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        output_path = tmp_path / "backup.db"

        args = argparse.Namespace(
            db=str(db_path),
            format="sqlite",
            output=str(output_path),
            compress=False,
            pretty=False,
            start_date=None,
            end_date=None,
            model=None,
            device=None,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.format = "sqlite"
        mock_result.output_path = str(output_path)
        mock_result.tables_exported = ["benchmark_runs", "benchmark_results", "benchmark_trends"]
        mock_result.rows_exported = 1000
        mock_result.file_size_bytes = 102400
        mock_result.compressed = False
        mock_result.duration_seconds = 3.0

        mock_exporter = MagicMock()
        mock_exporter.export_sqlite.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkExporter", return_value=mock_exporter):
            result = cmd_export(args)

            assert result == 0
            mock_exporter.export_sqlite.assert_called_once()

    def test_export_with_filter(self, tmp_path):
        """Test filtered export."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        output_path = tmp_path / "filtered.json"

        args = argparse.Namespace(
            db=str(db_path),
            format="json",
            output=str(output_path),
            compress=False,
            pretty=False,
            start_date="2024-01-01",
            end_date="2024-12-31",
            model="m2m100_418m,opus_en_fr",
            device="cpu,cuda:0",
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.format = "json"
        mock_result.output_path = str(output_path)
        mock_result.tables_exported = ["benchmark_runs", "benchmark_results"]
        mock_result.rows_exported = 100
        mock_result.file_size_bytes = 5120
        mock_result.compressed = False
        mock_result.duration_seconds = 0.8

        mock_exporter = MagicMock()
        mock_exporter.export_json.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkExporter", return_value=mock_exporter):
            with patch("src.benchmarking.cli.ExportFilter") as MockFilter:
                result = cmd_export(args)

                assert result == 0
                MockFilter.assert_called_once_with(
                    start_date="2024-01-01",
                    end_date="2024-12-31",
                    model_ids=["m2m100_418m", "opus_en_fr"],
                    devices=["cpu", "cuda:0"],
                )

    def test_export_with_compression(self, tmp_path):
        """Test compressed export."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        output_path = tmp_path / "export.json.gz"

        args = argparse.Namespace(
            db=str(db_path),
            format="json",
            output=str(output_path),
            compress=True,
            pretty=False,
            start_date=None,
            end_date=None,
            model=None,
            device=None,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.error = None
        mock_result.format = "json"
        mock_result.output_path = str(output_path)
        mock_result.tables_exported = ["benchmark_runs"]
        mock_result.rows_exported = 200
        mock_result.file_size_bytes = 4096
        mock_result.compressed = True
        mock_result.duration_seconds = 1.0

        mock_exporter = MagicMock()
        mock_exporter.export_json.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkExporter", return_value=mock_exporter):
            result = cmd_export(args)

            assert result == 0
            call_kwargs = mock_exporter.export_json.call_args[1]
            assert call_kwargs["compress"] is True

    def test_export_missing_db(self):
        """Test export with missing database."""
        args = argparse.Namespace(
            db="nonexistent.db",
            format="csv",
            output="export/",
            compress=False,
            pretty=False,
            start_date=None,
            end_date=None,
            model=None,
            device=None,
            verbose=False,
        )

        result = cmd_export(args)
        assert result == 1

    def test_export_error(self, tmp_path):
        """Test export failure handling."""
        db_path = tmp_path / "test.db"
        db_path.touch()
        output_path = tmp_path / "export.csv"

        args = argparse.Namespace(
            db=str(db_path),
            format="csv",
            output=str(output_path),
            compress=False,
            pretty=False,
            start_date=None,
            end_date=None,
            model=None,
            device=None,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.error = "Disk full"

        mock_exporter = MagicMock()
        mock_exporter.export_csv.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkExporter", return_value=mock_exporter):
            result = cmd_export(args)

            assert result == 1


class TestCmdArchive:
    """Tests for 'archive' command."""

    def test_archive_list(self, tmp_path):
        """Test --list shows archives."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=True,
            create=False,
            before=None,
            compress=False,
            delete_after=False,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_archive_info = MagicMock()
        mock_archive_info.archive_id = "archive_20241215_120000"
        mock_archive_info.archive_path = str(tmp_path / "archives/archive_20241215.db")
        mock_archive_info.compressed = False
        mock_archive_info.created_at = "2024-12-15T12:00:00"
        mock_archive_info.data_start_date = "2024-01-01T00:00:00"
        mock_archive_info.data_end_date = "2024-06-01T00:00:00"
        mock_archive_info.total_runs = 50
        mock_archive_info.total_results = 500
        mock_archive_info.file_size_bytes = 51200

        mock_archiver = MagicMock()
        mock_archiver.list_archives.return_value = [mock_archive_info]
        mock_archiver.get_archive_summary.return_value = {
            "archive_count": 1,
            "total_size_bytes": 51200,
        }

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0
            mock_archiver.list_archives.assert_called_once()
            mock_archiver.get_archive_summary.assert_called_once()

    def test_archive_list_empty(self, tmp_path):
        """Test --list when no archives exist."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=True,
            create=False,
            before=None,
            compress=False,
            delete_after=False,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_archiver = MagicMock()
        mock_archiver.list_archives.return_value = []

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0

    def test_archive_create(self, tmp_path):
        """Test archive creation."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=True,
            before="2024-01-01",
            compress=False,
            delete_after=False,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_metadata = MagicMock()
        mock_metadata.total_runs = 25
        mock_metadata.total_results = 250
        mock_metadata.file_size_bytes = 25600

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.archive_path = str(tmp_path / "archives/archive_20241215.db")
        mock_result.metadata = mock_metadata
        mock_result.duration_seconds = 2.0
        mock_result.rows_deleted = 0

        mock_archiver = MagicMock()
        mock_archiver.create_archive.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0
            mock_archiver.create_archive.assert_called_once_with(
                before_date="2024-01-01",
                compress=False,
                delete_after_archive=False,
            )

    def test_archive_create_requires_before(self, tmp_path):
        """Test --create requires --before."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=True,
            before=None,
            compress=False,
            delete_after=False,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_archiver = MagicMock()

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 1

    def test_archive_create_with_delete(self, tmp_path):
        """Test archive creation with --delete-after."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=True,
            before="2024-01-01",
            compress=True,
            delete_after=True,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_metadata = MagicMock()
        mock_metadata.total_runs = 25
        mock_metadata.total_results = 250
        mock_metadata.file_size_bytes = 12800

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.archive_path = str(tmp_path / "archives/archive_20241215.db.gz")
        mock_result.metadata = mock_metadata
        mock_result.duration_seconds = 3.0
        mock_result.rows_deleted = 275

        mock_archiver = MagicMock()
        mock_archiver.create_archive.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0
            mock_archiver.create_archive.assert_called_once_with(
                before_date="2024-01-01",
                compress=True,
                delete_after_archive=True,
            )

    def test_archive_create_no_data(self, tmp_path):
        """Test archive creation when no data to archive."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=True,
            before="2020-01-01",
            compress=False,
            delete_after=False,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.archive_path = None

        mock_archiver = MagicMock()
        mock_archiver.create_archive.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0

    def test_archive_restore(self, tmp_path):
        """Test archive restoration."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=False,
            before=None,
            compress=False,
            delete_after=False,
            restore="archive_20241215_120000",
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.success = True
        mock_result.archive_path = str(tmp_path / "archives/archive_20241215.db")
        mock_result.tables_restored = ["benchmark_runs", "benchmark_results"]
        mock_result.rows_restored = 275
        mock_result.duration_seconds = 1.5

        mock_archiver = MagicMock()
        mock_archiver.restore_archive.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0
            mock_archiver.restore_archive.assert_called_once_with("archive_20241215_120000")

    def test_archive_restore_failure(self, tmp_path):
        """Test archive restoration failure."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=False,
            before=None,
            compress=False,
            delete_after=False,
            restore="nonexistent_archive",
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_result = MagicMock()
        mock_result.success = False
        mock_result.error = "Archive not found"

        mock_archiver = MagicMock()
        mock_archiver.restore_archive.return_value = mock_result

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 1

    def test_archive_rotate(self, tmp_path):
        """Test archive rotation."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=False,
            before=None,
            compress=False,
            delete_after=False,
            restore=None,
            rotate=True,
            keep=3,
            verbose=False,
        )

        mock_archiver = MagicMock()
        mock_archiver.rotate_archives.return_value = 2

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 0
            mock_archiver.rotate_archives.assert_called_once_with(keep_count=3)

    def test_archive_no_action_specified(self, tmp_path):
        """Test error when no action specified."""
        db_path = tmp_path / "test.db"
        db_path.touch()

        args = argparse.Namespace(
            db=str(db_path),
            archive_dir=None,
            list=False,
            create=False,
            before=None,
            compress=False,
            delete_after=False,
            restore=None,
            rotate=False,
            keep=5,
            verbose=False,
        )

        mock_archiver = MagicMock()

        with patch("src.benchmarking.cli.BenchmarkArchiver", return_value=mock_archiver):
            result = cmd_archive(args)

            assert result == 1


class TestNewCLICommands:
    """Tests for new CLI commands help."""

    def test_migrate_command_help(self):
        """Verify migrate command has help text."""
        with patch("sys.argv", ["cli.py", "migrate", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_aggregate_command_help(self):
        """Verify aggregate command has help text."""
        with patch("sys.argv", ["cli.py", "aggregate", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_retention_command_help(self):
        """Verify retention command has help text."""
        with patch("sys.argv", ["cli.py", "retention", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_export_command_help(self):
        """Verify export command has help text."""
        with patch("sys.argv", ["cli.py", "export", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0

    def test_archive_command_help(self):
        """Verify archive command has help text."""
        with patch("sys.argv", ["cli.py", "archive", "--help"]):
            with pytest.raises(SystemExit) as exc_info:
                main()
            assert exc_info.value.code == 0
