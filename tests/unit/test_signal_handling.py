"""
SR-01: Unit tests for unified signal handling.

Tests that the unified signal handler properly coordinates:
1. Handler registration (exactly once per signal)
2. Cleanup sequence (telemetry → engine → exit)
3. Force-exit on second signal
"""

import signal
import time
from unittest.mock import Mock, patch

import pytest


def test_unified_handler_registration_count():
    """Test that exactly one handler is registered per signal."""
    from src.cli import setup_unified_signal_handler

    # Create mock engine
    mock_engine = Mock()
    mock_engine.request_shutdown = Mock()

    # Track signal.signal calls
    original_signal = signal.signal
    signal_calls = []

    def track_signal_call(sig, handler):
        signal_calls.append((sig, handler))
        return original_signal(sig, handler)

    with patch('signal.signal', side_effect=track_signal_call):
        setup_unified_signal_handler(mock_engine)

    # Should register SIGINT and SIGTERM (always)
    registered_signals = [sig for sig, _ in signal_calls]
    assert signal.SIGINT in registered_signals, "SIGINT should be registered"
    assert signal.SIGTERM in registered_signals, "SIGTERM should be registered"

    # Count registrations per signal (should be exactly 1)
    for sig in [signal.SIGINT, signal.SIGTERM]:
        count = sum(1 for s, _ in signal_calls if s == sig)
        assert count == 1, f"Signal {sig} registered {count} times, expected 1"


def test_unified_handler_windows_platform():
    """Test that SIGBREAK is registered on Windows."""
    from src.cli import setup_unified_signal_handler

    mock_engine = Mock()
    signal_calls = []

    def track_signal_call(sig, handler):
        signal_calls.append(sig)
        # Don't actually register to avoid side effects
        return lambda *args: None

    with patch('signal.signal', side_effect=track_signal_call):
        with patch('platform.system', return_value='Windows'):
            setup_unified_signal_handler(mock_engine)

    # On Windows, should register SIGINT, SIGTERM, and SIGBREAK
    assert signal.SIGINT in signal_calls
    assert signal.SIGTERM in signal_calls
    if hasattr(signal, 'SIGBREAK'):
        assert signal.SIGBREAK in signal_calls


def test_unified_handler_unix_platform():
    """Test that SIGBREAK is NOT registered on Unix."""
    from src.cli import setup_unified_signal_handler

    mock_engine = Mock()
    signal_calls = []

    def track_signal_call(sig, handler):
        signal_calls.append(sig)
        return lambda *args: None

    with patch('signal.signal', side_effect=track_signal_call):
        with patch('platform.system', return_value='Linux'):
            setup_unified_signal_handler(mock_engine)

    # On Linux, should register SIGINT and SIGTERM only
    assert signal.SIGINT in signal_calls
    assert signal.SIGTERM in signal_calls
    if hasattr(signal, 'SIGBREAK'):
        assert signal.SIGBREAK not in signal_calls


def test_cleanup_sequence_order():
    """Test that cleanup happens before engine shutdown."""
    from src.cli import setup_unified_signal_handler

    mock_engine = Mock()
    mock_engine.request_shutdown = Mock()

    call_order = []

    def mock_cleanup(*args, **kwargs):
        call_order.append('cleanup')

    def mock_request_shutdown():
        call_order.append('engine_shutdown')

    mock_engine.request_shutdown = mock_request_shutdown

    # Capture the handler
    captured_handler = None

    def capture_handler(sig, handler):
        nonlocal captured_handler
        if sig == signal.SIGINT:
            captured_handler = handler
        return lambda *args: None

    with patch('signal.signal', side_effect=capture_handler):
        with patch('src.observability.graceful_shutdown.cleanup_telemetry_contexts', side_effect=mock_cleanup):
            setup_unified_signal_handler(mock_engine)

    # Simulate SIGINT
    if captured_handler:
        captured_handler(signal.SIGINT, None)

    # Verify order: cleanup → engine shutdown
    assert call_order == ['cleanup', 'engine_shutdown'], \
        f"Expected ['cleanup', 'engine_shutdown'], got {call_order}"


