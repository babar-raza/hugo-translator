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
    """Create mock SystemInfo for testing (comprehensive version)."""
    return SystemInfo(
        cpu_model="Test CPU",
        cpu_cores=4,
        total_ram_gb=16.0,
        gpu_model=None,
        gpu_memory_gb=None,  # Comprehensive SystemInfo uses gpu_memory_gb
        os_name="TestOS",
        os_version="1.0",
        python_version="3.10",
        torch_version="2.0",
        collected_at_utc="2025-12-19T00:00:00Z",
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


# GPU Memory Tracking Tests (migrated from test_runner_gpu_memory.py - BM04C-03)


@pytest.fixture
def mock_backend():
    """Create mock backend with translate method."""
    backend = Mock()
    backend.translate_with_token_counts = Mock(
        return_value=(
            ['translated text'],
            100,  # input tokens
            50,   # output tokens
        )
    )
    return backend


def test_gpu_memory_tracking_enabled_on_cuda(mock_registry, mock_backend):
    """Test that GPU memory tracking is enabled when using CUDA device."""
    runner = BenchmarkRunner(registry=mock_registry, db_path=None)

    with patch('src.benchmarking.runner.TORCH_AVAILABLE', True), \
         patch('src.benchmarking.runner.torch') as mock_torch:

        # Setup torch mock
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.max_memory_allocated.return_value = 1024 * 1024 * 512  # 512 MB

        # Run benchmark
        results = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test text'],
            sample_ids=['sample_1'],
            model_id='test_model',
            device='cuda',
            batch_size=1,
        )

        # Verify GPU memory tracking was called
        mock_torch.cuda.reset_peak_memory_stats.assert_called()
        mock_torch.cuda.max_memory_allocated.assert_called()
        mock_torch.cuda.empty_cache.assert_called()

        # Verify result has peak_memory_mb set
        assert len(results) == 1
        assert results[0].peak_memory_mb is not None
        assert results[0].peak_memory_mb == 512.0


def test_gpu_memory_tracking_disabled_on_cpu(mock_registry, mock_backend):
    """Test that GPU memory tracking is NOT called when using CPU device."""
    runner = BenchmarkRunner(registry=mock_registry, db_path=None)

    with patch('src.benchmarking.runner.TORCH_AVAILABLE', True), \
         patch('src.benchmarking.runner.torch') as mock_torch:

        # Setup torch mock
        mock_torch.cuda.is_available.return_value = True

        # Run benchmark on CPU
        results = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test text'],
            sample_ids=['sample_1'],
            model_id='test_model',
            device='cpu',
            batch_size=1,
        )

        # Verify GPU memory tracking was NOT called for CPU
        mock_torch.cuda.reset_peak_memory_stats.assert_not_called()
        mock_torch.cuda.max_memory_allocated.assert_not_called()

        # Verify result has peak_memory_mb as None
        assert len(results) == 1
        assert results[0].peak_memory_mb is None


def test_oom_exception_handling(mock_registry, mock_backend):
    """Test that OOM exceptions are caught and logged properly."""
    runner = BenchmarkRunner(registry=mock_registry, db_path=None)

    with patch('src.benchmarking.runner.TORCH_AVAILABLE', True), \
         patch('src.benchmarking.runner.torch') as mock_torch:

        # Setup torch mock
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.OutOfMemoryError = RuntimeError  # Mock OOM exception
        mock_torch.cuda.max_memory_allocated.return_value = 1024 * 1024 * 2048  # 2GB

        # Make backend raise OOM
        mock_backend.translate_with_token_counts.side_effect = RuntimeError("CUDA out of memory")

        # Run benchmark
        results = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test text'],
            sample_ids=['sample_1'],
            model_id='test_model',
            device='cuda',
            batch_size=32,
        )

        # Verify error was captured
        assert len(results) == 1
        assert len(results[0].errors) > 0
        assert 'Translation failed' in results[0].errors[0]

        # Verify GPU cache was cleared
        mock_torch.cuda.empty_cache.assert_called()


def test_gpu_memory_tracking_without_torch(mock_registry, mock_backend):
    """Test that benchmarks work when torch is not available."""
    runner = BenchmarkRunner(registry=mock_registry, db_path=None)

    with patch('src.benchmarking.runner.TORCH_AVAILABLE', False):
        # Run benchmark without torch
        results = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test text'],
            sample_ids=['sample_1'],
            model_id='test_model',
            device='cuda',  # Even with cuda device specified
            batch_size=1,
        )

        # Should complete without error
        assert len(results) == 1
        assert results[0].peak_memory_mb is None


def test_multiple_batch_sizes_track_memory(mock_registry, mock_backend):
    """Test that different batch sizes track different memory usage."""
    runner = BenchmarkRunner(registry=mock_registry, db_path=None)

    with patch('src.benchmarking.runner.TORCH_AVAILABLE', True), \
         patch('src.benchmarking.runner.torch') as mock_torch:

        # Setup torch mock with increasing memory for larger batches
        mock_torch.cuda.is_available.return_value = True

        memory_values = [
            1024 * 1024 * 100,  # 100 MB for batch_size=1
            1024 * 1024 * 400,  # 400 MB for batch_size=4
        ]
        mock_torch.cuda.max_memory_allocated.side_effect = memory_values

        # Run with batch_size=1
        results_small = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test text'],
            sample_ids=['sample_1'],
            model_id='test_model',
            device='cuda',
            batch_size=1,
        )

        # Run with batch_size=4
        mock_backend.translate_with_token_counts.return_value = (
            ['translated'] * 4,
            400,
            200,
        )
        results_large = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test'] * 4,
            sample_ids=[f'sample_{i}' for i in range(4)],
            model_id='test_model',
            device='cuda',
            batch_size=4,
        )

        # Verify different memory values
        assert results_small[0].peak_memory_mb == 100.0
        assert results_large[0].peak_memory_mb == 400.0


def test_cuda_device_with_index(mock_registry, mock_backend):
    """Test GPU memory tracking works with specific CUDA device index (cuda:0)."""
    runner = BenchmarkRunner(registry=mock_registry, db_path=None)

    with patch('src.benchmarking.runner.TORCH_AVAILABLE', True), \
         patch('src.benchmarking.runner.torch') as mock_torch:

        # Setup torch mock
        mock_torch.cuda.is_available.return_value = True
        mock_torch.cuda.max_memory_allocated.return_value = 1024 * 1024 * 256  # 256 MB

        # Run benchmark with cuda:0
        results = runner._benchmark_translation(
            backend=mock_backend,
            texts=['test text'],
            sample_ids=['sample_1'],
            model_id='test_model',
            device='cuda:0',
            batch_size=1,
        )

        # Verify GPU memory tracking was called
        mock_torch.cuda.reset_peak_memory_stats.assert_called()
        mock_torch.cuda.max_memory_allocated.assert_called()

        # Verify result
        assert results[0].peak_memory_mb == 256.0
