"""
Graceful Shutdown Handler for Hugo Translator.

Ensures telemetry contexts are properly closed when the process is interrupted
(SIGINT/SIGTERM), preventing records from being left in "running" state.

Usage:
    from observability.graceful_shutdown import setup_graceful_shutdown

    # At application startup
    setup_graceful_shutdown()

    # Register telemetry context
    with telemetry.track_translation_session(...) as ctx:
        register_active_context(ctx)
        try:
            # Translation work...
        finally:
            unregister_active_context(ctx)
"""

import logging
import platform
import signal
import sys
import time
from datetime import datetime, timezone
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)

# Global registry of active telemetry contexts
_active_contexts: list[Any] = []
_contexts_lock = Lock()
_shutdown_handlers: list[callable] = []
_shutdown_in_progress = False


def register_active_context(context: Any) -> None:
    """
    Register an active telemetry context for graceful shutdown.

    Args:
        context: Active telemetry run context from track_translation_session()
    """
    with _contexts_lock:
        if context and context not in _active_contexts:
            _active_contexts.append(context)
            logger.debug(f"Registered telemetry context (total: {len(_active_contexts)})")


def unregister_active_context(context: Any) -> None:
    """
    Unregister a telemetry context after normal completion.

    Args:
        context: Telemetry run context to unregister
    """
    with _contexts_lock:
        if context in _active_contexts:
            _active_contexts.remove(context)
            logger.debug(f"Unregistered telemetry context (remaining: {len(_active_contexts)})")


def register_shutdown_handler(handler: callable) -> None:
    """
    Register a custom shutdown handler to be called on graceful shutdown.

    Args:
        handler: Callable to execute on shutdown (no arguments)
    """
    if handler not in _shutdown_handlers:
        _shutdown_handlers.append(handler)
        logger.debug(f"Registered shutdown handler: {handler.__name__}")


def cleanup_telemetry_contexts(signal_name: str = "SIGINT") -> None:
    """
    Close all active telemetry contexts and execute shutdown handlers.

    This function is called by the unified signal handler to ensure telemetry
    is properly cleaned up before engine shutdown.

    Args:
        signal_name: Name of signal that triggered shutdown (for logging)
    """
    logger.info(f"Cleaning up telemetry contexts (triggered by {signal_name})...")

    # Close all active telemetry contexts
    with _contexts_lock:
        context_count = len(_active_contexts)
        if context_count > 0:
            logger.info(f"Closing {context_count} active telemetry context(s)...")

            for i, context in enumerate(_active_contexts, 1):
                try:
                    # Update context with cancellation status
                    if hasattr(context, 'set_metrics'):
                        # GS-02: Calculate duration_ms from start_time if available
                        duration_ms = 0
                        if hasattr(context, '_start_time') and context._start_time:
                            duration_ms = int((time.time() - context._start_time) * 1000)
                        else:
                            logger.warning(f"Context {i} has no _start_time, duration will be 0")

                        # GS-03: Set explicit end_time in UTC
                        end_time = datetime.now(timezone.utc).isoformat()

                        # GS-04, GS-05: Extract partial metrics if available
                        partial_metrics = {}
                        if hasattr(context, 'get_partial_metrics'):
                            try:
                                partial_metrics = context.get_partial_metrics()
                                logger.debug(f"Extracted partial metrics: {partial_metrics.keys()}")
                            except Exception as e:
                                logger.warning(f"Failed to get partial metrics from context {i}: {e}")

                        # GS-01, GS-02, GS-03, GS-04, GS-05: Set all critical telemetry fields
                        context.set_metrics(
                            run_status="cancelled",
                            duration_ms=duration_ms,
                            end_time=end_time,
                            output_summary="Process interrupted by user",
                            error_summary=f"Process killed with {signal_name}",
                            **partial_metrics  # Include partial items_*, metrics_json, etc.
                        )

                    # Exit the context manager
                    if hasattr(context, '__exit__'):
                        context.__exit__(None, None, None)
                        logger.info(f"✓ Closed telemetry context {i}/{context_count}")
                except Exception as e:
                    logger.error(f"Failed to close telemetry context {i}: {e}")

            _active_contexts.clear()
        else:
            logger.debug("No active telemetry contexts to close")

    # Call custom shutdown handlers
    if _shutdown_handlers:
        logger.info(f"Executing {len(_shutdown_handlers)} shutdown handler(s)...")
        for handler in _shutdown_handlers:
            try:
                handler()
                logger.debug(f"✓ Executed {handler.__name__}")
            except Exception as e:
                logger.error(f"Shutdown handler {handler.__name__} failed: {e}")

    logger.info("Telemetry cleanup complete")