def test_force_exit_on_second_signal():
    """Test that second signal triggers immediate exit with code 130."""
    from src.cli import setup_unified_signal_handler

    mock_engine = Mock()
    mock_engine.request_shutdown = Mock()

    # Capture the handler
    captured_handler = None

    def capture_handler(sig, handler):
        nonlocal captured_handler
        if sig == signal.SIGINT:
            captured_handler = handler
        return lambda *args: None

    with patch('signal.signal', side_effect=capture_handler):
        with patch('src.observability.graceful_shutdown.cleanup_telemetry_contexts'):
            setup_unified_signal_handler(mock_engine)

    # First signal: should call cleanup and engine shutdown
    if captured_handler:
        captured_handler(signal.SIGINT, None)
        assert mock_engine.request_shutdown.called

    # Second signal: should exit with code 130
    with pytest.raises(SystemExit) as exc_info:
        captured_handler(signal.SIGINT, None)

    assert exc_info.value.code == 130, \
        f"Expected exit code 130, got {exc_info.value.code}"


def test_cleanup_error_handling():
    """Test that engine shutdown proceeds even if cleanup fails."""
    from src.cli import setup_unified_signal_handler

    mock_engine = Mock()
    mock_engine.request_shutdown = Mock()

    def mock_cleanup_error(*args, **kwargs):
        raise Exception("Telemetry cleanup failed")

    # Capture the handler
    captured_handler = None

    def capture_handler(sig, handler):
        nonlocal captured_handler
        if sig == signal.SIGINT:
            captured_handler = handler
        return lambda *args: None

    with patch('signal.signal', side_effect=capture_handler):
        with patch('src.observability.graceful_shutdown.cleanup_telemetry_contexts', side_effect=mock_cleanup_error):
            setup_unified_signal_handler(mock_engine)

    # Signal should still trigger engine shutdown even if cleanup fails
    if captured_handler:
        captured_handler(signal.SIGINT, None)

    # Engine shutdown should still be called
    assert mock_engine.request_shutdown.called, \
        "Engine shutdown should be called even if telemetry cleanup fails"


def test_graceful_shutdown_cleanup_function():
    """Test the cleanup_telemetry_contexts function directly."""
    from src.observability.graceful_shutdown import (
        _active_contexts,
        cleanup_telemetry_contexts,
        register_active_context,
    )

    # Clear any existing contexts
    _active_contexts.clear()

    # Create mock context with proper partial_metrics
    mock_context = Mock()
    mock_context.set_metrics = Mock()
    mock_context.__exit__ = Mock(return_value=None)
    mock_context._start_time = time.time()
    mock_context.get_partial_metrics = Mock(return_value={})  # Return empty dict

    # Register context
    register_active_context(mock_context)

    # Call cleanup
    cleanup_telemetry_contexts("SIGINT")

    # Verify context was closed
    assert mock_context.set_metrics.called, "set_metrics should be called"
    assert mock_context.__exit__.called, "Context __exit__ should be called"

    # Verify metrics set with correct status
    call_args = mock_context.set_metrics.call_args
    assert call_args is not None
    assert call_args[1]['run_status'] == 'cancelled'
    assert 'SIGINT' in call_args[1]['error_summary']


def test_legacy_setup_signal_handlers_delegates():
    """Test that legacy setup_signal_handlers delegates to unified handler."""
    from src.cli import setup_signal_handlers

    mock_engine = Mock()

    with patch('src.cli.setup_unified_signal_handler') as mock_unified:
        setup_signal_handlers(mock_engine)

    # Verify delegation
    mock_unified.assert_called_once_with(mock_engine)


def test_legacy_setup_graceful_shutdown_warns():
    """Test that legacy setup_graceful_shutdown logs deprecation warning."""
    from src.observability.graceful_shutdown import setup_graceful_shutdown

    with patch('signal.signal'):  # Prevent actual registration
        with patch('src.observability.graceful_shutdown.logger') as mock_logger:
            setup_graceful_shutdown()

    # Verify deprecation warning logged
    warning_calls = [call for call in mock_logger.warning.call_args_list
                     if 'deprecated' in str(call).lower()]
    assert len(warning_calls) > 0, "Deprecation warning should be logged"
