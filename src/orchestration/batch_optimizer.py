"""
Batch Processing Optimizer.

Optimizes large-scale translation jobs through:
- Auto-tuned batch sizes based on available resources
- Dynamic parallelism adaptation
- Prefetching for pipeline efficiency
- Length-based sorting for better batching
- OOM handling with graceful degradation
"""

import logging
import os
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import List, Optional, Tuple

from src.utils.metrics import calc_stats

logger = logging.getLogger(__name__)


@dataclass
class BatchConfig:
    """Configuration for batch optimization."""

    # Batch sizing
    initial_batch_size: int = 32
    min_batch_size: int = 4
    max_batch_size: int = 128

    # Resource limits
    target_memory_mb: Optional[int] = None  # Auto-detect if None
    target_gpu_memory_mb: Optional[int] = None  # Auto-detect if None

    # Parallelism
    num_workers: Optional[int] = None  # Auto-detect if None
    prefetch_batches: int = 2

    # Optimization strategies
    sort_by_length: bool = True  # Sort segments by length for efficient batching
    dynamic_batch_size: bool = True  # Adjust batch size based on performance
    enable_prefetch: bool = True  # Prefetch next batch while processing current

    # Error handling
    oom_retry_enabled: bool = True  # Retry with smaller batch on OOM
    oom_reduction_factor: float = 0.5  # Reduce batch size by this factor on OOM


@dataclass
class BatchStats:
    """Statistics from batch processing."""

    total_segments: int = 0
    batches_processed: int = 0
    avg_batch_size: float = 0.0
    peak_memory_mb: float = 0.0
    peak_gpu_memory_mb: float = 0.0
    total_duration_seconds: float = 0.0
    avg_throughput_segments_per_sec: float = 0.0
    oom_events: int = 0
    batch_size_adjustments: int = 0


