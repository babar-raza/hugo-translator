"""TC-APT-030 regression (G-19): the legacy mtime-only SweepScheduler path is retired.

Mission aspose-org-full-portfolio-translation-20260901.  ``SweepScheduler._needs_translation``
decides from ``st_mtime`` and enqueues ungoverned jobs -- a fourth execution path with a
weaker acceptance bar than ``campaign_runner.py`` under zero-defect.  It must not be
constructible without the explicit forensic override, and the orchestrator must not
enable it by default.
"""

from __future__ import annotations

import inspect
from unittest.mock import Mock

import pytest

from src.orchestrator.orchestrator import TranslationOrchestrator
from src.orchestrator.scheduler import SweepScheduler
from src.utils.deprecated_execution_guard import OVERRIDE_ENV, DeprecatedExecutionPathError


def test_sweep_scheduler_refuses_construction_without_override(monkeypatch):
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    with pytest.raises(DeprecatedExecutionPathError):
        SweepScheduler(config_service=Mock(), job_enqueue_callback=Mock())


def test_sweep_scheduler_constructs_only_under_exact_override(monkeypatch):
    monkeypatch.setenv(OVERRIDE_ENV, "unified_translate")  # wrong path's override
    with pytest.raises(DeprecatedExecutionPathError):
        SweepScheduler(config_service=Mock(), job_enqueue_callback=Mock())
    monkeypatch.setenv(OVERRIDE_ENV, "sweep_scheduler")
    sched = SweepScheduler(config_service=Mock(), job_enqueue_callback=Mock())
    assert not sched.is_running()


def test_orchestrator_does_not_enable_sweeps_by_default():
    sig = inspect.signature(TranslationOrchestrator.__init__)
    assert sig.parameters["enable_sweep_scheduler"].default is False


def test_orchestrator_default_construction_has_no_scheduler(monkeypatch):
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    orch = TranslationOrchestrator(config_service=Mock(), enable_file_watcher=False)
    assert orch.scheduler is None


def test_orchestrator_opting_into_sweeps_still_hits_the_guard(monkeypatch):
    monkeypatch.delenv(OVERRIDE_ENV, raising=False)
    with pytest.raises(DeprecatedExecutionPathError):
        TranslationOrchestrator(
            config_service=Mock(), enable_file_watcher=False, enable_sweep_scheduler=True
        )
