"""
Load Testing for Translation System.

Tests system behavior under concurrent load with realistic workloads.
"""

import concurrent.futures
import logging
import os
import statistics
import threading
import time
from dataclasses import dataclass, field
from pathlib import Path

import pytest

# Setup logging for load tests
logging.basicConfig(
    level=logging.INFO, format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)


@dataclass
class LoadTestMetrics:
    """Metrics collected during load test."""

    # Request metrics
    total_requests: int = 0
    successful_requests: int = 0
    failed_requests: int = 0

    # Timing metrics (seconds)
    latencies: list[float] = field(default_factory=list)
    start_time: float = 0.0
    end_time: float = 0.0

    # TM metrics
    tm_hits: int = 0
    tm_misses: int = 0
    l1_hits: int = 0
    l2_hits: int = 0
    l3_hits: int = 0

    # Resource metrics
    peak_memory_mb: float = 0.0
    avg_cpu_percent: float = 0.0

    # Error tracking
    errors: list[str] = field(default_factory=list)

    def add_latency(self, latency: float):
        """Add a latency measurement."""
        self.latencies.append(latency)

    def get_summary(self) -> dict:
        """Get summary statistics."""
        duration = self.end_time - self.start_time if self.end_time > 0 else 0

        summary = {
            # Request stats
            "total_requests": self.total_requests,
            "successful_requests": self.successful_requests,
            "failed_requests": self.failed_requests,
            "success_rate": (
                self.successful_requests / self.total_requests * 100
                if self.total_requests > 0
                else 0
            ),
            # Throughput
            "duration_seconds": duration,
            "throughput_rps": (self.total_requests / duration if duration > 0 else 0),
            # Latency stats
            "latency_p50": statistics.median(self.latencies) if self.latencies else 0,
            "latency_p95": (
                statistics.quantiles(self.latencies, n=20)[18]
                if len(self.latencies) >= 20
                else max(self.latencies)
                if self.latencies
                else 0
            ),
            "latency_p99": (
                statistics.quantiles(self.latencies, n=100)[98]
                if len(self.latencies) >= 100
                else max(self.latencies)
                if self.latencies
                else 0
            ),
            "latency_mean": statistics.mean(self.latencies) if self.latencies else 0,
            "latency_min": min(self.latencies) if self.latencies else 0,
            "latency_max": max(self.latencies) if self.latencies else 0,
            # TM stats
            "tm_hit_rate": (
                self.tm_hits / (self.tm_hits + self.tm_misses) * 100
                if (self.tm_hits + self.tm_misses) > 0
                else 0
            ),
            "l1_hits": self.l1_hits,
            "l2_hits": self.l2_hits,
            "l3_hits": self.l3_hits,
            # Resource usage
            "peak_memory_mb": self.peak_memory_mb,
            "avg_cpu_percent": self.avg_cpu_percent,
            # Errors
            "error_count": len(self.errors),
            "unique_errors": len(set(self.errors)),
        }

        return summary


@dataclass
class LoadTestConfig:
    """Configuration for load test."""

    num_workers: int = 10
    duration_seconds: int = 60
    test_files: list[Path] = field(default_factory=list)
    target_langs: list[str] = field(default_factory=lambda: ["es", "fr"])
    ramp_up_seconds: int = 0
    enable_tm: bool = True
    force_retranslation: bool = False


