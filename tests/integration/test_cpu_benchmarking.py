"""
Integration tests for CPU benchmarking script.

Tests verify that the benchmark script runs successfully with mocked models
and saves results to the database correctly.
"""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from scripts.benchmark_cpu_comprehensive import CPUBenchmarkRunner
from src.benchmarking.storage import BenchmarkDatabase


@pytest.fixture
def mock_corpus_file(tmp_path):
    """Create a temporary corpus file for testing."""
    corpus = [
        {"id": "test_001", "text_en": "Simple test."},
        {"id": "test_002", "text_en": "Another test."},
    ]
    corpus_path = tmp_path / "test_corpus.json"
    corpus_path.write_text(json.dumps(corpus))
    return corpus_path


@pytest.fixture
def mock_db_path(tmp_path):
    """Create a temporary database path."""
    return tmp_path / "test_cpu.db"


@pytest.fixture
def mock_model_and_tokenizer():
    """
    Create mock model and tokenizer for testing.

    Returns mocks that simulate translation behavior without loading
    real models (for speed).
    """
    # Mock tokenizer
    mock_tokenizer = MagicMock()
    mock_tokenizer.return_value = {
        "input_ids": MagicMock(shape=(1, 10))  # 10 input tokens
    }
    mock_tokenizer.decode.return_value = "Translated text"

    # Mock model
    mock_model = MagicMock()
    mock_outputs = MagicMock(shape=(1, 12))  # 12 output tokens
    mock_model.generate.return_value = mock_outputs

    return mock_model, mock_tokenizer


@pytest.mark.integration
@pytest.mark.slow
def test_cpu_benchmark_runner_initialization(mock_corpus_file, mock_db_path, test_model):
    """Test CPUBenchmarkRunner initialization."""
    runner = CPUBenchmarkRunner(
        model_ids=[test_model],
        batch_sizes=[4, 8],
        iterations=1,
        corpus_path=mock_corpus_file,
        db_path=mock_db_path,
    )

    assert runner.model_ids == [test_model]
    assert runner.batch_sizes == [4, 8]
    assert runner.iterations == 1
    assert len(runner.corpus_samples) == 2
    assert runner.database is not None


@pytest.mark.integration
def test_cpu_benchmark_runner_load_corpus_synthetic_fallback(mock_db_path, test_model):
    """Test CPUBenchmarkRunner falls back to synthetic corpus."""
    runner = CPUBenchmarkRunner(
        model_ids=[test_model],
        batch_sizes=[4],
        iterations=1,
        corpus_path=None,  # No corpus
        db_path=mock_db_path,
    )

    # Should use synthetic samples
    assert len(runner.corpus_samples) == 10
    assert all("id" in s and "text_en" in s for s in runner.corpus_samples)


@pytest.mark.integration
def test_cpu_benchmark_runner_check_model_available():
    """Test model availability checking."""
    runner = CPUBenchmarkRunner(
        model_ids=["m2m100_418m"],
        batch_sizes=[4],
        iterations=1,
        corpus_path=None,
        db_path=None,
    )

    # Check existing HF model (should be in registry)
    available = runner._check_model_available("m2m100_418m")
    # Note: This depends on registry state, so we just verify it doesn't crash
    assert isinstance(available, bool)

    # Check non-existent model
    available = runner._check_model_available("nonexistent_model")
    assert available is False


@pytest.mark.integration
@pytest.mark.slow
def test_cpu_benchmark_runner_collect_system_info():
    """Test system information collection."""
    runner = CPUBenchmarkRunner(
        model_ids=["m2m100_418m"],
        batch_sizes=[4],
        iterations=1,
        corpus_path=None,
        db_path=None,
    )

    system_info = runner._collect_system_info()

    # Verify required fields
    assert system_info.cpu_model
    assert system_info.cpu_cores > 0
    assert system_info.total_ram_gb > 0
    assert system_info.os_name
    assert system_info.python_version
    assert system_info.collected_at_utc


@pytest.mark.integration
@pytest.mark.slow
def test_cpu_benchmark_sample_with_mock(
    mock_corpus_file, mock_model_and_tokenizer
):
    """Test benchmarking a single sample with mocked model."""
    mock_model, mock_tokenizer = mock_model_and_tokenizer

    runner = CPUBenchmarkRunner(
        model_ids=["m2m100_418m"],
        batch_sizes=[4],
        iterations=1,
        corpus_path=mock_corpus_file,
        db_path=None,
    )

    sample = runner.corpus_samples[0]

    result = runner._benchmark_sample(
        model=mock_model,
        tokenizer=mock_tokenizer,
        sample=sample,
        model_id="m2m100_418m",
        batch_size=4,
    )

    # Verify result structure
    assert result.sample_id == sample["id"]
    assert result.model_id == "m2m100_418m"
    assert result.device == "cpu"
    assert result.batch_size == 4
    assert result.duration_seconds >= 0
    assert result.tokens_input == 10
    assert result.tokens_output == 12
    assert result.throughput_tokens_per_sec >= 0
    assert result.peak_memory_mb is not None
    assert len(result.errors) == 0