class BatchOptimizer:
    """
    Optimizes batch processing for translation jobs.

    Automatically tunes batch size, parallelism, and resource usage
    for optimal throughput on available hardware.
    """

    def __init__(self, config: BatchConfig):
        """
        Initialize batch optimizer.

        Args:
            config: Batch configuration
        """
        self.config = config
        self.stats = BatchStats()

        # Current batch size (adjusted dynamically)
        self._current_batch_size = config.initial_batch_size

        # Resource monitoring
        self._peak_memory_mb = 0.0
        self._peak_gpu_memory_mb = 0.0

        # Thread safety
        self._lock = threading.Lock()

        # BM-08: Timing instrumentation (OPT-05: bounded to prevent memory leak, CFG-01: configurable)
        from src.utils.config_loader import get_metrics_config
        metrics_config = get_metrics_config()
        timing_maxlen = metrics_config["metrics"]["storage"]["batch_optimizer"]["timing_metrics_maxlen"]

        self._timing_metrics = {
            "prepare_batches_ms": deque(maxlen=timing_maxlen),  # Bounded by config
            "process_batch_ms": deque(maxlen=timing_maxlen),  # Bounded by config
            "oom_recovery_ms": deque(maxlen=timing_maxlen),  # Bounded by config
            "batch_size_adjustments_ms": deque(maxlen=timing_maxlen),  # Bounded by config
        }

        # Initialize resource limits
        self._initialize_resource_limits()

        logger.info(
            f"Batch optimizer initialized: "
            f"batch_size={self._current_batch_size}, "
            f"workers={self.config.num_workers}"
        )

    def _initialize_resource_limits(self):
        """Initialize resource limits based on available hardware."""
        # Auto-detect CPU workers
        if self.config.num_workers is None:
            self.config.num_workers = min(
                os.cpu_count() or 4,
                8  # Cap at 8 workers
            )

        # Auto-detect memory limits
        if self.config.target_memory_mb is None:
            try:
                import psutil
                available_mb = psutil.virtual_memory().available / 1024 / 1024
                # Use 70% of available memory
                self.config.target_memory_mb = int(available_mb * 0.7)
            except ImportError:
                # Default to 4GB if psutil not available
                self.config.target_memory_mb = 4096

        # Auto-detect GPU memory
        if self.config.target_gpu_memory_mb is None:
            try:
                import torch
                if torch.cuda.is_available():
                    device = torch.cuda.current_device()
                    total_mb = torch.cuda.get_device_properties(device).total_memory / 1024 / 1024
                    # Use 80% of GPU memory (leave room for CUDA overhead)
                    self.config.target_gpu_memory_mb = int(total_mb * 0.8)
                else:
                    self.config.target_gpu_memory_mb = 0
            except ImportError:
                self.config.target_gpu_memory_mb = 0

        logger.info(
            f"Resource limits: "
            f"RAM={self.config.target_memory_mb}MB, "
            f"VRAM={self.config.target_gpu_memory_mb}MB, "
            f"Workers={self.config.num_workers}"
        )

    def get_optimal_batch_size(self) -> int:
        """
        Get current optimal batch size.

        Returns:
            Recommended batch size
        """
        with self._lock:
            return self._current_batch_size

    def prepare_batches(
        self,
        items: List[str],
        sort_by_length: Optional[bool] = None,
    ) -> List[List[str]]:
        """
        Prepare items into optimized batches.

        Args:
            items: List of items to batch (e.g., text segments)
            sort_by_length: Whether to sort by length (overrides config)

        Returns:
            List of batches
        """
        # BM-08: Timing instrumentation
        start_time = time.perf_counter()

        should_sort = (
            sort_by_length
            if sort_by_length is not None
            else self.config.sort_by_length
        )

        # Sort by length if enabled
        if should_sort:
            items = sorted(items, key=len)
            logger.debug(f"Sorted {len(items)} items by length")

        # Create batches
        batch_size = self.get_optimal_batch_size()
        batches = []

        for i in range(0, len(items), batch_size):
            batch = items[i : i + batch_size]
            batches.append(batch)

        # BM-08: Record timing
        duration_ms = (time.perf_counter() - start_time) * 1000
        with self._lock:
            self._timing_metrics["prepare_batches_ms"].append(duration_ms)

        if duration_ms > 100:
            logger.warning(f"Slow batch preparation: {duration_ms:.1f}ms for {len(items)} items")

        logger.info(
            f"Created {len(batches)} batches "
            f"(avg size: {len(items) / len(batches) if batches else 0:.1f})"
        )

        return batches

    def process_batch_with_monitoring(
        self,
        batch: List[str],
        process_func,
        *args,
        **kwargs
    ) -> Tuple[any, bool]:
        """
        Process a batch with resource monitoring and error handling.

        Args:
            batch: Batch of items to process
            process_func: Function to call with batch
            *args: Additional args for process_func
            **kwargs: Additional kwargs for process_func

        Returns:
            Tuple of (result, success)
        """
        start_time = time.perf_counter()

        try:
            # Monitor memory before
            mem_before = self._get_current_memory_mb()
            gpu_mem_before = self._get_current_gpu_memory_mb()

            # Process batch
            result = process_func(batch, *args, **kwargs)

            # Monitor memory after
            mem_after = self._get_current_memory_mb()
            gpu_mem_after = self._get_current_gpu_memory_mb()

            # Update peak usage
            with self._lock:
                self._peak_memory_mb = max(self._peak_memory_mb, mem_after)
                self._peak_gpu_memory_mb = max(self._peak_gpu_memory_mb, gpu_mem_after)

                # Update stats
                self.stats.batches_processed += 1
                self.stats.total_segments += len(batch)

            # Check if we should adjust batch size
            if self.config.dynamic_batch_size:
                self._adjust_batch_size(
                    mem_before, mem_after,
                    gpu_mem_before, gpu_mem_after,
                    len(batch)
                )

            # BM-08: Record timing
            duration_ms = (time.perf_counter() - start_time) * 1000
            with self._lock:
                self._timing_metrics["process_batch_ms"].append(duration_ms)

            if duration_ms > 1000:
                logger.warning(f"Slow batch processing: {duration_ms:.1f}ms for {len(batch)} items")

            logger.debug(
                f"Batch processed: {len(batch)} items in {duration_ms/1000:.2f}s "
                f"(mem: {mem_after:.0f}MB, gpu: {gpu_mem_after:.0f}MB)"
            )

            return result, True

        except RuntimeError as e:
            # Check if OOM error
            if "out of memory" in str(e).lower():
                logger.warning(f"OOM detected: {e}")

                if self.config.oom_retry_enabled:
                    return self._handle_oom(batch, process_func, *args, **kwargs)
                else:
                    raise

            else:
                raise

    def _handle_oom(
        self,
        batch: List[str],
        process_func,
        *args,
        **kwargs
    ) -> Tuple[any, bool]:
        """
        Handle out-of-memory error by reducing batch size and retrying.

        Args:
            batch: Original batch that caused OOM
            process_func: Processing function
            *args: Additional args
            **kwargs: Additional kwargs

        Returns:
            Tuple of (result, success)
        """
        # BM-08: Timing instrumentation
        start_time = time.perf_counter()

        with self._lock:
            self.stats.oom_events += 1

            # Reduce batch size
            old_size = self._current_batch_size
            self._current_batch_size = max(
                self.config.min_batch_size,
                int(self._current_batch_size * self.config.oom_reduction_factor)
            )

            logger.warning(
                f"OOM: Reduced batch size {old_size} -> {self._current_batch_size}"
            )

        # Clear GPU cache if available
        try:
            import torch
            if torch.cuda.is_available():
                torch.cuda.empty_cache()
                logger.info("Cleared GPU cache")
        except ImportError:
            pass

        # Split batch and retry
        new_batch_size = self._current_batch_size
        sub_batches = [
            batch[i : i + new_batch_size]
            for i in range(0, len(batch), new_batch_size)
        ]

        logger.info(f"Retrying with {len(sub_batches)} smaller batches")

        results = []
        for sub_batch in sub_batches:
            try:
                result = process_func(sub_batch, *args, **kwargs)
                results.append(result)
            except RuntimeError as e:
                if "out of memory" in str(e).lower():
                    # Still OOM even with smaller batch - fail
                    logger.error(f"OOM persists even with batch size {len(sub_batch)}")
                    raise
                else:
                    raise

        # BM-08: Record OOM recovery timing
        duration_ms = (time.perf_counter() - start_time) * 1000
        with self._lock:
            self._timing_metrics["oom_recovery_ms"].append(duration_ms)

        logger.info(f"OOM recovery completed in {duration_ms:.1f}ms")

        # Combine results (assuming they're lists)
        if results and isinstance(results[0], list):
            combined = []
            for r in results:
                combined.extend(r)
            return combined, True
        else:
            return results, True

    def _adjust_batch_size(
        self,
        mem_before: float,
        mem_after: float,
        gpu_mem_before: float,
        gpu_mem_after: float,
        batch_size: int,
    ):
        """
        Dynamically adjust batch size based on memory usage.

        Args:
            mem_before: Memory before batch (MB)
            mem_after: Memory after batch (MB)
            gpu_mem_before: GPU memory before batch (MB)
            gpu_mem_after: GPU memory after batch (MB)
            batch_size: Current batch size
        """
        # BM-08: Timing instrumentation
        start_time = time.perf_counter()

        mem_used = mem_after - mem_before
        gpu_mem_used = gpu_mem_after - gpu_mem_before

        # Check if we're close to limits
        if self.config.target_memory_mb:
            mem_util = mem_after / self.config.target_memory_mb
        else:
            mem_util = 0

        if self.config.target_gpu_memory_mb:
            gpu_util = gpu_mem_after / self.config.target_gpu_memory_mb
        else:
            gpu_util = 0

        max_util = max(mem_util, gpu_util)

        with self._lock:
            old_size = self._current_batch_size

            # If using > 90% of resources, reduce batch size
            if max_util > 0.9:
                self._current_batch_size = max(
                    self.config.min_batch_size,
                    int(self._current_batch_size * 0.8)
                )

            # If using < 60% of resources, increase batch size
            elif max_util < 0.6:
                self._current_batch_size = min(
                    self.config.max_batch_size,
                    int(self._current_batch_size * 1.2)
                )

            if self._current_batch_size != old_size:
                self.stats.batch_size_adjustments += 1

                # BM-08: Record adjustment timing
                duration_ms = (time.perf_counter() - start_time) * 1000
                self._timing_metrics["batch_size_adjustments_ms"].append(duration_ms)

                logger.info(
                    f"Adjusted batch size: {old_size} -> {self._current_batch_size} "
                    f"(mem: {mem_util:.0%}, gpu: {gpu_util:.0%})"
                )

    def _get_current_memory_mb(self) -> float:
        """Get current process memory usage in MB."""
        try:
            import psutil
            import os
            process = psutil.Process(os.getpid())
            return process.memory_info().rss / 1024 / 1024
        except ImportError:
            return 0.0

    def _get_current_gpu_memory_mb(self) -> float:
        """Get current GPU memory usage in MB."""
        try:
            import torch
            if torch.cuda.is_available():
                return torch.cuda.memory_allocated() / 1024 / 1024
            else:
                return 0.0
        except ImportError:
            return 0.0

    def get_stats(self) -> BatchStats:
        """
        Get batch processing statistics.

        Returns:
            BatchStats object
        """
        with self._lock:
            stats = BatchStats(
                total_segments=self.stats.total_segments,
                batches_processed=self.stats.batches_processed,
                avg_batch_size=(
                    self.stats.total_segments / self.stats.batches_processed
                    if self.stats.batches_processed > 0 else 0
                ),
                peak_memory_mb=self._peak_memory_mb,
                peak_gpu_memory_mb=self._peak_gpu_memory_mb,
                total_duration_seconds=self.stats.total_duration_seconds,
                avg_throughput_segments_per_sec=(
                    self.stats.total_segments / self.stats.total_duration_seconds
                    if self.stats.total_duration_seconds > 0 else 0
                ),
                oom_events=self.stats.oom_events,
                batch_size_adjustments=self.stats.batch_size_adjustments,
            )

        return stats

    def get_timing_metrics(self) -> Dict:
        """
        Get timing metrics for performance monitoring (BM-08).

        Returns:
            Dictionary with timing statistics for batch operations
        """
        with self._lock:
            return {
                "prepare_batches": calc_stats(self._timing_metrics["prepare_batches_ms"]),
                "process_batch": calc_stats(self._timing_metrics["process_batch_ms"]),
                "oom_recovery": calc_stats(self._timing_metrics["oom_recovery_ms"]),
                "batch_size_adjustments": calc_stats(self._timing_metrics["batch_size_adjustments_ms"]),
            }


