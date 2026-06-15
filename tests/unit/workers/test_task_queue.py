"""Tests for TC-AGT-06: Programmatic task queue."""

import json
import tempfile
from pathlib import Path

import pytest

from src.workers.task_queue import (
    TaskStatus,
    add_blocker,
    add_task,
    get_next_task,
    load_all_tasks,
    queue_summary,
    remove_task,
    update_task_status,
)


@pytest.fixture()
def queue_file(tmp_path):
    """Provide a temp queue file path."""
    return tmp_path / "task_queue.jsonl"


class TestAddTask:
    def test_add_new_task(self, queue_file):
        task = add_task("TC-01", "Test task", queue_file=queue_file)
        assert task["task_id"] == "TC-01"
        assert task["title"] == "Test task"
        assert task["status"] == "pending"
        assert queue_file.exists()

    def test_add_with_metadata(self, queue_file):
        task = add_task(
            "TC-02",
            "Task with meta",
            lane="B",
            priority="P1",
            horizon=2,
            depends_on=["TC-01"],
            metadata={"gap": "GAP-04"},
            queue_file=queue_file,
        )
        assert task["lane"] == "B"
        assert task["priority"] == "P1"
        assert task["horizon"] == 2
        assert task["depends_on"] == ["TC-01"]
        assert task["metadata"]["gap"] == "GAP-04"

    def test_dedup_by_task_id(self, queue_file):
        add_task("TC-01", "First", queue_file=queue_file)
        result = add_task("TC-01", "Duplicate", queue_file=queue_file)
        assert result["title"] == "First"
        tasks = load_all_tasks(queue_file=queue_file)
        assert len(tasks) == 1

    def test_multiple_tasks(self, queue_file):
        add_task("TC-01", "First", queue_file=queue_file)
        add_task("TC-02", "Second", queue_file=queue_file)
        add_task("TC-03", "Third", queue_file=queue_file)
        tasks = load_all_tasks(queue_file=queue_file)
        assert len(tasks) == 3


class TestUpdateStatus:
    def test_update_to_in_progress(self, queue_file):
        add_task("TC-01", "Test", queue_file=queue_file)
        result = update_task_status("TC-01", TaskStatus.IN_PROGRESS, queue_file=queue_file)
        assert result["status"] == "in_progress"

    def test_update_to_completed(self, queue_file):
        add_task("TC-01", "Test", queue_file=queue_file)
        result = update_task_status("TC-01", TaskStatus.COMPLETED, queue_file=queue_file)
        assert result["status"] == "completed"
        assert result["completed_at"] is not None

    def test_update_nonexistent(self, queue_file):
        result = update_task_status("TC-99", TaskStatus.COMPLETED, queue_file=queue_file)
        assert result is None

    def test_update_with_error(self, queue_file):
        add_task("TC-01", "Test", queue_file=queue_file)
        result = update_task_status(
            "TC-01",
            TaskStatus.BLOCKED,
            error="dependency missing",
            queue_file=queue_file,
        )
        assert result["status"] == "blocked"
        assert any("dependency missing" in str(b) for b in result["blockers"])


class TestAddBlocker:
    def test_add_blocker_sets_status(self, queue_file):
        add_task("TC-01", "Test", queue_file=queue_file)
        result = add_blocker("TC-01", "BLK-01", "API unavailable", queue_file=queue_file)
        assert result["status"] == "blocked"
        assert result["blockers"][-1]["blocker_id"] == "BLK-01"
        assert result["blockers"][-1]["description"] == "API unavailable"

    def test_add_blocker_nonexistent(self, queue_file):
        result = add_blocker("TC-99", "BLK-01", "desc", queue_file=queue_file)
        assert result is None


