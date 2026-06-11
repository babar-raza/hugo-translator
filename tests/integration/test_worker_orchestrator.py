"""Integration tests for the worker orchestrator trigger-to-launch flow.

All tests use mocked subprocess — no real workers are launched.
"""

import json
import os
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest


# All integration tests mock out PID liveness to avoid interference from
# real worker PID files on the developer's machine.
@pytest.fixture(autouse=True)
def _mock_pid_alive():
    """Prevent real PID files from interfering with trigger tests."""
    with patch("src.workers.worker_orchestrator.worker_pid_alive", return_value=False):
        yield


def _make_state(**overrides):
    state = {
        "last_check_time": time.time() - 600,
        "last_launch": {},
        "launch_history": [],
        "recently_completed_workers": [],
        "running_count": {},
    }
    state.update(overrides)
    return state


def _base_registry(tmp_path, **worker_overrides):
    """Return a minimal registry dict with one worker per type."""
    q_empty = tmp_path / "empty.jsonl"
    q_empty.write_text("", encoding="utf-8")

    defaults = {
        "content_worker": {
            "enabled": True,
            "mode": "oneshot",
            "module": "src.workers.autonomous_content_translation_worker",
            "cli_args": ["--mode", "oneshot"],
            "trigger": {"type": "queue_non_empty", "queue_path": str(q_empty)},
            "cooldown_seconds": 0,
            "max_concurrent": 1,
            "safe_command": ".venv/Scripts/python.exe -m src.workers.test --mode oneshot",
            "useful_work_criteria": "translated_files > 0",
        },
        "tm_improvement_worker": {
            "enabled": True,
            "mode": "oneshot",
            "module": "src.workers.tm_improvement_worker",
            "cli_args": ["--mode", "oneshot"],
            "trigger": {"type": "queue_non_empty", "queue_path": str(q_empty)},
            "cooldown_seconds": 0,
            "max_concurrent": 1,
            "safe_command": ".venv/Scripts/python.exe -m src.workers.test --mode oneshot",
            "useful_work_criteria": "improved_count > 0",
        },
        "verification_worker": {
            "enabled": True,
            "mode": "oneshot",
            "module": "src.workers.autonomous_verification_worker",
            "cli_args": ["--mode", "oneshot"],
            "trigger": {
                "type": "file_change",
                "paths": [str(tmp_path / "config")],
                "pattern": "*.yaml",
            },
            "cooldown_seconds": 0,
            "max_concurrent": 1,
            "safe_command": ".venv/Scripts/python.exe -m src.workers.test --mode oneshot",
            "useful_work_criteria": "config validated",
        },
    }

    for name, overrides in worker_overrides.items():
        if name in defaults:
            defaults[name].update(overrides)

    return {"workers": defaults}


class TestEmptyQueuesNoLaunch:
    """Scenario 1: Empty queues and no file changes -> no worker launched."""

    def test_no_workers_launched(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        registry = _base_registry(tmp_path)
        state = _make_state()
        launched = run_check_cycle(registry, state, dry_run=True)
        assert launched == []


class TestNonEmptyImprovementQueue:
    """Scenario 2: Non-empty improvement_queue.jsonl -> TM worker launched."""

    def test_tm_worker_triggered(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "improvement_queue.jsonl"
        q.write_text('{"candidate": "test"}\n', encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={"trigger": {"type": "queue_non_empty", "queue_path": str(q)}},
        )
        state = _make_state()
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "tm_improvement_worker" in launched


class TestConfigChangedTriggersVerification:
    """Scenario 3: Config file modified -> verification worker launched."""

    def test_verification_triggered_on_config_change(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        config_dir = tmp_path / "config"
        config_dir.mkdir()
        (config_dir / "global.yaml").write_text("key: val", encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            verification_worker={
                "trigger": {"type": "file_change", "paths": [str(config_dir)], "pattern": "*.yaml"},
            },
        )
        state = _make_state(last_check_time=time.time() - 100)
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "verification_worker" in launched


class TestCampaignSentinelBlocks:
    """Scenario 4: Campaign sentinel active -> content worker not launched."""

    def test_content_worker_blocked_by_sentinel(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        sentinel = tmp_path / "campaign_disabled"
        sentinel.write_text("", encoding="utf-8")

        q = tmp_path / "retranslate.jsonl"
        q.write_text('{"file": "test.md"}\n', encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            content_worker={
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "campaign_sentinel": str(sentinel),
            },
        )
        state = _make_state()
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "content_worker" not in launched


class TestCooldownBlocks:
    """Scenario 5: Cooldown not elapsed -> worker not re-launched."""

    def test_worker_blocked_by_cooldown(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x": 1}\n', encoding="utf-8")

        now = time.time()
        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "cooldown_seconds": 3600,
            },
        )
        state = _make_state(last_launch={"tm_improvement_worker": now - 10})
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "tm_improvement_worker" not in launched


class TestCircuitBreaker:
    """Scenario 6: After configured threshold, no more launches."""

    def test_circuit_breaker_blocks_all(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x": 1}\n', encoding="utf-8")

        now = time.time()
        # 6 launches in last hour exceeds the 5/hour limit
        history = [now - i * 60 for i in range(6)]

        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "cooldown_seconds": 0,
            },
        )
        state = _make_state(launch_history=history)
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "tm_improvement_worker" not in launched


class TestLivePidBlocks:
    """Scenario 7: Live PID exists -> no duplicate worker launched."""

    def test_live_pid_prevents_launch(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x": 1}\n', encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "cooldown_seconds": 0,
            },
        )
        state = _make_state()
        with patch("src.workers.worker_orchestrator.worker_pid_alive", return_value=True):
            launched = run_check_cycle(registry, state, dry_run=True)
        assert "tm_improvement_worker" not in launched


class TestDisabledWorker:
    """Scenario 8: Disabled worker -> not launched."""

    def test_disabled_worker_skipped(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x": 1}\n', encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={
                "enabled": False,
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "cooldown_seconds": 0,
            },
        )
        state = _make_state()
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "tm_improvement_worker" not in launched


