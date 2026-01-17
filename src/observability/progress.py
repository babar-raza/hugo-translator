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
from typing import Any, Callable, Deque, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProgressSnapshot:
    """Immutable snapshot of current progress state."""

    # Timing
    timestamp: float
    start_time: float
    elapsed_s: float
    eta_s: Optional[float] = None

    # ETA uncertainty tracking
    eta_confidence: str = "calculating"  # "high", "medium", "low"
    rate_volatility: float = 0.0  # Coefficient of variation

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

    # Token counting method tracking
    token_count_method: str = "estimated"  # "estimated" or "actual"

    # Errors
    error_count: int = 0
    last_error: str = ""
    last_failed_file: str = ""
    errors_by_type: Dict[str, int] = field(default_factory=dict)

    # Language tracking (NEW)
    target_langs: List[str] = field(default_factory=list)
    completed_langs: List[str] = field(default_factory=list)
    remaining_langs: List[str] = field(default_factory=list)
    langs_translated_count: int = 0
    langs_skipped_count: int = 0

    # Skip reasons (NEW)
    skip_reasons: Dict[str, int] = field(default_factory=dict)  # {reason: count}

    # Batch stats loaded from file (NEW)
    batch_stats: Dict[str, Any] = field(default_factory=dict)

    # Progress
    percent_complete_files: float = 0.0
    percent_complete_segments: float = 0.0

    # NEW: Separate translated vs skipped tracking
    files_translated: int = 0  # Actually translated (excludes skipped)
    files_processed: int = 0   # Total processed (done + skipped + failed)

    # NEW: Current file segment tracking
    current_file_segments_total: int = 0
    current_file_segments_done: int = 0

    # NEW: For rate suppression logic
    sample_count: int = 0  # Number of segment timing samples collected

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
            "tracking": {
                "files_translated": self.files_translated,
                "files_processed": self.files_processed,
                "current_file_segments_total": self.current_file_segments_total,
                "current_file_segments_done": self.current_file_segments_done,
                "sample_count": self.sample_count,
            },
        }

    def _format_eta(self) -> str:
        """Format ETA with uncertainty indicator."""
        if self.eta_s is None or self.eta_s < 0:
            return "calculating..."
        if self.eta_s == 0:
            return "done"

        hours, remainder = divmod(int(self.eta_s), 3600)
        minutes, seconds = divmod(remainder, 60)

        # Format time
        if hours > 0:
            time_str = f"{hours}h {minutes}m"
        elif minutes > 0:
            time_str = f"{minutes}m {seconds}s"
        else:
            time_str = f"{seconds}s"

        # Add confidence indicator for low confidence
        if self.eta_confidence == "low" and self.rate_volatility > 0.3:
            time_str += " (varying)"

        return time_str

    def to_compact_line(self) -> str:
        """Format as compact single-line metrics string."""
        eta_str = self._format_eta()
        token_indicator = " (actual)" if self.token_count_method == "actual" else " (~est)"
        return (
            f"[{self.percent_complete_segments:5.1f}%]  "
            f"Files: {self.files_done:,}/{self.files_total:,}  "
            f"Segments: {self.segments_done:,}/{self.segments_total:,}  "
            f"Rate: {self.segments_per_sec_rolling:.1f}/s  "
            f"Tokens: {self.tokens_in:,}→{self.tokens_out:,}{token_indicator}  "
            f"Cache: {self.cache_hit_rate*100:.0f}%  "
            f"ETA: {eta_str}"
            f"{f'  Errors: {self.error_count:,}' if self.error_count > 0 else ''}"
        )


