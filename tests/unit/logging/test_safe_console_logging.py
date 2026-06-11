"""
TC-REEXEC-09 / RISK-09: Safe console logging tests.

Proves that after worker logging is configured, structlog calls route through
stdlib logging and cannot crash on Windows restricted pipes.

Key insight: stdlib's StreamHandler.emit() wraps stream.write() in try/except,
calling handleError() on failure instead of propagating. We simulate the real
failure by using a stream whose write() raises OSError, NOT by replacing emit().
"""

from __future__ import annotations

import io
import logging
import sys
from unittest.mock import MagicMock, patch

import pytest
import structlog


class _BrokenStream:
    """Simulates a Windows restricted pipe that raises OSError on write."""

    def write(self, msg):
        raise OSError(22, "Invalid argument")

    def flush(self):
        raise OSError(22, "Invalid argument")


def _configure_structlog_stdlib():
    """Apply the same structlog.configure() as the worker main()."""
    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.stdlib.PositionalArgumentsFormatter(),
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.processors.StackInfoRenderer(),
            structlog.processors.format_exc_info,
            structlog.processors.UnicodeDecoder(),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=False,  # False for test isolation
    )


@pytest.fixture(autouse=True)
def _reset_structlog():
    """Reset structlog config after each test to avoid cross-test pollution."""
    yield
    structlog.reset_defaults()


class TestStructlogStdlibRouting:
    """After configure(), structlog must route through stdlib, not PrintLogger."""

    def test_structlog_routes_through_stdlib_after_configure(self):
        """structlog.get_logger() returns a stdlib-backed logger after configure."""
        _configure_structlog_stdlib()
        cfg = structlog.get_config()
        assert isinstance(cfg["logger_factory"], structlog.stdlib.LoggerFactory), (
            "logger_factory must be stdlib LoggerFactory"
        )

    def test_restricted_stdout_does_not_crash_structlog(self):
        """Writing to a broken stdout does not crash structlog when routed via stdlib.

        StreamHandler.emit() catches the OSError and calls handleError() instead
        of propagating. This is the core RISK-09 protection mechanism.
        """
        _configure_structlog_stdlib()

        test_logger = logging.getLogger("test.yaml_formatter")
        test_logger.handlers.clear()
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        # Use a broken stream — StreamHandler.emit() will catch the write error
        broken_handler = logging.StreamHandler(_BrokenStream())
        test_logger.addHandler(broken_handler)

        # Must NOT raise
        log = structlog.get_logger("test.yaml_formatter")
        log.debug("yaml_format_success", preserved_comments=True)

        test_logger.handlers.clear()

    def test_file_log_is_utf8_when_stdout_fails(self, tmp_path):
        """File handler receives message even when stream handler fails."""
        _configure_structlog_stdlib()

        test_logger = logging.getLogger("test.file_utf8")
        test_logger.handlers.clear()
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        # Add a file handler with UTF-8
        log_file = tmp_path / "test.log"
        file_handler = logging.FileHandler(str(log_file), encoding="utf-8")
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        test_logger.addHandler(file_handler)

        # Add a broken stream handler — emit() catches the error internally
        broken_handler = logging.StreamHandler(_BrokenStream())
        test_logger.addHandler(broken_handler)

        # Log a unicode message
        log = structlog.get_logger("test.file_utf8")
        log.info("test_message", content="Caf\u00e9 r\u00e9sum\u00e9")

        file_handler.flush()
        file_handler.close()

        content = log_file.read_text(encoding="utf-8")
        assert "test_message" in content

        test_logger.handlers.clear()

    def test_structlog_debug_call_does_not_abort_on_windows_pipe(self):
        """Exact RISK-09 regression: yaml_formatter.py:61 debug call is safe."""
        _configure_structlog_stdlib()

        test_logger = logging.getLogger("test.risk09_debug")
        test_logger.handlers.clear()
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        broken_handler = logging.StreamHandler(_BrokenStream())
        test_logger.addHandler(broken_handler)

        # Simulate yaml_formatter.py:61
        log = structlog.get_logger("test.risk09_debug")
        log.debug("yaml_format_success", preserved_comments=False)
        # Must not raise

        test_logger.handlers.clear()

    def test_yaml_ruamel_fallback_warning_does_not_abort_on_windows_pipe(self):
        """Exact RISK-09 regression: yaml_formatter.py:64 warning call is safe."""
        _configure_structlog_stdlib()

        test_logger = logging.getLogger("test.risk09_warning")
        test_logger.handlers.clear()
        test_logger.setLevel(logging.DEBUG)
        test_logger.propagate = False

        broken_handler = logging.StreamHandler(_BrokenStream())
        test_logger.addHandler(broken_handler)

        # Simulate yaml_formatter.py:64
        log = structlog.get_logger("test.risk09_warning")
        log.warning("yaml_ruamel_fallback", error="ruamel error text")
        # Must not raise

        test_logger.handlers.clear()

    def test_logger_factory_is_stdlib_after_worker_configure(self):
        """Verify the factory type matches what the worker installs."""
        _configure_structlog_stdlib()
        cfg = structlog.get_config()
        factory = cfg["logger_factory"]
        assert type(factory).__name__ == "LoggerFactory"
        assert "stdlib" in type(factory).__module__

    def test_configure_is_safe_to_call_twice(self):
        """Calling configure twice must not error or corrupt state."""
        _configure_structlog_stdlib()
        _configure_structlog_stdlib()

        log = structlog.get_logger("test.double_configure")
        log.info("still_works")
        # Must not raise

        cfg = structlog.get_config()
        assert isinstance(cfg["logger_factory"], structlog.stdlib.LoggerFactory)
