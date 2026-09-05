"""TC-APT-074: task_queue.py's atomic write must survive a transient Windows
sharing violation instead of aborting the whole mission_supervisor wake.

Reproduced live: os.replace(tmp, task_queue.jsonl) raised PermissionError
(WinError 5) twice in a row during a real multi-session mission run, once
because the destination was momentarily held open (OneDrive sync and/or a
peer session's own concurrent write are both consistent with the symptom).
See data/summaries/fp-task-queue-permission-20260905.json for the
first-principles record this fix follows.
"""

from unittest.mock import patch

import pytest

from src.workers.task_queue import _replace_with_retry


class TestReplaceWithRetry:
    def test_succeeds_after_two_transient_failures(self, tmp_path):
        calls = {"n": 0}
        real_replace = __import__("os").replace

        def flaky_replace(src, dst):
            calls["n"] += 1
            if calls["n"] < 3:
                raise PermissionError("WinError 5: Access is denied")
            return real_replace(src, dst)

        tmp_file = tmp_path / "src.tmp"
        tmp_file.write_text("payload", encoding="utf-8")
        dest = tmp_path / "task_queue.jsonl"

        with patch("src.workers.task_queue.os.replace", side_effect=flaky_replace):
            with patch("src.workers.task_queue.time.sleep") as mock_sleep:
                _replace_with_retry(str(tmp_file), dest)

        assert calls["n"] == 3
        assert dest.read_text(encoding="utf-8") == "payload"
        assert mock_sleep.call_count == 2

    def test_reraises_once_the_retry_budget_is_exhausted(self, tmp_path):
        tmp_file = tmp_path / "src.tmp"
        tmp_file.write_text("payload", encoding="utf-8")
        dest = tmp_path / "task_queue.jsonl"

        with patch(
            "src.workers.task_queue.os.replace",
            side_effect=PermissionError("WinError 5: Access is denied"),
        ) as mock_replace:
            with patch("src.workers.task_queue.time.sleep"):
                with pytest.raises(PermissionError):
                    _replace_with_retry(str(tmp_file), dest)

        # 5 retry-loop attempts + 1 final unguarded attempt.
        assert mock_replace.call_count == 6

    def test_uncontended_write_takes_a_single_attempt(self, tmp_path):
        tmp_file = tmp_path / "src.tmp"
        tmp_file.write_text("payload", encoding="utf-8")
        dest = tmp_path / "task_queue.jsonl"

        with patch("src.workers.task_queue.time.sleep") as mock_sleep:
            _replace_with_retry(str(tmp_file), dest)

        assert dest.read_text(encoding="utf-8") == "payload"
        mock_sleep.assert_not_called()
