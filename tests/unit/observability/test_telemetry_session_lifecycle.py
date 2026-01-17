"""
Tests for telemetry session lifecycle (Phase 2).

Tests verify POST/PATCH pattern, session management, cleanup, and backward compatibility
using real telemetry objects and actual session flows.
"""

import tempfile
from pathlib import Path

import pytest

from src.observability.telemetry_integration import TranslationTelemetry, DummyRunContext


# ==============================================================================
# Phase 2: Session Lifecycle Tests
# ==============================================================================


def test_start_and_complete_session_lifecycle():
    """Verify start_translation_session and complete_translation_session work together."""
    # Create real telemetry (may be disabled if client not available)
    telemetry = TranslationTelemetry(enabled=True)

    # Start session
    run_context, context_manager = telemetry.start_translation_session(
        job_type="translate_file",
        trigger_type="cli"
    )

    # Verify context returned
    assert run_context is not None
    assert context_manager is not None or isinstance(run_context, DummyRunContext)

    # If telemetry is enabled, verify session tracked
    if not isinstance(run_context, DummyRunContext):
        assert hasattr(telemetry, '_active_sessions')
        # Session should be in active sessions
        session_id = id(run_context)
        assert session_id in telemetry._active_sessions

        # Complete session
        telemetry.complete_translation_session(run_context)

        # Verify session removed from active sessions
        assert session_id not in telemetry._active_sessions


def test_context_manager_backward_compatibility():
    """Verify track_translation_session context manager still works."""
    telemetry = TranslationTelemetry(enabled=True)

    # Use context manager
    with telemetry.track_translation_session(
        job_type="translate_file",
        trigger_type="cli"
    ) as run_context:
        # Context should be returned
        assert run_context is not None


def test_disabled_telemetry_returns_dummy():
    """Verify disabled telemetry returns DummyRunContext."""
    telemetry = TranslationTelemetry(enabled=False)

    run_context, context_manager = telemetry.start_translation_session(
        job_type="translate_file",
        trigger_type="cli"
    )

    # Should get dummy context
    assert isinstance(run_context, DummyRunContext)
    assert context_manager is None


def test_complete_session_handles_missing_context():
    """Verify complete_translation_session handles unknown context gracefully."""
    telemetry = TranslationTelemetry(enabled=True)

    # Create a fake context not from start_translation_session
    fake_context = type('FakeContext', (), {'event_id': 'fake-123'})()

    # Should not crash
    telemetry.complete_translation_session(fake_context)


def test_session_with_file_path():
    """Test session creation with real file path."""
    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
        f.write("# Test Content")
        test_file = Path(f.name)

    try:
        telemetry = TranslationTelemetry(enabled=True)

        run_context, cm = telemetry.start_translation_session(
            job_type="translate_file",
            trigger_type="cli",
            file_path=test_file,
            target_langs=["fr"]
        )

        assert run_context is not None

        # Complete session
        if not isinstance(run_context, DummyRunContext):
            telemetry.complete_translation_session(run_context)

    finally:
        test_file.unlink()


def test_concurrent_session_management():
    """
    Test thread safety of session management with concurrent access.

    Verifies that multiple threads can start and complete sessions
    concurrently without race conditions or data corruption.
    """
    import threading

    telemetry = TranslationTelemetry(enabled=True)
    errors = []

    def start_and_complete_session(thread_id: int):
        """Worker function that starts and completes a session."""
        try:
            run_context, cm = telemetry.start_translation_session(
                job_type="translate_file",
                trigger_type="cli",
                file_path=Path(f"/test/file_{thread_id}.md")
            )

            # Simulate some work
            import time
            time.sleep(0.01)

            # Complete session
            if not isinstance(run_context, DummyRunContext):
                telemetry.complete_translation_session(run_context)
        except Exception as e:
            errors.append((thread_id, str(e)))

    # Spawn 10 threads that start and complete sessions concurrently
    threads = []
    num_threads = 10

    for i in range(num_threads):
        t = threading.Thread(target=start_and_complete_session, args=(i,))
        threads.append(t)
        t.start()

    # Wait for all threads to complete
    for t in threads:
        t.join()

    # Verify no errors occurred
    assert len(errors) == 0, f"Thread errors: {errors}"

    # Verify all sessions cleaned up (only if telemetry enabled)
    if telemetry.enabled and hasattr(telemetry, '_active_sessions'):
        assert len(telemetry._active_sessions) == 0, \
            f"Expected 0 active sessions, found {len(telemetry._active_sessions)}"


def test_session_auto_cleanup_on_gc():
    """
    Verify _active_sessions cleaned when run_context garbage collected.

    TC-CLEAN-01: Tests GAP-04 fix - weakref-based cleanup ensures that
    if run_context is garbage collected before complete_translation_session()
    is called, the _active_sessions entry is automatically removed.
    """
    import gc

    telemetry = TranslationTelemetry(enabled=True)

    # Start a session
    run_context, cm = telemetry.start_translation_session(
        job_type="translate_file",
        trigger_type="cli"
    )

    # Skip test if telemetry is disabled (returns DummyRunContext)
    if isinstance(run_context, DummyRunContext):
        pytest.skip("Telemetry disabled, cannot test weakref cleanup")

    # Verify session is tracked
    session_id = id(run_context)
    assert session_id in telemetry._active_sessions, \
        "Session should be in _active_sessions after start"

    # Delete the run_context reference (simulates exception/leak scenario)
    del run_context
    del cm

    # Force garbage collection
    gc.collect()

    # Verify session was auto-cleaned
    assert session_id not in telemetry._active_sessions, \
        "Session should be auto-cleaned from _active_sessions after gc"