class AdaptiveEMACalculator:
    """
    Adaptive EMA with dynamic alpha based on rate volatility detection.

    Features:
    - Baseline alpha=0.3 (current behavior when stable)
    - Adaptive alpha=0.7 (responsive when volatile)
    - Uses coefficient of variation (CV) for change detection
    """

    def __init__(
        self,
        baseline_alpha: float = 0.3,
        adaptive_alpha: float = 0.7,
        window_size: int = 10,
        volatility_threshold: float = 0.30  # 30% CV triggers adaptation
    ):
        self.baseline_alpha = baseline_alpha
        self.adaptive_alpha = adaptive_alpha
        self.volatility_threshold = volatility_threshold
        self.window_size = window_size

        self._ema_value: Optional[float] = None
        self._samples: Deque[float] = deque(maxlen=window_size)
        self._current_alpha = baseline_alpha
        self._lock = threading.Lock()

    def add_sample(self, value: float) -> float:
        """Add sample and return updated EMA with adaptive alpha."""
        with self._lock:
            self._samples.append(value)

            # Detect volatility
            if len(self._samples) >= 3:
                cv = self._calculate_coefficient_of_variation()
                if cv > self.volatility_threshold:
                    # High volatility - use adaptive alpha (more responsive)
                    self._current_alpha = self.adaptive_alpha
                else:
                    # Low volatility - use baseline alpha (smoother)
                    self._current_alpha = self.baseline_alpha

            # Update EMA
            if self._ema_value is None:
                self._ema_value = value
            else:
                self._ema_value = (
                    self._current_alpha * value +
                    (1 - self._current_alpha) * self._ema_value
                )

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
            self._current_alpha = self.baseline_alpha

    def get_volatility_state(self) -> dict:
        """Return current volatility state for display."""
        with self._lock:
            cv = self._calculate_coefficient_of_variation()
            return {
                "cv": cv,
                "is_volatile": cv > self.volatility_threshold,
                "current_alpha": self._current_alpha,
                "sample_count": len(self._samples)
            }

    def _calculate_coefficient_of_variation(self) -> float:
        """
        Calculate coefficient of variation (CV = std_dev / mean).

        CV > 0.3 indicates high variability requiring faster adaptation.
        """
        if len(self._samples) < 2:
            return 0.0

        mean = sum(self._samples) / len(self._samples)
        if mean == 0:
            return 0.0

        variance = sum((x - mean) ** 2 for x in self._samples) / len(self._samples)
        std_dev = variance ** 0.5
        return std_dev / mean


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
        update_interval: float = 3.0,
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
        self._last_info_log_time: float = 0.0  # WS2: Track INFO-level progress logging
        self._info_log_interval_seconds: float = 5.0  # WS2: Log INFO progress every 5 seconds

        # Counters (thread-safe access)
        self._lock = threading.RLock()
        self._files_total = 0
        self._files_done = 0
        self._files_failed = 0
        self._files_skipped = 0
        self._current_file = ""
        self._files_translated = 0  # NEW: Actually translated files
        self._current_file_segments_total = 0  # NEW
        self._current_file_segments_done = 0  # NEW

        self._segments_total = 0
        self._segments_done = 0
        self._segments_failed = 0

        self._batches_total = 0
        self._batches_done = 0
        self._current_batch_size = 0
        self._batch_segments_processed = 0  # D1: Track segments processed via batches

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
        self._token_count_method = "estimated"  # Track token counting method

        # Errors
        self._error_count = 0
        self._last_error = ""
        self._last_failed_file = ""
        self._errors_by_type: Dict[str, int] = {}

        # Language tracking (NEW)
        self._target_langs: List[str] = []  # All requested target languages
        self._completed_langs: set[str] = set()  # Languages fully completed
        self._skip_reasons_count: Dict[str, int] = {}  # Aggregate skip reasons

        # Timing accumulators for averages (OBS-03: use deque for O(1) eviction)
        self._segment_times: Deque[float] = deque(maxlen=100)
        self._batch_times: Deque[float] = deque(maxlen=50)

        # EMA calculators (adaptive for volatility detection)
        self._segment_rate_ema = AdaptiveEMACalculator(baseline_alpha=ema_alpha)
        self._file_rate_ema = AdaptiveEMACalculator(baseline_alpha=ema_alpha)

        # Background update thread
        self._update_thread: Optional[threading.Thread] = None
        self._stop_event = threading.Event()
        self._running = False

        # NDJSON stream file handle
        self._ndjson_file: Optional[Any] = None

    def start(self, files_total: int = 0, target_langs: Optional[List[str]] = None) -> None:
        """
        Start progress tracking.

        Args:
            files_total: Total number of files to process
            target_langs: List of target language codes to track
        """
        with self._lock:
            self._start_time = time.time()
            self._last_update_time = self._start_time
            self._files_total = files_total
            self._target_langs = target_langs or []
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

        # Final snapshot with batch stats
        snapshot = self.get_snapshot()

        # Load batch stats from file and attach
        batch_stats = _load_batch_stats_summary()
        snapshot.batch_stats = batch_stats

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

            # Get volatility state for ETA confidence
            volatility_state = self._segment_rate_ema.get_volatility_state()
            eta_confidence = "calculating"
            if eta_s is not None:
                if volatility_state["cv"] < 0.15:
                    eta_confidence = "high"
                elif volatility_state["cv"] < 0.30:
                    eta_confidence = "medium"
                else:
                    eta_confidence = "low"

            # Calculate remaining languages
            remaining_langs = [lang for lang in self._target_langs if lang not in self._completed_langs]

            return ProgressSnapshot(
                timestamp=now,
                start_time=self._start_time,
                elapsed_s=elapsed,
                eta_s=eta_s,
                eta_confidence=eta_confidence,
                rate_volatility=volatility_state["cv"],
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
                token_count_method=self._token_count_method,
                error_count=self._error_count,
                last_error=self._last_error,
                last_failed_file=self._last_failed_file,
                errors_by_type=dict(self._errors_by_type),
                percent_complete_files=pct_files,
                percent_complete_segments=pct_segs,
                # NEW language tracking fields
                target_langs=list(self._target_langs),
                completed_langs=list(self._completed_langs),
                remaining_langs=remaining_langs,
                langs_translated_count=len(self._completed_langs),
                langs_skipped_count=len(self._target_langs) - len(self._completed_langs) if self._target_langs else 0,
                skip_reasons=dict(self._skip_reasons_count),
                # NEW: Separate translated vs skipped tracking
                files_translated=self._files_translated,
                files_processed=self._files_done + self._files_skipped + self._files_failed,
                # NEW: Current file segment tracking
                current_file_segments_total=self._current_file_segments_total,
                current_file_segments_done=self._current_file_segments_done,
                # NEW: For rate suppression logic
                sample_count=len(self._segment_times),
                # batch_stats will be added in stop() method
            )

    def _calculate_eta(self) -> Optional[float]:
        """Calculate ETA with volatility-based confidence adjustment."""
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

        # Base ETA calculation
        base_eta = remaining_segments / rate

        # Check volatility state
        volatility = self._segment_rate_ema.get_volatility_state()

        # If volatile, apply confidence margin (20% pessimistic adjustment)
        if volatility["is_volatile"]:
            confidence_margin = 1.2
            return base_eta * confidence_margin

        return base_eta

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
        """
        Mark file processing started.

        Note: segment_count is used only for current file tracking (progress detail).
        The total segment count should be set upfront via set_totals() after pre-parsing.
        """
        with self._lock:
            self._current_file = os.path.basename(file_path)
            self._current_file_segments_total = segment_count
            self._current_file_segments_done = 0  # Reset for new file
            # NOTE: We no longer increment _segments_total here, as it's set upfront via set_totals()
            # after pre-parsing all files in _discover_all_segments()
            self._last_file_time = time.time()

        if not self.metrics_only:
            logger.debug(f"Processing: {self._current_file}")

    def file_completed(self, success: bool = True, has_new_translations: bool = True) -> None:
        """
        Mark current file completed.

        Args:
            success: True if file processed successfully, False if failed
            has_new_translations: True if at least one language was newly translated (not skipped)
        """
        now = time.time()
        with self._lock:
            if success:
                self._files_done += 1
                if has_new_translations:  # NEW
                    self._files_translated += 1  # NEW
            else:
                self._files_failed += 1
                self._last_failed_file = self._current_file

            # NEW: Reset current file tracking
            self._current_file_segments_total = 0
            self._current_file_segments_done = 0

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
            self._current_file_segments_done += count  # NEW

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
        """
        Mark batch completed.

        Args:
            batch_size: Number of segments processed in this batch (D1: used for validation)
        """
        now = time.time()
        with self._lock:
            self._batches_done += 1
            # D1: Track total segments processed via batch translation
            # This helps validation distinguish between individual cache lookups
            # and batch-processed segments
            self._batch_segments_processed += batch_size

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

    def add_tokens(self, tokens_in: int = 0, tokens_out: int = 0, method: str = "actual") -> None:
        """
        Add token counts.

        Args:
            tokens_in: Input token count
            tokens_out: Output token count
            method: Counting method - "actual" or "estimated"
        """
        with self._lock:
            self._tokens_in += tokens_in
            self._tokens_out += tokens_out
            # Track the method - if any call uses actual, mark as actual
            if method == "actual":
                self._token_count_method = "actual"

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

    def record_skip(self, lang: str, reason: str) -> None:
        """Record a skipped language-file combination with reason."""
        with self._lock:
            self._skip_reasons_count[reason] = self._skip_reasons_count.get(reason, 0) + 1

    def language_completed(self, lang: str) -> None:
        """Mark a language as fully completed across all files."""
        with self._lock:
            self._completed_langs.add(lang)

    def language_started(self, lang: str) -> None:
        """Mark a language as started (informational only)."""
        # Currently just a placeholder for future use
        pass

    def _format_unified_progress(self, snapshot: ProgressSnapshot) -> str:
        """
        Format unified progress line with all key metrics.

        Format: [STATUS] X% | Files: A/B ([OK]C [->]D [ERR]E) | Segs: F/G @ H/s | Cache: I% | ETA: J
        """
        # Calculate status
        if snapshot.segments_total == 0:
            status = "[INIT]"
            pct = 0.0
        elif snapshot.segments_done >= snapshot.segments_total:
            status = "[DONE]"
            pct = 100.0
        else:
            status = "[RUNNING]"
            pct = snapshot.percent_complete_segments

        # Format file counters with ASCII-safe indicators
        file_parts = []
        if snapshot.files_translated > 0:
            file_parts.append(f"[OK]{snapshot.files_translated}")
        if snapshot.current_file:
            file_parts.append("[->]1")
        if snapshot.files_failed > 0:
            file_parts.append(f"[ERR]{snapshot.files_failed}")
        if snapshot.files_skipped > 0:
            file_parts.append(f"[SKIP]{snapshot.files_skipped}")

        file_status = " ".join(file_parts) if file_parts else "[OK]0"

        # Format rate (suppress if not meaningful)
        if snapshot.sample_count < 5 or snapshot.segments_per_sec_rolling < 0.5:
            rate_str = "calculating..."
        else:
            rate_str = f"{snapshot.segments_per_sec_rolling:.1f}/s"

        # Build main line
        line = (
            f"{status} {pct:.0f}% | "
            f"Files: {snapshot.files_done}/{snapshot.files_total} ({file_status}) | "
            f"Segs: {snapshot.segments_done:,}/{snapshot.segments_total:,} @ {rate_str} | "
            f"Cache: {snapshot.cache_hit_rate*100:.0f}% | "
            f"ETA: {snapshot._format_eta()}"
        )

        # Add current file detail if present
        if snapshot.current_file and snapshot.current_file_segments_total > 0:
            file_pct = (snapshot.current_file_segments_done / snapshot.current_file_segments_total * 100) if snapshot.current_file_segments_total > 0 else 0
            line += (
                f"\n          Current: {snapshot.current_file} "
                f"(segment {snapshot.current_file_segments_done}/{snapshot.current_file_segments_total}, {file_pct:.0f}%)"
            )

        return line

    def _should_emit_progress(self, snapshot: ProgressSnapshot) -> bool:
        """
        Check if progress has changed significantly (avoid duplicate logs).

        Emits if:
        - Percent changed by >= 1%, OR
        - Files changed, OR
        - Segments changed by >= 10
        """
        if not hasattr(self, '_last_snapshot_for_dedup'):
            self._last_snapshot_for_dedup = None

        last = self._last_snapshot_for_dedup
        if last is None:
            self._last_snapshot_for_dedup = snapshot
            return True

        # Check significant changes
        percent_changed = abs(snapshot.percent_complete_segments - last.percent_complete_segments) >= 1.0
        files_changed = snapshot.files_done != last.files_done
        segments_changed = abs(snapshot.segments_done - last.segments_done) >= 10

        if percent_changed or files_changed or segments_changed:
            self._last_snapshot_for_dedup = snapshot
            return True

        return False

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
        # Check if should emit (duplicate detection)
        if not self._should_emit_progress(snapshot):
            return  # Skip duplicate

        # Console output
        if self.show_progress:
            progress_line = self._format_unified_progress(snapshot)
            if self.metrics_only:
                # Metrics-only mode: use print
                print(progress_line, flush=True)
            else:
                # Normal mode: use logger
                logger.info(progress_line)

        # File output
        if self.metrics_file:
            self._write_snapshot(snapshot)

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

        # Rule 3: Cache ops should equal segments processed (done + failed), accounting for batches
        # D1: Batch processing skips individual cache lookups, so we adjust the expected count
        # Formula: expected_cache_ops = segments_total - batch_segments_processed
        # This accounts for segments that were translated in batches (no individual lookups)
        cache_total = snapshot.cache_hits + snapshot.cache_misses
        segments_total = snapshot.segments_done + snapshot.segments_failed
        batch_segments = self._batch_segments_processed  # D1: segments processed via batches

        # D1: Calculate expected cache operations (segments not in batches)
        expected_cache_ops = segments_total - batch_segments

        # D1: Add 10% tolerance for batch overhead and timing variations
        tolerance = max(1000, int(segments_total * 0.10))
        segment_gap = abs(cache_total - expected_cache_ops)

        if segment_gap > tolerance and cache_total > 0:
            warnings.append(
                f"SEGMENT GAP: {cache_total} cache ops vs {expected_cache_ops} expected "
                f"(segments: {segments_total}, batched: {batch_segments}, "
                f"batches_done: {snapshot.batches_done}, gap: {segment_gap}, tolerance: {tolerance})"
            )

        # Log all warnings
        for warning in warnings:
            logger.warning(f"METRICS VALIDATION: {warning}")

    def _format_box_line(self, label: str, value: str, width: int = 76) -> str:
        """Format a line within a box with proper padding."""
        content = f"  {label:<12} {value}"
        padding = width - len(content)
        return f"│{content}{' ' * padding}│"

    def _log_final_summary(self, snapshot: ProgressSnapshot) -> None:
        """Log comprehensive final summary when tracking stops."""
        # Validate metrics consistency
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

        # Calculate derived metrics
        files_remaining = snapshot.files_total - snapshot.files_done
        pct_complete = snapshot.percent_complete_files
        langs_remaining = len(snapshot.remaining_langs)
        total_langs = len(snapshot.target_langs)

        box_width = 76  # Wider box for more information

        # ===== HEADER =====
        logger.info("┌" + "─" * box_width + "┐")
        logger.info("│" + " TRANSLATION COMPLETE ".center(box_width) + "│")
        logger.info("├" + "─" * box_width + "┤")

        # ===== OVERALL PROGRESS =====
        logger.info(self._format_box_line("Duration:", duration_str, box_width))

        status = "SUCCESS" if snapshot.error_count == 0 else "COMPLETED WITH ERRORS"

        # Use the dedicated files_translated field from Agent-A's changes
        if snapshot.files_translated == 0 and snapshot.files_skipped > 0:
            # All files were skipped - nothing was actually translated
            status_msg = f"{status} - [OK]0/{snapshot.files_total} files translated ([SKIP]{snapshot.files_skipped} skipped, all up-to-date)"
        elif snapshot.files_skipped > 0:
            # Some files translated, some skipped
            status_msg = f"{status} - [OK]{snapshot.files_translated}/{snapshot.files_total} files translated ([SKIP]{snapshot.files_skipped} skipped, {pct_complete:.1f}%)"
        else:
            # Normal case - all processed files were actually translated
            status_msg = f"{status} - [OK]{snapshot.files_done}/{snapshot.files_total} files translated ({pct_complete:.1f}%)"

        logger.info(self._format_box_line("Status:", status_msg, box_width))

        if files_remaining > 0:
            remaining_detail = f"{files_remaining} files remaining "
            remaining_detail += f"([SKIP]{snapshot.files_skipped} skipped, [ERR]{snapshot.files_failed} failed)"
            logger.info(self._format_box_line("", remaining_detail, box_width))

        # ===== LANGUAGE PROGRESS =====
        if snapshot.target_langs:
            logger.info("├" + "─" * box_width + "┤")
            logger.info("│" + " LANGUAGE PROGRESS ".ljust(box_width) + "│")
            logger.info("├" + "─" * box_width + "┤")

            completed_count = len(snapshot.completed_langs)
            lang_pct = (completed_count / total_langs * 100) if total_langs > 0 else 0

            logger.info(self._format_box_line("Translated:",
                f"{completed_count}/{total_langs} languages ({lang_pct:.1f}%)", box_width))

            if snapshot.completed_langs:
                langs_str = ', '.join(sorted(snapshot.completed_langs))
                logger.info(self._format_box_line("Completed:", langs_str, box_width))

            if snapshot.remaining_langs:
                remaining_str = ', '.join(sorted(snapshot.remaining_langs))
                logger.info(self._format_box_line("Remaining:",
                    f"{remaining_str} ({langs_remaining} languages pending)", box_width))

            # Calculate actual work done (files that were translated, not skipped)
            work_done = snapshot.files_translated * completed_count
            logger.info(self._format_box_line("Work Done:",
                f"{work_done} language outputs created", box_width))

        # ===== FILE PROGRESS =====
        logger.info("├" + "─" * box_width + "┤")
        logger.info("│" + " FILE PROGRESS ".ljust(box_width) + "│")
        logger.info("├" + "─" * box_width + "┤")

        logger.info(self._format_box_line("Total Files:",
            f"{snapshot.files_total} discovered", box_width))

        # Show translated files using dedicated field from Agent-A
        if snapshot.files_translated == 0 and snapshot.files_skipped > 0:
            logger.info(self._format_box_line("Completed:",
                f"[OK]0 files translated ([SKIP]{snapshot.files_skipped} skipped, all up-to-date)", box_width))
        else:
            logger.info(self._format_box_line("Completed:",
                f"[OK]{snapshot.files_done} files ([OK]{snapshot.files_translated} translated, {pct_complete:.1f}%)", box_width))

        if files_remaining > 0:
            logger.info(self._format_box_line("Remaining:",
                f"{files_remaining} files ({100-pct_complete:.1f}%)", box_width))
            if snapshot.files_skipped > 0:
                logger.info(self._format_box_line("  - Skipped:",
                    f"[SKIP]{snapshot.files_skipped} files (outputs already exist)", box_width))
            if snapshot.files_failed > 0:
                logger.info(self._format_box_line("  - Failed:",
                    f"[ERR]{snapshot.files_failed} files (translation errors)", box_width))

        # ===== TRANSLATION PERFORMANCE =====
        logger.info("├" + "─" * box_width + "┤")
        logger.info("│" + " TRANSLATION PERFORMANCE ".ljust(box_width) + "│")
        logger.info("├" + "─" * box_width + "┤")

        # Show segments with accurate wording - when files are skipped, segments aren't "translated"
        if snapshot.files_translated == 0 and snapshot.files_skipped > 0:
            # All files skipped - segments were checked but not translated
            logger.info(self._format_box_line("Segments:",
                f"{snapshot.segments_done:,}/{snapshot.segments_total:,} processed (0 translated, all skipped)",
                box_width))
        else:
            logger.info(self._format_box_line("Segments:",
                f"{snapshot.segments_done:,}/{snapshot.segments_total:,} translated ({snapshot.percent_complete_segments:.1f}%)",
                box_width))

        # Only show throughput if actual translation occurred
        if snapshot.files_translated > 0:
            logger.info(self._format_box_line("Throughput:",
                f"{snapshot.segments_per_sec_lifetime:.1f} seg/s, {snapshot.files_per_min:.1f} files/min",
                box_width))

        if snapshot.avg_segment_ms > 0 or snapshot.avg_batch_s > 0:
            logger.info(self._format_box_line("Avg Latency:",
                f"{snapshot.avg_segment_ms:.1f} ms/segment, {snapshot.avg_batch_s:.1f}s/batch",
                box_width))

        # ===== CACHE EFFECTIVENESS (MULTI-LAYER) =====
        logger.info("├" + "─" * box_width + "┤")
        logger.info("│" + " CACHE EFFECTIVENESS (Multi-Layer) ".ljust(box_width) + "│")
        logger.info("├" + "─" * box_width + "┤")

        total_lookups = snapshot.cache_hits + snapshot.cache_misses
        logger.info(self._format_box_line("Total Hits:",
            f"{snapshot.cache_hits:,}/{total_lookups:,} ({snapshot.cache_hit_rate*100:.1f}% overall hit rate)",
            box_width))

        # L1/L2/L3 breakdown
        if total_lookups > 0:
            l1_pct = (snapshot.l1_hits / total_lookups * 100)
            l2_pct = (snapshot.l2_hits / total_lookups * 100)
            l3_pct = (snapshot.l3_hits / total_lookups * 100)
            miss_pct = (snapshot.cache_misses / total_lookups * 100)

            logger.info(self._format_box_line("L1 (Memory):",
                f"{snapshot.l1_hits:,} hits ({l1_pct:.1f}%) - Fast in-memory cache",
                box_width))
            logger.info(self._format_box_line("L2 (Disk):",
                f"{snapshot.l2_hits:,} hits ({l2_pct:.1f}%) - Persistent TM database",
                box_width))
            logger.info(self._format_box_line("L3 (Fuzzy):",
                f"{snapshot.l3_hits:,} hits ({l3_pct:.1f}%) - Semantic similarity",
                box_width))
            logger.info(self._format_box_line("Misses:",
                f"{snapshot.cache_misses:,} ({miss_pct:.1f}%) - New translations",
                box_width))

        # ===== SKIP SUMMARY =====
        if snapshot.skip_reasons:
            logger.info("├" + "─" * box_width + "┤")
            logger.info("│" + " SKIP SUMMARY ".ljust(box_width) + "│")
            logger.info("├" + "─" * box_width + "┤")

            total_skips = sum(snapshot.skip_reasons.values())
            logger.info(self._format_box_line("Total Skips:",
                f"{total_skips} language-file combinations skipped", box_width))

            logger.info(self._format_box_line("Reasons:", "", box_width))

            # Sort by count descending
            sorted_reasons = sorted(snapshot.skip_reasons.items(),
                                   key=lambda x: x[1], reverse=True)

            # Map skip reasons to clean labels
            reason_labels = {
                'output_exists': 'Output files already present',
                'content_unchanged': 'Content hash matches',
                'force_skip_config': 'Configured to skip',
                # Handle compound reasons from engine (e.g., "content unchanged: mtime unchanged, hash assumed valid")
                'content unchanged: mtime unchanged, hash assumed valid': 'Content unchanged (mtime check)',
                'content unchanged: content unchanged (hash match': 'Content unchanged (hash verified)',
                'output is newer than source (mtime)': 'Output is newer than source',
            }

            for reason, count in sorted_reasons:
                pct = (count / total_skips * 100) if total_skips > 0 else 0

                # Try to find a clean label for this reason
                label = None
                for reason_key, reason_label in reason_labels.items():
                    if reason.startswith(reason_key):
                        label = reason_label
                        break

                # Fallback: clean up the reason string
                if not label:
                    # Remove common prefixes and clean up
                    label = reason.replace('content unchanged:', '').replace('_', ' ')
                    label = label.strip().capitalize()
                    if not label:
                        label = reason.replace('_', ' ').title()

                # Format: just show the clean label and count
                logger.info(self._format_box_line(f"  {label}:",
                    f"{count:,} ({pct:.1f}%)", box_width))

        # ===== ADAPTIVE BATCH TRANSLATION =====
        if snapshot.batch_stats and snapshot.batch_stats.get('per_language'):
            logger.info("├" + "─" * box_width + "┤")
            logger.info("│" + " ADAPTIVE BATCH TRANSLATION ".ljust(box_width) + "│")
            logger.info("├" + "─" * box_width + "┤")

            logger.info(self._format_box_line("Batch Calls:",
                f"{snapshot.batches_done:,} total batches processed", box_width))

            total_adaptations = snapshot.batch_stats.get('total_adaptations', 0)
            logger.info(self._format_box_line("Adaptations:",
                f"{total_adaptations} batch size changes made", box_width))

            logger.info(self._format_box_line("", "", box_width))
            logger.info(self._format_box_line("Per-Language Batch Sizes:", "", box_width))

            for lang in sorted(snapshot.batch_stats['per_language'].keys()):
                data = snapshot.batch_stats['per_language'][lang]
                current = data['current']
                baseline = data['baseline']
                adaptations = data['adaptations']

                if adaptations == 0:
                    msg = f"{lang}: {current} (baseline: {baseline}) - No adaptation"
                else:
                    change_type = "Reduced" if current < baseline else "Increased"
                    msg = f"{lang}: {current} (baseline: {baseline}) - {change_type} {adaptations}x"

                logger.info(self._format_box_line(f"  {msg}", "", box_width))

            # Fallback stats
            fallback_reasons = snapshot.batch_stats.get('fallback_reasons', {})
            if fallback_reasons:
                logger.info(self._format_box_line("", "", box_width))
                logger.info(self._format_box_line("Fallback Stats:", "", box_width))

                total_fallbacks = snapshot.batch_stats.get('total_fallbacks', 0)
                total_batches = snapshot.batches_done
                fallback_pct = (total_fallbacks / total_batches * 100) if total_batches > 0 else 0

                logger.info(self._format_box_line("  Total:",
                    f"{total_fallbacks:,} fallbacks ({fallback_pct:.1f}% of batches)", box_width))

                for reason, count in sorted(fallback_reasons.items(),
                                           key=lambda x: x[1], reverse=True):
                    reason_pct = (count / total_fallbacks * 100) if total_fallbacks > 0 else 0
                    reason_label = reason.replace('_', ' ').title()
                    logger.info(self._format_box_line(f"    {reason_label}:",
                        f"{count:,} ({reason_pct:.1f}%)", box_width))

        # ===== ERROR BREAKDOWN =====
        if snapshot.error_count > 0:
            logger.info("├" + "─" * box_width + "┤")
            logger.info("│" + " ERROR BREAKDOWN ".ljust(box_width) + "│")
            logger.info("├" + "─" * box_width + "┤")

            logger.warning(self._format_box_line("Total Errors:",
                f"{snapshot.error_count:,} errors encountered", box_width))

            if snapshot.errors_by_type:
                logger.info(self._format_box_line("", "", box_width))
                logger.info(self._format_box_line("By Type:", "", box_width))

                # Sort by count descending
                sorted_errors = sorted(snapshot.errors_by_type.items(),
                                      key=lambda x: x[1], reverse=True)

                error_labels = {
                    'translation_error': 'Model failures',
                    'validation_error': 'Validation rejections',
                    'file_write_error': 'Disk write failures',
                    'parse_error': 'Markdown parsing issues'
                }

                for error_type, count in sorted_errors:
                    pct = (count / snapshot.error_count * 100)
                    label = error_labels.get(error_type, error_type.replace('_', ' ').title())
                    logger.warning(self._format_box_line(f"  {error_type}:",
                        f"{count:,} ({pct:.1f}%) - {label}", box_width))

            if snapshot.last_failed_file:
                logger.info(self._format_box_line("", "", box_width))
                last_error_short = snapshot.last_error[:50] if snapshot.last_error else "unknown"
                logger.warning(self._format_box_line("Last Error:",
                    f"{last_error_short}... at {snapshot.last_failed_file}", box_width))

        # ===== TOKEN USAGE =====
        if snapshot.tokens_in > 0:
            logger.info("├" + "─" * box_width + "┤")
            logger.info("│" + " TOKEN USAGE ".ljust(box_width) + "│")
            logger.info("├" + "─" * box_width + "┤")

            logger.info(self._format_box_line("Input:",
                f"{snapshot.tokens_in:,} tokens sent to model", box_width))
            logger.info(self._format_box_line("Output:",
                f"{snapshot.tokens_out:,} tokens generated", box_width))

            # Calculate token savings from cache
            if snapshot.cache_hits > 0 and snapshot.segments_done > 0:
                avg_tokens_per_seg = snapshot.tokens_in / snapshot.segments_done
                tokens_saved = int(snapshot.cache_hits * avg_tokens_per_seg)
                total_tokens = snapshot.tokens_in + tokens_saved
                cache_savings_pct = (tokens_saved / total_tokens * 100) if total_tokens > 0 else 0

                logger.info(self._format_box_line("Cached:",
                    f"{tokens_saved:,} tokens saved via cache ({cache_savings_pct:.1f}% savings)",
                    box_width))
                logger.info(self._format_box_line("Total:",
                    f"{total_tokens:,} tokens processed", box_width))

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


