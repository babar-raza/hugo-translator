"""Unit tests for orchestrator trigger evaluation and launch decisions."""

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest


def _make_state(**overrides):
    state = {
        "last_check_time": time.time() - 600,
        "last_launch": {},
        "launch_history": [],
        "recently_launched_workers": [],
        "running_count": {},
    }
    state.update(overrides)
    return state


def _make_cfg(**overrides):
    cfg = {
        "enabled": True,
        "mode": "oneshot",
        "module": "src.workers.test",
        "cli_args": ["--mode", "oneshot"],
        "trigger": {"type": "queue_non_empty", "queue_path": "data/q.jsonl"},
        "cooldown_seconds": 60,
        "max_concurrent": 1,
        "safe_command": ".venv/Scripts/python.exe -m src.workers.test --mode oneshot",
        "useful_work_criteria": "x > 0",
    }
    cfg.update(overrides)
    return cfg


# ---------------------------------------------------------------------------
# evaluate_trigger
# ---------------------------------------------------------------------------

class TestEvaluateTrigger:
    def test_queue_non_empty_true(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        q = tmp_path / "q.jsonl"
        q.write_text('{"a":1}\n', encoding="utf-8")
        trigger = {"type": "queue_non_empty", "queue_path": str(q)}
        assert evaluate_trigger(trigger, {}) is True

    def test_queue_non_empty_false(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        q = tmp_path / "q.jsonl"
        q.write_text("", encoding="utf-8")
        trigger = {"type": "queue_non_empty", "queue_path": str(q)}
        assert evaluate_trigger(trigger, {}) is False

    def test_queue_missing_file(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        trigger = {"type": "queue_non_empty", "queue_path": str(tmp_path / "nope")}
        assert evaluate_trigger(trigger, {}) is False

    def test_file_change_detected(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        (tmp_path / "test.yaml").write_text("key: val")
        trigger = {"type": "file_change", "paths": [str(tmp_path)], "pattern": "*.yaml"}
        state = {"last_check_time": time.time() - 100}
        assert evaluate_trigger(trigger, state) is True

    def test_file_change_no_change(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        (tmp_path / "test.yaml").write_text("key: val")
        trigger = {"type": "file_change", "paths": [str(tmp_path)], "pattern": "*.yaml"}
        state = {"last_check_time": time.time() + 100}
        assert evaluate_trigger(trigger, state) is False

    def test_worker_completed(self):
        from src.workers.worker_orchestrator import evaluate_trigger

        trigger = {"type": "worker_completed", "worker": "content_worker"}
        state = {"recently_launched_workers": ["content_worker"]}
        assert evaluate_trigger(trigger, state) is True

    def test_worker_not_completed(self):
        from src.workers.worker_orchestrator import evaluate_trigger

        trigger = {"type": "worker_completed", "worker": "content_worker"}
        state = {"recently_launched_workers": []}
        assert evaluate_trigger(trigger, state) is False

    def test_multi_any_fires(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        q = tmp_path / "q.jsonl"
        q.write_text('{"a":1}\n', encoding="utf-8")
        trigger = {
            "type": "multi",
            "conditions": [
                {"type": "queue_non_empty", "queue_path": str(q)},
                {"type": "worker_completed", "worker": "nope"},
            ],
        }
        assert evaluate_trigger(trigger, {"recently_launched_workers": []}) is True

    def test_multi_none_fires(self, tmp_path):
        from src.workers.worker_orchestrator import evaluate_trigger

        trigger = {
            "type": "multi",
            "conditions": [
                {"type": "queue_non_empty", "queue_path": str(tmp_path / "nope")},
                {"type": "worker_completed", "worker": "nope"},
            ],
        }
        assert evaluate_trigger(trigger, {"recently_launched_workers": []}) is False

    def test_unknown_trigger_returns_false(self):
        from src.workers.worker_orchestrator import evaluate_trigger

        assert evaluate_trigger({"type": "magic"}, {}) is False

    def test_error_in_trigger_returns_false(self):
        from src.workers.worker_orchestrator import evaluate_trigger

        # Missing required fields should not crash
        assert evaluate_trigger({"type": "file_change"}, {}) is False


# ---------------------------------------------------------------------------
# should_launch
# ---------------------------------------------------------------------------

class TestShouldLaunch:
    def test_disabled_worker(self):
        from src.workers.worker_orchestrator import should_launch

        cfg = _make_cfg(enabled=False)
        ok, reason = should_launch("w", cfg, _make_state())
        assert ok is False
        assert "disabled" in reason

    def test_campaign_sentinel_blocks(self, tmp_path):
        from src.workers.worker_orchestrator import should_launch

        sentinel = tmp_path / "sentinel"
        sentinel.write_text("")
        cfg = _make_cfg(campaign_sentinel=str(sentinel))
        ok, reason = should_launch("w", cfg, _make_state())
        assert ok is False
        assert "campaign sentinel" in reason

    def test_cooldown_blocks(self):
        from src.workers.worker_orchestrator import should_launch

        now = time.time()
        state = _make_state(last_launch={"w": now - 10})
        cfg = _make_cfg(cooldown_seconds=60)
        ok, reason = should_launch("w", cfg, state, now=now)
        assert ok is False
        assert "cooldown" in reason

    def test_circuit_breaker_blocks(self):
        from src.workers.worker_orchestrator import should_launch

        now = time.time()
        history = [now - i * 60 for i in range(6)]  # 6 launches in last hour
        state = _make_state(launch_history=history)
        cfg = _make_cfg(cooldown_seconds=0)
        ok, reason = should_launch("w", cfg, state, now=now)
        assert ok is False
        assert "circuit breaker" in reason

    def test_no_trigger_fires(self, tmp_path):
        from src.workers.worker_orchestrator import should_launch

        cfg = _make_cfg(
            trigger={"type": "queue_non_empty", "queue_path": str(tmp_path / "empty.jsonl")}
        )
        ok, reason = should_launch("w", cfg, _make_state())
        assert ok is False
        assert "no trigger" in reason

    def test_trigger_fires(self, tmp_path):
        from src.workers.worker_orchestrator import should_launch

        q = tmp_path / "q.jsonl"
        q.write_text('{"x":1}\n')
        cfg = _make_cfg(
            trigger={"type": "queue_non_empty", "queue_path": str(q)},
            cooldown_seconds=0,
        )
        ok, reason = should_launch("w", cfg, _make_state())
        assert ok is True
        assert "trigger fired" in reason

    def test_live_pid_blocks(self, tmp_path, monkeypatch):
        from src.workers.worker_orchestrator import should_launch

        # Create PID file at the relative path the orchestrator looks for: data/logs/w.pid
        pid_dir = tmp_path / "data" / "logs"
        pid_dir.mkdir(parents=True)
        (pid_dir / "w.pid").write_text(str(os.getpid()))
        monkeypatch.chdir(tmp_path)

        q = tmp_path / "q.jsonl"
        q.write_text('{"x":1}\n')
        cfg = _make_cfg(
            trigger={"type": "queue_non_empty", "queue_path": str(q)},
            cooldown_seconds=0,
        )
        state = _make_state()
        with patch("src.workers.worker_orchestrator.worker_pid_alive", return_value=True):
            ok, reason = should_launch("w", cfg, state)
        assert ok is False
        assert "already running" in reason


# ---------------------------------------------------------------------------
# run_check_cycle
# ---------------------------------------------------------------------------

class TestRunCheckCycle:
    def test_no_triggers_no_launch(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        registry = {
            "workers": {
                "w": _make_cfg(
                    trigger={"type": "queue_non_empty", "queue_path": str(tmp_path / "nope")},
                    cooldown_seconds=0,
                ),
            }
        }
        state = _make_state()
        launched = run_check_cycle(registry, state, dry_run=True)
        assert launched == []

    def test_trigger_fires_dry_run(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x":1}\n')
        registry = {
            "workers": {
                "w": _make_cfg(
                    trigger={"type": "queue_non_empty", "queue_path": str(q)},
                    cooldown_seconds=0,
                ),
            }
        }
        state = _make_state()
        launched = run_check_cycle(registry, state, dry_run=True)
        assert "w" in launched

    def test_dry_run_does_not_call_popen(self, tmp_path):
        from src.workers.worker_orchestrator import run_check_cycle

        q = tmp_path / "q.jsonl"
        q.write_text('{"x":1}\n')
        registry = {
            "workers": {
                "w": _make_cfg(
                    trigger={"type": "queue_non_empty", "queue_path": str(q)},
                    cooldown_seconds=0,
                ),
            }
        }
        state = _make_state()
        with patch("src.workers.worker_orchestrator.subprocess.Popen") as mock_popen:
            run_check_cycle(registry, state, dry_run=True)
            mock_popen.assert_not_called()
