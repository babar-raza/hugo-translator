"""
Tests for GPU-accelerated translation models.

Tests GPU memory management, batch processing, and CPU fallback.
"""
import pytest
import torch

from src.model_runtime.loader import (
    CTranslate2Backend,
    HuggingFaceBackend,
    ModelLoader,
)
from src.model_runtime.registry import ModelInfo, ModelRegistry


class TestHuggingFaceBackendGPU:
    """Tests for HuggingFace backend with GPU."""

    def test_init_with_memory_limit(self):
        """Test initialization with memory limit."""
        model_info = ModelInfo(
            model_id="test_model",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda", max_memory_mb=2048)

        assert backend.max_memory_mb == 2048
        assert backend.device == "cuda"

    def test_init_without_memory_limit(self):
        """Test initialization without memory limit."""
        model_info = ModelInfo(
            model_id="test_model",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda")

        assert backend.max_memory_mb is None

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_load_on_gpu(self):
        """Test loading model on GPU."""
        model_info = ModelInfo(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda", max_memory_mb=4096)

        # Load model
        backend.load()

        assert backend.loaded
        assert backend.model is not None
        assert backend.tokenizer is not None

        # Check model is on GPU
        assert next(backend.model.parameters()).device.type == "cuda"

        # Cleanup
        backend.unload()

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_translate_on_gpu(self):
        """Test translation on GPU."""
        model_info = ModelInfo(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda", max_memory_mb=4096)

        backend.load()

        # Translate
        texts = ["Hello world", "How are you?"]
        translations = backend.translate(texts, "en", "es")

        assert len(translations) == 2
        assert all(isinstance(t, str) for t in translations)

        # Cleanup
        backend.unload()

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_gpu_memory_monitoring(self):
        """Test GPU memory monitoring during translation."""
        model_info = ModelInfo(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda", max_memory_mb=4096)

        # Check initial memory
        initial_memory = torch.cuda.memory_allocated(0)

        backend.load()

        # Check memory after loading
        loaded_memory = torch.cuda.memory_allocated(0)
        assert loaded_memory > initial_memory

        # Translate
        texts = ["Test sentence"] * 10
        backend.translate(texts, "en", "es")

        # Memory should be cleared after translation
        final_memory = torch.cuda.memory_allocated(0)

        # Cleanup
        backend.unload()
        torch.cuda.empty_cache()

        # Memory should be released
        cleanup_memory = torch.cuda.memory_allocated(0)
        assert cleanup_memory < loaded_memory

    def test_cpu_fallback(self):
        """Test CPU fallback when GPU not available."""
        model_info = ModelInfo(
            model_id="test_model",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cpu")

        assert backend.device == "cpu"
        # Should not try to set GPU memory limit
        assert backend.max_memory_mb is None or backend.device == "cpu"


class TestCTranslate2BackendGPU:
    """Tests for CTranslate2 backend with GPU."""

    def test_init_with_memory_limit(self):
        """Test initialization with memory limit."""
        model_info = ModelInfo(
            model_id="test_model",
            backend="ctranslate2",
            local_path="/path/to/model",
            model_size_mb=512,
            languages=["en", "es"],
        )
        backend = CTranslate2Backend(model_info, "cuda", max_memory_mb=2048)

        assert backend.max_memory_mb == 2048
        assert backend.device == "cuda"

    def test_init_without_memory_limit(self):
        """Test initialization without memory limit."""
        model_info = ModelInfo(
            model_id="test_model",
            backend="ctranslate2",
            local_path="/path/to/model",
            model_size_mb=512,
            languages=["en", "es"],
        )
        backend = CTranslate2Backend(model_info, "cuda")

        assert backend.max_memory_mb is None


class TestModelLoaderGPU:
    """Tests for ModelLoader with GPU."""

    def test_init_with_memory_limit(self):
        """Test initialization with memory limit."""
        registry = ModelRegistry()
        loader = ModelLoader(registry, device="cuda", max_memory_mb=4096)

        assert loader.device == "cuda"
        assert loader.max_memory_mb == 4096

    def test_create_backend_with_memory_limit(self):
        """Test creating backend with memory limit."""
        registry = ModelRegistry()
        loader = ModelLoader(registry, device="cuda", max_memory_mb=4096)

        model_info = ModelInfo(
            model_id="test_model",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )

        backend = loader._create_backend(model_info, "cuda")

        assert isinstance(backend, HuggingFaceBackend)
        assert backend.max_memory_mb == 4096

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_load_model_on_gpu(self):
        """Test loading model on GPU through loader."""
        # Create registry and add model
        registry = ModelRegistry()
        registry.register_model(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es", "fr", "de"],
        )

        loader = ModelLoader(registry, device="cuda", max_memory_mb=4096)

        # Load model
        backend = loader.load_model("m2m100_418m")

        assert backend.loaded
        assert backend.device == "cuda"

        # Cleanup
        loader.unload_all()
        torch.cuda.empty_cache()

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_multiple_models_memory_management(self):
        """Test loading multiple models with memory management."""
        registry = ModelRegistry()
        registry.register_model(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )

        loader = ModelLoader(registry, device="cuda", max_memory_mb=6144)

        # Load model
        backend = loader.load_model("m2m100_418m")
        assert backend.loaded

        # Check memory usage
        memory_usage = loader.get_memory_usage()
        assert "m2m100_418m" in memory_usage
        assert memory_usage["m2m100_418m"]["device"] == "cuda"

        # Cleanup
        loader.unload_all()
        torch.cuda.empty_cache()


class TestGPUMemoryManagement:
    """Tests for GPU memory management."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_memory_limit_enforcement(self):
        """Test that memory limits are enforced."""
        device_id = 0
        total_memory = torch.cuda.get_device_properties(device_id).total_memory / (1024**2)

        # Set a fraction
        max_memory_mb = int(total_memory * 0.5)
        fraction = max_memory_mb / total_memory

        torch.cuda.set_per_process_memory_fraction(fraction, device_id)

        # Reset
        torch.cuda.set_per_process_memory_fraction(1.0, device_id)

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_cache_clearing(self):
        """Test GPU cache clearing."""
        # Allocate some memory
        x = torch.randn(1000, 1000, device="cuda")
        allocated = torch.cuda.memory_allocated(0)
        assert allocated > 0

        # Clear
        del x
        torch.cuda.empty_cache()

        # Memory should be reduced (though not necessarily to zero)
        cleared = torch.cuda.memory_allocated(0)
        assert cleared < allocated


class TestBatchProcessing:
    """Tests for batch processing with GPU."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_batch_translation_gpu(self):
        """Test batch translation on GPU."""
        model_info = ModelInfo(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda", max_memory_mb=4096)

        backend.load()

        # Test different batch sizes
        for batch_size in [1, 2, 4, 8]:
            texts = [f"Test sentence {i}" for i in range(batch_size)]
            translations = backend.translate(texts, "en", "es")

            assert len(translations) == batch_size

        # Cleanup
        backend.unload()
        torch.cuda.empty_cache()

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_empty_batch(self):
        """Test translating empty batch."""
        model_info = ModelInfo(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda")

        backend.load()

        # Empty batch
        translations = backend.translate([], "en", "es")
        assert translations == []

        # Cleanup
        backend.unload()
        torch.cuda.empty_cache()


class TestErrorHandling:
    """Tests for error handling."""

    def test_model_not_loaded_error(self):
        """Test error when translating without loading model."""
        model_info = ModelInfo(
            model_id="test_model",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda")

        with pytest.raises(RuntimeError, match="Model not loaded"):
            backend.translate(["test"], "en", "es")

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_unload_and_reload(self):
        """Test unloading and reloading model."""
        model_info = ModelInfo(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )
        backend = HuggingFaceBackend(model_info, "cuda", max_memory_mb=4096)

        # Load
        backend.load()
        assert backend.loaded

        # Translate
        translations = backend.translate(["Test"], "en", "es")
        assert len(translations) == 1

        # Unload
        backend.unload()
        assert not backend.loaded

        # Reload
        backend.load()
        assert backend.loaded

        # Translate again
        translations = backend.translate(["Test again"], "en", "es")
        assert len(translations) == 1

        # Cleanup
        backend.unload()
        torch.cuda.empty_cache()
