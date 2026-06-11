"""Tests for content worker heartbeat interval (SR-01).

Verifies the heartbeat thread uses a 60-second interval, not the
previous 3600-second interval that caused permanent staleness in
the watchdog's 15-minute check window.
"""

import threading
from unittest.mock import MagicMock, patch


def _get_heartbeat_wait_timeout():
    """Extract the heartbeat wait timeout from _start_heartbeat_thread.

    Patches threading.Event so we can capture the timeout passed to wait().
    """
    captured = {}

    original_event_class = threading.Event

    class SpyEvent(original_event_class):
        def wait(self, timeout=None):
            captured["timeout"] = timeout
            # Signal stop immediately so the loop exits
            self.set()
            return True

    with patch("threading.Event", SpyEvent):
        with patch("src.workers.autonomous_content_translation_worker.logger"):
            from src.workers.autonomous_content_translation_worker import (
                AutonomousContentTranslationWorker,
            )

            worker = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
            worker._worker_id = "test"
            worker._write_heartbeat = MagicMock()

            worker._start_heartbeat_thread()
            # Give heartbeat thread a moment to execute
            worker._heartbeat_thread.join(timeout=2)

    return captured.get("timeout")


class TestHeartbeatInterval:
    def test_heartbeat_interval_is_60_seconds(self):
        """Heartbeat must write every 60s to stay within watchdog's 15-min stale threshold."""
        timeout = _get_heartbeat_wait_timeout()
        assert timeout == 60, f"Expected 60s heartbeat interval, got {timeout}s"

    def test_heartbeat_interval_not_3600(self):
        """Regression: heartbeat must not use the old 3600s interval."""
        timeout = _get_heartbeat_wait_timeout()
        assert timeout != 3600, "Heartbeat interval is still 3600s (old value)"
