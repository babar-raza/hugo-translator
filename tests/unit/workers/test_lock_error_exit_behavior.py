"""
TC-LOCK-02: Unit tests for LockError exit-code behavior in oneshot mode.

Verifies:
1. _run_oneshot() calls sys.exit(1) when all content roots blocked by LockError
2. _run_oneshot() exits normally (no sys.exit(1)) when some translations succeed
   despite lock errors on other roots
3. _run_oneshot() exits normally when no lock errors and nothing new to translate
4. _process_site() increments _run_lock_errors when _translate_content_root raises LockError
"""

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

MODULE = "src.workers.autonomous_content_translation_worker"


def _make_worker():
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )

    w = AutonomousContentTranslationWorker.__new__(AutonomousContentTranslationWorker)
    w.config = MagicMock()
    w.config.mode = "oneshot"
    w.config.site = "blog.aspose.org"
    w.config_service = MagicMock()
    w.translation_engine = MagicMock()
    return w


def _patch_oneshot_side_effects(monkeypatch, worker, *, run_new_files, run_lock_errors):
    """
    Patch all side-effectful callables in _run_oneshot() so a bare __new__ instance
    can run without AttributeError. _execute_translation_run sets instance state.
    """
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )

    def fake_execute(self):
        self._run_new_files = run_new_files
        self._run_lock_errors = run_lock_errors

    monkeypatch.setattr(AutonomousContentTranslationWorker, "_preflight_check", lambda self: True)
    monkeypatch.setattr(MODULE + "._continuation_start_safe", lambda *a, **kw: False)
    monkeypatch.setattr(
        AutonomousContentTranslationWorker,
        "_commit_orphaned_translations",
        lambda self: None,
    )
    monkeypatch.setattr(
        AutonomousContentTranslationWorker, "_execute_translation_run", fake_execute
    )
    monkeypatch.setattr(
        AutonomousContentTranslationWorker,
        "_recover_pending_commits",
        lambda self: None,
    )
    monkeypatch.setattr(
        AutonomousContentTranslationWorker, "_record_run_history", lambda self: None
    )
    monkeypatch.setattr(
        AutonomousContentTranslationWorker, "_record_state", lambda self, *a, **kw: None
    )
    monkeypatch.setattr(MODULE + "._emit_run_signal_safe", lambda *a, **kw: None)


# ---------------------------------------------------------------------------
# Test 1 — All content roots locked → sys.exit(1)
# ---------------------------------------------------------------------------


def test_oneshot_exits_1_when_all_content_roots_locked(monkeypatch):
    """If _run_lock_errors > 0 and _run_total_new == 0, _run_oneshot() must sys.exit(1)."""
    w = _make_worker()
    _patch_oneshot_side_effects(monkeypatch, w, run_new_files={}, run_lock_errors=1)

    with pytest.raises(SystemExit) as exc_info:
        w._run_oneshot()

    assert exc_info.value.code == 1


def test_oneshot_exits_1_when_preflight_rejects(monkeypatch):
    """A fail-closed preflight must propagate nonzero status to a launcher."""
    w = _make_worker()
    monkeypatch.setattr(
        type(w), "_preflight_check", lambda self: False
    )
    monkeypatch.setattr(type(w), "_record_state", lambda self, *a, **kw: None)

    with pytest.raises(SystemExit) as exc_info:
        w._run_oneshot()

    assert exc_info.value.code == 1


# ---------------------------------------------------------------------------
# Test 2 — Some translations succeeded despite lock errors → normal return (no exit 1)
# ---------------------------------------------------------------------------


def test_oneshot_exits_0_when_some_translations_succeed_despite_lock_errors(monkeypatch):
    """If _run_total_new > 0 even with lock errors, exit normally — partial success."""
    w = _make_worker()
    _patch_oneshot_side_effects(
        monkeypatch, w, run_new_files={"blog.aspose.org": 3}, run_lock_errors=1
    )

    # Should NOT raise SystemExit
    w._run_oneshot()


# ---------------------------------------------------------------------------
# Test 3 — No lock errors, nothing new to translate → normal return (no exit 1)
# ---------------------------------------------------------------------------


def test_oneshot_exits_0_when_no_lock_errors_and_nothing_to_translate(monkeypatch):
    """If _run_lock_errors == 0 and _run_total_new == 0, exit normally (already up to date)."""
    w = _make_worker()
    _patch_oneshot_side_effects(monkeypatch, w, run_new_files={}, run_lock_errors=0)

    # Should NOT raise SystemExit
    w._run_oneshot()


# ---------------------------------------------------------------------------
# Test 4 — _process_site() increments _run_lock_errors on LockError
# ---------------------------------------------------------------------------


def test_process_site_increments_lock_error_counter_on_lock_error(monkeypatch):
    """When _translate_content_root raises LockError, _run_lock_errors is incremented."""
    from src.utils.file_lock import LockError
    from src.workers.autonomous_content_translation_worker import (
        AutonomousContentTranslationWorker,
    )

    w = _make_worker()
    w._run_lock_errors = 0

    # Build a minimal mock profile
    mock_profile = MagicMock()
    mock_profile.content_roots = [Path("/fake/root")]
    mock_profile.target_langs = ["de"]
    mock_profile.family_scope = None
    mock_profile.display_name = "Test Site"

    monkeypatch.setattr(
        AutonomousContentTranslationWorker,
        "_get_site_profile",
        lambda self, site_id: mock_profile,
    )
    monkeypatch.setattr(
        AutonomousContentTranslationWorker,
        "_expand_family_content_roots",
        lambda self, profile, root: [root],
    )

    def raise_lock_error(self, *a, **kw):
        raise LockError("Failed to acquire lock after 300s")

    monkeypatch.setattr(
        AutonomousContentTranslationWorker,
        "_translate_content_root",
        raise_lock_error,
    )

    w._process_site("blog.aspose.org")

    assert w._run_lock_errors == 1