def _load_batch_stats_summary() -> Dict[str, Any]:
    """
    Load batch statistics for final summary.

    Returns:
        Dictionary with per-language batch sizes and adaptation summaries
    """
    batch_file = Path('.translation_progress/batch_stats.json')
    if not batch_file.exists():
        return {}

    try:
        import json
        with open(batch_file, 'r', encoding='utf-8') as f:
            data = json.load(f)

        summary = {
            'per_language': {},
            'total_adaptations': 0,
            'total_fallbacks': 0,
            'fallback_reasons': {}
        }

        for lang, lang_data in data.get('languages', {}).items():
            current = lang_data.get('current_batch_size', 0)
            baseline = lang_data.get('baseline_batch_size', 0)
            adaptation_history = lang_data.get('adaptation_history', [])
            adaptations = len(adaptation_history)

            summary['per_language'][lang] = {
                'current': current,
                'baseline': baseline,
                'adaptations': adaptations
            }
            summary['total_adaptations'] += adaptations

            # Aggregate fallback stats
            stats = lang_data.get('rolling_stats', {})
            fallback_batches = stats.get('fallback_batches', 0)
            summary['total_fallbacks'] += fallback_batches

            # Aggregate fallback reasons
            for reason_key in ['language_purity_failures', 'mapping_failures', 'exception_failures']:
                count = stats.get(reason_key, 0)
                if count > 0:
                    reason_name = reason_key.replace('_failures', '')
                    summary['fallback_reasons'][reason_name] = \
                        summary['fallback_reasons'].get(reason_name, 0) + count

        return summary
    except Exception as e:
        logger.warning(f"Failed to load batch stats for summary: {e}")
        return {}


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
