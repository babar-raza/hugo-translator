# Comprehensive Logging Guide for LLM-Based Troubleshooting

This guide explains how to use the enhanced structured logging system designed for feeding logs to LLMs for debugging and troubleshooting.

## Overview

The logging system provides:

- **Dual Output**: NDJSON files for LLM analysis + colored console output for humans
- **Log Rotation**: Automatic rotation at 100MB with 10 backup files
- **Correlation Tracking**: Trace operations across components with correlation IDs
- **Comprehensive Coverage**: Logging methods for all major components
- **Structured Data**: Every log entry is a JSON object with full context

## Configuration

### Global Configuration (config/global.yaml)

```yaml
observability:
  logging:
    enabled: true  # Enable structured logging
    log_level: "DEBUG"  # DEBUG, INFO, WARNING, ERROR, CRITICAL
    console_output: true  # Enable colored console output
    file_output: true  # Enable NDJSON file output
    log_file: "./data/logs/hugo-translator.ndjson"  # Path to log file
    max_file_size_mb: 100  # Max size before rotation (MB)
    backup_count: 10  # Number of rotated files to keep

    # Component-specific logging levels (optional overrides)
    components:
      orchestrator: "INFO"  # Job queue, scheduling
      translation_engine: "INFO"  # Segment extraction, translation
      tm: "DEBUG"  # TM lookups, writes, cache stats
      model_runtime: "INFO"  # Model loading, inference
      validation: "INFO"  # Validation checks
      worker: "INFO"  # Worker operations

    # Enable correlation IDs for cross-component tracing
    enable_correlation_ids: true
```

### CLI Override

```bash
# Override log level via CLI
translate-hugo --log-level DEBUG

# Override log file location
translate-hugo --log-file custom-logs.ndjson

# Both
translate-hugo --log-level DEBUG --log-file debug.ndjson
```

## Log Output Formats

### Console Output (Human-Readable)

```
2025-12-27 10:15:23 [info     ] job_started                    correlation_id=abc-123 job_id=job-456 job_type=file site_id=kb.aspose.net
```

### File Output (NDJSON for LLM)

```json
{"event": "job_started", "correlation_id": "abc-123", "job_id": "job-456", "job_type": "file", "site_id": "kb.aspose.net", "target_langs": ["de", "fr"], "input_count": 10, "priority": 5, "mode": "normal", "worker_id": "worker-1", "timestamp": "2025-12-27T10:15:23.123456Z", "level": "info", "logger": "translation_system"}
```

Each line in the NDJSON file is a complete JSON object that can be easily parsed by LLMs.

## Using Structured Logging in Your Code

### Basic Setup

```python
from src.observability.logger import get_logger, LogContext

# Get logger instance
logger = get_logger("my_component")

# Basic logging
logger.log_info("operation_started", component="my_component", count=10)
logger.log_warning("high_memory_usage", memory_mb=1024)
logger.log_error({"component": "my_component"}, error)
```

### Using Correlation Context

Correlation IDs automatically track operations across components:

```python
from src.observability.logger import LogContext, get_logger

logger = get_logger()

# Create correlation context for a job
with LogContext(job_id="job-123", worker_id="worker-1"):
    # All logs within this context will include job_id and worker_id
    logger.log_info("processing_started")

    # Call other functions - they inherit the context
    process_file(file_path)

    logger.log_info("processing_completed")
```

## Comprehensive Logging Methods

### Job Lifecycle

```python
from src.observability.logger import get_logger

logger = get_logger()

# Log job start
logger.log_job_start(job, worker_id="worker-1")

# Log job completion
logger.log_job_complete(job, result, worker_id="worker-1")

# Log job failure
logger.log_job_failed(job, error, worker_id="worker-1")
```

### Translation Memory (TM) Operations

```python
# Log TM lookup
logger.log_tm_lookup(
    site_id="kb.aspose.net",
    src_lang="en",
    tgt_lang="de",
    text="Hello world",
    result=lookup_result
)

# Log TM write
logger.log_tm_write(
    site_id="kb.aspose.net",
    src_lang="en",
    tgt_lang="de",
    source_text="Hello",
    translation="Hallo",
    layer="L2"
)

# Log TM cache statistics
logger.log_tm_cache_stats(
    layer="L1",
    hits=1000,
    misses=100,
    size=5000,
    max_size=10000
)
```

### Model Runtime & GPU

```python
# Log model loading
logger.log_model_loading_start(model_name="m2m100_418m", device="cuda")
logger.log_model_loading_complete(
    model_name="m2m100_418m",
    device="cuda",
    load_time_seconds=2.5,
    model_size_mb=418
)

# Log inference batch
logger.log_inference_batch(
    model_name="m2m100_418m",
    batch_size=32,
    inference_time_seconds=0.5,
    tokens_per_second=1200
)

# Log GPU stats
logger.log_gpu_stats(
    device_id=0,
    memory_allocated_mb=2048,
    memory_reserved_mb=2560,
    memory_total_mb=4096,
    utilization_percent=85.5
)
```

