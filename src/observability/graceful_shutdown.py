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
import signal
import sys
import time
from datetime import datetime, timezone
from typing import List, Optional, Any
from threading import Lock

logger = logging.getLogger(__name__)

# Global registry of active telemetry contexts
_active_contexts: List[Any] = []
_contexts_lock = Lock()
_shutdown_handlers: List[callable] = []
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


def _perform_graceful_shutdown(signum: int, frame) -> None:
    """
    Gracefully shutdown the application by closing all active telemetry contexts.

    Called when SIGINT (Ctrl+C) or SIGTERM is received.

    Args:
        signum: Signal number
        frame: Current stack frame (unused)
    """
    global _shutdown_in_progress

    if _shutdown_in_progress:
        logger.warning("Shutdown already in progress, forcing exit...")
        sys.exit(1)

    _shutdown_in_progress = True

    signal_name = "SIGINT" if signum == signal.SIGINT else "SIGTERM"
    logger.info(f"Received {signal_name}, shutting down gracefully...")

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
            logger.info("No active telemetry contexts to close")

    # Call custom shutdown handlers
    if _shutdown_handlers:
        logger.info(f"Executing {len(_shutdown_handlers)} shutdown handler(s)...")
        for handler in _shutdown_handlers:
            try:
                handler()
                logger.debug(f"✓ Executed {handler.__name__}")
            except Exception as e:
                logger.error(f"Shutdown handler {handler.__name__} failed: {e}")

    logger.info(f"Graceful shutdown complete")
    sys.exit(0)


def setup_graceful_shutdown() -> None:
    """
    Setup signal handlers for graceful shutdown on SIGINT and SIGTERM.

    Should be called once at application startup (in main() or cli entry point).

    Example:
        def main():
            setup_graceful_shutdown()
            # ... rest of application
    """
    # Register signal handlers
    signal.signal(signal.SIGINT, _perform_graceful_shutdown)
    signal.signal(signal.SIGTERM, _perform_graceful_shutdown)

    logger.info("Graceful shutdown handlers registered (SIGINT, SIGTERM)")


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
