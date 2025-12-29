"""
Structured logging for translation operations.

Provides JSON structured logging for debugging, audit, and monitoring.
Supports dual output: NDJSON to file for LLM analysis + colored console for humans.
"""

import logging
import sys
import uuid
from contextvars import ContextVar
from datetime import datetime
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.orchestrator.models import TranslationJob
from src.tm.models import LookupResult
from src.translation_engine.extractor.segment_extractor import Segment
from src.translation_engine.models import TranslationResult

# Context variables for correlation tracking
correlation_id_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)
job_id_var: ContextVar[Optional[str]] = ContextVar("job_id", default=None)
worker_id_var: ContextVar[Optional[str]] = ContextVar("worker_id", default=None)


def add_correlation_context(logger, method_name, event_dict):
    """Add correlation IDs from context vars to all log entries."""
    correlation_id = correlation_id_var.get()
    job_id = job_id_var.get()
    worker_id = worker_id_var.get()

    if correlation_id:
        event_dict["correlation_id"] = correlation_id
    if job_id:
        event_dict["job_id"] = job_id
    if worker_id:
        event_dict["worker_id"] = worker_id

    return event_dict


class DualOutputProcessor:
    """
    Processor that outputs to both console (colored) and file (NDJSON).

    This processor creates a fork in the processing chain to support
    dual rendering without duplicate configuration.
    """

    def __init__(self, log_file: Path, max_bytes: int, backup_count: int):
        """
        Initialize dual output processor.

        Args:
            log_file: Path to NDJSON log file
            max_bytes: Max bytes before rotation
            backup_count: Number of backup files
        """
        # Set up file logger with JSON output
        self.file_logger = logging.getLogger("hugo_translator.ndjson")
        self.file_logger.handlers.clear()
        self.file_logger.propagate = False
        self.file_logger.setLevel(logging.DEBUG)

        file_handler = RotatingFileHandler(
            str(log_file),
            maxBytes=max_bytes,
            backupCount=backup_count,
            encoding="utf-8",
        )
        file_handler.setFormatter(logging.Formatter("%(message)s"))
        self.file_logger.addHandler(file_handler)

        # JSON renderer for file output
        self.json_renderer = structlog.processors.JSONRenderer()

    def __call__(self, logger, method_name, event_dict):
        """
        Process log entry and output to file as NDJSON.

        Args:
            logger: Logger instance
            method_name: Log method name
            event_dict: Event dictionary

        Returns:
            event_dict unchanged for console rendering
        """
        # Render as JSON and write to file with error handling
        try:
            json_output = self.json_renderer(logger, method_name, event_dict.copy())
            self.file_logger.log(
                getattr(logging, event_dict.get("level", "info").upper(), logging.INFO),
                json_output,
            )
        except Exception as e:
            # Fallback to stderr if file logging fails
            # This prevents logging failures from crashing the application
            import traceback
            print(
                f"LOGGING ERROR: Failed to write NDJSON log: {e}",
                file=sys.stderr,
            )
            traceback.print_exc(file=sys.stderr)

        # Return event_dict unchanged for console rendering
        return event_dict


def setup_structured_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    console_output: bool = True,
    max_bytes: int = 100 * 1024 * 1024,  # 100MB default
    backup_count: int = 10,  # Keep 10 rotated files
) -> None:
    """
    Configure structured logging with dual output support.

    Supports:
    - NDJSON file output with rotation (for LLM analysis)
    - Colored console output (for human operators)
    - Correlation ID tracking across components
    - Full exception stack traces

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for NDJSON log output
        console_output: Whether to output to console
        max_bytes: Maximum size of each log file before rotation (default 100MB)
        backup_count: Number of rotated log files to keep (default 10)
    """
    # Clear any existing handlers
    root_logger = logging.getLogger()
    root_logger.handlers.clear()

    # Set root logger level
    root_logger.setLevel(getattr(logging, log_level.upper()))

    # Base processors for all outputs
    base_processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        add_correlation_context,  # Add correlation IDs
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add dual output processor if both console and file are requested
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        base_processors.append(
            DualOutputProcessor(log_file, max_bytes, backup_count)
        )

    # Add console renderer if console output is enabled
    if console_output:
        base_processors.append(structlog.dev.ConsoleRenderer())

        # Set up console handler for standard library logging
        console_handler = logging.StreamHandler(sys.stdout)
        console_handler.setLevel(getattr(logging, log_level.upper()))
        console_handler.setFormatter(logging.Formatter("%(message)s"))
        root_logger.addHandler(console_handler)
    elif log_file:
        # File only: use JSON renderer instead of console renderer
        base_processors.append(structlog.processors.JSONRenderer())

    # Configure structlog
    structlog.configure(
        processors=base_processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )


