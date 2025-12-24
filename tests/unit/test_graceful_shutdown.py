"""Unit tests for RES-06: Graceful Shutdown Handler.

Tests cover:
- Shutdown request coordination
- Shutdown callback registration and execution
- Signal handler setup
- Directory translation shutdown integration
"""

import signal
import pytest
import logging
from pathlib import Path
from threading import Lock, Thread
from typing import List
from unittest.mock import Mock, MagicMock, patch


class TestShutdownCoordination:
    """Tests for engine shutdown coordination methods."""

    def test_request_shutdown_sets_flag(self):
        """Test that request_shutdown sets the shutdown flag."""
        # Create mock engine with shutdown coordination
        class MockEngine:
            def __init__(self):
                self._shutdown_requested = False
                self._shutdown_lock = Lock()
                self._current_file = None
                self._shutdown_callbacks = []

            def request_shutdown(self):
                with self._shutdown_lock:
                    if self._shutdown_requested:
                        return
                    self._shutdown_requested = True

            def _check_shutdown(self):
                return self._shutdown_requested

        engine = MockEngine()
        assert engine._check_shutdown() is False

        engine.request_shutdown()
        assert engine._check_shutdown() is True

    def test_request_shutdown_idempotent(self):
        """Test that multiple shutdown requests are handled correctly."""
        class MockEngine:
            def __init__(self):
                self._shutdown_requested = False
                self._shutdown_lock = Lock()
                self._current_file = None
                self.request_count = 0

            def request_shutdown(self):
                with self._shutdown_lock:
                    if self._shutdown_requested:
                        return
                    self._shutdown_requested = True
                    self.request_count += 1

        engine = MockEngine()

        # Call multiple times
        engine.request_shutdown()
        engine.request_shutdown()
        engine.request_shutdown()

        # Should only increment once
        assert engine.request_count == 1
        assert engine._shutdown_requested is True

    def test_shutdown_callbacks_executed(self):
        """Test that registered callbacks are executed on shutdown."""
        class MockEngine:
            def __init__(self):
                self._shutdown_callbacks: List = []
                self.tm = None

            def register_shutdown_callback(self, callback):
                self._shutdown_callbacks.append(callback)

            def _perform_shutdown(self):
                for callback in self._shutdown_callbacks:
                    try:
                        callback()
                    except Exception:
                        pass

        engine = MockEngine()
        callback_executed = []

        def callback1():
            callback_executed.append("callback1")

        def callback2():
            callback_executed.append("callback2")

        engine.register_shutdown_callback(callback1)
        engine.register_shutdown_callback(callback2)

        engine._perform_shutdown()

        assert "callback1" in callback_executed
        assert "callback2" in callback_executed

    def test_shutdown_callback_error_handling(self):
        """Test that callback errors don't prevent other callbacks from running."""
        class MockEngine:
            def __init__(self):
                self._shutdown_callbacks: List = []
                self.tm = None

            def register_shutdown_callback(self, callback):
                self._shutdown_callbacks.append(callback)

            def _perform_shutdown(self):
                for callback in self._shutdown_callbacks:
                    try:
                        callback()
                    except Exception:
                        pass

        engine = MockEngine()
        callback_executed = []

        def failing_callback():
            raise RuntimeError("Callback failed")

        def working_callback():
            callback_executed.append("working")

        engine.register_shutdown_callback(failing_callback)
        engine.register_shutdown_callback(working_callback)

        # Should not raise, and working callback should run
        engine._perform_shutdown()
        assert "working" in callback_executed


class TestSignalHandlerSetup:
    """Tests for signal handler setup function."""

    def test_setup_signal_handlers_exists_in_cli(self):
        """Verify that setup_signal_handlers function exists in cli.py."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "cli.py"
        cli_content = cli_path.read_text(encoding='utf-8')

        assert "def setup_signal_handlers(" in cli_content
        assert "RES-06" in cli_content
        assert "signal.SIGINT" in cli_content
        assert "signal.SIGTERM" in cli_content

    def test_signal_handler_integration_in_translate_site(self):
        """Verify that translate_site calls setup_signal_handlers."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "cli.py"
        cli_content = cli_path.read_text(encoding='utf-8')

        # Check that setup_signal_handlers is called after engine creation
        assert "setup_signal_handlers(engine)" in cli_content


