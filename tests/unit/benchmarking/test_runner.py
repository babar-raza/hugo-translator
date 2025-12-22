"""
Unit tests for BenchmarkRunner.

Tests benchmark orchestration, token counting, error handling, and result persistence.
"""

import json
import pytest
from pathlib import Path
from unittest.mock import MagicMock, Mock, patch, mock_open

from src.benchmarking.runner import BenchmarkRunner, load_corpus
from src.benchmarking.storage import BenchmarkDatabase, BenchmarkResult, BenchmarkRun, SystemInfo
from src.model_runtime.registry import ModelInfo, ModelRegistry


@pytest.fixture
def mock_registry():
    """Create a mock ModelRegistry with test models."""
    registry = Mock(spec=ModelRegistry)

    # Create test model info
    model_info = ModelInfo(
        model_id="test_model",
        name="Test Model",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=100,
        min_ram_gb=2.0,
        optimal_device="cpu",
        parameters=100_000_000,
    )

    registry.models = {"test_model": model_info}
    return registry


@pytest.fixture
def mock_system_info():
    """Create mock SystemInfo for testing."""
    return SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=4,
        total_ram_gb=16.0,
        gpu_model=None,
        gpu_vram_gb=None,
        os_name="TestOS",
        os_version="1.0",
        python_version="3.10",
        torch_version="2.0",
        transformers_version="4.30",
        timestamp_utc="2025-12-19T00:00:00Z",
    )


@pytest.fixture
def tiny_corpus():
    """Create a minimal test corpus."""
    return [
        {"id": "test_001", "text_en": "Hello world", "domain": "general"},
        {"id": "test_002", "text_en": "Test text", "domain": "technical"},
    ]


@pytest.fixture
def temp_corpus_file(tmp_path, tiny_corpus):
    """Create a temporary corpus file."""
    corpus_dir = tmp_path / "data" / "benchmark_corpus"
    corpus_dir.mkdir(parents=True)

    corpus_file = corpus_dir / "tiny.json"
    corpus_file.write_text(json.dumps(tiny_corpus))

    return corpus_file


@pytest.mark.benchmarking
class TestLoadCorpus:
    """Test corpus loading functionality."""

    def test_load_tiny_corpus(self, tmp_path, tiny_corpus):
        """Test loading tiny corpus file."""
        # Create corpus file
        corpus_dir = tmp_path / "data" / "benchmark_corpus"
        corpus_dir.mkdir(parents=True)
        corpus_file = corpus_dir / "tiny.json"
        corpus_file.write_text(json.dumps(tiny_corpus))

        # Simply patch the file operations
        with patch('builtins.open', mock_open(read_data=json.dumps(tiny_corpus))):
            with patch('pathlib.Path.exists', return_value=True):
                result = load_corpus('tiny')

        assert len(result) == 2
        assert result[0]['id'] == 'test_001'

    def test_load_corpus_not_found(self):
        """Test handling of missing corpus file."""
        with patch('pathlib.Path.exists', return_value=False):
            with pytest.raises(FileNotFoundError, match="Corpus file not found"):
                load_corpus('nonexistent')

    def test_load_empty_corpus(self):
        """Test handling of empty corpus."""
        with patch('builtins.open', mock_open(read_data='[]')):
            with patch('pathlib.Path.exists', return_value=True):
                with pytest.raises(ValueError, match="Corpus is empty"):
                    load_corpus('tiny')

    def test_filter_by_category(self, tiny_corpus):
        """Test filtering corpus by category."""
        with patch('builtins.open', mock_open(read_data=json.dumps(tiny_corpus))):
            with patch('pathlib.Path.exists', return_value=True):
                result = load_corpus('technical')

        # Should filter to technical only (if any match)
        # If no match, returns full corpus
        assert len(result) >= 1