class LogContext:
    """Context manager for setting correlation IDs."""

    def __init__(
        self,
        correlation_id: Optional[str] = None,
        job_id: Optional[str] = None,
        worker_id: Optional[str] = None,
    ):
        """
        Initialize log context.

        Args:
            correlation_id: Correlation ID for tracing across components
            job_id: Job identifier
            worker_id: Worker identifier
        """
        self.correlation_id = correlation_id or str(uuid.uuid4())
        self.job_id = job_id
        self.worker_id = worker_id
        self._correlation_token = None
        self._job_token = None
        self._worker_token = None

    def __enter__(self):
        """Set context variables."""
        self._correlation_token = correlation_id_var.set(self.correlation_id)
        if self.job_id:
            self._job_token = job_id_var.set(self.job_id)
        if self.worker_id:
            self._worker_token = worker_id_var.set(self.worker_id)
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        """Reset context variables."""
        if self._correlation_token:
            correlation_id_var.reset(self._correlation_token)
        if self._job_token:
            job_id_var.reset(self._job_token)
        if self._worker_token:
            worker_id_var.reset(self._worker_token)


class StructuredLogger:
    """
    Structured logger for translation operations.

    Provides consistent structured logging for all major operations in the
    translation system. Supports dual output (console + NDJSON file) and
    correlation tracking.
    """

    def __init__(
        self,
        name: str = "translation_system",
        also_log_to_file: bool = False,
    ):
        """
        Initialize structured logger.

        Args:
            name: Logger name
            also_log_to_file: If True, also log to dedicated file logger
        """
        self.logger = structlog.get_logger(name)
        self.also_log_to_file = also_log_to_file
        if also_log_to_file:
            self.file_logger = structlog.get_logger("hugo_translator.file")
        else:
            self.file_logger = None

    def _log_both(self, level: str, event: str, **kwargs):
        """
        Log to both console and file if dual output is enabled.

        Args:
            level: Log level (info, debug, warning, error)
            event: Event name
            **kwargs: Additional context
        """
        # Log to main logger (console)
        getattr(self.logger, level)(event, **kwargs)

        # Also log to file logger if enabled (will use JSON renderer)
        if self.file_logger:
            getattr(self.file_logger, level)(event, **kwargs)

    # ===== Job Lifecycle Logging =====

    def log_job_start(self, job: TranslationJob, worker_id: str) -> None:
        """
        Log job start.

        Args:
            job: Translation job
            worker_id: Worker identifier
        """
        self._log_both(
            "info",
            "job_started",
            job_id=job.job_id,
            job_type=job.job_type.value,
            site_id=job.site_id,
            target_langs=job.target_langs,
            input_count=len(job.input_paths),
            input_paths=[str(p) for p in job.input_paths[:10]],  # First 10
            priority=job.priority,
            mode=job.mode.value,
            worker_id=worker_id,
        )

    def log_job_complete(
        self, job: TranslationJob, result: TranslationResult, worker_id: str
    ) -> None:
        """
        Log job completion with stats.

        Args:
            job: Translation job
            result: Translation result
            worker_id: Worker identifier
        """
        self._log_both(
            "info",
            "job_completed",
            job_id=job.job_id,
            job_type=job.job_type.value,
            site_id=job.site_id,
            success=result.success,
            outputs_count=len(result.outputs),
            output_paths=list(result.outputs.keys())[:10],  # First 10
            total_segments=result.stats.total_segments if result.stats else 0,
            tm_hits=result.stats.tm_hits if result.stats else 0,
            tm_hit_rate=round(
                (result.stats.tm_hits / result.stats.total_segments * 100)
                if result.stats and result.stats.total_segments > 0
                else 0,
                2,
            ),
            translated_segments=(
                result.stats.translated_segments if result.stats else 0
            ),
            duration_seconds=result.stats.duration_seconds if result.stats else 0,
            words_translated=result.stats.words_translated if result.stats else 0,
            error_count=len(result.errors),
            errors=result.errors[:5] if result.errors else [],  # First 5 errors
            worker_id=worker_id,
        )

    def log_job_failed(
        self, job: TranslationJob, error: Exception, worker_id: str
    ) -> None:
        """
        Log job failure.

        Args:
            job: Translation job
            error: Exception that occurred
            worker_id: Worker identifier
        """
        self._log_both(
            "error",
            "job_failed",
            job_id=job.job_id,
            job_type=job.job_type.value,
            site_id=job.site_id,
            error=str(error),
            error_type=type(error).__name__,
            error_module=type(error).__module__,
            worker_id=worker_id,
            exc_info=True,
        )

    # ===== File Translation Logging =====

    def log_segment_translation(
        self,
        segment: Segment,
        tm_result: LookupResult,
        translation: str,
        model_used: Optional[str] = None,
    ) -> None:
        """
        Log individual segment translation (for flow artifacts).

        Args:
            segment: Source segment
            tm_result: TM lookup result
            translation: Translated text
            model_used: Model identifier (if TM miss)
        """
        self._log_both(
            "debug",
            "segment_translated",
            segment_id=segment.id,
            source_text=segment.source_text[:200],  # More context
            translation=translation[:200],
            tm_hit=tm_result.hit,
            tm_source=tm_result.source if tm_result.hit else "none",
            confidence=tm_result.confidence if tm_result.hit else 0.0,
            model_used=model_used,
            site_id=segment.site_id,
            source_lang=segment.source_lang,
            segment_type=segment.type if hasattr(segment, "type") else "unknown",
        )

    def log_file_translation_start(
        self, site_id: str, file_path: Path, target_langs: list[str]
    ) -> None:
        """
        Log file translation start.

        Args:
            site_id: Site identifier
            file_path: File being translated
            target_langs: Target languages
        """
        self._log_both(
            "info",
            "file_translation_started",
            site_id=site_id,
            file_path=str(file_path),
            file_size_bytes=file_path.stat().st_size if file_path.exists() else 0,
            target_langs=target_langs,
        )

    def log_file_translation_complete(
        self, site_id: str, file_path: Path, result: TranslationResult
    ) -> None:
        """
        Log file translation completion.

        Args:
            site_id: Site identifier
            file_path: File that was translated
            result: Translation result
        """
        self._log_both(
            "info",
            "file_translation_completed",
            site_id=site_id,
            file_path=str(file_path),
            success=result.success,
            outputs=list(result.outputs.keys()),
            total_segments=result.stats.total_segments if result.stats else 0,
            tm_hits=result.stats.tm_hits if result.stats else 0,
            tm_hit_rate=round(
                (result.stats.tm_hits / result.stats.total_segments * 100)
                if result.stats and result.stats.total_segments > 0
                else 0,
                2,
            ),
            duration_seconds=result.stats.duration_seconds if result.stats else 0,
            errors=result.errors[:5] if result.errors else [],  # First 5
        )

    # ===== Translation Memory (TM) Logging =====

    def log_tm_lookup(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        text: str,
        result: LookupResult,
    ) -> None:
        """
        Log TM lookup operation.

        Args:
            site_id: Site identifier
            src_lang: Source language
            tgt_lang: Target language
            text: Source text
            result: Lookup result
        """
        self._log_both(
            "debug",
            "tm_lookup",
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            source_text=text[:200],
            hit=result.hit,
            source=result.source if result.hit else "none",
            confidence=result.confidence if result.hit else 0.0,
            translation=result.translation[:200] if result.hit and result.translation else None,
        )

    def log_tm_write(
        self,
        site_id: str,
        src_lang: str,
        tgt_lang: str,
        source_text: str,
        translation: str,
        layer: str,
    ) -> None:
        """
        Log TM write operation.

        Args:
            site_id: Site identifier
            src_lang: Source language
            tgt_lang: Target language
            source_text: Source text
            translation: Translation text
            layer: TM layer (L1/L2/L3)
        """
        self._log_both(
            "debug",
            "tm_write",
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            source_text=source_text[:200],
            translation=translation[:200],
            layer=layer,
        )

    def log_tm_cache_stats(
        self,
        layer: str,
        hits: int,
        misses: int,
        size: int,
        max_size: int,
    ) -> None:
        """
        Log TM cache statistics.

        Args:
            layer: Cache layer (L1/L2/L3)
            hits: Number of cache hits
            misses: Number of cache misses
            size: Current cache size
            max_size: Maximum cache size
        """
        total = hits + misses
        hit_rate = round((hits / total * 100), 2) if total > 0 else 0
        utilization = round((size / max_size * 100), 2) if max_size > 0 else 0

        self._log_both(
            "info",
            "tm_cache_stats",
            layer=layer,
            hits=hits,
            misses=misses,
            total_requests=total,
            hit_rate_percent=hit_rate,
            cache_size=size,
            max_size=max_size,
            utilization_percent=utilization,
        )

    # ===== Orchestrator & Queue Logging =====

    def log_queue_job_enqueued(
        self,
        job_id: str,
        job_type: str,
        site_id: str,
        priority: int,
        queue_depth: int,
    ) -> None:
        """
        Log job enqueued to queue.

        Args:
            job_id: Job identifier
            job_type: Type of job
            site_id: Site identifier
            priority: Job priority
            queue_depth: Current queue depth
        """
        self._log_both(
            "info",
            "queue_job_enqueued",
            job_id=job_id,
            job_type=job_type,
            site_id=site_id,
            priority=priority,
            queue_depth=queue_depth,
        )

    def log_queue_job_dequeued(
        self,
        job_id: str,
        worker_id: str,
        wait_time_seconds: float,
        queue_depth: int,
    ) -> None:
        """
        Log job dequeued from queue.

        Args:
            job_id: Job identifier
            worker_id: Worker that dequeued the job
            wait_time_seconds: Time job spent in queue
            queue_depth: Current queue depth
        """
        self._log_both(
            "info",
            "queue_job_dequeued",
            job_id=job_id,
            worker_id=worker_id,
            wait_time_seconds=wait_time_seconds,
            queue_depth=queue_depth,
        )

    def log_orchestrator_started(
        self,
        worker_count: int,
        queue_backend: str,
    ) -> None:
        """
        Log orchestrator startup.

        Args:
            worker_count: Number of workers
            queue_backend: Queue backend type
        """
        self._log_both(
            "info",
            "orchestrator_started",
            worker_count=worker_count,
            queue_backend=queue_backend,
        )

    def log_orchestrator_stopped(
        self,
        total_jobs_processed: int,
        total_runtime_seconds: float,
    ) -> None:
        """
        Log orchestrator shutdown.

        Args:
            total_jobs_processed: Total jobs processed
            total_runtime_seconds: Total runtime
        """
        self._log_both(
            "info",
            "orchestrator_stopped",
            total_jobs_processed=total_jobs_processed,
            total_runtime_seconds=total_runtime_seconds,
        )

    # ===== Model Runtime & GPU Logging =====

    def log_model_loading_start(
        self,
        model_name: str,
        device: str,
    ) -> None:
        """
        Log model loading start.

        Args:
            model_name: Model identifier
            device: Device (cpu/cuda/mps)
        """
        self._log_both(
            "info",
            "model_loading_started",
            model_name=model_name,
            device=device,
        )

    def log_model_loading_complete(
        self,
        model_name: str,
        device: str,
        load_time_seconds: float,
        model_size_mb: Optional[float] = None,
    ) -> None:
        """
        Log model loading completion.

        Args:
            model_name: Model identifier
            device: Device (cpu/cuda/mps)
            load_time_seconds: Time to load model
            model_size_mb: Model size in MB
        """
        self._log_both(
            "info",
            "model_loaded",
            model_name=model_name,
            device=device,
            load_time_seconds=load_time_seconds,
            model_size_mb=model_size_mb,
        )

    def log_inference_batch(
        self,
        model_name: str,
        batch_size: int,
        inference_time_seconds: float,
        tokens_per_second: Optional[float] = None,
    ) -> None:
        """
        Log model inference batch.

        Args:
            model_name: Model identifier
            batch_size: Number of segments in batch
            inference_time_seconds: Inference time
            tokens_per_second: Throughput in tokens/sec
        """
        self._log_both(
            "debug",
            "inference_batch",
            model_name=model_name,
            batch_size=batch_size,
            inference_time_seconds=inference_time_seconds,
            tokens_per_second=tokens_per_second,
            time_per_segment=round(inference_time_seconds / batch_size, 4)
            if batch_size > 0
            else 0,
        )

    def log_gpu_stats(
        self,
        device_id: int,
        memory_allocated_mb: float,
        memory_reserved_mb: float,
        memory_total_mb: float,
        utilization_percent: Optional[float] = None,
    ) -> None:
        """
        Log GPU statistics.

        Args:
            device_id: GPU device ID
            memory_allocated_mb: Allocated memory in MB
            memory_reserved_mb: Reserved memory in MB
            memory_total_mb: Total memory in MB
            utilization_percent: GPU utilization %
        """
        self._log_both(
            "debug",
            "gpu_stats",
            device_id=device_id,
            memory_allocated_mb=memory_allocated_mb,
            memory_reserved_mb=memory_reserved_mb,
            memory_total_mb=memory_total_mb,
            memory_utilization_percent=round(
                (memory_allocated_mb / memory_total_mb * 100), 2
            )
            if memory_total_mb > 0
            else 0,
            gpu_utilization_percent=utilization_percent,
        )

    # ===== Validation Logging =====

    def log_validation_check(
        self,
        validator_name: str,
        source_text: str,
        translation: str,
        passed: bool,
        severity: str,
        message: Optional[str] = None,
    ) -> None:
        """
        Log validation check result.

        Args:
            validator_name: Name of validator
            source_text: Source text
            translation: Translation text
            passed: Whether validation passed
            severity: Severity level (error/warning/info)
            message: Optional validation message
        """
        self._log_both(
            "debug" if passed else "warning",
            "validation_check",
            validator_name=validator_name,
            source_text=source_text[:200],
            translation=translation[:200],
            passed=passed,
            severity=severity,
            message=message,
        )

    def log_validation_failed(
        self,
        file_path: str,
        validator_name: str,
        error: Exception,
    ) -> None:
        """
        Log validation execution failure.

        Args:
            file_path: File being validated
            validator_name: Validator that failed
            error: Exception that occurred
        """
        self._log_both(
            "error",
            "validation_failed",
            file_path=file_path,
            validator_name=validator_name,
            error=str(error),
            error_type=type(error).__name__,
            exc_info=True,
        )

    # ===== Sweep Logging =====

    def log_sweep_started(self, site_id: str, sweep_id: str) -> None:
        """
        Log sweep operation start.

        Args:
            site_id: Site identifier
            sweep_id: Sweep identifier
        """
        self._log_both(
            "info",
            "sweep_started",
            site_id=site_id,
            sweep_id=sweep_id,
        )

    def log_sweep_progress(
        self,
        site_id: str,
        sweep_id: str,
        files_scanned: int,
        files_total: int,
        jobs_created: int,
    ) -> None:
        """
        Log sweep progress.

        Args:
            site_id: Site identifier
            sweep_id: Sweep identifier
            files_scanned: Files scanned so far
            files_total: Total files to scan
            jobs_created: Jobs created
        """
        self._log_both(
            "info",
            "sweep_progress",
            site_id=site_id,
            sweep_id=sweep_id,
            files_scanned=files_scanned,
            files_total=files_total,
            progress_percent=round((files_scanned / files_total * 100), 2)
            if files_total > 0
            else 0,
            jobs_created=jobs_created,
        )

    def log_sweep_completed(
        self, site_id: str, sweep_id: str, total_jobs: int, duration_seconds: float
    ) -> None:
        """
        Log sweep completion.

        Args:
            site_id: Site identifier
            sweep_id: Sweep identifier
            total_jobs: Total jobs created
            duration_seconds: Duration in seconds
        """
        self._log_both(
            "info",
            "sweep_completed",
            site_id=site_id,
            sweep_id=sweep_id,
            total_jobs=total_jobs,
            duration_seconds=duration_seconds,
        )

    # ===== Generic Logging Methods =====

    def log_error(self, context: Dict[str, Any], error: Exception) -> None:
        """
        Log error with full context and stack trace.

        Args:
            context: Context dictionary
            error: Exception that occurred
        """
        self._log_both(
            "error",
            "error_occurred",
            **context,
            error=str(error),
            error_type=type(error).__name__,
            error_module=type(error).__module__,
            exc_info=True,
        )

    def log_warning(self, message: str, **kwargs: Any) -> None:
        """
        Log warning with context.

        Args:
            message: Warning message
            **kwargs: Additional context
        """
        self._log_both("warning", message, **kwargs)

    def log_info(self, message: str, **kwargs: Any) -> None:
        """
        Log info message with context.

        Args:
            message: Info message
            **kwargs: Additional context
        """
        self._log_both("info", message, **kwargs)

    def log_debug(self, message: str, **kwargs: Any) -> None:
        """
        Log debug message with context.

        Args:
            message: Debug message
            **kwargs: Additional context
        """
        self._log_both("debug", message, **kwargs)


# Global logger instance
_global_logger: Optional[StructuredLogger] = None


def get_logger(name: str = "translation_system") -> StructuredLogger:
    """
    Get or create global logger instance.

    Args:
        name: Logger name

    Returns:
        StructuredLogger instance
    """
    global _global_logger
    if _global_logger is None:
        _global_logger = StructuredLogger(name)
    return _global_logger
