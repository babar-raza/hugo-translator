"""
Unit tests for TC-RW-04: Verification worker quality spot check.

Tests _check_file_integrity() and _run_quality_spot_check() from
autonomous_verification_worker.py.
"""

import json
import time
from pathlib import Path
from unittest.mock import patch

import pytest

from src.workers.autonomous_verification_worker import AutonomousVerificationWorker


class TestCheckFileIntegrity:
    """Test the static _check_file_integrity method."""

    def test_valid_file(self, tmp_path):
        f = tmp_path / "good.md"
        content = "---\ntitle: Test\ndate: 2026-01-01\n---\n\nThis is a valid article body with enough content.\n"
        f.write_text(content, encoding="utf-8")

        ok, reason = AutonomousVerificationWorker._check_file_integrity(f)
        assert ok is True
        assert reason == ""

    def test_too_small(self, tmp_path):
        f = tmp_path / "tiny.md"
        f.write_text("---\nx\n---\n", encoding="utf-8")

        ok, reason = AutonomousVerificationWorker._check_file_integrity(f)
        assert ok is False
        assert "too small" in reason

    def test_no_front_matter(self, tmp_path):
        f = tmp_path / "nofm.md"
        f.write_text("A" * 100, encoding="utf-8")

        ok, reason = AutonomousVerificationWorker._check_file_integrity(f)
        assert ok is False
        assert "missing front matter" in reason

    def test_unclosed_front_matter(self, tmp_path):
        f = tmp_path / "unclosed.md"
        content = "---\ntitle: Test\ndate: 2026-01-01\n" + "A" * 100
        f.write_text(content, encoding="utf-8")

        ok, reason = AutonomousVerificationWorker._check_file_integrity(f)
        assert ok is False
        assert "not closed" in reason

    def test_empty_body(self, tmp_path):
        f = tmp_path / "emptybody.md"
        content = "---\ntitle: Test\ndate: 2026-01-01\n---\n   \n  \n"
        # Pad front matter to get past 50-byte check
        content = "---\ntitle: A really long title to pad bytes\ndate: 2026-01-01\n---\n   \n"
        f.write_text(content, encoding="utf-8")

        ok, reason = AutonomousVerificationWorker._check_file_integrity(f)
        assert ok is False
        assert "empty" in reason

    def test_nonexistent_file(self, tmp_path):
        f = tmp_path / "ghost.md"

        ok, reason = AutonomousVerificationWorker._check_file_integrity(f)
        assert ok is False
        assert "read error" in reason


class TestRunQualitySpotCheck:
    """Test _run_quality_spot_check method."""

    def _make_worker(self):
        from src.workers.autonomous_verification_worker import (
            AutonomousVerificationWorkerConfig,
        )

        config = AutonomousVerificationWorkerConfig(config_root="config/")
        return AutonomousVerificationWorker(config)

    def test_no_state_file(self, tmp_path, monkeypatch):
        """Without content_worker.state.json, spot check should not run."""
        worker = self._make_worker()
        # chdir to tmp_path so Path("data/logs/...") resolves to a nonexistent file
        monkeypatch.chdir(tmp_path)
        result = worker._run_quality_spot_check()
        assert result["ran"] is False
        assert "no recent" in result["reason"]

    def test_old_state_skips(self, tmp_path, monkeypatch):
        """Content worker last success > 2h ago should skip spot check."""
        worker = self._make_worker()
        monkeypatch.chdir(tmp_path)
        state_dir = tmp_path / "data" / "logs"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "content_worker.state.json"
        old_ts = time.time() - 10000  # ~2.8 hours ago
        state_file.write_text(json.dumps({"last_success_ts": old_ts}), encoding="utf-8")

        result = worker._run_quality_spot_check()
        assert result["ran"] is False
        assert ">2h" in result["reason"]

    def test_recent_state_runs_check(self, tmp_path, monkeypatch):
        """Content worker last success < 2h ago should trigger spot check."""
        worker = self._make_worker()
        monkeypatch.chdir(tmp_path)
        state_dir = tmp_path / "data" / "logs"
        state_dir.mkdir(parents=True)
        state_file = state_dir / "content_worker.state.json"
        recent_ts = time.time() - 60  # 1 minute ago
        state_file.write_text(json.dumps({"last_success_ts": recent_ts}), encoding="utf-8")

        with patch.object(type(worker), "_find_output_dirs", return_value=[]):
            result = worker._run_quality_spot_check()
        assert result["ran"] is True
        assert result["files_checked"] == 0
