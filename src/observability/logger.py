"""
Structured logging for translation operations.

Provides JSON structured logging for debugging, audit, and monitoring.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import structlog

from src.orchestrator.models import TranslationJob
from src.tm.models import LookupResult
from src.translation_engine.extractor.segment_extractor import Segment
from src.translation_engine.models import TranslationResult


def setup_structured_logging(
    log_level: str = "INFO",
    log_file: Optional[Path] = None,
    console_output: bool = True,
) -> None:
    """
    Configure structured logging for the translation system.

    Args:
        log_level: Logging level (DEBUG, INFO, WARNING, ERROR)
        log_file: Optional file path for log output (NDJSON format)
        console_output: Whether to output to console
    """
    # Configure standard library logging
    logging.basicConfig(
        format="%(message)s",
        stream=sys.stdout if console_output else None,
        level=getattr(logging, log_level.upper()),
    )

    # Configure structlog processors
    processors = [
        structlog.stdlib.filter_by_level,
        structlog.stdlib.add_logger_name,
        structlog.stdlib.add_log_level,
        structlog.stdlib.PositionalArgumentsFormatter(),
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.processors.StackInfoRenderer(),
        structlog.processors.format_exc_info,
        structlog.processors.UnicodeDecoder(),
    ]

    # Add appropriate renderer based on output
    if console_output:
        # Human-readable colored output for console
        processors.append(structlog.dev.ConsoleRenderer())
    else:
        # JSON output for file logging
        processors.append(structlog.processors.JSONRenderer())

    # Configure structlog
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    # Set up file logging if requested
    if log_file:
        log_file.parent.mkdir(parents=True, exist_ok=True)
        file_handler = logging.FileHandler(str(log_file))
        file_handler.setFormatter(logging.Formatter("%(message)s"))

        # Create separate logger for file with JSON output
        file_logger = logging.getLogger("translation_system_file")
        file_logger.addHandler(file_handler)
        file_logger.setLevel(getattr(logging, log_level.upper()))


class StructuredLogger:
    """
    Structured logger for translation operations.

    Provides consistent structured logging for all major operations in the
    translation system.
    """

    def __init__(self, name: str = "translation_system"):
        """
        Initialize structured logger.

        Args:
            name: Logger name
        """
        self.logger = structlog.get_logger(name)

    def log_job_start(self, job: TranslationJob, worker_id: str) -> None:
        """
        Log job start.

        Args:
            job: Translation job
            worker_id: Worker identifier
        """
        self.logger.info(
            "job_started",
            job_id=job.job_id,
            job_type=job.job_type.value,
            site_id=job.site_id,
            target_langs=job.target_langs,
            input_count=len(job.input_paths),
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
        self.logger.info(
            "job_completed",
            job_id=job.job_id,
            job_type=job.job_type.value,
            site_id=job.site_id,
            success=result.success,
            outputs_count=len(result.outputs),
            total_segments=result.stats.total_segments if result.stats else 0,
            tm_hits=result.stats.tm_hits if result.stats else 0,
            translated_segments=(
                result.stats.translated_segments if result.stats else 0
            ),
            duration_seconds=result.stats.duration_seconds if result.stats else 0,
            words_translated=result.stats.words_translated if result.stats else 0,
            error_count=len(result.errors),
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
        self.logger.error(
            "job_failed",
            job_id=job.job_id,
            job_type=job.job_type.value,
            site_id=job.site_id,
            error=str(error),
            error_type=type(error).__name__,
            worker_id=worker_id,
            exc_info=True,
        )

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
        self.logger.debug(
            "segment_translated",
            segment_id=segment.id,
            source_text=segment.source_text[:100],  # Truncate long text
            translation=translation[:100],
            tm_hit=tm_result.hit,
            tm_source=tm_result.source if tm_result.hit else "none",
            confidence=tm_result.confidence if tm_result.hit else 0.0,
            model_used=model_used,
            site_id=segment.site_id,
            source_lang=segment.source_lang,
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
        self.logger.info(
            "file_translation_started",
            site_id=site_id,
            file_path=str(file_path),
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
        self.logger.info(
            "file_translation_completed",
            site_id=site_id,
            file_path=str(file_path),
            success=result.success,
            outputs=list(result.outputs.keys()),
            total_segments=result.stats.total_segments if result.stats else 0,
            tm_hits=result.stats.tm_hits if result.stats else 0,
            duration_seconds=result.stats.duration_seconds if result.stats else 0,
            errors=result.errors,
        )

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
        self.logger.debug(
            "tm_lookup",
            site_id=site_id,
            src_lang=src_lang,
            tgt_lang=tgt_lang,
            source_text=text[:100],
            hit=result.hit,
            source=result.source if result.hit else "none",
            confidence=result.confidence if result.hit else 0.0,
        )

    def log_sweep_started(self, site_id: str, sweep_id: str) -> None:
        """
        Log sweep operation start.

        Args:
            site_id: Site identifier
            sweep_id: Sweep identifier
        """
        self.logger.info(
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
        self.logger.info(
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
        self.logger.info(
            "sweep_completed",
            site_id=site_id,
            sweep_id=sweep_id,
            total_jobs=total_jobs,
            duration_seconds=duration_seconds,
        )

    def log_error(self, context: Dict[str, Any], error: Exception) -> None:
        """
        Log error with full context.

        Args:
            context: Context dictionary
            error: Exception that occurred
        """
        self.logger.error(
            "error_occurred",
            **context,
            error=str(error),
            error_type=type(error).__name__,
            exc_info=True,
        )

    def log_warning(self, message: str, **kwargs: Any) -> None:
        """
        Log warning with context.

        Args:
            message: Warning message
            **kwargs: Additional context
        """
        self.logger.warning(message, **kwargs)

    def log_info(self, message: str, **kwargs: Any) -> None:
        """
        Log info message with context.

        Args:
            message: Info message
            **kwargs: Additional context
        """
        self.logger.info(message, **kwargs)

    def log_debug(self, message: str, **kwargs: Any) -> None:
        """
        Log debug message with context.

        Args:
            message: Debug message
            **kwargs: Additional context
        """
        self.logger.debug(message, **kwargs)


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