### Orchestrator & Queue

```python
# Log job enqueued
logger.log_queue_job_enqueued(
    job_id="job-123",
    job_type="file",
    site_id="kb.aspose.net",
    priority=5,
    queue_depth=10
)

# Log job dequeued
logger.log_queue_job_dequeued(
    job_id="job-123",
    worker_id="worker-1",
    wait_time_seconds=0.5,
    queue_depth=9
)

# Log orchestrator lifecycle
logger.log_orchestrator_started(worker_count=4, queue_backend="redis")
logger.log_orchestrator_stopped(total_jobs_processed=1000, total_runtime_seconds=3600)
```

### Validation

```python
# Log validation check
logger.log_validation_check(
    validator_name="placeholder_integrity",
    source_text="Hello {name}",
    translation="Hallo {name}",
    passed=True,
    severity="error",
    message=None
)

# Log validation failure
logger.log_validation_failed(
    file_path="/path/to/file.md",
    validator_name="yaml_validator",
    error=exception
)
```

### File Translation

```python
# Log file translation start
logger.log_file_translation_start(
    site_id="kb.aspose.net",
    file_path=Path("content/page.md"),
    target_langs=["de", "fr"]
)

# Log file translation complete
logger.log_file_translation_complete(
    site_id="kb.aspose.net",
    file_path=Path("content/page.md"),
    result=translation_result
)

# Log segment translation (verbose, for debugging)
logger.log_segment_translation(
    segment=segment,
    tm_result=lookup_result,
    translation="translated text",
    model_used="m2m100_418m"
)
```

## Adding Logging to Your Components

### Example: Adding Logging to TM Layer

```python
# src/tm/l2_persistent.py
from src.observability.logger import get_logger, LogContext

logger = get_logger("tm.l2")

class L2PersistentCache:
    def lookup(self, site_id: str, src_lang: str, tgt_lang: str, text: str):
        # Lookup in cache
        result = self._query_db(site_id, src_lang, tgt_lang, text)

        # Log the lookup
        logger.log_tm_lookup(site_id, src_lang, tgt_lang, text, result)

        return result

    def write(self, site_id: str, src_lang: str, tgt_lang: str, source: str, translation: str):
        # Write to cache
        self._insert_db(site_id, src_lang, tgt_lang, source, translation)

        # Log the write
        logger.log_tm_write(site_id, src_lang, tgt_lang, source, translation, layer="L2")
```

### Example: Adding Logging to Model Runtime

```python
# src/model_runtime/loader.py
from src.observability.logger import get_logger
import time

logger = get_logger("model_runtime")

class ModelLoader:
    def load_model(self, model_name: str, device: str):
        # Log loading start
        logger.log_model_loading_start(model_name, device)

        start_time = time.time()
        model = self._load_model_impl(model_name, device)
        load_time = time.time() - start_time

        # Log loading complete
        logger.log_model_loading_complete(
            model_name,
            device,
            load_time,
            model_size_mb=self._get_model_size(model)
        )

        return model
```

### Example: Error Logging with Full Context

```python
from src.observability.logger import get_logger

logger = get_logger()

try:
    result = process_translation(file_path, target_langs)
except Exception as e:
    # Log error with full context and stack trace
    logger.log_error(
        {
            "operation": "process_translation",
            "file_path": str(file_path),
            "target_langs": target_langs,
            "site_id": site_id,
        },
        e
    )
    raise
```

## Feeding Logs to LLM for Troubleshooting

### Extract Relevant Logs

```bash
# Get all ERROR logs
grep '"level":"error"' data/logs/hugo-translator.ndjson > errors.ndjson

# Get logs for specific correlation ID
grep '"correlation_id":"abc-123"' data/logs/hugo-translator.ndjson > trace.ndjson

# Get logs for specific component
grep '"logger":"tm' data/logs/hugo-translator.ndjson > tm-logs.ndjson

# Get logs for specific time range (requires jq)
cat data/logs/hugo-translator.ndjson | jq -c 'select(.timestamp >= "2025-12-27T10:00:00" and .timestamp <= "2025-12-27T11:00:00")'
```

### Feed to LLM

```bash
# Copy errors to clipboard (Windows)
type errors.ndjson | clip

# Or create a focused summary
echo "Here are the error logs from my translation system. Please analyze them and identify the root cause:" > prompt.txt
type errors.ndjson >> prompt.txt
```

### Sample LLM Prompts

