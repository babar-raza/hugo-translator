"""Tests for TC-AGT-10: Supervisor loop above worker orchestrator."""

import json
from pathlib import Path

import pytest

from src.workers.continuation_state import (
    complete_run,
    fail_run,
    interrupt_run,
    start_run as start_cont_run,
)
from src.workers.continuation_state import add_blocker as add_cont_blocker
from src.workers.supervisor_loop import (
    SupervisorDecision,
    decide,
    execute_decision,
    inspect_state,
    load_supervisor_events,
    run_cycle,
)
from src.workers.task_queue import TaskStatus, add_task, load_all_tasks, update_task_status


@pytest.fixture()
def state_file(tmp_path):
    return tmp_path / "continuation_state.json"


@pytest.fixture()
def queue_file(tmp_path):
    return tmp_path / "task_queue.jsonl"


@pytest.fixture()
def signals_dir(tmp_path):
    sdir = tmp_path / "signals"
    sdir.mkdir()
    return sdir


@pytest.fixture()
def event_log(tmp_path):
    return tmp_path / "supervisor_events.jsonl"


class TestInspectState:
    def test_empty_state(self, state_file, queue_file, signals_dir):
        snapshot = inspect_state(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
        )
        assert snapshot["continuation"]["phase"] == "idle"
        assert snapshot["should_resume"] is False
        assert snapshot["circuit_broken"] is False
        assert snapshot["next_task"]["task_id"] is None
        assert snapshot["latest_signal"] is None

    def test_with_tasks(self, state_file, queue_file, signals_dir):
        add_task("TC-01", "Test task", priority="P1", queue_file=queue_file)
        snapshot = inspect_state(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
        )
        assert snapshot["next_task"]["task_id"] == "TC-01"
        assert snapshot["queue_summary"]["total"] == 1

    def test_with_signal(self, state_file, queue_file, signals_dir):
        signal = {"run_id": "test-001", "verdict": "CLEAN_RUN", "status": "completed"}
        (signals_dir / "run-signal-test-001.json").write_text(json.dumps(signal), encoding="utf-8")
        snapshot = inspect_state(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
        )
        assert snapshot["latest_signal"]["verdict"] == "CLEAN_RUN"

    def test_with_interrupted_state(self, state_file, queue_file, signals_dir):
        start_cont_run("run-001", "site", ["de"], state_file=state_file)
        interrupt_run(pending_items=["file.md"], state_file=state_file)
        snapshot = inspect_state(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
        )
        assert snapshot["should_resume"] is True
        assert snapshot["continuation"]["pending_work_count"] == 1


class TestDecide:
    def test_proceed_with_task(self):
        snapshot = {
            "circuit_broken": False,
            "should_resume": False,
            "continuation": {"blockers_count": 0, "consecutive_failures": 0},
            "next_task": {"task_id": "TC-01", "title": "Test", "priority": "P1", "lane": "D"},
            "latest_signal": None,
        }
        decision = decide(snapshot)
        assert decision["decision"] == SupervisorDecision.PROCEED.value
        assert decision["task_id"] == "TC-01"

    def test_circuit_break(self):
        snapshot = {
            "circuit_broken": True,
            "should_resume": False,
            "continuation": {"blockers_count": 0, "consecutive_failures": 5},
            "next_task": {"task_id": None},
            "latest_signal": None,
        }
        decision = decide(snapshot)
        assert decision["decision"] == SupervisorDecision.CIRCUIT_BREAK.value

    def test_resume_interrupted(self):
        snapshot = {
            "circuit_broken": False,
            "should_resume": True,
            "continuation": {"blockers_count": 0, "pending_work_count": 3},
            "next_task": {"task_id": "TC-01"},
            "latest_signal": None,
        }
        decision = decide(snapshot)
        assert decision["decision"] == SupervisorDecision.RESUME.value

    def test_blocked(self):
        snapshot = {
            "circuit_broken": False,
            "should_resume": False,
            "continuation": {"blockers_count": 2, "consecutive_failures": 0},
            "next_task": {"task_id": "TC-01"},
            "latest_signal": None,
        }
        decision = decide(snapshot)
        assert decision["decision"] == SupervisorDecision.BLOCK.value

    def test_skip_no_work(self):
        snapshot = {
            "circuit_broken": False,
            "should_resume": False,
            "continuation": {"blockers_count": 0, "consecutive_failures": 0},
            "next_task": {"task_id": None, "title": None, "priority": None, "lane": None},
            "latest_signal": None,
        }
        decision = decide(snapshot)
        assert decision["decision"] == SupervisorDecision.SKIP.value

    def test_priority_order(self):
        """Circuit break > resume > block > proceed > skip."""
        # Circuit break takes priority
        snapshot = {
            "circuit_broken": True,
            "should_resume": True,
            "continuation": {"blockers_count": 2, "consecutive_failures": 5},
            "next_task": {"task_id": "TC-01"},
        }
        assert decide(snapshot)["decision"] == SupervisorDecision.CIRCUIT_BREAK.value


