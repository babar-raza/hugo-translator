"""
Production-grade Progress Tracking and Metrics for Translation Pipeline.

Provides real-time progress updates with:
- ETA calculation using exponential moving average (EMA)
- Rolling throughput (segments/sec, files/min)
- Cache hit rate tracking
- Periodic console and file output
- Two-terminal support (metrics-only mode)
"""

import json
import logging
import os
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from collections import deque
from typing import Any, Callable, Deque, Dict, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProgressSnapshot:
    """Immutable snapshot of current progress state."""

    # Timing
    timestamp: float
    start_time: float
    elapsed_s: float
    eta_s: Optional[float] = None

    # Files
    files_total: int = 0
    files_done: int = 0
    files_failed: int = 0
    files_skipped: int = 0
    current_file: str = ""

    # Segments
    segments_total: int = 0
    segments_done: int = 0
    segments_failed: int = 0

    # Batches
    batches_total: int = 0
    batches_done: int = 0
    current_batch_size: int = 0

    # Performance
    segments_per_sec_rolling: float = 0.0
    segments_per_sec_lifetime: float = 0.0
    files_per_min: float = 0.0
    avg_segment_ms: float = 0.0
    avg_batch_s: float = 0.0

    # Cache
    cache_hits: int = 0
    cache_misses: int = 0
    cache_hit_rate: float = 0.0
    l1_hits: int = 0
    l2_hits: int = 0
    l3_hits: int = 0

    # Translation
    model_name: str = ""
    device: str = ""
    tokens_in: int = 0
    tokens_out: int = 0
    retries: int = 0

    # Errors
    error_count: int = 0
    last_error: str = ""
    last_failed_file: str = ""
    errors_by_type: Dict[str, int] = field(default_factory=dict)

    # Progress
    percent_complete_files: float = 0.0
    percent_complete_segments: float = 0.0

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for JSON serialization."""
        return {
            "timestamp": self.timestamp,
            "timestamp_iso": datetime.fromtimestamp(self.timestamp).isoformat(),
            "start_time": self.start_time,
            "elapsed_s": round(self.elapsed_s, 2),
            "eta_s": round(self.eta_s, 2) if self.eta_s is not None else None,
            "eta_formatted": self._format_eta(),
            "overall": {
                "percent_complete_files": round(self.percent_complete_files, 1),
                "percent_complete_segments": round(self.percent_complete_segments, 1),
            },
            "files": {
                "total": self.files_total,
                "done": self.files_done,
                "failed": self.files_failed,
                "skipped": self.files_skipped,
                "current": self.current_file,
            },
            "segments": {
                "total": self.segments_total,
                "done": self.segments_done,
                "failed": self.segments_failed,
            },
            "batches": {
                "total": self.batches_total,
                "done": self.batches_done,
                "current_size": self.current_batch_size,
            },
            "performance": {
                "segments_per_sec_rolling": round(self.segments_per_sec_rolling, 2),
                "segments_per_sec_lifetime": round(self.segments_per_sec_lifetime, 2),
                "files_per_min": round(self.files_per_min, 2),
                "avg_segment_ms": round(self.avg_segment_ms, 2),
                "avg_batch_s": round(self.avg_batch_s, 3),
            },
            "cache": {
                "hits": self.cache_hits,
                "misses": self.cache_misses,
                "hit_rate": round(self.cache_hit_rate, 3),
                "l1_hits": self.l1_hits,
                "l2_hits": self.l2_hits,
                "l3_hits": self.l3_hits,
            },
            "translation": {
                "model": self.model_name,
                "device": self.device,
                "tokens_in": self.tokens_in,
                "tokens_out": self.tokens_out,
                "retries": self.retries,
            },
            "errors": {
                "count": self.error_count,
                "last_error": self.last_error,
                "last_failed_file": self.last_failed_file,
                "by_type": self.errors_by_type,
            },
        }

    def _format_eta(self) -> str:
        """Format ETA as human-readable string."""
        if self.eta_s is None or self.eta_s < 0:
            return "calculating..."
        if self.eta_s == 0:
            return "done"

        hours, remainder = divmod(int(self.eta_s), 3600)
        minutes, seconds = divmod(remainder, 60)

        if hours > 0:
            return f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            return f"{minutes}m {seconds}s"
        else:
            return f"{seconds}s"

    def to_compact_line(self) -> str:
        """Format as compact single-line metrics string."""
        eta_str = self._format_eta()
        return (
            f"[{self.percent_complete_segments:5.1f}%]  "
            f"Files: {self.files_done:,}/{self.files_total:,}  "
            f"Segments: {self.segments_done:,}/{self.segments_total:,}  "
            f"Rate: {self.segments_per_sec_rolling:.1f}/s  "
            f"Cache: {self.cache_hit_rate*100:.0f}%  "
            f"ETA: {eta_str}"
            f"{f'  Errors: {self.error_count:,}' if self.error_count > 0 else ''}"
        )


class EMACalculator:
    """
    Exponential Moving Average calculator for throughput smoothing.

    Uses EMA for more responsive throughput estimates that
    give more weight to recent observations.
    """

    def __init__(self, alpha: float = 0.3, window_size: int = 10):
        """
        Initialize EMA calculator.

        Args:
            alpha: Smoothing factor (0-1). Higher = more weight on recent values.
            window_size: Number of samples to keep for moving average fallback.
        """
        self.alpha = alpha
        self.window_size = window_size
        self._ema_value: Optional[float] = None
        self._samples: Deque[float] = deque(maxlen=window_size)
        self._lock = threading.Lock()

    def add_sample(self, value: float) -> float:
        """
        Add a new sample and return updated EMA.

        Args:
            value: New sample value

        Returns:
            Current EMA value
        """
        with self._lock:
            self._samples.append(value)  # deque auto-evicts when maxlen exceeded

            if self._ema_value is None:
                self._ema_value = value
            else:
                self._ema_value = self.alpha * value + (1 - self.alpha) * self._ema_value

            return self._ema_value

    def get_value(self) -> float:
        """Get current EMA value."""
        with self._lock:
            return self._ema_value or 0.0

    def get_moving_average(self) -> float:
        """Get simple moving average of recent samples."""
        with self._lock:
            if not self._samples:
                return 0.0
            return sum(self._samples) / len(self._samples)

    def reset(self) -> None:
        """Reset calculator state."""
        with self._lock:
            self._ema_value = None
            self._samples.clear()


class ProgressTracker:
    """
    Production-grade progress tracker with real-time metrics.

    Features:
    - File, segment, batch progress tracking
    - ETA calculation with rolling throughput
    - Periodic console/file output
    - Thread-safe concurrent updates
    - Two-terminal support (metrics-only mode)
    """

    def __init__(
        self,
        update_interval: float = 2.0,
        metrics_file: Optional[Path] = None,
        metrics_only: bool = False,
        show_progress: bool = True,
        ema_alpha: float = 0.3,
        milestone_callback: Optional[Callable[[ProgressSnapshot], None]] = None,
    ):
        """
        Initialize progress tracker.

        Args:
            update_interval: Seconds between periodic updates
            metrics_file: Path for metrics output (creates .json + .ndjson files)
            metrics_only: If True, suppress normal logs, emit only metrics
            show_progress: If True, show progress updates
            ema_alpha: EMA smoothing factor for throughput
            milestone_callback: Optional callback for milestone events
        """
        self.update_interval = update_interval
        self.metrics_file = Path(metrics_file) if metrics_file else None
        self.metrics_only = metrics_only
        self.show_progress = show_progress
        self.milestone_callback = milestone_callback

        # Timing
        self._start_time: float = 0.0
        self._last_update_time: float = 0.0
        self._last_segment_time: float = 0.0
        self._last_file_time: float = 0.0
        self._last_batch_time: float = 0.0  # OBS-01: Initialize properly

        # Counters (thread-safe access)
        self._lock = threading.RLock()
        self._files_total = 0
        self._files_done = 0
        self._files_failed = 0
        self._files_skipped = 0
        self._current_file = ""

        self._segments_total = 0
        self._segments_done = 0
        self._segments_failed = 0

        self._batches_total = 0
        self._batches_done = 0
        self._current_batch_size = 0

        # Cache stats
        self._cache_hits = 0
        self._cache_misses = 0
        self._l1_hits = 0
        self._l2_hits = 0
        self._l3_hits = 0

        # Translation stats
        self._model_name = ""
        self._device = ""
        self._tokens_in = 0
        self._tokens_out = 0
        self._retries = 0

        # Errors
        self._error_count = 0
        self._last_error = ""
        self._last_failed_file = ""
        self._errors_by_type: Dict[str, int] = {}

        # Timing accumulators for averages (OBS-03: use deque for O(1) eviction)
        self._segment_times: Deque[float] = deque(maxlen=100)
        self._batch_times: Deque[float] = deque(maxlen=50)

        # EMA calculators
        self._segment_rate_ema = EMACalculator(alpha=ema_alpha)
        self._file_rate_ema = EMACalculator(alpha=ema_alpha)

        # Background update thread
        self._update_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # NDJSON stream file handle
        self._ndjson_file: Optional[Any] = None

    def start(self, files_total: int = 0) -> None:
        """
        Start progress tracking.

        Args:
            files_total: Total number of files to process
        """
        with self._lock:
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._files_total = files_total
            self._running = True

        # Open NDJSON stream if metrics file specified
        if self.metrics_file:
            self._setup_metrics_files()

        # Start background update thread
        if self.show_progress and self.update_interval > 0:
            self._stop_event.clear()
            self._update_thread = threading.Thread(
                target=self._update_loop,
                daemon=True,
                name="ProgressTracker"
            )
            self._update_thread.start()

        logger.debug("Progress tracking started")

    def stop(self) -> ProgressSnapshot:
        """
        Stop progress tracking and return final snapshot.

        Returns:
            Final progress snapshot
        """
        self._running = False
        self._stop_event.set()

        if self._update_thread and self._update_thread.is_alive():
            self._update_thread.join(timeout=2.0)

        # Final snapshot
        snapshot = self.get_snapshot()

        # Write final metrics
        if self.metrics_file:
            self._write_snapshot(snapshot)
            self._close_metrics_files()

        # Log final summary
        if not self.metrics_only:
            self._log_final_summary(snapshot)

        return snapshot

    def get_snapshot(self) -> ProgressSnapshot:
        """
        Get current progress snapshot (thread-safe).

        Returns:
            Immutable snapshot of current state
        """
        with self._lock:
            now = time.time()
            elapsed = now - self._start_time if self._start_time > 0 else 0

            # Calculate percentages
            pct_files = (self._files_done / self._files_total * 100) if self._files_total > 0 else 0
            pct_segs = (self._segments_done / self._segments_total * 100) if self._segments_total > 0 else 0

            # Calculate lifetime throughput
            lifetime_seg_rate = self._segments_done / elapsed if elapsed > 0 else 0
            lifetime_file_rate = (self._files_done / elapsed * 60) if elapsed > 0 else 0

            # Calculate cache hit rate
            total_lookups = self._cache_hits + self._cache_misses
            hit_rate = self._cache_hits / total_lookups if total_lookups > 0 else 0

            # Calculate averages
            avg_seg_ms = 0.0
            if self._segment_times:
                avg_seg_ms = (sum(self._segment_times) / len(self._segment_times)) * 1000

            avg_batch_s = 0.0
            if self._batch_times:
                avg_batch_s = sum(self._batch_times) / len(self._batch_times)

            # Calculate ETA
            eta_s = self._calculate_eta()

            return ProgressSnapshot(
                timestamp=now,
                start_time=self._start_time,
                elapsed_s=elapsed,
                eta_s=eta_s,
                files_total=self._files_total,
                files_done=self._files_done,
                files_failed=self._files_failed,
                files_skipped=self._files_skipped,
                current_file=self._current_file,
                segments_total=self._segments_total,
                segments_done=self._segments_done,
                segments_failed=self._segments_failed,
                batches_total=self._batches_total,
                batches_done=self._batches_done,
                current_batch_size=self._current_batch_size,
                segments_per_sec_rolling=self._segment_rate_ema.get_value(),
                segments_per_sec_lifetime=lifetime_seg_rate,
                files_per_min=lifetime_file_rate,
                avg_segment_ms=avg_seg_ms,
                avg_batch_s=avg_batch_s,
                cache_hits=self._cache_hits,
                cache_misses=self._cache_misses,
                cache_hit_rate=hit_rate,
                l1_hits=self._l1_hits,
                l2_hits=self._l2_hits,
                l3_hits=self._l3_hits,
                model_name=self._model_name,
                device=self._device,
                tokens_in=self._tokens_in,
                tokens_out=self._tokens_out,
                retries=self._retries,
                error_count=self._error_count,
                last_error=self._last_error,
                last_failed_file=self._last_failed_file,
                errors_by_type=dict(self._errors_by_type),
                percent_complete_files=pct_files,
                percent_complete_segments=pct_segs,
            )

    def _calculate_eta(self) -> Optional[float]:
        """Calculate estimated time remaining based on rolling throughput."""
        if self._segments_total == 0:
            return None

        remaining_segments = self._segments_total - self._segments_done
        if remaining_segments <= 0:
            return 0.0

        rate = self._segment_rate_ema.get_value()
        if rate <= 0:
            # Fallback to lifetime rate
            elapsed = time.time() - self._start_time
            rate = self._segments_done / elapsed if elapsed > 0 and self._segments_done > 0 else 0

        if rate <= 0:
            return None

        return remaining_segments / rate

    # === Update methods (called by translation engine) ===

    def set_totals(self, files: int = 0, segments: int = 0, batches: int = 0) -> None:
        """Set total counts for progress calculation."""
        with self._lock:
            if files > 0:
                self._files_total = files
            if segments > 0:
                self._segments_total = segments
            if batches > 0:
                self._batches_total = batches

    def add_segments(self, count: int) -> None:
        """Add to total segment count (for progressive discovery)."""
        with self._lock:
            self._segments_total += count

    def add_batches(self, count: int) -> None:
        """Add to total batch count (for progressive discovery across languages)."""
        with self._lock:
            self._batches_total += count

    def file_started(self, file_path: str, segment_count: int = 0) -> None:
        """Mark file processing started."""
        with self._lock:
            self._current_file = os.path.basename(file_path)
            if segment_count > 0:
                self._segments_total += segment_count
            self._last_file_time = time.time()

        if not self.metrics_only:
            logger.debug(f"Processing: {self._current_file}")

    def file_completed(self, success: bool = True) -> None:
        """Mark current file completed."""
        now = time.time()
        with self._lock:
            if success:
                self._files_done += 1
            else:
                self._files_failed += 1
                self._last_failed_file = self._current_file

            # Update file rate
            if self._last_file_time > 0:
                duration = now - self._last_file_time
                rate = 60.0 / duration if duration > 0 else 0  # files per minute
                self._file_rate_ema.add_sample(rate)

        # Milestone callback
        if self.milestone_callback:
            self.milestone_callback(self.get_snapshot())

    def file_skipped(self) -> None:
        """Mark file as skipped (already translated, etc.)."""
        with self._lock:
            self._files_skipped += 1

    def segments_completed(self, count: int, duration_s: float = 0.0) -> None:
        """Mark segments as completed."""
        with self._lock:
            self._segments_done += count

            if duration_s > 0 and count > 0:
                per_segment = duration_s / count
                self._segment_times.append(per_segment)  # deque auto-evicts

                # Update rate EMA
                rate = count / duration_s if duration_s > 0 else 0
                self._segment_rate_ema.add_sample(rate)

    def segment_failed(self) -> None:
        """Mark a segment as failed."""
        with self._lock:
            self._segments_failed += 1

    def batch_started(self, batch_size: int) -> None:
        """Mark batch processing started."""
        with self._lock:
            self._current_batch_size = batch_size
            self._last_batch_time = time.time()

    def batch_completed(self, batch_size: int) -> None:
        """Mark batch completed."""
        now = time.time()
        with self._lock:
            self._batches_done += 1

            if self._last_batch_time > 0:  # OBS-01: removed hasattr() check
                duration = now - self._last_batch_time
                self._batch_times.append(duration)  # OBS-03: deque auto-evicts

    def cache_hit(self, layer: str = "l1") -> None:
        """Record a cache hit."""
        with self._lock:
            self._cache_hits += 1
            if layer == "l1":
                self._l1_hits += 1
            elif layer == "l2":
                self._l2_hits += 1
            elif layer == "l3":
                self._l3_hits += 1

    def cache_miss(self) -> None:
        """Record a cache miss."""
        with self._lock:
            self._cache_misses += 1

    def set_model(self, model_name: str, device: str = "") -> None:
        """Set translation model info."""
        with self._lock:
            self._model_name = model_name
            self._device = device

    def add_tokens(self, tokens_in: int = 0, tokens_out: int = 0) -> None:
        """Add token counts."""
        with self._lock:
            self._tokens_in += tokens_in
            self._tokens_out += tokens_out

    def add_retry(self) -> None:
        """Record a retry attempt."""
        with self._lock:
            self._retries += 1

    def record_error(self, error_type: str, message: str, file_path: str = "") -> None:
        """Record an error."""
        with self._lock:
            self._error_count += 1
            self._last_error = message[:200] if message else ""
            if file_path:
                self._last_failed_file = os.path.basename(file_path)

            # SR-02: Log ERROR for every counted error (ensures observability)
            error_context = f"file={file_path}" if file_path else "no file context"
            logger.error(
                f"Error #{self._error_count} recorded: {error_type} - {message[:100]} ({error_context})"
            )

            # Track by type
            self._errors_by_type[error_type] = self._errors_by_type.get(error_type, 0) + 1

    # === Background update ===

    def _update_loop(self) -> None:
        """Background thread for periodic updates."""
        while not self._stop_event.wait(self.update_interval):
            if not self._running:
                break

            try:
                snapshot = self.get_snapshot()
                self._emit_update(snapshot)
            except Exception as e:
                logger.warning(f"Progress update error: {e}")

    def _emit_update(self, snapshot: ProgressSnapshot) -> None:
        """Emit a progress update to console and/or file."""
        # Console output
        if self.show_progress:
            if self.metrics_only:
                # Metrics-only mode: compact single line
                print(snapshot.to_compact_line(), flush=True)
            else:
                # Normal mode: structured log
                self._log_progress(snapshot)

        # File output
        if self.metrics_file:
            self._write_snapshot(snapshot)

    def _log_progress(self, snapshot: ProgressSnapshot) -> None:
        """Log progress to standard logging."""
        eta_str = snapshot._format_eta()
        logger.info(
            f"[{snapshot.percent_complete_segments:5.1f}%] "
            f"Files: {snapshot.files_done:,}/{snapshot.files_total:,}  "
            f"Segments: {snapshot.segments_done:,}/{snapshot.segments_total:,}  "
            f"Rate: {snapshot.segments_per_sec_rolling:.1f}/s  "
            f"Cache: {snapshot.cache_hit_rate*100:.0f}%  "
            f"ETA: {eta_str}"
        )

    def _validate_metrics_consistency(self, snapshot: ProgressSnapshot) -> None:
        """Validate metrics for internal contradictions (SR-04)."""
        warnings = []

        # Rule 1: No failures → no errors (most critical check)
        if snapshot.files_failed == 0 and snapshot.error_count > 0:
            warnings.append(
                f"CONTRADICTION: 0 failed files but {snapshot.error_count} errors counted"
            )

        # Rule 2: Errors should not vastly exceed failed files
        if snapshot.error_count > snapshot.files_failed * 3:  # Allow some multi-error files
            warnings.append(
                f"ANOMALY: {snapshot.error_count} errors but only {snapshot.files_failed} failures "
                f"(ratio: {snapshot.error_count / max(1, snapshot.files_failed):.1f}:1)"
            )

        # Rule 3: Cache ops should equal segments processed (done + failed)
        # SR-03: cache_hits + cache_misses = segments_done + segments_failed
        cache_total = snapshot.cache_hits + snapshot.cache_misses
        segments_total = snapshot.segments_done + snapshot.segments_failed
        segment_gap = abs(cache_total - segments_total)
        if segment_gap > 1000 and cache_total > 0:  # 1000 segment tolerance
            warnings.append(
                f"SEGMENT GAP: {cache_total} cache ops vs {segments_total} segments "
                f"(done: {snapshot.segments_done}, failed: {snapshot.segments_failed}, gap: {segment_gap})"
            )

        # Log all warnings
        for warning in warnings:
            logger.warning(f"METRICS VALIDATION: {warning}")

    def _format_box_line(self, label: str, value: str, width: int = 58) -> str:
        """Format a line within a box with proper padding."""
        content = f"  {label:<12} {value}"
        padding = width - len(content)
        return f"│{content}{' ' * padding}│"

    def _log_final_summary(self, snapshot: ProgressSnapshot) -> None:
        """Log final summary when tracking stops."""
        # SR-04: Validate metrics consistency before logging
        self._validate_metrics_consistency(snapshot)

        # Format duration
        hours, remainder = divmod(int(snapshot.elapsed_s), 3600)
        minutes, seconds = divmod(remainder, 60)
        if hours > 0:
            duration_str = f"{hours}h {minutes}m {seconds}s"
        elif minutes > 0:
            duration_str = f"{minutes}m {seconds}s"
        else:
            duration_str = f"{seconds}s"

        # Build summary box
        box_width = 58
        logger.info("┌" + "─" * box_width + "┐")
        logger.info("│" + " TRANSLATION COMPLETE ".center(box_width) + "│")
        logger.info("├" + "─" * box_width + "┤")

        logger.info(self._format_box_line("Duration:", duration_str, box_width))
        logger.info(self._format_box_line("Files:",
            f"{snapshot.files_done:,} completed, {snapshot.files_failed:,} failed, {snapshot.files_skipped:,} skipped",
            box_width))
        logger.info(self._format_box_line("Segments:",
            f"{snapshot.segments_done:,}/{snapshot.segments_total:,} ({snapshot.percent_complete_segments:.1f}%)",
            box_width))
        logger.info(self._format_box_line("Throughput:",
            f"{snapshot.segments_per_sec_lifetime:.1f} seg/s, {snapshot.files_per_min:.1f} files/min",
            box_width))
        logger.info(self._format_box_line("Cache:",
            f"{snapshot.cache_hit_rate*100:.1f}% hit rate ({snapshot.cache_hits:,} hits, {snapshot.cache_misses:,} misses)",
            box_width))

        if snapshot.tokens_in > 0:
            logger.info(self._format_box_line("Tokens:",
                f"{snapshot.tokens_in:,} in, {snapshot.tokens_out:,} out",
                box_width))

        if snapshot.error_count > 0:
            logger.warning(self._format_box_line("Errors:",
                f"{snapshot.error_count:,} total",
                box_width))

        logger.info("└" + "─" * box_width + "┘")

    # === Metrics file output ===

    def _setup_metrics_files(self) -> None:
        """Set up metrics output files."""
        if not self.metrics_file:
            return

        # Ensure parent directory exists
        self.metrics_file.parent.mkdir(parents=True, exist_ok=True)

        # NDJSON stream file (append mode)
        ndjson_path = self.metrics_file.with_suffix('.ndjson')
        try:
            self._ndjson_file = open(ndjson_path, 'a', encoding='utf-8')
            logger.debug(f"Opened NDJSON stream: {ndjson_path}")
        except Exception as e:
            logger.warning(f"Failed to open NDJSON file: {e}")

    def _write_snapshot(self, snapshot: ProgressSnapshot) -> None:
        """Write snapshot to metrics files."""
        if not self.metrics_file:
            return

        data = snapshot.to_dict()

        # Write snapshot JSON (overwrite)
        json_path = self.metrics_file.with_name(
            self.metrics_file.stem + '_current.json'
        )
        try:
            with open(json_path, 'w', encoding='utf-8') as f:
                json.dump(data, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to write snapshot JSON: {e}")

        # Append to NDJSON stream
        if self._ndjson_file:
            try:
                self._ndjson_file.write(json.dumps(data) + '\n')
                self._ndjson_file.flush()
            except Exception as e:
                logger.warning(f"Failed to write NDJSON: {e}")

    def _close_metrics_files(self) -> None:
        """Close metrics output files."""
        if self._ndjson_file:
            try:
                self._ndjson_file.close()
            except Exception:
                pass
            self._ndjson_file = None


# Global progress tracker instance
_global_tracker: Optional[ProgressTracker] = None


def get_progress_tracker() -> Optional[ProgressTracker]:
    """Get the global progress tracker instance."""
    return _global_tracker


def init_progress_tracker(
    update_interval: float = 2.0,
    metrics_file: Optional[Path] = None,
    metrics_only: bool = False,
    show_progress: bool = True,
) -> ProgressTracker:
    """
    Initialize global progress tracker.

    Args:
        update_interval: Seconds between periodic updates
        metrics_file: Path for metrics output
        metrics_only: If True, suppress normal logs
        show_progress: If True, show progress updates

    Returns:
        Initialized progress tracker
    """
    global _global_tracker
    _global_tracker = ProgressTracker(
        update_interval=update_interval,
        metrics_file=metrics_file,
        metrics_only=metrics_only,
        show_progress=show_progress,
    )
    return _global_tracker


def stop_progress_tracker() -> Optional[ProgressSnapshot]:
    """Stop and clean up global progress tracker."""
    global _global_tracker
    if _global_tracker:
        snapshot = _global_tracker.stop()
        _global_tracker = None
        return snapshot
    return None
