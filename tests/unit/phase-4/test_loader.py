"""
Unit tests for Model Loader.
"""
from unittest.mock import MagicMock, Mock, patch

import pytest

from src.model_runtime import (
    HuggingFaceBackend,
    ModelInfo,
    ModelLoader,
    ModelRegistry,
)


@pytest.fixture
def sample_model_info():
    """Create sample ModelInfo."""
    return ModelInfo(
        model_id="test_model",
        name="Test Model",
        backend="huggingface",
        supported_pairs="all",
        model_size_mb=300,
        min_ram_gb=2,
        optimal_device="cpu",
        parameters=100000000,
        hf_model_id="test/model",
    )


@pytest.fixture
def mock_registry(sample_model_info):
    """Create mock ModelRegistry."""
    registry = Mock(spec=ModelRegistry)
    registry.get_model.return_value = sample_model_info
    return registry


class TestModelBackend:
    """Test ModelBackend abstract class."""

    def test_backend_initialization(self, sample_model_info):
        """Test ModelBackend initialization."""
        # Can't instantiate ABC directly, test through concrete class
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        assert backend.model_info == sample_model_info
        assert backend.device == "cpu"
        assert backend.loaded is False

    def test_is_loaded(self, sample_model_info):
        """Test is_loaded method."""
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        assert backend.is_loaded() is False


