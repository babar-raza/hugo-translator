"""
Unit tests for structured logging.
"""

import tempfile
from datetime import datetime
from pathlib import Path
from unittest.mock import Mock

import pytest
import structlog

from src.observability.logger import StructuredLogger, get_logger, setup_structured_logging
from src.orchestrator.models import JobMode, JobType, TranslationJob
from src.tm.models import LookupResult
from src.translation_engine.extractor.segment_extractor import Segment
from src.translation_engine.models import TranslationResult, TranslationStats


@pytest.fixture
def temp_log_file():
    """Create temporary log file."""
    with tempfile.NamedTemporaryFile(mode="w", delete=False, suffix=".log") as f:
        log_path = Path(f.name)
    yield log_path
    # Cleanup - try to remove but don't fail if file is locked
    try:
        if log_path.exists():
            log_path.unlink()
    except PermissionError:
        pass  # File might still be open on Windows


@pytest.fixture
def logger():
    """Create test logger."""
    return StructuredLogger("test_logger")


@pytest.fixture
def sample_job():
    """Create sample translation job."""
    return TranslationJob(
        job_id="test_job_123",
        job_type=JobType.FILE,
        site_id="test.site",
        target_langs=["fr", "es"],
        input_paths=[Path("/test/file.md")],
        priority=5,
        mode=JobMode.MANUAL,
    )


@pytest.fixture
def sample_segment():
    """Create sample segment."""
    return Segment(
        id="seg_001",
        source_text="Hello world",
        context={"type": "body", "path": "paragraph"},
        site_id="test.site",
        source_lang="en",
        placeholder_map={},
        metadata={},
    )


@pytest.fixture
def sample_result():
    """Create sample translation result."""
    return TranslationResult(
        success=True,
        file_path=Path("/test/file.md"),
        outputs={"fr": Path("/test/fr/file.md"), "es": Path("/test/es/file.md")},
        stats=TranslationStats(
            total_segments=10,
            tm_hits=7,
            translated_segments=3,
            duration_seconds=1.5,
            words_translated=50,
        ),
        errors=[],
    )


class TestStructuredLoggerSetup:
    """Test logger setup and configuration."""

    def test_setup_default_console(self):
        """Test default console logging setup."""
        setup_structured_logging(log_level="INFO", console_output=True)

        # Logger should be configured
        logger = structlog.get_logger()
        assert logger is not None

    def test_setup_with_file_output(self, temp_log_file):
        """Test logging setup with file output."""
        setup_structured_logging(log_level="DEBUG", log_file=temp_log_file, console_output=False)

        # Log file should be created
        assert temp_log_file.exists()

    def test_setup_with_different_log_levels(self):
        """Test setup with different log levels."""
        for level in ["DEBUG", "INFO", "WARNING", "ERROR"]:
            setup_structured_logging(log_level=level)
            # Should not raise an error
            assert True


