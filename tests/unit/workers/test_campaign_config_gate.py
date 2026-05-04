"""
TC-REEXEC-06: Campaign config gate tests.

Proves that the scheduler.campaign_mode_enabled config key in global.yaml
controls daemon-mode startup. Oneshot mode is never gated.
"""
from __future__ import annotations

import logging
from unittest.mock import MagicMock, patch

import pytest

from src.workers.autonomous_content_translation_worker import (
    AutonomousContentTranslationWorker,
    AutonomousWorkerConfig,
)


def _make_worker(mode: str, campaign_enabled: bool) -> AutonomousContentTranslationWorker:
    """Create a worker with mocked config_service and the given campaign flag."""
    config = AutonomousWorkerConfig(mode=mode)
    worker = AutonomousContentTranslationWorker(config)

    # Mock config_service with _raw_global_config
    mock_cs = MagicMock()
    mock_cs._raw_global_config = {
        "scheduler": {
            "campaign_mode_enabled": campaign_enabled,
            "max_queue_files_per_run": 2000,
        }
    }
    worker.config_service = mock_cs
    return worker


class TestCampaignConfigGate:
    """Campaign config gate must block daemon when disabled, allow oneshot always."""

    @patch.object(AutonomousContentTranslationWorker, "_stop_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_heartbeat")
    @patch.object(AutonomousContentTranslationWorker, "_record_state")
    @patch.object(AutonomousContentTranslationWorker, "_start_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_pid_file")
    @patch("src.workers.autonomous_content_translation_worker.emit_worker_event")
    def test_daemon_exits_when_campaign_disabled(
        self, mock_emit, mock_pid, mock_hb_start, mock_record, mock_hb_write, mock_hb_stop, caplog
    ):
        """Daemon mode must return early when campaign_mode_enabled=false."""
        worker = _make_worker(mode="daemon", campaign_enabled=False)

        with caplog.at_level(logging.INFO):
            worker.run()

        assert "campaign_mode_enabled=false" in caplog.text
        # _run_daemon should NOT have been called
        assert not hasattr(worker, "_daemon_ran")

    @patch.object(AutonomousContentTranslationWorker, "_stop_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_heartbeat")
    @patch.object(AutonomousContentTranslationWorker, "_record_state")
    @patch.object(AutonomousContentTranslationWorker, "_start_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_pid_file")
    @patch.object(AutonomousContentTranslationWorker, "_run_daemon")
    @patch("src.workers.autonomous_content_translation_worker.emit_worker_event")
    def test_daemon_proceeds_when_campaign_enabled(
        self, mock_emit, mock_daemon, mock_pid, mock_hb_start, mock_record, mock_hb_write, mock_hb_stop
    ):
        """Daemon mode must proceed to _run_daemon when campaign_mode_enabled=true."""
        worker = _make_worker(mode="daemon", campaign_enabled=True)

        worker.run()

        mock_daemon.assert_called_once()

    @patch.object(AutonomousContentTranslationWorker, "_stop_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_heartbeat")
    @patch.object(AutonomousContentTranslationWorker, "_record_state")
    @patch.object(AutonomousContentTranslationWorker, "_start_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_pid_file")
    @patch.object(AutonomousContentTranslationWorker, "_run_oneshot")
    @patch("src.workers.autonomous_content_translation_worker.emit_worker_event")
    def test_oneshot_ignores_campaign_gate(
        self, mock_emit, mock_oneshot, mock_pid, mock_hb_start, mock_record, mock_hb_write, mock_hb_stop
    ):
        """Oneshot mode must run regardless of campaign_mode_enabled value."""
        worker = _make_worker(mode="oneshot", campaign_enabled=False)

        worker.run()

        mock_oneshot.assert_called_once()

    @patch.object(AutonomousContentTranslationWorker, "_stop_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_heartbeat")
    @patch.object(AutonomousContentTranslationWorker, "_record_state")
    @patch.object(AutonomousContentTranslationWorker, "_start_heartbeat_thread")
    @patch.object(AutonomousContentTranslationWorker, "_write_pid_file")
    @patch("src.workers.autonomous_content_translation_worker.emit_worker_event")
    def test_config_default_is_safe(
        self, mock_emit, mock_pid, mock_hb_start, mock_record, mock_hb_write, mock_hb_stop, caplog
    ):
        """When scheduler section is missing from config, daemon must exit safely."""
        config = AutonomousWorkerConfig(mode="daemon")
        worker = AutonomousContentTranslationWorker(config)

        # Empty config — no scheduler section
        mock_cs = MagicMock()
        mock_cs._raw_global_config = {}
        worker.config_service = mock_cs

        with caplog.at_level(logging.INFO):
            worker.run()

        assert "campaign_mode_enabled=false" in caplog.text
