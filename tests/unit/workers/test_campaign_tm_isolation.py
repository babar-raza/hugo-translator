from pathlib import Path
from types import SimpleNamespace

import pytest

from src.workers.autonomous_content_translation_worker import (
    AutonomousContentTranslationWorker,
)


def test_non_campaign_worker_uses_configured_l3_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = AutonomousContentTranslationWorker._l3_index_path(Path("custom-tm"), None)

    assert result == Path("custom-tm") / "l3_faiss"


def test_campaign_worker_uses_isolated_namespaced_l3_path(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    result = AutonomousContentTranslationWorker._l3_index_path(
        Path("data/tm"), SimpleNamespace(campaign_id="pilot-v1")
    )

    assert result == (tmp_path / "data" / "campaigns" / "pilot-v1" / "tm" / "l3_faiss").resolve()
    assert result != (tmp_path / "data" / "tm" / "l3_faiss").resolve()


def test_campaign_l3_path_rejects_traversal(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)

    with pytest.raises(ValueError, match="escapes"):
        AutonomousContentTranslationWorker._l3_index_path(
            Path("data/tm"), SimpleNamespace(campaign_id="../../outside")
        )


def test_campaign_l3_flushes_each_accepted_addition():
    campaign = SimpleNamespace(campaign_id="pilot-v1")

    assert AutonomousContentTranslationWorker._l3_save_interval(campaign) == 1
    assert AutonomousContentTranslationWorker._l3_save_interval(None) == 100
