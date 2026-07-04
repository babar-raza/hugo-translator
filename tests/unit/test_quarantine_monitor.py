"""TC-H4B: Quarantine queue depth monitor tests.

Tests the quarantine.jsonl depth reporting logic in worker_orchestrator.print_status().

The plan referenced a check_worker_health.ps1 that was not created; the quarantine
monitoring logic lives in worker_orchestrator.py print_status() which counts lines
in data/quarantine.jsonl.  These tests verify edge cases with real temp files using
monkeypatch.chdir() to redirect relative path lookups.
"""
from __future__ import annotations

import json
from pathlib import Path

import pytest


def _empty_state() -> dict:
    return {"last_launch": {}, "launch_history": []}


def _run_print_status(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict:
    """Change cwd to tmp_path and call print_status with empty registry."""
    monkeypatch.chdir(tmp_path)
    from src.workers.worker_orchestrator import print_status
    registry = {"workers": {}}
    return print_status(registry, _empty_state(), as_json=False)


class TestQuarantineQueueDepth:
    """Tests for quarantine.jsonl depth reporting in print_status()."""

    def test_missing_quarantine_file_no_crash(self, tmp_path, monkeypatch):
        """Missing quarantine.jsonl must not crash — key absent from report."""
        # No data/ dir created at all
        report = _run_print_status(tmp_path, monkeypatch)
        queues = report.get("queues", {})
        assert "data/quarantine.jsonl" not in queues, (
            "Missing quarantine.jsonl must not appear in queues report"
        )

    def test_empty_quarantine_file_returns_zero(self, tmp_path, monkeypatch):
        """Empty quarantine.jsonl must report 0 entries — no false warning."""
        (tmp_path / "data").mkdir()
        (tmp_path / "data" / "quarantine.jsonl").write_text("", encoding="utf-8")

        report = _run_print_status(tmp_path, monkeypatch)
        queues = report.get("queues", {})
        assert queues.get("data/quarantine.jsonl") == 0, (
            f"Empty quarantine file must report 0 entries, got: {queues}"
        )

    def test_single_valid_entry(self, tmp_path, monkeypatch):
        """Single valid JSONL entry reports count=1."""
        (tmp_path / "data").mkdir()
        entry = {"output_path": "/some/file.de.md", "tgt_lang": "de", "queued_at": "2026-06-11"}
        (tmp_path / "data" / "quarantine.jsonl").write_text(
            json.dumps(entry) + "\n", encoding="utf-8"
        )

        report = _run_print_status(tmp_path, monkeypatch)
        assert report["queues"]["data/quarantine.jsonl"] == 1

    def test_multiple_entries_correct_count(self, tmp_path, monkeypatch):
        """Multiple JSONL entries report correct line count."""
        (tmp_path / "data").mkdir()
        entries = [
            {"output_path": f"/some/file_{i}.de.md", "tgt_lang": "de", "queued_at": "2026-06-11"}
            for i in range(5)
        ]
        content = "\n".join(json.dumps(e) for e in entries) + "\n"
        (tmp_path / "data" / "quarantine.jsonl").write_text(content, encoding="utf-8")

        report = _run_print_status(tmp_path, monkeypatch)
        assert report["queues"]["data/quarantine.jsonl"] == 5

    def test_malformed_json_lines_counted_not_fatal(self, tmp_path, monkeypatch):
        """Malformed JSON lines must be counted (not parsed), not cause a crash."""
        (tmp_path / "data").mkdir()
        # Mix of valid and malformed lines — the monitor just counts lines
        lines = [
            '{"output_path": "/good/file.md"}',
            "NOT JSON AT ALL",
            '{"partial": true',  # truncated
            "another bad line",
        ]
        (tmp_path / "data" / "quarantine.jsonl").write_text(
            "\n".join(lines) + "\n", encoding="utf-8"
        )

        report = _run_print_status(tmp_path, monkeypatch)
        # 4 lines + trailing newline = 5 lines total (empty last line counted)
        # The reporter counts physical lines, not parsed entries
        count = report["queues"]["data/quarantine.jsonl"]
        assert count >= 4, (
            f"Malformed JSON lines must not crash; expected >=4 lines counted, got {count}"
        )