class TestGetNextTask:
    def test_get_next_by_priority(self, queue_file):
        add_task("TC-01", "Low", priority="P2", queue_file=queue_file)
        add_task("TC-02", "High", priority="P0", queue_file=queue_file)
        add_task("TC-03", "Medium", priority="P1", queue_file=queue_file)
        result = get_next_task(queue_file=queue_file)
        assert result["task_id"] == "TC-02"

    def test_get_next_filters_by_lane(self, queue_file):
        add_task("TC-01", "Lane B", lane="B", queue_file=queue_file)
        add_task("TC-02", "Lane D", lane="D", queue_file=queue_file)
        result = get_next_task(lane="D", queue_file=queue_file)
        assert result["task_id"] == "TC-02"

    def test_get_next_skips_completed(self, queue_file):
        add_task("TC-01", "Done", queue_file=queue_file)
        update_task_status("TC-01", TaskStatus.COMPLETED, queue_file=queue_file)
        add_task("TC-02", "Pending", queue_file=queue_file)
        result = get_next_task(queue_file=queue_file)
        assert result["task_id"] == "TC-02"

    def test_get_next_skips_blocked_dependencies(self, queue_file):
        add_task("TC-01", "Dep", queue_file=queue_file)
        add_task("TC-02", "Blocked", depends_on=["TC-01"], queue_file=queue_file)
        add_task("TC-03", "Free", queue_file=queue_file)
        result = get_next_task(queue_file=queue_file)
        # TC-02 depends on TC-01 (not completed), so TC-01 or TC-03 should be returned
        assert result["task_id"] in ("TC-01", "TC-03")

    def test_get_next_unlocks_after_dep_completed(self, queue_file):
        add_task("TC-01", "Dep", priority="P2", queue_file=queue_file)
        add_task("TC-02", "Dependent", priority="P0", depends_on=["TC-01"], queue_file=queue_file)
        update_task_status("TC-01", TaskStatus.COMPLETED, queue_file=queue_file)
        result = get_next_task(queue_file=queue_file)
        assert result["task_id"] == "TC-02"

    def test_get_next_empty_queue(self, queue_file):
        result = get_next_task(queue_file=queue_file)
        assert result is None


class TestRemoveTask:
    def test_remove_existing(self, queue_file):
        add_task("TC-01", "Test", queue_file=queue_file)
        assert remove_task("TC-01", queue_file=queue_file) is True
        assert load_all_tasks(queue_file=queue_file) == []

    def test_remove_nonexistent(self, queue_file):
        assert remove_task("TC-99", queue_file=queue_file) is False


class TestQueueSummary:
    def test_summary_counts(self, queue_file):
        add_task("TC-01", "A", queue_file=queue_file)
        add_task("TC-02", "B", queue_file=queue_file)
        update_task_status("TC-02", TaskStatus.COMPLETED, queue_file=queue_file)
        add_task("TC-03", "C", queue_file=queue_file)
        add_blocker("TC-03", "BLK", "reason", queue_file=queue_file)
        summary = queue_summary(queue_file=queue_file)
        assert summary["total"] == 3
        assert summary["pending"] == 1
        assert summary["completed"] == 1
        assert summary["blocked"] == 1


class TestLoadAllTasks:
    def test_filter_by_status(self, queue_file):
        add_task("TC-01", "A", queue_file=queue_file)
        add_task("TC-02", "B", queue_file=queue_file)
        update_task_status("TC-02", TaskStatus.COMPLETED, queue_file=queue_file)
        pending = load_all_tasks(status=TaskStatus.PENDING, queue_file=queue_file)
        assert len(pending) == 1
        assert pending[0]["task_id"] == "TC-01"


class TestPersistence:
    def test_roundtrip_through_file(self, queue_file):
        """Verify JSONL format survives read-write cycle."""
        add_task("TC-01", "Task One", lane="B", priority="P1", queue_file=queue_file)
        add_task("TC-02", "Task Two", lane="D", priority="P0", queue_file=queue_file)

        # Read raw JSONL
        lines = queue_file.read_text(encoding="utf-8").strip().splitlines()
        assert len(lines) == 2
        for line in lines:
            entry = json.loads(line)
            assert "task_id" in entry
            assert "created_at" in entry

    def test_empty_file_handled(self, queue_file):
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        queue_file.write_text("", encoding="utf-8")
        tasks = load_all_tasks(queue_file=queue_file)
        assert tasks == []

    def test_malformed_lines_skipped(self, queue_file):
        queue_file.parent.mkdir(parents=True, exist_ok=True)
        queue_file.write_text(
            '{"task_id":"TC-01","title":"Good","status":"pending"}\n'
            "NOT JSON\n"
            '{"task_id":"TC-02","title":"Also Good","status":"pending"}\n',
            encoding="utf-8",
        )
        tasks = load_all_tasks(queue_file=queue_file)
        assert len(tasks) == 2