def _perform_graceful_shutdown(signum: int, frame) -> None:
    """
    Legacy signal handler - kept for backward compatibility.

    DEPRECATED: This handler is now replaced by the unified signal handler
    in cli.py. It is kept here to avoid breaking existing code that might
    call setup_graceful_shutdown() directly.

    Args:
        signum: Signal number
        frame: Current stack frame (unused)
    """
    global _shutdown_in_progress

    if _shutdown_in_progress:
        logger.warning("Shutdown already in progress, forcing exit...")
        sys.exit(1)

    _shutdown_in_progress = True

    signal_name = signal.Signals(signum).name if hasattr(signal, 'Signals') else str(signum)
    cleanup_telemetry_contexts(signal_name)
    logger.info("Graceful shutdown complete")
    sys.exit(0)


def setup_graceful_shutdown() -> None:
    """
    Setup platform-aware signal handlers for graceful shutdown.

    DEPRECATED: This function is deprecated and has been replaced by the unified
    signal handler in cli.py (setup_unified_signal_handler). It is kept for
    backward compatibility but will be removed in a future version.

    The unified handler properly coordinates telemetry cleanup AND engine shutdown,
    fixing the issue where the second handler registration would overwrite the first.

    On Windows: Registers SIGINT and SIGBREAK (if available)
    On Unix (Linux/macOS): Registers SIGINT and SIGTERM

    Should be called once at application startup (in main() or cli entry point).

    Example:
        def main():
            setup_graceful_shutdown()
            # ... rest of application
    """
    logger.warning(
        "setup_graceful_shutdown() is deprecated. "
        "Use setup_unified_signal_handler() from cli.py instead."
    )

    system = platform.system()

    # Always register SIGINT (works on all platforms)
    signal.signal(signal.SIGINT, _perform_graceful_shutdown)

    if system == "Windows":
        # Windows: Use SIGBREAK instead of SIGTERM
        if hasattr(signal, 'SIGBREAK'):
            signal.signal(signal.SIGBREAK, _perform_graceful_shutdown)
            logger.info("Graceful shutdown handlers registered for Windows (SIGINT, SIGBREAK)")
        else:
            logger.warning("SIGBREAK not available, using SIGINT only")
            logger.info("Graceful shutdown handlers registered for Windows (SIGINT)")
    else:
        # Unix-like systems (Linux, macOS, etc.): Use SIGTERM
        signal.signal(signal.SIGTERM, _perform_graceful_shutdown)
        logger.info(f"Graceful shutdown handlers registered for {system} (SIGINT, SIGTERM)")


def get_active_context_count() -> int:
    """
    Get the number of currently active telemetry contexts.

    Returns:
        Number of active contexts
    """
    with _contexts_lock:
        return len(_active_contexts)


def reset_for_testing() -> None:
    """
    Reset global state for testing purposes.

    WARNING: Only use in test code. This clears all registered contexts
    and shutdown handlers, and resets the shutdown flag.
    """
    global _shutdown_in_progress
    with _contexts_lock:
        _active_contexts.clear()
        _shutdown_handlers.clear()
        _shutdown_in_progress = False
