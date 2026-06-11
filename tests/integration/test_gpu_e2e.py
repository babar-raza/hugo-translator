"""
End-to-End GPU Pipeline Integration Tests.

Tests complete translation pipeline with GPU acceleration.
"""

import tempfile

import pytest
import torch

from src.hardware.gpu_manager import GPUManager
from src.model_runtime.loader import ModelLoader
from src.model_runtime.registry import ModelRegistry
from src.tm.l3_semantic import L3SemanticTM


class TestGPUPipelineIntegration:
    """End-to-end GPU pipeline tests."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_full_pipeline_gpu(self):
        """Test complete pipeline on GPU."""
        # 1. GPU Detection
        gpu_manager = GPUManager()
        caps = gpu_manager.detect()

        assert caps.has_cuda
        assert caps.device_count > 0

        device = gpu_manager.auto_select_device()
        assert device.startswith("cuda")

        # 2. L3 Semantic TM on GPU
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # Add TM entries
            tm.add_entry(
                entry_id="tm1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Hello world",
                translation="Hola mundo",
            )

            assert tm.device == "cuda"
            assert tm.count() == 1

            # Search
            matches = tm.semantic_search(
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                query_text="Hello",
                k=1,
                threshold=0.5,
            )

            assert len(matches) > 0

        # 3. Translation Model on GPU
        registry = ModelRegistry()
        registry.register_model(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )

        loader = ModelLoader(registry, device=device, max_memory_mb=4096)
        model = loader.load_model("m2m100_418m")

        assert model.loaded
        assert model.device.startswith("cuda")

        # Translate
        texts = ["Hello", "Goodbye"]
        translations = model.translate(texts, "en", "es")

        assert len(translations) == 2

        # Cleanup
        loader.unload_all()
        torch.cuda.empty_cache()

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_gpu_memory_monitoring(self):
        """Test GPU memory monitoring throughout pipeline."""
        gpu_manager = GPUManager()

        # Initial memory
        mem_initial = gpu_manager.get_gpu_memory(0)
        assert mem_initial is not None

        with tempfile.TemporaryDirectory() as tmpdir:
            # Create L3 TM
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            # Memory after L3
            mem_after_l3 = gpu_manager.get_gpu_memory(0)
            assert mem_after_l3.used_mb > mem_initial.used_mb

            # Cleanup
            del tm
            torch.cuda.empty_cache()

            mem_after_cleanup = gpu_manager.get_gpu_memory(0)
            # Memory should be reduced
            assert mem_after_cleanup.used_mb < mem_after_l3.used_mb

    def test_cpu_fallback_pipeline(self):
        """Test complete pipeline with CPU fallback."""
        # Force CPU mode
        gpu_manager = GPUManager({"enable_gpu": False})
        caps = gpu_manager.detect()

        device = caps.recommended_device
        assert device == "cpu"

        # L3 on CPU
        with tempfile.TemporaryDirectory() as tmpdir:
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=False,
            )

            assert tm.device == "cpu"

            tm.add_entry(
                entry_id="tm1",
                site_id="test_site",
                src_lang="en",
                tgt_lang="es",
                source_text="Test",
                translation="Prueba",
            )

            assert tm.count() == 1

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_batch_pipeline_gpu(self):
        """Test batch processing through full pipeline."""
        gpu_manager = GPUManager()
        device = gpu_manager.auto_select_device()

        with tempfile.TemporaryDirectory() as tmpdir:
            # Build TM with batch
            tm = L3SemanticTM(
                index_path=tmpdir,
                embedding_model="all-MiniLM-L6-v2",
                use_gpu=True,
            )

            entries = []
            for i in range(50):
                entries.append(
                    {
                        "entry_id": f"tm{i}",
                        "site_id": "test_site",
                        "src_lang": "en",
                        "tgt_lang": "es",
                        "source_text": f"Test sentence {i}",
                        "translation": f"Sentencia {i}",
                    }
                )

            count = tm.batch_add(entries)
            assert count == 50

            # Translate batch
            registry = ModelRegistry()
            registry.register_model(
                model_id="m2m100_418m",
                backend="huggingface",
                hf_model_id="facebook/m2m100_418M",
                model_size_mb=1024,
                languages=["en", "es"],
            )

            loader = ModelLoader(registry, device=device, max_memory_mb=4096)
            model = loader.load_model("m2m100_418m")

            texts = [f"Text {i}" for i in range(10)]
            translations = model.translate(texts, "en", "es")

            assert len(translations) == 10

            # Cleanup
            loader.unload_all()
            torch.cuda.empty_cache()


class TestGPUPerformanceIntegration:
    """Test performance with GPU acceleration."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    @pytest.mark.slow
    def test_gpu_faster_than_cpu(self):
        """Verify GPU is faster than CPU for translations."""
        import time

        registry = ModelRegistry()
        registry.register_model(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )

        texts = ["Test sentence"] * 8

        # GPU benchmark
        loader_gpu = ModelLoader(registry, device="cuda", max_memory_mb=4096)
        model_gpu = loader_gpu.load_model("m2m100_418m")

        # Warmup
        model_gpu.translate(texts[:2], "en", "es")

        start = time.perf_counter()
        translations_gpu = model_gpu.translate(texts, "en", "es")
        torch.cuda.synchronize()
        gpu_time = time.perf_counter() - start

        loader_gpu.unload_all()
        torch.cuda.empty_cache()

        # CPU benchmark
        loader_cpu = ModelLoader(registry, device="cpu")
        model_cpu = loader_cpu.load_model("m2m100_418m")

        # Warmup
        model_cpu.translate(texts[:2], "en", "es")

        start = time.perf_counter()
        translations_cpu = model_cpu.translate(texts, "en", "es")
        cpu_time = time.perf_counter() - start

        loader_cpu.unload_all()

        # GPU should be faster
        assert gpu_time < cpu_time
        speedup = cpu_time / gpu_time
        print(f"\nGPU Speedup: {speedup:.2f}x")

        # Verify translations are same length
        assert len(translations_gpu) == len(translations_cpu)


class TestGPUErrorHandling:
    """Test error handling in GPU pipeline."""

    @pytest.mark.skipif(
        not torch.cuda.is_available(),
        reason="CUDA not available",
    )
    def test_oom_recovery(self):
        """Test recovery from GPU OOM."""
        gpu_manager = GPUManager({"max_gpu_memory_mb": 512})  # Very low limit

        device = gpu_manager.auto_select_device()

        registry = ModelRegistry()
        registry.register_model(
            model_id="m2m100_418m",
            backend="huggingface",
            hf_model_id="facebook/m2m100_418M",
            model_size_mb=1024,
            languages=["en", "es"],
        )

        loader = ModelLoader(registry, device=device, max_memory_mb=512)

        # Loading might fail with low memory
        try:
            model = loader.load_model("m2m100_418m")
            # If it loads, try a huge batch that will fail
            texts = ["Test"] * 1000
            try:
                model.translate(texts, "en", "es")
            except RuntimeError as e:
                assert "memory" in str(e).lower() or "OOM" in str(e)
        except RuntimeError as e:
            # Expected to fail with low memory
            assert "memory" in str(e).lower() or "OOM" in str(e)
        finally:
            loader.unload_all()
            torch.cuda.empty_cache()
            # Reset memory fraction
            torch.cuda.set_per_process_memory_fraction(1.0, 0)
