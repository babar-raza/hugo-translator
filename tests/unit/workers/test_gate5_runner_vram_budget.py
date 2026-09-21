"""TC-APT-047: the Gate-5 runner's per-process VRAM budget must actually reach ModelLoader.

The budget is resolved lazily inside ``build_real_engine``, so a wrong import or a
dropped argument stays invisible until a real GPU shard runs.  These tests pin both
ends: the enforcer is imported from the module that defines it, and the resolved MB
value is handed to ``ModelLoader`` as ``max_memory_mb``.

The stubs are classes, not lambdas, on purpose: several modules evaluate
``ConfigService | None`` style annotations at import time, which a function object
cannot satisfy.
"""

from pathlib import Path
from types import SimpleNamespace

import pytest

import scripts.campaign.run_gate5_batch as runner

REPO_ROOT = Path(__file__).resolve().parents[3]


class _RecordingLoader:
    last_kwargs: dict = {}

    def __init__(self, registry, device="cpu", max_memory_mb=None, load_mode=None, config=None):
        type(self).last_kwargs = {"device": device, "max_memory_mb": max_memory_mb}


class _Stub:
    def __init__(self, *args, **kwargs):
        pass


class _RecordingTM(_Stub):
    last_kwargs: dict = {}

    def __init__(self, *args, **kwargs):
        type(self).last_kwargs = kwargs


@pytest.fixture
def recording_loader(monkeypatch):
    _RecordingLoader.last_kwargs = {}
    monkeypatch.setattr("src.model_runtime.loader.ModelLoader", _RecordingLoader)
    monkeypatch.setattr("src.model_runtime.registry.ModelRegistry", _Stub)
    monkeypatch.setattr("src.tm.l1_cache.L1Cache", _Stub)
    monkeypatch.setattr("src.tm.l2_persistent.L2PersistentTM", _Stub)
    monkeypatch.setattr("src.tm.TranslationMemory", _RecordingTM)
    monkeypatch.setattr("src.translation_engine.engine.TranslationEngine", _Stub)
    return _RecordingLoader


def _force_cuda(monkeypatch, available: bool):
    monkeypatch.setattr("torch.cuda.is_available", lambda: available)


def test_gpu_percent_is_resolved_to_max_memory_mb(recording_loader, monkeypatch):
    _force_cuda(monkeypatch, True)
    monkeypatch.setattr(
        "src.hardware.vram_enforcer.VRAMEnforcer.enforce_from_config",
        lambda self, hardware_config, device="cuda:0": (
            13100,
            SimpleNamespace(percent=float(hardware_config["max_gpu_memory_percent"])),
        ),
    )

    runner.build_real_engine(REPO_ROOT, max_gpu_memory_percent=80)

    assert recording_loader.last_kwargs["device"] == "cuda"
    assert recording_loader.last_kwargs["max_memory_mb"] == 13100


def test_no_percent_leaves_the_config_default_in_charge(recording_loader, monkeypatch):
    _force_cuda(monkeypatch, True)

    runner.build_real_engine(REPO_ROOT)

    assert recording_loader.last_kwargs["max_memory_mb"] is None


def test_percent_is_ignored_without_cuda(recording_loader, monkeypatch):
    _force_cuda(monkeypatch, False)

    runner.build_real_engine(REPO_ROOT, max_gpu_memory_percent=80)

    assert recording_loader.last_kwargs["device"] == "cpu"
    assert recording_loader.last_kwargs["max_memory_mb"] is None


def test_vram_enforcer_lives_where_the_runner_imports_it_from():
    """Guards the exact import that was wrong on first write (vram_budget, not _enforcer)."""
    from src.hardware.vram_enforcer import VRAMEnforcer

    assert hasattr(VRAMEnforcer(), "enforce_from_config")


def test_campaign_spool_prevents_direct_tm_writes(recording_loader, monkeypatch, tmp_path):
    _force_cuda(monkeypatch, False)
    spool_path = tmp_path / "campaign-intents.sqlite3"

    runner.build_real_engine(REPO_ROOT, tm_intent_spool_path=spool_path)

    assert _RecordingTM.last_kwargs["intent_spool"].path == spool_path
    assert spool_path.is_file()
