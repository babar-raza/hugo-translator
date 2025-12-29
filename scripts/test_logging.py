#!/usr/bin/env python3
"""
Test script to demonstrate the new structured logging system.

This script shows:
1. Dual output (colored console + NDJSON file)
2. Correlation ID tracking
3. Comprehensive logging methods for all components
4. Log rotation
"""

import sys
from pathlib import Path

# Add project root to path
project_root = Path(__file__).parent.parent
sys.path.insert(0, str(project_root))

from src.observability.logger import (
    setup_structured_logging,
    get_logger,
    LogContext,
)


def test_basic_logging():
    """Test basic logging functionality."""
    logger = get_logger("test")

    print("\n=== Testing Basic Logging ===")
    logger.log_info("test_started", component="test_script")
    logger.log_debug("debug_message", detail="This is a debug message")
    logger.log_warning("test_warning", reason="This is a warning")
    logger.log_info("test_completed", component="test_script")


def test_correlation_context():
    """Test correlation ID tracking."""
    logger = get_logger("test")

    print("\n=== Testing Correlation Context ===")
    with LogContext(job_id="test-job-123", worker_id="test-worker"):
        logger.log_info("job_processing_started")
        logger.log_info("processing_file", file_path="/path/to/file.md")
        logger.log_info("job_processing_completed")


def test_tm_logging():
    """Test TM logging methods."""
    logger = get_logger("test")

    print("\n=== Testing TM Logging ===")

    # Simulate TM lookup
    from src.tm.models import LookupResult

    # TM hit
    hit_result = LookupResult(
        hit=True,
        translation="Hallo Welt",
        source="L2",
        confidence=1.0,
    )
    logger.log_tm_lookup(
        site_id="test.site",
        src_lang="en",
        tgt_lang="de",
        text="Hello World",
        result=hit_result,
    )

    # TM miss
    miss_result = LookupResult(hit=False, translation=None, source="", confidence=0.0)
    logger.log_tm_lookup(
        site_id="test.site",
        src_lang="en",
        tgt_lang="fr",
        text="Goodbye",
        result=miss_result,
    )

    # TM write
    logger.log_tm_write(
        site_id="test.site",
        src_lang="en",
        tgt_lang="de",
        source_text="Hello World",
        translation="Hallo Welt",
        layer="L2",
    )

    # TM cache stats
    logger.log_tm_cache_stats(
        layer="L1", hits=1000, misses=100, size=5000, max_size=10000
    )


def test_model_logging():
    """Test model runtime logging."""
    logger = get_logger("test")

    print("\n=== Testing Model Runtime Logging ===")

    logger.log_model_loading_start(model_name="m2m100_418m", device="cuda")
    logger.log_model_loading_complete(
        model_name="m2m100_418m",
        device="cuda",
        load_time_seconds=2.5,
        model_size_mb=418,
    )

    logger.log_inference_batch(
        model_name="m2m100_418m",
        batch_size=32,
        inference_time_seconds=0.5,
        tokens_per_second=1200,
    )

    logger.log_gpu_stats(
        device_id=0,
        memory_allocated_mb=2048,
        memory_reserved_mb=2560,
        memory_total_mb=4096,
        utilization_percent=85.5,
    )


def test_orchestrator_logging():
    """Test orchestrator logging."""
    logger = get_logger("test")

    print("\n=== Testing Orchestrator Logging ===")

    logger.log_orchestrator_started(worker_count=4, queue_backend="redis")

    logger.log_queue_job_enqueued(
        job_id="job-123",
        job_type="file",
        site_id="test.site",
        priority=5,
        queue_depth=10,
    )

    logger.log_queue_job_dequeued(
        job_id="job-123",
        worker_id="worker-1",
        wait_time_seconds=0.5,
        queue_depth=9,
    )

    logger.log_orchestrator_stopped(
        total_jobs_processed=1000, total_runtime_seconds=3600
    )


def test_validation_logging():
    """Test validation logging."""
    logger = get_logger("test")

    print("\n=== Testing Validation Logging ===")

    # Validation passed
    logger.log_validation_check(
        validator_name="placeholder_integrity",
        source_text="Hello {name}",
        translation="Hallo {name}",
        passed=True,
        severity="error",
        message=None,
    )

    # Validation failed
    logger.log_validation_check(
        validator_name="placeholder_integrity",
        source_text="Hello {name}",
        translation="Hallo",  # Missing placeholder
        passed=False,
        severity="error",
        message="Placeholder {name} missing in translation",
    )

    # Validator execution failed
    try:
        raise ValueError("Test validation error")
    except Exception as e:
        logger.log_validation_failed(
            file_path="/path/to/file.md", validator_name="yaml_validator", error=e
        )


def test_error_logging():
    """Test error logging with full context."""
    logger = get_logger("test")

    print("\n=== Testing Error Logging ===")

    try:
        # Simulate an error
        raise RuntimeError("Simulated translation error")
    except Exception as e:
        logger.log_error(
            {
                "operation": "translate_file",
                "file_path": "/path/to/file.md",
                "site_id": "test.site",
                "target_langs": ["de", "fr"],
            },
            e,
        )


def main():
    """Run all tests."""
    print("=" * 80)
    print("Testing Hugo Translator Structured Logging System")
    print("=" * 80)

    # Set up logging with dual output
    log_file = Path("data/logs/test-logging.ndjson")
    setup_structured_logging(
        log_level="DEBUG",
        log_file=log_file,
        console_output=True,
        max_bytes=10 * 1024 * 1024,  # 10MB
        backup_count=3,
    )

    print(f"\nLogs will be written to:")
    print(f"  Console: Colored, human-readable")
    print(f"  File: {log_file} (NDJSON format)")
    print(f"\nAfter running this script, you can:")
    print(f"  1. View colored output above")
    print(f"  2. Inspect NDJSON logs: cat {log_file}")
    print(f"  3. Feed NDJSON to LLM for analysis")
    print()

    # Run all tests
    test_basic_logging()
    test_correlation_context()
    test_tm_logging()
    test_model_logging()
    test_orchestrator_logging()
    test_validation_logging()
    test_error_logging()

    print("\n" + "=" * 80)
    print("Testing Complete!")
    print("=" * 80)
    print(f"\nCheck the log file at: {log_file.absolute()}")
    print("\nYou can now:")
    print(f"  1. View logs: cat {log_file}")
    print(f"  2. Filter logs: grep '\"level\":\"error\"' {log_file}")
    print(f"  3. Copy to LLM: cat {log_file} | clip (Windows) or pbcopy (Mac)")
    print()


if __name__ == "__main__":
    main()