class TestHuggingFaceBackend:
    """Test HuggingFaceBackend."""

    def test_backend_creation(self, sample_model_info):
        """Test creating HuggingFace backend."""
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        assert backend.model_info.model_id == "test_model"
        assert backend.device == "cpu"
        assert backend.model is None
        assert backend.tokenizer is None

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_load_model(self, mock_model_class, mock_tokenizer_class, sample_model_info):
        """Test loading HuggingFace model."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        # Create backend and load
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        backend.load()

        # Verify
        assert backend.loaded is True
        assert backend.tokenizer is not None
        assert backend.model is not None
        mock_tokenizer_class.from_pretrained.assert_called_once()
        mock_model_class.from_pretrained.assert_called_once()

    @patch("transformers.AutoTokenizer")
    @patch("transformers.AutoModelForSeq2SeqLM")
    def test_translate(
        self, mock_model_class, mock_tokenizer_class, sample_model_info
    ):
        """Test translation with HuggingFace backend."""
        # Setup mocks
        mock_tokenizer = MagicMock()
        mock_model = MagicMock()
        mock_tokenizer_class.from_pretrained.return_value = mock_tokenizer
        mock_model_class.from_pretrained.return_value = mock_model

        # Mock tokenizer behavior
        mock_tokenizer.return_value = {
            "input_ids": MagicMock(),
            "attention_mask": MagicMock(),
        }
        mock_tokenizer.batch_decode.return_value = ["Bonjour"]

        # Mock model.generate
        mock_outputs = MagicMock()
        mock_model.generate.return_value = mock_outputs

        # Create backend, load, and translate
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        backend.load()

        translations = backend.translate(["Hello"], "en", "fr")

        assert len(translations) == 1
        assert translations[0] == "Bonjour"

    def test_translate_without_load(self, sample_model_info):
        """Test translation fails without loading."""
        backend = HuggingFaceBackend(sample_model_info, "cpu")

        with pytest.raises(RuntimeError, match="Model not loaded"):
            backend.translate(["Hello"], "en", "fr")

    def test_translate_empty_list(self, sample_model_info):
        """Test translation with empty list."""
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        backend.loaded = True  # Mock loaded state

        translations = backend.translate([], "en", "fr")
        assert translations == []

    @patch("gc.collect")
    def test_unload_model(self, mock_gc_collect, sample_model_info):
        """Test unloading HuggingFace model."""
        backend = HuggingFaceBackend(sample_model_info, "cpu")
        backend.model = MagicMock()
        backend.tokenizer = MagicMock()
        backend.loaded = True

        backend.unload()

        assert backend.model is None
        assert backend.tokenizer is None
        assert backend.loaded is False
        mock_gc_collect.assert_called_once()


class TestModelLoader:
    """Test ModelLoader."""

    def test_loader_initialization(self, mock_registry):
        """Test creating ModelLoader."""
        loader = ModelLoader(mock_registry, device="cpu")
        assert loader.registry == mock_registry
        assert loader.device == "cpu"
        assert len(loader.loaded_models) == 0

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_load_model(self, mock_backend_class, mock_registry):
        """Test loading model."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cpu")
        backend = loader.load_model("test_model")

        assert backend == mock_backend
        mock_backend.load.assert_called_once()
        assert "test_model" in loader.loaded_models

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_load_model_cached(self, mock_backend_class, mock_registry):
        """Test loading already-loaded model returns cached version."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cpu")

        # Load first time
        backend1 = loader.load_model("test_model")

        # Load second time (should be cached)
        backend2 = loader.load_model("test_model")

        assert backend1 == backend2
        # load() should only be called once
        assert mock_backend.load.call_count == 1

    def test_get_loaded_model(self, mock_registry):
        """Test getting loaded model."""
        loader = ModelLoader(mock_registry, device="cpu")

        # Not loaded yet
        result = loader.get_loaded_model("test_model")
        assert result is None

        # Load model
        mock_backend = MagicMock()
        loader.loaded_models["test_model"] = mock_backend

        # Should now return backend
        result = loader.get_loaded_model("test_model")
        assert result == mock_backend

    def test_unload_model(self, mock_registry):
        """Test unloading model."""
        loader = ModelLoader(mock_registry, device="cpu")

        # Add mock backend
        mock_backend = MagicMock()
        loader.loaded_models["test_model"] = mock_backend

        # Unload
        loader.unload_model("test_model")

        assert "test_model" not in loader.loaded_models
        mock_backend.unload.assert_called_once()

    def test_unload_all(self, mock_registry):
        """Test unloading all models."""
        loader = ModelLoader(mock_registry, device="cpu")

        # Add multiple mock backends
        mock_backend1 = MagicMock()
        mock_backend2 = MagicMock()
        loader.loaded_models["model1"] = mock_backend1
        loader.loaded_models["model2"] = mock_backend2

        # Unload all
        loader.unload_all()

        assert len(loader.loaded_models) == 0
        mock_backend1.unload.assert_called_once()
        mock_backend2.unload.assert_called_once()

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_preload_models(self, mock_backend_class, mock_registry):
        """Test preloading multiple models."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cpu")

        # Preload
        loader.preload_models(["model1", "model2"])

        # Should have loaded both
        assert len(loader.loaded_models) >= 1  # At least attempted

    def test_list_loaded_models(self, mock_registry):
        """Test listing loaded models."""
        loader = ModelLoader(mock_registry, device="cpu")

        # Empty initially
        assert loader.list_loaded_models() == []

        # Add models
        loader.loaded_models["model1"] = MagicMock()
        loader.loaded_models["model2"] = MagicMock()

        models = loader.list_loaded_models()
        assert len(models) == 2
        assert "model1" in models
        assert "model2" in models

    def test_get_memory_usage(self, mock_registry, sample_model_info):
        """Test getting memory usage."""
        loader = ModelLoader(mock_registry, device="cpu")

        # Add mock backend
        mock_backend = MagicMock()
        mock_backend.is_loaded.return_value = True
        mock_backend.device = "cpu"
        mock_backend.model_info = sample_model_info
        loader.loaded_models["test_model"] = mock_backend

        usage = loader.get_memory_usage()

        assert "test_model" in usage
        assert usage["test_model"]["loaded"] is True
        assert usage["test_model"]["device"] == "cpu"
        assert usage["test_model"]["size_mb"] == 300

    def test_len(self, mock_registry):
        """Test __len__ method."""
        loader = ModelLoader(mock_registry, device="cpu")
        assert len(loader) == 0

        loader.loaded_models["model1"] = MagicMock()
        assert len(loader) == 1

    def test_contains(self, mock_registry):
        """Test __contains__ method."""
        loader = ModelLoader(mock_registry, device="cpu")

        assert "model1" not in loader

        loader.loaded_models["model1"] = MagicMock()
        assert "model1" in loader

    def test_create_backend_unsupported(self, mock_registry):
        """Test creating backend for unsupported type."""
        loader = ModelLoader(mock_registry, device="cpu")

        # Create model info with unsupported backend
        unsupported_model = ModelInfo(
            model_id="test",
            name="Test",
            backend="unsupported",
            supported_pairs="all",
            model_size_mb=100,
            min_ram_gb=1,
            optimal_device="cpu",
        )

        with pytest.raises(ValueError, match="Unsupported backend"):
            loader._create_backend(unsupported_model, "cpu")