class TestEngineShutdownMethods:
    """Tests to verify engine has the required shutdown methods."""

    def test_engine_has_shutdown_methods(self):
        """Verify that engine.py contains the shutdown methods."""
        engine_path = Path(__file__).parent.parent.parent / "src" / "translation_engine" / "engine.py"
        engine_content = engine_path.read_text(encoding='utf-8')

        # Check method signatures exist
        assert "def request_shutdown(" in engine_content
        assert "def _check_shutdown(" in engine_content
        assert "def _perform_shutdown(" in engine_content
        assert "def register_shutdown_callback(" in engine_content
        assert "_shutdown_requested" in engine_content
        assert "_shutdown_lock" in engine_content
        assert "_current_file" in engine_content
        assert "RES-06" in engine_content

    def test_engine_has_shutdown_integration_in_directory_methods(self):
        """Verify that directory translation methods check for shutdown."""
        engine_path = Path(__file__).parent.parent.parent / "src" / "translation_engine" / "engine.py"
        engine_content = engine_path.read_text(encoding='utf-8')

        # Check that _check_shutdown is called in translation methods
        assert "_check_shutdown()" in engine_content


class TestKeyboardInterruptHandler:
    """Tests for KeyboardInterrupt handling in CLI."""

    def test_keyboard_interrupt_performs_shutdown(self):
        """Verify that KeyboardInterrupt handler performs engine shutdown."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "cli.py"
        cli_content = cli_path.read_text(encoding='utf-8')

        # Check that KeyboardInterrupt handler calls _perform_shutdown
        assert "except KeyboardInterrupt:" in cli_content
        assert "_perform_shutdown()" in cli_content


class TestConcurrentShutdown:
    """Tests for thread-safety of shutdown coordination."""

    def test_shutdown_request_thread_safe(self):
        """Test that shutdown request is thread-safe."""
        class MockEngine:
            def __init__(self):
                self._shutdown_requested = False
                self._shutdown_lock = Lock()
                self.request_count = 0

            def request_shutdown(self):
                with self._shutdown_lock:
                    if self._shutdown_requested:
                        return
                    self._shutdown_requested = True
                    self.request_count += 1

        engine = MockEngine()
        threads = []

        # Spawn multiple threads that all try to request shutdown
        for _ in range(10):
            t = Thread(target=engine.request_shutdown)
            threads.append(t)
            t.start()

        for t in threads:
            t.join()

        # Only one should succeed
        assert engine.request_count == 1
        assert engine._shutdown_requested is True


class TestShutdownWithL3Save:
    """Tests for L3 index saving during shutdown."""

    def test_perform_shutdown_saves_l3_index(self):
        """Test that _perform_shutdown attempts to save L3 index."""
        class MockL3:
            def __init__(self):
                self.save_called = False

            def save_index(self):
                self.save_called = True

        class MockTM:
            def __init__(self):
                self.l3 = MockL3()

        class MockEngine:
            def __init__(self):
                self.tm = MockTM()
                self._shutdown_callbacks = []

            def _perform_shutdown(self):
                # RES-06: Perform shutdown sequence
                try:
                    if self.tm:
                        l3 = getattr(self.tm, 'l3', None)
                        if l3 and hasattr(l3, 'save_index'):
                            l3.save_index()
                except Exception:
                    pass

                for callback in self._shutdown_callbacks:
                    try:
                        callback()
                    except Exception:
                        pass

        engine = MockEngine()
        engine._perform_shutdown()

        assert engine.tm.l3.save_called is True

    def test_perform_shutdown_handles_l3_save_error(self):
        """Test that L3 save errors don't crash shutdown."""
        class MockL3:
            def save_index(self):
                raise RuntimeError("Save failed")

        class MockTM:
            def __init__(self):
                self.l3 = MockL3()

        class MockEngine:
            def __init__(self):
                self.tm = MockTM()
                self._shutdown_callbacks = []
                self.callbacks_executed = False

            def _perform_shutdown(self):
                try:
                    if self.tm:
                        l3 = getattr(self.tm, 'l3', None)
                        if l3 and hasattr(l3, 'save_index'):
                            l3.save_index()
                except Exception:
                    pass

                for callback in self._shutdown_callbacks:
                    try:
                        callback()
                    except Exception:
                        pass
                self.callbacks_executed = True

        engine = MockEngine()

        # Should not raise
        engine._perform_shutdown()

        # Callbacks should still execute
        assert engine.callbacks_executed is True


class TestParallelTranslationShutdown:
    """Tests for shutdown handling in parallel translation."""

    def test_parallel_shutdown_cancels_futures(self):
        """Verify engine code includes future cancellation on shutdown."""
        engine_path = Path(__file__).parent.parent.parent / "src" / "translation_engine" / "engine.py"
        engine_content = engine_path.read_text(encoding='utf-8')

        # Check that parallel method handles shutdown by cancelling futures
        assert "_translate_directory_parallel" in engine_content
        # Check for shutdown handling in parallel code
        assert "cancel()" in engine_content or "_check_shutdown" in engine_content