@pytest.mark.integration
@pytest.mark.slow
@patch("scripts.benchmark_cpu_comprehensive.ModelLoader")
def test_cpu_benchmark_full_run_with_mocks(
    mock_loader_class, mock_corpus_file, mock_db_path, mock_model_and_tokenizer
):
    """
    Test full benchmark run with mocked model loading.

    This is the most comprehensive test, verifying:
    - Model loading (mocked)
    - Benchmark execution
    - Database writes
    """
    mock_model, mock_tokenizer = mock_model_and_tokenizer

    # Mock ModelLoader to return a backend object with .model and .tokenizer attributes
    mock_backend = MagicMock()
    mock_backend.model = mock_model
    mock_backend.tokenizer = mock_tokenizer
    mock_loader = MagicMock()
    mock_loader.load_model.return_value = mock_backend
    mock_loader_class.return_value = mock_loader

    # Create runner
    runner = CPUBenchmarkRunner(
        model_ids=["m2m100_418m"],
        batch_sizes=[4],
        thread_counts=[2],
        iterations=1,
        corpus_path=mock_corpus_file,
        db_path=mock_db_path,
    )

    # Mock model availability check to return True
    with patch.object(runner, "_check_model_available", return_value=True):
        # Run benchmarks
        runs = runner.run_all_benchmarks()

    # Verify results
    assert len(runs) == 1  # 1 model x 1 batch size x 1 thread count
    run = runs[0]

    assert run.model_id == "m2m100_418m"
    assert run.device == "cpu"
    assert run.batch_sizes == [4]
    assert run.iterations == 1
    assert len(run.results) == 2  # 2 corpus samples x 1 iteration
    assert run.total_duration_seconds > 0

    # Verify database write
    db = BenchmarkDatabase(mock_db_path)
    saved_runs = db.list_runs()
    assert len(saved_runs) == 1
    assert saved_runs[0][0] == run.run_id


@pytest.mark.integration
def test_cpu_benchmark_runner_print_summary(mock_corpus_file, capsys):
    """Test summary printing."""
    runner = CPUBenchmarkRunner(
        model_ids=["m2m100_418m"],
        batch_sizes=[4, 8],
        iterations=1,
        corpus_path=mock_corpus_file,
        db_path=None,
    )

    # Create mock runs for summary
    from src.benchmarking.storage import BenchmarkResult, BenchmarkRun, SystemInfo

    system_info = SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=4,
        total_ram_gb=16.0,
    )

    mock_runs = [
        BenchmarkRun(
            run_id="test_run_1",
            model_id="m2m100_418m",
            device="cpu",
            batch_sizes=[4],
            iterations=1,
            corpus_category="tiny",
            purpose="test",
            tags=["cpu"],
            system_info=system_info,
            results=[
                BenchmarkResult(
                    sample_id="test_001",
                    model_id="m2m100_418m",
                    device="cpu",
                    batch_size=4,
                    duration_seconds=0.5,
                    tokens_input=10,
                    tokens_output=12,
                    throughput_tokens_per_sec=44.0,
                    peak_memory_mb=100.0,
                )
            ],
            total_duration_seconds=1.0,
            metadata={"thread_count": 4},
        )
    ]

    runner.print_summary(mock_runs)

    # Verify output contains key information
    captured = capsys.readouterr()
    assert "CPU BENCHMARK SUMMARY" in captured.out
    assert "m2m100_418m" in captured.out
    assert "44.0" in captured.out  # Throughput
    assert "100.0" in captured.out  # Memory


@pytest.mark.integration
def test_cpu_benchmark_invalid_corpus_handling(tmp_path, mock_db_path):
    """Test handling of invalid corpus files."""
    # Create invalid corpus (empty)
    invalid_corpus = tmp_path / "invalid.json"
    invalid_corpus.write_text("[]")

    with pytest.raises(ValueError, match="Corpus is empty"):
        CPUBenchmarkRunner(
            model_ids=["m2m100_418m"],
            batch_sizes=[4],
            iterations=1,
            corpus_path=invalid_corpus,
            db_path=mock_db_path,
        )

    # Create malformed corpus
    malformed_corpus = tmp_path / "malformed.json"
    malformed_corpus.write_text('{"invalid": "json"')

    with pytest.raises(ValueError, match="Invalid corpus JSON"):
        CPUBenchmarkRunner(
            model_ids=["m2m100_418m"],
            batch_sizes=[4],
            iterations=1,
            corpus_path=malformed_corpus,
            db_path=mock_db_path,
        )


@pytest.mark.integration
def test_cpu_benchmark_detect_optimal_threads():
    """Test optimal thread detection."""
    runner = CPUBenchmarkRunner(
        model_ids=["m2m100_418m"],
        batch_sizes=[4],
        iterations=1,
        corpus_path=None,
        db_path=None,
    )

    threads = runner._detect_optimal_threads()

    # Should be positive and less than or equal to physical cores
    assert threads > 0
    import psutil

    physical_cores = psutil.cpu_count(logical=False) or psutil.cpu_count(logical=True)
    assert threads <= physical_cores
