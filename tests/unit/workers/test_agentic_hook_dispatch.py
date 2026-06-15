"""TC-INTEG-01: Prove agentic hooks dispatch to target modules when enabled.

These tests verify that the _safe() wrapper functions in the worker
actually call their target module functions when config is enabled.
This closes the gap between "hooks exist" and "hooks work when enabled".
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock, patch

import pytest

from src.workers.autonomous_content_translation_worker import (
    _continuation_complete_safe,
    _continuation_fail_safe,
    _continuation_start_safe,
    _emit_run_signal_safe,
)


def _make_config_service(overrides: dict) -> MagicMock:
    """Create a mock ConfigService with specified module configs."""
    base = {
        "run_signal_emitter": {"enabled": False},
        "continuation_state": {"enabled": False},
    }
    base.update(overrides)
    svc = MagicMock()
    svc.get_config.return_value = base
    return svc


class TestEmitRunSignalSafe:
    """Verify _emit_run_signal_safe dispatches when enabled."""

    def test_skips_when_disabled(self):
        svc = _make_config_service({})
        with patch("src.observability.run_signal_emitter.emit_run_signal") as mock_emit:
            _emit_run_signal_safe(
                site_id="test",
                run_new_files={"de": 3},
                run_rejected=1,
                run_attempted=4,
                run_start=time.time(),
                config_service=svc,
            )
            mock_emit.assert_not_called()

    def test_dispatches_when_enabled(self):
        svc = _make_config_service({"run_signal_emitter": {"enabled": True}})
        with (
            patch("src.observability.run_signal_emitter.emit_run_signal") as mock_emit,
            patch("src.observability.run_signal_emitter.build_signal_from_run_stats") as mock_build,
        ):
            mock_build.return_value = {"test": "signal"}
            _emit_run_signal_safe(
                site_id="docs.aspose.net",
                run_new_files={"de": 5, "fr": 3},
                run_rejected=2,
                run_attempted=10,
                run_start=time.time(),
                config_service=svc,
            )
            mock_build.assert_called_once()
            mock_emit.assert_called_once_with({"test": "signal"})
            # Verify stats dict passed to build_signal_from_run_stats
            call_kwargs = mock_build.call_args
            assert call_kwargs[1]["site_id"] == "docs.aspose.net"


class TestContinuationStartSafe:
    """Verify _continuation_start_safe dispatches when enabled."""

    def test_returns_false_when_disabled(self):
        svc = _make_config_service({})
        result = _continuation_start_safe("run-1", "test", ["de"], svc)
        assert result is False

    def test_dispatches_when_enabled(self):
        svc = _make_config_service({"continuation_state": {"enabled": True}})
        with patch("src.workers.continuation_state.start_run") as mock_start:
            result = _continuation_start_safe("run-123", "docs.aspose.net", ["de", "fr"], svc)
            assert result is True
            mock_start.assert_called_once_with("run-123", "docs.aspose.net", ["de", "fr"])


class TestContinuationCompleteSafe:
    """Verify _continuation_complete_safe dispatches when enabled."""

    def test_skips_when_disabled(self):
        svc = _make_config_service({})
        with patch("src.workers.continuation_state.complete_run") as mock_complete:
            _continuation_complete_safe(files_accepted=5, files_rejected=2, config_service=svc)
            mock_complete.assert_not_called()

    def test_dispatches_when_enabled(self):
        svc = _make_config_service({"continuation_state": {"enabled": True}})
        with patch("src.workers.continuation_state.complete_run") as mock_complete:
            _continuation_complete_safe(files_accepted=5, files_rejected=2, config_service=svc)
            mock_complete.assert_called_once_with(
                files_processed=7,
                files_accepted=5,
                files_rejected=2,
            )


class TestContinuationFailSafe:
    """Verify _continuation_fail_safe dispatches when enabled."""

    def test_skips_when_disabled(self):
        svc = _make_config_service({})
        with patch("src.workers.continuation_state.fail_run") as mock_fail:
            _continuation_fail_safe("timeout", svc)
            mock_fail.assert_not_called()

    def test_dispatches_when_enabled(self):
        svc = _make_config_service({"continuation_state": {"enabled": True}})
        with patch("src.workers.continuation_state.fail_run") as mock_fail:
            _continuation_fail_safe("OOM error", svc)
            mock_fail.assert_called_once_with(error="OOM error")


class TestHookExceptionSafety:
    """Verify hooks never propagate exceptions."""

    def test_emit_signal_swallows_exception(self):
        svc = _make_config_service({"run_signal_emitter": {"enabled": True}})
        with patch(
            "src.observability.run_signal_emitter.build_signal_from_run_stats",
            side_effect=RuntimeError("boom"),
        ):
            # Must not raise
            _emit_run_signal_safe(
                site_id="test",
                run_new_files={},
                run_rejected=0,
                run_attempted=0,
                run_start=time.time(),
                config_service=svc,
            )

    def test_continuation_start_swallows_exception(self):
        svc = _make_config_service({"continuation_state": {"enabled": True}})
        with patch(
            "src.workers.continuation_state.start_run",
            side_effect=RuntimeError("boom"),
        ):
            result = _continuation_start_safe("r1", "s1", ["de"], svc)
            assert result is False