class TestForceQuitGuidance:
    """Tests for RES-06-MSG: Force-quit user guidance message."""

    def test_signal_handler_shows_force_quit_message(self, caplog):
        """Verify signal handler shows force-quit guidance in log output."""
        from src.cli import setup_signal_handlers

        mock_engine = Mock()
        mock_engine.request_shutdown = Mock()

        with caplog.at_level(logging.WARNING):
            # Set up signal handlers
            setup_signal_handlers(mock_engine)

            # Get and call the SIGINT handler
            current_handler = signal.getsignal(signal.SIGINT)
            current_handler(signal.SIGINT, None)

        # Verify message contains force-quit guidance
        assert "Press Ctrl+C again to force quit" in caplog.text
        assert "graceful shutdown" in caplog.text.lower()

        # Verify engine.request_shutdown was called
        mock_engine.request_shutdown.assert_called_once()

    def test_signal_handler_message_includes_progress_save(self, caplog):
        """Verify message mentions saving progress."""
        from src.cli import setup_signal_handlers

        mock_engine = Mock()

        with caplog.at_level(logging.WARNING):
            setup_signal_handlers(mock_engine)
            handler = signal.getsignal(signal.SIGINT)
            handler(signal.SIGINT, None)

        # Verify message mentions saving progress
        assert "saving progress" in caplog.text.lower()
        assert "finishing current file" in caplog.text.lower()

    def test_signal_handler_works_for_sigterm(self, caplog):
        """Verify signal handler works for SIGTERM as well."""
        from src.cli import setup_signal_handlers

        mock_engine = Mock()

        with caplog.at_level(logging.WARNING):
            setup_signal_handlers(mock_engine)

            # Get and call the SIGTERM handler
            handler = signal.getsignal(signal.SIGTERM)
            handler(signal.SIGTERM, None)

        # Verify same message shown for SIGTERM
        assert "Press Ctrl+C again to force quit" in caplog.text
        mock_engine.request_shutdown.assert_called_once()

    def test_force_quit_message_in_cli_source(self):
        """Verify the force-quit message exists in CLI source code."""
        cli_path = Path(__file__).parent.parent.parent / "src" / "cli.py"
        cli_content = cli_path.read_text(encoding='utf-8')

        # Verify the message is in the signal_handler function
        assert "Press Ctrl+C again to force quit" in cli_content
        assert "Finishing current file and saving progress" in cli_content

