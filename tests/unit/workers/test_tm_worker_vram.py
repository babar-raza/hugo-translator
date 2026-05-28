"""
Unit tests for TMImprovementWorker._offload_resources() VRAM lifecycle method.

Tests exercise:
  - LLM client unload signalling
  - L3 FAISS offload signalling
  - Resilience to exceptions in both paths
  - gc.collect() and torch.cuda.empty_cache() invocations

No real CUDA, Ollama, or FAISS is required — all dependencies are MagicMock.
"""

import sys
import types
import unittest
from unittest.mock import MagicMock, patch


# ---------------------------------------------------------------------------
# Stub heavy optional dependencies before the worker module is imported
# ---------------------------------------------------------------------------
def _ensure_stubs():
    stubs = {
        "ctranslate2": types.ModuleType("ctranslate2"),
        "faiss": types.ModuleType("faiss"),
        "lmdb": types.ModuleType("lmdb"),
        "pytz": types.ModuleType("pytz"),
    }
    if "sentence_transformers" not in sys.modules:
        stubs["sentence_transformers"] = types.ModuleType("sentence_transformers")

    for name, mod in stubs.items():
        if name not in sys.modules:
            sys.modules[name] = mod

    if "torch" not in sys.modules:
        torch_stub = types.ModuleType("torch")
        cuda_stub = types.ModuleType("torch.cuda")
        cuda_stub.is_available = MagicMock(return_value=True)
        cuda_stub.empty_cache = MagicMock()
        torch_stub.cuda = cuda_stub
        sys.modules["torch"] = torch_stub
        sys.modules["torch.cuda"] = cuda_stub


_ensure_stubs()


def _make_worker(*, llm_client=None, l3=None):
    """
    Build a minimal TMImprovementWorker with only the attributes used by
    _offload_resources().

    llm_client  — MagicMock or None
    l3          — MagicMock or None (placed on worker.tm.l3)
    """
    from src.workers.tm_improvement_worker import TMImprovementWorker

    worker = TMImprovementWorker.__new__(TMImprovementWorker)

    # Attributes used by _offload_resources()
    worker.llm_client = llm_client
    worker._worker_id = "tm_worker"

    # tm is either None or an object with a .l3 attribute
    if l3 is not None:
        worker.tm = MagicMock()
        worker.tm.l3 = l3
    else:
        worker.tm = MagicMock()
        worker.tm.l3 = None

    # config referenced by logging inside _offload_resources
    worker.config = MagicMock()
    worker.config.llm_model = "qwen3:14b"

    return worker


class TestOffloadResourcesLlmClient(unittest.TestCase):
    """Tests for the LLM-client branch of _offload_resources()."""

    def test_calls_unload_from_server_when_llm_client_set(self):
        """Must call llm_client.unload_from_server() when llm_client is not None."""
        llm = MagicMock()
        worker = _make_worker(llm_client=llm)

        with patch("gc.collect"):
            worker._offload_resources()

        llm.unload_from_server.assert_called_once()

    def test_skips_unload_when_llm_client_is_none(self):
        """Must not crash and must skip the call when llm_client is None."""
        worker = _make_worker(llm_client=None)

        with patch("gc.collect"):
            worker._offload_resources()  # should not raise

    def test_resilient_to_unload_from_server_exception(self):
        """Must continue executing (not propagate) when unload_from_server() raises."""
        llm = MagicMock()
        llm.unload_from_server.side_effect = RuntimeError("Ollama connection refused")
        worker = _make_worker(llm_client=llm)

        with patch("gc.collect"):
            try:
                worker._offload_resources()
            except Exception as exc:
                self.fail(f"_offload_resources() raised unexpectedly: {exc!r}")


class TestOffloadResourcesL3(unittest.TestCase):
    """Tests for the L3 FAISS branch of _offload_resources()."""

    def test_calls_offload_to_cpu_on_l3(self):
        """Must call l3.offload_to_cpu() when l3 has that method."""
        l3 = MagicMock()
        l3.offload_to_cpu = MagicMock()
        worker = _make_worker(l3=l3)

        with patch("gc.collect"):
            worker._offload_resources()

        l3.offload_to_cpu.assert_called_once()

    def test_skips_l3_offload_when_l3_is_none(self):
        """Must not crash when tm.l3 is None."""
        worker = _make_worker(l3=None)

        with patch("gc.collect"):
            worker._offload_resources()  # should not raise

    def test_resilient_to_l3_offload_exception(self):
        """Must not propagate exception raised by l3.offload_to_cpu()."""
        l3 = MagicMock()
        l3.offload_to_cpu.side_effect = RuntimeError("FAISS internal error")
        worker = _make_worker(l3=l3)

        with patch("gc.collect"):
            try:
                worker._offload_resources()
            except Exception as exc:
                self.fail(f"_offload_resources() raised unexpectedly: {exc!r}")

    def test_skips_offload_when_l3_has_no_method(self):
        """Must not crash when tm.l3 exists but lacks offload_to_cpu."""
        l3_no_method = MagicMock(spec=[])  # no attributes at all
        worker = _make_worker(l3=l3_no_method)

        with patch("gc.collect"):
            worker._offload_resources()  # should not raise


class TestOffloadResourcesCudaFlush(unittest.TestCase):
    """Tests for the CUDA cache-flush tail of _offload_resources()."""

    def test_calls_gc_collect(self):
        """Must call gc.collect() to release Python-side references."""
        worker = _make_worker()

        with patch("gc.collect") as mock_gc:
            worker._offload_resources()

        mock_gc.assert_called()

    def test_calls_empty_cache_when_cuda_available(self):
        """Must call torch.cuda.empty_cache() when CUDA is available."""
        worker = _make_worker()
        empty_cache_mock = MagicMock()
        with patch("gc.collect"), \
             patch("torch.cuda.is_available", return_value=True), \
             patch("torch.cuda.empty_cache", empty_cache_mock):
            worker._offload_resources()
        empty_cache_mock.assert_called_once()

    def test_does_not_crash_when_torch_absent(self):
        """Must silently pass when torch is not installed (ImportError path)."""
        worker = _make_worker()
        with patch("gc.collect"), \
             patch.dict(sys.modules, {"torch": None}):
            worker._offload_resources()  # should not raise


if __name__ == "__main__":
    unittest.main()