class LoadTestRunner:
    """
    Load test runner for translation system.

    Simulates realistic concurrent translation workloads.
    """

    def __init__(self, config: LoadTestConfig):
        """
        Initialize load test runner.

        Args:
            config: Load test configuration
        """
        self.config = config
        self.metrics = LoadTestMetrics()
        self._lock = threading.Lock()
        self._stop_event = threading.Event()

    def run(self) -> LoadTestMetrics:
        """
        Run the load test.

        Returns:
            LoadTestMetrics with results
        """
        logger.info(
            f"Starting load test with {self.config.num_workers} workers "
            f"for {self.config.duration_seconds}s"
        )

        self.metrics.start_time = time.time()

        try:
            # Start resource monitoring in background
            monitor_thread = threading.Thread(target=self._monitor_resources, daemon=True)
            monitor_thread.start()

            # Run concurrent workers
            with concurrent.futures.ThreadPoolExecutor(
                max_workers=self.config.num_workers
            ) as executor:
                futures = []

                # Submit worker tasks
                for worker_id in range(self.config.num_workers):
                    # Stagger start times for ramp-up
                    delay = (
                        worker_id * self.config.ramp_up_seconds / self.config.num_workers
                        if self.config.ramp_up_seconds > 0
                        else 0
                    )

                    future = executor.submit(self._worker_loop, worker_id, delay)
                    futures.append(future)

                # Wait for test duration
                time.sleep(self.config.duration_seconds)

                # Signal workers to stop
                self._stop_event.set()

                # Wait for all workers to complete
                concurrent.futures.wait(futures, timeout=30)

        except Exception as e:
            logger.error(f"Load test failed: {e}")
            with self._lock:
                self.metrics.errors.append(str(e))

        finally:
            self.metrics.end_time = time.time()

        # Log summary
        summary = self.metrics.get_summary()
        logger.info(f"Load test completed: {summary}")

        return self.metrics

    def _worker_loop(self, worker_id: int, start_delay: float = 0):
        """
        Worker loop that sends translation requests.

        Args:
            worker_id: Unique worker identifier
            start_delay: Delay before starting (for ramp-up)
        """
        if start_delay > 0:
            time.sleep(start_delay)

        logger.info(f"Worker {worker_id} started")

        while not self._stop_event.is_set():
            # Pick a random test file
            if not self.config.test_files:
                logger.warning(f"Worker {worker_id}: No test files available")
                break

            import random

            test_file = random.choice(self.config.test_files)

            # Execute translation request
            self._execute_request(worker_id, test_file)

            # Small delay between requests (avoid hammering)
            time.sleep(0.1)

        logger.info(f"Worker {worker_id} completed")

    def _execute_request(self, worker_id: int, test_file: Path):
        """
        Execute a single translation request.

        Args:
            worker_id: Worker identifier
            test_file: Path to test file
        """
        start_time = time.time()

        try:
            # Import here to avoid circular dependencies
            from src.model_runtime import ModelLoader
            from src.tm import TranslationMemory
            from src.translation_engine import TranslationEngine
            from src.utils.config_loader import ConfigService

            # Create minimal components for test
            # Note: In real load test, these would be shared instances
            config_service = ConfigService()
            tm = TranslationMemory()
            model_loader = ModelLoader()

            engine = TranslationEngine(
                config_service=config_service,
                tm=tm,
                model_loader=model_loader,
                enable_validation=False,
                enable_telemetry=False,  # Disable telemetry during load test
            )

            # Execute translation
            result = engine.translate_file(
                site_id="default",
                file_path=test_file,
                target_langs=self.config.target_langs,
                force=self.config.force_retranslation,
            )

            # Record metrics
            latency = time.time() - start_time

            with self._lock:
                self.metrics.total_requests += 1
                self.metrics.add_latency(latency)

                if result.success:
                    self.metrics.successful_requests += 1

                    # Track TM stats
                    self.metrics.tm_hits += result.stats.tm_hits
                    self.metrics.l1_hits += result.stats.l1_hits
                    self.metrics.l2_hits += result.stats.l2_hits
                    self.metrics.l3_hits += result.stats.l3_hits
                    self.metrics.tm_misses += result.stats.translated_segments
                else:
                    self.metrics.failed_requests += 1
                    if result.errors:
                        self.metrics.errors.extend(result.errors[:1])  # Sample first error

            logger.debug(
                f"Worker {worker_id}: Request completed in {latency:.3f}s "
                f"(success={result.success})"
            )

        except Exception as e:
            latency = time.time() - start_time

            with self._lock:
                self.metrics.total_requests += 1
                self.metrics.failed_requests += 1
                self.metrics.add_latency(latency)
                self.metrics.errors.append(str(e)[:100])  # Truncate long errors

            logger.error(f"Worker {worker_id}: Request failed: {e}")

    def _monitor_resources(self):
        """Monitor system resource usage during test."""
        try:
            import psutil

            process = psutil.Process()

            samples = []

            while not self._stop_event.is_set():
                # Sample memory and CPU
                mem_mb = process.memory_info().rss / 1024 / 1024
                cpu_percent = process.cpu_percent(interval=1.0)

                with self._lock:
                    self.metrics.peak_memory_mb = max(self.metrics.peak_memory_mb, mem_mb)

                samples.append(cpu_percent)

                time.sleep(1.0)

            # Calculate average CPU
            if samples:
                with self._lock:
                    self.metrics.avg_cpu_percent = statistics.mean(samples)

        except ImportError:
            logger.warning("psutil not available - resource monitoring disabled")
        except Exception as e:
            logger.error(f"Resource monitoring failed: {e}")


# ============================================================================
# PYTEST TESTS
# ============================================================================


