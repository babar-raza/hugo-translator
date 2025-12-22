"""
Tests for Benchmark CLI module.

Validates argument parsing, command execution, storage interactions,
and error handling for all CLI commands.
"""
import argparse
import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch

from src.benchmarking.cli import (
    cmd_compare,
    cmd_list,
    cmd_recommend,
    cmd_report,
    cmd_run,
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
