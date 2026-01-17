"""
LoggingEngine - Unified structured logging (NDJSON).

Wraps existing StructuredLogger to provide consistent logging interface
across execution modes with correlation tracking and NDJSON output.
"""

import logging
from pathlib import Path
from typing import Dict, Any, Optional

from src.observability.logger import (
    StructuredLogger,
    LogContext,
    setup_structured_logging,
    get_logger as get_structured_logger
)

logger = logging.getLogger(__name__)


class LoggingEngine:
    """
    Unified logging engine for structured NDJSON logging.

    Wraps StructuredLogger to provide consistent interface for:
    - Structured logging (NDJSON format)
    - Correlation tracking (request/job/worker IDs)
    - Dual output (console + file)
    - Context management

    Args:
        name: Logger name (default: "translation_system")
        log_level: Logging level (default: "INFO")
        log_file: Optional log file path for NDJSON output
        console_output: Whether to output to console (default: True)

    Example:
        # Initialize engine
        logging_engine = LoggingEngine(
            name="hugo-translator",
            log_level="INFO",
            log_file=Path("logs/translation.ndjson")
        )

        # Basic logging
        logging_engine.info("Translation started", file="example.md", lang="es")
        logging_engine.warning("Low memory", available_mb=512)
        logging_engine.error("Translation failed", error="Timeout")

        # Context-based logging with correlation IDs
        with logging_engine.with_context(job_id="job_123", worker_id="worker_1"):
            logging_engine.info("Processing job")
            # ... do work ...
            logging_engine.info("Job complete")
    """

    def __init__(
        self,
        name: str = "translation_system",
        log_level: str = "INFO",
        log_file: Optional[Path] = None,
        console_output: bool = True
    ):
        """Initialize logging engine."""
        print("DEBUG: LoggingEngine.__init__ started", flush=True)
        self.name = name
        self.log_level = log_level
        self.log_file = log_file
        self.console_output = console_output

        # Set up structured logging
        if log_file or console_output:
            print(f"DEBUG: About to call setup_structured_logging", flush=True)
            setup_structured_logging(
                log_level=log_level,
                log_file=log_file,
                console_output=console_output
            )
            print(f"DEBUG: setup_structured_logging completed", flush=True)

        # Get structured logger
        print(f"DEBUG: About to create StructuredLogger", flush=True)
        self.logger = StructuredLogger(name=name)
        print(f"DEBUG: StructuredLogger created", flush=True)

        logger.info(
            f"LoggingEngine initialized: name={name}, level={log_level}, "
            f"log_file={log_file}, console={console_output}"
        )

    def info(self, message: str, **kwargs: Any) -> None:
        """
        Log info message with context.

        Args:
            message: Info message
            **kwargs: Additional context fields

        Example:
            engine.info("File translated", file="example.md", lang="es", segments=42)
        """
        self.logger.log_info(message, **kwargs)

    def debug(self, message: str, **kwargs: Any) -> None:
        """
        Log debug message with context.

        Args:
            message: Debug message
            **kwargs: Additional context fields

        Example:
            engine.debug("TM lookup", source="hello", hit=True, confidence=0.95)
        """
        self.logger.log_debug(message, **kwargs)

    def warning(self, message: str, **kwargs: Any) -> None:
        """
        Log warning message with context.

        Args:
            message: Warning message
            **kwargs: Additional context fields

        Example:
            engine.warning("Low memory", available_mb=512, threshold_mb=1024)
        """
        self.logger.log_warning(message, **kwargs)

    def error(self, message: str, **kwargs: Any) -> None:
        """
        Log error message with context.

        Args:
            message: Error message
            **kwargs: Additional context fields

        Example:
            engine.error("Translation failed", error="Timeout", retry_count=3)
        """
        # Use log_error if 'error' kwarg is an Exception
        if "error" in kwargs and isinstance(kwargs["error"], Exception):
            context = {k: v for k, v in kwargs.items() if k != "error"}
            context["message"] = message
            self.logger.log_error(context, kwargs["error"])
        else:
            # Otherwise use generic log method
            self.logger._log_both("error", message, **kwargs)

    def with_context(
        self,
        correlation_id: Optional[str] = None,
        job_id: Optional[str] = None,
        worker_id: Optional[str] = None
    ) -> LogContext:
        """
        Create context manager for correlation tracking.

        All log messages within the context will include the specified IDs.

        Args:
            correlation_id: Correlation ID for tracing across components
            job_id: Job identifier
            worker_id: Worker identifier

        Returns:
            LogContext context manager

        Example:
            with engine.with_context(job_id="job_123", worker_id="worker_1"):
                engine.info("Job started")
                # ... process job ...
                engine.info("Job completed")

            # All logs within context include job_id and worker_id
        """
        return LogContext(
            correlation_id=correlation_id,
            job_id=job_id,
            worker_id=worker_id
        )

    def get_logger(self) -> StructuredLogger:
        """
        Get underlying structured logger for advanced usage.

        Returns:
            StructuredLogger instance

        Note:
            Most code should use LoggingEngine methods instead of
            accessing the logger directly.

        Example:
            logger = engine.get_logger()
            logger.log_model_loading_start("m2m100_418m", "cuda")
        """
        return self.logger

    def set_level(self, level: str) -> None:
        """
        Update logging level at runtime.

        Args:
            level: New logging level (DEBUG, INFO, WARNING, ERROR)

        Example:
            engine.set_level("DEBUG")  # Enable debug logging
            # ... debug work ...
            engine.set_level("INFO")   # Restore normal logging
        """
        self.log_level = level
        root_logger = logging.getLogger()
        root_logger.setLevel(getattr(logging, level.upper()))
        logger.info(f"Logging level changed to {level}")


# Global logging engine instance
_global_logging_engine: Optional[LoggingEngine] = None


def get_logging_engine(
    name: str = "translation_system",
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    console_output: bool = True
) -> LoggingEngine:
    """
    Get or create global logging engine instance.

    Args:
        name: Logger name (default: "translation_system")
        log_level: Logging level (default: "INFO")
        log_file: Optional log file path for NDJSON output
        console_output: Whether to output to console (default: True)

    Returns:
        LoggingEngine instance

    Note:
        First call creates the global instance with specified settings.
        Subsequent calls return the same instance (ignoring parameters).

    Example:
        # Initialize global logging
        engine = get_logging_engine(
            log_level="INFO",
            log_file=Path("logs/translation.ndjson")
        )

        # Later, get same instance
        engine = get_logging_engine()  # Returns same instance
    """
    global _global_logging_engine

    if _global_logging_engine is None:
        _global_logging_engine = LoggingEngine(
            name=name,
            log_level=log_level,
            log_file=log_file,
            console_output=console_output
        )

    return _global_logging_engine