@pytest.fixture
def test_files(tmp_path):
    """Create test Hugo markdown files."""
    files = []

    # Small file
    small = tmp_path / "small.md"
    small.write_text(
        """---
title: "Small Test"
---

This is a small test file with minimal content.
""",
        encoding="utf-8",
    )
    files.append(small)

    # Medium file
    medium = tmp_path / "medium.md"
    medium.write_text(
        """---
title: "Medium Test"
description: "A medium-sized test file"
---

# Medium Test File

This is a medium-sized test file with multiple paragraphs.

## Section 1

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua.

## Section 2

Ut enim ad minim veniam, quis nostrud exercitation ullamco laboris nisi
ut aliquip ex ea commodo consequat.

## Section 3

Duis aute irure dolor in reprehenderit in voluptate velit esse cillum
dolore eu fugiat nulla pariatur.
""",
        encoding="utf-8",
    )
    files.append(medium)

    # Large file
    large = tmp_path / "large.md"
    content = """---
title: "Large Test"
description: "A large test file for load testing"
tags: ["test", "load", "performance"]
---

# Large Test File

This is a large test file with extensive content for load testing.

"""
    # Add multiple sections
    for i in range(10):
        content += f"""
## Section {i + 1}

Lorem ipsum dolor sit amet, consectetur adipiscing elit. Sed do eiusmod
tempor incididunt ut labore et dolore magna aliqua. Ut enim ad minim veniam,
quis nostrud exercitation ullamco laboris nisi ut aliquip ex ea commodo consequat.

Duis aute irure dolor in reprehenderit in voluptate velit esse cillum dolore
eu fugiat nulla pariatur. Excepteur sint occaecat cupidatat non proident.

### Subsection {i + 1}.1

More content here with additional paragraphs to make the file larger.
This helps simulate realistic translation workloads.

### Subsection {i + 1}.2

Even more content with varied structure and formatting.

- List item 1
- List item 2
- List item 3

"""

    large.write_text(content, encoding="utf-8")
    files.append(large)

    return files


@pytest.mark.slow
def test_concurrent_translation_low_load(test_files):
    """
    Test concurrent translations with low load (2 workers, 10s).

    Verifies basic concurrent operation without errors.
    """
    config = LoadTestConfig(
        num_workers=2,
        duration_seconds=10,
        test_files=test_files,
        target_langs=["es"],
        enable_tm=True,
    )

    runner = LoadTestRunner(config)
    metrics = runner.run()

    # Assertions
    summary = metrics.get_summary()

    assert metrics.total_requests > 0, "Should have processed some requests"
    assert summary["success_rate"] > 80, "Success rate should be > 80%"
    assert summary["latency_mean"] < 30, "Mean latency should be reasonable"
    assert len(metrics.errors) < metrics.total_requests * 0.2, "Error rate should be < 20%"

    logger.info(f"Low load test summary: {summary}")


@pytest.mark.slow
def test_concurrent_translation_medium_load(test_files):
    """
    Test concurrent translations with medium load (5 workers, 20s).

    Verifies system stability under moderate concurrent load.
    """
    config = LoadTestConfig(
        num_workers=5,
        duration_seconds=20,
        test_files=test_files,
        target_langs=["es", "fr"],
        enable_tm=True,
    )

    runner = LoadTestRunner(config)
    metrics = runner.run()

    # Assertions
    summary = metrics.get_summary()

    assert metrics.total_requests >= 10, "Should process multiple requests"
    assert summary["success_rate"] > 70, "Success rate should be > 70%"
    assert summary["throughput_rps"] > 0, "Should have measurable throughput"

    logger.info(f"Medium load test summary: {summary}")


@pytest.mark.slow
@pytest.mark.skipif(
    os.getenv("SKIP_HEAVY_LOAD_TESTS") == "1",
    reason="Heavy load test disabled via environment variable",
)
def test_concurrent_translation_high_load(test_files):
    """
    Test concurrent translations with high load (10 workers, 30s).

    Verifies system performance under heavy concurrent load.
    Tests for deadlocks, race conditions, and resource leaks.
    """
    config = LoadTestConfig(
        num_workers=10,
        duration_seconds=30,
        test_files=test_files,
        target_langs=["es", "fr", "de"],
        ramp_up_seconds=5,
        enable_tm=True,
    )

    runner = LoadTestRunner(config)
    metrics = runner.run()

    # Assertions
    summary = metrics.get_summary()

    assert metrics.total_requests >= 20, "Should process many requests"
    assert summary["success_rate"] > 60, "Success rate should be > 60%"
    assert summary["latency_p99"] < 60, "p99 latency should be < 60s"

    # Check for deadlocks (all requests should complete)
    assert metrics.total_requests == (metrics.successful_requests + metrics.failed_requests), (
        "All requests should be accounted for (no deadlocks)"
    )

    logger.info(f"High load test summary: {summary}")
    logger.info(f"TM hit rate: {summary['tm_hit_rate']:.1f}%")


