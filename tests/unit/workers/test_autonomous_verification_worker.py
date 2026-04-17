"""
Unit tests for autonomous verification worker.
"""

import json
from pathlib import Path
from unittest.mock import patch

import pytest

from src.workers.autonomous_verification_worker import (
    AutonomousVerificationWorker,
    AutonomousVerificationWorkerConfig,
)


def test_oneshot_success_writes_durable_state(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Successful oneshot run should produce state and success provenance."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config" / "site_profiles").mkdir(parents=True)
    (tmp_path / "config" / "site_profiles" / "site-a.yaml").write_text("site: a\n", encoding="utf-8")

    worker = AutonomousVerificationWorker(
        AutonomousVerificationWorkerConfig(
            config_root="config",
            mode="oneshot",
        )
    )

    with patch("src.workers.autonomous_verification_worker.start_worker_run", return_value="evt-1"), patch(
        "src.workers.autonomous_verification_worker.complete_worker_run", return_value=True
    ), patch("src.workers.autonomous_verification_worker.emit_worker_event", return_value="evt-2"):
        worker.setup()
        worker.run()

    state_path = tmp_path / "data" / "logs" / "verification_worker.state.json"
    assert state_path.exists()
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["worker_id"] == "verification_worker"
    assert payload["log_path"] == "data/logs/verification_worker.log"
    assert payload["last_success_ts"]
    assert payload["state"] == "stopped"


def test_oneshot_failure_sets_last_error_without_success(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """Failed verification pass should set error provenance and no success timestamp."""
    monkeypatch.chdir(tmp_path)
    (tmp_path / "config").mkdir(parents=True)

    worker = AutonomousVerificationWorker(
        AutonomousVerificationWorkerConfig(
            config_root="config",
            mode="oneshot",
        )
    )

    with patch("src.workers.autonomous_verification_worker.start_worker_run", return_value="evt-1"), patch(
        "src.workers.autonomous_verification_worker.complete_worker_run", return_value=True
    ), patch("src.workers.autonomous_verification_worker.emit_worker_event", return_value="evt-2"):
        worker.setup()
        with pytest.raises(RuntimeError, match="Verification checks failed"):
            worker.run()

    state_path = tmp_path / "data" / "logs" / "verification_worker.state.json"
    payload = json.loads(state_path.read_text(encoding="utf-8"))
    assert payload["state"] == "stopped"
    assert payload["last_error_ts"]
    assert "last_success_ts" not in payload