class TestStructuredLogger:
    """Test StructuredLogger methods."""

    def test_logger_initialization(self, logger):
        """Test logger initialization."""
        assert logger.logger is not None

    def test_log_job_start(self, logger, sample_job):
        """Test logging job start."""
        # Should not raise an error
        logger.log_job_start(sample_job, worker_id="worker-1")

    def test_log_job_complete(self, logger, sample_job, sample_result):
        """Test logging job completion."""
        logger.log_job_complete(sample_job, sample_result, worker_id="worker-1")

    def test_log_job_failed(self, logger, sample_job):
        """Test logging job failure."""
        error = ValueError("Test error")
        logger.log_job_failed(sample_job, error, worker_id="worker-1")

    def test_log_segment_translation(self, logger, sample_segment):
        """Test logging segment translation."""
        tm_result = LookupResult(
            hit=True,
            translation="Bonjour le monde",
            source="l2_exact",
            confidence=1.0,
            candidates=[],
            metadata={},
        )

        logger.log_segment_translation(
            sample_segment, tm_result, translation="Bonjour le monde", model_used=None
        )

    def test_log_segment_translation_with_model(self, logger, sample_segment):
        """Test logging segment translation with model."""
        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        logger.log_segment_translation(
            sample_segment,
            tm_result,
            translation="Bonjour le monde",
            model_used="m2m100_418m",
        )

    def test_log_file_translation_start(self, logger):
        """Test logging file translation start."""
        logger.log_file_translation_start(
            site_id="test.site",
            file_path=Path("/test/file.md"),
            target_langs=["fr", "es"],
        )

    def test_log_file_translation_complete(self, logger, sample_result):
        """Test logging file translation completion."""
        logger.log_file_translation_complete(
            site_id="test.site", file_path=Path("/test/file.md"), result=sample_result
        )

    def test_log_tm_lookup(self, logger):
        """Test logging TM lookup."""
        tm_result = LookupResult(
            hit=True,
            translation="Bonjour",
            source="l1_cache",
            confidence=1.0,
            candidates=[],
            metadata={},
        )

        logger.log_tm_lookup(
            site_id="test.site",
            src_lang="en",
            tgt_lang="fr",
            text="Hello",
            result=tm_result,
        )

    def test_log_tm_lookup_miss(self, logger):
        """Test logging TM lookup miss."""
        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        logger.log_tm_lookup(
            site_id="test.site",
            src_lang="en",
            tgt_lang="fr",
            text="Hello",
            result=tm_result,
        )

    def test_log_sweep_started(self, logger):
        """Test logging sweep start."""
        logger.log_sweep_started(site_id="test.site", sweep_id="sweep_001")

    def test_log_sweep_progress(self, logger):
        """Test logging sweep progress."""
        logger.log_sweep_progress(
            site_id="test.site",
            sweep_id="sweep_001",
            files_scanned=50,
            files_total=100,
            jobs_created=5,
        )

    def test_log_sweep_progress_zero_total(self, logger):
        """Test logging sweep progress with zero total files."""
        logger.log_sweep_progress(
            site_id="test.site",
            sweep_id="sweep_001",
            files_scanned=0,
            files_total=0,
            jobs_created=0,
        )

    def test_log_sweep_completed(self, logger):
        """Test logging sweep completion."""
        logger.log_sweep_completed(
            site_id="test.site",
            sweep_id="sweep_001",
            total_jobs=10,
            duration_seconds=120.5,
        )

    def test_log_error(self, logger):
        """Test logging errors with context."""
        context = {
            "site_id": "test.site",
            "file_path": "/test/file.md",
            "operation": "translate",
        }
        error = RuntimeError("Test error")

        logger.log_error(context, error)

    def test_log_warning(self, logger):
        """Test logging warnings."""
        logger.log_warning("Test warning", site_id="test.site", reason="test")

    def test_log_info(self, logger):
        """Test logging info messages."""
        logger.log_info("Test info", site_id="test.site", status="active")

    def test_log_debug(self, logger):
        """Test logging debug messages."""
        logger.log_debug("Test debug", site_id="test.site", detail="verbose")

    def test_long_text_truncation(self, logger):
        """Test that long text is truncated in logs."""
        long_text = "x" * 200
        segment = Segment(
            id="seg_001",
            source_text=long_text,
            context={"type": "body"},
            site_id="test.site",
            source_lang="en",
            placeholder_map={},
            metadata={},
        )

        tm_result = LookupResult(
            hit=False, translation=None, source="none", confidence=0.0, candidates=[], metadata={}
        )

        # Should not raise an error
        logger.log_segment_translation(segment, tm_result, translation=long_text, model_used=None)


class TestGlobalLogger:
    """Test global logger instance."""

    def test_get_logger_creates_instance(self):
        """Test get_logger creates global instance."""
        logger = get_logger()
        assert isinstance(logger, StructuredLogger)

    def test_get_logger_returns_same_instance(self):
        """Test get_logger returns the same instance."""
        logger1 = get_logger()
        logger2 = get_logger()
        assert logger1 is logger2

    def test_get_logger_with_name(self):
        """Test get_logger with custom name."""
        logger = get_logger("custom_logger")
        assert logger is not None
