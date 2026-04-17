"""
Unit tests for LoggingEngine.

Tests logging wrapper with mocked StructuredLogger.
"""

import sys
import unittest
from pathlib import Path
from unittest.mock import Mock, patch

# Add src to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent / "src"))

from src.shared_engines.logging_engine import LoggingEngine, get_logging_engine


class TestLoggingEngine(unittest.TestCase):
    """Test LoggingEngine wrapper."""

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_initialization_default(self, mock_structured_logger, mock_setup):
        """Test LoggingEngine initializes with defaults."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()

        self.assertEqual(engine.name, "translation_system")
        self.assertEqual(engine.log_level, "INFO")
        self.assertIsNone(engine.log_file)
        self.assertTrue(engine.console_output)
        mock_setup.assert_called_once_with(
            log_level="INFO",
            log_file=None,
            console_output=True
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_initialization_custom(self, mock_structured_logger, mock_setup):
        """Test LoggingEngine initializes with custom settings."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        log_file = Path("logs/test.ndjson")
        engine = LoggingEngine(
            name="custom-logger",
            log_level="DEBUG",
            log_file=log_file,
            console_output=False
        )

        self.assertEqual(engine.name, "custom-logger")
        self.assertEqual(engine.log_level, "DEBUG")
        self.assertEqual(engine.log_file, log_file)
        self.assertFalse(engine.console_output)
        mock_setup.assert_called_once_with(
            log_level="DEBUG",
            log_file=log_file,
            console_output=False
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_info_logging(self, mock_structured_logger, mock_setup):
        """Test info() logs info message."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()
        engine.info("Test info message", file="example.md", lang="es")

        mock_logger_instance.log_info.assert_called_once_with(
            "Test info message",
            file="example.md",
            lang="es"
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_debug_logging(self, mock_structured_logger, mock_setup):
        """Test debug() logs debug message."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()
        engine.debug("Test debug message", source="hello", hit=True)

        mock_logger_instance.log_debug.assert_called_once_with(
            "Test debug message",
            source="hello",
            hit=True
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_warning_logging(self, mock_structured_logger, mock_setup):
        """Test warning() logs warning message."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()
        engine.warning("Low memory", available_mb=512)

        mock_logger_instance.log_warning.assert_called_once_with(
            "Low memory",
            available_mb=512
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_error_logging_with_string(self, mock_structured_logger, mock_setup):
        """Test error() logs error message with string."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()
        engine.error("Translation failed", error="Timeout", retry_count=3)

        mock_logger_instance._log_both.assert_called_once_with(
            "error",
            "Translation failed",
            error="Timeout",
            retry_count=3
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_error_logging_with_exception(self, mock_structured_logger, mock_setup):
        """Test error() logs error message with Exception."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()
        test_exception = ValueError("Test error")
        engine.error("Translation failed", error=test_exception, retry_count=3)

        # Should call log_error with context and exception
        mock_logger_instance.log_error.assert_called_once()
        args = mock_logger_instance.log_error.call_args
        context_dict = args[0][0]
        exception = args[0][1]

        self.assertEqual(context_dict["message"], "Translation failed")
        self.assertEqual(context_dict["retry_count"], 3)
        self.assertEqual(exception, test_exception)

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    @patch('src.shared_engines.logging_engine.LogContext')
    def test_with_context(self, mock_log_context, mock_structured_logger, mock_setup):
        """Test with_context() returns LogContext."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance
        mock_context_instance = Mock()
        mock_log_context.return_value = mock_context_instance

        engine = LoggingEngine()
        context = engine.with_context(
            job_id="job_123",
            worker_id="worker_1",
            correlation_id="corr_456"
        )

        self.assertEqual(context, mock_context_instance)
        mock_log_context.assert_called_once_with(
            correlation_id="corr_456",
            job_id="job_123",
            worker_id="worker_1"
        )

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_get_logger(self, mock_structured_logger, mock_setup):
        """Test get_logger() returns underlying logger."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine()
        logger = engine.get_logger()

        self.assertEqual(logger, mock_logger_instance)

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_set_level(self, mock_structured_logger, mock_setup):
        """Test set_level() changes logging level."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine(log_level="INFO")
        engine.set_level("DEBUG")

        self.assertEqual(engine.log_level, "DEBUG")
        # Verify root logger level was changed
        import logging
        root_logger = logging.getLogger()
        self.assertEqual(root_logger.level, logging.DEBUG)

    @patch('src.shared_engines.logging_engine.setup_structured_logging')
    @patch('src.shared_engines.logging_engine.StructuredLogger')
    def test_no_setup_when_no_output(self, mock_structured_logger, mock_setup):
        """Test setup_structured_logging not called when no output."""
        mock_logger_instance = Mock()
        mock_structured_logger.return_value = mock_logger_instance

        engine = LoggingEngine(
            log_file=None,
            console_output=False
        )

        # setup_structured_logging should not be called
        mock_setup.assert_not_called()


class TestGetLoggingEngine(unittest.TestCase):
    """Test get_logging_engine() factory function."""

    def setUp(self):
        """Clear global logging engine before each test."""
        import src.shared_engines.logging_engine
        src.shared_engines.logging_engine._global_logging_engine = None

    @patch('src.shared_engines.logging_engine.LoggingEngine')
    def test_get_logging_engine_creates_instance(self, mock_logging_engine):
        """Test get_logging_engine() creates new instance on first call."""
        mock_engine_instance = Mock()
        mock_logging_engine.return_value = mock_engine_instance

        engine = get_logging_engine(
            name="test-logger",
            log_level="DEBUG",
            log_file=Path("logs/test.ndjson")
        )

        self.assertEqual(engine, mock_engine_instance)
        mock_logging_engine.assert_called_once_with(
            name="test-logger",
            log_level="DEBUG",
            log_file=Path("logs/test.ndjson"),
            console_output=True
        )

    @patch('src.shared_engines.logging_engine.LoggingEngine')
    def test_get_logging_engine_returns_same_instance(self, mock_logging_engine):
        """Test get_logging_engine() returns same instance on subsequent calls."""
        mock_engine_instance = Mock()
        mock_logging_engine.return_value = mock_engine_instance

        # First call
        engine1 = get_logging_engine(name="test-logger")

        # Second call (should return same instance, ignore parameters)
        engine2 = get_logging_engine(name="different-logger", log_level="ERROR")

        self.assertEqual(engine1, engine2)
        # Should only be called once (first call)
        mock_logging_engine.assert_called_once()


if __name__ == "__main__":
    unittest.main()
