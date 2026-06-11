"""Unit tests for tokenizer access methods in model backends."""

from unittest.mock import Mock

from src.model_runtime.loader import CTranslate2Backend, HuggingFaceBackend, ModelLoader
from src.model_runtime.registry import ModelInfo


class TestHuggingFaceBackendTokenizer:
    """Test tokenizer access methods in HuggingFaceBackend."""

    def test_get_token_count_without_tokenizer(self):
        """Test get_token_count returns 0 when tokenizer unavailable."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=2.0,
            optimal_device="cpu",
        )
        backend = HuggingFaceBackend(model_info, device="cpu")

        # Without loading, tokenizer should be None
        assert backend.get_token_count("test text") == 0

    def test_get_token_count_with_mock_tokenizer(self):
        """Test get_token_count with mocked tokenizer."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=2.0,
            optimal_device="cpu",
        )
        backend = HuggingFaceBackend(model_info, device="cpu")

        # Mock tokenizer
        backend.tokenizer = Mock()
        backend.loaded = True
        backend.tokenizer.tokenize = Mock(return_value=["test", "text", "tokens"])

        count = backend.get_token_count("test text")
        assert count == 3
        backend.tokenizer.tokenize.assert_called_once_with("test text")

    def test_get_token_count_handles_exception(self):
        """Test get_token_count handles tokenizer exceptions gracefully."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=2.0,
            optimal_device="cpu",
        )
        backend = HuggingFaceBackend(model_info, device="cpu")

        # Mock tokenizer that raises exception
        backend.tokenizer = Mock()
        backend.loaded = True
        backend.tokenizer.tokenize = Mock(side_effect=Exception("Tokenization failed"))

        count = backend.get_token_count("test text")
        assert count == 0

    def test_get_batch_token_counts_with_mock_tokenizer(self):
        """Test get_batch_token_counts with mocked tokenizer."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=2.0,
            optimal_device="cpu",
        )
        backend = HuggingFaceBackend(model_info, device="cpu")

        # Mock tokenizer
        backend.tokenizer = Mock()
        backend.loaded = True
        backend.tokenizer.return_value = {"input_ids": [[1, 2, 3], [4, 5]]}

        texts = ["text one", "text two"]
        counts = backend.get_batch_token_counts(texts)
        assert counts == [3, 2]

    def test_get_batch_token_counts_handles_exception(self):
        """Test get_batch_token_counts handles exceptions gracefully."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="huggingface",
            supported_pairs="all",
            model_size_mb=500,
            min_ram_gb=2.0,
            optimal_device="cpu",
        )
        backend = HuggingFaceBackend(model_info, device="cpu")

        # Mock tokenizer that raises exception
        backend.tokenizer = Mock()
        backend.loaded = True
        backend.tokenizer.side_effect = Exception("Batch tokenization failed")

        texts = ["text one", "text two"]
        counts = backend.get_batch_token_counts(texts)
        assert counts == [0, 0]


class TestCTranslate2BackendTokenizer:
    """Test tokenizer access methods in CTranslate2Backend."""

    def test_get_token_count_without_tokenizer(self):
        """Test get_token_count returns 0 when tokenizer unavailable."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=300,
            min_ram_gb=1.5,
            optimal_device="cpu",
        )
        backend = CTranslate2Backend(model_info, device="cpu")

        # Without loading, tokenizer should be None
        assert backend.get_token_count("test text") == 0

    def test_get_token_count_with_mock_tokenizer(self):
        """Test get_token_count with mocked tokenizer."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=300,
            min_ram_gb=1.5,
            optimal_device="cpu",
        )
        backend = CTranslate2Backend(model_info, device="cpu")

        # Mock tokenizer
        backend.tokenizer = Mock()
        backend.loaded = True
        backend.tokenizer.tokenize = Mock(return_value=["test", "text", "tokens"])

        count = backend.get_token_count("test text")
        assert count == 3

    def test_get_token_count_handles_exception(self):
        """Test get_token_count handles exceptions gracefully."""
        model_info = ModelInfo(
            model_id="test-model",
            name="Test Model",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=300,
            min_ram_gb=1.5,
            optimal_device="cpu",
        )
        backend = CTranslate2Backend(model_info, device="cpu")

        # Mock tokenizer that raises exception
        backend.tokenizer = Mock()
        backend.loaded = True
        backend.tokenizer.tokenize = Mock(side_effect=Exception("Tokenization failed"))

        count = backend.get_token_count("test text")
        assert count == 0


class TestModelLoaderTokenizer:
    """Test tokenizer for counting method in ModelLoader."""

    def test_get_tokenizer_for_counting_returns_loaded_model(self):
        """Test get_tokenizer_for_counting returns loaded model."""
        from src.model_runtime.registry import ModelRegistry

        registry = Mock(spec=ModelRegistry)
        loader = ModelLoader(registry, device="cpu")

        # Mock a loaded model
        mock_backend = Mock()
        loader.loaded_models["test-model"] = mock_backend

        result = loader.get_tokenizer_for_counting("test-model")
        assert result == mock_backend

    def test_get_tokenizer_for_counting_returns_none_if_not_loaded(self):
        """Test get_tokenizer_for_counting returns None if model not loaded."""
        from src.model_runtime.registry import ModelRegistry

        registry = Mock(spec=ModelRegistry)
        loader = ModelLoader(registry, device="cpu")

        result = loader.get_tokenizer_for_counting("nonexistent-model")
        assert result is None