**For debugging errors:**
```
I'm debugging translation errors in my system. Here are the NDJSON logs showing the error sequence.
Each line is a JSON log entry with timestamp, correlation_id, and full context.
Please analyze the logs and:
1. Identify the root cause
2. Show the sequence of events leading to the error
3. Suggest fixes

[paste NDJSON logs]
```

**For performance analysis:**
```
Here are logs from my translation system showing model inference and TM cache operations.
Please analyze the performance and identify bottlenecks:

[paste NDJSON logs with inference_batch and tm_cache_stats events]
```

**For tracing a specific job:**
```
Here are all logs for correlation_id abc-123, showing a complete translation job execution.
Please trace through the execution and explain what happened at each step:

[paste filtered logs for that correlation_id]
```

## Log Rotation

Logs automatically rotate when they reach 100MB (configurable). Rotated files are named:

```
data/logs/hugo-translator.ndjson         # Current log file
data/logs/hugo-translator.ndjson.1       # Most recent backup
data/logs/hugo-translator.ndjson.2       # Older backup
...
data/logs/hugo-translator.ndjson.10      # Oldest backup (then deleted)
```

## Best Practices

1. **Use Correlation Context**: Wrap job processing in `LogContext` to automatically track operations

2. **Log Key Decisions**: Always log when the system makes important decisions (fallbacks, retries, cache hits/misses)

3. **Include Full Context**: When logging errors, include all relevant context (file paths, languages, configuration)

4. **Use Appropriate Log Levels**:
   - `DEBUG`: Verbose details (segment-level operations, individual TM lookups)
   - `INFO`: Important milestones (job start/complete, file processing)
   - `WARNING`: Unexpected but handled (validation failures, fallbacks)
   - `ERROR`: Failures (exceptions, critical errors)

5. **Structured Data**: Always use keyword arguments to log structured data, not formatted strings:
   ```python
   # Good
   logger.log_info("file_processed", file_path=str(path), segments=10)

   # Bad (not machine-readable)
   logger.log_info(f"Processed {path} with {10} segments")
   ```

6. **Sample High-Volume Operations**: For very high-volume operations (segment-level), consider sampling:
   ```python
   import random
   if random.random() < 0.1:  # 10% sampling
       logger.log_segment_translation(segment, tm_result, translation)
   ```

## Example: Complete Workflow with Logging

```python
from src.observability.logger import get_logger, LogContext
from pathlib import Path

logger = get_logger()

def translate_site(site_id: str, files: list[Path], target_langs: list[str]):
    """Translate a site with comprehensive logging."""

    # Create correlation context for this operation
    with LogContext(correlation_id=f"site-{site_id}"):
        logger.log_info(
            "site_translation_started",
            site_id=site_id,
            file_count=len(files),
            target_langs=target_langs
        )

        try:
            for file_path in files:
                # File-level context
                with LogContext(job_id=f"file-{file_path.name}"):
                    logger.log_file_translation_start(site_id, file_path, target_langs)

                    try:
                        result = translate_file(site_id, file_path, target_langs)
                        logger.log_file_translation_complete(site_id, file_path, result)
                    except Exception as e:
                        logger.log_error(
                            {
                                "operation": "file_translation",
                                "site_id": site_id,
                                "file_path": str(file_path),
                                "target_langs": target_langs
                            },
                            e
                        )
                        raise

            logger.log_info(
                "site_translation_completed",
                site_id=site_id,
                files_processed=len(files)
            )

        except Exception as e:
            logger.log_error(
                {
                    "operation": "site_translation",
                    "site_id": site_id,
                    "file_count": len(files)
                },
                e
            )
            raise
```

## Troubleshooting the Logging System

### Logs Not Appearing in File

1. Check `config/global.yaml` - ensure `observability.logging.file_output: true`
2. Check file permissions on `data/logs/` directory
3. Check if log file path is writable
4. Look for "Warning: Failed to load logging config" message on startup

### Logs Not Structured

1. Ensure you're using the logging methods on `StructuredLogger`, not `logging` module directly
2. Verify `setup_structured_logging()` was called during startup
3. Check that you're using keyword arguments, not formatted strings

### Missing Correlation IDs

1. Ensure you're wrapping operations in `LogContext`
2. Check `config/global.yaml` - ensure `enable_correlation_ids: true`
3. Verify context managers are being used with `with` statement

## Next Steps

To add comprehensive logging throughout your system:

1. Identify high-value logging points (job processing, TM operations, model inference, errors)
2. Add logging calls using the appropriate methods
3. Test with `log_level: DEBUG` to see all logs
4. Adjust log levels per component as needed
5. Set up regular log analysis workflows

The logging system is now ready to capture comprehensive operational data for LLM-based debugging and troubleshooting!