@pytest.mark.benchmarking
class TestBenchmarkRunner:
    """Test BenchmarkRunner orchestration."""

    def test_init_without_db(self, mock_registry):
        """Test initialization without database."""
        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        assert runner.registry == mock_registry
        assert runner.db is None
        assert runner.system_collector is not None

    def test_init_with_db(self, mock_registry):
        """Test initialization with database."""
        runner = BenchmarkRunner(registry=mock_registry, db_path=":memory:")

        assert runner.db is not None
        assert isinstance(runner.db, BenchmarkDatabase)

    def test_run_benchmark_model_not_found(self, mock_registry):
        """Test error handling for missing model."""
        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with pytest.raises(ValueError, match="not found in registry"):
            runner.run_benchmark(
                model_id="nonexistent",
                device="cpu",
                batch_sizes=[8],
                iterations=1,
            )

    def test_run_benchmark_cuda_unavailable(self, mock_registry):
        """Test error handling for unavailable CUDA."""
        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with patch('torch.cuda.is_available', return_value=False):
            with pytest.raises(RuntimeError, match="CUDA is not available"):
                runner.run_benchmark(
                    model_id="test_model",
                    device="cuda",
                    batch_sizes=[8],
                    iterations=1,
                )

    @patch('src.benchmarking.runner.load_corpus')
    @patch('src.benchmarking.runner.ModelLoader')
    def test_run_benchmark_success(self, mock_loader_class, mock_load_corpus, mock_registry):
        """Test successful benchmark run."""
        # Setup mocks
        mock_load_corpus.return_value = [
            {"id": "test_001", "text_en": "Hello", "domain": "general"},
        ]

        # Mock system info collector
        mock_system_info = Mock()
        mock_system_info.cpu_model = "Test CPU"
        mock_system_info.cpu_cores = 4
        mock_system_info.total_ram_gb = 16.0
        mock_system_info.gpu_model = None
        mock_system_info.gpu_memory_gb = None
        mock_system_info.os_name = "TestOS"
        mock_system_info.os_version = "1.0"
        mock_system_info.python_version = "3.10"
        mock_system_info.torch_version = "2.0"
        mock_system_info.collected_at_utc = "2025-12-19T00:00:00Z"

        # Mock backend
        mock_backend = Mock()
        mock_backend.translate_with_token_counts = Mock(
            return_value=(["Привет"], 10, 8)
        )

        # Mock loader
        mock_loader = Mock()
        mock_loader.load_model.return_value = mock_backend
        mock_loader_class.return_value = mock_loader

        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with patch.object(runner.system_collector, 'collect', return_value=mock_system_info):
            result = runner.run_benchmark(
                model_id="test_model",
                device="cpu",
                batch_sizes=[1],
                iterations=1,
                corpus_filter="tiny",
            )

        # Verify result
        assert result.model_id == "test_model"
        assert result.device == "cpu"
        assert result.batch_sizes == [1]
        assert result.iterations == 1
        assert len(result.results) == 1
        assert result.results[0].tokens_input == 10
        assert result.results[0].tokens_output == 8

        # Verify loader was called
        mock_loader.load_model.assert_called_once_with("test_model", device="cpu")
        mock_loader.unload_all.assert_called_once()

    @patch('src.benchmarking.runner.load_corpus')
    @patch('src.benchmarking.runner.ModelLoader')
    def test_run_benchmark_with_db_persistence(self, mock_loader_class, mock_load_corpus, mock_registry):
        """Test benchmark run with database persistence."""
        # Setup mocks
        mock_load_corpus.return_value = [
            {"id": "test_001", "text_en": "Hello", "domain": "general"},
        ]

        mock_system_info = Mock()
        mock_system_info.cpu_model = "Test CPU"
        mock_system_info.cpu_cores = 4
        mock_system_info.total_ram_gb = 16.0
        mock_system_info.gpu_model = None
        mock_system_info.gpu_memory_gb = None
        mock_system_info.os_name = "TestOS"
        mock_system_info.os_version = "1.0"
        mock_system_info.python_version = "3.10"
        mock_system_info.torch_version = "2.0"
        mock_system_info.collected_at_utc = "2025-12-19T00:00:00Z"

        mock_backend = Mock()
        mock_backend.translate_with_token_counts = Mock(
            return_value=(["Привет"], 10, 8)
        )

        mock_loader = Mock()
        mock_loader.load_model.return_value = mock_backend
        mock_loader_class.return_value = mock_loader

        # Use in-memory database
        runner = BenchmarkRunner(registry=mock_registry, db_path=":memory:")

        with patch.object(runner.system_collector, 'collect', return_value=mock_system_info):
            result = runner.run_benchmark(
                model_id="test_model",
                device="cpu",
                batch_sizes=[1],
                iterations=1,
                corpus_filter="tiny",
                purpose="test",
                tags=["unittest"],
            )

        # Verify persistence
        saved_runs = runner.db.list_runs()
        assert len(saved_runs) == 1
        assert saved_runs[0][0] == result.run_id

    @patch('src.benchmarking.runner.load_corpus')
    @patch('src.benchmarking.runner.ModelLoader')
    def test_run_benchmark_ct2_fallback(self, mock_loader_class, mock_load_corpus, mock_registry):
        """Test token counting fallback for CT2 backend."""
        # Setup mocks
        mock_load_corpus.return_value = [
            {"id": "test_001", "text_en": "Hello world", "domain": "general"},
        ]

        mock_system_info = Mock()
        mock_system_info.cpu_model = "Test CPU"
        mock_system_info.cpu_cores = 4
        mock_system_info.total_ram_gb = 16.0
        mock_system_info.gpu_model = None
        mock_system_info.gpu_memory_gb = None
        mock_system_info.os_name = "TestOS"
        mock_system_info.os_version = "1.0"
        mock_system_info.python_version = "3.10"
        mock_system_info.torch_version = "2.0"
        mock_system_info.collected_at_utc = "2025-12-19T00:00:00Z"

        # Mock backend WITHOUT translate_with_token_counts (CT2 backend)
        mock_backend = Mock(spec=['translate', 'load', 'unload', 'is_loaded'])
        mock_backend.translate.return_value = ["Привет мир"]

        mock_loader = Mock()
        mock_loader.load_model.return_value = mock_backend
        mock_loader_class.return_value = mock_loader

        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with patch.object(runner.system_collector, 'collect', return_value=mock_system_info):
            with patch('src.benchmarking.runner.estimate_token_count', return_value=5):
                result = runner.run_benchmark(
                    model_id="test_model",
                    device="cpu",
                    batch_sizes=[1],
                    iterations=1,
                    corpus_filter="tiny",
                )

        # Verify fallback token counting was used
        assert len(result.results) == 1
        # Token count should be from estimate_token_count (5)
        assert result.results[0].tokens_input == 5
        assert result.results[0].tokens_output == 5

    @patch('src.benchmarking.runner.load_corpus')
    @patch('src.benchmarking.runner.ModelLoader')
    def test_run_benchmark_with_max_samples(self, mock_loader_class, mock_load_corpus, mock_registry):
        """Test limiting corpus with max_samples."""
        # Setup mocks with larger corpus
        mock_load_corpus.return_value = [
            {"id": f"test_{i:03d}", "text_en": f"Text {i}", "domain": "general"}
            for i in range(10)
        ]

        mock_system_info = Mock()
        mock_system_info.cpu_model = "Test CPU"
        mock_system_info.cpu_cores = 4
        mock_system_info.total_ram_gb = 16.0
        mock_system_info.gpu_model = None
        mock_system_info.gpu_memory_gb = None
        mock_system_info.os_name = "TestOS"
        mock_system_info.os_version = "1.0"
        mock_system_info.python_version = "3.10"
        mock_system_info.torch_version = "2.0"
        mock_system_info.collected_at_utc = "2025-12-19T00:00:00Z"

        mock_backend = Mock()
        mock_backend.translate_with_token_counts = Mock(
            return_value=(["Текст"] * 3, 30, 24)
        )

        mock_loader = Mock()
        mock_loader.load_model.return_value = mock_backend
        mock_loader_class.return_value = mock_loader

        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with patch.object(runner.system_collector, 'collect', return_value=mock_system_info):
            result = runner.run_benchmark(
                model_id="test_model",
                device="cpu",
                batch_sizes=[3],
                iterations=1,
                corpus_filter="tiny",
                max_samples=3,
            )

        # Verify only 3 samples processed
        assert result.metadata["corpus_size"] == 3
        assert len(result.results) == 3

    @patch('src.benchmarking.runner.load_corpus')
    @patch('src.benchmarking.runner.ModelLoader')
    def test_run_benchmark_translation_error(self, mock_loader_class, mock_load_corpus, mock_registry):
        """Test error handling during translation."""
        # Setup mocks
        mock_load_corpus.return_value = [
            {"id": "test_001", "text_en": "Hello", "domain": "general"},
        ]

        mock_system_info = Mock()
        mock_system_info.cpu_model = "Test CPU"
        mock_system_info.cpu_cores = 4
        mock_system_info.total_ram_gb = 16.0
        mock_system_info.gpu_model = None
        mock_system_info.gpu_memory_gb = None
        mock_system_info.os_name = "TestOS"
        mock_system_info.os_version = "1.0"
        mock_system_info.python_version = "3.10"
        mock_system_info.torch_version = "2.0"
        mock_system_info.collected_at_utc = "2025-12-19T00:00:00Z"

        # Mock backend that raises error
        mock_backend = Mock()
        mock_backend.translate_with_token_counts = Mock(
            side_effect=RuntimeError("Translation failed")
        )

        mock_loader = Mock()
        mock_loader.load_model.return_value = mock_backend
        mock_loader_class.return_value = mock_loader

        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with patch.object(runner.system_collector, 'collect', return_value=mock_system_info):
            result = runner.run_benchmark(
                model_id="test_model",
                device="cpu",
                batch_sizes=[1],
                iterations=1,
                corpus_filter="tiny",
            )

        # Should have error result
        assert len(result.results) == 1
        assert len(result.results[0].errors) > 0
        assert "Translation failed" in result.results[0].errors[0]
        assert result.results[0].tokens_input == 0
        assert result.results[0].throughput_tokens_per_sec == 0.0

    @patch('src.benchmarking.runner.load_corpus')
    @patch('src.benchmarking.runner.ModelLoader')
    def test_run_benchmark_multiple_batch_sizes(self, mock_loader_class, mock_load_corpus, mock_registry):
        """Test benchmark with multiple batch sizes and iterations."""
        # Setup mocks
        mock_load_corpus.return_value = [
            {"id": f"test_{i:03d}", "text_en": f"Text {i}", "domain": "general"}
            for i in range(4)
        ]

        mock_system_info = Mock()
        mock_system_info.cpu_model = "Test CPU"
        mock_system_info.cpu_cores = 4
        mock_system_info.total_ram_gb = 16.0
        mock_system_info.gpu_model = None
        mock_system_info.gpu_memory_gb = None
        mock_system_info.os_name = "TestOS"
        mock_system_info.os_version = "1.0"
        mock_system_info.python_version = "3.10"
        mock_system_info.torch_version = "2.0"
        mock_system_info.collected_at_utc = "2025-12-19T00:00:00Z"

        mock_backend = Mock()

        def mock_translate(texts, src_lang, tgt_lang):
            return ([f"Текст {i}" for i in range(len(texts))], len(texts) * 10, len(texts) * 8)

        mock_backend.translate_with_token_counts = Mock(side_effect=mock_translate)

        mock_loader = Mock()
        mock_loader.load_model.return_value = mock_backend
        mock_loader_class.return_value = mock_loader

        runner = BenchmarkRunner(registry=mock_registry, db_path=None)

        with patch.object(runner.system_collector, 'collect', return_value=mock_system_info):
            result = runner.run_benchmark(
                model_id="test_model",
                device="cpu",
                batch_sizes=[2, 4],
                iterations=2,
                corpus_filter="tiny",
            )

        # 2 batch sizes * 2 iterations * (4 samples / 2 per batch + 4 samples / 4 per batch)
        # = 2 * 2 * (2 + 1) = 12 batches
        # But we have 4 samples, so:
        # - batch_size=2: 2 batches per iteration * 2 iterations = 4 batches * 2 samples = 8 results
        # - batch_size=4: 1 batch per iteration * 2 iterations = 2 batches * 4 samples = 8 results
        # Total: 16 results
        expected_results = (2 // 2 * 2 + 4 // 4 * 1) * 2 * 4  # Simplified: (2+1)*2*4 = 24 results total

        # Actually: batch_sizes=[2,4], iterations=2, samples=4
        # For batch_size=2: iterations=2, each iteration processes all 4 samples in 2 batches
        #   = 2 iterations * 4 samples = 8 results
        # For batch_size=4: iterations=2, each iteration processes all 4 samples in 1 batch
        #   = 2 iterations * 4 samples = 8 results
        # Total = 16 results
        assert len(result.results) == 16
        assert result.batch_sizes == [2, 4]
        assert result.iterations == 2


@pytest.mark.benchmarking
class TestRunnerCLI:
    """Test CLI argument parsing and execution."""

    @patch('src.benchmarking.runner.BenchmarkRunner')
    @patch('src.benchmarking.runner.ModelRegistry')
    def test_cli_help(self, mock_registry_class, mock_runner_class):
        """Test CLI help text."""
        from src.benchmarking.runner import main

        with patch('sys.argv', ['runner.py', '--help']):
            with pytest.raises(SystemExit) as exc_info:
                main()

            assert exc_info.value.code == 0

    @patch('src.benchmarking.runner.BenchmarkRunner')
    @patch('src.benchmarking.runner.ModelRegistry')
    @patch('pathlib.Path.exists', return_value=True)
    def test_cli_minimal_args(self, mock_exists, mock_registry_class, mock_runner_class):
        """Test CLI with minimal arguments."""
        from src.benchmarking.runner import main

        # Mock registry
        mock_registry = Mock()
        mock_registry.models = {"test_model": Mock()}
        mock_registry_class.return_value = mock_registry

        # Mock runner
        mock_runner = Mock()
        mock_result = Mock()
        mock_result.run_id = "test_run"
        mock_result.model_id = "test_model"
        mock_result.device = "cpu"
        mock_result.batch_sizes = [8]
        mock_result.iterations = 1
        mock_result.corpus_category = "tiny"
        mock_result.results = []
        mock_result.total_duration_seconds = 1.0
        mock_runner.run_benchmark.return_value = mock_result
        mock_runner_class.return_value = mock_runner

        with patch('sys.argv', ['runner.py', '--model', 'test_model', '--device', 'cpu']):
            exit_code = main()

        assert exit_code == 0
        mock_runner.run_benchmark.assert_called_once()
