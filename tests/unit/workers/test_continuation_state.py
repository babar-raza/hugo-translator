"""Tests for TC-AGT-07: Cross-session continuation state machine."""

import json
from pathlib import Path

import pytest

from src.workers.continuation_state import (
    RunPhase,
    add_blocker,
    complete_run,
    fail_run,
    get_pending_work,
    get_run_history,
    interrupt_run,
    is_circuit_broken,
    load_state,
    record_progress,
    should_resume,
    start_run,
)


@pytest.fixture()
def state_file(tmp_path):
    return tmp_path / "continuation_state.json"


class TestLoadState:
    def test_empty_when_no_file(self, state_file):
        state = load_state(state_file=state_file)
        assert state["phase"] == "idle"
        assert state["run_id"] is None
        assert state["stats"]["total_runs"] == 0

    def test_corrupt_file_returns_empty(self, state_file):
        state_file.parent.mkdir(parents=True, exist_ok=True)
        state_file.write_text("NOT JSON", encoding="utf-8")
        state = load_state(state_file=state_file)
        assert state["phase"] == "idle"


class TestRunLifecycle:
    def test_start_run(self, state_file):
        state = start_run("run-001", "docs.aspose.net.words", ["de", "fr"], state_file=state_file)
        assert state["phase"] == "running"
        assert state["run_id"] == "run-001"
        assert state["current_site"] == "docs.aspose.net.words"
        assert state["current_langs"] == ["de", "fr"]
        assert state["started_at"] is not None

    def test_complete_run(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        state = complete_run(
            files_processed=10,
            files_accepted=8,
            files_rejected=2,
            next_action="Run quality audit",
            state_file=state_file,
        )
        assert state["phase"] == "completed"
        assert state["completed_at"] is not None
        assert state["pending_work"] == []
        assert state["next_action"] == "Run quality audit"
        assert state["stats"]["total_runs"] == 1
        assert state["stats"]["consecutive_failures"] == 0

    def test_fail_run(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        state = fail_run(
            "OutOfMemoryError",
            pending_items=["file1.md", "file2.md"],
            state_file=state_file,
        )
        assert state["phase"] == "failed"
        assert state["pending_work"] == ["file1.md", "file2.md"]
        assert state["stats"]["consecutive_failures"] == 1
        assert "OutOfMemoryError" in state["next_action"]

    def test_interrupt_run(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        state = interrupt_run(
            pending_items=["file3.md"],
            state_file=state_file,
        )
        assert state["phase"] == "interrupted"
        assert state["pending_work"] == ["file3.md"]
        assert state["next_action"] == "Resume interrupted run"

    def test_resume_after_interrupt(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        interrupt_run(pending_items=["file3.md"], state_file=state_file)

        assert should_resume(state_file=state_file) is True

        state = start_run("run-002", "site", ["de"], state_file=state_file)
        assert state["phase"] == "running"
        assert state["run_id"] == "run-002"
        # Pending work from interrupted run is preserved
        assert state["pending_work"] == ["file3.md"]


class TestRecordProgress:
    def test_incremental_progress(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        record_progress(files_processed=5, files_accepted=4, state_file=state_file)
        record_progress(files_processed=3, files_accepted=3, state_file=state_file)

        state = load_state(state_file=state_file)
        assert state["stats"]["total_files_processed"] == 8
        assert state["stats"]["total_files_accepted"] == 7

    def test_update_pending(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        record_progress(pending_items=["a.md", "b.md"], state_file=state_file)
        assert get_pending_work(state_file=state_file) == ["a.md", "b.md"]


class TestRunHistory:
    def test_history_accumulates(self, state_file):
        for i in range(3):
            start_run(f"run-{i}", "site", ["de"], state_file=state_file)
            complete_run(files_processed=i + 1, state_file=state_file)

        history = get_run_history(state_file=state_file)
        assert len(history) == 3
        assert history[0]["run_id"] == "run-0"
        assert history[2]["run_id"] == "run-2"

    def test_history_capped_at_50(self, state_file):
        for i in range(55):
            start_run(f"run-{i}", "site", ["de"], state_file=state_file)
            complete_run(files_processed=1, state_file=state_file)

        history = get_run_history(limit=100, state_file=state_file)
        assert len(history) == 50

    def test_history_limit(self, state_file):
        for i in range(5):
            start_run(f"run-{i}", "site", ["de"], state_file=state_file)
            complete_run(files_processed=1, state_file=state_file)

        history = get_run_history(limit=2, state_file=state_file)
        assert len(history) == 2
        assert history[-1]["run_id"] == "run-4"


class TestBlockers:
    def test_add_blocker(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        state = add_blocker(
            "BLK-001",
            "LLM endpoint unreachable",
            blocker_type="external_dependency",
            state_file=state_file,
        )
        assert len(state["blockers"]) == 1
        assert state["blockers"][0]["blocker_id"] == "BLK-001"
        assert state["blockers"][0]["type"] == "external_dependency"


class TestCircuitBreaker:
    def test_not_broken_initially(self, state_file):
        assert is_circuit_broken(state_file=state_file) is False

    def test_broken_after_threshold(self, state_file):
        for i in range(3):
            start_run(f"run-{i}", "site", ["de"], state_file=state_file)
            fail_run("error", state_file=state_file)

        assert is_circuit_broken(max_consecutive_failures=3, state_file=state_file) is True

    def test_reset_on_success(self, state_file):
        for i in range(2):
            start_run(f"run-{i}", "site", ["de"], state_file=state_file)
            fail_run("error", state_file=state_file)

        start_run("run-2", "site", ["de"], state_file=state_file)
        complete_run(files_processed=1, state_file=state_file)

        assert is_circuit_broken(max_consecutive_failures=3, state_file=state_file) is False


class TestShouldResume:
    def test_no_resume_when_idle(self, state_file):
        assert should_resume(state_file=state_file) is False

    def test_no_resume_when_completed(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        complete_run(state_file=state_file)
        assert should_resume(state_file=state_file) is False

    def test_resume_when_interrupted(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        interrupt_run(state_file=state_file)
        assert should_resume(state_file=state_file) is True

    def test_no_resume_when_failed(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        fail_run("error", state_file=state_file)
        assert should_resume(state_file=state_file) is False


class TestPersistence:
    def test_state_persists_to_disk(self, state_file):
        start_run("run-001", "site", ["de"], state_file=state_file)
        assert state_file.exists()
        data = json.loads(state_file.read_text(encoding="utf-8"))
        assert data["run_id"] == "run-001"
        assert data["phase"] == "running"
