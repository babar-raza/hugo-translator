"""
Timeout guard using signal-based interruption (Unix) or thread-based timeout (Windows).

This module provides a context manager for detecting and handling hung operations
that exceed a specified timeout threshold.
"""
import ctypes
import logging
import platform
import signal
import sys
import threading
import traceback
from contextlib import contextmanager

logger = logging.getLogger(__name__)


class TimeoutError(Exception):
    """Raised when operation times out."""
    pass


@contextmanager
def timeout_guard(seconds: int, operation_name: str = "operation"):
    """
    Context manager that raises TimeoutError if operation takes longer than specified seconds.

    On Windows, uses ctypes.pythonapi.PyThreadState_SetAsyncExc to inject a
    TimeoutError into the main thread. This is more reliable than threading.Timer +
    Event, which can only check the flag AFTER the blocked operation returns.

    On Unix/Linux/macOS, uses signal.SIGALRM (most reliable).

    Args:
        seconds: Timeout in seconds
        operation_name: Name of operation for logging

    Raises:
        TimeoutError: If operation exceeds timeout

    Note:
        On Windows, async exception injection may not interrupt C-level blocking
        calls (e.g., inside torch CUDA kernels). In that case, a stack trace dump
        is logged for post-mortem analysis after a grace period.
    """
    if platform.system() == "Windows":
        timer = None
        timed_out = threading.Event()
        main_thread_id = threading.current_thread().ident

        def _timeout_handler():
            """Called when timeout expires. Injects TimeoutError into the main thread."""
            timed_out.set()
            logger.error(f"TIMEOUT: {operation_name} exceeded {seconds}s limit")

            # Inject TimeoutError into the main thread via async exception
            try:
                ret = ctypes.pythonapi.PyThreadState_SetAsyncExc(
                    ctypes.c_ulong(main_thread_id),
                    ctypes.py_object(TimeoutError),
                )
                if ret == 0:
                    logger.error("Timeout: failed to inject exception (invalid thread id)")
                elif ret > 1:
                    # More than one thread affected — clear it
                    ctypes.pythonapi.PyThreadState_SetAsyncExc(
                        ctypes.c_ulong(main_thread_id), None
                    )
                    logger.error("Timeout: async exception affected multiple threads, cleared")
                else:
                    logger.warning("Timeout: injected TimeoutError into main thread")
            except Exception as e:
                logger.error(f"Timeout: failed to inject async exception: {e}")

            # Grace period: if the exception doesn't land (stuck in C code),
            # dump stack traces for post-mortem diagnosis
            def _dump_stacks():
                if timed_out.is_set():
                    logger.error(
                        f"TIMEOUT STUCK: {operation_name} still blocked after "
                        f"{seconds + 30}s. Dumping thread stacks:"
                    )
                    for tid, frame in sys._current_frames().items():
                        logger.error(
                            f"Thread {tid}:\n"
                            + "".join(traceback.format_stack(frame))
                        )

            grace_timer = threading.Timer(30, _dump_stacks)
            grace_timer.daemon = True
            grace_timer.start()

        try:
            timer = threading.Timer(seconds, _timeout_handler)
            timer.daemon = True
            timer.start()
            logger.debug(f"Timeout guard active: {operation_name} (limit: {seconds}s)")

            yield

            # Check if timeout occurred during operation (belt-and-suspenders)
            if timed_out.is_set():
                raise TimeoutError(f"{operation_name} timed out after {seconds}s")
        finally:
            if timer:
                timer.cancel()
            timed_out.clear()  # Signal grace timer to skip dump if we exited normally

    else:
        # Unix/Linux/macOS: Use SIGALRM (most reliable)
        def _timeout_handler(signum, frame):
            """Signal handler for SIGALRM."""
            raise TimeoutError(f"{operation_name} timed out after {seconds}s")

        # Save old handler to restore later
        old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
        signal.alarm(seconds)
        logger.debug(f"Timeout guard active: {operation_name} (limit: {seconds}s)")

        try:
            yield
        finally:
            # Cancel alarm and restore old handler
            signal.alarm(0)
            signal.signal(signal.SIGALRM, old_handler)
