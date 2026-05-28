"""
Unit tests for AutonomousContentTranslationWorker._offload_models() VRAM lifecycle method.

Tests run without real CUDA, ML models, or filesystem side-effects by using MagicMock
for all dependencies.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub heavy optional dependencies ONLY — do NOT stub stdlib modules like
# zoneinfo, as that breaks pydantic on Python 3.13.
# ---------------------------------------------------------------------------
def _ensure_stubs():
    mods_to_stub = [
        "ctranslate2",
        "transformers",
        "sentence_transformers",
        "faiss",
        "lmdb",
        "pytz",
    ]
    for mod in mods_to_stub:
        if mod not in sys.modules:
            sys.modules[mod] = types.ModuleType(mod)

    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=True)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        sys.modules["torch"] = torch_stub
        sys.modules["torch.cuda"] = cuda_stub


_ensure_stubs()


def _make_worker():
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )
    worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    worker.translation_engine = None
    worker._worker_id = "content_worker"
    return worker


class TestOffloadModelsNoEngine(unittest.TestCase):

    def test_noop_when_translation_engine_is_none(self):
        """Must return early without error when translation_engine is None."""
        worker = _make_worker()
        worker.translation_engine = None
        worker._offload_models()  # must not raise

    def test_noop_when_model_loader_is_none(self):
        """Must return early when engine exists but model_loader is None."""
        worker = _make_worker()
        worker.translation_engine = MagicMock()
        worker.translation_engine.model_loader = None
        worker._offload_models()  # must not raise

    def test_noop_when_loaded_models_is_empty(self):
        """Must return early without calling unload_all() when no models are loaded."""
        worker = _make_worker()
        engine = MagicMock()
        engine.model_loader.loaded_models = {}
        worker.translation_engine = engine
        worker._offload_models()
        engine.model_loader.unload_all.assert_not_called()


class TestOffloadModelsWithLoadedModels(unittest.TestCase):

    def _make_worker_with_models(self, model_keys=("m2m100",)):
        worker = _make_worker()
        engine = MagicMock()
        engine.model_loader.loaded_models = {k: MagicMock() for k in model_keys}
        worker.translation_engine = engine
        return worker

    def test_calls_unload_all_when_models_are_loaded(self):
        """Must call model_loader.unload_all() when models are present."""
        worker = self._make_worker_with_models(["m2m100", "nllb"])
        with patch("gc.collect"):
            worker._offload_models()
        worker.translation_engine.model_loader.unload_all.assert_called_once()

    def test_calls_gc_collect_after_unload(self):
        """Must call gc.collect() after unloading models."""
        worker = self._make_worker_with_models()
        with patch("gc.collect") as mock_gc:
            worker._offload_models()
        mock_gc.assert_called()

    def test_calls_empty_cache_when_cuda_available(self):
        """Must call torch.cuda.empty_cache() when CUDA is available."""
        worker = self._make_worker_with_models()
        empty_cache_mock = MagicMock()
        with patch("gc.collect"), \
             patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.empty_cache", empty_cache_mock):
            worker._offload_models()
        empty_cache_mock.assert_called_once()

    def test_does_not_crash_when_torch_import_fails(self):
        """Must not raise even if torch is unavailable (ImportError is silenced)."""
        worker = self._make_worker_with_models()
        with patch("gc.collect"), \
             patch.dict(sys.modules, {"torch": None}):
            worker._offload_models()  # should not raise

    def test_empty_cache_not_called_when_cuda_unavailable(self):
        """Must not call empty_cache() when CUDA is unavailable."""
        worker = self._make_worker_with_models()
        empty_cache_mock = MagicMock()
        with patch("gc.collect"), \
             patch("torch.cuda.is_available", return_value=False), \
             patch("torch.cuda.empty_cache", empty_cache_mock):
            worker._offload_models()
        empty_cache_mock.assert_not_called()


if __name__ == "__main__":
    unittest.main()