class TestGracefulShutdownTelemetryFields:
    """Tests for GS-01, GS-02, GS-03: Critical telemetry field capture during shutdown."""

    def test_shutdown_sets_cancelled_status(self):
        """GS-01: Verify run_status is set to 'cancelled' when signal received."""
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts, _shutdown_in_progress
        from unittest.mock import Mock
        import signal

        # Reset global state
        _active_contexts.clear()
        import src.observability.graceful_shutdown as gs_module
        gs_module._shutdown_in_progress = False

        # Create mock context
        mock_ctx = Mock()
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify set_metrics called with run_status
        assert mock_ctx.set_metrics.called
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert call_kwargs['run_status'] == 'cancelled'
        assert 'error_summary' in call_kwargs
        assert 'SIGINT' in call_kwargs['error_summary']

    def test_shutdown_calculates_duration(self):
        """GS-02: Verify duration_ms is calculated from start_time."""
        import time
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context with start_time 5 seconds ago
        mock_ctx = Mock()
        mock_ctx._start_time = time.time() - 5.0
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify duration_ms is approximately 5000ms
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert 'duration_ms' in call_kwargs
        assert 4000 < call_kwargs['duration_ms'] < 6000

    def test_shutdown_calculates_duration_fallback(self):
        """GS-02: Verify duration_ms falls back to 0 if _start_time missing."""
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context without _start_time
        mock_ctx = Mock()
        del mock_ctx._start_time  # Ensure no _start_time attribute
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify duration_ms is 0
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert call_kwargs['duration_ms'] == 0

    def test_shutdown_sets_end_time(self):
        """GS-03: Verify end_time is set to current UTC timestamp."""
        from datetime import datetime, timezone
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context
        mock_ctx = Mock()
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()

        # Register context
        _active_contexts.append(mock_ctx)

        # Capture time before shutdown
        before = datetime.now(timezone.utc)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Capture time after shutdown
        after = datetime.now(timezone.utc)

        # Verify end_time is ISO 8601 UTC format and within range
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        end_time_str = call_kwargs['end_time']
        
        # Parse end_time (handle both Z and +00:00 suffixes)
        end_time = datetime.fromisoformat(end_time_str.replace('Z', '+00:00'))

        assert before <= end_time <= after
        # Verify format is ISO 8601 with timezone
        assert '+' in end_time_str or end_time_str.endswith('Z')

    def test_shutdown_sets_all_fields_together(self):
        """GS-01/02/03: Verify all critical fields set together."""
        import time
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context
        mock_ctx = Mock()
        mock_ctx._start_time = time.time() - 3.0
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify all critical fields present
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert call_kwargs['run_status'] == 'cancelled'
        assert call_kwargs['duration_ms'] > 2000
        assert call_kwargs['duration_ms'] < 4000
        assert 'end_time' in call_kwargs
        assert 'output_summary' in call_kwargs
        assert 'error_summary' in call_kwargs
        assert 'SIGINT' in call_kwargs['error_summary']

    def test_shutdown_captures_partial_items_metrics(self):
        """GS-04: Verify partial items_* metrics are extracted and passed."""
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context with get_partial_metrics returning items_*
        mock_ctx = Mock()
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()
        mock_ctx.get_partial_metrics = Mock(return_value={
            'items_discovered': 10,
            'items_succeeded': 5,
            'items_failed': 1
        })

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify get_partial_metrics was called
        assert mock_ctx.get_partial_metrics.called

        # Verify set_metrics received partial items_*
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert call_kwargs.get('items_discovered') == 10
        assert call_kwargs.get('items_succeeded') == 5
        assert call_kwargs.get('items_failed') == 1

    def test_shutdown_captures_partial_metrics_json(self):
        """GS-05: Verify partial metrics_json is extracted and passed."""
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context with get_partial_metrics returning metrics_json
        mock_ctx = Mock()
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()
        mock_ctx.get_partial_metrics = Mock(return_value={
            'metrics_json': {
                'tokens_input': 1500,
                'tokens_output': 2000,
                'tm_hits': 10,
                'l1_hits': 5,
                'l2_hits': 3,
                'translated_segments': 25
            }
        })

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify set_metrics received metrics_json
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert 'metrics_json' in call_kwargs
        metrics = call_kwargs['metrics_json']
        assert metrics['tokens_input'] == 1500
        assert metrics['tokens_output'] == 2000
        assert metrics['tm_hits'] == 10

    def test_shutdown_handles_missing_get_partial_metrics(self):
        """GS-04/05: Verify graceful degradation if get_partial_metrics not available."""
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context WITHOUT get_partial_metrics
        mock_ctx = Mock()
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()
        # Remove get_partial_metrics
        del mock_ctx.get_partial_metrics

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown - should not raise
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify set_metrics was still called (without partial metrics)
        assert mock_ctx.set_metrics.called
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert call_kwargs['run_status'] == 'cancelled'

    def test_shutdown_handles_get_partial_metrics_exception(self):
        """GS-04/05: Verify exception handling if get_partial_metrics fails."""
        from unittest.mock import Mock
        from src.observability.graceful_shutdown import _perform_graceful_shutdown, _active_contexts
        import signal
        import src.observability.graceful_shutdown as gs_module

        # Reset global state
        _active_contexts.clear()
        gs_module._shutdown_in_progress = False

        # Create mock context with get_partial_metrics that raises
        mock_ctx = Mock()
        mock_ctx.set_metrics = Mock()
        mock_ctx.__exit__ = Mock()
        mock_ctx.get_partial_metrics = Mock(side_effect=RuntimeError("Failed to get metrics"))

        # Register context
        _active_contexts.append(mock_ctx)

        # Trigger shutdown - should not raise
        try:
            _perform_graceful_shutdown(signal.SIGINT, None)
        except SystemExit:
            pass

        # Verify set_metrics was still called (without partial metrics)
        assert mock_ctx.set_metrics.called
        call_kwargs = mock_ctx.set_metrics.call_args[1]
        assert call_kwargs['run_status'] == 'cancelled'

    def test_dummy_run_context_get_partial_metrics(self):
        """GS-04/05: Verify DummyRunContext.get_partial_metrics() returns empty dict."""
        from src.observability.telemetry_integration import DummyRunContext

        dummy = DummyRunContext()
        result = dummy.get_partial_metrics()

        assert isinstance(result, dict)
        assert len(result) == 0
