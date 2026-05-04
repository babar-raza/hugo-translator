"""Tests for CI stdout heartbeat (TC-04)."""
from __future__ import annotations

import threading
from unittest.mock import patch

import pytest

from src.utils.ci_heartbeat import start_ci_heartbeat


@pytest.fixture(autouse=True)
def _reset_heartbeat():
    """Reset the module-level singleton guard between tests."""
    import src.utils.ci_heartbeat as mod
    with mod._heartbeat_lock:
        mod._heartbeat_started = False
    yield
    with mod._heartbeat_lock:
        mod._heartbeat_started = False


class TestCIHeartbeat:
    def test_skips_outside_ci(self):
        """Heartbeat should not start when CI env var is unset."""
        with patch.dict("os.environ", {}, clear=True):
            assert start_ci_heartbeat() is False

    def test_starts_in_ci(self):
        """Heartbeat starts when CI=true."""
        with patch.dict("os.environ", {"CI": "true"}):
            result = start_ci_heartbeat()
            assert result is True

    def test_force_starts_without_ci(self):
        """force=True starts heartbeat even without CI env var."""
        with patch.dict("os.environ", {}, clear=True):
            assert start_ci_heartbeat(force=True) is True

    def test_duplicate_prevention(self):
        """Second call returns False (already running)."""
        with patch.dict("os.environ", {"CI": "true"}):
            assert start_ci_heartbeat() is True
            assert start_ci_heartbeat() is False

    def test_daemon_thread(self):
        """Heartbeat thread is a daemon (won't block process exit)."""
        # Count existing heartbeat threads before starting a new one
        before = len([t for t in threading.enumerate() if t.name == "ci-heartbeat"])
        with patch.dict("os.environ", {"CI": "true"}):
            start_ci_heartbeat()
            hb_threads = [t for t in threading.enumerate() if t.name == "ci-heartbeat"]
            assert len(hb_threads) == before + 1
            assert hb_threads[-1].daemon is True
