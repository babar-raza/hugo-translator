"""
Metrics Collection for Translation System.

Provides Prometheus-compatible metrics for monitoring translation
operations, TM performance, and system health.
"""

import json
import logging
import os
import threading
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class Metric:
    """Base metric class."""

    name: str
    help_text: str
    labels: dict[str, str] = field(default_factory=dict)


@dataclass
class Counter(Metric):
    """Counter metric that only increases."""

    value: float = 0.0

    def increment(self, amount: float = 1.0) -> None:
        """Increment counter by amount."""
        self.value += amount

    def get(self) -> float:
        """Get current value."""
        return self.value


@dataclass
class Gauge(Metric):
    """Gauge metric that can go up or down."""

    value: float = 0.0

    def set(self, value: float) -> None:
        """Set gauge to value."""
        self.value = value

    def increment(self, amount: float = 1.0) -> None:
        """Increment gauge by amount."""
        self.value += amount

    def decrement(self, amount: float = 1.0) -> None:
        """Decrement gauge by amount."""
        self.value -= amount

    def get(self) -> float:
        """Get current value."""
        return self.value


@dataclass
class Histogram(Metric):
    """Histogram metric for tracking distributions."""

    buckets: list[float] = field(default_factory=lambda: [0.01, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0, 60.0])
    values: list[float] = field(default_factory=list)
    bucket_counts: dict[float, int] = field(default_factory=dict)
    sum: float = 0.0
    count: int = 0

    def __post_init__(self) -> None:
        """Initialize bucket counts."""
        for bucket in self.buckets:
            self.bucket_counts[bucket] = 0

    def observe(self, value: float) -> None:
        """Record an observation."""
        self.values.append(value)
        self.sum += value
        self.count += 1

        # Update bucket counts
        for bucket in self.buckets:
            if value <= bucket:
                self.bucket_counts[bucket] += 1

    def get_stats(self) -> dict[str, Any]:
        """Get histogram statistics."""
        if not self.values:
            return {
                "count": 0,
                "sum": 0.0,
                "mean": 0.0,
                "min": 0.0,
                "max": 0.0,
            }

        return {
            "count": self.count,
            "sum": self.sum,
            "mean": self.sum / self.count if self.count > 0 else 0.0,
            "min": min(self.values),
            "max": max(self.values),
            "buckets": self.bucket_counts,
        }


