"""
Unit tests for CTranslate2Backend.unload() VRAM lifecycle changes.

Verifies that after calling unload():
  - translator and tokenizer attributes are set to None
  - gc.collect() is called
  - torch.cuda.empty_cache() is called when device=='cuda' and CUDA is available
"""

import gc
import sys
import types
import unittest
from unittest.mock import MagicMock, patch, call


def _make_model_info():
    """Return a minimal ModelInfo-like object sufficient for CTranslate2Backend."""
    info = MagicMock()
    info.model_id = "test-model"
    info.local_path = None
    info.hf_model_id = "test-hf-model"
    return info


def _build_backend(device: str):
    """Instantiate CTranslate2Backend without importing real ctranslate2 / transformers."""
    # Stub heavy optional dependencies before importing loader
    for mod in ("ctranslate2", "transformers", "sentencepiece"):
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    from src.model_runtime.loader import CTranslate2Backend

    backend = CTranslate2Backend.__new__(CTranslate2Backend)
    # Manually initialise the attributes set by __init__
    backend.model_info = _make_model_info()
    backend.device = device
    backend.translator = MagicMock(name="translator")
    backend.tokenizer = MagicMock(name="tokenizer")
    backend.loaded = True
    backend.max_memory_mb = None
    return backend


class TestCTranslate2BackendUnload(unittest.TestCase):
    """Tests for CTranslate2Backend.unload()."""

    # ------------------------------------------------------------------
    # Helper: build a stubbed torch module
    # ------------------------------------------------------------------
    @staticmethod
    def _make_torch_stub(cuda_available: bool):
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=cuda_available)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        return torch_stub

    # ------------------------------------------------------------------
    # Tests
    # ------------------------------------------------------------------
    def test_unload_clears_translator_and_tokenizer(self):
        """unload() must set translator and tokenizer to None."""
        backend = _build_backend("cuda")
        torch_stub = self._make_torch_stub(cuda_available=True)

        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch("src.model_runtime.loader.torch", torch_stub):
                backend.unload()

        self.assertIsNone(backend.translator, "translator should be None after unload()")
        self.assertIsNone(backend.tokenizer, "tokenizer should be None after unload()")

    def test_unload_calls_gc_collect(self):
        """unload() must call gc.collect()."""
        backend = _build_backend("cuda")
        torch_stub = self._make_torch_stub(cuda_available=True)

        with patch("gc.collect") as mock_gc:
            with patch.dict(sys.modules, {"torch": torch_stub}):
                with patch("src.model_runtime.loader.torch", torch_stub):
                    backend.unload()

        mock_gc.assert_called_once()

    def test_unload_calls_empty_cache_when_cuda_available(self):
        """unload() must call torch.cuda.empty_cache() when device=='cuda' and CUDA available."""
        backend = _build_backend("cuda")
        torch_stub = self._make_torch_stub(cuda_available=True)

        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch("src.model_runtime.loader.torch", torch_stub):
                backend.unload()

        torch_stub.cuda.is_available.assert_called()
        torch_stub.cuda.empty_cache.assert_called_once()

    def test_unload_skips_empty_cache_when_cuda_unavailable(self):
        """unload() must NOT call torch.cuda.empty_cache() when CUDA is unavailable."""
        backend = _build_backend("cuda")
        torch_stub = self._make_torch_stub(cuda_available=False)

        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch("src.model_runtime.loader.torch", torch_stub):
                backend.unload()

        torch_stub.cuda.empty_cache.assert_not_called()

    def test_unload_skips_empty_cache_for_cpu_device(self):
        """unload() must NOT call torch.cuda.empty_cache() when device is 'cpu'."""
        backend = _build_backend("cpu")
        torch_stub = self._make_torch_stub(cuda_available=True)

        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch("src.model_runtime.loader.torch", torch_stub):
                backend.unload()

        torch_stub.cuda.empty_cache.assert_not_called()

    def test_unload_sets_loaded_false(self):
        """unload() must set self.loaded to False."""
        backend = _build_backend("cuda")
        torch_stub = self._make_torch_stub(cuda_available=True)

        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch("src.model_runtime.loader.torch", torch_stub):
                backend.unload()

        self.assertFalse(backend.loaded, "loaded flag should be False after unload()")

    def test_unload_handles_none_translator_gracefully(self):
        """unload() must not crash when translator is already None."""
        backend = _build_backend("cuda")
        backend.translator = None
        torch_stub = self._make_torch_stub(cuda_available=True)

        with patch.dict(sys.modules, {"torch": torch_stub}):
            with patch("src.model_runtime.loader.torch", torch_stub):
                try:
                    backend.unload()
                except Exception as exc:
                    self.fail(f"unload() raised {exc!r} with translator=None")


if __name__ == "__main__":
    unittest.main()
