from pathlib import Path
from types import SimpleNamespace

from src.workers.autonomous_content_translation_worker import (
    AutonomousContentTranslationWorker,
    AutonomousWorkerConfig,
)


def test_campaign_preflight_checks_manifest_content_drive(tmp_path, monkeypatch):
    config_root = tmp_path / "config"
    config_root.mkdir()
    content_repo = tmp_path / "content-checkout"
    content_repo.mkdir()
    worker = AutonomousContentTranslationWorker(
        AutonomousWorkerConfig(config_root=str(config_root), device="cpu")
    )
    worker.campaign = SimpleNamespace(content_repo=str(content_repo))
    observed = []

    def fake_disk_usage(path):
        observed.append(Path(path).resolve())
        return (100, 94, 6)

    monkeypatch.setattr("shutil.disk_usage", fake_disk_usage)

    assert worker._preflight_check() is True
    assert observed == [content_repo.resolve()]


def test_campaign_preflight_blocks_critical_manifest_content_drive(tmp_path, monkeypatch):
    config_root = tmp_path / "config"
    config_root.mkdir()
    content_repo = tmp_path / "content-checkout"
    content_repo.mkdir()
    worker = AutonomousContentTranslationWorker(
        AutonomousWorkerConfig(config_root=str(config_root), device="cpu")
    )
    worker.campaign = SimpleNamespace(content_repo=str(content_repo))
    monkeypatch.setattr("shutil.disk_usage", lambda _path: (100, 96, 4))

    assert worker._preflight_check() is False
