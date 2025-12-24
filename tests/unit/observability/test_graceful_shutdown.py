"""
Unit tests for graceful_shutdown module.

Tests signal handling, context registration, and graceful shutdown behavior.
All tests use mocked signals and contexts - no actual process termination.
"""

import pytest
import signal
import time
import threading
from unittest.mock import Mock, patch, MagicMock
from datetime import datetime, timezone

from src.observability.graceful_shutdown import (
    register_active_context,
    unregister_active_context,
    register_shutdown_handler,
    get_active_context_count,
    setup_graceful_shutdown,
    _perform_graceful_shutdown,
    reset_for_testing,
)


class TestContextRegistration:
    """Test suite for context registration and unregistration."""

    def setup_method(self):
        """Reset state before each test."""
        reset_for_testing()

    def test_register_context_adds_to_list(self):
        """Test that registering a context adds it to the active list."""
        mock_context = Mock()

        register_active_context(mock_context)

        assert get_active_context_count() == 1

    def test_register_multiple_contexts(self):
        """Test registering multiple contexts."""
        ctx1 = Mock(name="context1")
        ctx2 = Mock(name="context2")
        ctx3 = Mock(name="context3")

        register_active_context(ctx1)
        register_active_context(ctx2)
        register_active_context(ctx3)

        assert get_active_context_count() == 3

    def test_register_duplicate_context_ignored(self):
        """Test that duplicate registration is idempotent."""
        mock_context = Mock()

        register_active_context(mock_context)
        register_active_context(mock_context)  # Duplicate
        register_active_context(mock_context)  # Another duplicate

        assert get_active_context_count() == 1

    def test_register_none_context_ignored(self):
        """Test that None context is ignored."""
        register_active_context(None)

        assert get_active_context_count() == 0

    def test_unregister_context_removes_from_list(self):
        """Test that unregistering a context removes it."""
        mock_context = Mock()

        register_active_context(mock_context)
        assert get_active_context_count() == 1

        unregister_active_context(mock_context)
        assert get_active_context_count() == 0

    def test_unregister_only_removes_specified_context(self):
        """Test that unregistering only removes the specified context."""
        ctx1 = Mock(name="context1")
        ctx2 = Mock(name="context2")
        ctx3 = Mock(name="context3")

        register_active_context(ctx1)
        register_active_context(ctx2)
        register_active_context(ctx3)

        unregister_active_context(ctx2)

        assert get_active_context_count() == 2

    def test_unregister_nonexistent_context_safe(self):
        """Test that unregistering a non-existent context is safe."""
        ctx1 = Mock(name="context1")
        ctx2 = Mock(name="context2")

        register_active_context(ctx1)

        # Unregister context that was never registered
        unregister_active_context(ctx2)

        assert get_active_context_count() == 1

    def test_double_unregister_safe(self):
        """Test that double unregistration is safe."""
        mock_context = Mock()

        register_active_context(mock_context)
        unregister_active_context(mock_context)
        unregister_active_context(mock_context)  # Double unregister

        assert get_active_context_count() == 0