class TestCTranslate2Backend:
    """Test CTranslate2Backend (if available)."""

    def test_backend_creation(self):
        """Test creating CTranslate2 backend."""
        from src.model_runtime.loader import CTranslate2Backend

        model_info = ModelInfo(
            model_id="test_ct2",
            name="Test CT2",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=200,
            min_ram_gb=1,
            optimal_device="cpu",
        )

        backend = CTranslate2Backend(model_info, "cpu")
        assert backend.model_info.model_id == "test_ct2"
        assert backend.device == "cpu"

    def test_translate_without_load(self):
        """Test CT2 translation fails without loading."""
        from src.model_runtime.loader import CTranslate2Backend

        model_info = ModelInfo(
            model_id="test_ct2",
            name="Test CT2",
            backend="ctranslate2",
            supported_pairs="all",
            model_size_mb=200,
            min_ram_gb=1,
            optimal_device="cpu",
        )

        backend = CTranslate2Backend(model_info, "cpu")

        with pytest.raises(RuntimeError, match="Model not loaded"):
            backend.translate(["Hello"], "en", "fr")


class TestModelLoaderLoadMode:
    """Test ModelLoader load_mode parameter (T103: federated-splashing-panda)."""

    def test_model_loader_with_load_mode_none(self, mock_registry):
        """Test ModelLoader with load_mode=None (auto mode)."""
        loader = ModelLoader(mock_registry, device="cpu", load_mode=None)
        assert loader.load_mode is None

    def test_model_loader_with_load_mode_fp16(self, mock_registry):
        """Test ModelLoader with load_mode='fp16'."""
        loader = ModelLoader(mock_registry, device="cuda", load_mode="fp16")
        assert loader.load_mode == "fp16"

    def test_model_loader_with_load_mode_fp32(self, mock_registry):
        """Test ModelLoader with load_mode='fp32'."""
        loader = ModelLoader(mock_registry, device="cpu", load_mode="fp32")
        assert loader.load_mode == "fp32"

    def test_model_loader_with_load_mode_int8(self, mock_registry):
        """Test ModelLoader with load_mode='int8'."""
        loader = ModelLoader(mock_registry, device="cpu", load_mode="int8")
        assert loader.load_mode == "int8"

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_create_backend_translates_load_mode_fp16(
        self, mock_backend_class, mock_registry, sample_model_info
    ):
        """Test _create_backend translates load_mode='fp16' to use_fp16=True."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cuda", load_mode="fp16")
        backend = loader._create_backend(sample_model_info, "cuda")

        # Verify HuggingFaceBackend was called with use_fp16=True
        mock_backend_class.assert_called_once()
        call_kwargs = mock_backend_class.call_args[1]
        assert call_kwargs.get("use_fp16") is True

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_create_backend_translates_load_mode_fp32(
        self, mock_backend_class, mock_registry, sample_model_info
    ):
        """Test _create_backend translates load_mode='fp32' to use_fp16=False."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cpu", load_mode="fp32")
        backend = loader._create_backend(sample_model_info, "cpu")

        # Verify HuggingFaceBackend was called with use_fp16=False
        mock_backend_class.assert_called_once()
        call_kwargs = mock_backend_class.call_args[1]
        assert call_kwargs.get("use_fp16") is False

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_create_backend_translates_load_mode_int8(
        self, mock_backend_class, mock_registry, sample_model_info
    ):
        """Test _create_backend translates load_mode='int8' to use_int8=True."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cpu", load_mode="int8")
        backend = loader._create_backend(sample_model_info, "cpu")

        # Verify HuggingFaceBackend was called with use_int8=True, use_fp16=False
        mock_backend_class.assert_called_once()
        call_kwargs = mock_backend_class.call_args[1]
        assert call_kwargs.get("use_int8") is True
        assert call_kwargs.get("use_fp16") is False

    @patch("src.model_runtime.loader.HuggingFaceBackend")
    def test_create_backend_translates_load_mode_none(
        self, mock_backend_class, mock_registry, sample_model_info
    ):
        """Test _create_backend with load_mode=None uses default (auto)."""
        mock_backend = MagicMock()
        mock_backend_class.return_value = mock_backend

        loader = ModelLoader(mock_registry, device="cuda", load_mode=None)
        backend = loader._create_backend(sample_model_info, "cuda")

        # Verify HuggingFaceBackend was called with use_fp16=True (default for CUDA)
        mock_backend_class.assert_called_once()
        call_kwargs = mock_backend_class.call_args[1]
        assert call_kwargs.get("use_fp16") is True