class TestDryRunNoPopen:
    """Scenario 9: Dry-run -> logs launch decision but does not call subprocess.Popen."""

    def test_dry_run_does_not_spawn_processes(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x": 1}\n', encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "cooldown_seconds": 0,
            },
        )
        state = _make_state()
        with patch("src.workers.worker_orchestrator.subprocess.Popen") as mock_popen:
            launched = run_check_cycle(registry, state, dry_run=True)
            mock_popen.assert_not_called()
        assert "tm_improvement_worker" in launched

    def test_dry_run_writes_event_log(self, tmp_path):
        from src.workers.worker_orchestrator import _EVENT_LOG, run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x": 1}\n', encoding="utf-8")

        registry = _base_registry(
            tmp_path,
            tm_improvement_worker={
                "trigger": {"type": "queue_non_empty", "queue_path": str(q)},
                "cooldown_seconds": 0,
            },
        )
        state = _make_state()

        # Patch _EVENT_LOG to write to tmp_path
        event_log = tmp_path / "events.jsonl"
        with patch("src.workers.worker_orchestrator._EVENT_LOG", event_log):
            run_check_cycle(registry, state, dry_run=True)

        assert event_log.exists()
        lines = [l for l in event_log.read_text(encoding="utf-8").splitlines() if l.strip()]
        events = [json.loads(l) for l in lines]
        dry_run_events = [e for e in events if e.get("event") == "dry_run_launch"]
        assert len(dry_run_events) >= 1


class TestStatusCommand:
    """TC-12: --status subcommand returns structured worker overview."""

    def test_print_status_returns_all_workers(self, tmp_path):
        from src.workers.worker_orchestrator import print_status

        registry = _base_registry(tmp_path)
        state = _make_state()
        with patch("src.workers.worker_orchestrator.print_status.__module__", create=True):
            pass
        report = print_status(registry, state, as_json=False)
        assert "workers" in report
        assert "content_worker" in report["workers"]
        assert "queues" in report
        assert "circuit_breaker" in report

    def test_print_status_json(self, tmp_path, capsys):
        from src.workers.worker_orchestrator import print_status

        registry = _base_registry(tmp_path)
        state = _make_state()
        report = print_status(registry, state, as_json=True)
        captured = capsys.readouterr()
        parsed = json.loads(captured.out)
        assert "workers" in parsed
        assert "content_worker" in parsed["workers"]


class TestWorkerCompletedTrigger:
    """Bonus: worker_completed trigger fires when content_worker completes."""

    def test_verification_triggered_after_content_worker(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        registry = _base_registry(
            tmp_path,
            verification_worker={
                "trigger": {"type": "worker_completed", "worker": "content_worker"},
            },
        )
        state = _make_state(recently_completed_workers=["content_worker"])
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "verification_worker" in launched
