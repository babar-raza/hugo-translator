"""Tests for read-only queue and file-change probe functions."""

import json
import time
from pathlib import Path

import pytest


class TestQueueEntryCount:
    def test_missing_file_returns_zero(self, tmp_path):
        from src.workers.queue_probes import queue_entry_count

        assert queue_entry_count(tmp_path / "nope.jsonl") == 0

    def test_empty_file_returns_zero(self, tmp_path):
        from src.workers.queue_probes import queue_entry_count

        (tmp_path / "q.jsonl").write_text("", encoding="utf-8")
        assert queue_entry_count(tmp_path / "q.jsonl") == 0

    def test_counts_valid_entries(self, tmp_path):
        from src.workers.queue_probes import queue_entry_count

        p = tmp_path / "q.jsonl"
        lines = [json.dumps({"id": i}) for i in range(5)]
        p.write_text("\n".join(lines) + "\n", encoding="utf-8")
        assert queue_entry_count(p) == 5

    def test_skips_malformed_lines(self, tmp_path):
        from src.workers.queue_probes import queue_entry_count

        p = tmp_path / "q.jsonl"
        p.write_text('{"ok": 1}\nBAD LINE\n{"ok": 2}\n', encoding="utf-8")
        assert queue_entry_count(p) == 2

    def test_skips_blank_lines(self, tmp_path):
        from src.workers.queue_probes import queue_entry_count

        p = tmp_path / "q.jsonl"
        p.write_text('{"a":1}\n\n\n{"b":2}\n', encoding="utf-8")
        assert queue_entry_count(p) == 2


class TestQueueHasEntries:
    def test_false_when_empty(self, tmp_path):
        from src.workers.queue_probes import queue_has_entries

        (tmp_path / "q.jsonl").write_text("", encoding="utf-8")
        assert queue_has_entries(tmp_path / "q.jsonl") is False

    def test_true_when_non_empty(self, tmp_path):
        from src.workers.queue_probes import queue_has_entries

        (tmp_path / "q.jsonl").write_text('{"x":1}\n', encoding="utf-8")
        assert queue_has_entries(tmp_path / "q.jsonl") is True

    def test_false_when_missing(self, tmp_path):
        from src.workers.queue_probes import queue_has_entries

        assert queue_has_entries(tmp_path / "nope.jsonl") is False


class TestContentRepoHasChanges:
    def test_detects_new_md_file(self, tmp_path):
        from src.workers.queue_probes import content_repo_has_changes

        past = time.time() - 10
        md = tmp_path / "test.md"
        md.write_text("# Hello", encoding="utf-8")
        assert content_repo_has_changes(tmp_path, past) is True

    def test_no_changes_when_old(self, tmp_path):
        from src.workers.queue_probes import content_repo_has_changes

        md = tmp_path / "test.md"
        md.write_text("# Hello", encoding="utf-8")
        future = time.time() + 100
        assert content_repo_has_changes(tmp_path, future) is False

    def test_missing_dir_returns_false(self, tmp_path):
        from src.workers.queue_probes import content_repo_has_changes

        assert content_repo_has_changes(tmp_path / "nope", 0.0) is False


class TestConfigChangedSince:
    def test_detects_yaml_change(self, tmp_path):
        from src.workers.queue_probes import config_changed_since

        past = time.time() - 10
        (tmp_path / "global.yaml").write_text("key: val", encoding="utf-8")
        assert config_changed_since(tmp_path, past) is True

    def test_no_change_when_old(self, tmp_path):
        from src.workers.queue_probes import config_changed_since

        (tmp_path / "global.yaml").write_text("key: val", encoding="utf-8")
        future = time.time() + 100
        assert config_changed_since(tmp_path, future) is False


class TestFileExists:
    def test_exists(self, tmp_path):
        from src.workers.queue_probes import file_exists

        (tmp_path / "f").write_text("x")
        assert file_exists(tmp_path / "f") is True

    def test_missing(self, tmp_path):
        from src.workers.queue_probes import file_exists

        assert file_exists(tmp_path / "nope") is False


class TestStateFileRecent:
    def test_recent_file(self, tmp_path):
        from src.workers.queue_probes import state_file_recent

        (tmp_path / "s.json").write_text("{}")
        assert state_file_recent(tmp_path / "s.json", 60) is True

    def test_old_file(self, tmp_path):
        from src.workers.queue_probes import state_file_recent

        p = tmp_path / "s.json"
        p.write_text("{}")
        import os

        os.utime(p, (0, 0))
        assert state_file_recent(p, 60) is False

    def test_missing_file(self, tmp_path):
        from src.workers.queue_probes import state_file_recent

        assert state_file_recent(tmp_path / "nope", 60) is False


class TestWorkerPidAlive:
    def test_missing_pid_file(self, tmp_path):
        from src.workers.queue_probes import worker_pid_alive

        assert worker_pid_alive(tmp_path / "nope.pid") is False

    def test_invalid_pid_content(self, tmp_path):
        from src.workers.queue_probes import worker_pid_alive

        (tmp_path / "w.pid").write_text("not_a_number")
        assert worker_pid_alive(tmp_path / "w.pid") is False

    def test_current_process_is_alive(self, tmp_path):
        import os

        from src.workers.queue_probes import worker_pid_alive

        (tmp_path / "w.pid").write_text(str(os.getpid()))
        assert worker_pid_alive(tmp_path / "w.pid") is True
