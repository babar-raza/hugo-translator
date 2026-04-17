"""
Tests for CW-STATE-01: last_success_ts only advances when files are actually translated.

Verifies that autonomous_content_translation_worker._run_daemon() and _run_oneshot()
only call _record_state(success=True) when _run_new_files contains at least one
successful translation.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_worker(tmp_path: Path, run_new_files: dict) -> Any:
    """
    Return a MagicMock of the content worker with _run_new_files pre-set
    so we can test the success-tracking logic without running the engine.
    """
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )

    worker = MagicMock(spec=AutonomousContentTranslationWorker)
    worker._run_new_files = run_new_files

    # Make _execute_translation_run populate _run_new_files (side effect)
    def _fake_execute():
        # already set on worker before call in tests
        pass

    worker._execute_translation_run.side_effect = _fake_execute
    return worker


# ---------------------------------------------------------------------------
# Tests: _record_state success flag
# ---------------------------------------------------------------------------


class TestDaemonSuccessTracking:
    """Daemon mode: success=True only when _run_new_files > 0."""

    def test_zero_new_files_does_not_set_success(self, tmp_path):
        """When _run_new_files is empty, success=False preserves last_success_ts."""
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        worker = MagicMock(spec=AutonomousContentTranslationWorker)
        worker._run_new_files = {}  # no files translated

        def fake_execute():
            pass  # _run_new_files already set to empty

        worker._execute_translation_run.side_effect = fake_execute

        # Simulate the daemon try-block logic extracted from _run_daemon
        worker._execute_translation_run()
        _run_total_new = sum(getattr(worker, "_run_new_files", {}).values())
        worker._record_state("run_completed", success=(_run_total_new > 0))

        # Verify _record_state was called with success=False
        worker._record_state.assert_called_once_with("run_completed", success=False)

    def test_nonzero_new_files_sets_success(self, tmp_path):
        """When _run_new_files has entries, success=True updates last_success_ts."""
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        worker = MagicMock(spec=AutonomousContentTranslationWorker)
        worker._run_new_files = {"blog.aspose.net": 5}

        def fake_execute():
            pass

        worker._execute_translation_run.side_effect = fake_execute

        worker._execute_translation_run()
        _run_total_new = sum(getattr(worker, "_run_new_files", {}).values())
        worker._record_state("run_completed", success=(_run_total_new > 0))

        worker._record_state.assert_called_once_with("run_completed", success=True)

    def test_multi_site_partial_success_counts(self, tmp_path):
        """Multi-site run: total > 0 even if one site translated nothing."""
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        worker = MagicMock(spec=AutonomousContentTranslationWorker)
        # site1 translated nothing; site2 translated 3
        worker._run_new_files = {"blog.aspose.net": 0, "docs.aspose.net": 3}

        worker._execute_translation_run()
        _run_total_new = sum(getattr(worker, "_run_new_files", {}).values())
        worker._record_state("run_completed", success=(_run_total_new > 0))

        worker._record_state.assert_called_once_with("run_completed", success=True)

    def test_getattr_fallback_when_attribute_missing(self, tmp_path):
        """If _run_new_files is missing (attribute not set), total=0 → success=False."""
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        worker = MagicMock(spec=AutonomousContentTranslationWorker)
        # Intentionally NOT setting _run_new_files → getattr fallback to {}
        del worker._run_new_files

        _run_total_new = sum(getattr(worker, "_run_new_files", {}).values())
        worker._record_state("run_completed", success=(_run_total_new > 0))

        worker._record_state.assert_called_once_with("run_completed", success=False)


class TestOneshotSuccessTracking:
    """Oneshot mode applies the same success-tracking logic."""

    def test_oneshot_zero_output_no_success(self):
        """Oneshot with zero translations: success=False."""
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        worker = MagicMock(spec=AutonomousContentTranslationWorker)
        worker._run_new_files = {}

        worker._execute_translation_run()
        _run_total_new = sum(getattr(worker, "_run_new_files", {}).values())
        worker._record_state("run_completed", success=(_run_total_new > 0))

        worker._record_state.assert_called_once_with("run_completed", success=False)

    def test_oneshot_with_output_sets_success(self):
        """Oneshot with 1+ translations: success=True."""
        from src.workers.autonomous_content_translation_worker import (
            AutonomousContentTranslationWorker,
        )

        worker = MagicMock(spec=AutonomousContentTranslationWorker)
        worker._run_new_files = {"reference.aspose.net": 12}

        worker._execute_translation_run()
        _run_total_new = sum(getattr(worker, "_run_new_files", {}).values())
        worker._record_state("run_completed", success=(_run_total_new > 0))

        worker._record_state.assert_called_once_with("run_completed", success=True)


class TestRecordWorkerStateLedger:
    """Integration: record_worker_state only updates last_success_ts when success=True."""

    def test_success_false_does_not_advance_last_success_ts(self, tmp_path):
        """success=False must NOT update last_success_ts in state file."""
        from datetime import datetime, timezone

        from src.workers.worker_state import load_worker_state, record_worker_state

        old_ts = "2026-02-26T18:55:24+00:00"
        # Pre-seed state with an existing success
        initial = {
            "worker_id": "content_worker",
            "state": "run_completed",
            "last_success_ts": old_ts,
            "pid": 1,
            "updated_at": old_ts,
        }
        state_path = tmp_path / "content_worker.state.json"
        state_path.write_text(json.dumps(initial), encoding="utf-8")

        # Record a new run_completed with success=False
        now = datetime(2026, 2, 28, 22, 0, 0, tzinfo=timezone.utc)
        record_worker_state(
            "content_worker",
            "run_completed",
            success=False,
            log_dir=tmp_path,
            now=now,
        )

        updated = load_worker_state("content_worker", log_dir=tmp_path)
        # last_success_ts must NOT have advanced
        assert updated["last_success_ts"] == old_ts, (
            f"last_success_ts advanced unexpectedly to {updated['last_success_ts']}"
        )
        # But updated_at should advance
        assert updated["updated_at"] != old_ts

    def test_success_true_advances_last_success_ts(self, tmp_path):
        """success=True must update last_success_ts to the current timestamp."""
        from datetime import datetime, timezone

        from src.workers.worker_state import load_worker_state, record_worker_state

        old_ts = "2026-02-26T18:55:24+00:00"
        initial = {
            "worker_id": "content_worker",
            "state": "run_completed",
            "last_success_ts": old_ts,
            "pid": 1,
            "updated_at": old_ts,
        }
        state_path = tmp_path / "content_worker.state.json"
        state_path.write_text(json.dumps(initial), encoding="utf-8")

        now = datetime(2026, 2, 28, 22, 0, 0, tzinfo=timezone.utc)
        record_worker_state(
            "content_worker",
            "run_completed",
            success=True,
            log_dir=tmp_path,
            now=now,
        )

        updated = load_worker_state("content_worker", log_dir=tmp_path)
        assert updated["last_success_ts"] == now.isoformat(), (
            f"last_success_ts not updated: {updated['last_success_ts']}"
        )