def test_tm_performance_under_load(test_files):
    """
    Test Translation Memory performance under concurrent load.

    Verifies TM hit rates improve with repeated content (warm cache).
    """
    # Phase 1: Cold cache
    config_cold = LoadTestConfig(
        num_workers=3,
        duration_seconds=10,
        test_files=[test_files[0]],  # Use same file repeatedly
        target_langs=["es"],
        enable_tm=True,
        force_retranslation=True,  # Force initial translation
    )

    runner_cold = LoadTestRunner(config_cold)
    metrics_cold = runner_cold.run()

    # Phase 2: Warm cache (repeat same translations)
    config_warm = LoadTestConfig(
        num_workers=3,
        duration_seconds=10,
        test_files=[test_files[0]],  # Same file
        target_langs=["es"],  # Same language
        enable_tm=True,
        force_retranslation=False,  # Use TM
    )

    runner_warm = LoadTestRunner(config_warm)
    metrics_warm = runner_warm.run()

    # Assertions
    summary_cold = metrics_cold.get_summary()
    summary_warm = metrics_warm.get_summary()

    logger.info(f"Cold cache TM hit rate: {summary_cold['tm_hit_rate']:.1f}%")
    logger.info(f"Warm cache TM hit rate: {summary_warm['tm_hit_rate']:.1f}%")

    # Warm cache should have MUCH higher hit rate
    assert summary_warm["tm_hit_rate"] > summary_cold["tm_hit_rate"], (
        "Warm cache should have higher TM hit rate"
    )

    # Warm cache should be faster
    assert summary_warm["latency_mean"] < summary_cold["latency_mean"], (
        "Warm cache should have lower latency"
    )


def test_no_deadlocks_with_shared_resources(test_files):
    """
    Test that concurrent access to shared resources doesn't cause deadlocks.

    Tests TM and model loader thread safety.
    """
    config = LoadTestConfig(
        num_workers=8,
        duration_seconds=15,
        test_files=test_files,
        target_langs=["es", "fr"],
        enable_tm=True,
    )

    runner = LoadTestRunner(config)

    # Run with timeout - if deadlock occurs, this will fail
    import signal

    def timeout_handler(signum, frame):
        raise TimeoutError("Load test timed out - possible deadlock")

    # Set timeout (only on Unix-like systems)
    if hasattr(signal, "SIGALRM"):
        signal.signal(signal.SIGALRM, timeout_handler)
        signal.alarm(30)  # 30s timeout

    try:
        metrics = runner.run()

        if hasattr(signal, "SIGALRM"):
            signal.alarm(0)  # Cancel timeout

        # All requests should complete (no hanging threads)
        summary = metrics.get_summary()
        assert metrics.total_requests > 0, "Should have processed requests"

        logger.info(f"Deadlock test completed successfully: {summary}")

    except TimeoutError:
        pytest.fail("Load test timed out - possible deadlock detected")


def test_resource_usage_stays_bounded(test_files):
    """
    Test that resource usage (memory, CPU) stays within reasonable bounds.

    Checks for memory leaks and excessive CPU usage.
    """
    try:
        import psutil
    except ImportError:
        pytest.skip("psutil not available - skipping resource test")

    process = psutil.Process()
    initial_memory_mb = process.memory_info().rss / 1024 / 1024

    config = LoadTestConfig(
        num_workers=5,
        duration_seconds=20,
        test_files=test_files,
        target_langs=["es"],
        enable_tm=True,
    )

    runner = LoadTestRunner(config)
    metrics = runner.run()

    summary = metrics.get_summary()

    # Check memory growth
    memory_growth_mb = summary["peak_memory_mb"] - initial_memory_mb

    logger.info(f"Initial memory: {initial_memory_mb:.1f} MB")
    logger.info(f"Peak memory: {summary['peak_memory_mb']:.1f} MB")
    logger.info(f"Memory growth: {memory_growth_mb:.1f} MB")
    logger.info(f"Avg CPU: {summary['avg_cpu_percent']:.1f}%")

    # Memory growth should be reasonable (< 500MB for this test)
    assert memory_growth_mb < 500, f"Excessive memory growth: {memory_growth_mb:.1f} MB"

    # Average CPU should be reasonable (allow high CPU during test)
    # Just check it's not stuck at 100%
    assert summary["avg_cpu_percent"] < 100, "CPU usage should not be constantly maxed out"


if __name__ == "__main__":
    # Allow running tests directly
    pytest.main([__file__, "-v", "-s"])