def create_batch_optimizer(
    initial_batch_size: int = 32,
    enable_optimization: bool = True,
    **kwargs
) -> BatchOptimizer:
    """
    Factory function to create batch optimizer.

    Args:
        initial_batch_size: Starting batch size
        enable_optimization: Whether to enable dynamic optimization
        **kwargs: Additional config parameters

    Returns:
        Configured batch optimizer
    """
    config = BatchConfig(
        initial_batch_size=initial_batch_size,
        dynamic_batch_size=enable_optimization,
        sort_by_length=enable_optimization,
        enable_prefetch=enable_optimization,
        **kwargs
    )

    return BatchOptimizer(config)


# CLI for testing
if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser(description="Test batch optimizer")
    parser.add_argument("--batch-size", type=int, default=32, help="Initial batch size")
    parser.add_argument("--items", type=int, default=1000, help="Number of items")

    args = parser.parse_args()

    # Create optimizer
    optimizer = create_batch_optimizer(initial_batch_size=args.batch_size)

    # Create test items
    items = [f"Item {i}" * (i % 10 + 1) for i in range(args.items)]

    print(f"Testing with {len(items)} items...")

    # Prepare batches
    batches = optimizer.prepare_batches(items)

    print(f"Created {len(batches)} batches")
    print(f"Optimal batch size: {optimizer.get_optimal_batch_size()}")

    # Get stats
    stats = optimizer.get_stats()
    print(f"\nStats:")
    print(f"  Batches: {stats.batches_processed}")
    print(f"  Avg batch size: {stats.avg_batch_size:.1f}")
    print(f"  Peak memory: {stats.peak_memory_mb:.1f} MB")
