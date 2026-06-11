"""
Unit tests for L3SemanticTM.offload_to_cpu() and reload_to_gpu() VRAM lifecycle methods.

All heavy dependencies (faiss, sentence_transformers, torch) are mocked so tests
run without any GPU or ML packages installed.

Patching strategy:
- faiss is imported at module level in l3_semantic.py -> patch src.tm.l3_semantic.faiss
- torch is imported locally inside methods -> intercepted via sys.modules patch
"""

import sys
import threading
import types
import unittest
from unittest.mock import MagicMock, patch

_faiss_stub = types.ModuleType("faiss")
_faiss_stub.IndexFlatL2 = MagicMock()
_faiss_stub.index_gpu_to_cpu = MagicMock(side_effect=lambda idx: MagicMock(name="cpu_index"))
_faiss_stub.index_cpu_to_gpu = MagicMock(
    side_effect=lambda res, dev, idx: MagicMock(name="gpu_index")
)
_faiss_stub.StandardGpuResources = MagicMock(return_value=MagicMock(name="gpu_res"))

_torch_stub = types.ModuleType("torch")
_cuda_stub = types.ModuleType("torch.cuda")
_cuda_stub.is_available = MagicMock(return_value=True)
_cuda_stub.empty_cache = MagicMock()
_torch_stub.cuda = _cuda_stub

_st_stub = types.ModuleType("sentence_transformers")
_st_stub.SentenceTransformer = MagicMock()

for _name, _mod in [
    ("faiss", _faiss_stub),
    ("torch", _torch_stub),
    ("torch.cuda", _cuda_stub),
    ("sentence_transformers", _st_stub),
    ("numpy", types.ModuleType("numpy")),
]:
    sys.modules[_name] = _mod


def _make_l3(*, use_faiss_gpu=True, device="cuda"):
    from src.tm.l3_semantic import L3SemanticTM

    obj = L3SemanticTM.__new__(L3SemanticTM)
    obj.use_faiss_gpu = use_faiss_gpu
    obj.device = device
    obj.index = MagicMock(name="faiss_index")
    obj.encoder = MagicMock(name="encoder")
    obj._index_on_gpu = use_faiss_gpu
    obj._encoder_on_gpu = device == "cuda"
    obj._lock = threading.Lock()
    return obj


class TestOffloadToCpu(unittest.TestCase):
    def _run_offload(self, obj):
        with patch("src.tm.l3_semantic.faiss", _faiss_stub):
            with patch.dict(sys.modules, {"torch": _torch_stub, "torch.cuda": _cuda_stub}):
                obj.offload_to_cpu()

    def test_offload_calls_index_gpu_to_cpu_when_use_faiss_gpu(self):
        obj = _make_l3(use_faiss_gpu=True, device="cuda")
        _faiss_stub.index_gpu_to_cpu.reset_mock()
        self._run_offload(obj)
        _faiss_stub.index_gpu_to_cpu.assert_called_once()

    def test_offload_moves_encoder_to_cpu_when_device_is_cuda(self):
        obj = _make_l3(use_faiss_gpu=False, device="cuda")
        self._run_offload(obj)
        obj.encoder.to.assert_called_with("cpu")

    def test_offload_sets_index_on_gpu_false_after_faiss_move(self):
        obj = _make_l3(use_faiss_gpu=True, device="cuda")
        _faiss_stub.index_gpu_to_cpu.reset_mock()
        self._run_offload(obj)
        self.assertFalse(obj._index_on_gpu)

    def test_offload_sets_encoder_on_gpu_false_after_encoder_move(self):
        obj = _make_l3(use_faiss_gpu=False, device="cuda")
        self._run_offload(obj)
        self.assertFalse(obj._encoder_on_gpu)

    def test_offload_noop_when_device_is_cpu_and_no_faiss_gpu(self):
        obj = _make_l3(use_faiss_gpu=False, device="cpu")
        _faiss_stub.index_gpu_to_cpu.reset_mock()
        obj.encoder.to.reset_mock()
        self._run_offload(obj)
        _faiss_stub.index_gpu_to_cpu.assert_not_called()
        obj.encoder.to.assert_not_called()

    def test_offload_skips_index_when_index_is_none(self):
        obj = _make_l3(use_faiss_gpu=True, device="cuda")
        obj.index = None
        _faiss_stub.index_gpu_to_cpu.reset_mock()
        self._run_offload(obj)
        _faiss_stub.index_gpu_to_cpu.assert_not_called()


class TestReloadToGpu(unittest.TestCase):
    def _run_reload(self, obj):
        with patch("src.tm.l3_semantic.faiss", _faiss_stub):
            with patch.dict(sys.modules, {"torch": _torch_stub, "torch.cuda": _cuda_stub}):
                obj.reload_to_gpu()

    def test_reload_calls_index_cpu_to_gpu_when_offloaded(self):
        obj = _make_l3(use_faiss_gpu=True, device="cuda")
        obj._index_on_gpu = False
        _faiss_stub.index_cpu_to_gpu.reset_mock()
        self._run_reload(obj)
        _faiss_stub.index_cpu_to_gpu.assert_called_once()

    def test_reload_moves_encoder_to_cuda_when_offloaded(self):
        obj = _make_l3(use_faiss_gpu=False, device="cuda")
        obj._encoder_on_gpu = False
        self._run_reload(obj)
        obj.encoder.to.assert_called_with("cuda")

    def test_reload_sets_index_on_gpu_true_after_faiss_move(self):
        obj = _make_l3(use_faiss_gpu=True, device="cuda")
        obj._index_on_gpu = False
        _faiss_stub.index_cpu_to_gpu.reset_mock()
        self._run_reload(obj)
        self.assertTrue(obj._index_on_gpu)

    def test_reload_sets_encoder_on_gpu_true_after_encoder_move(self):
        obj = _make_l3(use_faiss_gpu=False, device="cuda")
        obj._encoder_on_gpu = False
        self._run_reload(obj)
        self.assertTrue(obj._encoder_on_gpu)

    def test_reload_noop_when_already_on_gpu(self):
        obj = _make_l3(use_faiss_gpu=True, device="cuda")
        obj._index_on_gpu = True
        obj._encoder_on_gpu = True
        _faiss_stub.index_cpu_to_gpu.reset_mock()
        obj.encoder.to.reset_mock()
        self._run_reload(obj)
        _faiss_stub.index_cpu_to_gpu.assert_not_called()
        obj.encoder.to.assert_not_called()

    def test_reload_skips_faiss_when_use_faiss_gpu_false(self):
        obj = _make_l3(use_faiss_gpu=False, device="cuda")
        obj._index_on_gpu = False
        _faiss_stub.index_cpu_to_gpu.reset_mock()
        self._run_reload(obj)
        _faiss_stub.index_cpu_to_gpu.assert_not_called()


if __name__ == "__main__":
    unittest.main()