class TestExecuteDecision:
    def test_execute_proceed_dry_run(self, queue_file, event_log):
        add_task("TC-01", "Test", queue_file=queue_file)
        decision = {
            "decision": SupervisorDecision.PROCEED.value,
            "reason": "test",
            "recommended_action": "execute",
            "task_id": "TC-01",
        }
        result = execute_decision(
            decision,
            task_queue_file=queue_file,
            event_log=event_log,
            dry_run=True,
        )
        assert result["dry_run"] is True
        # Task should NOT be updated in dry-run
        tasks = load_all_tasks(queue_file=queue_file)
        assert tasks[0]["status"] == "pending"

    def test_execute_proceed_live(self, queue_file, event_log):
        add_task("TC-01", "Test", queue_file=queue_file)
        decision = {
            "decision": SupervisorDecision.PROCEED.value,
            "reason": "test",
            "recommended_action": "execute",
            "task_id": "TC-01",
        }
        result = execute_decision(
            decision,
            task_queue_file=queue_file,
            event_log=event_log,
            dry_run=False,
        )
        assert result["executed"] is True
        tasks = load_all_tasks(queue_file=queue_file)
        assert tasks[0]["status"] == "in_progress"

    def test_execute_skip(self, event_log):
        decision = {
            "decision": SupervisorDecision.SKIP.value,
            "reason": "nothing to do",
            "recommended_action": "idle",
            "task_id": None,
        }
        result = execute_decision(decision, event_log=event_log, dry_run=False)
        assert result["executed"] is True

    def test_events_logged(self, event_log):
        decision = {
            "decision": SupervisorDecision.SKIP.value,
            "reason": "test",
            "recommended_action": "idle",
            "task_id": None,
        }
        execute_decision(decision, event_log=event_log, dry_run=False)
        events = load_supervisor_events(event_log=event_log)
        assert len(events) == 1
        assert events[0]["decision"] == "skip"


class TestRunCycle:
    def test_full_cycle_idle(self, state_file, queue_file, signals_dir, event_log):
        result = run_cycle(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
            event_log=event_log,
        )
        assert result["decision"]["decision"] == SupervisorDecision.SKIP.value
        assert result["execution"]["executed"] is True

    def test_full_cycle_with_task(self, state_file, queue_file, signals_dir, event_log):
        add_task("TC-01", "Important task", priority="P0", queue_file=queue_file)
        result = run_cycle(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
            event_log=event_log,
        )
        assert result["decision"]["decision"] == SupervisorDecision.PROCEED.value
        assert result["decision"]["task_id"] == "TC-01"
        # Task should be in_progress
        tasks = load_all_tasks(queue_file=queue_file)
        assert tasks[0]["status"] == "in_progress"

    def test_full_cycle_circuit_broken(self, state_file, queue_file, signals_dir, event_log):
        for i in range(3):
            start_cont_run(f"run-{i}", "site", ["de"], state_file=state_file)
            fail_run("error", state_file=state_file)
        add_task("TC-01", "Task", queue_file=queue_file)
        result = run_cycle(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
            event_log=event_log,
        )
        assert result["decision"]["decision"] == SupervisorDecision.CIRCUIT_BREAK.value

    def test_dry_run_cycle(self, state_file, queue_file, signals_dir, event_log):
        add_task("TC-01", "Task", queue_file=queue_file)
        result = run_cycle(
            continuation_state_file=state_file,
            task_queue_file=queue_file,
            signals_dir=signals_dir,
            event_log=event_log,
            dry_run=True,
        )
        assert result["execution"]["dry_run"] is True
        # Task should remain pending
        tasks = load_all_tasks(queue_file=queue_file)
        assert tasks[0]["status"] == "pending"


class TestSupervisorEvents:
    def test_load_empty(self, event_log):
        events = load_supervisor_events(event_log=event_log)
        assert events == []

    def test_load_with_limit(self, state_file, queue_file, signals_dir, event_log):
        for _ in range(5):
            run_cycle(
                continuation_state_file=state_file,
                task_queue_file=queue_file,
                signals_dir=signals_dir,
                event_log=event_log,
            )
        events = load_supervisor_events(limit=3, event_log=event_log)
        assert len(events) == 3

    def test_events_have_timestamp(self, event_log):
        decision = {
            "decision": "skip",
            "reason": "test",
            "recommended_action": "idle",
            "task_id": None,
        }
        execute_decision(decision, event_log=event_log)
        events = load_supervisor_events(event_log=event_log)
        assert "timestamp" in events[0]
