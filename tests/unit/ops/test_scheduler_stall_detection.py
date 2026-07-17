"""TC-OPS-STALL-001: scheduler's stall detector must not kill a freshly
dispatched process just because its job's log file predates a full outage.

Root cause (found live, 2026-07-17): `_check_and_kill_stall()` computed
staleness purely from the job's *log file* mtime. After any full stop
(reboot, crash, manual kill-all), the log file's mtime is frozen from before
the stop, so the very next dispatch's PID looked "silent for hours" from the
first post-restart poll cycle and got killed within ~60-90s, before it could
even load its model -- an infinite dispatch/kill crash-loop. Confirmed live
against `review_latin_m2m` and `headings_nonlatin_a` after a 2026-07-17
10:58 system reboot, while `unified_shard_4` (whose log genuinely was
writing fresh lines) was correctly left alone.

Fix: floor the staleness calculation at `max(log_mtime, lock_mtime)` -- the
child process rewrites its own PID into the lock file on startup (existing
convention), so the lock mtime reliably reflects "when did this specific PID
start," independent of the log file's older history.

`.local/scheduler.py` is not on the normal import path (dot-prefixed,
machine-local ops script) -- loaded here via importlib by file path.
"""

import importlib.util
import os
import sys
import time
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_SCHEDULER_PATH = _REPO_ROOT / ".local" / "scheduler.py"

pytestmark = pytest.mark.skipif(
    not _SCHEDULER_PATH.exists(), reason=".local/scheduler.py not present in this checkout"
)


def _load_scheduler_module():
    spec = importlib.util.spec_from_file_location("_test_scheduler", _SCHEDULER_PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture()
def scheduler(tmp_path, monkeypatch):
    mod = _load_scheduler_module()
    # Redirect all path-construction helpers at the module's LOCAL constant
    # to an isolated tmp dir -- never touch the real .local/ directory.
    monkeypatch.setattr(mod, "LOCAL", tmp_path)
    return mod


def _touch(path: Path, age_seconds: float):
    path.write_text("x", encoding="utf-8")
    stamp = time.time() - age_seconds
    os.utime(path, (stamp, stamp))


class TestStallDetectionFloorsAtLockMtime:
    def test_stale_log_but_fresh_lock_is_not_a_stall(self, scheduler, tmp_path):
        """The exact post-outage scenario: log is ancient, lock is fresh
        (just dispatched). Must NOT be killed."""
        job = {"id": "headings_nonlatin_a", "queue": "heal_headings_nonlatin_a.jsonl"}
        _touch(tmp_path / "heal_headings_nonlatin_a.log", age_seconds=9 * 3600)  # 9h old
        _touch(tmp_path / "heal_headings_nonlatin_a.lock", age_seconds=5)  # just dispatched

        with patch("psutil.Process") as mock_process:
            killed = scheduler._check_and_kill_stall(job, pid=99999)

        assert killed is False
        mock_process.assert_not_called()

    def test_stale_log_and_stale_lock_is_a_genuine_stall(self, scheduler, tmp_path):
        """A real stall: both log and lock are old (long-running process
        that stopped producing output). Must be killed."""
        job = {"id": "headings_nonlatin_a", "queue": "heal_headings_nonlatin_a.jsonl"}
        _touch(tmp_path / "heal_headings_nonlatin_a.log", age_seconds=3600)  # 60 min old
        _touch(tmp_path / "heal_headings_nonlatin_a.lock", age_seconds=3600)  # dispatched 60 min ago, never refreshed

        mock_proc_instance = MagicMock()
        with patch("psutil.Process", return_value=mock_proc_instance) as mock_process:
            killed = scheduler._check_and_kill_stall(job, pid=12345)

        assert killed is True
        mock_process.assert_called_once_with(12345)
        mock_proc_instance.terminate.assert_called_once()

    def test_fresh_log_is_never_a_stall_regardless_of_lock(self, scheduler, tmp_path):
        """A healthy, actively-logging process must never be killed, even if
        its lock file happens to be older (e.g. long-running job that hasn't
        needed redispatch)."""
        job = {"id": "unified_shard_4", "kind": "unified_shard", "shard_id": 4}
        _touch(tmp_path / "unified_s4.pid", age_seconds=3600)
        # unified_shard jobs resolve their log via _scan_log_path -- exercise
        # the same helper the real dispatch loop uses rather than guessing
        # its filename convention.
        log_path = scheduler._job_log_path(job)
        _touch(log_path, age_seconds=10)  # written 10s ago -- actively progressing

        with patch("psutil.Process") as mock_process:
            killed = scheduler._check_and_kill_stall(job, pid=42)

        assert killed is False
        mock_process.assert_not_called()

    def test_no_lock_file_falls_back_to_log_mtime_only(self, scheduler, tmp_path):
        """Backward-compatible: if a lock file genuinely doesn't exist yet,
        behavior must match the pre-fix log-only staleness check rather than
        erroring."""
        job = {"id": "headings_nonlatin_a", "queue": "heal_headings_nonlatin_a.jsonl"}
        _touch(tmp_path / "heal_headings_nonlatin_a.log", age_seconds=3600)
        # deliberately do not create the .lock file

        mock_proc_instance = MagicMock()
        with patch("psutil.Process", return_value=mock_proc_instance):
            killed = scheduler._check_and_kill_stall(job, pid=12345)

        assert killed is True
        mock_proc_instance.terminate.assert_called_once()