class TestThreadSafety:
    """Test suite for thread safety of context operations."""

    def setup_method(self):
        """Reset state before each test."""
        reset_for_testing()

    def test_concurrent_registration(self):
        """Test concurrent registration from multiple threads."""
        contexts = [Mock(name=f"context{i}") for i in range(100)]
        threads = []

        def register_context(ctx):
            register_active_context(ctx)

        # Start threads
        for ctx in contexts:
            thread = threading.Thread(target=register_context, args=(ctx,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        assert get_active_context_count() == 100

    def test_concurrent_registration_and_unregistration(self):
        """Test concurrent registration and unregistration."""
        contexts = [Mock(name=f"context{i}") for i in range(50)]
        threads = []

        def register_then_unregister(ctx):
            register_active_context(ctx)
            time.sleep(0.001)  # Small delay
            unregister_active_context(ctx)

        # Start threads
        for ctx in contexts:
            thread = threading.Thread(target=register_then_unregister, args=(ctx,))
            threads.append(thread)
            thread.start()

        # Wait for all threads
        for thread in threads:
            thread.join()

        assert get_active_context_count() == 0


class TestSignalHandlers:
    """Test suite for signal handler setup."""

    def setup_method(self):
        """Reset state before each test."""
        reset_for_testing()

    def test_setup_registers_signal_handlers_on_unix(self):
        """Test that setup_graceful_shutdown registers SIGINT and SIGTERM on Unix."""
        with patch('src.observability.graceful_shutdown.platform.system', return_value='Linux'):
            with patch('signal.signal') as mock_signal:
                setup_graceful_shutdown()

                # Verify SIGINT handler registered
                calls = mock_signal.call_args_list
                assert any(
                    call[0][0] == signal.SIGINT
                    for call in calls
                ), "SIGINT handler should be registered on Linux"

                # Verify SIGTERM handler registered
                assert any(
                    call[0][0] == signal.SIGTERM
                    for call in calls
                ), "SIGTERM handler should be registered on Linux"

    def test_setup_registers_signal_handlers_on_windows(self):
        """Test that setup_graceful_shutdown registers SIGINT and SIGBREAK on Windows."""
        with patch('src.observability.graceful_shutdown.platform.system', return_value='Windows'):
            with patch('signal.signal') as mock_signal:
                # Mock SIGBREAK availability
                with patch('src.observability.graceful_shutdown.signal.SIGBREAK', signal.SIGINT, create=True):
                    setup_graceful_shutdown()

                    # Verify SIGINT handler registered
                    calls = mock_signal.call_args_list
                    assert any(
                        call[0][0] == signal.SIGINT
                        for call in calls
                    ), "SIGINT handler should be registered on Windows"

    def test_setup_registers_signal_handlers_on_macos(self):
        """Test that setup_graceful_shutdown registers SIGINT and SIGTERM on macOS."""
        with patch('src.observability.graceful_shutdown.platform.system', return_value='Darwin'):
            with patch('signal.signal') as mock_signal:
                setup_graceful_shutdown()

                # Verify SIGINT handler registered
                calls = mock_signal.call_args_list
                assert any(
                    call[0][0] == signal.SIGINT
                    for call in calls
                ), "SIGINT handler should be registered on macOS"

                # Verify SIGTERM handler registered
                assert any(
                    call[0][0] == signal.SIGTERM
                    for call in calls
                ), "SIGTERM handler should be registered on macOS"

    def test_setup_handles_missing_sigbreak_on_windows(self):
        """Test graceful handling when SIGBREAK is not available on Windows."""
        with patch('src.observability.graceful_shutdown.platform.system', return_value='Windows'):
            with patch('signal.signal') as mock_signal:
                # Simulate SIGBREAK not being available
                with patch('src.observability.graceful_shutdown.hasattr', return_value=False):
                    setup_graceful_shutdown()

                    # Should still register SIGINT
                    calls = mock_signal.call_args_list
                    assert any(
                        call[0][0] == signal.SIGINT
                        for call in calls
                    ), "SIGINT handler should still be registered even without SIGBREAK"


class TestGracefulShutdown:
    """Test suite for graceful shutdown behavior."""

    def setup_method(self):
        """Reset state before each test."""
        reset_for_testing()

    def test_shutdown_closes_all_contexts(self):
        """Test that shutdown closes all active contexts."""
        # Create mock contexts with proper spec
        ctx1 = Mock(spec=['set_metrics', '__exit__', '_start_time'])
        ctx1.set_metrics = Mock()
        ctx1.__exit__ = Mock()
        ctx1._start_time = time.time()

        ctx2 = Mock(spec=['set_metrics', '__exit__', '_start_time'])
        ctx2.set_metrics = Mock()
        ctx2.__exit__ = Mock()
        ctx2._start_time = time.time()

        register_active_context(ctx1)
        register_active_context(ctx2)

        # Perform shutdown (mock sys.exit to prevent actual exit)
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify both contexts were closed
        ctx1.set_metrics.assert_called_once()
        ctx1.__exit__.assert_called_once()
        ctx2.set_metrics.assert_called_once()
        ctx2.__exit__.assert_called_once()

    def test_shutdown_sets_correct_metrics(self):
        """Test that shutdown sets correct cancellation metrics."""
        mock_context = Mock(spec=['set_metrics', '__exit__', '_start_time'])
        mock_context.set_metrics = Mock()
        mock_context.__exit__ = Mock()
        mock_context._start_time = time.time() - 5  # 5 seconds ago

        register_active_context(mock_context)

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify set_metrics called with correct arguments
        call_kwargs = mock_context.set_metrics.call_args[1]
        assert call_kwargs['run_status'] == 'cancelled'
        assert call_kwargs['duration_ms'] >= 4900  # ~5000ms
        assert call_kwargs['duration_ms'] <= 5200
        assert 'end_time' in call_kwargs
        assert 'error_summary' in call_kwargs
        assert 'SIGINT' in call_kwargs['error_summary']

    def test_shutdown_handles_context_without_start_time(self):
        """Test shutdown handles contexts without _start_time gracefully."""
        mock_context = Mock(spec=['set_metrics', '__exit__'])
        mock_context.set_metrics = Mock()
        mock_context.__exit__ = Mock()
        # No _start_time attribute - should be handled by hasattr check

        register_active_context(mock_context)

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify set_metrics called with duration_ms=0
        call_kwargs = mock_context.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 0

    def test_shutdown_extracts_partial_metrics(self):
        """Test shutdown extracts partial metrics if available."""
        mock_context = Mock(spec=['set_metrics', '__exit__', '_start_time', 'get_partial_metrics'])
        mock_context.set_metrics = Mock()
        mock_context.__exit__ = Mock()
        mock_context._start_time = time.time()
        mock_context.get_partial_metrics = Mock(return_value={
            'items_discovered': 100,
            'items_succeeded': 75,
            'items_failed': 5,
        })

        register_active_context(mock_context)

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify partial metrics included
        call_kwargs = mock_context.set_metrics.call_args[1]
        assert call_kwargs['items_discovered'] == 100
        assert call_kwargs['items_succeeded'] == 75
        assert call_kwargs['items_failed'] == 5

    def test_shutdown_handles_get_partial_metrics_exception(self):
        """Test shutdown handles exception from get_partial_metrics."""
        mock_context = Mock(spec=['set_metrics', '__exit__', '_start_time', 'get_partial_metrics'])
        mock_context.set_metrics = Mock()
        mock_context.__exit__ = Mock()
        mock_context._start_time = time.time()
        mock_context.get_partial_metrics = Mock(side_effect=Exception("Metric error"))

        register_active_context(mock_context)

        # Should not raise exception
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify context still closed
        mock_context.__exit__.assert_called_once()

    def test_shutdown_handles_context_without_set_metrics(self):
        """Test shutdown handles contexts without set_metrics method."""
        # Use MagicMock which allows arbitrary attribute assignment
        mock_context = MagicMock(spec=['__exit__'])
        mock_context.__exit__ = Mock()

        register_active_context(mock_context)

        # Should not raise exception
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify __exit__ still called
        mock_context.__exit__.assert_called_once()

    def test_shutdown_handles_context_without_exit(self):
        """Test shutdown handles contexts without __exit__ method."""
        mock_context = Mock(spec=['set_metrics', '_start_time'])
        mock_context.set_metrics = Mock()
        mock_context._start_time = time.time()

        register_active_context(mock_context)

        # Should not raise exception
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify set_metrics still called
        mock_context.set_metrics.assert_called_once()

    def test_shutdown_handles_exit_exception(self):
        """Test shutdown handles exception from context.__exit__."""
        mock_context = Mock(spec=['set_metrics', '__exit__', '_start_time'])
        mock_context.set_metrics = Mock()
        mock_context.__exit__ = Mock(side_effect=Exception("Exit error"))
        mock_context._start_time = time.time()

        register_active_context(mock_context)

        # Should not raise exception
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Verify attempt was made
        mock_context.__exit__.assert_called_once()

    def test_shutdown_clears_context_registry(self):
        """Test that shutdown clears the context registry."""
        ctx1 = Mock(spec=['set_metrics', '__exit__', '_start_time'])
        ctx1.set_metrics = Mock()
        ctx1.__exit__ = Mock()
        ctx1._start_time = time.time()

        register_active_context(ctx1)
        assert get_active_context_count() == 1

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        assert get_active_context_count() == 0

    def test_shutdown_with_no_contexts(self):
        """Test shutdown with no active contexts."""
        # Should not raise exception
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

    def test_reentrant_shutdown_exits_immediately(self):
        """Test that second signal during shutdown forces exit."""
        # Test needs fresh state but will trigger shutdown twice in same test
        # Don't register any context - we're just testing the shutdown flag behavior

        with patch('sys.exit', side_effect=SystemExit) as mock_exit:
            # First shutdown sets the flag
            try:
                _perform_graceful_shutdown(signal.SIGINT, None)
            except SystemExit:
                pass

            # Verify first shutdown completed normally
            assert mock_exit.call_count == 1
            assert mock_exit.call_args[0][0] == 0

        # Second shutdown attempt - flag is still set from first shutdown
        with patch('sys.exit', side_effect=SystemExit) as mock_exit:
            try:
                _perform_graceful_shutdown(signal.SIGINT, None)
            except SystemExit:
                pass

            # Should exit with code 1 (forced) immediately
            mock_exit.assert_called_once_with(1)

    def test_shutdown_signal_name_for_sigterm(self):
        """Test shutdown uses correct signal name for SIGTERM."""
        mock_context = Mock(spec=['set_metrics', '__exit__', '_start_time'])
        mock_context.set_metrics = Mock()
        mock_context.__exit__ = Mock()
        mock_context._start_time = time.time()

        register_active_context(mock_context)

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGTERM, None)

        # Verify error summary mentions SIGTERM
        call_kwargs = mock_context.set_metrics.call_args[1]
        assert 'SIGTERM' in call_kwargs['error_summary']


class TestShutdownHandlers:
    """Test suite for custom shutdown handlers."""

    def setup_method(self):
        """Reset state before each test."""
        reset_for_testing()

    def test_register_shutdown_handler(self):
        """Test registering a custom shutdown handler."""
        handler_called = []

        def custom_handler():
            handler_called.append(True)

        register_shutdown_handler(custom_handler)

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        assert len(handler_called) == 1

    def test_multiple_shutdown_handlers(self):
        """Test multiple shutdown handlers are called."""
        calls = []

        def handler1():
            calls.append(1)

        def handler2():
            calls.append(2)

        def handler3():
            calls.append(3)

        register_shutdown_handler(handler1)
        register_shutdown_handler(handler2)
        register_shutdown_handler(handler3)

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        assert calls == [1, 2, 3]

    def test_shutdown_handler_exception_handled(self):
        """Test that shutdown handler exceptions are handled gracefully."""
        success_calls = []

        def failing_handler():
            raise Exception("Handler error")

        def success_handler():
            success_calls.append(True)

        register_shutdown_handler(failing_handler)
        register_shutdown_handler(success_handler)

        # Should not raise exception
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Success handler should still be called
        assert len(success_calls) == 1

    def test_duplicate_handler_registration_ignored(self):
        """Test that duplicate handler registration is idempotent."""
        calls = []

        def handler():
            calls.append(1)

        register_shutdown_handler(handler)
        register_shutdown_handler(handler)  # Duplicate
        register_shutdown_handler(handler)  # Another duplicate

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Should only be called once
        assert len(calls) == 1


class TestResetForTesting:
    """Test suite for reset_for_testing helper."""

    def test_reset_clears_contexts(self):
        """Test that reset clears all contexts."""
        ctx1 = Mock()
        ctx2 = Mock()

        register_active_context(ctx1)
        register_active_context(ctx2)
        assert get_active_context_count() == 2

        reset_for_testing()

        assert get_active_context_count() == 0

    def test_reset_clears_shutdown_handlers(self):
        """Test that reset clears shutdown handlers."""
        handler_calls = []

        def handler():
            handler_calls.append(True)

        register_shutdown_handler(handler)
        reset_for_testing()

        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Handler should not be called
        assert len(handler_calls) == 0

    def test_reset_clears_shutdown_flag(self):
        """Test that reset clears shutdown in progress flag."""
        # Trigger shutdown to set flag
        with patch('sys.exit'):
            _perform_graceful_shutdown(signal.SIGINT, None)

        # Reset
        reset_for_testing()

        # Should be able to shutdown again without forced exit
        with patch('sys.exit') as mock_exit:
            _perform_graceful_shutdown(signal.SIGINT, None)
            # Should exit with 0 (normal), not 1 (forced)
            mock_exit.assert_called_with(0)