class MetricsCollector:
    """
    Collects and manages metrics for the translation system.

    Provides Prometheus-compatible metrics that can be exported
    for monitoring and alerting.
    """

    def __init__(
        self,
        worker_id: str | None = None,
        push_interval: int = 60,
        enable_push: bool = False,
        pushgateway_url: str | None = None,
    ):
        """
        Initialize metrics collector.

        Args:
            worker_id: Unique worker identifier
            push_interval: Seconds between metric pushes
            enable_push: Whether to push metrics to Pushgateway
            pushgateway_url: URL of Prometheus Pushgateway
        """
        self.worker_id = worker_id or "default"
        self.push_interval = push_interval
        self.enable_push = enable_push
        self.pushgateway_url = pushgateway_url

        # Metric storage
        self._counters: dict[str, Counter] = {}
        self._gauges: dict[str, Gauge] = {}
        self._histograms: dict[str, Histogram] = {}
        self._lock = threading.Lock()

        # Push thread
        self._push_thread: threading.Thread | None = None
        self._stop_push = threading.Event()

        # Initialize core metrics
        self._init_core_metrics()

        # Start push thread if enabled
        if self.enable_push and self.pushgateway_url:
            self.start_push()

    def _init_core_metrics(self) -> None:
        """Initialize core translation metrics."""

        # Translation counters
        self.register_counter(
            "translations_total",
            "Total number of translation operations",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "translations_success",
            "Number of successful translations",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "translations_failed",
            "Number of failed translations",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "translation_errors_total",
            "Total translation errors by type",
            {"worker_id": self.worker_id},
        )

        # TM counters
        self.register_counter(
            "tm_lookups_total",
            "Total TM lookups",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "tm_hits_l1",
            "L1 cache hits",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "tm_hits_l2",
            "L2 exact match hits",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "tm_hits_l3",
            "L3 semantic match hits",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "tm_misses",
            "TM misses (model translation required)",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "tm_writes_total",
            "Total TM write operations",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "tm_errors_total",
            "Total TM errors",
            {"worker_id": self.worker_id},
        )

        # Model counters
        self.register_counter(
            "model_translations_total",
            "Total model translation calls",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "model_load_count",
            "Number of times models were loaded",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "model_errors_total",
            "Total model errors",
            {"worker_id": self.worker_id},
        )

        # Validation counters
        self.register_counter(
            "validation_checks_total",
            "Total validation checks performed",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "validation_failures_total",
            "Total validation failures",
            {"worker_id": self.worker_id},
        )

        # Gauges
        self.register_gauge(
            "queue_depth",
            "Current job queue depth",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "active_jobs",
            "Number of active translation jobs",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "tm_cache_size",
            "Current L1 cache size",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "tm_l2_size_bytes",
            "L2 TM database size in bytes",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "tm_l3_index_size",
            "L3 TM index entry count",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "model_memory_usage_bytes",
            "Model memory usage in bytes",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "disk_usage_percent",
            "Disk usage percentage",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "memory_usage_percent",
            "Memory usage percentage",
            {"worker_id": self.worker_id},
        )

        # Retry tracking (BM-08)
        self.register_counter(
            "retry_count_total",
            "Total retry attempts by error type",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "warmup_iterations",
            "Number of warmup iterations performed",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "actual_iterations",
            "Number of actual iterations performed",
            {"worker_id": self.worker_id},
        )

        # Histograms
        self.register_histogram(
            "translation_duration_seconds",
            "Translation operation duration",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "tm_lookup_duration_seconds",
            "TM lookup duration",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "model_translation_duration_seconds",
            "Model translation duration",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "segment_length",
            "Translation segment length in characters",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "batch_size",
            "Translation batch sizes",
            {"worker_id": self.worker_id},
        )

        # BM-08: Extended metrics for better performance visibility
        self.register_histogram(
            "model_load_duration_seconds",
            "Time to load model into memory",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "tokenization_duration_seconds",
            "Tokenization duration by language pair",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "l3_encoding_duration_seconds",
            "L3 semantic encoding duration (separate from lookup)",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "l3_lookup_duration_seconds",
            "L3 pure lookup duration (without encoding)",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "retry_duration_seconds",
            "Time lost to retry attempts",
            {"worker_id": self.worker_id},
        )
        self.register_histogram(
            "batch_preparation_duration_seconds",
            "Batch preparation overhead before translation",
            {"worker_id": self.worker_id},
        )

        # CHH-04: Content hash tracking metrics
        self.register_histogram(
            "content_hash_compute_duration_seconds",
            "Duration to compute file content hash (MD5/SHA256)",
            {"worker_id": self.worker_id},
            buckets=[0.001, 0.005, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0],
        )
        self.register_histogram(
            "metadata_save_duration_seconds",
            "Duration to save metadata file (including lock acquisition)",
            {"worker_id": self.worker_id},
            buckets=[0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0],
        )
        self.register_histogram(
            "metadata_lock_acquire_duration_seconds",
            "Duration to acquire Redis distributed lock for metadata",
            {"worker_id": self.worker_id},
            buckets=[0.001, 0.01, 0.05, 0.1, 0.5, 1.0, 5.0, 10.0, 30.0],
        )
        self.register_counter(
            "content_hash_cache_hits",
            "Number of content hash cache hits (mtime unchanged)",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "content_hash_cache_misses",
            "Number of content hash cache misses (mtime changed, recompute hash)",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "content_hash_changes_detected",
            "Number of file changes detected via content hash",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "content_hash_no_change",
            "Number of files with no content change detected",
            {"worker_id": self.worker_id},
        )
        self.register_counter(
            "metadata_lock_timeouts",
            "Number of Redis lock timeouts (fell back to direct write)",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "metadata_file_size_bytes",
            "Current metadata file size in bytes",
            {"worker_id": self.worker_id},
        )
        self.register_gauge(
            "metadata_tracked_files",
            "Number of source files tracked in metadata",
            {"worker_id": self.worker_id},
        )

    def register_counter(
        self,
        name: str,
        help_text: str,
        labels: dict[str, str] | None = None,
    ) -> Counter:
        """Register a new counter metric."""
        with self._lock:
            key = self._make_key(name, labels or {})
            if key not in self._counters:
                self._counters[key] = Counter(
                    name=name,
                    help_text=help_text,
                    labels=labels or {},
                )
            return self._counters[key]

    def register_gauge(
        self,
        name: str,
        help_text: str,
        labels: dict[str, str] | None = None,
    ) -> Gauge:
        """Register a new gauge metric."""
        with self._lock:
            key = self._make_key(name, labels or {})
            if key not in self._gauges:
                self._gauges[key] = Gauge(
                    name=name,
                    help_text=help_text,
                    labels=labels or {},
                )
            return self._gauges[key]

    def register_histogram(
        self,
        name: str,
        help_text: str,
        labels: dict[str, str] | None = None,
        buckets: list[float] | None = None,
    ) -> Histogram:
        """Register a new histogram metric."""
        with self._lock:
            key = self._make_key(name, labels or {})
            if key not in self._histograms:
                hist = Histogram(
                    name=name,
                    help_text=help_text,
                    labels=labels or {},
                )
                if buckets:
                    hist.buckets = buckets
                    hist.__post_init__()
                self._histograms[key] = hist
            return self._histograms[key]

    def increment(
        self,
        name: str,
        amount: float = 1.0,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Increment a counter."""
        labels_with_worker = {"worker_id": self.worker_id}
        if labels:
            labels_with_worker.update(labels)
        key = self._make_key(name, labels_with_worker)

        with self._lock:
            if key in self._counters:
                self._counters[key].increment(amount)
            else:
                # Try to find counter without extra labels (just worker_id)
                default_key = self._make_key(name, {"worker_id": self.worker_id})
                if default_key in self._counters:
                    self._counters[default_key].increment(amount)
                else:
                    logger.warning(f"Counter {name} not registered")

    def set_gauge(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Set a gauge value."""
        labels_with_worker = {"worker_id": self.worker_id}
        if labels:
            labels_with_worker.update(labels)
        key = self._make_key(name, labels_with_worker)

        with self._lock:
            if key in self._gauges:
                self._gauges[key].set(value)
            else:
                # Try to find gauge without extra labels (just worker_id)
                default_key = self._make_key(name, {"worker_id": self.worker_id})
                if default_key in self._gauges:
                    self._gauges[default_key].set(value)
                else:
                    logger.warning(f"Gauge {name} not registered")

    def observe(
        self,
        name: str,
        value: float,
        labels: dict[str, str] | None = None,
    ) -> None:
        """Record an observation in a histogram."""
        labels_with_worker = {"worker_id": self.worker_id}
        if labels:
            labels_with_worker.update(labels)
        key = self._make_key(name, labels_with_worker)

        with self._lock:
            if key in self._histograms:
                self._histograms[key].observe(value)
            else:
                # Try to find histogram without extra labels (just worker_id)
                default_key = self._make_key(name, {"worker_id": self.worker_id})
                if default_key in self._histograms:
                    self._histograms[default_key].observe(value)
                else:
                    logger.warning(f"Histogram {name} not registered")

    def get_all(self) -> dict[str, Any]:
        """Get all metrics."""
        with self._lock:
            metrics = {}

            # Counters
            for key, counter in self._counters.items():
                metrics[key] = {
                    "type": "counter",
                    "name": counter.name,
                    "help": counter.help_text,
                    "labels": counter.labels,
                    "value": counter.get(),
                }

            # Gauges
            for key, gauge in self._gauges.items():
                metrics[key] = {
                    "type": "gauge",
                    "name": gauge.name,
                    "help": gauge.help_text,
                    "labels": gauge.labels,
                    "value": gauge.get(),
                }

            # Histograms
            for key, histogram in self._histograms.items():
                metrics[key] = {
                    "type": "histogram",
                    "name": histogram.name,
                    "help": histogram.help_text,
                    "labels": histogram.labels,
                    "stats": histogram.get_stats(),
                }

            return metrics

    def export_prometheus(self) -> str:
        """
        Export metrics in Prometheus text format.

        Returns:
            Prometheus-formatted metrics string
        """
        lines = []

        with self._lock:
            # Export counters
            for counter in self._counters.values():
                lines.append(f"# HELP {counter.name} {counter.help_text}")
                lines.append(f"# TYPE {counter.name} counter")
                labels_str = self._format_labels(counter.labels)
                lines.append(f"{counter.name}{labels_str} {counter.get()}")

            # Export gauges
            for gauge in self._gauges.values():
                lines.append(f"# HELP {gauge.name} {gauge.help_text}")
                lines.append(f"# TYPE {gauge.name} gauge")
                labels_str = self._format_labels(gauge.labels)
                lines.append(f"{gauge.name}{labels_str} {gauge.get()}")

            # Export histograms
            for histogram in self._histograms.values():
                lines.append(f"# HELP {histogram.name} {histogram.help_text}")
                lines.append(f"# TYPE {histogram.name} histogram")
                labels_str = self._format_labels(histogram.labels)

                # Export bucket counts
                for bucket, count in histogram.bucket_counts.items():
                    bucket_labels = {**histogram.labels, "le": str(bucket)}
                    bucket_str = self._format_labels(bucket_labels)
                    lines.append(f"{histogram.name}_bucket{bucket_str} {count}")

                # Export sum and count
                lines.append(f"{histogram.name}_sum{labels_str} {histogram.sum}")
                lines.append(f"{histogram.name}_count{labels_str} {histogram.count}")

        return "\n".join(lines) + "\n"

    def push_metrics(self) -> None:
        """Push metrics to Prometheus Pushgateway."""
        if not self.pushgateway_url:
            logger.warning("No pushgateway URL configured")
            return

        try:
            import requests

            metrics_text = self.export_prometheus()
            url = f"{self.pushgateway_url}/metrics/job/translation_worker/instance/{self.worker_id}"

            response = requests.post(url, data=metrics_text, headers={"Content-Type": "text/plain"})
            response.raise_for_status()

            logger.debug(f"Pushed metrics to {url}")

        except Exception as e:
            logger.error(f"Failed to push metrics: {e}")

    def start_push(self) -> None:
        """Start periodic metric pushing."""
        if self._push_thread and self._push_thread.is_alive():
            logger.warning("Push thread already running")
            return

        self._stop_push.clear()
        self._push_thread = threading.Thread(target=self._push_loop, daemon=True)
        self._push_thread.start()
        logger.info(f"Started metrics push thread (interval: {self.push_interval}s)")

    def stop(self) -> None:
        """Stop metric pushing."""
        if self._push_thread and self._push_thread.is_alive():
            self._stop_push.set()
            self._push_thread.join(timeout=5.0)
            logger.info("Stopped metrics push thread")

    def _push_loop(self) -> None:
        """Periodic push loop."""
        while not self._stop_push.is_set():
            try:
                self.push_metrics()
            except Exception as e:
                logger.error(f"Error in push loop: {e}")

            self._stop_push.wait(self.push_interval)

    @staticmethod
    def _make_key(name: str, labels: dict[str, str]) -> str:
        """Create unique key for metric with labels."""
        label_items = sorted(labels.items())
        label_str = ",".join(f"{k}={v}" for k, v in label_items)
        return f"{name}{{{label_str}}}" if label_str else name

    @staticmethod
    def _format_labels(labels: dict[str, str]) -> str:
        """Format labels for Prometheus export."""
        if not labels:
            return ""
        label_items = sorted(labels.items())
        label_str = ",".join(f'{k}="{v}"' for k, v in label_items)
        return f"{{{label_str}}}"

    def get_tm_hit_rate(self) -> float:
        """
        Calculate TM hit rate (percentage of lookups that hit L1/L2/L3).

        Returns:
            Hit rate between 0.0 and 1.0, or 0.0 if no lookups
        """
        with self._lock:
            # Find the TM lookup metrics
            lookups_key = self._make_key("tm_lookups_total", {"worker_id": self.worker_id})
            l1_hits_key = self._make_key("tm_hits_l1", {"worker_id": self.worker_id})
            l2_hits_key = self._make_key("tm_hits_l2", {"worker_id": self.worker_id})
            l3_hits_key = self._make_key("tm_hits_l3", {"worker_id": self.worker_id})

            total_lookups = self._counters.get(lookups_key, Counter("", "")).get()
            if total_lookups == 0:
                return 0.0

            l1_hits = self._counters.get(l1_hits_key, Counter("", "")).get()
            l2_hits = self._counters.get(l2_hits_key, Counter("", "")).get()
            l3_hits = self._counters.get(l3_hits_key, Counter("", "")).get()

            total_hits = l1_hits + l2_hits + l3_hits
            return total_hits / total_lookups

    def get_error_rate(self) -> float:
        """
        Calculate overall error rate.

        Returns:
            Error rate between 0.0 and 1.0, or 0.0 if no operations
        """
        with self._lock:
            total_key = self._make_key("translations_total", {"worker_id": self.worker_id})
            failed_key = self._make_key("translations_failed", {"worker_id": self.worker_id})

            total = self._counters.get(total_key, Counter("", "")).get()
            if total == 0:
                return 0.0

            failed = self._counters.get(failed_key, Counter("", "")).get()
            return failed / total

    def get_stats_summary(self) -> dict[str, Any]:
        """
        Get a summary of key metrics and statistics.

        Returns:
            Dictionary containing summary statistics
        """
        with self._lock:
            # Get core counters
            translations_total = self._counters.get(
                self._make_key("translations_total", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()
            translations_success = self._counters.get(
                self._make_key("translations_success", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()
            translations_failed = self._counters.get(
                self._make_key("translations_failed", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()

            # Get TM counters
            tm_lookups = self._counters.get(
                self._make_key("tm_lookups_total", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()
            tm_l1_hits = self._counters.get(
                self._make_key("tm_hits_l1", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()
            tm_l2_hits = self._counters.get(
                self._make_key("tm_hits_l2", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()
            tm_l3_hits = self._counters.get(
                self._make_key("tm_hits_l3", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()
            tm_misses = self._counters.get(
                self._make_key("tm_misses", {"worker_id": self.worker_id}),
                Counter("", "")
            ).get()

            # Get gauges
            queue_depth = self._gauges.get(
                self._make_key("queue_depth", {"worker_id": self.worker_id}),
                Gauge("", "")
            ).get()
            active_jobs = self._gauges.get(
                self._make_key("active_jobs", {"worker_id": self.worker_id}),
                Gauge("", "")
            ).get()

            # Get histogram stats
            translation_duration_key = self._make_key(
                "translation_duration_seconds", {"worker_id": self.worker_id}
            )
            translation_stats = self._histograms.get(
                translation_duration_key,
                Histogram("", "")
            ).get_stats()

            return {
                "worker_id": self.worker_id,
                "translations": {
                    "total": int(translations_total),
                    "success": int(translations_success),
                    "failed": int(translations_failed),
                    "success_rate": translations_success / translations_total if translations_total > 0 else 0.0,
                },
                "tm": {
                    "lookups": int(tm_lookups),
                    "l1_hits": int(tm_l1_hits),
                    "l2_hits": int(tm_l2_hits),
                    "l3_hits": int(tm_l3_hits),
                    "misses": int(tm_misses),
                    "total_hits": int(tm_l1_hits + tm_l2_hits + tm_l3_hits),
                    "hit_rate": self.get_tm_hit_rate(),
                },
                "queue": {
                    "depth": int(queue_depth),
                    "active_jobs": int(active_jobs),
                },
                "performance": {
                    "translation_duration": translation_stats,
                },
            }


# Global metrics instance
_global_metrics: MetricsCollector | None = None


def get_metrics() -> MetricsCollector:
    """Get or create global metrics collector."""
    global _global_metrics
    if _global_metrics is None:
        _global_metrics = MetricsCollector()
    return _global_metrics


def init_metrics(
    worker_id: str | None = None,
    push_interval: int = 60,
    enable_push: bool = False,
    pushgateway_url: str | None = None,
) -> MetricsCollector:
    """
    Initialize global metrics collector.

    Args:
        worker_id: Unique worker identifier
        push_interval: Seconds between metric pushes
        enable_push: Whether to push metrics to Pushgateway
        pushgateway_url: URL of Prometheus Pushgateway

    Returns:
        Initialized metrics collector
    """
    global _global_metrics
    _global_metrics = MetricsCollector(
        worker_id=worker_id,
        push_interval=push_interval,
        enable_push=enable_push,
        pushgateway_url=pushgateway_url,
    )
    return _global_metrics


def record_coverage_snapshot(
    site_id: str,
    target_langs: list[str],
    total_files: int,
    successful_files: int,
    completion_filter_skipped: int,
    coverage_file: Path | None = None,
) -> None:
    """
    WS-COMP-8: Write a per-site translation coverage snapshot to data/metrics/coverage.json.

    The file is a JSON array; each call appends one record so the dashboard can track
    coverage trends over time.  Old entries are kept (max 500 per site×lang pair).

    Args:
        site_id: Site identifier (e.g. "docs.aspose.net")
        target_langs: Target language codes translated in this run
        total_files: Files that were selected for translation (after completion filter)
        successful_files: Files that were successfully translated
        completion_filter_skipped: Files skipped as already up-to-date (completion filter)
        coverage_file: Override path for the JSON file (default: data/metrics/coverage.json)
    """
    if coverage_file is None:
        coverage_file = Path(os.getcwd()) / "data" / "metrics" / "coverage.json"

    try:
        coverage_file.parent.mkdir(parents=True, exist_ok=True)

        # Load existing records
        records: list[dict] = []
        if coverage_file.exists():
            try:
                with open(coverage_file, encoding="utf-8") as fh:
                    records = json.load(fh)
                if not isinstance(records, list):
                    records = []
            except (json.JSONDecodeError, OSError):
                records = []

        timestamp = datetime.now(tz=timezone.utc).isoformat()

        new_entry: dict[str, Any] = {
            "timestamp": timestamp,
            "site_id": site_id,
            "target_langs": target_langs,
            "total_files": total_files,
            "successful_files": successful_files,
            "completion_filter_skipped": completion_filter_skipped,
            # Effective coverage denominator = files needing work + files already current
            "denominator": total_files + completion_filter_skipped,
            # coverage_pct = successful / (total_needing_work + already_current)
            "coverage_pct": round(
                successful_files / (total_files + completion_filter_skipped) * 100, 1
            ) if (total_files + completion_filter_skipped) > 0 else None,
        }
        records.append(new_entry)

        # Prune to keep only last 500 records to prevent unbounded growth
        if len(records) > 500:
            records = records[-500:]

        with open(coverage_file, "w", encoding="utf-8") as fh:
            json.dump(records, fh, indent=2)

        logger.debug(
            "Coverage snapshot written: site=%s langs=%d total=%d succeeded=%d skipped=%d coverage=%.1f%%",
            site_id, len(target_langs), total_files, successful_files,
            completion_filter_skipped, new_entry.get("coverage_pct") or 0.0,
        )
    except Exception as exc:
        logger.warning("Failed to write coverage snapshot for %s: %s", site_id, exc)
